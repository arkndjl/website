#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The daily build of the college basketball game model (python3 scripts/cbb_games.py, run by .github/workflows/cbb-board.yml):
data/cbb_games.json (the next two slates, power ratings, season odds).

This season's games and lines are kept in scripts/data/cbb_games_<season>.json.gz (committed): each run re-reads ESPN's
scoreboard for every date of the season (schedule, scores), refreshes the lines of games in the next two days (ESPN's
core odds, every book; the line at publish time for picks) and takes each final game's closing line once. Ratings start
from scripts/data/cbb_games_state.json (last season's final ratings, Elo and market ratings, written by --fit) and the
preseason prior from the board's rosters (scripts/cbb_prior.json.gz); Barttorvik supplies possessions and per-game minutes.
"""
import gzip
import html
import json
import math
import os
import re
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import cbb_games as C
import cbb_games_hist as H
import names as NM
import numpy as np

SEASON = 2027
LOG = os.path.join(C.HERE, 'data', f'cbb_games_{SEASON}.json.gz')
SUMMARY = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={i}'
PICKS_LEFT = 2                    # slates shown: today's and the next date with games
SIMS = 5000
# the season sims' strength shock, tuned on 2016-20 rest-of-season wins (CRPS t -5.6 against the old 3 x sqrt(8 / (8 +
# games)), 2021-26 t -9.8; conference wins -5.5 / -10.6; conference title log loss -0.8 / -4.7)
# Retuned Nov 2 2026 on the full-scale power rating (cbb_tourney.team_rating): the 2016-20 best, a 0 k 8 b 4 (wins
# CRPS t -2.2), ties 2021-26 (1.0788 both, t -0.1) and loses there on conference wins (t +1.0) and title (t +1.2), so
# these stay (data/cbb_games_research.json sims)
SHOCK_A, SHOCK_K, SHOCK_B = 2.0, 8.0, 4.0
POSTSEASON = re.compile(r'tournament|championship|playoff', re.I)     # conference games with these notes: the tournaments


def iso(d):
    """ESPN's '2026-11-01T14:30Z' as RFC 3339 with seconds (Hugo's time parses only that)"""
    return d[:-1] + ':00Z' if len(d) == 17 else d


def now_utc():
    return datetime.now(timezone.utc)


def fetch_json(url, timeout=40):
    for i in range(3):
        r = subprocess.run(['curl', '-s', '-m', str(timeout), '-A', H.UA, url], capture_output=True, text=True)
        try:
            return json.loads(r.stdout)
        except ValueError:
            continue
    return None


def parse(e):
    g = H.parse_event(e)
    if not g:
        return None
    c = e['competitions'][0]
    side = {x['homeAway']: x for x in c['competitors']}
    g['ha'], g['aa'] = side['home']['team'].get('abbreviation'), side['away']['team'].get('abbreviation')
    g['venue'] = (c.get('venue') or {}).get('fullName')
    if c.get('timeValid') is False:
        g['tba'] = True               # ESPN lists a date with no tip time yet (05:00Z)
    g['tv'] = ', '.join(n for b in c.get('broadcasts') or [] for n in b.get('names', []))
    for k in ('home', 'away'):
        rk = (side[k].get('curatedRank') or {}).get('current')
        if rk and rk <= 25:
            g[k[0] + 'ap'] = rk
    return g


def update_log():
    try:
        log = {g['id']: g for g in json.load(gzip.open(LOG))}
    except (OSError, ValueError):
        log = {}
    now = now_utc()
    ds = list(H.dates(SEASON))
    # every date: past ones only while a game there isn't final yet (or the date is within three days)
    final_dates = defaultdict(lambda: True)
    for g in log.values():
        d = C.et_date(g['date']).replace('-', '')
        final_dates[d] = final_dates[d] and g.get('hs') is not None
    recent = (now - timedelta(days=3)).strftime('%Y%m%d')
    want = [d for d in ds if d >= recent or not final_dates[d] or d not in {C.et_date(g['date']).replace('-', '') for g in log.values()}]
    with ThreadPoolExecutor(8) as ex:
        for j in ex.map(lambda d: fetch_json(H.SB.format(d=d)), want):
            for e in (j or {}).get('events', []):
                g = parse(e)
                if not g or g['season'] != SEASON:
                    continue
                old = log.get(g['id'], {})
                for k in ('spread', 'total', 'mlh', 'mla', 'open', 'book', 'closed', 'poss', 'hb', 'ab', 'seen', 'pt', 'ptx'):
                    if k in old:
                        g[k] = old[k]
                log[g['id']] = g
    # lines: games in the next two days (current line), and each final game once (its close)
    soon = (now + timedelta(days=2)).isoformat()
    todo = [g for g in log.values() if (g.get('hs') is None and g['date'] <= soon and g['state'] == 'pre')
            or (g.get('hs') is not None and not g.get('closed'))]
    with ThreadPoolExecutor(16) as ex:
        for g, o in zip(todo, ex.map(lambda g: fetch_json(H.ODDS.format(i=g['id'])), todo)):
            if o is None:
                continue
            ln = H.pick_line(o.get('items', []))
            if ln.get('spread') is None and g.get('spread') is not None:
                ln = {}
            g.update(ln)
            if g.get('hs') is not None:
                g['closed'] = True
            elif ln.get('spread') is not None and 'seen' not in g:
                g['seen'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    # each final game's possession time from its ESPN play-by-play, once (the asymmetric tempo, cbb_games aplmix); a game
    # whose log is partial is tried again on the next two runs ('ptx')
    todo = [g for g in log.values() if g.get('hs') is not None and 'pt' not in g and g.get('ptx', 0) < 3]
    with ThreadPoolExecutor(12) as ex:
        for g, j in zip(todo, ex.map(lambda g: fetch_json(SUMMARY.format(i=g['id'])), todo)):
            v = C.poss_secs((j or {}).get('plays') or [], g['home'], g['away'])
            if v:
                g['pt'] = v
                g.pop('ptx', None)
            else:
                g['ptx'] = g.get('ptx', 0) + 1
    # possessions and Barttorvik names (this season's super_sked)
    os.makedirs(C.CACHE, exist_ok=True)
    p = os.path.join(C.CACHE, f'bt_sked{SEASON}.csv')
    subprocess.run(['curl', '-s', '-m', '120', '-A', H.UA, f'https://barttorvik.com/{SEASON}_super_sked.csv', '-o', p], check=False)
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        bt = H.bart(SEASON)
        for g in log.values():
            if g.get('hs') is None or 'poss' in g:
                continue
            local = C.et_date(g['date'])
            q = bt.get((local, tuple(sorted((g['hs'], g['as'])))))
            if q and len(q) == 1:
                g['poss'] = round(q[0][0], 1)
                if g['hs'] != g['as']:
                    g['hb'], g['ab'] = q[0][1][g['hs']], q[0][1][g['as']]
    rows = sorted(log.values(), key=lambda g: (g['date'], g['id']))
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with gzip.GzipFile(LOG, 'wb', mtime=0) as f:          # mtime 0: the same games make the same bytes (no empty commits)
        f.write(json.dumps(rows, separators=(',', ':')).encode())
    return rows


COVERS = 'https://www.covers.com/sport/basketball/ncaab/injuries'
INJ_OUT = os.path.join(C.ROOT, 'data', 'cbb_injuries.json')
# chance a listed player sits, by Covers' status. College basketball has no status history to measure, so these are
# the NBA's minutes-weighted rates on its 2019-20 to 2025-26 reports (data/nba_games_fit.json P: doubtful plays 2.5%,
# questionable 56%, probable 95%; ESPN's and Covers' day-to-day read as questionable). Each run appends the matched
# report to INJ_LOG (append-only, one line per player per status per day), the college log that
# scripts/cbb_sit_refit.py refits these on once it holds 400 scored listings; a refit that passes its held-out test
# is written to data/cbb_sit_fit.json and replaces these.
SIT = {'out': 1.0, 'out for season': 1.0, 'suspended': 1.0, 'doubtful': 0.975, 'questionable': 0.44, 'day to day': 0.44,
       'game time decision': 0.44, 'probable': 0.05}
INJ_LOG = os.path.join(C.ROOT, 'scripts', 'data', 'cbb_injury_log', f'{SEASON}.jsonl')
try:
    _fit = json.load(open(os.path.join(C.ROOT, 'data', 'cbb_sit_fit.json')))
    if _fit.get('ship'):
        SIT.update(_fit['sit'])
except (OSError, ValueError):
    pass


def log_injuries(rows):
    """append today's matched listings to INJ_LOG: [date, team, Barttorvik pid, name, status], each once a day"""
    day = now_utc().strftime('%Y-%m-%d')
    seen = set()
    try:
        with open(INJ_LOG) as f:
            for line in f:
                if line.startswith(f'["{day}"'):
                    seen.add(line.strip())
    except OSError:
        pass
    new = [json.dumps([day, *r], separators=(',', ':')) for r in rows]
    new = [x for x in dict.fromkeys(new) if x not in seen]
    if new:
        os.makedirs(os.path.dirname(INJ_LOG), exist_ok=True)
        with open(INJ_LOG, 'a') as f:
            f.write('\n'.join(new) + '\n')
    return len(new)


