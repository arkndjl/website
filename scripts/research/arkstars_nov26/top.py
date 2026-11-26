# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Shared pieces of the top-tier tests (prereg.md): a leave-one-class-out logit for the hit on the elite pool, and the
even-odds 5-star+ line with its report."""
import numpy as np


def logit(X, y, lam=1e-3):
    """standardised Newton logit with a small ridge; returns predict(A)"""
    m = X.mean(0); s = X.std(0); s[s == 0] = 1
    A = np.c_[np.ones(len(X)), (X - m) / s]; b = np.zeros(A.shape[1]); P = lam * np.eye(A.shape[1]); P[0, 0] = 0
    for _ in range(60):
        p = 1 / (1 + np.exp(-A @ b)); g = A.T @ (y - p) - P @ b; Hs = A.T @ (A * (p * (1 - p))[:, None]) + P
        st = np.linalg.solve(Hs, g); b = b + st
        if np.abs(st).max() < 1e-9: break
    raw = np.r_[b[0] - (b[1:] * m / s).sum(), b[1:] / s]      # on the unstandardised columns
    return (lambda Z: 1 / (1 + np.exp(-(raw[0] + np.asarray(Z, float) @ raw[1:])))), raw


def loco(X, hit, cls, pool, train, fwd=()):
    """p for every row (coefficients from the pool rows of the other training classes; forward classes from all of
    them) and the log loss of the hit"""
    p = np.full(len(hit), np.nan); tr = np.isin(cls, list(train))
    for c in train:
        f, _ = logit(X[pool & tr & (cls != c)], hit[pool & tr & (cls != c)]); p[cls == c] = f(X[cls == c])
    if len(fwd):
        f, _ = logit(X[pool & tr], hit[pool & tr]); m = np.isin(cls, list(fwd)); p[m] = f(X[m])
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return p, -(hit * np.log(q) + (1 - hit) * np.log(1 - q))


def _rate(hit, m, cls, classes, rng, extra=None):
    out = {'n': int(m.sum()), 'perClass': round(float(m.sum() / len(classes)), 2), 'hit': round(float(hit[m].mean()), 3) if m.any() else None}
    if m.any():
        bs = []
        for _ in range(4000):
            cc = rng.choice(classes, len(classes)); num = sum(hit[m & (cls == c)].sum() for c in cc); den = sum((m & (cls == c)).sum() for c in cc)
            if den: bs.append(num / den)
        out['ci90'] = [round(float(np.quantile(bs, .05)), 3), round(float(np.quantile(bs, .95)), 3)]
        for k, v in (extra or {}).items(): out[k] = round(float(v[m].mean()), 3)
    return out


def line_report(score, p, hit, cls, pool, train, fwd, ship, five, extra=None, X=None):
    """ship: mask of the shipped 5-star+ tier; five: mask of 5 stars or better (either line's plain tier = five less
    the tier). p: held-out chance of the hit."""
    rng = np.random.default_rng(26); train = list(train); tr = np.isin(cls, train)
    new = p >= 0.5
    out = {'new': _rate(hit, new & tr, cls, train, rng, extra), 'shipped': _rate(hit, ship & tr, cls, train, rng, extra),
           'plainUnderNew': _rate(hit, five & ~new & tr, cls, train, rng, extra), 'plainUnderShipped': _rate(hit, five & ~ship & tr, cls, train, rng, extra),
           'newByClass': {int(c): [int((new & (cls == c)).sum()), int(hit[new & (cls == c)].sum())] for c in train},
           'shippedByClass': {int(c): [int((ship & (cls == c)).sum()), int(hit[ship & (cls == c)].sum())] for c in train}}
    cal = []
    for a in np.arange(0, 1, .1):
        m = pool & tr & (p >= a) & (p < a + .1)
        if m.any(): cal.append({'p': f'{a:.1f}-{a + .1:.1f}', 'n': int(m.sum()), 'pred': round(float(p[m].mean()), 3), 'hit': round(float(hit[m].mean()), 3)})
    out['calibration'] = cal
    if X is not None and X.shape[1] == 1:
        _, raw = logit(X[pool & tr], hit[pool & tr]); out['lineScore'] = round(float(-raw[0] / raw[1]), 3); out['coef'] = [round(float(x), 5) for x in raw]
        bs = []
        for _ in range(1000):
            cc = rng.choice(train, len(train)); i = np.concatenate([np.where(pool & (cls == c))[0] for c in cc]); _, rw = logit(X[i], hit[i]); bs.append(-rw[0] / rw[1])
        out['lineScoreCi90'] = [round(float(np.quantile(bs, .05)), 3), round(float(np.quantile(bs, .95)), 3)]
    if len(fwd):
        fw = np.isin(cls, list(fwd))
        out['forward'] = {'new': _rate(hit, new & fw, cls, list(fwd), rng, extra), 'shipped': _rate(hit, ship & fw, cls, list(fwd), rng, extra),
                          'plainUnderNew': _rate(hit, five & ~new & fw, cls, list(fwd), rng, extra),
                          'byClass': {int(c): {'new': [int((new & (cls == c)).sum()), int(hit[new & (cls == c)].sum())], 'shipped': [int((ship & (cls == c)).sum()), int(hit[ship & (cls == c)].sum())]} for c in fwd}}
    n, pl = out['new'], out['plainUnderNew']
    a = bool(n['hit'] is not None and n['hit'] >= .5); b = bool(n.get('ci90') and pl['hit'] is not None and n['ci90'][0] > pl['hit']); c = bool(n['perClass'] >= 1)
    near = abs(n['perClass'] - out['shipped']['perClass']) <= 1
    out['rule'] = {'hit50': a, 'aboveplain': b, 'onePerClass': c, 'withinOneOfShipped': bool(near), 'moves': bool(a and b and c and not near)}
    return out
