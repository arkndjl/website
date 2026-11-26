#!/usr/bin/env python3
"""Strict walk-forward version of roster.py 'swap': for pair n every pXPM value (training rows and the scored season) comes
from the pXPM model fit on pairs m <= n-1 only (targets <= n), so no coefficient has seen season n+1.  -> roster_wf.json"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import xpm as X
import roster as RS
A = RS.A; R = RS.R
PRM = {'o': (0.35, 0.2, 200, 0), 'd': (0.6, 0.4, 100, 0.25)}
G = {s: X.grams(s, PRM[s], True) for s in 'od'}
per, pp = {}, {}
for n in A.PAIRS:
    tr = [m for m in X.YRS[:-1] if m <= n - 1]
    beta = {s: X.solve(G[s], tr, True) for s in 'od'}
    RS.PX.clear()
    for y in X.YRS:
        if y > n: continue
        v = {s: X.design(y, s, PRM[s], True) @ beta[s] for s in 'od'}
        RS.PX[y] = {pid: [float(v['o'][i]), float(v['d'][i])] for i, pid in enumerate(X.ROWS[y]['pid'])}
    R.xrow = RS.make('swap'); RP = A.roster_prior(); R.xrow = RS.ORIG
    vn = {pid: v for pid, (v, k) in RP[n].items() if k in ('ret', 'tr', 'back')}
    per[n], pp[n] = A.predict_rows(n, vn, 'bpm'); print(n, flush=True)
sc = A.predict_score(per, pp); base = json.load(open(os.path.join(HERE, 'roster.json')))['base']
d = [sc['byPair'][n] - base['byPair'][str(n)] if str(n) in base['byPair'] else sc['byPair'][n] - base['byPair'][n] for n in A.PAIRS]
t, p = A.paired_t(d)
out = {'teamR2': [base['teamR2'], sc['teamR2']], 'playerR_vsBPM': [base['playerR_vsBPM'], sc['playerR_vsBPM']], 'pairsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': round(p, 5)}
print(out); json.dump(out, open(os.path.join(HERE, 'roster_wf.json'), 'w'), indent=1)
