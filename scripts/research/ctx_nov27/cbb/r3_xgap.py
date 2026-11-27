#!/usr/bin/env python3
"""R3 (prereg.md, round 2): the CBB backup watch's xGap terms (data/backup_age.json cbb) were fit on Nov 11 on pairs
graded by BPM; since Nov 26 the live grade carries pXPM in last season's slot. Pairs graded as live (backup_age_fit
cbb_pairs px=True); the shipped a, b, c against a walk-forward refit on these pairs.  -> r3.json"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, HERE)
import backup_age_fit as B
from h1_builder import tstat
SHIP = {'a': -0.06718, 'b': 0.4812, 'c': 1.27864}        # data/backup_age.json cbb, asof 2026-11-11
path = sys.argv[1] if len(sys.argv) > 1 else B.RESEARCH
P = np.array(B.cbb_pairs(path, px=True), float); P0 = np.array(B.cbb_pairs(path, px=False), float)
ys = sorted(set(P[:, 0].astype(int))); e0, e1, by = [], [], {}
for y in ys[4:]:
    tr, te = P[P[:, 0] + B.H <= y], P[P[:, 0] == y]
    if len(tr) < 100 or not len(te): continue
    b = np.linalg.lstsq(np.c_[np.ones(len(tr)), tr[:, 1:3]], tr[:, 3], rcond=None)[0]
    a0 = (SHIP['a'] + SHIP['b'] * te[:, 1] + SHIP['c'] * te[:, 2] - te[:, 3]) ** 2; a1 = (np.c_[np.ones(len(te)), te[:, 1:3]] @ b - te[:, 3]) ** 2
    e0 += list(a0); e1 += list(a1); by[y] = (float(a0.mean()), float(a1.mean()))
d = np.array(e0) - np.array(e1); f = B.fit(list(P)); f0 = B.fit(list(P0))
out = {'pairs_px_grade': len(P), 'pairs_bpm_grade': len(P0), 'held': len(d), 'mse_shipped': round(float(np.mean(e0)), 4), 'mse_refit': round(float(np.mean(e1)), 4),
       't': round(tstat(d), 2), 'k': int(sum(v[0] > v[1] for v in by.values())), 'seasons': len(by),
       'refit': {k: round(f[k], 5) for k in ('a', 'b', 'c', 'sd')}, 'refit_age_t': f['t'], 'bpm_grade_refit_today': {k: round(f0[k], 5) for k in ('a', 'b', 'c')}}
print(out)
json.dump(out, open(os.path.join(HERE, 'r3.json'), 'w'), indent=1)
