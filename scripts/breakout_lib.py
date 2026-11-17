# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Shared fitting and held-out testing for the Potential Breakout research scripts (scripts/*_breakout_research.py).

Two kinds of test, both leave-one-season-out (the held-out season's rows never touch the fit, standardization included):
- workload scaling: weighted least squares of next-season efficiency on this season's efficiency + the change in
  workload (+ player traits x that change). Error = weighted squared error.
- breakout odds: ridge logistic of "broke out next season" on a baseline + one candidate signal. Error = log loss.
Gain = baseline error - candidate error per held-out season; t = mean / SE over seasons (season-block, so players
inside a season share one draw). PASS = t >= 2 and better in more than half the seasons, then Holm across the
candidates a sport tested. numpy only."""
import math

import numpy as np


def zfit(X, w=None):
    w = np.ones(len(X)) if w is None else w
    mu = np.average(X, axis=0, weights=w)
    sd = np.sqrt(np.average((X - mu) ** 2, axis=0, weights=w))
    sd[sd < 1e-9] = 1.0
    return mu, sd


def wls(X, y, w, lam=1e-3):
    """weighted ridge least squares with intercept; returns (b0, b) on the raw scale of X"""
    mu, sd = zfit(X, w)
    Z = (X - mu) / sd
    A = np.column_stack([np.ones(len(Z)), Z])
    W = w / w.mean()
    R = lam * np.eye(A.shape[1])
    R[0, 0] = 0
    beta = np.linalg.solve(A.T @ (A * W[:, None]) + R * len(Z), A.T @ (W * y))
    b = beta[1:] / sd
    return beta[0] - float(mu @ b), b


def logit(X, y, w=None, lam=1e-3, it=60):
    """weighted ridge logistic (IRLS) with intercept; returns (b0, b) on the raw scale of X"""
    w = np.ones(len(X)) if w is None else w
    mu, sd = zfit(X, w)
    Z = (X - mu) / sd
    A = np.column_stack([np.ones(len(Z)), Z])
    W0 = w / w.mean()
    beta = np.zeros(A.shape[1])
    p0 = np.clip(np.average(y, weights=W0), 1e-4, 1 - 1e-4)
    beta[0] = math.log(p0 / (1 - p0))
    R = lam * np.eye(A.shape[1]) * len(Z)
    R[0, 0] = 0
    for _ in range(it):
        eta = np.clip(A @ beta, -30, 30)
        p = 1 / (1 + np.exp(-eta))
        g = A.T @ (W0 * (y - p)) - R @ beta
        H = A.T @ (A * (W0 * p * (1 - p))[:, None]) + R
        step = np.linalg.solve(H, g)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    b = beta[1:] / sd
    return beta[0] - float(mu @ b), b


def sig(x):
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def loso(seasons, fit_pred, err):
    """per held-out season: mean error. fit_pred(train_mask, test_mask) -> predictions for test rows;
    err(pred, test_mask) -> per-row error. Returns {season: (sum error, sum weight)}"""
    out = {}
    for s in sorted(set(seasons.tolist())):
        te = seasons == s
        tr = ~te
        if te.sum() < 5:
            continue
        out[s] = err(fit_pred(tr, te), te)
    return out


def compare(base, cand):
    """base/cand: {season: (err sum, weight sum)} -> dict with held-out errors, gain, t, seasons won"""
    S = sorted(set(base) & set(cand))
    bw = sum(base[s][1] for s in S)
    b = sum(base[s][0] for s in S) / bw
    c = sum(cand[s][0] for s in S) / bw
    g = np.array([(base[s][0] - cand[s][0]) / base[s][1] for s in S])
    wts = np.array([base[s][1] for s in S])
    m = np.average(g, weights=wts)
    se = math.sqrt(np.average((g - m) ** 2, weights=wts) / max(1, len(S) - 1))
    t = m / se if se > 0 else 0.0
    won = int((g > 0).sum())
    return {'base': round(float(b), 5), 'cand': round(float(c), 5), 'gain': round(float(b - c), 6),
            't': round(float(t), 2), 'won': won, 'seasons': len(S)}


def holm(results, alpha=0.05):
    """results: {name: compare-dict}; adds 'p' (one-sided normal on t) and 'pass' with Holm step-down"""
    names = sorted(results, key=lambda k: -results[k]['t'])
    m = len(names)
    alive = True
    for i, k in enumerate(names):
        r = results[k]
        p = 0.5 * math.erfc(r['t'] / math.sqrt(2))
        r['p'] = round(p, 4)
        ok = alive and p <= alpha / (m - i) and r['won'] * 2 > r['seasons']
        if not ok:
            alive = False
        r['pass'] = bool(ok)
    return results
