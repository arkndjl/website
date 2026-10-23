#!/usr/bin/env python3
"""One scoring and selection harness for every model on the site (numpy only; scripts/harness.mjs is the Node port of
the scoring, paired-test and multiple-testing parts, for the CFB models; keep the two in step).

    python3 scripts/harness.py --test       # self-test; also run `node scripts/harness.mjs --test`
    python3 scripts/harness.py --ledger     # every tested term in data/model_ledger.json, by model, with its verdict
    python3 scripts/harness.py --stale      # terms past their re-validation date

Scoring rules (per row, lower is better, all proper or the loss the model is fit on): ae, se, logloss, brier,
crps_normal (a normal forecast), rps (ordinal tiers, e.g. FV buckets), pinball (a quantile).

Paired test: candidate loss minus base loss on the same rows. The standard error is cluster-robust (CR1; one or more
cluster keys, multiway by Cameron-Gelbach-Miller), because games on the same day, or players in the same class,
share shocks and an i.i.d. t overstates the evidence. `deff` is the variance inflation against the i.i.d. t.
p is one-sided (does the candidate lower the loss), from Student t on G - 1 degrees of freedom (G = fewest clusters).

Splits: tune/held masks by season, walk-forward fits (each season from the seasons before it), and group folds
(whole players or whole schools out).

Selection and re-scoring (the project rule): a term enters on the tuning seasons; the held-out seasons are reported
and only veto. Re-scoring takes each kept term out of the full model and measures both splits. Evidence is the
Stouffer z of the tuning and held-out t (equal weight), and the Benjamini-Hochberg q runs over every term in the
ledger at once (one family, all models), so a q of .10 means about one in ten terms at that level is noise.
    keep   q <= .10
    drop   q > .10 and the held-out loss without it is no worse (removing it costs nothing out of sample)
    watch  q > .10 but held out is worse without it (not proven, not free to remove)
Core terms (a model's backbone, e.g. efficiency ratings) are scored but never dropped by the rule.
"""
import json
import math
import os
import sys
import datetime as dt

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(ROOT, 'data', 'model_ledger.json')
Q_KEEP = 0.10
REVALIDATE_DAYS = 365


# ---------------------------------------------------------------- scoring rules (per row; lower is better)
def ae(pred, y):
    return np.abs(np.asarray(pred, float) - np.asarray(y, float))


def se(pred, y):
    return (np.asarray(pred, float) - np.asarray(y, float)) ** 2


def logloss(p, y, eps=1e-6):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier(p, y):
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def _phi(z):
    return np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _Phi(z):
    z = np.asarray(z, float)
    return 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))


def crps_normal(mu, sd, y):
    """CRPS of a normal forecast N(mu, sd^2) at y (closed form; in the units of y)"""
    mu, sd, y = (np.asarray(v, float) for v in (mu, sd, y))
    z = (y - mu) / sd
    return sd * (z * (2 * _Phi(z) - 1) + 2 * _phi(z) - 1 / math.sqrt(math.pi))


def rps(probs, k):
    """ranked probability score: probs is rows x K (ordered categories), k the realized category index"""
    P = np.cumsum(np.asarray(probs, float), axis=1)
    O = (np.arange(P.shape[1])[None, :] >= np.asarray(k)[:, None]).astype(float)
    return ((P - O) ** 2)[:, :-1].sum(axis=1) / max(P.shape[1] - 1, 1)


def pinball(q, tau, y):
    d = np.asarray(y, float) - np.asarray(q, float)
    return np.maximum(tau * d, (tau - 1) * d)


RULES = {'ae': ae, 'se': se, 'logloss': logloss, 'brier': brier}


# ---------------------------------------------------------------- distributions (no scipy)
def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-300 else 1e-300)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-300 else 1e-300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-300 else 1e-300
        de = d * c
        h *= de
        if abs(de - 1) < 1e-12:
            break
    return h


def _ibeta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lb) * _betacf(a, b, x) / a
    return 1 - math.exp(lb) * _betacf(b, a, 1 - x) / b


def t_cdf(t, df):
    """Student t CDF (normal past 1000 df)"""
    if not math.isfinite(t):
        return 0.0 if t < 0 else 1.0
    if df > 1000:
        return 0.5 * (1 + math.erf(t / math.sqrt(2)))
    x = df / (df + t * t)
    tail = 0.5 * _ibeta(df / 2, 0.5, x)
    return tail if t < 0 else 1 - tail


