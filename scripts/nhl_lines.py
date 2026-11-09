#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL lines: forward trios and defence pairs at 5-on-5 from the NHL's shift charts, with goals and expected goals
while together (data/nhl_lines.json for the board's lines tab), and the line inputs tested on the game model.

    python3 scripts/nhl_lines.py                 # the current season's lines tab (static/data/lines/nhl.json)
    python3 scripts/nhl_lines.py --pull S [S..]  # cache past seasons' shifts (scripts/.cache/nhl/shifts/<S>.json.gz)
    python3 scripts/nhl_lines.py --check S       # 5v5 build against the box score's ice time
    python3 scripts/nhl_lines_research.py        # continuity, on/off and power-play unit inputs on the game model
                                                 # (data/nhl_lines_research.json)

Data: shift charts (api.nhle.com/stats/rest/en/shiftcharts; when a game has none, as for most 2026-27 games after
mid-October, the NHL's HTML time-on-ice reports TH/TV, jersey numbers joined to player ids by the game's box score),
the dressed skaters and their positions (stats-API skater game logs, frozen in scripts/data/nhl_lineups.json.gz),
MoneyPuck's shot file (xG per unblocked attempt; shots_<year>.zip).

5-on-5 = both teams with five skaters and a goalie on the ice. A shot or goal at second t counts for the skaters on
the ice over (t-1, t]: a player coming on at t is not credited. Forward trio / defence pair time counts only while a
team has exactly three forwards and two defencemen out.
"""
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nhl_data as D  # noqa: E402

ROOT = os.path.dirname(HERE)
SHD = os.path.join(D.CACHE, 'shifts')
MPD = os.path.join(D.CACHE, 'mpshots')
MPURL = 'https://peter-tanner.com/moneypuck/downloads/shots_{}.zip'
OUT = os.path.join(ROOT, 'static', 'data', 'lines', 'nhl.json')     # lazy-loaded by the lines tab
RES = os.path.join(ROOT, 'data', 'nhl_lines_research.json')


# ---------------------------------------------------------------- shifts
def _clock(s):
    m, x = s.split(':')
    return int(m) * 60 + int(x)


def api_shifts(gid):
    """[[player id, team, period, start s, end s]] from the shift-chart API; None on failure, [] when it has none"""
    url = f'{D.STATS}/shiftcharts?cayenneExp=gameId={gid}'
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': D.UA, 'Accept-Encoding': 'gzip'})
            r = urllib.request.urlopen(req, timeout=60)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            out = []
            for s in json.loads(b).get('data', []):
                if s.get('typeCode') != 517 or not s.get('startTime') or not s.get('endTime'):
                    continue
                out.append([s['playerId'], D.team(s['teamAbbrev']), s['period'], _clock(s['startTime']),
                            _clock(s['endTime'])])
            return out
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def html_shifts(gid):
    """the same rows from the NHL's HTML time-on-ice reports (home TH, visitor TV); jersey -> id from the box score"""
    box = D.get(f'{D.WEB}/gamecenter/{gid}/boxscore')
    if not box or 'playerByGameStats' not in box:
        return None
    s = str(gid)
    yrs = f'{s[:4]}{int(s[:4]) + 1}'
    out = []
    for side, code in (('homeTeam', 'TH'), ('awayTeam', 'TV')):
        tm = D.team(box[side]['abbrev'])
        pg = box['playerByGameStats'][side]
        num = {p['sweaterNumber']: p['playerId'] for k in ('forwards', 'defense', 'goalies') for p in pg.get(k, [])}
        raw = D.get(f'https://www.nhl.com/scores/htmlreports/{yrs}/{code}{s[4:]}.HTM', raw=True)
        if not raw:
            return None
        t = re.sub(r'<[^>]+>', '|', raw.decode('utf-8', 'replace'))
        t = re.sub(r'\s*\|\s*', '|', t.replace('&nbsp;', ' '))
        t = re.sub(r'\|+', '|', t)
        # each player block: "|<jersey> <LAST, FIRST>|Shift #|..." then rows "|n|per|m:ss / m:ss|m:ss / m:ss|mm:ss|"
        blocks = re.split(r'\|(\d{1,2}) [A-Z][^|]*, [^|]*\|Shift #\|', t)
        for i in range(1, len(blocks) - 1, 2):
            pid = num.get(int(blocks[i]))
            if pid is None:
                continue
            body = blocks[i + 1].split('|Per|SHF|')[0]
            for m in re.finditer(r'\|(\d+)\|(\d|OT)\|(\d+:\d\d) / \d+:\d\d\|(\d+:\d\d) / \d+:\d\d\|', body):
                per = 4 if m.group(2) == 'OT' else int(m.group(2))
                a, b = _clock(m.group(3)), _clock(m.group(4))
                if b > a:
                    out.append([pid, tm, per, a, b])
    return out


def game_shifts(gid, html=True):
    s = api_shifts(gid)
    if not s and html:
        h = html_shifts(gid)
        if h:
            return h
    return s


def season_shifts(S, gids=None, workers=8, html=False):
    """{gameId str: shifts} for season S (cached; games missing from the cache are fetched)"""
    fn = os.path.join(SHD, f'{S}.json.gz')
    have = D.load(fn) if os.path.exists(fn) else {}
    if gids is None:
        gids = [g['id'] for g in D.games(S) if g['final']]
    need = [g for g in gids if str(g) not in have]
    if need:
        with ThreadPoolExecutor(workers) as ex:
            for gid, sh in zip(need, ex.map(lambda g: game_shifts(g, html), need)):
                if sh:
                    have[str(gid)] = sh
        D.save(fn, have)
        print('shifts', S, len(have), 'games;', len(need), 'requested', flush=True)
    return have


# ---------------------------------------------------------------- shots
def mp_shots(S, max_age_h=None):
    """{gameId str: [(game second, shooting team, xG, goal, strength 'hs-as' skaters, empty net either side)]} from
    MoneyPuck's shot file for season S (regular season and playoffs)"""
    os.makedirs(MPD, exist_ok=True)
    fn = os.path.join(MPD, f'shots_{S - 1}.zip')
    stale = max_age_h is not None and os.path.exists(fn) and time.time() - os.path.getmtime(fn) > max_age_h * 3600
    if not os.path.exists(fn) or stale:
        b = D.get(MPURL.format(S - 1), raw=True)
        if b:
            with open(fn + '.tmp', 'wb') as f:
                f.write(b)
            os.replace(fn + '.tmp', fn)
    if not os.path.exists(fn):
        return {}
    z = zipfile.ZipFile(fn)
    out = defaultdict(list)
    with z.open(z.namelist()[0]) as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding='utf-8')):
            gid = f'{S - 1}0{int(r["game_id"]):05d}' if len(r['game_id']) <= 6 else r['game_id']
            home = r['isHomeTeam'] == '1'
            tm = D.team(r['teamCode'])
            en = r.get('homeEmptyNet') == '1' or r.get('awayEmptyNet') == '1'
            out[gid].append((int(float(r['time'])), tm, home, float(r['xGoal'] or 0), int(r['goal'] == '1'),
                             f"{r['homeSkatersOnIce']}-{r['awaySkatersOnIce']}", en))
    return dict(out)


