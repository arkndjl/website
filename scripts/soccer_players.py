#!/usr/bin/env python3
"""Soccer player values for the SOCCER ARKBOARD: GAR, goals above replacement, and PAR, league points above
replacement, fit to team goal difference (data/soccer_war.json, static/data/soccer-war/<season>.json, the fit in
data/soccer_war_fit.json).

    python3 scripts/soccer_players.py --fit       # every big-five season since 2014-15: parse, fit, write all seasons
    python3 scripts/soccer_players.py             # this season only (the live refresh), at the fitted weights
    python3 scripts/soccer_players.py --backup    # backup watch only, from the cached rows

Data: Understat's match pages (scripts/soccer_data.py usm): who played, when they came on and off, every shot with its
minute and expected goals (xG), and each player's xA (expected assists), xGChain and xGBuildup. From them, for each
player-season in a league: minutes; the team's xG for and against while he was on the pitch (on), and the same with
him off (off); his own non-penalty xG and his xA; xGBuildup (xG of possessions he was part of before the last pass
and the shot); for goalkeepers, goals saved against xG faced (non-penalty shots on target and off: Understat's xG is
before the shot, so this is mostly finishing luck against him). Every rate is per 90 minutes, relative to the
league-season average, and shrunk toward the average for his position by minutes (the shrink minutes tuned).

The weights: each team-season's goal difference a match is predicted from LAST season's shrunk rates of its players,
weighted by THIS season's minutes (players new to the big five carry the replacement level), centred within the
league-season; a ridge fit, leave-one-season-out. A rate keeps its weight only if dropping it raises the
held-out error. A player's value a match = his rates at those weights; replacement = the minutes-weighted value of
players with under 900 minutes in a season (the fringe of the squads); GAR = (value - replacement) x matches of
minutes; PAR = GAR x league points per goal of difference (a team-season regression).
"""
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict, Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D

ROOT = os.path.dirname(HERE)
ROWS = os.path.join(HERE, 'data', 'soccer_player_rows.json.gz')
FIT = os.path.join(ROOT, 'data', 'soccer_war_fit.json')
OUT = os.path.join(ROOT, 'data', 'soccer_war.json')
SDIR = os.path.join(ROOT, 'static', 'data', 'soccer-war')
FIRST = 2015
FEATS = ['onf', 'ona', 'rel', 'npxg', 'xas', 'bup', 'gk']
NAMES = {'onf': 'team xG for with him on', 'ona': 'team xG against with him on (negative = fewer)',
         'rel': 'on minus off: team xG difference', 'npxg': 'own non-penalty xG', 'xas': 'expected assists (xA)',
         'bup': 'xGBuildup', 'gk': 'goalkeeper: goals saved vs xG faced'}