def z_of_p(p):
    """normal quantile of a one-sided p (Acklam's rational approximation, |error| < 1e-9 after one Newton step)"""
    p = min(max(p, 1e-15), 1 - 1e-15)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p > 1 - 0.02425:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    else:
        q = p - 0.5; r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    e = 0.5 * (1 + math.erf(x / math.sqrt(2))) - p
    return x - e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)


# ---------------------------------------------------------------- paired test
def _cr_var(d, g):
    """CR1 variance of the mean of d with clusters g"""
    n = len(d)
    _, inv = np.unique(g, return_inverse=True)
    G = int(inv.max()) + 1
    s = np.bincount(inv, weights=d - d.mean(), minlength=G)
    return float((s @ s) / n ** 2 * G / max(G - 1, 1)), G


def paired(new, base, cluster=None):
    """new minus base loss, row by row. d < 0: the candidate is better. cluster: an array of keys, or a list of
    them (multiway). Returns d, se, t, one-sided p (candidate better), n, clusters G, deff."""
    new, base = np.asarray(new, float), np.asarray(base, float)
    ok = ~(np.isnan(new) | np.isnan(base))
    d = (new - base)[ok]
    n = len(d)
    if n < 3:
        return {'d': 0.0, 'se': None, 't': 0.0, 'p': 0.5, 'n': n, 'G': n, 'deff': 1.0}
    v_iid = float(d.var(ddof=1) / n)
    if cluster is None:
        v, G = v_iid, n
    else:
        ks = cluster if isinstance(cluster, (list, tuple)) else [cluster]
        ks = [np.asarray(k)[ok] for k in ks]
        if len(ks) == 1:
            v, G = _cr_var(d, ks[0])
        else:
            # multiway (Cameron-Gelbach-Miller): add one-way variances, subtract the intersections, by inclusion-exclusion
            from itertools import combinations
            v, G = 0.0, n
            for r in range(1, len(ks) + 1):
                for sub in combinations(range(len(ks)), r):
                    key = np.array(['|'.join(str(ks[j][i]) for j in sub) for i in range(n)]) if r > 1 else ks[sub[0]]
                    vi, gi = _cr_var(d, key)
                    v += (-1) ** (r + 1) * vi
                    if r == 1:
                        G = min(G, gi)
            # never below the largest one-way variance (CGM can undershoot with few clusters)
            v = max(v, max(_cr_var(d, k)[0] for k in ks))
    sev = math.sqrt(v) if v > 0 else float('nan')
    t = float(d.mean() / sev) if sev and sev == sev and sev > 0 else 0.0
    return {'d': float(d.mean()), 'se': sev, 't': t, 'p': t_cdf(t, G - 1) if G > 1 else 0.5, 'n': n, 'G': int(G),
            'deff': round(v / v_iid, 2) if v_iid > 0 else 1.0}


# ---------------------------------------------------------------- multiple testing
def bh(p):
    """Benjamini-Hochberg q values (the FDR at which each test would just pass)"""
    p = np.asarray(p, float)
    m = len(p)
    if not m:
        return p
    o = np.argsort(p)
    q = np.empty(m)
    run = 1.0
    for i in range(m - 1, -1, -1):
        run = min(run, p[o[i]] * m / (i + 1))
        q[o[i]] = run
    return q


def holm(p):
    """Holm step-down adjusted p (family-wise error)"""
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    a = np.empty(m)
    run = 0.0
    for i, j in enumerate(o):
        run = max(run, min(1.0, (m - i) * p[j]))
        a[j] = run
    return a


def stouffer(zs, w=None):
    zs = np.asarray(zs, float)
    w = np.ones_like(zs) if w is None else np.asarray(w, float)
    return float((w * zs).sum() / math.sqrt((w * w).sum()))


def p_of_z(z):
    return 0.5 * (1 + math.erf(-z / math.sqrt(2)))


# ---------------------------------------------------------------- splits and fits
def season_masks(S, tune, held_from, valid=None):
    S = np.asarray(S)
    ok = np.ones(len(S), bool) if valid is None else np.asarray(valid, bool)
    return ok & (S >= tune[0]) & (S <= tune[1]), ok & (S >= held_from)


