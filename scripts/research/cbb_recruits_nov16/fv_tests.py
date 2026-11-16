# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family FV: P1 ordinal ladder, P2 Poisson value part, against the shipped hurdle (classes 2009-16 held out)."""
import json
import math
import os

import numpy as np

from common import C, CP, CV, T, OUT, load, tstat


def Z(F, cols, m=None, s=None):
    X = np.array([[f[c] for c in cols] for f in F], float)
    if m is None: m, s = C.std_fit(X)
    return np.clip((X - m) / s, -4, 4), m, s


class Ladder:
    def fit(self, F, ts):
        fv = ts + 20; self.r = []
        for j, t in enumerate(T):
            at = fv >= (T[j - 1] if j else 20); y = (fv[at] >= t).astype(float)
            cols = CP if j == 0 else ['lrk']; lam = 1.0 if t <= 55 else 10.0
            Fa = [F[i] for i in np.where(at)[0]]
            if y.sum() == 0 or y.sum() == len(y): self.r.append((cols, None, None, float(y.mean()) if len(y) else 0.0)); continue
            X, m, s = Z(Fa, cols); self.r.append((cols, (m, s), C.logit_fit(X, y, lam), None))
        return self

    def above(self, F):
        """P(rfv >= T_j), one column a threshold"""
        out = np.ones((len(F), len(T))); cur = np.ones(len(F))
        for j, (cols, ms, b, const) in enumerate(self.r):
            if b is None: p = np.full(len(F), const)
            else:
                X, _, _ = Z(F, cols, *ms); p = 1 / (1 + np.exp(-(b[0] + X @ b[1:])))
            cur = cur * p; out[:, j] = cur
        return out


def e_of(A): return 20 + 10 * A[:, 0] + 5 * A[:, 1:].sum(1)


def hurdle_above(M, F):
    p, mu = M.parts(F)
    return np.array([[M.above(float(pi), float(mi), t - 20) for t in T] for pi, mi in zip(p, mu)])


class Pois(C.Hurdle):
    """the hurdle with the value part fit on the level: E[ts | NBA] = exp(a + b z), Poisson quasi-likelihood, ridge 2"""
    def fit(self, F, ts):
        super().fit(F, ts)
        pos = ts > 0; Xv = np.array([[f[c] for c in self.cv] for f in F])[pos]
        Zv = np.clip((Xv - self.mv) / self.sv, -4, 4); A = np.c_[np.ones(len(Zv)), Zv]; y = ts[pos]
        b = np.r_[math.log(y.mean()), np.zeros(Zv.shape[1])]; pen = np.diag(np.r_[0, np.full(Zv.shape[1], 2.0)])
        for _ in range(100):
            mu = np.exp(A @ b); st = np.linalg.solve(A.T @ (A * mu[:, None]) + pen, A.T @ (y - mu) - pen @ b)
            b += st
            if np.abs(st).max() < 1e-9: break
        self.bq = b
        return self

    def ets(self, F, shrink=1.0):
        p, _ = self.parts(F, shrink)
        Xv = np.clip((np.array([[f[c] for c in self.cv] for f in F]) - self.mv) / self.sv, -4, 4)
        return p * np.exp(self.bq[0] + shrink * (Xv @ self.bq[1:]))


def main():
    H, rows, F, cls, ts = load(C.TRAIN + C.FORWARD)
    tr = np.isin(cls, C.TRAIN); fv = ts + 20
    I = (fv[:, None] >= np.array(T)[None, :]).astype(float)
    A0 = np.zeros((len(rows), len(T))); A1 = np.zeros_like(A0); E0 = np.zeros(len(rows)); E2 = np.zeros(len(rows))
    def fold(te, trn):
        Ft = [F[i] for i in np.where(trn)[0]]; Fe = [F[i] for i in np.where(te)[0]]
        M = C.Hurdle(CP, CV).fit(Ft, ts[trn]); A0[te] = hurdle_above(M, Fe); E0[te] = 20 + M.ets(Fe)
        A1[te] = Ladder().fit(Ft, ts[trn]).above(Fe)
        E2[te] = 20 + Pois(CP, CV).fit(Ft, ts[trn]).ets(Fe)
    for c in C.TRAIN: fold(cls == c, tr & (cls != c))
    fold(~tr, tr)
    E1 = e_of(A1)
    rps0 = ((A0 - I) ** 2).sum(1); rps1 = ((A1 - I) ** 2).sum(1)
    se0, se1, se2 = (E0 - fv) ** 2, (E1 - fv) ** 2, (E2 - fv) ** 2
    rk = np.array([r['rk'] or 999 for r in rows])
    def gate(d, m):
        by = [float(d[m & (cls == c)].mean()) for c in sorted(set(cls[m]))]
        return {'gain': round(float(d[m].mean()), 5), 't': round(tstat(d[m]), 2), 'tClass': round(tstat(by), 2), 'won': f'{sum(x > 0 for x in by)}/{len(by)}',
                'byClass': [round(x, 4) for x in by]}
    def top(E, m):
        return {f'{lo}-{hi}': {'n': int((m & (rk >= lo) & (rk <= hi)).sum()), 'pred': round(float(E[m & (rk >= lo) & (rk <= hi)].mean()), 1),
                               'real': round(float(fv[m & (rk >= lo) & (rk <= hi)].mean()), 1)} for lo, hi in ((1, 5), (6, 10), (11, 25), (26, 50), (51, 100), (101, 400))}
    out = {'n': int(tr.sum()), 'mse': {'shipped': round(float(se0[tr].mean()), 3), 'ladder': round(float(se1[tr].mean()), 3), 'poisson': round(float(se2[tr].mean()), 3)},
           'rps': {'shipped': round(float(rps0[tr].mean()), 5), 'ladder': round(float(rps1[tr].mean()), 5)},
           'P1': {'rps': gate(rps0 - rps1, tr), 'mse': gate(se0 - se1, tr), 'forward_rps': gate(rps0 - rps1, ~tr), 'forward_mse': gate(se0 - se1, ~tr)},
           'P2': {'mse': gate(se0 - se2, tr), 'forward_mse': gate(se0 - se2, ~tr)},
           'byRank': {'shipped': top(E0, tr), 'ladder': top(E1, tr), 'poisson': top(E2, tr)},
           'rho': {k: round(float(np.mean([C.spearman(E[cls == c], fv[cls == c]) for c in C.TRAIN])), 4) for k, E in (('shipped', E0), ('ladder', E1), ('poisson', E2))},
           # each threshold's Brier, shipped vs ladder (where the ladder's gain or loss sits)
           'brier': {str(t): [round(float(((A0[tr, j] - I[tr, j]) ** 2).mean()), 5), round(float(((A1[tr, j] - I[tr, j]) ** 2).mean()), 5)] for j, t in enumerate(T)}}
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.path.join(OUT, 'fv_tests.json'), 'w'), indent=1)
    np.save(os.path.join(OUT, 'heldout_E.npy'), np.c_[cls, E0, E1, E2])


if __name__ == '__main__':
    main()
