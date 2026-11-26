#!/usr/bin/env python3
"""pXPM round 2 downstream gates (prereg.md): v2 (v1 + team context + recruit rating) vs v1 inside the roster prior
(strict walk-forward, roster_wf protocol) and as the FV returner driver (fv.py protocol, leave-one-pair-out values).
    python3 pxpm2_down.py -> pxpm2_down.json"""
import hashlib, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import pxpm2 as P2
X = P2.X; A = P2.A
import cbb_roster as R
V2 = ['F3', 'F2']


def grams(blocks):
    G = {}
    for s in 'od':
        for m in X.YRS[:-1]:
            D = P2.design(m, s, blocks); Rw = X.ROWS[m]; w = Rw['w']; y = Rw['y' + s]; Dw = D * w[:, None]; G[(s, m)] = (D.T @ Dw, Dw.T @ y)
    return G


def beta(G, tr):
    out = {}
    for s in 'od':
        A_ = sum(G[(s, m)][0] for m in tr); b = sum(G[(s, m)][1] for m in tr); P = np.zeros(A_.shape[0]); P[X.NB0:] = 10.0
        out[s] = np.linalg.solve(A_ + np.diag(P) + 1e-9 * np.eye(len(P)), b)
    return out


def values(y, blocks, b): 
    v = P2.design(y, 'o', blocks) @ b['o'] + P2.design(y, 'd', blocks) @ b['d']
    return {pid: float(v[i]) for i, pid in enumerate(X.ROWS[y]['pid'])}


PX = {}
BASE = R.xrow
def xrow(k, r, p, ts, y):
    x = BASE(k, r, p, ts, y)
    if k not in ('ret', 'tr'): return x
    v = PX.get(int(p['year']), {}).get(str(p['pid'])); m = R.f(p['min_per'], 0) / 100
    if v is None: v = R.f(p['bpm'], R.REPL)
    x = list(x); x[1] = v; x[4] = v * m; x[10] = x[7] * v
    return x


def roster(blocks):
    G = grams(blocks); per, pp = {}, {}
    for n in A.PAIRS:
        b = beta(G, [m for m in X.YRS[:-1] if m <= n - 1]); PX.clear()
        for y in X.YRS:
            if y <= n: PX[y] = values(y, blocks, b)
        R.xrow = xrow; RP = A.roster_prior(); R.xrow = BASE
        vn = {pid: v for pid, (v, k) in RP[n].items() if k in ('ret', 'tr', 'back')}
        per[n], pp[n] = A.predict_rows(n, vn, 'bpm'); print('roster', blocks, n, flush=True)
    return A.predict_score(per, pp)


def fv_gate():
    import cbb_data as D
    import cbb_fit as F
    import cbb_fv_drivers as V
    sys.path.insert(0, HERE)
    L = {}
    for nm, blocks in (('pxpm', []), ('pxpm2', V2)):
        G = grams(blocks); L[nm] = {n: values(n, blocks, beta(G, [m for m in X.YRS[:-1] if m != n])) for n in X.YRS}
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json'))); thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.set_context(careers); rows = []
    for c in careers:
        if c['last'] > 2020: continue
        for i, s in enumerate(c['seasons']):
            if s['year'] not in F.TRAIN or i == 0: continue
            f = F.features(c, i); p = c['seasons'][i - 1]
            for nm in L: f[nm] = L[nm].get(int(p['year']), {}).get(str(c['pid']))
            rows.append({'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'f': f})
    tops = [c['nba']['fvx'] for c in careers if c['last'] in F.SCALE_CLASSES and c['nba']['fvx'] >= 60]; F.TOP_MEAN = round(float(np.mean(tops)), 2)
    rr = [r for r in rows if not r['f']['newcomer']]
    fit = json.load(open(os.path.join(ROOT, 'data', 'cbb_fit.json'))); m = fit['models']['returner']; kept, lam = list(m['kept']), m['lam']
    import fv as FVR
    alt = [k if k != 'pxpm' else 'pxpm2' for k in kept]
    return {'kept': kept, 'n': len(rr), 'v2 for v1': FVR.swap(rr, kept, alt, lam)}


if __name__ == '__main__':
    out = {}
    s1, s2 = roster([]), roster(V2); d = [s2['byPair'][n] - s1['byPair'][n] for n in A.PAIRS]; t, p = A.paired_t(d)
    out['roster'] = {'teamR2': [s1['teamR2'], s2['teamR2']], 'playerR_vsBPM': [s1['playerR_vsBPM'], s2['playerR_vsBPM']], 't': t, 'pairsBetter': int(sum(x > 0 for x in d))}
    print(out['roster'], flush=True); json.dump(out, open(os.path.join(HERE, 'pxpm2_down.json'), 'w'), indent=1)
    out['fv'] = fv_gate(); print(out['fv'], flush=True)
    json.dump(out, open(os.path.join(HERE, 'pxpm2_down.json'), 'w'), indent=1)