POS = {'GK': 'GK', 'DR': 'D', 'DL': 'D', 'DC': 'D', 'DMR': 'M', 'DML': 'M', 'DMC': 'M', 'MR': 'M', 'ML': 'M', 'MC': 'M',
       'AMR': 'F', 'AML': 'F', 'AMC': 'M', 'FW': 'F', 'FWR': 'F', 'FWL': 'F'}


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- parse
def parse_match(m, lg, S, mid):
    """per player: minutes and on-pitch xG/goals for and against, own stats"""
    ro = m['ro']
    side_shots = {s: [(int(f(x[0])), f(x[1]), x[3], x[4]) for x in m['sh'].get(s, [])] for s in 'ha'}
    out = []
    for s in 'ha':
        o = 'a' if s == 'h' else 'h'
        rs = {r['id']: r for r in ro[s]}
        start = {}
        for r in rs.values():
            if int(f(r.get('positionOrder'))) < 17 and str(r.get('roster_out')) in ('0', 'None', ''):
                start[r['id']] = 0
        for _ in range(6):                                   # subs: on when the player they replaced came off
            for r in rs.values():
                ro_ = str(r.get('roster_out') or '0')
                if r['id'] not in start and ro_ in start and ro_ in rs:
                    start[r['id']] = start[ro_] + int(f(rs[ro_]['time']))
        tf = sum(x[1] for x in side_shots[s] if x[3] != 'Penalty')
        ta = sum(x[1] for x in side_shots[o] if x[3] != 'Penalty')
        for r in rs.values():
            mins = int(f(r['time']))
            if mins <= 0 or r['id'] not in start:
                continue
            a = start[r['id']]; b = min(90, a + mins)

            def on(mn):
                return a <= mn < b or (b >= 90 and mn >= 90)
            xf = sum(x[1] for x in side_shots[s] if x[3] != 'Penalty' and on(x[0]))
            xa_ = sum(x[1] for x in side_shots[o] if x[3] != 'Penalty' and on(x[0]))
            gf = sum(1 for x in side_shots[s] if x[2] == 'Goal' and on(x[0]))
            ga = sum(1 for x in side_shots[o] if x[2] == 'Goal' and on(x[0]))
            gk = sum(x[1] - (x[2] == 'Goal') for x in side_shots[o] if x[3] != 'Penalty' and on(x[0])) if r['position'] == 'GK' else 0.0
            out.append({'p': r['player_id'], 'n': r['player'], 'team': r.get('team_id'), 'side': s, 'pos': r['position'],
                        'min': b - a if b > a else mins, 'xf': xf, 'xa': xa_, 'tf': tf, 'ta': ta, 'gf': gf, 'ga': ga,
                        'g': int(f(r['goals'])), 'as': int(f(r['assists'])), 'x': f(r['xG']), 'xA': f(r['xA']),
                        'bu': f(r['xGBuildup']), 'ch': f(r['xGChain']), 'kp': int(f(r['key_passes'])), 'gks': gk,
                        'sh': int(f(r['shots']))})
    return out


def penalties(m):
    """xG of each player's penalties (Understat counts them in xG; npxG drops them)"""
    p = Counter()
    for s in 'ha':
        for x in m['sh'].get(s, []):
            if x[4] == 'Penalty':
                p[x[2]] += f(x[1])
    return p


def build_rows(S0, S1, before=None):
    """player-season rows: (league, season, team title) -> player totals (before: only matches kicked off before this
    'YYYY-MM-DD', for an in-season snapshot)"""
    agg = {}
    teams = {}
    for S in range(S0, S1 + 1):
        for lg in D.BIG5:
            d = D.us_league(lg, S)
            if not d:
                continue
            for tid, t in d['teams'].items():
                teams[tid] = t['title']
            nm = 0
            for mt in d['matches']:
                if not mt['res'] or (before and (mt.get('t') or '') >= before):
                    continue
                m = D.us_match(mt['id'])
                if not m:
                    continue
                nm += 1
                pens = penalties(m)
                gd = {'h': int(mt['hg']) - int(mt['ag']), 'a': int(mt['ag']) - int(mt['hg'])}
                for r in parse_match(m, lg, S, mt['id']):
                    tid = mt['hid'] if r['side'] == 'h' else mt['aid']
                    k = (lg, S, tid, r['p'])
                    a = agg.setdefault(k, {'n': r['n'], 'pos': Counter(), 'mp': 0, 'min': 0, 'xf': 0, 'xa': 0, 'tf': 0, 'ta': 0,
                                           'gf': 0, 'ga': 0, 'g': 0, 'as': 0, 'x': 0, 'pen': 0, 'xA': 0, 'bu': 0, 'ch': 0, 'kp': 0,
                                           'gks': 0, 'start': 0, 'sh': 0})
                    a['mp'] += 1; a['min'] += r['min']
                    for kk in ('xf', 'xa', 'tf', 'ta', 'gf', 'ga', 'g', 'as', 'x', 'xA', 'bu', 'ch', 'kp', 'gks', 'sh'):
                        a[kk] += r[kk]
                    a['pen'] += pens.get(r['p'], 0.0)
                    if r['pos'] != 'Sub':
                        a['pos'][r['pos']] += 1; a['start'] += 1
                    else:
                        a['pos']['Sub'] += 0
            if not before:
                print(lg, S, nm, 'matches', flush=True)
    rows = []
    for (lg, S, tid, p), a in agg.items():
        pc = [x for x, _ in a['pos'].most_common() if x != 'Sub']
        a['pos'] = POS.get(pc[0], 'M') if pc else 'M'
        rows.append(dict(a, lg=lg, S=S, tid=tid, team=teams.get(tid, tid), p=p))
    return rows