# Covers' team names that aren't Barttorvik's under the shared team key
COVERS_TEAMS = {'ACU': 'Abilene Christian', 'AR-Pine Bluff': 'Arkansas Pine Bluff', 'CA Baptist': 'Cal Baptist', 'Cal Poly SLO': 'Cal Poly',
                'Central CT': 'Central Connecticut', 'Charleston So': 'Charleston Southern', 'CSU Bakersfield': 'Cal St. Bakersfield',
                'CSU Fullerton': 'Cal St. Fullerton', 'CSU Northridge': 'Cal St. Northridge', 'Eastern WA': 'Eastern Washington',
                'FDU': 'Fairleigh Dickinson', 'FIU Panthers': 'FIU', 'Fort Wayne': 'Purdue Fort Wayne', 'GW': 'George Washington',
                'HCU': 'Houston Christian', 'IUPUI': 'IU Indy', 'Kansas City': 'UMKC', 'MD Eastern': 'Maryland Eastern Shore',
                'Middle TN': 'Middle Tennessee', 'Miss Valley St': 'Mississippi Valley St.', 'Monmouth-NJ': 'Monmouth',
                'MS State': 'Mississippi St.', 'NC A&T': 'North Carolina A&T', 'NC Central': 'North Carolina Central',
                'ND State': 'North Dakota St.', 'NIU': 'Northern Illinois', 'Northern CO': 'Northern Colorado',
                'Northern KY': 'Northern Kentucky', 'Pennsylvania': 'Penn', 'Queens NC': 'Queens', 'SC State': 'South Carolina St.',
                'SD State': 'South Dakota St.', 'SE Louisiana': 'Southeastern Louisiana', 'SE Missouri St.': 'Southeast Missouri St.',
                'SFA': 'Stephen F. Austin', 'Southern IL': 'Southern Illinois', 'St. Thomas (MN)': 'St. Thomas', 'Tenn-Martin': 'Tennessee Martin',
                'Texas A&M-CC': 'Texas A&M Corpus Chris', 'Texas R-G Valley': 'UT Rio Grande Valley', 'Texas-Arlington': 'UT Arlington',
                'UL Lafayette': 'Louisiana', 'UL Monroe': 'Louisiana Monroe'}


def covers_report():
    """Covers' college basketball injury report: [(team, full name, position, status, detail, news date)]"""
    try:
        r = subprocess.run(['curl', '-s', '-m', '60', '-A', H.UA, COVERS], capture_output=True, text=True)
        h = r.stdout
    except Exception:
        return []
    out = []
    parts = re.split(r'<a id="([^"]+)"></a>\s*<section>', h)
    row = re.compile(r"<tr>\s*<td>\s*<a href='[^']*/players/\d+/([^']+)'[^>]*>\s*([^<]+?)\s*</a>\s*</td>\s*<td>([^<]*)</td>\s*"
                     r"<td><b>([^<]+)</b>(?:<br>\(\s*([^)]+)\))?", re.S)
    for i in range(1, len(parts) - 1, 2):
        for slug, shown, pos, st, when in row.findall(parts[i + 1]):
            name = ' '.join(w.capitalize() for w in slug.split('-'))
            stt, _, detail = st.partition(' - ')
            team = html.unescape(parts[i])
            out.append((COVERS_TEAMS.get(team, team), name, pos.strip(), stt.strip(), detail.strip(), (when or '').strip()))
    return merge_rotowire(out)


RW_CBB = {'Out (season)': 'Out For Season', 'Out': 'Out', 'Doubtful': 'Doubtful', 'Questionable': 'Questionable',
          'Probable': 'Probable', 'Active': None}