def fit_ols(Xm, y, close=None, lam=0.0, ridge=0.0, calib=(), screen=None):
    """the shared game-model fit (every sport's margin and total weights come through here or walk_ols).

    lam = 0 (default): least squares on the results y, unchanged from before.
    lam > 0: the multi-task loss sum (y - Xb)^2 + lam x sum (close - Xb)^2 over rows with a close (results only where
    there is none): the same as least squares on (y + lam close) / (1 + lam) with weight 1 + lam on lined rows. The
    close is a low-noise label for the expected margin (its error around the result is the game's own noise), so the
    weights' standard errors shrink, but it carries the market's view of each input, so the composite is then put back
    on the results' scale: y ~ s x (X b) + X[:, calib] g on every training row (1 + len(calib) parameters).
    lam = inf: the close alone, then that calibration.
    screen: drop lined rows whose close sits more than screen robust sd from the close fit (swapped home/away lines)
    and refit. Returns the weight vector on Xm's columns (the calibration folded in)."""
    Xm, y = np.asarray(Xm, float), np.asarray(y, float)
    k = Xm.shape[1]

    def ls(A, b, w=None):
        if w is not None:
            r = np.sqrt(w)
            A, b = A * r[:, None], b * r
        if ridge:
            return np.linalg.solve(A.T @ A + ridge * np.eye(A.shape[1]), A.T @ b)
        return np.linalg.lstsq(A, b, rcond=None)[0]                 # min-norm when a term is all zero in early seasons
    if not lam or close is None:
        return ls(Xm, y)
    c = np.asarray(close, float)
    lined = ~np.isnan(c)
    if screen:
        bc = ls(Xm[lined], c[lined])
        e = c[lined] - Xm[lined] @ bc
        rsd = 1.4826 * np.median(np.abs(e - np.median(e)))
        bad = np.zeros(len(c), bool)
        bad[np.flatnonzero(lined)[np.abs(e) > screen * rsd]] = True
        lined = lined & ~bad
    if np.isinf(lam):
        b = ls(Xm[lined], c[lined])
    else:
        t = np.where(lined, (y + lam * np.nan_to_num(c)) / (1 + lam), y)
        b = ls(Xm, t, np.where(lined, 1 + lam, 1.0))
    # back on the results' scale: s x composite (+ the calib columns refit on the results)
    Z = np.column_stack([Xm @ b] + [Xm[:, j] for j in calib])
    g = np.linalg.lstsq(Z, y, rcond=None)[0]
    w = g[0] * b
    for j, gj in zip(calib, g[1:]):
        w[j] += gj
    return w


def walk_ols(Xm, y, S, first, train=None, ridge=0.0, close=None, lam=0.0, calib=(), screen=None):
    """each season >= first predicted by least squares on the seasons before it (train: rows allowed in training);
    close, lam, calib, screen: the closing-line training target (fit_ols)"""
    Xm, y, S = np.asarray(Xm, float), np.asarray(y, float), np.asarray(S)
    tr_ok = np.ones(len(y), bool) if train is None else np.asarray(train, bool)
    c = None if close is None else np.asarray(close, float)
    pred = np.full(len(y), np.nan)
    for s in range(int(first), int(S.max()) + 1):
        tr, te = (S < s) & tr_ok, S == s
        if not te.any() or tr.sum() <= Xm.shape[1]:
            continue
        b = fit_ols(Xm[tr], y[tr], None if c is None else c[tr], lam, ridge, calib, screen)
        pred[te] = Xm[te] @ b
    return pred


def group_folds(ids, k=5, seed=0):
    """fold index per row with whole groups (players, schools) kept together"""
    import hashlib
    return np.array([int(hashlib.md5(f'{seed}|{i}'.encode()).hexdigest(), 16) % k for i in ids])


# ---------------------------------------------------------------- re-scoring kept terms
def drop_one(predict, terms, y, tune, held, loss=ae, cluster=None, core=(), base=None):
    """predict(list_of_terms) -> walk-forward predictions. Each kept term is removed from the full model and both
    splits are scored: d > 0 means the model is worse without the term (the term helps)."""
    full = base if base is not None else predict(list(terms))
    lf = loss(full, y)
    out = []
    for f in terms:
        lw = loss(predict([z for z in terms if z != f]), y)
        a, b = paired(lf[tune], lw[tune], None if cluster is None else _sub(cluster, tune)), \
            paired(lf[held], lw[held], None if cluster is None else _sub(cluster, held))
        out.append(record(f, a, b, core=f in core,
                          tune_loss=(float(np.nanmean(lf[tune])), float(np.nanmean(lw[tune]))),
                          held_loss=(float(np.nanmean(lf[held])), float(np.nanmean(lw[held])))))
    return out


def _sub(cluster, m):
    return [np.asarray(c)[m] for c in cluster] if isinstance(cluster, (list, tuple)) else np.asarray(cluster)[m]


