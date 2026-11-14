# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""F6 (pre-registered): gradient-boosted trees on the baseline inputs, averaged .5 with the linear hurdle on E[FV].
Hyperparameters fixed before the run (depth 3, rate .05, 200 rounds, 50 a leaf, l2 1); school-held-out folds."""
import json
import math
import os
import sys

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data as D   # noqa: E402
import rh as H     # noqa: E402
R, T = H.R, H.T

KW = dict(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=50, l2_regularization=1.0, random_state=0)
data = H.prep(H.dedupe(D.load())); sz = R.size_norms(data)
X = H.X_of(data, H.BASE['on'] + ['pos'], sz)
y = np.array([r['on'] for r in data], float); fv = np.array([r['fv'] or 0 for r in data], float)
cls = np.array([r['year'] for r in data]); yo = np.array([r['out'] for r in data]); fo = R.folds(data)
p0, f0 = H.cv(data, H.BASE['on'], H.BASE['fv'], sz)
e0 = p0 * np.maximum(f0, R.FLOOR) + (1 - p0) * R.FLOOR
pt = np.zeros(len(data)); ft = np.zeros(len(data))
for f in range(5):
    tr = fo != f; te = ~tr
    pt[te] = HistGradientBoostingClassifier(**KW).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    m = tr & (y == 1); ft[te] = HistGradientBoostingRegressor(**KW).fit(X[m], fv[m]).predict(X[te])
et = pt * np.maximum(ft, R.FLOOR) + (1 - pt) * R.FLOOR
out = {}
for nm, e in (('trees', et), ('blend', (e0 + et) / 2)):
    d = np.array([T.spear(e[cls == c], yo[cls == c]) - T.spear(e0[cls == c], yo[cls == c]) for c in sorted(set(cls))])
    out[nm] = {'rho': round(T.spear(e, yo), 4), 'base': round(T.spear(e0, yo), 4), 'won': f'{int((d > 0).sum())}/{len(d)}',
               't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)}
ll = lambda p: -(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1)))
out['ll'] = {'linear': round(float(ll(p0).mean()), 5), 'trees': round(float(ll(pt).mean()), 5), 'blend': round(float(ll((p0 + pt) / 2).mean()), 5)}
top = lambda e, q: round(float(np.mean(yo[e >= np.quantile(e, 1 - q)])), 3)
out['top3 mean outcome'] = {'linear': top(e0, .03), 'blend': top((e0 + et) / 2, .03)}
print(json.dumps(out, indent=1))
f = os.path.join(HERE, 'f_tests.json'); prev = json.load(open(f)) if os.path.exists(f) else {}
prev['F6 tree blend'] = out; json.dump(prev, open(f, 'w'), indent=1)
