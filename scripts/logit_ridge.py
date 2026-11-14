# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Ridge logistic regression on standardized inputs (numpy only), shared by the availability fits (nfl_q.py, nba_play.py)."""
import numpy as np

LAMS = (0.3, 1.0, 3.0, 10.0, 30.0)


def logloss(p, y, w=None):
    p = np.clip(p, 0.005, 0.995)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def fit_ridge(X, y, lam, w=None, iters=60):
    """Newton steps; returns (b with the constant first, column means, column sds). The constant is not penalized."""
    mu = X.mean(0); sd = X.std(0); sd[sd < 1e-9] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    w = np.ones(len(y)) if w is None else w / w.mean()
    b = np.zeros(Z.shape[1])
    pm = float(np.clip((w * y).sum() / w.sum(), 1e-4, 1 - 1e-4)); b[0] = np.log(pm / (1 - pm))
    P = np.eye(Z.shape[1]) * lam; P[0, 0] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(Z @ b, -30, 30)))
        g = Z.T @ (w * (p - y)) + P @ b
        Hs = (Z * (w * p * (1 - p))[:, None]).T @ Z + P
        step = np.linalg.solve(Hs, g)
        b -= step
        if np.abs(step).max() < 1e-8:
            break
    return b, mu, sd


def predict(X, b, mu, sd):
    return 1 / (1 + np.exp(-np.clip(np.column_stack([np.ones(len(X)), (X - mu) / sd]) @ b, -30, 30)))


def pick_lambda(X, y, S, w=None, lams=LAMS):
    """leave-one-season-out log loss on the tune rows"""
    best = None
    for lam in lams:
        ll = 0.0
        for s in sorted(set(S)):
            tr, te = S != s, S == s
            b, mu, sd = fit_ridge(X[tr], y[tr], lam, None if w is None else w[tr])
            l = logloss(predict(X[te], b, mu, sd), y[te])
            ll += float((l * (1 if w is None else w[te])).sum())
        if best is None or ll < best[0]:
            best = (ll, lam)
    return best[1]