def record(term, tune, held, core=False, tune_loss=None, held_loss=None, **extra):
    """one ledger row from two paired tests of (with the term) minus (without it): t < 0 means the term helps"""
    r = {'term': term, 'core': bool(core),
         'tune': {'d': round(-tune['d'], 5), 't': round(tune['t'], 2), 'p': round(tune['p'], 4), 'n': tune['n'], 'G': tune['G'], 'deff': tune['deff']},
         'held': {'d': round(-held['d'], 5), 't': round(held['t'], 2), 'p': round(held['p'], 4), 'n': held['n'], 'G': held['G'], 'deff': held['deff']}}
    if tune_loss:
        r['tune']['with'], r['tune']['without'] = round(tune_loss[0], 5), round(tune_loss[1], 5)
    if held_loss:
        r['held']['with'], r['held']['without'] = round(held_loss[0], 5), round(held_loss[1], 5)
    r.update(extra)
    return r


def from_t(term, t_tune, t_held, n_tune=None, n_held=None, core=False, d_held=None, **extra):
    """a ledger row from stored t statistics (t < 0: the term helps), for models whose data this harness can't rebuild"""
    mk = lambda t, n: None if t is None else {'d': None, 't': round(t, 2), 'p': round(t_cdf(t, (n or 10 ** 6) - 1), 4), 'n': n, 'G': n, 'deff': None}
    r = {'term': term, 'core': bool(core), 'tune': mk(t_tune, n_tune), 'held': mk(t_held, n_held), 'stored': True}
    if d_held is not None and r['held']:
        r['held']['d'] = d_held
    r.update(extra)
    return r


def judge(rows, q_keep=Q_KEEP):
    """fills z, p, q and the verdict on every row (one BH family)"""
    for r in rows:
        r['z'] = round(stouffer([-s['t'] for s in (r['tune'], r['held']) if s]), 2)
        r['p'] = p_of_z(r['z'])
    qs = bh([r['p'] for r in rows])
    for r, q in zip(rows, qs):
        r['q'] = round(float(q), 4)
        r['p'] = round(r['p'], 4)
        # held-out worse without the term: d > 0 (measured) or t < 0 (stored)
        # no held-out split (stored CV evidence only): never free to remove
        hd = r['held'].get('d') if r['held'] else None
        worse_without = True if not r['held'] else (hd > 0) if hd is not None else (r['held']['t'] < 0)
        if r['q'] <= q_keep:
            r['verdict'] = 'keep'
        elif r.get('core'):
            r['verdict'] = 'core'
        elif worse_without:
            r['verdict'] = 'watch'
        else:
            r['verdict'] = 'drop'
    return rows


def write_ledger(models, path=LEDGER, today=None, pending=None):
    """models: {name: {'desc', 'loss', 'split', 'rows': [record...], 'source'}}; judges all rows as one family"""
    today = today or dt.date.today().isoformat()
    allrows = [r for m in models.values() for r in m['rows']]
    judge(allrows)
    due = (dt.date.fromisoformat(today) + dt.timedelta(days=REVALIDATE_DAYS)).isoformat()
    for m in models.values():
        m.setdefault('tested', today)
        m.setdefault('revalidate', due)
    out = {'asof': today, 'rule': __doc__.split('Selection and re-scoring')[1].split('Core terms')[0].strip().replace('\n', ' '),
           'qKeep': Q_KEEP, 'family': len(allrows),
           'counts': {v: sum(r['verdict'] == v for r in allrows) for v in ('keep', 'watch', 'drop', 'core')}, 'models': models,
           'pending': pending or {}}
    with open(path, 'w') as f:
        json.dump(out, f, indent=1)
    return out


def show(path=LEDGER, stale=False):
    L = json.load(open(path))
    today = dt.date.today().isoformat()
    print(f"ledger {L['asof']}: {L['family']} terms, BH family-wide, keep at q <= {L['qKeep']}: {L['counts']}")
    for name, m in L['models'].items():
        if stale and m['revalidate'] > today:
            continue
        print(f"\n{name}  ({m.get('loss')}, {m.get('split')}; tested {m['tested']}, re-validate by {m['revalidate']})")
        for r in sorted(m['rows'], key=lambda r: r['q']):
            ht = f"{r['held']['t']:6.2f}" if r['held'] else '     -'
            print(f"  {('removed' if r.get('removed') else r['verdict']):7s} {r['term']:14s} tune t {r['tune']['t']:6.2f}  held t {ht}  z {r['z']:5.2f}  q {r['q']:.3f}"
                  + ('  (stored)' if r.get('stored') else ''))


# ---------------------------------------------------------------- self-test
FIXTURE = os.path.join(HERE, 'data', 'harness_fixture.json')