def team_seasons(S0, S1):
    """(league, season, Understat team id) -> matches, goal difference, points, xG for and against"""
    out = {}
    for S in range(S0, S1 + 1):
        for lg in D.BIG5:
            d = D.us_league(lg, S)
            if not d:
                continue
            for tid, t in d['teams'].items():
                h = t['history']
                if not h:
                    continue
                gf = sum(int(x['scored']) for x in h); ga = sum(int(x['missed']) for x in h)
                pts = sum(3 if int(x['scored']) > int(x['missed']) else 1 if x['scored'] == x['missed'] else 0 for x in h)
                out[(lg, S, tid)] = {'mp': len(h), 'gd': gf - ga, 'pts': pts, 'xgd': sum(x['xG'] - x['xGA'] for x in h),
                                     'title': t['title']}
    return out


# ---------------------------------------------------------------- rates
def rates(rows, shrink):
    """per-90 rates relative to the league-season average (minutes-weighted), shrunk toward the position mean by
    `shrink` minutes"""
    by = defaultdict(list)
    for r in rows:
        by[(r['lg'], r['S'])].append(r)
    for rs in by.values():
        tot = sum(r['min'] for r in rs) or 1
        for r in rs:
            m90 = max(r['min'], 1) / 90
            r['_onf'] = r['xf'] / m90
            r['_ona'] = -r['xa'] / m90
            r['_npxg'] = (r['x'] - r['pen']) / m90
            r['_xas'] = r['xA'] / m90
            r['_bup'] = r['bu'] / m90
            r['_gk'] = r['gks'] / m90 if r['pos'] == 'GK' else 0.0
            r['_rel'] = 0.0                               # on minus off: set in prep()
        for k in FEATS:
            mu = sum(r['_' + k] * r['min'] for r in rs) / tot
            for r in rs:
                r['_' + k] -= mu
        for pos in ('GK', 'D', 'M', 'F'):
            ps = [r for r in rs if r['pos'] == pos]
            pm = sum(r['min'] for r in ps) or 1
            for k in FEATS:
                mu = sum(r['_' + k] * r['min'] for r in ps) / pm
                for r in ps:
                    w = r['min'] / (r['min'] + shrink)
                    r[k] = w * r['_' + k] + (1 - w) * mu
    return rows


def on_off(rows, ts):
    """on minus off, team non-penalty xG difference a 90 (team match xG from the player rows' own on-pitch sums)"""
    team = defaultdict(lambda: [0.0, 0.0, 0.0])          # minutes x 1/11, xG for, against (from on-pitch, / 11)
    for r in rows:
        t = team[(r['lg'], r['S'], r['tid'])]
        t[0] += r['min']; t[1] += r['xf']; t[2] += r['xa']
    for r in rows:
        t = team[(r['lg'], r['S'], r['tid'])]
        tm = t[0] / 11                                    # team minutes
        tf, ta = t[1] / 11, t[2] / 11                     # team xG for/against (each on-pitch shot counted by 11)
        offm = tm - r['min']
        if r['min'] < 90 or offm < 90:
            r['_relraw'] = 0.0
            continue
        on_d = (r['xf'] - r['xa']) / (r['min'] / 90)
        off_d = ((tf - r['xf']) - (ta - r['xa'])) / (offm / 90)
        r['_relraw'] = on_d - off_d


def prep(rows, shrink):
    on_off(rows, None)
    for r in rows:
        r['_relpre'] = r['_relraw']
    rates(rows, shrink)
    # rates() zeroes _rel; put on-off back, centre and shrink it like the others
    by = defaultdict(list)
    for r in rows:
        by[(r['lg'], r['S'])].append(r)
    for rs in by.values():
        tot = sum(r['min'] for r in rs) or 1
        mu = sum(r['_relpre'] * r['min'] for r in rs) / tot
        for pos in ('GK', 'D', 'M', 'F'):
            ps = [r for r in rs if r['pos'] == pos]
            pm = sum(r['min'] for r in ps) or 1
            pmu = sum((r['_relpre'] - mu) * r['min'] for r in ps) / pm
            for r in ps:
                w = r['min'] / (r['min'] + 2 * shrink)       # on-off is noisier: twice the shrink
                r['rel'] = w * (r['_relpre'] - mu) + (1 - w) * pmu
    return rows