def merge_rotowire(rows):
    """Covers' rows with RotoWire's college injury news (scripts/rotowire.py; the last 2 days) merged in, newest per
    player: a RotoWire item dated the same day as Covers' note or later replaces it (Active takes him off); a player
    Covers doesn't list is added. Same row shape, so the same sit rates price both."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    try:
        import rotowire as RW
        RW.refresh('cbasketball')
        news = RW.items('cbasketball', since=time.time() - 2 * 86400)
    except Exception as e:  # noqa: BLE001
        print('cbb injuries: RotoWire news unavailable:', e)
        return rows
    def day(when):            # Covers' "Wed, Oct 7": this season's date
        try:
            d = dt.datetime.strptime(when.split(', ', 1)[1] + f' {now_utc().year}', '%b %d %Y').date()
            return d.replace(year=d.year - 1) if d > now_utc().date() + dt.timedelta(days=1) else d
        except (IndexError, ValueError):
            return None
    out, n = list(rows), 0
    for it in news:
        st = RW.item_status(it)
        if st not in RW_CBB:
            continue
        team = COVERS_TEAMS.get(it['team'], it['team'])
        d = dt.datetime.fromtimestamp(it['ts'], ZoneInfo('America/New_York')).date()
        same = [r for r in out if NM.team_key(r[0]) == NM.team_key(team) and NM.same(r[1], it['player'])]
        if any(day(r[5]) and day(r[5]) > d for r in same):
            continue
        for r in same:
            out.remove(r)
        if RW_CBB[st]:
            out.append((team, it['player'], it['pos'], RW_CBB[st], it['inj'], d.strftime('%a, %b %-d')))
        n += 1
    # out for weeks or the season by his RotoWire injury card (scripts/rotowire_history.py), when no row lists him
    for v in RW.long_term('cbasketball'):
        team = COVERS_TEAMS.get(v['team'], v['team'])
        if any(NM.team_key(r[0]) == NM.team_key(team) and NM.same(r[1], v['player']) for r in out):
            continue
        out.append((team, v['player'], v['pos'], 'Out For Season' if v['season'] else 'Out', v['injury'],
                    dt.date.fromisoformat(v['last_d']).strftime('%a, %b %-d')))
        n += 1
    print(f'cbb injuries: {n} RotoWire items merged')
    try:   # RotoWire's move news: a player who left the program (dismissed, portal, retired) sits the rest of the season
        import rotowire_moves as RM
        k = 0
        for m in RM.exits('cbasketball'):
            if not m['team'] or m['team'] in RM.FA:
                continue
            team = COVERS_TEAMS.get(m['team'], m['team'])
            if any(NM.team_key(r[0]) == NM.team_key(team) and NM.same(r[1], m['player']) and r[3] == 'Out For Season' for r in out):
                continue
            out = [r for r in out if not (NM.team_key(r[0]) == NM.team_key(team) and NM.same(r[1], m['player']))]
            out.append((team, m['player'], m['pos'], 'Out For Season', m['head'],
                        dt.date.fromisoformat(m['d']).strftime('%a, %b %-d')))
            k += 1
        print(f'cbb injuries: {k} RotoWire program exits')
    except Exception as e:  # noqa: BLE001
        print('cbb injuries: RotoWire exits unavailable:', e)
    return out


def pre_listed(report, logs):
    """the injury report on last season's Barttorvik players: team -> {pid: chance he sits}, for the players who
    haven't played for the team this season"""
    prev = C.bt_logs(SEASON - 1)
    pn = defaultdict(dict)
    try:
        for r in json.load(gzip.open(os.path.join(C.BTLOG, f'{SEASON - 1}.json.gz'))):
            pn[r[47]][r[51]] = r[48]
    except Exception:
        return {}
    played = {t: {pid for _, d in gl for pid in d} for t, gl in logs.items()}
    keys = {NM.team_key(t): t for t in set(prev) | set(logs)}
    # the board's careers: this season's team -> [(name, last season's team)]
    d = json.load(gzip.open(os.path.join(C.HERE, 'cbb_prior.json.gz')))
    K = {k: i for i, k in enumerate(d['keep'])}
    ci = {k: i for i, k in enumerate(d['cols'])}
    roster = defaultdict(list)
    for row, c in zip(d['rows'], d['careers']):
        last = [x for x in c['seasons'] if x[K['year']] == SEASON - 1]
        if c.get('bt') and last:
            roster[c['bt']].append({'pid': last[0][K['team']], 'name': row[ci['name']]})
    out = defaultdict(dict)
    for team, name, pos, stt, detail, when in report:
        t, sit = keys.get(NM.team_key(team)), SIT.get(stt.lower())
        if not t or sit is None:
            continue
        hit, _ = NM.Matcher([{'pid': p, 'name': n} for p, n in pn.get(t, {}).items()], team=None, pos=None, sport='basketball').find(name)
        if not hit:
            # a transfer: his old school from the board, then his line there
            r, _ = NM.Matcher(roster.get(t, []), team=None, pos=None, sport='basketball').find(name)
            old = r and keys.get(NM.team_key(r['pid']))
            if old:
                hit, _ = NM.Matcher([{'pid': p, 'name': n} for p, n in pn.get(old, {}).items()], team=None, pos=None, sport='basketball').find(name)
        if hit and hit['pid'] not in played.get(t, ()):
            out[t][hit['pid']] = sit
    return dict(out)


# the availability snapshot (avail_snapshot, refresh_injuries): this season's part, rewritten by each build, and last
# season's (players by school, their lines, the board's rosters), rewritten only when it changes
SNAP = os.path.join(C.HERE, 'data', 'cbb_avail_snap.json.gz')
SNAP_PREV = os.path.join(C.HERE, 'data', 'cbb_avail_prev.json.gz')
PREV_KEYS = ('prevTeams', 'pn', 'val', 'roster')


def pid_order(pid):
    """sort key for player ids: Barttorvik's int pids first in number order, then the ESPN fill's 'e<id>' strings
    (cbb_espn_logs gives a player it cannot match to Barttorvik a string id, so one team can hold both)"""
    return (isinstance(pid, str), pid if isinstance(pid, int) else 0, str(pid))


def avail_snapshot(logs):
    """the report-free part of the availability inputs at this build, so a later injury report re-prices the slate
    without the game logs (refresh_injuries). Per team, this season's players (pid, name, played, value at a full
    absence over the team's bench as avail() counts it, games missed in a row, minutes a game, BPM shown); last
    season's players by school; their pre_out() line; the board's rosters with each player's school last season"""
    names, teams = {}, defaultdict(set)
    try:
        for r in json.load(gzip.open(os.path.join(C.BTLOG, f'{SEASON}.json.gz'))):
            names[r[51]] = r[48]; teams[r[47]].add(r[51])
    except Exception:
        pass
    T = {}
    for t in set(logs) | set(teams):
        gl = logs.get(t, [])
        k = len(gl)
        st, run = {}, defaultdict(int)
        for d, pl in gl:
            for pid, (mn, gb) in pl.items():
                s = st.setdefault(pid, [0, 0.0, 0.0]); s[0] += 1; s[1] += mn; s[2] += gb * mn
            for pid in st:
                run[pid] = 0 if pid in pl else run[pid] + 1
        rp = -3.0
        if k >= 3:
            bs = [(mn, bm) for g, mn, bm in st.values() if g < 0.6 * k or mn / g < 12]
            rp = (sum(b for _, b in bs) + -3.0 * C.BENCH) / (sum(m for m, _ in bs) + C.BENCH)
        pl = []
        for pid in sorted(set(teams.get(t, ())) | set(st), key=pid_order):
            g, mn, bm = st.get(pid, (0, 0.0, 0.0))
            rot = k >= 3 and g >= 0.6 * k and mn / g >= 12
            u = max(0.0, (bm - 150.0) / (mn + 150.0) - rp) * (mn / k) / 40 if rot else 0.0
            pl.append([pid, names.get(pid, ''), int(pid in st), int(rot), round(u, 6), run[pid] if rot else 0,
                       round(mn / g, 1) if g else 0.0, round((bm - 150) / (mn + 150), 1) if g else 0.0])
        T[t] = {'k': k, 'rp': round(rp, 6), 'pl': pl}
    # last season: every Barttorvik row by school, and the pre_out() line (200+ minutes, any team)
    prev = C.bt_logs(SEASON - 1)
    pn = defaultdict(dict)
    try:
        for r in json.load(gzip.open(os.path.join(C.BTLOG, f'{SEASON - 1}.json.gz'))):
            pn[r[47]][r[51]] = r[48]
    except Exception:
        pass
    tot = defaultdict(lambda: [0.0, 0.0, defaultdict(float)])
    ng = {t: len(gl) for t, gl in prev.items()}
    for t, gl in prev.items():
        for _, d in gl:
            for pid, (mn, gb) in d.items():
                z = tot[pid]; z[0] += mn; z[1] += gb * mn; z[2][t] += mn
    val = {}
    for pid, (m, b, by) in tot.items():
        if m >= 200.0:
            main = max(by, key=by.get)
            val[pid] = [round((b - 150.0) / (m + 150.0), 6), round(m / max(1, ng[main]), 4)]
    roster = defaultdict(list)
    try:
        d = json.load(gzip.open(os.path.join(C.HERE, 'cbb_prior.json.gz')))
        K = {k: i for i, k in enumerate(d['keep'])}
        ci = {k: i for i, k in enumerate(d['cols'])}
        for row, c in zip(d['rows'], d['careers']):
            last = [x for x in c['seasons'] if x[K['year']] == SEASON - 1]
            if c.get('bt') and last:
                roster[c['bt']].append([row[ci['name']], last[0][K['team']]])
    except Exception:
        pass
    return {'season': SEASON, 'teams': T, 'prevTeams': sorted(prev), 'pn': {t: [[p, v[p]] for p in sorted(v, key=pid_order)] for t, v in pn.items()},
            'val': {str(p): v for p, v in val.items()}, 'roster': dict(roster)}


