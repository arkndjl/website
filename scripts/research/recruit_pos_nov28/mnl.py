"""Multinomial logit with an L2 penalty, Newton steps (numpy only). Soft targets allowed (rows of Y sum to 1)."""
import numpy as np


def fit_newton(X, Y, lam=1.0, w=None, iters=30, tol=1e-7, B0=None):
    n, d = X.shape; K = Y.shape[1]
    w = np.ones(n) if w is None else w
    B = np.zeros((d, K)) if B0 is None else B0.copy()
    pen = np.full(d, lam); pen[0] = 1e-2          # column 0 = intercept, barely penalised
    def obj(B):
        Z = X @ B; Z -= Z.max(1, keepdims=True); P = np.exp(Z); P /= P.sum(1, keepdims=True)
        return -(w[:, None] * Y * np.log(P + 1e-12)).sum() + .5 * (pen[:, None] * B * B).sum(), P
    last = np.inf
    for _ in range(iters):
        ll, P = obj(B)
        G = X.T @ (w[:, None] * (P - Y)) + pen[:, None] * B           # d x K
        H = np.zeros((d * K, d * K))
        for a in range(K):
            for b in range(a, K):
                s = w * P[:, a] * ((a == b) - P[:, b])
                blk = (X * s[:, None]).T @ X
                H[a * d:(a + 1) * d, b * d:(b + 1) * d] = blk
                if a != b: H[b * d:(b + 1) * d, a * d:(a + 1) * d] = blk
        H += np.diag(np.tile(pen, K)) + 1e-8 * np.eye(d * K)
        step = np.linalg.solve(H, G.T.reshape(-1)).reshape(K, d).T
        a = 1.0
        while a > 1e-4:
            nb = B - a * step; nl, _ = obj(nb)
            if nl <= ll: break
            a *= .5
        B = nb
        if abs(last - ll) < tol * max(1, abs(ll)): break
        last = ll
    return B


def predict(X, B):
    Z = X @ B; Z -= Z.max(1, keepdims=True); P = np.exp(Z); return P / P.sum(1, keepdims=True)


def logloss(P, Y):
    return -(Y * np.log(np.clip(P, 1e-12, 1))).sum(1)


def fit_lbfgs(X, Y, lam=1.0, w=None, iters=500, m=12, tol=1e-9, B0=None):
    """the same objective by L-BFGS (fast when d x K is large)"""
    n, d = X.shape; K = Y.shape[1]
    w = np.ones(n) if w is None else w
    pen = np.full(d, lam); pen[0] = 1e-2
    def fg(b):
        B = b.reshape(d, K); Z = X @ B; Z -= Z.max(1, keepdims=True); P = np.exp(Z); P /= P.sum(1, keepdims=True)
        f = -(w[:, None] * Y * np.log(P + 1e-12)).sum() + .5 * (pen[:, None] * B * B).sum()
        return f, (X.T @ (w[:, None] * (P - Y)) + pen[:, None] * B).reshape(-1)
    x = np.zeros(d * K) if B0 is None else B0.reshape(-1).copy()
    f, g = fg(x); S, Yv = [], []
    for _ in range(iters):
        q = g.copy(); al = []
        for s, yv in reversed(list(zip(S, Yv))):
            a = s @ q / (yv @ s); al.append(a); q -= a * yv
        if S: q *= (S[-1] @ Yv[-1]) / (Yv[-1] @ Yv[-1])
        for (s, yv), a in zip(zip(S, Yv), reversed(al)):
            q += s * (a - yv @ q / (yv @ s))
        p = -q; t = 1.0; gp = g @ p
        if gp >= 0: p = -g; gp = g @ p; S, Yv = [], []
        while True:
            xn = x + t * p; fn, gn = fg(xn)
            if fn <= f + 1e-4 * t * gp or t < 1e-10: break
            t *= .5
        s, yv = xn - x, gn - g
        if s @ yv > 1e-12: S.append(s); Yv.append(yv); S, Yv = S[-m:], Yv[-m:]
        if abs(f - fn) < tol * max(1, abs(f)): x, f, g = xn, fn, gn; break
        x, f, g = xn, fn, gn
    return x.reshape(d, K)


fit = fit_lbfgs