def _fixture_results():
    F = json.load(open(FIXTURE))
    a, b, c1, c2 = (np.array(F[k]) for k in ('a', 'b', 'c1', 'c2'))
    return {'t_cdf': [round(t_cdf(t, df), 8) for t, df in F['tdf']],
            'z_of_p': [round(z_of_p(p), 8) for p in F['ps']],
            'bh': [round(float(x), 8) for x in bh(F['ps'])], 'holm': [round(float(x), 8) for x in holm(F['ps'])],
            'iid': {k: (round(v, 8) if isinstance(v, float) else v) for k, v in paired(a, b).items()},
            'cr1': {k: (round(v, 8) if isinstance(v, float) else v) for k, v in paired(a, b, c1).items()},
            'cr2': {k: (round(v, 8) if isinstance(v, float) else v) for k, v in paired(a, b, [c1, c2]).items()},
            'crps': [round(float(x), 8) for x in crps_normal([0, 1, -2], [1, 2, 3], [0.5, -1, 4])],
            'rps': [round(float(x), 8) for x in rps([[.2, .5, .3], [.6, .3, .1]], [2, 0])],
            'logloss': [round(float(x), 8) for x in logloss([.2, .9], [0, 1])],
            'stouffer': round(stouffer([1.0, 2.0]), 8)}


def selftest():
    import random
    if not os.path.exists(FIXTURE):
        rnd = random.Random(7)
        n = 400
        a = [rnd.gauss(0, 1) for _ in range(n)]
        F = {'a': [round(x + rnd.gauss(-0.1, 0.5), 4) for x in a], 'b': [round(x, 4) for x in a],
             'c1': [i // 20 for i in range(n)], 'c2': [i % 7 for i in range(n)],
             'tdf': [[-2.0, 5], [1.3, 30], [-0.4, 2], [3.1, 2000], [0.0, 9]], 'ps': [0.001, 0.04, 0.03, 0.2, 0.5, 0.011]}
        json.dump(F, open(FIXTURE, 'w'))
    R = _fixture_results()
    # known values
    assert abs(R['t_cdf'][0] - 0.05096974) < 1e-6, R['t_cdf']
    assert abs(R['z_of_p'][1] - (-1.75068607)) < 1e-6, R['z_of_p']
    assert abs(R['crps'][0] - 0.33140353) < 1e-6, R['crps']
    assert R['bh'] == [0.006, 0.06, 0.06, 0.24, 0.5, 0.033], R['bh']
    assert R['cr1']['deff'] > 0 and R['cr2']['G'] == 7, R['cr2']
    # closed-form CRPS against the integral of (F - 1{x >= y})^2
    xs = np.linspace(-12, 12, 48001)
    F_ = _Phi((xs - 1) / 2)
    num = float(np.sum((F_ - (xs >= -1)) ** 2) * (xs[1] - xs[0]))
    assert abs(num - R['crps'][1]) < 1e-3, (num, R['crps'][1])
    # walk-forward OLS recovers a known slope; drop_one flags the noise term and keeps the real one
    rng = np.random.default_rng(3)
    n = 4000
    S = np.repeat(np.arange(2010, 2020), n // 10)
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    y = 2 * x1 + rng.normal(size=n)
    X = {'one': np.ones(n), 'x1': x1, 'noise': x2}
    pred = lambda fs: walk_ols(np.column_stack([X[f] for f in fs]), y, S, 2012)
    tu, he = season_masks(S, (2012, 2015), 2016, ~np.isnan(pred(['one'])))
    rows = judge(drop_one(pred, ['one', 'x1', 'noise'], y, tu, he, cluster=S, core=('one',)))
    v = {r['term']: r['verdict'] for r in rows}
    assert v['x1'] == 'keep' and v['noise'] in ('drop', 'watch'), rows
    F = json.load(open(FIXTURE))
    if 'expect' not in F:
        F['expect'] = R
        json.dump(F, open(FIXTURE, 'w'))
    assert _close(R, F['expect']), 'results moved from scripts/data/harness_fixture.json expect'
    print('harness.py: all tests pass (node scripts/harness.mjs --test checks the same expect values)')


def _close(a, b, tol=1e-6):
    if isinstance(a, dict):
        return set(a) == set(b) and all(_close(a[k], b[k], tol) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= tol * max(1, abs(b))
    return a == b


if __name__ == '__main__':
    if '--test' in sys.argv:
        selftest()
    elif '--ledger' in sys.argv or '--stale' in sys.argv:
        show(stale='--stale' in sys.argv)
    else:
        print(__doc__)