def apply_report(snap, report):
    """the injury report on a snapshot: 'next' availability (avail(listed=...)) and injury-report (pre_out(listed=...))
    values by Barttorvik team, the matched listings, the missing-player lists shown on the game cards"""
    T = snap['teams']
    bt_teams = {NM.team_key(t): t for t in T if T[t]['k']}
    keys = {NM.team_key(t): t for t in set(snap['prevTeams']) | {t for t in T if T[t]['k']}}
    val = snap['val']
    listed, status, unmatched, logged, pre = defaultdict(dict), {}, [], [], defaultdict(dict)
    M, P = {}, {}
    def mt(t):
        if t not in M:
            M[t] = NM.Matcher([{'pid': p[0], 'name': p[1]} for p in T[t]['pl'] if p[1]], team=None, pos=None, sport='basketball')
        return M[t]
    def mp(t):
        if t not in P:
            P[t] = NM.Matcher([{'pid': p, 'name': n} for p, n in snap['pn'].get(t, [])], team=None, pos=None, sport='basketball')
        return P[t]
    for team, name, pos, stt, detail, when in report:
        sit = SIT.get(stt.lower())
        t = bt_teams.get(NM.team_key(team))
        if not t or sit is None:
            unmatched.append(f'{name} ({team}, {stt})')
        else:
            hit, _ = mt(t).find(name)
            if not hit:
                unmatched.append(f'{name} ({team}, {stt})')
            else:
                listed[t][hit['pid']] = sit
                status[(t, hit['pid'])] = stt if not detail else f'{stt} ({detail})'
                logged.append([t, hit['pid'], name, stt.lower()])
        # pre_listed(): last season's line, at this school, else at the school his board career lists
        t2 = keys.get(NM.team_key(team))
        if not t2 or sit is None:
            continue
        played = {p[0] for p in T.get(t2, {}).get('pl', []) if p[2]}
        hit, _ = mp(t2).find(name)
        if not hit:
            r, _ = NM.Matcher([{'pid': o, 'name': n} for n, o in snap['roster'].get(t2, [])], team=None, pos=None, sport='basketball').find(name)
            old = r and keys.get(NM.team_key(r['pid']))
            if old:
                hit, _ = mp(old).find(name)
        if hit and hit['pid'] not in played:
            pre[t2][hit['pid']] = sit
    inj, pinj, missing = {}, {}, {}
    for t, v in T.items():
        L = listed.get(t, {})
        s = 0.0
        if v['k'] >= 3:
            for pid, nm, pld, rot, u, run, mpg, bpm in v['pl']:
                if not u:
                    continue
                if pid in L:
                    s += L[pid] / C.SIT_AGAIN * u
                elif run:
                    s += u
        inj[t] = round(s, 3)
        miss = []
        for pid, nm, pld, rot, u, run, mpg, bpm in v['pl']:
            if not rot:
                continue
            if pid in L:
                why = status[(t, pid)]
            elif run:
                why = 'sat last game' if run == 1 else f'sat last {run} games'
            else:
                continue
            miss.append({'name': nm, 'st': why, 'mpg': mpg, 'bpm': bpm})
        if miss:
            missing[t] = sorted(miss, key=lambda x: -x['mpg'])
    for t in set(pre) | set(T):
        rp = T[t]['rp'] if t in T and T[t]['k'] >= 3 else -3.0
        pinj[t] = round(sum(f * max(0.0, val[str(p)][0] - rp) * val[str(p)][1] / 40 for p, f in pre.get(t, {}).items() if str(p) in val), 3)
    return {'inj': inj, 'pinj': pinj, 'missing': missing, 'listed': dict(listed), 'pre': dict(pre), 'logged': logged, 'unmatched': unmatched}


def avail_live():
    """this season's availability (value of rotation players who missed the team's last game or are listed on the
    injury report) and their names; the snapshot refresh_injuries() re-prices from"""
    logs = C.bt_logs(SEASON)
    report = covers_report()
    snap = avail_snapshot(logs)
    A = apply_report(snap, report)
    listed = A['listed']
    if report:
        print(f'cbb injuries: {len(report)} listed on Covers, {sum(len(v) for v in listed.values())} matched to Barttorvik players'
              + (f'; not matched: {", ".join(A["unmatched"][:12])}' if A['unmatched'] else ''))
        write_injuries(report)
        log_injuries(A['logged'])
    # 'pinj': the report's players who haven't played for the team yet this season, valued off last season's line
    # (matched among last season's Barttorvik players: at this school, else at the school his board career lists)
    pl = A['pre']
    if report:
        print(f'cbb injuries: {sum(len(v) for v in pl.values())} of the report not yet played this season, valued off last season (pinj)')
    C.PINJ.update(C.pre_out(logs, C.bt_logs(SEASON - 1), listed=pl))
    av = C.avail(logs, listed=listed) if logs else {}
    # the snapshot's 'next' values are the walk's (one reading of the logs, two code paths)
    bad = [t for t in snap['teams'] if abs(av.get((t, 'next'), 0.0) - A['inj'].get(t, 0.0)) > 1e-3
           or abs(C.PINJ.get((t, 'next'), 0.0) - A['pinj'].get(t, 0.0)) > 1e-3]
    if bad:
        print(f'cbb injuries: snapshot differs from the walk for {len(bad)} teams ({", ".join(bad[:5])})')
    snap['ok'] = not bad
    return av, A['missing'], snap


