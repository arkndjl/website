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


# ---------- gradient-boosted trees (log loss), numpy fit, plain-dict trees served stdlib ----------
def _bins(X, nb=32):
    return [np.unique(np.quantile(X[:, j], np.linspace(0, 1, nb + 1)[1:-1])) for j in range(X.shape[1])]


def _tree(X, g, h, cuts, depth, min_leaf, lam=1.0):
    def leaf(idx):
        return {'v': float(-g[idx].sum() / (h[idx].sum() + lam))}

    def grow(idx, d):
        if d == 0 or len(idx) < 2 * min_leaf:
            return leaf(idx)
        G, H = g[idx].sum(), h[idx].sum()
        best = (0.0, None, None)
        for j, cj in enumerate(cuts):
            xj = X[idx, j]
            for c in cj:
                m = xj <= c
                nl = m.sum()
                if nl < min_leaf or len(idx) - nl < min_leaf:
                    continue
                gl, hl = g[idx][m].sum(), h[idx][m].sum()
                gain = gl * gl / (hl + lam) + (G - gl) ** 2 / (H - hl + lam) - G * G / (H + lam)
                if gain > best[0]:
                    best = (gain, j, float(c))
        if best[1] is None:
            return leaf(idx)
        m = X[idx, best[1]] <= best[2]
        return {'f': best[1], 't': best[2], 'l': grow(idx[m], d - 1), 'r': grow(idx[~m], d - 1)}
    return grow(np.arange(len(X)), depth)


def tree_pred(t, x):
    while 'v' not in t:
        t = t['l'] if x[t['f']] <= t['t'] else t['r']
    return t['v']


def gbm_fit(X, y, rounds=400, lr=0.05, depth=3, min_leaf=60, Xv=None, yv=None):
    """returns (f0, trees, best_rounds). With a validation set, best_rounds = argmin validation log loss."""
    p0 = min(max(y.mean(), 1e-4), 1 - 1e-4)
    f0 = math.log(p0 / (1 - p0))
    F = np.full(len(y), f0)
    Fv = None if Xv is None else np.full(len(yv), f0)
    cuts = _bins(X)
    trees, hist = [], []
    for _ in range(rounds):
        p = sig(F)
        t = _tree(X, p - y, p * (1 - p), cuts, depth, min_leaf)
        t = _scale(t, lr)
        trees.append(t)
        F += np.array([tree_pred(t, x) for x in X])
        if Fv is not None:
            Fv += np.array([tree_pred(t, x) for x in Xv])
            pv = np.clip(sig(Fv), 1e-6, 1 - 1e-6)
            hist.append(float(-(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)).mean()))
    best = int(np.argmin(hist)) + 1 if hist else rounds
    return f0, trees, best


def _scale(t, lr):
    if 'v' in t:
        return {'v': round(t['v'] * lr, 6)}
    return {'f': t['f'], 't': round(t['t'], 6), 'l': _scale(t['l'], lr), 'r': _scale(t['r'], lr)}


def gbm_pred(f0, trees, X):
    return sig(np.array([f0 + sum(tree_pred(t, x) for t in trees) for x in X]))


# ---------- ceiling: 80th percentile of next season's value under a workload change ----------
TAU = 0.8


def pinball(y, c, w, tau=TAU):
    u = y - c
    return w * np.where(u >= 0, tau * u, (tau - 1) * u)


def wq(x, w, q):
    o = np.argsort(x)
    cw = np.cumsum(w[o]) / w.sum()
    return float(x[o][min(len(x) - 1, int(np.searchsorted(cw, q)))])


def ceiling_fit(X, y, w, SX=None, lam=1e-3):
    """mean by ridge WLS on X; spread: E|resid| by WLS on SX (or a constant), ceiling = mean + q x spread, q = the
    weighted 80th percentile of resid / spread. Returns a plain dict the live builds evaluate stdlib-only."""
    b0, b = wls(X, y, w, lam)
    r = y - (b0 + X @ b)
    if SX is None:
        c0, c = float(np.average(np.abs(r), weights=w)), np.zeros(0)
        s = np.full(len(y), c0)
    else:
        c0, c = wls(SX, np.abs(r), w, lam)
        s = np.maximum(c0 + SX @ c, 0.25 * np.average(np.abs(r), weights=w))
    return {'b0': float(b0), 'b': [float(v) for v in b], 'c0': float(c0), 'c': [float(v) for v in c],
            'floor': float(0.25 * np.average(np.abs(r), weights=w)), 'q': wq(r / s, w, TAU)}