# ---------------------------------------------------------------- fit
def design(rows, ts, feats, prior=True):
    """team-season X (sum over players of minutes share x rates) and y (goal difference a match). prior: last
    season's rates (a player's previous big-five season, any club) at this season's minutes"""
    last = {}
    for r in sorted(rows, key=lambda r: r['S']):
        last.setdefault(r['p'], {})[r['S']] = r
    X, y, key = defaultdict(lambda: np.zeros(len(feats))), {}, []
    for r in rows:
        k = (r['lg'], r['S'], r['tid'])
        if k not in ts:
            continue
        share = r['min'] / (90 * ts[k]['mp'])
        if prior:
            pr = None
            for S0 in (r['S'] - 1, r['S'] - 2):
                q = last.get(r['p'], {}).get(S0)
                if q and q['min'] >= 300:
                    pr = q; break
            v = np.array([pr[f_] for f_ in feats]) if pr else None
        else:
            v = np.array([r[f_] for f_ in feats])
        if v is None:
            continue                                     # new player: carries 0 (league-average) here; repl. via intercept
        X[k] += share * v
    for k in X:
        y[k] = ts[k]['gd'] / ts[k]['mp']
    ks = sorted(X)
    Xm = np.array([X[k] for k in ks]); ym = np.array([y[k] for k in ks])
    # centre within league-season
    grp = defaultdict(list)
    for i, k in enumerate(ks):
        grp[(k[0], k[1])].append(i)
    for idx in grp.values():
        Xm[idx] -= Xm[idx].mean(0); ym[idx] -= ym[idx].mean()
    # share of minutes covered by returning players (new players' share sits at league average)
    return ks, Xm, ym


def ridge(X, y, lam):
    k = X.shape[1]
    return np.linalg.solve(X.T @ X + lam * np.eye(k), X.T @ y)


def loso(ks, X, y, lam):
    seasons = sorted({k[1] for k in ks})
    err, n = 0.0, 0
    pred = np.zeros(len(y))
    for S in seasons:
        tr = np.array([k[1] != S for k in ks]); te = ~tr
        if te.sum() == 0 or tr.sum() < 20:
            continue
        b = ridge(X[tr], y[tr], lam)
        pred[te] = X[te] @ b
    return float(np.mean((y - pred) ** 2)), pred


