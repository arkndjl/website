#!/usr/bin/env python3
"""Guard for B-D1 on the board's WAR form (round-1 war_check.py): team wins = a x games + b x team WAR, WAR from GBPM
(shipped) vs GBPM shrunk 100 minutes toward the season's minutes-weighted GBPM mean; leave one season out 2013-26."""
import json, math, os, sys
import numpy as np
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'cbb')))
import audit as A
import war_check as W
YS = W.YS
for y in A.YEARS:
    pl = A.S[y]['pl']; e = sum(v['e'] for v in pl.values()); m = sum(v['gbpm'] * v['e'] for v in pl.values()) / e
    for v in pl.values(): v['gbpm_k'] = (v['gbpm'] * v['e'] + 100 * m) / (v['e'] + 100)
res = {}
for k in ('gbpm', 'gbpm_k'):
    R = float(np.mean([W.ninth(y, k) for y in YS])); Rw = W.rows(k, R); sse = {}
    for y in YS:
        tr = [r for s in YS if s != y for r in Rw[s]]
        c = np.linalg.lstsq(np.array([[g, x] for g, x, _ in tr]), np.array([w for *_, w in tr]), rcond=None)[0]
        sse[y] = float(sum((w - c[0] * g - c[1] * x) ** 2 for g, x, w in Rw[y]))
    res[k] = {'repl': round(R, 3), 'heldRMSE': round(math.sqrt(sum(sse.values()) / sum(len(Rw[y]) for y in YS)), 4), 'sse': sse}
d = np.array([res['gbpm']['sse'][y] - res['gbpm_k']['sse'][y] for y in YS])
res['t'] = round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2); res['seasonsBetter'] = int((d > 0).sum()); res['of'] = len(YS)
for k in ('gbpm', 'gbpm_k'): res[k].pop('sse')
print(res); json.dump(res, open(os.path.join(HERE, 'cbb_war_guard.json'), 'w'), indent=1)
