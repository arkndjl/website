#!/usr/bin/env python3
"""Port round, NBA descriptive (prereg.md B2): rXPM-G, the per-game mean of a game-level team-adjusted box value (the
CBB GBPM analogue), against rXPM (txpm) on held-out describe of team win%; plus the duplicate game check.
Seasons 2019..2026 (ESPN box lines scripts/nba_pbox_hist.json.gz); static/data/nba-xpm/2027.json (lockbox) never read.
NBA pXPM belongs to another thread and is not touched.
    python3 scripts/research/metric_audit_nov24/port/nhl_soccer_nba/nba.py [project files dir] -> nba.json"""
import gzip, json, math, os, sys
from collections import defaultdict
from math import erf
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
PF = sys.argv[1] if len(sys.argv) > 1 else '/mnt/project-files'
SEAS = list(range(2019, 2027))
GH = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_games_hist.json.gz')))['games']
BOX = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_pbox_hist.json.gz')))
GAMES = [g for g in GH if g['t'] == 2 and g.get('fin') and g['S'] in SEAS and g['id'] in BOX]
print(len(GAMES), 'regular season games with box lines', flush=True)


def gs(r):
    """Hollinger game score on the ESPN line (FGM, FTM estimated; no OREB / PF split)"""
    _, _, _, _, mn, pts, reb, ast, fg3, stl, blk, tov, fga, fta = r
    ftm = .77 * fta; fgm = max(0.0, (pts - fg3 - ftm) / 2)
    return pts + .4 * fgm - .7 * fga - .4 * (fta - ftm) + .5 * reb + .7 * ast + stl + .7 * blk - tov


# ---- game-level values, season stints, win% (ESPN space)
gv = defaultdict(lambda: defaultdict(list))      # S -> pid -> [(game value, minutes)]
mins = defaultdict(lambda: defaultdict(float))   # S -> (pid, team) -> minutes
rawS = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))   # S -> pid -> [GS, min]  (season anchoring)
tmS = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0]))  # S -> team -> [margin x 48 / game min summed, games, wins]
dups = defaultdict(list)
for g in GAMES:
    dups[(g['tip'][:10], frozenset((g['h'], g['a'])))].append(g['id'])
    b = BOX[g['id']]
    if g['h'] not in b or g['a'] not in b: continue
    rows = {t: [r for r in b[t] if r[4] > 0] for t in (g['h'], g['a'])}
    tmin = {t: sum(r[4] for r in rows[t]) for t in rows}
    if min(tmin.values()) < 200: continue                       # partial box
    gm = tmin[g['h']] / 5
    allr = [(t, r, gs(r) / r[4] * 48) for t in rows for r in rows[t]]
    mu = sum(x * r[4] for t, r, x in allr) / sum(r[4] for t, r, x in allr)
    marg = {g['h']: g['hs'] - g['as'], g['a']: g['as'] - g['hs']}
    for t in rows:
        rr = [(r, x - mu) for tt, r, x in allr if tt == t]
        cur = 5 * sum(x * r[4] for r, x in rr) / tmin[t]
        d = (marg[t] * 48 / gm - cur) / 5
        for r, x in rr:
            if r[4] >= 10: gv[g['S']][r[0]].append(x + d)
            mins[g['S']][(r[0], t)] += r[4]
            rawS[g['S']][r[0]][0] += gs(r); rawS[g['S']][r[0]][1] += r[4]
        T = tmS[g['S']][t]; T[0] += marg[t] * 48 / gm; T[1] += 1; T[2] += marg[t] > 0

ESPNV = {}
for S in SEAS:
    pm = defaultdict(float)
    for (pid, t), m in mins[S].items(): pm[pid] += m
    ESPNV[S] = {'pm': pm}
    ESPNV[S]['G'] = {pid: float(np.mean([v for v in l])) for pid, l in gv[S].items()}
    ESPNV[S]['Gw'] = {pid: sum(1 for _ in l) for pid, l in gv[S].items()}
    # season-anchored version of the same box value: season rate over the league, one shift a team a season
    lg = sum(a[0] for a in rawS[S].values()) * 48 / sum(a[1] for a in rawS[S].values())
    rate = {pid: a[0] / a[1] * 48 - lg for pid, a in rawS[S].items() if a[1] > 0}
    tmin = defaultdict(float); tsum = defaultdict(float)
    for (pid, t), m in mins[S].items(): tmin[t] += m; tsum[t] += rate[pid] * m
    shift = {t: (tmS[S][t][0] / tmS[S][t][1] - 5 * tsum[t] / tmin[t]) / 5 for t in tmin}
    acc = defaultdict(lambda: [0.0, 0.0])
    for (pid, t), m in mins[S].items(): acc[pid][0] += (rate[pid] + shift[t]) * m; acc[pid][1] += m
    ESPNV[S]['Ssn'] = {pid: a[0] / a[1] for pid, a in acc.items() if a[1] > 0}
    ESPNV[S]['team'] = {t: (v[2] / v[1], v[0] / v[1]) for t, v in tmS[S].items()}    # win%, margin a 48