# ---------------------------------------------------------------- per-second build
def onice(shifts, lineup):
    """per-second on-ice sets for one game: {team: [(skaters frozenset, goalie on?)]} indexed by game second
    (second k = interval (k, k+1]); skaters = ids in the team's dressed lineup ('<id><F|D>'), anything else a goalie"""
    pos = {}
    for t, ids in lineup.items():
        for x in ids:
            pos[int(x[:-1])] = x[-1]
    end = 0
    per_team = defaultdict(list)
    for pid, tm, per, a, b in shifts:
        if per > 4 or b <= a:          # regulation + regular-season OT only (shootouts have no shifts)
            continue
        t0, t1 = (per - 1) * 1200 + a, (per - 1) * 1200 + b
        per_team[tm].append((pid, t0, t1))
        end = max(end, t1)
    out = {}
    for tm, rows in per_team.items():
        sk = [set() for _ in range(end)]
        gk = [False] * end
        for pid, t0, t1 in rows:
            p = pos.get(pid)
            for k in range(t0, t1):
                if p:
                    sk[k].add(pid)
                else:
                    gk[k] = True
        out[tm] = (sk, gk)
    return out, pos, end


def game_units(shifts, lineup, shots, home, away):
    """5-on-5 units for one game: {team: {'F': {trio: [s, gf, ga, xgf, xga]}, 'D': {...}, 'P': {pid: [...]},
    'W': {(a, b): [...]}, 'pp': {pid: [s, xgf]}, 'pk': {pid: [s, xga]}, 'toi5': s}}"""
    oi, pos, end = onice(shifts, lineup)
    if home not in oi or away not in oi:
        return None
    teams = (home, away)
    strength = [None] * end         # '5v5', or (team on the power play) for 5v4
    for k in range(end):
        nh, na = len(oi[home][0][k]), len(oi[away][0][k])
        gh, ga = oi[home][1][k], oi[away][1][k]
        if gh and ga:
            if nh == 5 and na == 5:
                strength[k] = '5v5'
            elif nh == 5 and na == 4:
                strength[k] = home
            elif nh == 4 and na == 5:
                strength[k] = away
    res = {t: {'F': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]), 'D': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]),
               'P': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]), 'W': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]),
               'pp': defaultdict(lambda: [0, 0.0]), 'pk': defaultdict(lambda: [0, 0.0]), 'toi5': 0, 'tot': [0, 0, 0, 0.0, 0.0]}
           for t in teams}

    def keys(t, k):
        s = oi[t][0][k]
        f = tuple(sorted(p for p in s if pos[p] == 'F'))
        d = tuple(sorted(p for p in s if pos[p] == 'D'))
        return s, f, d

    def add(t, k, i, v):
        s, f, d = keys(t, k)
        r = res[t]
        if len(f) == 3 and len(d) == 2:
            r['F'][f][i] += v
            r['D'][d][i] += v
        for p in s:
            r['P'][p][i] += v
        sl = sorted(s)
        for a in range(len(sl)):
            for b in range(a + 1, len(sl)):
                r['W'][(sl[a], sl[b])][i] += v
        r['tot'][i] += v

    for k in range(end):
        st = strength[k]
        if st == '5v5':
            for t in teams:
                add(t, k, 0, 1)
                res[t]['toi5'] += 1
        elif st in teams:
            o = away if st == home else home
            for p in oi[st][0][k]:
                res[st]['pp'][p][0] += 1
            for p in oi[o][0][k]:
                res[o]['pk'][p][0] += 1
    for sec, tm, ishome, xg, goal, stren, en in shots or []:
        k = sec - 1
        if k < 0 or k >= end or en:
            continue
        o = away if tm == home else home
        if tm not in teams:
            continue
        st = strength[k]
        if st == '5v5' and stren == '5-5':
            add(tm, k, 3, xg); add(o, k, 4, xg)
            if goal:
                add(tm, k, 1, 1); add(o, k, 2, 1)
        elif st == tm:
            for p in oi[tm][0][k]:
                res[tm]['pp'][p][1] += xg
            for p in oi[o][0][k]:
                res[o]['pk'][p][1] += xg
    return res