def fit():
    S1 = D.current_season()
    if os.path.exists(ROWS) and '--reparse' not in sys.argv:
        rows = D.load(ROWS)
    else:
        rows = build_rows(FIRST, S1)
        D.save(ROWS, rows)
    ts = team_seasons(FIRST, S1)
    done = [r for r in rows if r['S'] < S1]
    tsd = {k: v for k, v in ts.items() if k[1] < S1}
    best = None
    for shrink in (100, 200, 300, 500, 800):
        prep(done, shrink)
        ks, X, y = design(done, tsd, FEATS)
        for lam in (0.1, 1.0, 5.0):
            e, _ = loso(ks, X, y, lam)
            print('shrink', shrink, 'lam', lam, round(e, 5), flush=True)
            if best is None or e < best[0]:
                best = (e, shrink, lam)
    e0, shrink, lam = best
    prep(done, shrink)
    ks, X, y = design(done, tsd, FEATS)
    var = float(np.mean(y ** 2))
    feats = list(FEATS)
    evidence = {}
    # backward elimination: drop a rate while dropping it doesn't raise held-out error
    while True:
        idx = [FEATS.index(f_) for f_ in feats]
        e_full, _ = loso(ks, X[:, idx], y, lam)
        drops = []
        for f_ in feats:
            j = [FEATS.index(g) for g in feats if g != f_]
            e_d, _ = loso(ks, X[:, j], y, lam) if j else (var, None)
            drops.append((e_d - e_full, f_))
            evidence[f_] = {'dMse': round(e_d - e_full, 5)}
        drops.sort()
        if drops[0][0] < 1e-5 and len(feats) > 1:
            print('drop', drops[0][1], round(drops[0][0], 5), flush=True)
            feats.remove(drops[0][1])
        else:
            break
    idx = [FEATS.index(f_) for f_ in feats]
    e_fin, pred = loso(ks, X[:, idx], y, lam)
    b = ridge(X[:, idx], y, lam)
    w = {f_: round(float(v), 4) for f_, v in zip(feats, b)}
    # points per goal of difference a match (team-seasons)
    gdm = np.array([tsd[k]['gd'] / tsd[k]['mp'] for k in tsd]); ppm = np.array([tsd[k]['pts'] / tsd[k]['mp'] for k in tsd])
    ppg = float(np.polyfit(gdm, ppm, 1)[0])
    # the same weights on the same season's rates (how much of the table the values describe)
    ks2, X2, y2 = design(done, tsd, feats, prior=False)
    r2_same = 1 - float(np.mean((y2 - X2 @ np.array([w[f_] for f_ in feats])) ** 2)) / float(np.mean(y2 ** 2))
    # xG-difference-only baseline: last season's team xGD a match carried forward
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'shrink': shrink, 'lambda': lam,
           'feats': feats, 'w': w, 'names': NAMES, 'evidence': evidence, 'ptsPerGoal': round(ppg, 3),
           'r2Held': round(1 - e_fin / var, 3), 'r2Same': round(r2_same, 3), 'teamSeasons': len(ks),
           'seasons': [FIRST, S1 - 1]}
    json.dump(out, open(FIT, 'w'), indent=1, allow_nan=False)
    print(json.dumps(out, indent=1))
    write(rows, out, ts, all_seasons=True)


def value(r, F):
    return sum(F['w'][f_] * r[f_] for f_ in F['feats'])