def write_injuries(report):
    """data/cbb_injuries.json, rewritten only when the list changes (the refresh runs every half hour)"""
    body = {'src': COVERS, 'players': [{'team': t, 'name': n, 'pos': ps, 'status': st, 'detail': d or None, 'news': w or None}
                                       for t, n, ps, st, d, w in report]}
    try:
        old = json.load(open(INJ_OUT))
        if old.get('players') == body['players']:
            return False
    except (OSError, ValueError):
        pass
    with open(INJ_OUT, 'w') as f:
        json.dump({'asof': now_utc().strftime('%Y-%m-%dT%H:%M:%SZ'), **body}, f, indent=0)
    return True


def build():
    F = json.load(open(C.FIT))
    st = json.load(open(C.STATE))
    P, feats, coef, sd = F['params'], F['feats'], F['coef'], F['sd']
    rows = update_log()
    hist = C.load_hist()
    btname = C.bt_map(hist)
    tp, bt_live, confs = C.team_prior_live(SEASON, btname)
    btname.update(bt_live)
    # D-I: the board's teams, plus last season's rated teams with a full D-I schedule this season (non-D-I opponents
    # play a handful of D-I games and share one rating)
    sched = defaultdict(int)
    for g in rows:
        sched[g['home']] += 1; sched[g['away']] += 1
    d1 = set(bt_live) | {t for t in st['final'] if sched[t] >= 20}
    # a school the board has no conference for takes its conference-game opponents' (ESPN flags conference games)
    opp = defaultdict(lambda: defaultdict(int))
    for g in rows:
        if g.get('conf'):
            opp[g['home']][confs.get(g['away'], '')] += 1; opp[g['away']][confs.get(g['home'], '')] += 1
    for t in d1:
        if not confs.get(t):
            c = {k: v for k, v in opp[t].items() if k}
            if c:
                confs[t] = max(c, key=c.get)
    W = C.Walk(P, {SEASON: tp}, btname, coefs={SEASON: F['prior']})
    for t, v in st['elo'].items():
        W.elo[t] = v
    for t, v in st['mkt'].items():
        W.mkt[t] = v
    W.tlg = st.get('tlg', 140.0)
    for t, v in st.get('tm', {}).items():          # last season's market totals, part carried in (P['tcar'])
        W.tm[t] = v
    W.final[SEASON - 1] = st['final']
    if st.get('xfinal'):
        W.xfinal[SEASON - 1] = st['xfinal']       # last season's pooled non-D-I rating (P['xcar'])
    W.attm[SEASON - 1] = st.get('att', {})         # last season's home crowds ('hatt')
    av, missing, asnap = avail_live()
    now = now_utc()
    today = C.et_date(now.strftime('%Y-%m-%dT%H:%M:%SZ'))
    dates = sorted({C.et_date(g['date']) for g in rows if C.et_date(g['date']) >= today and g['state'] != 'post'})
    show = set(dates[:PICKS_LEFT])
    upto = dates[PICKS_LEFT - 1] if len(dates) >= PICKS_LEFT else (dates[-1] if dates else None)
    proj = {}
    # ESPN BPI's forecast for the games on the page (the 'bpi' input; scripts/public_ratings.py)
    if 'bpi' in feats:
        import public_ratings
        from concurrent.futures import ThreadPoolExecutor
        ids = [str(g['id']) for g in rows if C.et_date(g['date']) in show and g['state'] == 'pre']
        with ThreadPoolExecutor(12) as ex:
            for gid, v in ex.map(public_ratings.bpi_one, ids):
                if v:
                    C.BPI[gid] = v

    # game-control ratings for this season's games (the 'gc' input; scripts/control_ratings.py)
    if 'gc' in feats or 'gm' in feats:
        import control_ratings
        try:
            for k, v in control_ratings.cbb_feat_live(rows, SEASON, [k for k in ('gc', 'gm') if k in feats]).items():
                C.GC[k].update(v)
        except Exception as e:                  # ESPN down: the input sits at 0 (a neutral matchup) for the day
            print('game control failed:', e, flush=True)

    def collect(g, x, tx, R):
        m = sum(coef[f] * x[f] for f in feats)
        tot = sum(F['tcoef'][f] * tx[f] for f in C.TFEATS)
        proj[g['id']] = (m, tot, x, R.poss(g['home'], g['away']))
    R, pri, pfeats = C.season_walk(W, SEASON, rows, d1, av, collect, upto=upto or '0000')
    if not R.nobs and not upto:
        R.solve(0)
    names, logos, abbr = {}, {}, {}
    for g in rows:
        for k in ('home', 'away'):
            names[g[k]] = g[k[0] + 'n']; abbr[g[k]] = g.get(k[0] + 'a') or g[k[0] + 'n'][:4].upper()
    board = json.load(open(os.path.join(C.ROOT, 'static', 'data', 'cbb-all.json')))
    bc = {k: i for i, k in enumerate(board['cols'])}
    best = {}
    for r in board['rows']:
        m = re.search(r'/(\d+)\.png', r[bc['logo']] or '')
        if m:
            logos[m[1]] = r[bc['logo']]
            if r[bc['fv']] and (m[1] not in best or r[bc['fv']] > best[m[1]]['fv']):
                best[m[1]] = {'name': r[bc['name']], 'pos': r[bc['pos']], 'fv': r[bc['fv']]}
    logo = lambda t: logos.get(t) or f'https://a.espncdn.com/i/teamlogos/ncaa/500/{t}.png'

    # power ratings: points against an average D-I team on a neutral floor, from the game model's weights: the
    # efficiency (its own weight plus BPI's, whose fallback with no ESPN forecast is the efficiency), Elo and the
    # long-memory margin rating (scripts/cbb_tourney.py team_rating, the tournament odds' rating), so a rating gap plus
    # the home edge is the game model's margin (slope ~1 on today's games)
    import cbb_tourney
    teams = sorted(t for t in d1 if t in R.ix)
    elo_avg = sum(W.elo[t] for t in teams) / len(teams)
    mkt_avg = sum(W.mkt[t] for t in teams) / len(teams)
    P0 = R.tau + float(np.mean([R.T[R.ix[t]] for t in teams])) * 2
    net_ = {t: float(R.net(t)) for t in teams}
    T_ = {t: float(R.T[R.ix[t]]) for t in teams}
    try:
        gm_t = cbb_tourney.live_gm(rows, SEASON) if 'gm' in feats else {}
    except Exception as e:            # history file missing: the margin rating sits at average for the day
        print('margin rating failed:', repr(e), flush=True)
        gm_t = {}
    gm_avg = float(np.mean([gm_t.get(t, 0.0) for t in teams]))
    rating = cbb_tourney.team_rating(net_, T_, float(R.tau), W.elo, gm_t, teams, coef)
    edge = lambda g: 0.0 if g['neutral'] else cbb_tourney.home_edge(coef, 1.0 if g.get('conf') else 0.0, g['home'])
    order = sorted(teams, key=lambda t: -rating[t])
    rk = {t: i + 1 for i, t in enumerate(order)}
    prior_rk = {t: i + 1 for i, t in enumerate(sorted(teams, key=lambda t: -pri.get(t, {}).get('net', -99)))}

    # records
    rec = defaultdict(lambda: [0, 0, 0, 0])
    for g in rows:
        if g.get('hs') is None:
            continue
        for t, w in ((g['home'], g['hs'] > g['as']), (g['away'], g['as'] > g['hs'])):
            rec[t][0 if w else 1] += 1
            if g.get('conf'):
                rec[t][2 if w else 3] += 1
    recs = lambda t: f'{rec[t][0]}-{rec[t][1]}'

    # season odds: the rest of the regular season simulated (conference tournaments and March left out); each team's
    # true strength drawn once a season around its rating, each game around its margin (the model's home court with BPI's,
    # conference-home and altitude terms). The strength sd: sqrt(SHOCK_A^2 x SHOCK_K / (SHOCK_K + games played) +
    # SHOCK_B^2 x share of its regular season left), the rating's error plus its drift over the games left
    # (scripts/cbb_games_research.py sims: past seasons from Dec 1, Jan 15 and Feb 15)
    reg = lambda g: (g['stype'] == 2 and 'tournament' not in (g.get('note') or '').lower()
                     and not (g.get('conf') and POSTSEASON.search(g.get('note') or '')))
    left = [g for g in rows if g.get('hs') is None and reg(g) and g['home'] in rk and g['away'] in rk]
    nreg = defaultdict(int)
    for g in rows:
        if reg(g) and g['home'] in rk and g['away'] in rk:
            nreg[g['home']] += 1; nreg[g['away']] += 1
    sims = {}
    if left:
        ti = {t: i for i, t in enumerate(teams)}
        hi = np.array([ti[g['home']] for g in left]); ai = np.array([ti[g['away']] for g in left])
        cf = np.array([1.0 if g.get('conf') else 0.0 for g in left])
        mm = np.array([rating[g['home']] - rating[g['away']] + edge(g) for g in left])
        nleft = defaultdict(int)
        for g in left:
            nleft[g['home']] += 1; nleft[g['away']] += 1
        tsd = np.array([math.sqrt(SHOCK_A ** 2 * SHOCK_K / (SHOCK_K + R.ng[t]) + SHOCK_B ** 2 * nleft[t] / max(1, nreg[t])) for t in teams])
        rng = np.random.default_rng(int(now.strftime('%Y%m%d')))
        W_, CW, CL, title = np.zeros(len(teams)), np.zeros(len(teams)), np.zeros(len(teams)), np.zeros(len(teams))
        conf_of = np.array([confs.get(t, '') for t in teams])
        base_cw = np.array([rec[t][2] for t in teams], float); base_cl = np.array([rec[t][3] for t in teams], float)
        for chunk in range(SIMS // 1000):
            shock = rng.normal(0, 1, (1000, len(teams))) * tsd
            m = mm + shock[:, hi] - shock[:, ai]
            hw = (m + rng.normal(0, sd, m.shape)) > 0
            w = np.zeros((1000, len(teams))); cw = np.zeros((1000, len(teams))); cl = np.zeros((1000, len(teams)))
            for arr, idx, val in ((w, hi, hw), (w, ai, ~hw)):
                np.add.at(arr, (slice(None), idx), val.astype(float))
            np.add.at(cw, (slice(None), hi), (hw * cf)); np.add.at(cw, (slice(None), ai), (~hw * cf))
            np.add.at(cl, (slice(None), hi), (~hw * cf)); np.add.at(cl, (slice(None), ai), (hw * cf))
            W_ += w.sum(0); CW += cw.sum(0); CL += cl.sum(0)
            pct = (base_cw + cw) - (base_cl + cl)
            for c in set(conf_of):
                if not c:
                    continue
                k = conf_of == c
                top = pct[:, k].max(1, keepdims=True)
                title[k] += (pct[:, k] >= top - 1e-9).sum(0)
        for t, i in ti.items():
            sims[t] = {'xW': rec[t][0] + W_[i] / SIMS, 'xL': rec[t][1] + (sum(1 for g in left if t in (g['home'], g['away'])) - W_[i] / SIMS),
                       'cxW': rec[t][2] + CW[i] / SIMS, 'cxL': rec[t][3] + CL[i] / SIMS, 'title': title[i] / SIMS}

    power = []
    for t in order:
        k = R.ix[t]
        s = sims.get(t, {})
        power.append({'rk': rk[t], 'id': t, 't': names.get(t, t), 'logo': logo(t), 'conf': confs.get(t, ''),
                      'rating': round(rating[t], 1), 'off': round(float(R.mu + R.O[k]), 1), 'def': round(float(R.mu - R.D[k]), 1),
                      'tempo': round(float(R.tau + R.T[k]), 1), 'elo': round(W.elo[t]), 'mkt': round(W.mkt[t] - mkt_avg, 1),
                      'prior': round(pri.get(t, {}).get('net', 0.0), 1), 'priorRk': prior_rk.get(t), 'rec': recs(t),
                      'crec': f'{rec[t][2]}-{rec[t][3]}', 'xW': round(s['xW'], 1) if s else None, 'xL': round(s['xL'], 1) if s else None,
                      'cxW': round(s['cxW'], 1) if s else None, 'cxL': round(s['cxL'], 1) if s else None,
                      'title': round(s['title'], 3) if s else None, 'g': R.ng[t]})
    # NCAA tournament odds (scripts/cbb_tourney.py): conference tournaments, the committee, the bracket
    tmeta = None
    try:
        nc, tmeta = cbb_tourney.live(rows, set(teams), confs, net_, T_, float(R.tau), W.elo, R.ng, coef, sd, SEASON,
                                     gm=gm_t if 'gm' in feats else None)
        for r in power:
            if r['id'] in nc:
                r['nc'] = nc[r['id']]
    except Exception as e:            # the odds sit out a day rather than stop the build
        print('tournament odds failed:', repr(e), flush=True)
    import rank_odds                  # 80% rank range and P(#1 / top 4 / top 25) from the measured rating sd
    rank_odds.add(power, 'cbb', lambda r: 1 - min(1.0, r['g'] / 31))

    # team breakdowns for the power rankings' dropdowns (scripts/team_detail.py, display only): the rating split into
    # the preseason prior's roster terms, this season's results (the efficiency solve's move off the prior) and Elo,
    # each against an average D-I team; the schedule with each game left at the season sims' margin
    try:
        import team_detail
        pc = W.prior_coef(SEASON)
        ce, sc = coef.get('eff', 0.0) + coef.get('bpi', 0.0), P0 / 100
        pn = {t: pri.get(t, {}).get('net', 0.0) for t in teams}
        pf = [k for k in C.PRIOR_F if k not in ('one', 'nohist')]
        fm = {k: float(np.mean([pfeats[t].get(k, 0.0) for t in teams if t in pfeats])) for k in pf} if pfeats else {}
        pn_m = float(np.mean([pn[t] for t in teams]))
        res_m = float(np.mean([R.net(t) - pn[t] for t in teams]))
        TD = {}
        for t in teams:
            pp = [[k, round(ce * sc * pc.get(k, 0.0) * (pfeats[t].get(k, 0.0) - fm[k]), 2)] for k in pf] if t in pfeats else []
            known = sum(v for _, v in pp)
            rest_ = ce * sc * (pn[t] - pn_m) - known
            if abs(rest_) >= 0.05:
                pp.append(['other', round(rest_, 2)])
            parts = [['prior', round(ce * sc * (pn[t] - pn_m), 2)], ['results', round(ce * sc * (R.net(t) - pn[t] - res_m), 2)],
                     ['elo', round(coef.get('elo', 0.0) * (W.elo[t] - elo_avg) / 25, 2)]]
            if coef.get('gm'):
                parts.append(['gm', round(coef['gm'] * (gm_t.get(t, 0.0) - gm_avg), 2)])
            TD[t] = {'parts': parts, 'pparts': pp}
        sg = []
        for g in rows:
            if g['home'] not in rk and g['away'] not in rk or g['stype'] not in (2, 3):
                continue
            d = C.et_date(g['date'])
            if g.get('hs') is not None:
                sg.append({'d': d, 'h': g['home'], 'a': g['away'], 'n': g['neutral'], 'hs': g['hs'], 'as': g['as']})
                continue
            if g['id'] in proj:
                m = proj[g['id']][0]
            elif g['home'] in rk and g['away'] in rk:
                m = rating[g['home']] - rating[g['away']] + edge(g)
            else:
                m = None
            sg.append({'d': d, 'h': g['home'], 'a': g['away'], 'n': g['neutral'], 'm': m, 'p': None if m is None else float(C.phi(m / sd))})
        for t, s in team_detail.schedules(sg, teams).items():
            TD[t]['sch'] = s
        team_detail.save('cbb', TD, names={t: names.get(t, t) for g in sg for t in (g['h'], g['a']) if t not in rk}, asof=now.strftime('%Y-%m-%dT%H:%M:%SZ'))
    except Exception as e:            # the dropdowns keep yesterday's file rather than stop the build
        print('team breakdowns failed:', repr(e), flush=True)

    # the slates
    labels = {'eff': 'efficiency', 'elo': 'Elo', 'mkt': 'market', 'home': 'home court', 'inj': 'availability', 'pinj': 'injury report', 'rest': 'rest',
              'confh': 'conference home', 'alt': 'altitude', 'early': 'preseason prior', 'tourn': 'tournament', 'form': 'form', 'mkteff': 'early market', 'bpi': 'ESPN BPI', 'gc': 'game control', 'gm': 'long-memory margin', 'hatt': 'home crowd'}
    # Novig's main lines at its asks first; ESPN's DraftKings where Novig has none
    try:
        import novig
        NV = novig.prices('cbb')
    except Exception as e:
        print('novig:', e); NV = {}
    out_games = []
    for g in rows:
        d = C.et_date(g['date'])
        if d not in show or g['id'] not in proj:
            continue
        m, tot, x, poss = proj[g['id']]
        px = NV.get(str(g['id']))
        if px:
            g = {**g, 'spread': -px['L'] if px.get('L') is not None else g.get('spread'), 'total': px.get('T') or g.get('total'),
                 'mlh': px.get('mlH') or g.get('mlh'), 'mla': px.get('mlA') or g.get('mla'), 'book': 'Novig'}
        L = -g['spread'] if g.get('spread') is not None else None
        ph = C.phi(m / sd)
        side = lambda k: {'id': g[k], 'n': names.get(g[k], g[k]), 'ab': abbr.get(g[k]), 'logo': logo(g[k]), 'rec': recs(g[k]),
                          'rk': rk.get(g[k]), 'ap': g.get(k[0] + 'ap'), 'conf': confs.get(g[k], ''), 'best': best.get(g[k])}
        item = {'id': g['id'], 'date': d, 'kick': iso(g['date']), 'home': side('home'), 'away': side('away'), 'neutral': g['neutral'],
                'tba': g.get('tba') or None, 'confGame': g.get('conf'), 'note': g.get('note') or None, 'venue': g.get('venue'), 'tv': g.get('tv') or None,
                'margin': round(m, 1), 'total': round(tot, 1), 'pHome': round(ph, 3), 'poss': round(poss, 1),
                'hs': round((tot + m) / 2), 'as': round((tot - m) / 2), 'line': L, 'tline': g.get('total'),
                'ml': {'home': g.get('mlh'), 'away': g.get('mla')} if g.get('mlh') else None, 'book': g.get('book'),
                'edge': round(m - L, 1) if L is not None else None,
                'parts': {labels[f]: round(coef[f] * x[f], 1) for f in feats if abs(coef[f] * x[f]) >= 0.5},
                'q': (rk.get(g['home'], 400) + rk.get(g['away'], 400))}
        for k in ('home', 'away'):
            mi = missing.get(btname.get(g[k]))
            if mi and g.get('hs') is None:
                item[k[0] + 'out'] = mi[:3]
        if g.get('hs') is not None:
            item['final'] = {'home': g['hs'], 'away': g['as']}
        else:
            # what refresh_injuries() re-prices from: the teams, possessions, margin, the two injury inputs, total
            asnap.setdefault('games', {})[str(g['id'])] = [btname.get(g['home']), btname.get(g['away']), round(poss, 4), round(m, 6),
                                                         round(x.get('inj', 0.0), 6), round(x.get('pinj', 0.0), 6), round(tot, 6)]
        out_games.append(item)
    out_games.sort(key=lambda z: (z['date'], z['q'], z['kick']))
    # model against the line this season, games already played (pregame margin, close)
    ats = [0, 0, 0]
    for g in rows:
        if g.get('hs') is None or g['id'] not in proj or g.get('spread') is None:
            continue
        m = proj[g['id']][0]; L = -g['spread']; r = g['hs'] - g['as']
        if abs(m - L) < 1 or r == L:
            ats[2] += r == L
            continue
        ats[0 if (m - L > 0) == (r - L > 0) else 1] += 1
    res = {'asof': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'season': f'{SEASON - 1}-{str(SEASON)[2:]}', 'sd': sd, 'tsd': F['tsd'],
           'dates': sorted(show), 'games': out_games, 'power': power, 'sims': SIMS if sims else 0, 'left': len(left),
           'ats': {'w': ats[0], 'l': ats[1]}, 'played': sum(1 for g in rows if g.get('hs') is not None),
           'test': F['test'], 'coef': coef, 'feats': feats, 'tourney': tmeta}
    old = None
    try:
        old = json.load(open(C.OUT))
    except (OSError, ValueError):
        pass
    # rank movement, the CFB board's window (a week): the ARK ranking kept on each change; the move is against the
    # ranking as of 7 days ago, or the preseason prior rank before the season is a week old
    import datetime as _dt
    day = now.date()
    hist = {k: v for k, v in ((old or {}).get('rkHist') or {}).items() if k >= f'{SEASON - 1}-08-01'}
    cur = {r['id']: r['rk'] for r in power}
    if not hist or hist[max(hist)] != cur:          # stored only on change, so a quiet day writes nothing
        hist[day.isoformat()] = cur
    cut = (day - _dt.timedelta(days=7)).isoformat()
    back = [k for k in sorted(hist) if k <= cut]
    hist = {k: hist[k] for k in sorted(hist) if k > cut or (back and k == back[-1])}
    snap = hist[back[-1]] if back else None
    for r in power:
        r['prev'] = snap.get(r['id']) if snap else r.get('priorRk')
    res['prevFrom'] = back[-1] if back else 'preseason'
    res['rkHist'] = hist
    if old and {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in res.items() if k != 'asof'})):
        print('cbb games: no change')
    else:
        with open(C.OUT, 'w') as f:
            json.dump(res, f, separators=(',', ':'))
        print(f'cbb games: {len(out_games)} games on {sorted(show)}, {len(power)} teams rated, {len(left)} games simulated')
    save_snap(asnap)


