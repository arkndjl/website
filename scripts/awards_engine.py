# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Award voter model shared by every sport (scripts/awards.py builds the races, scripts/awards_research.py the tests).

A race is a season's candidate pool: one row a player, features x, and the voting order of those who got votes. The
model is a rank-ordered (exploded) conditional logit: P(winner) = softmax(x . b) over the pool, then P(2nd) the same
over the rest, down to DEPTH places, so finalists teach the model as well as winners. Features are standardised on
the training pool (mu, sd stored with the coefficients); L2 on b. Newton steps (the likelihood is concave).

fit() needs numpy; prob() is stdlib so the daily refresh runs without it."""
import math

DEPTH = 3


def prob(x_rows, b, mu, sd):
    """P(win) for each row of one race (stdlib): softmax of standardised x . b"""
    z = [sum(bk * ((xk - m) / s) for bk, xk, m, s in zip(b, x, mu, sd)) for x in x_rows]
    if not z: return []
    m = max(z)
    e = [math.exp(v - m) for v in z]
    t = sum(e)
    return [v / t for v in e]


def fit(races, l2=1.0, depth=DEPTH, iters=60):
    """races: list of (X list-of-rows, order list of row indices, best first). Returns b, mu, sd."""
    import numpy as np
    Xall = np.array([r for X, _ in races for r in X], float)
    mu = Xall.mean(0)
    sd = Xall.std(0)
    sd[sd == 0] = 1.0
    R = [((np.array(X, float) - mu) / sd, list(o)) for X, o in races]
    k = Xall.shape[1]
    b = np.zeros(k)

    def obj(b, need=True):
        f = -0.5 * l2 * b @ b
        g = -l2 * b
        H = -l2 * np.eye(k)
        for Z, o in R:
            alive = np.ones(len(Z), bool)
            for j in o[:depth]:
                zz = Z[alive]
                u = zz @ b
                m = u.max()
                p = np.exp(u - m); t = p.sum(); p /= t
                f += Z[j] @ b - m - np.log(t)
                if need:
                    mean = p @ zz
                    g += Z[j] - mean
                    H -= (zz * p[:, None]).T @ zz - np.outer(mean, mean)
                alive[j] = False
        return f, g, H

    f0, g, H = obj(b)
    for _ in range(iters):
        step = -np.linalg.solve(H, g)
        a = 1.0
        while a > 1e-6:
            f1 = obj(b + a * step, False)[0]
            if f1 >= f0 - 1e-12: break
            a *= 0.5
        b = b + a * step
        if np.abs(a * step).max() < 1e-7: break
        f0, g, H = obj(b)
    return b.tolist(), mu.tolist(), sd.tolist()


def loglik_winner(X, win, b, mu, sd):
    p = prob(X, b, mu, sd)
    return math.log(max(p[win], 1e-12)), p


def loglik_order(X, order, b, mu, sd, k):
    """log-likelihood of the first k places of the order (the exploded logit's own objective on one race)"""
    z = [sum(bk * ((xk - m) / s) for bk, xk, m, s in zip(b, x, mu, sd)) for x in X]
    alive = set(range(len(z)))
    ll = 0.0
    for j in order[:k]:
        m = max(z[i] for i in alive)
        ll += z[j] - m - math.log(sum(math.exp(z[i] - m) for i in alive))
        alive.discard(j)
    return ll


def loso_k(races, seasons, k, l2=1.0, cols=None):
    """leave-one-season-out for a top-k race (k named, order = the named): held-out log-likelihood of the named k and
    how many of the model's top k were named"""
    out = []
    pick = (lambda X: [[r[c] for c in cols] for r in X]) if cols is not None else (lambda X: X)
    for i, s in enumerate(seasons):
        X, o = races[i]
        if not o: continue
        b, mu, sd = fit([(pick(Z), q) for (Z, q), t in zip(races, seasons) if t != s and q], l2=l2, depth=k)
        Xp = pick(X)
        z = [sum(bk * ((xk - m) / v) for bk, xk, m, v in zip(b, x, mu, sd)) for x in Xp]
        top = set(sorted(range(len(z)), key=lambda j: -z[j])[:k])
        hit = len(top & set(o[:k]))
        out.append({'season': s, 'll': loglik_order(Xp, o, b, mu, sd, k), 'hit': hit, 'pw': hit / k, 'fav_p': 0.0})
    return out


def loso(races, seasons, l2=1.0, depth=DEPTH, cols=None):
    """leave-one-season-out: for each season fit on the others, score log P(actual winner) and whether the model's
    favourite won. races[i] belongs to seasons[i]. cols: feature columns to use (None = all)."""
    out = []
    pick = (lambda X: [[r[c] for c in cols] for r in X]) if cols is not None else (lambda X: X)
    for i, s in enumerate(seasons):
        train = [(pick(X), o) for (X, o), t in zip(races, seasons) if t != s and o]
        X, o = races[i]
        if not o: continue
        b, mu, sd = fit(train, l2=l2, depth=depth)
        ll, p = loglik_winner(pick(X), o[0], b, mu, sd)
        top = max(range(len(p)), key=p.__getitem__)
        out.append({'season': s, 'll': ll, 'pw': p[o[0]], 'hit': int(top == o[0]), 'fav_p': p[top]})
    return out


def paired(a, b):
    """mean and t of the per-season log-likelihood gain of model a over model b (same seasons)"""
    d = [x['ll'] - y['ll'] for x, y in zip(a, b)]
    n = len(d)
    if n < 2: return {'n': n, 'gain': d[0] if d else 0, 't': 0, 'wins': sum(v > 0 for v in d)}
    m = sum(d) / n
    v = sum((x - m) ** 2 for x in d) / (n - 1)
    return {'n': n, 'gain': round(m, 4), 't': round(m / math.sqrt(v / n), 2) if v > 0 else 0.0,
            'wins': sum(x > 0 for x in d)}
