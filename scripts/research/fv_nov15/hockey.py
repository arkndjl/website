# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""H1 two-part hockey draft grade: P(any NHL game) x mean outcome FV among those who played, class held out."""
import sys, os, json, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np
from scipy import stats
import hockey_prospects as H

W = H.war_tables(); rows = H.read_rows(W); H.nhl_so_far(rows, W); sc = H.outcome_scale(rows)
tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr]); F = [H.feats(r) for r in tr]
babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
kept = json.load(open(H.FIT))['kept']
X = np.array([[f[c] for c in kept] for f in F])
played = np.array([r['nhl_gp'] > 0 for r in tr])
pick = np.array([r['pick'] for r in tr]); C = sorted(set(cls))
print('rows', len(tr), 'played', played.mean().round(3), 'kept', kept, 'y|played', y[played].mean().round(2), 'y|not', y[~played].mean())


def logit(X, t, lam=1.0):
    X1 = np.column_stack([np.ones(len(X)), X]); w = np.zeros(X1.shape[1])
    P = lam * np.eye(X1.shape[1]); P[0, 0] = 0
    for _ in range(60):
        q = 1 / (1 + np.exp(-X1 @ w))
        w += np.linalg.solve((X1 * (q * (1 - q))[:, None]).T @ X1 + P, X1.T @ (t - q) - P @ w)
    return w


def lin(a, b): return np.clip(H.pred(H.ols(X[a], y[a]), X[b]), 20, 80)


def two(a, b):
    w = logit(X[a], played[a].astype(float))
    p = 1 / (1 + np.exp(-(w[0] + X[b] @ w[1:])))
    ap = a & played
    m = H.pred(H.ols(X[ap], y[ap]), X[b])
    return np.clip(20 + p * (np.clip(m, 20, 80) - 20), 20, 80)


p0 = np.zeros(len(y)); p1 = np.zeros(len(y))
for c in C:
    b = cls == c; p0[b] = lin(~b, b); p1[b] = two(~b, b)
e0, e1 = (p0 - y) ** 2, (p1 - y) ** 2
g = np.array([e0[cls == c].mean() - e1[cls == c].mean() for c in C])
t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g))); p = float(stats.t.sf(t, len(g) - 1))
top = pick <= 64
a, b = cls <= 2015, cls > 2015
f0, f1 = lin(a, b), two(a, b)
rho = lambda u, v: float(stats.spearmanr(u, v)[0])
res = dict(test='H1 two-part draft', mse=[round(e0.mean(), 3), round(e1.mean(), 3)], gain=round(float(g.mean()), 3), t=round(float(t), 2),
           p=round(p, 5), wins=int((g > 0).sum()), of=len(g), byClass=[round(float(v), 2) for v in g],
           top64=[round(e0[top].mean(), 2), round(e1[top].mean(), 2)], top64rho=[round(rho(p0[top], y[top]), 4), round(rho(p1[top], y[top]), 4)],
           fwd=[round(float(np.mean((f0 - y[b]) ** 2)), 3), round(float(np.mean((f1 - y[b]) ** 2)), 3)],
           fwd_top64=[round(float(np.mean((f0 - y[b])[pick[b] <= 64] ** 2)), 2), round(float(np.mean((f1 - y[b])[pick[b] <= 64] ** 2)), 2)],
           fwd_top64rho=[round(rho(f0[pick[b] <= 64], y[b][pick[b] <= 64]), 4), round(rho(f1[pick[b] <= 64], y[b][pick[b] <= 64]), 4)])
cal = []
for lo in range(20, 75, 5):
    m = (p1 >= lo) & (p1 < lo + 5)
    if m.sum() >= 5: cal.append([lo, int(m.sum()), round(float(p1[m].mean()), 1), round(float(y[m].mean()), 1)])
res['calib'] = cal
t32 = np.concatenate([np.where(cls == c)[0][np.argsort(-p1[cls == c])[:32]] for c in C])
t32o = np.concatenate([np.where(cls == c)[0][np.argsort(-p0[cls == c])[:32]] for c in C])
res['top32real'] = [round(float(y[t32o].mean()), 2), round(float(y[t32].mean()), 2)]
print(json.dumps(res, indent=1))
if len(sys.argv) > 1: json.dump(res, open(sys.argv[1], 'w'), indent=1)
np.save('/tmp/h1_p.npy', np.vstack([p0, p1, y, cls, pick]))
