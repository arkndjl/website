#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Team special teams rating (Noah, Nov 2 2026: "incorporate all special teams value as team badges and into the game
model; in the special teams tab, a team ranking of who has the best special teams"; FG and punt blocks included).

    python3 scripts/st_teams.py events nfl|cfb     # play-by-play -> per game, each side's units (cache)
    python3 scripts/st_teams.py research nfl|cfb   # badge + rating tests -> data/st_teams_research.json
    python3 scripts/st_teams.py build nfl|cfb      # this season's team table -> data/st_teams_<sport>.json

Every special teams snap is valued in points, and each unit is credited only with what it controls:
  kr / pr   returns: value of the return minus the mean return fielded at the same spot (5-yard bins, by season and
            kick type), the same expected as the returner tab (scripts/st_returners.py)
  cov       coverage: minus the opponent's return over expected on this team's kickoffs and punts
  ko        kickoffs: the kicking side's value of the kick before the return (touchbacks, fair catches, out of bounds,
            hang and distance), against the league's average kickoff
  punt      punting: the same for punts, against the league's average punt from that line of scrimmage
  fg        field goals and extra points over the make rate from that distance (unblocked kicks)
  blk       blocks: punts, field goals and extra points this team blocked, minus its own kicks blocked, each worth
            the swing against an average kick from that spot
NFL values are nflverse EPA. CFB has no EPA: points use drive points by field position (mean points on drives
starting x yards from the goal, ESPN drives of the season and the one before; a TD 7, a lost ball the other side's
drive), a field goal 3 x (made - make rate at that distance), an extra point 1 x (made - make rate). Plays with an
accepted penalty and onside kicks are left out (the call decides those).

Per game: ST points over expected = the sum of the units. The rating is that per game, season to date, shrunk to half
last season's team rate and half the league's worth n0 games (n0 from split-half reliability, the team badge recipe in
scripts/team_badges.py).

Results (Nov 2 2026, data/st_teams_research.json, data/st_teams_nfl_model.json):
  badge    PASSES both sports: midpoint rating vs the rest of the season's ST points, NFL r .30 (2015-21) / .22 (2022-26),
           CFB .31 / .31 (2017-22 / 2023-26). Shown as the Special Teams team badge (team_badges_build.st_badges).
           Units alone: kickoffs and punting repeat (NFL r .23-.29, CFB .24-.43); returns, coverage, FG and blocks
           barely do (blocks NFL held r -.10). n0: NFL 26 games, CFB 17.
  model    FAILS both. vs the close (home minus away, points): NFL tune t 1.7, held t 0.8, held error no gain; CFB tune
           t 0.8, held t 2.3 (held SE t -2.2): held only, a re-score lead. NFL walk-forward (nfl_games params, 2015-20 /
           2021-25 MAE): adding it +.056 / +.012, in place of 'ret' +.054 / +.030, non-return units beside 'ret'
           +.043 / +.008. No unit passes alone (BH over 17 tests a sport).
