# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import *
import numpy as np
rows, players, tn = load_rows()
rec = base_rec(rows); P = live_P(); pw = M.wf_probs(rec, P)
C = [(x, p) for x, p in zip(rec, pw) if x[0][14] and 0 < x[0][14] < 1]
def rep(name, key):
    g = {}
    for x, p in C:
        g.setdefault(key(x), []).append((math.log(x[0][14]) - math.log(p), p, x[0][14]))
    print('--', name)
    for k in sorted(g, key=str):
        d = np.array([a for a, _, _ in g[k]])
        pm = np.array([b for _, b, _ in g[k]]); pc = np.array([c for _, _, c in g[k]])
        print(f'  {str(k):14s} n {len(d):5d} gap {d.mean():+.4f} t {d.mean()/(d.std(ddof=1)/len(d)**.5+1e-12):+.2f}  llM {-np.log(pm).mean():.4f} llC {-np.log(pc).mean():.4f} favM {np.maximum(pm,1-pm).mean():.3f} favC {np.maximum(pc,1-pc).mean():.3f}')
rep('half', lambda x: (x[0][0] // 10000, 'H1' if x[0][0] % 10000 < 601 else 'H2'))
rep('tour', lambda x: x[0][1])
rep('level', lambda x: x[0][2])
rep('surface', lambda x: x[0][3])
rep('round', lambda x: x[0][4])
def rk(x):
    r = [v or 999 for v in (x[0][12], x[0][13])]
    m = max(r)
    return '1 both<=50' if m <= 50 else '2 worst<=100' if m <= 100 else '3 worst<=200' if m <= 200 else '4 worst>200'
rep('rank', rk)
rep('bo', lambda x: x[0][5])
# model-minus-close logit gap vs outcome: where is the close more extreme?
