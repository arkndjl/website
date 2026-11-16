#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T1 (prereg.md): the WTA hurdle fit on WTA + ATP rows, the analogue of the pooled top rungs that ship for international
basketball (internationals fit with college players). Shared slopes on the WTA kept drivers, a WTA intercept and
ridge-shrunk WTA x driver deviations; lambda nested from {1, 10, 100} by inner birth-year-out. October snapshot.

    python3 scripts/tennis_prospects.py --rows
    python3 scripts/research/fv_port_nov16/tennis_port.py   # -> scripts/research/fv_port_nov16/tennis_results.json"""
import json, math, os, pickle, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
import tennis_prospects as T
from scipy import stats

LAMS = (1.0, 10.0, 100.0)


def logit_r(X, y, pen, it=60):
    b = np.zeros(X.shape[1]); P = np.diag(pen)
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        H = X.T @ (X * (p * (1 - p) + 1e-9)[:, None]) + P
        d = np.linalg.solve(H, X.T @ (y - p) - P @ b); b += d
        if np.abs(d).max() < 1e-8: break
    return b


def ridge(X, y, pen):
    return np.linalg.solve(X.T @ X + np.diag(pen), X.T @ y)


class Pool:
    """design [1, wta, Z, wta x Z]; Z standardized on the WTA training rows"""
    def __init__(self, Fw, Fa, cols):
        self.cols = cols; self.m = Fw[cols].values.mean(0); self.s = Fw[cols].values.std(0) + 1e-9

    def X(self, F, wta):
        Z = (F[self.cols].values - self.m) / self.s; w = np.full((len(F), 1), float(wta))
        return np.hstack([np.ones((len(F), 1)), w, Z, w * Z])

    def pen(self, lam):
        k = len(self.cols); return np.r_[1e-3, 1e-3, np.full(k, 1e-3), np.full(k, lam)]


def fit_pool(Fw, yw, pw, Fa, ya, pa, cols, lam):
    pm = Pool(Fw, Fa, cols)
    X = np.vstack([pm.X(Fw, 1), pm.X(Fa, 0)]); y = np.r_[yw, ya]; pos = np.r_[pw, pa]
    bl = logit_r(X, pos.astype(float), pm.pen(lam)); bo = ridge(X[pos], y[pos], pm.pen(lam))
    return pm, bl, bo


def pred_pool(mod, F):
    pm, bl, bo = mod; X = pm.X(F, 1)
    p = 1 / (1 + np.exp(-np.clip(X @ bl, -30, 30))); return (1 - p) * 20 + p * (X @ bo)


def main():
    rows = pickle.load(open(T.ROWS, 'rb'))
    fit = json.load(open(os.path.join(T.ROOT if hasattr(T, 'ROOT') else os.path.dirname(SCR), 'data', 'tennis_prospects_fit.json')))
    snap = '%02d-%02d' % T.SEL_SNAP; cols = fit['wta']['kept']
    Xw, Fw, yw, pw, bw = T.snap_rows(rows, 'wta', snap)
    Xa, Fa, ya, pa, ba = T.snap_rows(rows, 'atp', snap)
    print('rows wta', len(Fw), 'atp', len(Fa), 'cols', cols)
    p0 = T.loso(Fw, yw, pw, bw, cols)[2]
    p1 = np.zeros(len(yw)); picks = {}
    for b in np.unique(bw):
        te = bw == b; trw = ~te; tra = ba != b
        # inner birth-year-out on the training years picks lambda
        inner = {}
        for lam in LAMS:
            e = []
            for b2 in np.unique(bw[trw]):
                ti = trw & (bw != b2); vi = bw == b2
                mod = fit_pool(Fw[ti], yw[ti], pw[ti], Fa[tra & (ba != b2)], ya[tra & (ba != b2)], pa[tra & (ba != b2)], cols, lam)
                e.append(np.mean((pred_pool(mod, Fw[vi]) - yw[vi]) ** 2))
            inner[lam] = float(np.mean(e))
        lam = min(inner, key=inner.get); picks[int(b)] = lam
        p1[te] = pred_pool(fit_pool(Fw[trw], yw[trw], pw[trw], Fa[tra], ya[tra], pa[tra], cols, lam), Fw[te])
        print(int(b), 'lambda', lam, flush=True)
    g = T.fold_mse(p0, yw, bw) - T.fold_mse(p1, yw, bw)
    t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g))); p = float(stats.t.sf(t, len(g) - 1))
    season = Xw.season.values
    t50 = lambda q: float(pd.Series(yw[np.argsort(-q)]).groupby(season[np.argsort(-q)]).head(50).mean())
    # forward: fit births <= 1993 on both tours, grade WTA 1994-97; lambda = the most picked
    lamf = max(set(picks.values()), key=list(picks.values()).count)
    trw, tew, tra = bw <= T.FWD, bw > T.FWD, ba <= T.FWD
    bl, bo = T.hurdle(Fw, yw, pw, cols, trw); q, mu = T.hpred(Fw[tew], cols, bl, bo); f0 = (1 - q) * 20 + q * mu
    f1 = pred_pool(fit_pool(Fw[trw], yw[trw], pw[trw], Fa[tra], ya[tra], pa[tra], cols, lamf), Fw[tew])
    yt, st = yw[tew], season[tew]
    ft = lambda q: float(pd.Series(yt[np.argsort(-q)]).groupby(st[np.argsort(-q)]).head(50).mean())
    out = {'T1': dict(gain=round(float(g.mean()), 3), t=round(float(t), 2), p=round(p, 4), wins=int((g > 0).sum()), of=len(g),
                      mse=[round(float(np.mean((p0 - yw) ** 2)), 3), round(float(np.mean((p1 - yw) ** 2)), 3)],
                      top50=[round(t50(p0), 2), round(t50(p1), 2)], lambdas=picks,
                      fwd=[round(float(np.mean((f0 - yt) ** 2)), 3), round(float(np.mean((f1 - yt) ** 2)), 3)],
                      fwd_top50=[round(ft(f0), 2), round(ft(f1), 2)])}
    print(json.dumps(out))
    json.dump(out, open(os.path.join(HERE, 'tennis_results.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
