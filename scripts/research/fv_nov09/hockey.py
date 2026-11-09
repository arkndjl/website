# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""prereg H1 (rus) and H2 (gbm) on the hockey draft model"""
import sys, os, json, math
sys.path.insert(0, '/home/user/website/scripts')
import numpy as np
from scipy import stats
import hockey_prospects as H
from sklearn.ensemble import HistGradientBoostingRegressor as GB

W = H.war_tables(); rows = H.read_rows(W); H.nhl_so_far(rows, W); sc = H.outcome_scale(rows)
tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr]); F = [H.feats(r) for r in tr]
babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
kept = json.load(open('/home/user/website/data/hockey_fit.json'))['kept']
for f, r in zip(F, tr): f['rus'] = int(r.get('country') == 'RUS')
pick = np.array([r['pick'] for r in tr]); C = sorted(set(cls))
print('rows', len(tr), 'rus', sum(f['rus'] for f in F), 'kept', kept)

def mat(cols): return np.array([[f[c] for c in cols] for f in F])
def ols_pred(X, a, b): return np.clip(H.pred(H.ols(X[a], y[a]), X[b]), 20, 80)
allc = list(dict.fromkeys(kept + H.CANDS + ['cs']))
def gbm_pred(a, b):
    m = GB(max_depth=3, learning_rate=.05, max_iter=300, min_samples_leaf=40, l2_regularization=1.0, random_state=0)
    m.fit(mat(allc)[a], y[a]); return np.clip(m.predict(mat(allc)[b]), 20, 80)

def run(name, predfn):
    X0 = mat(kept); p0 = np.zeros(len(y)); p1 = np.zeros(len(y))
    for c in C:
        b = cls == c; p0[b] = ols_pred(X0, ~b, b); p1[b] = predfn(~b, b, p0[b])
    e0, e1 = (p0 - y) ** 2, (p1 - y) ** 2
    g = np.array([e0[cls == c].mean() - e1[cls == c].mean() for c in C])
    t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g))); p = float(stats.t.sf(t, len(g) - 1))
    top = pick <= 64
    a, b = cls <= 2015, cls > 2015
    f0 = ols_pred(X0, a, b); f1 = predfn(a, b, f0)
    res = dict(test=name, mse=[round(e0.mean(), 3), round(e1.mean(), 3)], gain=round(float(g.mean()), 3), t=round(float(t), 2), p=round(p, 4),
               wins=int((g > 0).sum()), of=len(g), top64=[round(e0[top].mean(), 2), round(e1[top].mean(), 2)],
               fwd=[round(float(np.mean((f0 - y[b]) ** 2)), 3), round(float(np.mean((f1 - y[b]) ** 2)), 3)],
               fwd_top64=[round(float(np.mean((f0 - y[b])[pick[b] <= 64] ** 2)), 2), round(float(np.mean((f1 - y[b])[pick[b] <= 64] ** 2)), 2)])
    print(res); return res

X1 = mat(kept + ['rus'])
out = [run('H1 rus', lambda a, b, p0: ols_pred(X1, a, b)),
       run('H2 gbm', lambda a, b, p0: .5 * p0 + .5 * gbm_pred(a, b))]
bb = H.ols(X1, y); out[0]['coef'] = round(float(bb[-1]), 3)
print('rus coef', bb[-1])
json.dump(out, open('/mnt/project-files/fv/sweep-nov09/hockey.json', 'w'), indent=1)
