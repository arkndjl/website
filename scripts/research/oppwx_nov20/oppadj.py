# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Opponent adjustment of a per-game player (or unit) rate, and the tests that decide whether it ships (Nov 20 2026).

The method of the NFL QB season metric (project files qb-season-metric/qbs_test.py), made generic:

    row      = (season, game, order, unit, opp, exposure, value)     value = the summed metric in that game
    D[opp]   = what that opponent allowed per unit of exposure in its OTHER games that season, minus the league's rate,
               shrunk toward 0 by n / (n + K) (n = the exposure it faced in those games)
    adjusted = value - c x exposure x D[opp]

Tests (a unit-season needs MIN exposure, each half MINH):
    split    odd vs even games (alternated in date order): r of the two half rates, raw vs adjusted, paired bootstrap
             over unit-seasons of the difference in r -> P(better)
    ahead    the first FRAC of the unit's games against the RAW rate of the rest: weighted squared error, raw vs
             adjusted, paired t over unit-seasons
An adjustment ships when P(better) >= .90 on the split on the held seasons AND the look-ahead error is not worse.
"""
from collections import defaultdict
import numpy as np


def home_adjust(rows, by=None, vals=None):
    """values with the league's home / away gap taken out (per season and class): row[7] = True at home"""
    v = np.array([r[6] for r in rows]) if vals is None else np.asarray(vals, float)
    t = defaultdict(lambda: [0.0, 0.0])
    for r, x in zip(rows, v):
        c = by(r) if by else 0
        t[(r[0], c, bool(r[7]))][0] += x; t[(r[0], c, bool(r[7]))][1] += r[5]
        t[(r[0], c, None)][0] += x; t[(r[0], c, None)][1] += r[5]
    out = v.copy()
    for i, r in enumerate(rows):
        c = by(r) if by else 0
        a = t[(r[0], c, bool(r[7]))]; m = t[(r[0], c, None)]
        if a[1] > 0 and m[1] > 0:
            out[i] -= r[5] * (a[0] / a[1] - m[0] / m[1])
    return out


def defence(rows, K, by=None, vals=None):
    """rows -> {(season, opp, game): shrunk allowed rate over league, that game left out}; `by` groups rows into classes
    (position groups) that each get their own allowed rate (None = one class)"""
    lg = defaultdict(lambda: [0.0, 0.0]); tot = defaultdict(lambda: [0.0, 0.0]); gm = defaultdict(lambda: [0.0, 0.0])
    for i, r in enumerate(rows):
        c = by(r) if by else 0
        s, g, o, e, v = r[0], r[1], r[4], r[5], (r[6] if vals is None else vals[i])
        lg[(s, c)][0] += v; lg[(s, c)][1] += e
        tot[(s, c, o)][0] += v; tot[(s, c, o)][1] += e
        gm[(s, c, o, g)][0] += v; gm[(s, c, o, g)][1] += e
    D = {}
    for (s, c, o, g), (v, e) in gm.items():
        V, E = tot[(s, c, o)]
        m = lg[(s, c)][0] / lg[(s, c)][1]
        n = E - e
        D[(s, c, o, g)] = ((V - v) - m * n) / (n + K) if n + K > 0 else 0.0
    return D


def adjust(rows, K, c=1.0, by=None, home=False):
    base = home_adjust(rows, by) if home else np.array([r[6] for r in rows])
    D = defence(rows, K, by, base)
    out = []
    for r, x in zip(rows, base):
        cl = by(r) if by else 0
        out.append(x - c * r[5] * D.get((r[0], cl, r[4], r[1]), 0.0))
    return np.array(out)