def ceiling_pred(f, X, SX=None):
    m = f['b0'] + X @ np.array(f['b'])
    s = np.full(len(X), f['c0']) if not f['c'] else np.maximum(f['c0'] + SX @ np.array(f['c']), f['floor'])
    return m + f['q'] * s, m


def ceiling_tests(S, y, w, X0, cands, up):
    """S season, y next value, w weight, X0 base columns, cands {name: (extra mean columns, spread columns or None,
    names of the extra columns)}; passers' columns are pooled once by name for the final model,
    up = rows whose workload rose (coverage check). Each candidate alone vs the base (pinball loss at .80, held out by
    season), Holm, then base + passers. Returns (tests, keep, final compare, coverage, fit on all rows)."""
    def make(Xm, SX):
        def fp(tr, te):
            f = ceiling_fit(Xm[tr], y[tr], w[tr], None if SX is None else SX[tr])
            return ceiling_pred(f, Xm[te], None if SX is None else SX[te])[0]
        return fp
    err = lambda c, te: (float(pinball(y[te], c, w[te]).sum()), float(w[te].sum()))
    base = loso(S, make(X0, None), err)
    tests = {}
    for k, (xm, sx, _) in cands.items():
        Xm = X0 if xm is None else np.column_stack([X0, xm])
        tests[k] = compare(base, loso(S, make(Xm, sx), err))
    holm(tests)
    keep = [k for k in cands if tests[k]['pass']]
    xs, cols = [], []
    for k in keep:
        for j, nm in enumerate(cands[k][2]):
            if nm not in cols:
                cols.append(nm)
                xs.append(cands[k][0][:, j])
    sxs = [cands[k][1] for k in keep if cands[k][1] is not None]
    Xf = np.column_stack([X0] + xs) if xs else X0
    SXf = sxs[0] if sxs else None
    final = compare(base, loso(S, make(Xf, SXf), err)) if keep else None
    cov = {}
    for nm, m in (('all', np.ones(len(y), bool)), ('up', up)):
        hit = tot = 0.0
        for s in sorted(set(S.tolist())):
            te, tr = S == s, S != s
            f = ceiling_fit(Xf[tr], y[tr], w[tr], None if SXf is None else SXf[tr])
            c = ceiling_pred(f, Xf[te], None if SXf is None else SXf[te])[0]
            mm = m[te]
            hit += float((w[te] * (y[te] <= c))[mm].sum())
            tot += float(w[te][mm].sum())
        cov[nm] = round(hit / tot, 3) if tot else None
    return tests, keep, final, cov, ceiling_fit(Xf, y, w, SXf), cols


def ceiling_study(S, y, w, F, du, base, ctx, spread, up):
    """F: {input: array}. Pre-registered ceiling candidates from named inputs: usage change (dU, dU^2), usage change x
    context (dU, dU x ctx), scaled spread (spread inputs + |dU|). Returns the result dict with the fit's column names
    in the form scripts/ceiling.py evaluates."""
    X0 = np.column_stack([F[k] for k in base])
    cn = ['dU'] + ['dU*' + k for k in ctx]
    cands = {'usage change': (np.column_stack([du, du ** 2]), None, ['dU', 'dU2']),
             'usage change x context': (np.column_stack([du] + [du * F[k] for k in ctx]), None, cn),
             'scaled spread': (None, np.column_stack([F[k] for k in spread] + [np.abs(du)]), [])}
    tests, keep, final, cov, fit, extra = ceiling_tests(S, y, w, X0, cands, up)
    fit.update({'cols': list(base) + extra, 'scol': (list(spread) + ['absdU']) if 'scaled spread' in keep else []})
    return {'n': int(len(y)), 'seasons': [int(S.min()), int(S.max())], 'tests': tests, 'keep': keep, 'final': final,
            'coverage': cov, 'fit': fit}