def smoke():
    """the availability snapshot as a runner builds it (python3 scripts/cbb_games.py --smoke, run by the build gate):
    Barttorvik answers with a page, so this season's file is missing and the ESPN fill gives the players it cannot
    match 'e<id>' string ids next to Barttorvik's int pids; the snapshot, its JSON round trip and apply_report() run
    on that mix with no network"""
    import tempfile
    saved = C.BTLOG, C.bt_logs
    try:
        C.BTLOG = tempfile.mkdtemp(prefix='cbb-smoke-')
        C.bt_logs = lambda s: {'Duke': [('2026-03-01', {101: (30.0, 9.0), 'e555': (260.0, 4.0)})]}
        logs = {'Duke': [(f'2026-11-0{i}', {101: (30.0, 6.0), 102: (20.0, 0.0), 'e900': (28.0, 3.5), 'e77': (14.0, -1.0)})
                         for i in range(1, 5)] + [('2026-11-05', {101: (30.0, 6.0), 102: (20.0, 0.0)})]}
        snap = avail_snapshot(logs)
        snap = json.loads(json.dumps(snap, separators=(',', ':'), sort_keys=True))
        pids = [p[0] for p in snap['teams']['Duke']['pl']]
        assert pids == [101, 102, 'e77', 'e900'], pids
        A = apply_report(snap, [])
        assert A['inj']['Duke'] > 0 and A['missing']['Duke'][0]['st'] == 'sat last game', A
    finally:
        C.BTLOG, C.bt_logs = saved
    print(f'cbb smoke: snapshot of {len(pids)} players (int and ESPN string ids), inj {A["inj"]["Duke"]}: ok')


