"""Shared fitting and held-out testing for xAAV (scripts/xaav.py): the AAV a player would sign for as a free agent
now, as a share of the salary cap, from position, age and the site's metrics.

Rows: dicts with 'y' (signing league year: the held-out unit), 'grp', 'age', 't' (AAV / cap that year) and the
metric inputs. A form is a function row -> feature list. fit() is least squares (light ridge) on log(t), predicted
back as exp(xb) x the training rows' mean exp(residual) (smearing), then clipped to the league's floor and ceiling.
loyo() leaves one signing year out at a time; compare() gives MAE (cap share), paired t on |error| and seasons won.
numpy only."""
import math

try:
    import numpy as np
except ImportError:   # the live build only needs onehot / hinge / agebin
    np = None


def design(rows, form):
    return np.array([form(r) for r in rows], dtype=float)


def fit(rows, form, ridge=1e-3, log=True):
    """log: True (log share), False (the share itself) or 'sqrt' (square root of the share, between the two)"""
    X = design(rows, form)
    tf = {True: math.log, False: float, 'sqrt': math.sqrt}[log]
    y = np.array([tf(r['t']) for r in rows])
    P = ridge * np.eye(X.shape[1]); P[0, 0] = 0.0
    b = np.linalg.solve(X.T @ X + P, X.T @ y)
    e = y - X @ b
    smear = float(np.mean(np.exp(e))) if log is True else float(np.mean(e ** 2)) if log == 'sqrt' else 0.0
    return {'b': b.tolist(), 'smear': smear, 'log': log}


def back(z, log, smear):
    """a fitted value back to a cap share (smearing: E[exp(z + e)], E[(z + e)^2])"""
    if log is True:
        return math.exp(z) * smear
    if log == 'sqrt':
        return max(z, 0.0) ** 2 + smear
    return z


def predict(m, rows, form, lo=None, hi=None):
    X = design(rows, form)
    z = X @ np.array(m['b'])
    p = [back(v, m['log'], m['smear']) for v in z]
    out = []
    for r, v in zip(rows, p):
        a = lo(r) if callable(lo) else lo
        c = hi(r) if callable(hi) else hi
        if a is not None: v = max(v, a)
        if c is not None: v = min(v, c)
        out.append(float(v))
    return out


def loyo(rows, form, lo=None, hi=None, **kw):
    """held-out prediction for every row, its signing year left out of the fit"""
    pred = [None] * len(rows)
    for y in sorted({r['y'] for r in rows}):
        tr = [r for r in rows if r['y'] != y]
        te = [i for i, r in enumerate(rows) if r['y'] == y]
        m = fit(tr, form, **kw)
        for i, v in zip(te, predict(m, [rows[i] for i in te], form, lo, hi)):
            pred[i] = v
    return pred


def forward(rows, form, first, lo=None, hi=None, **kw):
    """time split: each year from `first` on predicted from a fit on the years before it only"""
    pred = {}
    for y in sorted({r['y'] for r in rows if r['y'] >= first}):
        tr = [r for r in rows if r['y'] < y]
        te = [i for i, r in enumerate(rows) if r['y'] == y]
        m = fit(tr, form, **kw)
        for i, v in zip(te, predict(m, [rows[i] for i in te], form, lo, hi)):
            pred[i] = v
    return pred


def compare(rows, pa, pb, idx=None):
    """model a against baseline b: MAE of each (cap share, x 100 = points of cap), paired t on |err a| - |err b|,
    held-out years where a has the lower MAE, R2 of each, calibration slope of a (t on a)"""
    idx = list(range(len(rows))) if idx is None else list(idx)
    t = np.array([rows[i]['t'] for i in idx]); a = np.array([pa[i] for i in idx]); b = np.array([pb[i] for i in idx])
    ea, eb = np.abs(a - t), np.abs(b - t)
    d = ea - eb
    sd = float(d.std(ddof=1))
    tt = float(d.mean() / (sd / math.sqrt(len(d)))) if sd > 0 else None
    ys = sorted({rows[i]['y'] for i in idx})
    won = 0
    for y in ys:
        k = [j for j, i in enumerate(idx) if rows[i]['y'] == y]
        won += ea[k].mean() < eb[k].mean()
    v = float(np.var(t))
    slope = float(np.cov(a, t)[0, 1] / np.var(a, ddof=1))
    top = a >= 0.07
    cal = round(float(t[top].mean() / a[top].mean()), 3) if top.sum() >= 5 else None
    return {'n': len(idx), 'maeA': round(float(ea.mean()) * 100, 3), 'maeB': round(float(eb.mean()) * 100, 3), 'topCal': cal,
            'nTop': int(top.sum()),
            't': round(tt, 2) if tt is not None else None, 'won': f'{won}/{len(ys)}', 'r2A': round(1 - float(np.mean((a - t) ** 2)) / v, 3),
            'r2B': round(1 - float(np.mean((b - t) ** 2)) / v, 3), 'slopeA': round(slope, 3)}


def onehot(v, levels):
    return [1.0 if v == x else 0.0 for x in levels]


def agebin(a, cuts=(24, 27, 30, 33)):
    """age bins: under 24, 24-26, 27-29, 30-32, 33+ (index)"""
    return sum(a >= c for c in cuts)


def hinge(a, k):
    return max(0.0, a - k), max(0.0, k - a)