def _halves(rows, vals, MIN, MINH, seasons=None):
    by = defaultdict(list)
    for i, r in enumerate(rows):
        if seasons is None or r[0] in seasons:
            by[(r[0], r[3])].append(i)
    keys, A, B = [], [], []
    for k in sorted(by):
        ix = by[k]
        if sum(rows[i][5] for i in ix) < MIN:
            continue
        gs = sorted({(rows[i][2], rows[i][1]) for i in ix})
        half = {g[1]: j % 2 for j, g in enumerate(gs)}
        a = [i for i in ix if half[rows[i][1]] == 0]; b = [i for i in ix if half[rows[i][1]] == 1]
        ea = sum(rows[i][5] for i in a); eb = sum(rows[i][5] for i in b)
        if ea < MINH or eb < MINH:
            continue
        keys.append(k); A.append((a, ea)); B.append((b, eb))
    return keys, A, B


def split(rows, variants, MIN, MINH, seasons=None, boots=2000, seed=1):
    """variants: {name: adjusted values array}; 'raw' must be one. -> {name: {r, dr, P}}"""
    keys, A, B = _halves(rows, variants['raw'], MIN, MINH, seasons)
    H = {}
    for nm, v in variants.items():
        H[nm] = (np.array([v[a].sum() / ea for a, ea in A]), np.array([v[b].sum() / eb for b, eb in B]))
    rng = np.random.default_rng(seed); n = len(keys)
    idx = rng.integers(0, n, (boots, n))
    out = {'n': n}
    def rs(a, b):
        return np.array([np.corrcoef(a[i], b[i])[0, 1] for i in idx])
    r0 = rs(*H['raw'])
    for nm, (a, b) in H.items():
        r = float(np.corrcoef(a, b)[0, 1])
        o = {'r': round(r, 4), 'sb': round(2 * r / (1 + r), 4)}
        if nm != 'raw':
            d = rs(a, b) - r0
            o['dr'] = round(float(d.mean()), 4); o['P'] = round(float((d > 0).mean()), 3)
        out[nm] = o
    return out


def ahead(rows, variants, MIN, MINH, frac=0.5, seasons=None, prior=None):
    """first `frac` of each unit-season's games -> the raw rate of the rest. Each variant's early rate is shrunk toward
    the pool mean by its own best k (picked on the same rows, one free number each, so the comparison is fair).
    -> {name: {mse, k, t vs raw}}"""
    by = defaultdict(list)
    for i, r in enumerate(rows):
        if seasons is None or r[0] in seasons:
            by[(r[0], r[3])].append(i)
    E1, E2, Y, X = [], [], [], {nm: [] for nm in variants}
    for k in sorted(by):
        ix = sorted(by[k], key=lambda i: (rows[i][2], rows[i][1]))
        if sum(rows[i][5] for i in ix) < MIN:
            continue
        gs = []
        for i in ix:
            if not gs or gs[-1] != rows[i][1]:
                gs.append(rows[i][1])
        cut = set(gs[:max(1, int(len(gs) * frac))])
        a = np.array([i for i in ix if rows[i][1] in cut]); b = np.array([i for i in ix if rows[i][1] not in cut])
        if not len(a) or not len(b):
            continue
        ea = sum(rows[i][5] for i in a); eb = sum(rows[i][5] for i in b)
        if ea < MINH or eb < MINH:
            continue
        E1.append(ea); E2.append(eb); Y.append(variants['raw'][b].sum() / eb)
        for nm, v in variants.items():
            X[nm].append(v[a].sum() / ea)
    E1, E2, Y = np.array(E1), np.array(E2), np.array(Y)
    out = {'n': len(Y)}
    errs = {}
    for nm in variants:
        x = np.array(X[nm]); mu = np.average(x, weights=E1)
        best = None
        for kk in (0, .25, .5, 1, 2, 4, 8):
            ksh = kk * np.median(E1)
            p = mu + (x - mu) * E1 / (E1 + ksh)
            e = (p - Y) ** 2 * E2
            m = e.sum() / E2.sum()
            if best is None or m < best[0]:
                best = (m, kk, e)
        errs[nm] = best[2]
        out[nm] = {'mse': round(float(best[0]), 5), 'k': best[1]}
    for nm in variants:
        if nm != 'raw':
            d = errs[nm] - errs['raw']
            out[nm]['t'] = round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2)
    return out
