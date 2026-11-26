#!/usr/bin/env python3
"""rXPM round 3 amendment 3: cross-design check of the college box weights (base BPM). python3 rxpm7.py -> rxpm7.json"""
import json, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gl, rxpm4 as R4, rxpm6 as R6
from rxpm4 import paired, CNT, YEARS, COL, ZC
RW = {'A': R6.RA}
pk = os.path.join(gl.GB, 'designs.pkl')
if os.path.exists(pk): RW.update(pickle.load(open(pk, 'rb')))
else:
    RW['R1'] = {y: R6.strict_rows(y) for y in YEARS}; RW['R2b'] = {y: R6.split_rows(y) for y in YEARS}
    pickle.dump({k: RW[k] for k in ('R1', 'R2b')}, open(pk, 'wb'))
LAM = 30


def xb(R): return np.column_stack([R[:, COL['bpm']], R[:, ZC]])
SC = {k: float(np.sqrt(np.mean(np.concatenate([RW[k][y][:, COL['bpm']] for y in YEARS]) ** 2))) for k in RW}


def fit_d(designs, tr):
    X = np.vstack([xb(RW[k][s]) / SC[k] for k in designs for s in tr]); y = np.concatenate([RW[k][s][:, 0] for k in designs for s in tr])
    b = R4.ridge(X, y, LAM, 1); return b[1:] / b[0]


def score(dset, k):
    """per-season SSE of BPM alone and BPM + d.z (d from dset[y], slope refit on the other seasons) on design k"""
    sb, sx = {}, {}
    for y in YEARS:
        tr = [s for s in YEARS if s != y]; d = dset[y]
        xs = np.concatenate([RW[k][s][:, COL['bpm']] for s in tr]); yy = np.concatenate([RW[k][s][:, 0] for s in tr]); b0 = float(xs @ yy / (xs @ xs))
        xv = np.concatenate([RW[k][s][:, COL['bpm']] + RW[k][s][:, ZC] @ d for s in tr]); b1 = float(xv @ yy / (xv @ xv))
        R = RW[k][y]; sb[y] = float(((R[:, 0] - b0 * R[:, COL['bpm']]) ** 2).sum()); sx[y] = float(((R[:, 0] - b1 * (R[:, COL['bpm']] + R[:, ZC] @ d)) ** 2).sum())
    return sb, sx


if __name__ == '__main__':
    out = {}; SETS = {}
    for nm, ds in (('fit on A', ['A']), ('fit on R1', ['R1']), ('fit on R2b', ['R2b']), ('fit on all three', ['A', 'R1', 'R2b'])):
        SETS[nm] = {y: fit_d(ds, [s for s in YEARS if s != y]) for y in YEARS}
        e = {'weights': {c: round(float(v), 2) for c, v in zip(CNT, np.mean([SETS[nm][y] for y in YEARS], axis=0))}}
        for k in RW:
            sb, sx = score(SETS[nm], k); tot = sum(float((RW[k][y][:, 0] ** 2).sum()) for y in YEARS)
            t, p, n = paired([sb[y] - sx[y] for y in YEARS]); e[k] = {'R2': [round(1 - sum(sb.values()) / tot, 5), round(1 - sum(sx.values()) / tot, 5)], 't': t, 'better': n}
        e['min_t'] = min(e[k]['t'] for k in RW); out[nm] = e; print(nm, json.dumps(e), flush=True)
    pickle.dump(SETS, open(os.path.join(gl.GB, 'sets.pkl'), 'wb'))
    json.dump(out, open(os.path.join(HERE, 'rxpm7.json'), 'w'), indent=1)