def espn_rows(S, key):
    V = ESPNV[S][key]; pm = ESPNV[S]['pm']
    fill = float(np.mean([v for pid, v in V.items() if pm[pid] < 500] or [0]))
    s, tm = defaultdict(float), defaultdict(float)
    for (pid, t), m in mins[S].items(): s[t] += V.get(pid, fill) * m; tm[t] += m
    return [(5 * s[t] / tm[t], ESPNV[S]['team'][t][0], ESPNV[S]['team'][t][1]) for t in s]


# ---- rXPM, BPM (bbref space)
P = pd.read_csv(f'{PF}/cbb/xpm/players.csv', low_memory=False, usecols=['year', 'pid', 'tm', 'mp'])
P = P[~P.tm.astype(str).str.match(r'^\dTM$|^TOT$')].copy(); P['mp'] = pd.to_numeric(P.mp, errors='coerce').fillna(0)
T = pd.read_csv(f'{PF}/cbb/xpm/teams.csv')
T['net'] = pd.to_numeric(T.net_rtg.astype(str).str.replace('+', '', regex=False), errors='coerce')
TW = {(r.year, r.tm): (r.wins / (r.wins + r.losses), r.net) for r in T.itertuples()}
XS = {S: {p['id']: p for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{S}.json')))['players']
          if not p.get('pr')} for S in SEAS}


def bb_rows(S, key):
    V = {pid: p[key] for pid, p in XS[S].items() if p.get(key) is not None}
    fill = float(np.mean([v for pid, v in V.items() if XS[S][pid]['mp'] < 500]))
    s, tm = defaultdict(float), defaultdict(float)
    for r in P[P.year == S].itertuples(): s[r.tm] += V.get(r.pid, fill) * r.mp; tm[r.tm] += r.mp
    return [(5 * s[t] / tm[t], *TW[(S, t)]) for t in s if (S, t) in TW]


def centre(rows, j):
    mx, my = np.mean([r[0] for r in rows]), np.mean([r[j] for r in rows])
    return [(r[0] - mx, r[j] - my) for r in rows]


def held(R, j):
    out = {}
    for S in SEAS:
        o = [r for Y in SEAS if Y != S for r in centre(R[Y], j)]
        b = sum(x * y for x, y in o) / sum(x * x for x, y in o); a = centre(R[S], j)
        out[S] = (sum((y - b * x) ** 2 for x, y in a), sum(y * y for x, y in a))
    return out


def hr2(h): return 1 - sum(v[0] for v in h.values()) / sum(v[1] for v in h.values())


def ins(R, j):
    a = [r for S in SEAS for r in centre(R[S], j)]; return float(np.corrcoef(*zip(*a))[0, 1] ** 2)


M = {'rXPM (txpm)': {S: bb_rows(S, 'txpm') for S in SEAS}, 'XPM': {S: bb_rows(S, 'xpm') for S in SEAS},
     'BPM': {S: bb_rows(S, 'bpm') for S in SEAS},
     'rXPM-G (per-game mean, game-anchored box)': {S: espn_rows(S, 'G') for S in SEAS},
     'same box, season-anchored': {S: espn_rows(S, 'Ssn') for S in SEAS}}
OUT = {'asof': '2026-11-24', 'seasons': [SEAS[0], SEAS[-1]], 'games': len(GAMES), 'metrics': {}}
HD = {}
for k, R in M.items():
    HD[k] = held(R, 1)
    OUT['metrics'][k] = {'describeWin': round(ins(R, 1), 4), 'describeWinHeld': round(hr2(HD[k]), 4),
                         'describeNet': round(ins(R, 2), 4), 'teamSeasons': sum(len(R[S]) for S in SEAS)}
    print(k, OUT['metrics'][k], flush=True)
a, b = HD['rXPM-G (per-game mean, game-anchored box)'], HD['rXPM (txpm)']
d = np.array([(b[S][0] - a[S][0]) / b[S][1] for S in SEAS]); t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
OUT['B2'] = {'target': 'held-out describe R2, team win%', 'before': OUT['metrics']['rXPM (txpm)']['describeWinHeld'],
             'after': OUT['metrics']['rXPM-G (per-game mean, game-anchored box)']['describeWinHeld'], 't': round(t, 2),
             'p': round(1 - 0.5 * (1 + erf(t / math.sqrt(2))), 4), 'seasonsBetter': int((d > 0).sum()), 'n': len(SEAS)}
a2 = HD['same box, season-anchored']; d2 = np.array([(a2[S][0] - a[S][0]) / a2[S][1] for S in SEAS])
OUT['B2_mechanism_vs_season_anchored'] = {'t': round(float(d2.mean() / (d2.std(ddof=1) / math.sqrt(len(d2)))), 2),
                                          'seasonsBetter': int((d2 > 0).sum())}
print('B2', OUT['B2'], OUT['B2_mechanism_vs_season_anchored'], flush=True)
OUT['duplicates'] = {'sameDayTeams': sum(len(v) - 1 for v in dups.values() if len(v) > 1),
                     'sameId': len(GAMES) - len({g['id'] for g in GAMES}),
                     'boxPlayerDupRows': sum(len(r) - len({x[0] for x in r}) for gid in (g['id'] for g in GAMES) for r in BOX[gid].values())}
print('dups', OUT['duplicates'])
json.dump(OUT, open(os.path.join(HERE, 'nba.json'), 'w'), indent=1)
print('wrote nba.json')
