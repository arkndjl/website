# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""W2/W3 top-weighted hurdle fit on the tennis October rows, birth year held out."""
import sys, os, json, math, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np, pandas as pd
from scipy import stats
import tennis_prospects as T

rows = pickle.load(open(T.ROWS, 'rb')); fit = json.load(open(T.FIT))
snap = '%02d-%02d' % T.SEL_SNAP
sig = lambda z: 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def flogit(X, y, w, l2=1e-3, it=60):
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = sig(X @ b)
        Hm = X.T @ (X * (w * p * (1 - p) + 1e-9)[:, None]) + l2 * np.eye(len(b))
        d = np.linalg.solve(Hm, X.T @ (w * (y - p)) - l2 * b); b += d
        if np.abs(d).max() < 1e-8: break
    return b


def wols(X, y, w):
    sw = np.sqrt(w); return np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]


def tt(g):
    g = np.asarray(g, float); t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))
    return round(float(t), 2), round(float(stats.t.sf(t, len(g) - 1)), 5)


OUT = []
for tour in T.TOURS:
    kept = fit[tour]['kept']
    X, F, y, pos, by = T.snap_rows(rows, tour, snap); season = X.season.values
    Xa = np.column_stack([np.ones(len(F)), F[kept].values])

    def base(tr, te):
        bl, bo = T.hurdle(F, y, pos, kept, tr); p, mu = T.hpred(F[te], kept, bl, bo); return (1 - p) * 20 + p * mu

    def cand(tr, te):
        bl, bo = T.hurdle(F, y, pos, kept, tr); p, mu = T.hpred(F[tr], kept, bl, bo)
        w = 1 + np.maximum(0, (1 - p) * 20 + p * mu - 30) / 10
        A = Xa[tr]; b1 = flogit(A, pos[tr].astype(float), w); m = pos[tr]; b2 = wols(A[m], y[tr][m], w[m])
        q = sig(Xa[te] @ b1); return (1 - q) * 20 + q * (Xa[te] @ b2)

    p0 = np.zeros(len(y)); p1 = np.zeros(len(y))
    for b in np.unique(by):
        te = by == b; p0[te] = base(~te, te); p1[te] = cand(~te, te)
    e0, e1 = (p0 - y) ** 2, (p1 - y) ** 2; top = p0 >= 40
    U = np.unique(by)
    ga = [e0[by == b].mean() - e1[by == b].mean() for b in U]
    gt = [e0[(by == b) & top].mean() - e1[(by == b) & top].mean() for b in U if ((by == b) & top).sum()]
    tr, te = by <= T.FWD, by > T.FWD
    f0, f1 = base(tr, te), cand(tr, te); yt, st = y[te], season[te]
    ft = lambda p: float(pd.Series(yt[np.argsort(-p)]).groupby(st[np.argsort(-p)]).head(50).mean())
    res = dict(test='W top-weighted ' + tour, n=len(y), nTop=int(top.sum()),
               all=dict(mse=[round(float(e0.mean()), 3), round(float(e1.mean()), 3)], t=tt(ga)[0], wins=int(sum(v > 0 for v in ga)), of=len(ga)),
               top40=dict(mse=[round(float(e0[top].mean()), 3), round(float(e1[top].mean()), 3)], t=tt(gt)[0], p=tt(gt)[1], wins=int(sum(v > 0 for v in gt)), of=len(gt)),
               fwd_mse=[round(float(np.mean((f0 - yt) ** 2)), 3), round(float(np.mean((f1 - yt) ** 2)), 3)], fwd_top50=[round(ft(f0), 3), round(ft(f1), 3)])
    print(json.dumps(res)); OUT.append(res)
if len(sys.argv) > 1: json.dump(OUT, open(sys.argv[1], 'w'), indent=1)
