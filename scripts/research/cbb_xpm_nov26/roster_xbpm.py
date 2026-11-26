#!/usr/bin/env python3
"""Lead check: the board's xBPM (walk-forward: value for season y fit on target seasons <= y-1) in place of last-season
BPM in the roster prior (as roster.py 'swap' does with pXPM), same harness.  -> roster_xbpm.json"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.argv = sys.argv[:1]
import xbpm as XB          # builds rows (and reruns its comparison)
import roster as RS
A, R, F = RS.A, RS.R, XB.F
V = {}
for y in range(2011, 2027):
    m = F.xbpm_fit([r for r in XB.rows if r['year'] <= y - 1], F.XB_RET)
    te = [r for r in XB.rows if r['year'] == y]
    Z = F.Std.__new__(F.Std); Z.m = np.array(m['mean']); Z.s = np.array(m['sd']); Z.clip = 4
    p = np.hstack([np.ones((len(te), 1)), Z(F.matrix(te, F.XB_RET))]) @ np.array(m['w'])
    V[y] = {r['pid']: float(v) for r, v in zip(te, p)}


def xrow(k, r, p, ts, y):
    x = RS.ORIG(k, r, p, ts, y)
    if k not in ('ret', 'tr'): return x
    v = V.get(y, {}).get(str(r.get('pid', p.get('pid'))))
    if v is None: return x
    m = R.f(p['min_per'], 0) / 100; x = list(x); x[1] = v; x[4] = v * m; x[10] = x[7] * v
    return x


R.xrow = xrow; RP = A.roster_prior(); R.xrow = RS.ORIG
vn = {n: {pid: v for pid, (v, k) in RP[n].items() if k in ('ret', 'tr', 'back')} for n in A.PAIRS}
_, _, sc = A.predict(lambda n: vn[n]); base = json.load(open(os.path.join(HERE, 'roster.json')))
b = base['base']; px = base['swap']
d = [sc['byPair'][n] - b['byPair'][str(n)] for n in A.PAIRS]; t, p = A.paired_t(d)
out = {'xBPM swap': {'teamR2': [b['teamR2'], sc['teamR2']], 'playerR_vsBPM': [b['playerR_vsBPM'], sc['playerR_vsBPM']], 'pairsBetter': int(sum(x > 0 for x in d)), 't': t},
       'pXPM swap (roster.json)': px}
print(json.dumps(out)); json.dump(out, open(os.path.join(HERE, 'roster_xbpm.json'), 'w'), indent=1)
