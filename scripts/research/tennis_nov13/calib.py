# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import *
from mtests import *
rows, players, tn = load_rows()
rec = base_rec(rows, name='base_ta')
F, m = arrays(rec); z = wf_logit(F, m)
for lab, mask in [(str(y), m['y'] == y) for y in range(2018, 2027)] + [('2023-26', m['y'] >= 2023), ('2025-26 close rows', ~np.isnan(m['pc']))]:
    X = z[mask][:, None]
    w = newton(np.vstack([X, -X]), np.r_[np.ones(len(X)), np.zeros(len(X))], ridge=1e-9, w0=np.ones(1))
    p = 1 / (1 + np.exp(-X[:, 0])); H = (2 * (X[:, 0] ** 2) * p * (1 - p)).sum()
    print(lab, 'n', int(mask.sum()), 'slope', round(float(w[0]), 3), 'se', round(H ** -.5, 3), 'LL', round(float(nll(z[mask]).mean()), 5))
for lv in 'GMA':
    for per in ((2012, 2022), (2023, 2026)):
        mask = (m['lv'] == lv) & (m['y'] >= per[0]) & (m['y'] <= per[1])
        X = z[mask][:, None]
        w = newton(np.vstack([X, -X]), np.r_[np.ones(len(X)), np.zeros(len(X))], ridge=1e-9, w0=np.ones(1))
        p = 1 / (1 + np.exp(-X[:, 0])); H = (2 * (X[:, 0] ** 2) * p * (1 - p)).sum()
        print('level', lv, per, 'n', int(mask.sum()), 'slope', round(float(w[0]), 3), 'se', round(H ** -.5, 3))
