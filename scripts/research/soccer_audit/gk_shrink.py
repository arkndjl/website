#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import sys, os, json, math, numpy as np
from collections import defaultdict
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..'))
import soccer_players as SPL, soccer_data as D
F = json.load(open('data/soccer_war_fit.json'))
S1 = D.current_season()
rows = D.load(SPL.ROWS)
done = [r for r in rows if r['S'] < S1]
ts = SPL.team_seasons(SPL.FIRST, S1)
tsd = {k: v for k, v in ts.items() if k[1] < S1}
LS, TMV = SPL.league_strength(), SPL.tm_values()
pri = dict(priors=SPL.PRIORS, LS=LS, TMV=TMV)
feats = F['feats']; lam = F['lambda']
SPL.prep(done, F['shrink'])
def regk(k):
    by = defaultdict(list)
    for r in done:
        if r['pos'] == 'GK': by[(r['lg'], r['S'])].append(r)
    for rs in by.values():
        pm = sum(r['min'] for r in rs) or 1
        mu = sum(r['_gk'] * r['min'] for r in rs) / pm
        for r in rs:
            w = r['min'] / (r['min'] + k)
            r['gk'] = w * r['_gk'] + (1 - w) * mu
res = {}
for k in (300, 1000, 2000, 4000, 8000, 10**9):
    regk(k)
    ks, X, y = SPL.design(done, tsd, feats, **pri)
    e, pred = SPL.loso(ks, X, y, lam)
    se = defaultdict(list)
    for kk, yy, pp in zip(ks, y, pred): se[kk[1]].append((yy - pp) ** 2)
    res[k] = {s: float(np.mean(v)) for s, v in se.items()}
    print(k, round(e, 5), flush=True)
base = res[300]
for k in res:
    d = np.array([base[s] - res[k][s] for s in sorted(base)])
    print(k, 'gain', round(d.mean(), 5), 't', round(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)) + 1e-12), 2), 'wins', int((d > 0).sum()), 'of', len(d), '2022+', round(d[[s >= 2022 for s in sorted(base)]].mean(), 5))
