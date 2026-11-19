# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 3: Transfer% fit on every earlier cycle against the single cycle before (pre-registered in prereg.md).
Inputs (dir argv[1]): cfbfastR-data roster CSVs r<Y>.csv 2018-2026, ESPN player boxes pb<Y>.parquet 2021-2025.
Writes moves.json (FBS movers with home and both schools) for the landing proxy test."""
import json, math, os, sys
from collections import Counter, defaultdict
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
DIR = sys.argv[1]
L = json.load(open(os.path.join(ROOT, 'data/cfb_transfer_fit.json')))['landing']['schools']
LOC = json.load(open(os.path.join(ROOT, 'scripts/geo/team_loc.json')))
ros = {y: pd.read_csv(os.path.join(DIR, f'r{y}.csv'), low_memory=False).drop_duplicates(['athlete_id', 'team']) for y in range(2018, 2027)}
first = {}
for y in sorted(ros):
    for a in ros[y].athlete_id: first.setdefault(a, y)
# roster team name -> ESPN team id, by the players the box scores share with the roster
name2tid, play = {}, {}
for y in range(2021, 2026):
    b = pd.read_parquet(os.path.join(DIR, f'pb{y}.parquet'), columns=['athlete_id', 'team_id', 'game_id'])
    b['athlete_id'] = pd.to_numeric(b.athlete_id, errors='coerce'); b = b.dropna(subset=['athlete_id']); b['athlete_id'] = b.athlete_id.astype('int64')
    gp = b.drop_duplicates(['athlete_id', 'game_id']).groupby('athlete_id').size()
    tg = b.drop_duplicates(['team_id', 'game_id']).groupby('team_id').size()
    at = b.groupby('athlete_id').team_id.agg(lambda s: s.value_counts().index[0])
    play[y] = (gp, tg, at)
    m = ros[y].merge(at.rename('tid'), left_on='athlete_id', right_index=True)
    for nm, g in m.groupby('team'):
        c = g.tid.value_counts()
        if c.iloc[0] >= 10: name2tid.setdefault(nm, Counter())[str(c.index[0])] += c.iloc[0]
name2tid = {k: v.most_common(1)[0][0] for k, v in name2tid.items()}
def hav(a, b, c, d):
    p = math.pi / 180; x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(x))
GRP = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'OT': 'OL', 'G': 'OL', 'C': 'OL', 'OG': 'OL', 'DL': 'DL', 'DT': 'DL', 'DE': 'DL', 'NT': 'DL', 'EDGE': 'DL',
       'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB', 'DB': 'DB', 'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB', 'PK': 'ST', 'K': 'ST', 'P': 'ST', 'LS': 'ST'}
GS = ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB', 'ST']
rows, moves = [], []
for S in range(2021, 2026):
    nxt = ros[S + 1].groupby('athlete_id').team.agg(list).to_dict()
    gp, tg, at = play[S]
    for r in ros[S].itertuples():
        tid = name2tid.get(r.team)
        if tid not in L or L[tid][0] not in ('P4', 'G5'): continue
        n = nxt.get(r.athlete_id)
        if not n: continue
        y = 0 if r.team in n else 1
        yrs = min(4, S - first[r.athlete_id] + 1)
        g = GRP.get(str(r.position), 'OT')
        ptm = float(gp.get(r.athlete_id, 0)) / max(1.0, float(tg.get(int(tid), tg.max()))) if True else 0
        loc = LOC.get(tid); home = isinstance(r.home_latitude, float) and not math.isnan(r.home_latitude) and loc
        dist = math.log(1 + hav(r.home_latitude, r.home_longitude, loc[0], loc[1])) if home else 0.0
        x = [1.0] + [1.0 if yrs == k else 0.0 for k in (2, 3, 4)] + [1.0 if g == k else 0.0 for k in GS[1:]] + [1.0 if L[tid][0] == 'P4' else 0.0, min(1.0, ptm),
             dist, 1.0 if home and str(r.home_state) == loc[2] else 0.0, 0.0 if home else 1.0]
        rows.append((S, tid, y, x))
        if y and home:
            to = name2tid.get(n[0])
            if to in L: moves.append({'S': S, 'id': int(r.athlete_id), 'from': tid, 'to': to, 'lat': r.home_latitude, 'lon': r.home_longitude, 'st': str(r.home_state)})
json.dump(moves, open(os.path.join(DIR, 'moves.json'), 'w'))
Sx = np.array([r[0] for r in rows]); T = np.array([r[1] for r in rows]); Y = np.array([r[2] for r in rows], float); X = np.array([r[3] for r in rows])
def fit(X, y, w=None, lam=1.0):
    w = np.ones(len(y)) if w is None else w
    mu, sd = X[:, 1:].mean(0), X[:, 1:].std(0) + 1e-9
    Z = np.column_stack([np.ones(len(y)), (X[:, 1:] - mu) / sd]); b = np.zeros(Z.shape[1]); R = lam * np.eye(Z.shape[1]); R[0, 0] = 0
    for _ in range(40):
        p = 1 / (1 + np.exp(-Z @ b)); g = Z.T @ (w * (p - y)) + R @ b; H = (Z * (w * p * (1 - p))[:, None]).T @ Z + R
        b -= np.linalg.solve(H, g)
    return lambda Xn: 1 / (1 + np.exp(-np.column_stack([np.ones(len(Xn)), (Xn[:, 1:] - mu) / sd]) @ b))
def ll(p, y): p = np.clip(p, 1e-6, 1 - 1e-6); return -(y * np.log(p) + (1 - y) * np.log(1 - p))
def auc(p, y):
    o = np.argsort(p); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1); n1 = y.sum(); return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (len(y) - n1)))
def clus(d, k):
    ks = sorted(set(k)); m = np.array([d[k == x].sum() for x in ks]); n = len(ks)
    return float(d.mean()), float(m.mean() / (m.std(ddof=1) / math.sqrt(n))), n
out = {'rows': {int(s): [int((Sx == s).sum()), round(float(Y[Sx == s].mean()), 4)] for s in sorted(set(Sx))}, 'teams': len(set(T)), 'folds': {}}
for C in (2023, 2024, 2025):
    te = Sx == C
    pB = fit(X[Sx == C - 1], Y[Sx == C - 1])(X[te])
    trA = Sx < C
    pA = fit(X[trA], Y[trA])(X[te])
    wR = 0.5 ** ((C - 1 - Sx[trA]) / 1.0)
    pR = fit(X[trA], Y[trA], wR)(X[te])
    d = ll(pB, Y[te]) - ll(pA, Y[te]); dr = ll(pA, Y[te]) - ll(pR, Y[te])
    out['folds'][f'{C}->{C + 1}'] = {'n': int(te.sum()), 'llB': round(float(ll(pB, Y[te]).mean()), 5), 'llA': round(float(ll(pA, Y[te]).mean()), 5), 'aucB': round(auc(pB, Y[te]), 4), 'aucA': round(auc(pA, Y[te]), 4),
                                    'B_minus_A': [round(v, 5) if i < 2 else v for i, v in enumerate(clus(d, T[te]))], 'recency_A_minus_R': [round(v, 5) if i < 2 else v for i, v in enumerate(clus(dr, T[te]))]}
out['moves'] = len(moves)
print(json.dumps(out, indent=1))
