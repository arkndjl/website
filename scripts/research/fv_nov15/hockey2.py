# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""H3 Central Scouting rise and W1 top-weighted least squares on the hockey draft model, class held out."""
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
for f, r in zip(F, tr):
    c = r.get('css') or {}
    f['crise'] = math.log(c['mid']) - math.log(c['final']) if c.get('mid') and c.get('final') and not r['G'] else 0.0
X0 = np.array([[f[c] for c in kept] for f in F]); X1 = np.array([[f[c] for c in kept + ['crise']] for f in F])
pick = np.array([r['pick'] for r in tr]); C = sorted(set(cls)); top = pick <= 64
rho = lambda u, v: float(stats.spearmanr(u, v)[0])


def wols(X, y, w, lam=1.0):
    X1_ = np.column_stack([np.ones(len(X)), X]); P = lam * np.eye(X1_.shape[1]); P[0, 0] = 0
    return np.linalg.solve((X1_ * w[:, None]).T @ X1_ + P, (X1_ * w[:, None]).T @ y)


def lin(X, a, b): return np.clip(H.pred(H.ols(X[a], y[a]), X[b]), 20, 80)


def wls(X, a, b):
    g0 = np.clip(H.pred(H.ols(X[a], y[a]), X[a]), 20, 80)
    return np.clip(H.pred(wols(X[a], y[a], 1 + np.maximum(0, g0 - 30) / 10), X[b]), 20, 80)


def run(name, base, cand, sel):
    p0 = np.zeros(len(y)); p1 = np.zeros(len(y))
    for c in C:
        b = cls == c; p0[b] = base(~b, b); p1[b] = cand(~b, b)
    e0, e1 = (p0 - y) ** 2, (p1 - y) ** 2
    def ft(m):
        g = np.array([e0[(cls == c) & m].mean() - e1[(cls == c) & m].mean() for c in C])
        t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))
        return dict(mse=[round(float(e0[m].mean()), 3), round(float(e1[m].mean()), 3)], t=round(float(t), 2), p=round(float(stats.t.sf(t, len(g) - 1)), 5), wins=int((g > 0).sum()), of=len(g))
    a, b = cls <= 2015, cls > 2015
    f0, f1 = base(a, b), cand(a, b); tb = pick[b] <= 64
    res = dict(test=name, all=ft(np.ones(len(y), bool)), top64=ft(top), top64rho=[round(rho(p0[top], y[top]), 4), round(rho(p1[top], y[top]), 4)],
               fwd=[round(float(np.mean((f0 - y[b]) ** 2)), 3), round(float(np.mean((f1 - y[b]) ** 2)), 3)],
               fwd_top64=[round(float(np.mean((f0 - y[b])[tb] ** 2)), 2), round(float(np.mean((f1 - y[b])[tb] ** 2)), 2)],
               fwd_top64rho=[round(rho(f0[tb], y[b][tb]), 4), round(rho(f1[tb], y[b][tb]), 4)])
    print(json.dumps(res)); return res


out = [run('H3 css rise', lambda a, b: lin(X0, a, b), lambda a, b: lin(X1, a, b), None),
       run('W1 top-weighted', lambda a, b: lin(X0, a, b), lambda a, b: wls(X0, a, b), None)]
out[0]['coef'] = round(float(H.ols(X1, y)[-1]), 3); out[0]['n'] = int(sum(1 for f in F if f['crise'] != 0))
out[1]['coef'] = dict(zip(['const'] + kept, [round(float(v), 3) for v in wols(X0, y, 1 + np.maximum(0, np.clip(H.pred(H.ols(X0, y), X0), 20, 80) - 30) / 10)]))
print(out[0]['coef'], out[0]['n'], out[1]['coef'])
if len(sys.argv) > 1: json.dump(out, open(sys.argv[1], 'w'), indent=1)