# ---------------------------------------------------------------- season tables
def lineups_for(S):
    import nhl_games as G
    ln = G._lineups(S)
    if not ln:
        ln = G.lineups_from_logs(D.skater_logs(S))
        G.set_lineups(S, ln)
    return ln


def season_units(S, games=None, shots=None, html=False, workers=8):
    """[(game dict, {team: units})] for season S's final regular-season and playoff games, in date order"""
    games = games or [g for g in D.games(S) if g['final']]
    ln = lineups_for(S)
    sh = season_shifts(S, [g['id'] for g in games], html=html, workers=workers)
    shots = mp_shots(S) if shots is None else shots
    out = []
    for g in games:
        gid = str(g['id'])
        if gid not in sh or gid not in ln:
            continue
        u = game_units(sh[gid], ln[gid], shots.get(gid), g['h'], g['a'])
        if u:
            out.append((g, u, gid in shots))
    return out


def check(S):
    """5v5 build against the box score: each skater's shift-chart ice time vs the stats API's, and 5v5 time a game"""
    logs = D.skater_logs(S)
    toi = {(str(r[0]), r[1]): r[5] for r in logs}
    sh = season_shifts(S)
    diffs, n = [], 0
    for gid, rows in sh.items():
        tot = defaultdict(int)
        for pid, tm, per, a, b in rows:
            if per <= 4:
                tot[pid] += b - a
        for pid, s in tot.items():
            if (gid, pid) in toi:
                diffs.append(s - toi[(gid, pid)]); n += 1
    diffs.sort()
    within = sum(abs(d) <= 2 for d in diffs) / max(1, len(diffs))
    units = season_units(S)
    t5 = [u[t]['toi5'] / 60 for g, u, _ in units for t in u]
    xg = [u[t]['tot'][3] for g, u, ok in units if ok for t in u]
    out = {'season': S, 'playerGames': n, 'shareWithin2s': round(within, 4),
           'medianDiffS': diffs[len(diffs) // 2] if diffs else None, 'games': len(units),
           'toi5PerTeamGame': round(sum(t5) / max(1, len(t5)), 2), 'xgf5PerTeamGame': round(sum(xg) / max(1, len(xg)), 3)}
    print(out)
    return out


# ---------------------------------------------------------------- compact season summaries (research + board)
def _key(k):
    return '-'.join(map(str, k))


def summarize(S, html=False, workers=8):
    """per game, per team: forward trios and D pairs [s, gf, ga, xgf, xga], each skater's 5v5 line, pair-together
    5v5 lines (WOWY, pairs with 60+ s) and power-play / penalty-kill [s, xG]; cached as
    scripts/.cache/nhl/lines/<S>.json.gz for finished seasons"""
    fn = os.path.join(D.CACHE, 'lines', f'{S}.json.gz')
    if os.path.exists(fn) and S < D.current_season():
        return D.load(fn)
    out = []
    for g, u, has_xg in season_units(S, html=html, workers=workers):
        row = {'id': g['id'], 'day': g['day'], 'h': g['h'], 'a': g['a'], 'po': g['type'] == 3, 'xg': has_xg, 't': {}}
        for t, r in u.items():
            row['t'][t] = {'F': {_key(k): v for k, v in r['F'].items()}, 'D': {_key(k): v for k, v in r['D'].items()},
                           'P': {str(k): v for k, v in r['P'].items()},
                           'W': {_key(k): v for k, v in r['W'].items() if v[0] >= 60},
                           'pp': {str(k): v for k, v in r['pp'].items()}, 'pk': {str(k): v for k, v in r['pk'].items()},
                           'toi5': r['toi5'], 'tot': r['tot']}
        out.append(row)
    out.sort(key=lambda r: (r['day'], r['id']))
    if S < D.current_season():
        D.save(fn, out)
    return out


# ---------------------------------------------------------------- the board's lines tab
def _pct(f, a):
    return None if f + a <= 0 else round(100 * f / (f + a), 1)


def _unit(ids, v, name, last_s=None):
    s, gf, ga, xf, xa = v
    return {'p': [name.get(int(i), str(i)) for i in ids], 'min': round(s / 60, 1),
            'last': None if last_s is None else round(last_s / 60, 1), 'gf': gf, 'ga': ga,
            'xgf': round(xf, 2), 'xga': round(xa, 2), 'gfp': _pct(gf, ga), 'xgfp': _pct(xf, xa)}


def build(S=None):
    """static/data/lines/nhl.json: every team's current lines (its last game's trios and pairs by 5v5 time) with their season
    numbers together, the season's most-used units, each skater's 5v5 on/off and his most common linemate (WOWY)"""
    S = S or D.current_season()
    games = [g for g in D.games(S, fresh=True) if g['final'] and g['type'] == 2]
    logs = D.skater_logs(S, fresh=True)
    import nhl_games as NG
    NG.set_lineups(S, NG.lineups_from_logs(logs))
    full = {r[1]: r[2] for r in logs}
    name = {}
    for pid, nm in full.items():
        parts = nm.split(' ', 1)
        name[pid] = parts[1] if len(parts) == 2 else nm
    shots = mp_shots(S, max_age_h=10)
    rows = season_units(S, games=games, shots=shots, html=True, workers=6)
    seas = defaultdict(lambda: {'F': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]), 'D': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]),
                                'P': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]), 'W': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]),
                                'T': defaultdict(lambda: [0, 0, 0, 0.0, 0.0]), 'gp': defaultdict(int), 'games': 0, 'xg': 0})
    last, prev = {}, {}
    for g, u, has_xg in rows:
        for t, r in u.items():
            A = seas[t]
            A['games'] += 1
            A['xg'] += has_xg
            for grp in ('F', 'D', 'P', 'W'):
                for k, v in r[grp].items():
                    for i in range(5):
                        A[grp][k][i] += v[i]
            for p, v in r['P'].items():
                A['gp'][p] += 1
                for i in range(5):
                    A['T'][p][i] += r['tot'][i]          # the team's 5v5 numbers in his games
            prev[t] = last.get(t)
            last[t] = (g, r)
    try:                                   # full team names from the depth chart file (scripts/backup_watch.py)
        tn = {x['t']: x['n'] for x in json.load(open(os.path.join(ROOT, 'static', 'data', 'depth', 'nhl.json')))['teams']}
    except (OSError, ValueError, KeyError):
        tn = {}
    teams = []
    for t in sorted(seas):
        A = seas[t]
        if t not in last:
            continue
        g, r = last[t]
        opp = g['a'] if g['h'] == t else g['h']
        fl = sorted(r['F'].items(), key=lambda kv: -kv[1][0])[:4]
        dl = sorted(r['D'].items(), key=lambda kv: -kv[1][0])[:3]
        prev_top = set()
        if prev.get(t):
            prev_top = set(k for k, _ in sorted(prev[t][1]['F'].items(), key=lambda kv: -kv[1][0])[:4])
        T = {'t': t, 'n': tn.get(t, t), 'logo': f'/img/nhl/{t.lower()}.png', 'gp': A['games'], 'xgGames': A['xg'],
             'last': {'day': g['day'], 'opp': opp, 'home': g['h'] == t},
             'lines': [_unit(k, A['F'][k], name, v[0]) for k, v in fl],
             'pairs': [_unit(k, A['D'][k], name, v[0]) for k, v in dl],
             'kept': sum(k in prev_top for k, _ in fl) if prev.get(t) else None,
             'topF': [_unit(k, v, name) for k, v in sorted(A['F'].items(), key=lambda kv: -kv[1][0])[:8] if v[0] >= 300],
             'topD': [_unit(k, v, name) for k, v in sorted(A['D'].items(), key=lambda kv: -kv[1][0])[:6] if v[0] >= 300]}
        sk = []
        pos = {}
        for ids in NG._lineups(S).values():
            for x in ids.get(t, []):
                pos[int(x[:-1])] = x[-1]
        for p, v in A['P'].items():
            if v[0] < 3600:                  # 60+ 5v5 minutes
                continue
            tv = A['T'][p]
            off = [tv[i] - v[i] for i in range(5)]
            mates = [(k, w) for k, w in A['W'].items() if p in k]
            mate = None
            if mates:
                k, w = max(mates, key=lambda kw: kw[1][0])
                q = k[0] if k[1] == p else k[1]
                qv = A['P'].get(q)
                apart = [v[i] - w[i] for i in range(5)]
                q_apart = [qv[i] - w[i] for i in range(5)] if qv else None
                mate = {'p': name.get(int(q), str(q)), 'min': round(w[0] / 60, 1), 'xgfp': _pct(w[3], w[4]),
                        'apart': _pct(apart[3], apart[4]) if apart[0] >= 1800 else None,
                        'mateApart': _pct(q_apart[3], q_apart[4]) if q_apart and q_apart[0] >= 1800 else None}
            on_x, off_x = _pct(v[3], v[4]), _pct(off[3], off[4])
            sk.append({'p': name.get(int(p), str(p)), 'n': full.get(int(p), ''), 'pos': pos.get(int(p), ''),
                       'gp': A['gp'][p], 'min': round(v[0] / 60, 1), 'gfp': _pct(v[1], v[2]), 'xgfp': on_x,
                       'offx': off_x if off[0] >= 1800 else None,
                       'rel': None if on_x is None or off_x is None or off[0] < 1800 else round(on_x - off_x, 1),
                       'mate': mate})
        sk.sort(key=lambda x: -x['min'])
        T['skaters'] = sk
        teams.append(T)
    out = {'season': S, 'label': f'{S - 1}-{str(S)[2:]}', 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'games': len(rows), 'teams': teams}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + '.tmp', 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)
    os.replace(OUT + '.tmp', OUT)
    print('wrote', OUT, os.path.getsize(OUT), 'bytes;', len(rows), 'games,', len(teams), 'teams')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--pull':
        for S in map(int, a[1:]):
            season_shifts(S)
            mp_shots(S)
    elif a and a[0] == '--check':
        check(int(a[1]))
    else:
        build()