def write(rows, F, ts, all_seasons=False):
    prep(rows, F['shrink'])
    by = defaultdict(list)
    for r in rows:
        by[r['S']].append(r)
    # replacement, by position: the minutes-weighted value a match of players under 900 minutes, all seasons (the
    # squads' fringe): a keeper is measured against a fringe keeper, a striker against a fringe forward
    F['repl'] = {}
    for pos in ('GK', 'D', 'M', 'F'):
        fr = [r for r in rows if r['pos'] == pos and 90 <= r['min'] < 900]
        F['repl'][pos] = round(sum(value(r, F) * r['min'] for r in fr) / max(1, sum(r['min'] for r in fr)), 4)
    os.makedirs(SDIR, exist_ok=True)
    cur = D.current_season()
    for S, rs in sorted(by.items()):
        if not all_seasons and S != cur:
            continue
        out = []
        for r in rs:
            if r['min'] < 90:
                continue
            v = value(r, F)
            repl = F['repl'][r['pos']]
            gar = (v - repl) * r['min'] / 90
            o = {'p': r['p'], 'n': r['n'], 'team': r['team'], 'lg': r['lg'], 'pos': r['pos'], 'mp': r['mp'], 'min': r['min'],
                 'g': r['g'], 'a': r['as'], 'npxg': round(r['x'] - r['pen'], 2), 'xa': round(r['xA'], 2),
                 'xg': round(r['x'], 2), 'sh': r.get('sh', 0), 'kp': r['kp'], 'ch': round(r['ch'], 2), 'bu': round(r['bu'], 2),
                 'st': r['start'], 'onxgd': round((r['xf'] - r['xa']) / max(r['min'], 1) * 90, 2),
                 'v90': round(v, 3), 'gar': round(gar, 2), 'par': round(gar * F['ptsPerGoal'], 2),
                 'gar90': round((v - repl), 3)}
            for f_ in F['feats']:
                o['c_' + f_] = round(F['w'][f_] * r[f_] * r['min'] / 90, 2)
            out.append(o)
        out.sort(key=lambda o: -o['gar'])
        for i, o in enumerate(out, 1):
            o['rk'] = i
        for o in out:
            c = {f_: o.pop('c_' + f_, 0) for f_ in FEATS}
            o['off'] = round(sum(c[f_] for f_ in ('onf', 'npxg', 'xas', 'bup')), 2)
            o['def'] = round(sum(c[f_] for f_ in ('ona', 'gk')), 2)
            o['oth'] = round(c['rel'], 2)
        games = max([r['mp'] for r in rs] or [1])
        import soccer_mv as MV                            # estimated market value next to GAR (scripts/soccer_mv.py)
        MV.attach(S, out)
        txt = json.dumps({'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'games': games,
                          'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'players': out,
                          'mv': MV.meta(S)}, separators=(',', ':'), allow_nan=False)
        open(os.path.join(SDIR, f'{S}.json'), 'w').write(txt)
        if S == cur:
            top = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'season': S, 'current': S,
                   'seasons': [{'season': x, 'label': f'{x - 1}-{x % 100:02d}'} for x in sorted(by, reverse=True)],
                   'repl': F['repl'], 'feats': F['feats'], 'w': F['w'],
                   'ptsPerGoal': F['ptsPerGoal'], 'players': out[:300]}
            json.dump(top, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
            backup(rows, F, S)
    json.dump(F, open(FIT, 'w'), indent=1, allow_nan=False)


# ---------------------------------------------------------------- backup watch
BW_START = {'GK': 1, 'D': 4, 'M': 4, 'F': 2}      # a 4-4-2 / 4-3-3 shape: the most-used players at each spot start
BW_K, BW_MIN, BW_GAP = 900, 270, 0.05
BACKUP = os.path.join(ROOT, 'data', 'backup_soccer.json')


def backup(rows, F, S):
    """data/backup_soccer.json, the shape scripts/backup_watch.py writes: no depth charts for soccer, so the order is
    minutes this season within team and position (GK, D, M, F): the most-used are the starters, the next as many the
    2nd string, the next the 3rd. The grade is value a 90 above his position's replacement over this season and last
    (half weight), shrunk to replacement with BW_K minutes. A backup is listed when he beats the lowest-graded
    starter at his position by BW_GAP goals a 90 and has BW_MIN minutes."""
    past = defaultdict(lambda: [0.0, 0.0])                # player -> [weighted value-above-repl x minutes, weighted minutes]
    for r in rows:
        w = {S: 1.0, S - 1: 0.5}.get(r['S'])
        if w:
            past[r['p']][0] += w * (value(r, F) - F['repl'][r['pos']]) * r['min']
            past[r['p']][1] += w * r['min']
    grade = {p: a / (m + BW_K) for p, (a, m) in past.items()}
    squads = defaultdict(list)
    for r in rows:
        if r['S'] == S:
            squads[(r['team'], r['pos'])].append(r)
    out = []
    for (team, pos), rs in squads.items():
        rs.sort(key=lambda r: -r['min'])
        n = BW_START[pos]
        st = rs[:n]
        if len(st) < n:
            continue
        low = min(st, key=lambda r: grade[r['p']])
        for i, r in enumerate(rs[n:3 * n]):
            g = grade[r['p']]
            if r['min'] >= BW_MIN and g - grade[low['p']] >= BW_GAP:
                out.append({'name': r['n'], 'team': team, 'lg': r['lg'], 'pos': pos, 'str': 2 if i < n else 3,
                            'g': round(g, 2), 'use': r['min'],
                            'starter': {'name': low['n'], 'g': round(grade[low['p']], 2), 'use': low['min']},
                            'gap': round(g - grade[low['p']], 2)})
    out.sort(key=lambda o: -o['gap'])
    json.dump({'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'asof': dt.date.today().isoformat(), 'k': BW_K,
               'min': BW_MIN, 'gap': BW_GAP, 'w': [1.0, 0.5], 'rows': out}, open(BACKUP, 'w'), indent=0, allow_nan=False)


def current():
    F = json.load(open(FIT))
    S = D.current_season()
    old = [r for r in D.load(ROWS) if r['S'] < S]          # finished seasons are frozen in ROWS (re-run --fit each summer)
    rows = old + build_rows(S, S)
    write(rows, F, None)


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
    elif '--backup' in sys.argv:                      # from the cached rows, no pull
        F = json.load(open(FIT)); rows = D.load(ROWS); prep(rows, F['shrink'])
        backup(rows, F, D.current_season())
    else:
        current()
