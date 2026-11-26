#!/usr/bin/env python3
"""rXPM round 3 report card for the shipped form: rXPM = BPM + d . z, zero-sum within team, d fit on starter absences
(rxpm7 'fit on R1', leave-one-season-out here; all seasons in the shipped fit). python3 rxpm8.py -> rxpm8.json, rxpm_fit.json"""
import json, os, pickle, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gl, rxpm4 as R4, rxpm6 as R6, rxpm7 as R7
from rxpm4 import paired, CNT, YEARS, COL, ZC
SETS = pickle.load(open(os.path.join(gl.GB, 'sets.pkl'), 'rb'))['fit on R1']
import rxpm5 as R5
R5.dvec = lambda y: (1.0, SETS[y]); R5.FV = {y: R5.full_values(y) for y in YEARS}
RW = R7.RW


def vs(k, col):
    """rXPM vs a baseline column on design k (slopes refit on the other seasons)"""
    s0, s1 = {}, {}
    for y in YEARS:
        tr = [s for s in YEARS if s != y]; d = SETS[y]; yy = np.concatenate([RW[k][s][:, 0] for s in tr])
        xs = np.concatenate([RW[k][s][:, COL[col]] for s in tr]); b0 = float(xs @ yy / (xs @ xs))
        xv = np.concatenate([RW[k][s][:, COL['bpm']] + RW[k][s][:, ZC] @ d for s in tr]); b1 = float(xv @ yy / (xv @ xv))
        R = RW[k][y]; s0[y] = float(((R[:, 0] - b0 * R[:, COL[col]]) ** 2).sum()); s1[y] = float(((R[:, 0] - b1 * (R[:, COL['bpm']] + R[:, ZC] @ d)) ** 2).sum())
    tot = sum(float((RW[k][y][:, 0] ** 2).sum()) for y in YEARS); t, p, n = paired([s0[y] - s1[y] for y in YEARS])
    return {'R2': [round(1 - sum(s0.values()) / tot, 5), round(1 - sum(s1.values()) / tot, 5)], 't': t, 'p': round(p, 5), 'seasonsBetter': n, 'of': len(YEARS),
            'bySeason': {y: [round(1 - s0[y] / float((RW[k][y][:, 0] ** 2).sum()), 5), round(1 - s1[y] / float((RW[k][y][:, 0] ** 2).sum()), 5)] for y in YEARS},
            'gainPct': round(100 * ((1 - sum(s1.values()) / tot) / (1 - sum(s0.values()) / tot) - 1), 1)}


if __name__ == '__main__':
    out = {'form': 'rXPM = BPM + d.z - team minutes-weighted mean of d.z (x2 key below = rXPM, x1 = BPM)',
           'weights LOSO mean (rating points per SD of the rate x reliability)': {c: round(float(v), 3) for c, v in zip(CNT, np.mean([SETS[y] for y in YEARS], axis=0))},
           'weights LOSO sd': {c: round(float(v), 3) for c, v in zip(CNT, np.std([SETS[y] for y in YEARS], axis=0))}}
    out['absence designs'] = {k: {'vsBPM': vs(k, 'bpm'), 'vsGBPM': vs(k, 'gbpm')} for k in RW}
    for k in RW: print(k, {b: {x: v for x, v in e.items() if x != 'bySeason'} for b, e in out['absence designs'][k].items()}, flush=True)
    for nm, fn in (('C', R5.test_c), ('G', R5.guard_g), ('N', R5.guard_n), ('B', R5.test_b)):
        out[nm] = fn(); print(nm, json.dumps(out[nm]), flush=True)
    # shipped weights: all seasons, starters design
    d = R7.fit_d(['R1'], YEARS)
    json.dump({'src': 'scripts/research/cbb_xpm_nov26/rxpm8.py', 'design': 'starter absences (20+ mpg, 8+ games), seasons 2008-2026, ridge 30, base BPM',
               'rates': CNT, 'd': [round(float(v), 4) for v in d], 'krel': R4.KREL}, open(os.path.join(HERE, 'rxpm_fit.json'), 'w'), indent=1)
    out['shipped weights'] = {c: round(float(v), 3) for c, v in zip(CNT, d)}
    json.dump(out, open(os.path.join(HERE, 'rxpm8.json'), 'w'), indent=1)