"""
import collections
import csv
import datetime
import gzip
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

CACHE = os.path.join(HERE, '.cache', 'st')
UNITS = ['kr', 'pr', 'cov', 'ko', 'punt', 'fg', 'blk']
FRANCHISE = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA'}
BIN = 5


def season_now():
    d = datetime.date.today()
    return d.year if d.month >= 8 else d.year - 1


def f(x, d=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except (TypeError, ValueError):
        return d


def tm(t):
    return FRANCHISE.get(t, t)


def spot_expect(plays, key):
    """mean of 'v' by (season, kind, bin of plays[key]); thin bins borrow from all seasons. Sets p['e']."""
    S, A = collections.defaultdict(lambda: [0, 0.0]), collections.defaultdict(lambda: [0, 0.0])
    b = lambda p: int(max(0, min(110, p[key])) // BIN)
    for p in plays:
        for D, k in ((S, (p['s'], p['k'], b(p))), (A, (p['k'], b(p)))):
            D[k][0] += 1; D[k][1] += p['v']
    for p in plays:
        n, v = S[(p['s'], p['k'], b(p))]
        n2, v2 = A[(p['k'], b(p))]
        w = min(1.0, n / 25)
        p['e'] = w * v / max(n, 1) + (1 - w) * v2 / max(n2, 1)


# ------------------------------------------------------------------ NFL
def nfl_events(first=2013, last=None, save=True):
    import nfl_war as W
    last = last or season_now()
    games = {}      # gid -> {'S', 'wk', 'h', 'a', 'date', units h/a}
    kicks = []      # kickoffs and punts: dict(s, k, gid, kick team, recv team, epa, catch, ret, los)
    for s in range(first, last + 1):
        p = W.get(f'play_by_play_{s}.csv.gz', f'{W.REL}/pbp/play_by_play_{s}.csv.gz', fresh=(s == last and '--fresh' in sys.argv))
        rd = csv.reader(gzip.open(p, 'rt', encoding='utf-8'))
        h = next(rd); I = {c: i for i, c in enumerate(h)}
        g = lambda r, c: r[I[c]]
        for r in rd:
            gid = g(r, 'game_id')
            if gid not in games:
                games[gid] = {'S': s, 'wk': int(g(r, 'week')), 'h': tm(g(r, 'home_team')), 'a': tm(g(r, 'away_team')),
                              'date': g(r, 'game_date'), 'u': {'h': collections.defaultdict(float), 'a': collections.defaultdict(float)},
                              'n': collections.Counter()}
            pt = g(r, 'play_type')
            ko, pu = g(r, 'kickoff_attempt') == '1', g(r, 'punt_attempt') == '1'
            fg, xp = g(r, 'field_goal_attempt') == '1', g(r, 'extra_point_attempt') == '1'
            if not (ko or pu or fg or xp) or pt not in ('kickoff', 'punt', 'field_goal', 'extra_point'):
                continue
            if g(r, 'penalty') == '1' or 'onside' in g(r, 'desc').lower():
                continue
            epa = f(g(r, 'epa'))
            pos, de = tm(g(r, 'posteam')), tm(g(r, 'defteam'))
            if epa is None or not pos or not de:
                continue
            G = games[gid]
            side = lambda t: 'h' if t == G['h'] else 'a' if t == G['a'] else None
            if fg or xp:
                blocked = (g(r, 'field_goal_result') if fg else g(r, 'extra_point_result')) == 'blocked'
                if blocked:
                    if side(pos) and side(de):
                        G['u'][side(pos)]['blk'] += epa; G['u'][side(de)]['blk'] -= epa
                        G['n']['blk'] += 1
                elif side(pos):
                    G['u'][side(pos)]['fg'] += epa
                continue
            if pu and g(r, 'punt_blocked') == '1':
                if side(pos) and side(de):
                    G['u'][side(pos)]['blk'] += epa; G['u'][side(de)]['blk'] -= epa
                    G['n']['blk'] += 1
                continue
            yl, dist = f(g(r, 'yardline_100')), f(g(r, 'kick_distance'))
            kick, recv = (de, pos) if ko else (pos, de)
            # the kicking side's EPA: nflverse posteam receives a kickoff and kicks a punt
            kv = -epa if ko else epa
            rid = g(r, 'kickoff_returner_player_id' if ko else 'punt_returner_player_id')
            fair = g(r, 'kickoff_fair_catch' if ko else 'punt_fair_catch') == '1'
            ret = rid not in ('', 'NA') and not fair and g(r, 'touchback') != '1' and yl is not None and dist is not None
            catch = (yl + dist if ko else 100 - (yl - dist)) if ret else None
            kicks.append({'s': s, 'k': 'kr' if ko else 'pr', 'gid': gid, 'kick': kick, 'recv': recv, 'kv': kv,
                          'ret': ret, 'catch': catch, 'v': -kv})
    rets = [k for k in kicks if k['ret']]
    spot_expect(rets, 'catch')
    for k in kicks:
        G = games[k['gid']]
        sk = 'h' if k['kick'] == G['h'] else 'a' if k['kick'] == G['a'] else None
        sr = 'h' if k['recv'] == G['h'] else 'a' if k['recv'] == G['a'] else None
        if not sk or not sr:
            continue
        r = (k['v'] - k['e']) if k['ret'] else 0.0      # return over expected, receiving side
        G['u'][sr][k['k']] += r
        G['u'][sk]['cov'] -= r
        G['u'][sk]['ko' if k['k'] == 'kr' else 'punt'] += k['kv'] + r
        G['n'][k['k']] += 1
    return finish('nfl', games, save)


def finish(sport, games, save=True):
    """centre each unit on the league's per-game mean by season (kick EPA isn't zero-mean), then cache"""
    mean = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0]))
    for G in games.values():
        for s in ('h', 'a'):
            for u in UNITS:
                m = mean[G['S']][u]; m[0] += G['u'][s][u]; m[1] += 1
    out = []
    for gid, G in games.items():
        sides = {}
        for s in ('h', 'a'):
            d = {u: round(G['u'][s][u] - mean[G['S']][u][0] / max(1, mean[G['S']][u][1]), 4) for u in UNITS}
            d['st'] = round(sum(d[u] for u in UNITS), 4)
            sides[s] = d
        out.append({'gid': gid, 'S': G['S'], 'wk': G.get('wk', 0), 'date': G['date'], 'h': G['h'], 'a': G['a'],
                    'sh': sides['h'], 'sa': sides['a'], 'nb': G['n'].get('blk', 0)})
    out.sort(key=lambda e: (e['date'], e['gid']))
    if not save:
        return out
    os.makedirs(CACHE, exist_ok=True)
    with gzip.open(os.path.join(CACHE, f'{sport}_st.json.gz'), 'wt') as fh:
        json.dump(out, fh)
    by = collections.defaultdict(list)
    for e in out:
        by[e['S']].append(e)
    for S in sorted(by):
        xs = [e[k]['st'] for e in by[S] for k in ('sh', 'sa')]
        m = sum(xs) / len(xs); sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))
        print(sport, S, len(by[S]), 'games, ST pts/g sd', round(sd, 2), 'blocks', sum(e['nb'] for e in by[S]), flush=True)
    return out


# ------------------------------------------------------------------ CFB
def cfb_events(first=2016, last=None, save=True):
    import cfb_espn_hist as EH
    last = last or season_now()
    PBP = os.path.join(EH.DIR, '..', 'espn_pbp')
    games, loaded = {}, {}
    for s in range(first, last + 1):
        gp = os.path.join(EH.DIR, f'games{s}.json')
        if not os.path.exists(gp):
            continue
        for g in json.load(open(gp)):
            p = os.path.join(PBP, f"{g['id']}.json.gz")
            if g.get('done') and os.path.exists(p):
                games[str(g['id'])] = (s, g)
    # drive points by start (yards to goal), per season and the one before (as st_returners)
    dpts = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0]))
    for gid, (s, g) in games.items():
        d = json.load(gzip.open(os.path.join(PBP, f'{gid}.json.gz'), 'rt'))
        loaded[gid] = d
        for dr in d['drives']:
            pl = [p for p in dr['plays'] if not re.match(r'(Kickoff|Punt|Blocked Punt|Extra Point|Two)', p.get('t') or '')]
            if not pl or pl[0].get('dn') != 1 or not pl[0].get('yl') or str(pl[0].get('st')) != str(dr.get('tm')):
                continue
            res = (dr.get('res') or '').upper()
            pts = 7 if ('TD' in res or 'TOUCHDOWN' in res) else 3 if res in ('FG', 'FIELD GOAL', 'FG GOOD') else 0
            if 'MISSED' in res:
                pts = 0
            x = int(pl[0]['yl'])
            if 1 <= x <= 99:
                dpts[s][x][0] += 1; dpts[s][x][1] += pts
    curves = {}
    for s in sorted(dpts):
        D = {}
        for x in range(1, 100):
            n = v = 0
            for ss in (s, s - 1):
                for z in range(x - 4, x + 5):
                    if z in dpts.get(ss, {}):
                        n += dpts[ss][z][0]; v += dpts[ss][z][1]
            D[x] = v / n if n else None
        xs = [x for x in D if D[x] is not None]
        for x in range(1, 100):
            if D[x] is None:
                D[x] = D[min(xs, key=lambda z: abs(z - x))]
        for x in range(2, 100):
            D[x] = min(D[x], D[x - 1])
        D[0] = 7.0
        curves[s] = D
    KD = re.compile(r"(?:kickoff|punt)\s+(?:for\s+)?(\d+)\s+(?:yards?|yds?)", re.I)
    FGD = re.compile(r"(\d+)\s*(?:yd|yds|yard|yards)?\s*(?:field goal|FG)", re.I)
    RX = re.compile(r"returns?\s+(?:for\s+)?(-?\d+)\s+(?:yards?|yds?)|(-?\d+)\s+Yd\s+(?:Kickoff|Punt)\s+Return", re.I)
    kicks, fgs, xps, blks = [], [], [], []
    meta = {}
    for gid, (s, g) in games.items():
        d = loaded[gid]
        ha = {t.get('ha'): str(t.get('id')) for t in d.get('teams') or []}
        if 'home' not in ha or 'away' not in ha:
            continue
        meta[gid] = {'S': s, 'h': ha['home'], 'a': ha['away'], 'date': (d.get('date') or g.get('date') or '')[:10], 'wk': g.get('w', 0)}
        D = curves[s]
        val = lambda yl: D[max(1, min(99, int(yl)))]
        flat = [p for dr in d['drives'] for p in dr['plays']]
        SKIP = ('Kickoff', 'Punt', 'Blocked', 'Penalty', 'Timeout', 'End ', 'Extra', 'Two', 'Field Goal', 'Missed Field', 'Coin')

        def after(i):
            # the next snap from scrimmage: (offense, yards to goal). ESPN's end-of-play spot flips sides in some seasons
            # (2023 touchbacks at 25 and 75), the next snap's spot doesn't
            for q in flat[i + 1:i + 6]:
                tq = q.get('t') or ''
                if tq.startswith(SKIP) or not q.get('yl') or q.get('dn') not in (1, '1'):
                    continue
                return str(q.get('st') or ''), int(q['yl'])
            return None, None
        for i, p in enumerate(flat):
            if True:
                t = p.get('t') or ''; x = p.get('x') or ''; X = x.upper()
                st, et = str(p.get('st') or ''), str(p.get('et') or '')
                if st not in (ha['home'], ha['away']):
                    continue
                op = ha['away'] if st == ha['home'] else ha['home']
                pen = p.get('pen') or 'PENALTY' in X
                # extra points ride on the scoring row: "(Name KICK)", "(Name PAT MISSED / failed / BLOCKED)"
                m = re.search(r'\(([^()]*\b(?:KICK|PAT)\b[^()]*)\)', x, re.I)
                if m and p.get('sc') and 'TWO' not in m.group(1).upper():
                    note = m.group(1).upper()
                    scorer = st
                    if any(w in t for w in ('Return', 'Interception', 'Fumble', 'Blocked', 'Safety')):
                        scorer = et if et in (ha['home'], ha['away']) else st     # a defensive or return score
                    if 'BLOCK' in note:
                        blks.append({'gid': gid, 'kick': scorer, 'kind': 'xp', 's': s})
                    else:
                        xps.append({'gid': gid, 'team': scorer, 'ok': not re.search(r'MISS|FAIL|NO GOOD', note), 's': s})
                if pen and not t.startswith(('Field Goal', 'Blocked', 'Missed Field')):
                    continue
                if 'onside' in x.lower():
                    continue
                if t.startswith('Blocked Field Goal') or (t.startswith('Field Goal') and 'BLOCKED' in X):
                    m = FGD.search(x)
                    dist = int(m.group(1)) if m else (int(p['yl']) + 17 if p.get('yl') else None)
                    if dist:
                        blks.append({'gid': gid, 'kick': st, 'dist': dist, 'kind': 'fg', 's': s,
                                     'td': 1 if p.get('sc') and et != st else 0})
                    continue
                if t.startswith('Field Goal') or t == 'Missed Field Goal Return':
                    m = FGD.search(x)
                    dist = int(m.group(1)) if m else (int(p['yl']) + 17 if p.get('yl') else None)
                    if dist and 17 <= dist <= 70:
                        fgs.append({'gid': gid, 'team': st, 'dist': dist, 'ok': 'GOOD' in t.upper() or ('GOOD' in X and 'NO GOOD' not in X), 's': s})
                    continue
                if t.startswith('Blocked Punt'):
                    los = p.get('yl')
                    if not los:
                        continue
                    # the blocking side's value: a TD 7, else the ball near the line of scrimmage
                    v = 7.0 if (p.get('sc') or 'TOUCHDOWN' in X) else val(100 - int(los))
                    blks.append({'gid': gid, 'kick': st, 'los': int(los), 'v': v, 'kind': 'punt', 's': s})
                    continue
                ko, pu = t.startswith('Kickoff'), t.startswith('Punt')
                if not (ko or pu) or not p.get('yl'):
                    continue
                # values from the text alone (ESPN's end-of-play spot flips sides in some seasons and its play order is
                # scrambled in some games): catch spot = 100 - kick spot + distance, end = catch - return yards
                kick, recv = st, op
                yl = int(p['yl']); xl = x.lower()
                kd = KD.search(x)
                m = RX.search(x)
                ry = int(m.group(1) or m.group(2)) if m else 0
                tdr = bool(p.get('sc')) and ('Touchdown' in t or 'TOUCHDOWN' in X)
                if 'touchback' in xl:
                    c, end = None, (75 if ko else 80)
                elif kd:
                    c = 100 - yl + int(kd.group(1))
                    if c > 100 and not m:
                        c, end = None, (75 if ko else 80)
                    elif ko and ('out-of-bounds' in xl or 'out of bounds' in xl) and not m:
                        end = 65
                    elif 'fair catch' in xl:
                        end = min(c, 75) if ko else c
                    else:
                        end = c - ry
                elif tdr and m:
                    c, end = ry, 0
                else:
                    continue
                lost = bool(p.get('to')) and ('fumble' in xl or 'muff' in xl) and not tdr
                if tdr:
                    v = 7.0 if not lost else -7.0
                elif not (0 <= end <= 100):
                    continue
                elif lost:
                    v = -val(max(1, 100 - end))
                else:
                    v = val(max(1, end))
                ret = c if (c is not None and (m or 'muff' in xl) and 'fair catch' not in xl and 0 <= c <= 110) else None
                kicks.append({'s': s, 'k': 'kr' if ko else 'pr', 'gid': gid, 'kick': kick, 'recv': recv, 'v': v,
                              'ret': ret is not None, 'catch': ret, 'los': yl})
    import numpy as np
    fgp = {}
    for s in sorted({x['s'] for x in fgs}):
        xs = [x for x in fgs if abs(x['s'] - s) <= 1]
        X = np.array([[1.0, x['dist']] for x in xs]); y = np.array([1.0 if x['ok'] else 0.0 for x in xs])
        b = np.zeros(2)
        for _ in range(25):
            pr = 1 / (1 + np.exp(-X @ b)); W = pr * (1 - pr)
            b += np.linalg.solve(X.T @ (X * W[:, None]) + 1e-6 * np.eye(2), X.T @ (y - pr))
        fgp[s] = b
        print('cfb', s, 'FG make 30/45/55', [round(float(1 / (1 + math.exp(-(b[0] + b[1] * d)))), 3) for d in (30, 45, 55)], len(xs), flush=True)
    pfg = lambda s, d: 1 / (1 + math.exp(-(fgp[s][0] + fgp[s][1] * d)))
    xpr = collections.defaultdict(lambda: [0, 0])
    for x in xps:
        xpr[x['s']][0] += x['ok']; xpr[x['s']][1] += 1
    G = {gid: {**m, 'u': {'h': collections.defaultdict(float), 'a': collections.defaultdict(float)}, 'n': collections.Counter()}
         for gid, m in meta.items()}
    side = lambda gg, t: 'h' if t == gg['h'] else 'a' if t == gg['a'] else None
    for x in fgs:
        gg = G.get(x['gid'])
        if gg and side(gg, x['team']):
            gg['u'][side(gg, x['team'])]['fg'] += 3 * ((1 if x['ok'] else 0) - pfg(x['s'], x['dist']))
    for x in xps:
        gg = G.get(x['gid'])
        if gg and side(gg, x['team']):
            r = xpr[x['s']]
            gg['u'][side(gg, x['team'])]['fg'] += (1 if x['ok'] else 0) - r[0] / r[1]
    # punts: expected receiving value from the line of scrimmage (5-yd bins), the punting side's value against it
    pun = [k for k in kicks if k['k'] == 'pr']
    for k in pun:
        k['lb'] = k['los']
    for k in pun:
        k['k0'] = k['k']
    spot_expect([dict(k, k='p') for k in pun], 'lb')
    lb = collections.defaultdict(lambda: [0, 0.0])
    for k in pun:
        lb[(k['s'], k['los'] // BIN)][0] += 1; lb[(k['s'], k['los'] // BIN)][1] += k['v']
    E_los = lambda s, los: (lambda n, v: v / n if n else 0.0)(*lb[(s, los // BIN)])
    for b in blks:
        gg = G.get(b['gid'])
        if not gg:
            continue
        sk = side(gg, b['kick'])
        if not sk:
            continue
        so = 'a' if sk == 'h' else 'h'
        if b['kind'] == 'punt':
            sw = b['v'] - E_los(b['s'], b['los'])            # the blocking side's gain over an average punt
        elif b['kind'] == 'fg':
            sw = 3 * pfg(b['s'], b['dist']) + 7 * b.get('td', 0)
        else:
            sw = 1.0 * (xpr[b['s']][0] / max(1, xpr[b['s']][1]))
        gg['u'][so]['blk'] += sw; gg['u'][sk]['blk'] -= sw; gg['n']['blk'] += 1
    rets = [k for k in kicks if k['ret']]
    spot_expect(rets, 'catch')
    kom = collections.defaultdict(lambda: [0, 0.0])
    for k in kicks:
        if k['k'] == 'kr':
            kom[k['s']][0] += 1; kom[k['s']][1] += k['v']
    for k in kicks:
        gg = G.get(k['gid'])
        if not gg:
            continue
        sk, sr = side(gg, k['kick']), side(gg, k['recv'])
        if not sk or not sr:
            continue
        r = (k['v'] - k['e']) if k['ret'] else 0.0
        base = (kom[k['s']][1] / kom[k['s']][0]) if k['k'] == 'kr' else E_los(k['s'], k['los'])
        gg['u'][sr][k['k']] += r
        gg['u'][sk]['cov'] -= r
        gg['u'][sk]['ko' if k['k'] == 'kr' else 'punt'] += (base - k['v']) + r
        gg['n'][k['k']] += 1
    print('cfb kicks', len(kicks), 'returns', len(rets), 'fg', len(fgs), 'xp', len(xps), 'blocks', len(blks), flush=True)
    return finish('cfb', G, save)


def load(sport):
    with gzip.open(os.path.join(CACHE, f'{sport}_st.json.gz'), 'rt') as fh:
        return json.load(fh)


if __name__ == '__main__':
    cmd, sp = sys.argv[1], sys.argv[2]
    if cmd == 'events':
        (nfl_events if sp == 'nfl' else cfb_events)()
    elif cmd == 'research':
        import st_teams_research as R
        R.main(sp)
    elif cmd == 'build':
        import st_teams_research as R
        R.build(sp)