def save_snap(snap):
    """the snapshot in its two files, each written only when its content changed (gzip with no timestamp)"""
    snap = {k: v for k, v in snap.items() if not k.startswith('_')}
    for path, part in ((SNAP, {k: v for k, v in snap.items() if k not in PREV_KEYS}), (SNAP_PREV, {k: snap[k] for k in PREV_KEYS if k in snap})):
        body = json.dumps(part, separators=(',', ':'), sort_keys=True).encode()
        try:
            if gzip.open(path).read() == body:
                continue
        except (OSError, EOFError):
            pass
        with open(path, 'wb') as f, gzip.GzipFile(fileobj=f, mode='wb', mtime=0) as z:
            z.write(body)


def load_snap():
    snap = json.load(gzip.open(SNAP))
    snap.update(json.load(gzip.open(SNAP_PREV)))
    return snap


INJ_LABELS = {'inj': 'availability', 'pinj': 'injury report'}


def refresh_injuries():
    """re-price the slate on the newest injury report between builds (python3 scripts/cbb_games.py --injuries; run by
    scripts/picks_refresh.py every odds-snap tick, before the picks): Covers' report with RotoWire's news merged in,
    read on the last build's snapshot (scripts/data/cbb_avail_snap.json.gz + cbb_avail_prev.json.gz), the 'inj' and 'pinj' inputs recomputed for
    every game not yet tipped, the margin moved by the fitted weights on the change. Ratings, lines and everything else
    stay the build's until the next one. Writes data/cbb_games.json only when a game changed"""
    try:
        snap, res = load_snap(), json.load(open(C.OUT))
    except (OSError, ValueError, EOFError) as e:
        print('cbb injuries refresh: no snapshot or games file:', e)
        return 0
    if snap.get('season') != SEASON or not snap.get('ok') or not snap.get('games'):
        print('cbb injuries refresh: snapshot not usable (season, parity or no games), left to the build')
        return 0
    report = covers_report()
    if not report:
        print('cbb injuries refresh: no report read, the build\'s numbers stay')
        return 0
    A = apply_report(snap, report)
    coef, sd = res['coef'], res['sd']
    now = now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')
    n = 0
    for i, item in enumerate(res['games']):
        gs = snap['games'].get(str(item['id']))
        if not gs or item.get('final') or (item.get('kick') or '') <= now:
            continue
        hb, ab, poss, m0, xi0, xp0, tot = gs
        x = {'inj': (A['inj'].get(ab, 0.0) - A['inj'].get(hb, 0.0)) * poss / 100,
             'pinj': (A['pinj'].get(ab, 0.0) - A['pinj'].get(hb, 0.0)) * poss / 100}
        m = m0 + coef.get('inj', 0.0) * (x['inj'] - xi0) + coef.get('pinj', 0.0) * (x['pinj'] - xp0)
        new = dict(item, margin=round(m, 1), pHome=round(C.phi(m / sd), 3),
                   hs=round((tot + m) / 2), **{'as': round((tot - m) / 2)})
        if item.get('line') is not None:
            new['edge'] = round(m - item['line'], 1)
        parts = {k: v for k, v in (item.get('parts') or {}).items() if k not in INJ_LABELS.values()}
        for f, lab in INJ_LABELS.items():
            if f in coef and abs(coef[f] * x[f]) >= 0.5:
                parts[lab] = round(coef[f] * x[f], 1)
        new['parts'] = parts
        for k, b in (('home', hb), ('away', ab)):
            new.pop(k[0] + 'out', None)
            mi = A['missing'].get(b)
            if mi:
                new[k[0] + 'out'] = mi[:3]
        if new != item:
            res['games'][i] = new
            n += 1
    wrote = write_injuries(report)
    log_injuries(A['logged'])
    if n:
        res['injAsof'] = now
        with open(C.OUT, 'w') as f:
            json.dump(res, f, separators=(',', ':'))
    print(f'cbb injuries refresh: {len(report)} listed, {n} games re-priced' + ('' if wrote else ', report unchanged'))
    return n
