#!/usr/bin/env python3
"""pXPM (X2, history + box) for every season 2008-2026 with leave-one-pair-out coefficients (season n's value never fit
on its own next-season target), fixed at the walk-forward's modal pick (O 0.35/0.2/K200/g0, D 0.6/0.4/K100/g.25), for the
downstream tests (FV driver, roster prior, mock). -> pxpm_loso.json.gz {year: {pid: [O, D, minutes]}}"""
import gzip, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import xpm as X
PRM = {'o': (0.35, 0.2, 200, 0), 'd': (0.6, 0.4, 100, 0.25)}
G = {s: X.grams(s, PRM[s], True) for s in 'od'}
out = {}
for n in X.YRS:
    v = {s: X.design(n, s, PRM[s], True) @ X.solve(G[s], [m for m in X.YRS[:-1] if m != n], True) for s in 'od'}
    R = X.ROWS[n]
    out[n] = {pid: [round(float(v['o'][i]), 3), round(float(v['d'][i]), 3), round(float(R['e0'][i]))] for i, pid in enumerate(R['pid'])}
with gzip.open(os.path.join(HERE, 'pxpm_loso.json.gz'), 'wt') as f: json.dump(out, f)
print({n: len(out[n]) for n in out})
