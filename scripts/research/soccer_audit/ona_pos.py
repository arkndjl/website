#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import sys, json, math, numpy as np
from collections import defaultdict
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..'))
import soccer_players as SPL, soccer_data as D
F = json.load(open('data/soccer_war_fit.json'))
S1 = D.current_season()
done = [r for r in D.load(SPL.ROWS) if r['S'] < S1]
tsd = {k: v for k, v in SPL.team_seasons(SPL.FIRST, S1).items() if k[1] < S1}
pri = dict(priors=SPL.PRIORS, LS=SPL.league_strength(), TMV=SPL.tm_values())
SPL.prep(done, F['shrink'])
for r in done:
    for g in ('GK', 'D', 'M', 'F'):
        r['ona_' + g] = r['ona'] if r['pos'] == g else 0.0
        r['rel_' + g] = r['rel'] if r['pos'] == g else 0.0
base = F['feats']
arms = {'base': base,
        'ona by pos': [f for f in base if f != 'ona'] + ['ona_GK', 'ona_D', 'ona_M', 'ona_F'],
        'rel by pos': [f for f in base if f != 'rel'] + ['rel_GK', 'rel_D', 'rel_M', 'rel_F']}
res = {}
for name, fs in arms.items():
    ks, X, y = SPL.design(done, tsd, fs, **pri)
    e, pred = SPL.loso(ks, X, y, F['lambda'])
    se = defaultdict(list)
    for kk, yy, pp in zip(ks, y, pred): se[kk[1]].append((yy - pp) ** 2)
    res[name] = {s: float(np.mean(v)) for s, v in se.items()}
    b = SPL.ridge(X, y, F['lambda'])
    print(name, round(e, 5), dict(zip(fs, np.round(b[:len(fs)], 3))), flush=True)
for name in res:
    d = np.array([res['base'][s] - res[name][s] for s in sorted(res['base'])])
    print(name, 'gain', round(d.mean(), 5), 't', round(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)) + 1e-12), 2), 'wins', int((d > 0).sum()), 'of', len(d))
