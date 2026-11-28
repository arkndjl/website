#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB team builder win chance scale (units sweep, Nov 28 2026).

The builder's ratings (now, roster, w/ targets, seasons 2-3) are on the ARK rating's scale, points a game over an
average D-I team. Its win chance was ncdf(.68 x gap / 11.4), as if the gap were points per 100 possessions. Question: on
a next-season rating on that scale, which factor k in ncdf(k x gap / 11.4) prices next season's conference games best?

Point in time: each season y-1's final rating is a ridge least squares margin rating from that season's D-I games
(home court fit with it), on the per-game scale like the ARK rating; it stands for a next-season rating, as the builder's
are. Season y's conference games are scored (home court from the training seasons). Walk-forward: k is fit on test
seasons before y (log loss), y = 2018..2026. Forms: k = .68 (live), k = 1 (the units), k fit.
Pre-registered: a form ships over .68 if its log loss is lower, paired t <= -2 by game and it wins most seasons.
Also reported: next-season conference win% of each team against the same forms' xW (RMSE).
"""
import gzip
import json
import math
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OUT = os.path.join(ROOT, 'research', 'cbb_builder_xw.json')
SD = 11.4


def ncdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def vcdf(z):
    """normal cdf on arrays (Abramowitz and Stegun 7.1.26 erf, error under 1.5e-7)"""
    x = np.abs(z) / math.sqrt(2); t = 1 / (1 + 0.3275911 * x)
    e = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return 0.5 * (1 + np.sign(z) * e)


def ratings(G):
    """ridge LS: margin = r_home - r_away + h x (not neutral); teams with 10+ games"""
    n = defaultdict(int)
    for g in G: n[g['home']] += 1; n[g['away']] += 1
    T = sorted(t for t, c in n.items() if c >= 10); ix = {t: i for i, t in enumerate(T)}
    rows, y = [], []
    for g in G:
        if g['home'] in ix and g['away'] in ix:
            rows.append((ix[g['home']], ix[g['away']], 0.0 if g['neutral'] else 1.0)); y.append(g['hs'] - g['as'])
    m = len(T) + 1
    A = np.zeros((m, m)); b = np.zeros(m)
    for (h, a, c), v in zip(rows, y):
        x = {h: 1.0, a: -1.0}; x[m - 1] = c
        for i, xi in x.items():
            b[i] += xi * v
            for j, xj in x.items(): A[i, j] += xi * xj
    A[np.arange(m - 1), np.arange(m - 1)] += 1.0
    s = np.linalg.solve(A, b)
    r = s[:-1] - s[:-1].mean()
    return {t: float(r[ix[t]]) for t in T}, float(s[-1])


def main():
    H = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_games_hist.json.gz')))
    by = defaultdict(list)
    for g in H:
        if g.get('hs') is None or g.get('as') is None or g['hs'] == g['as']: continue
        by[g['season']].append(g)
    ys = sorted(by)
    R = {y: ratings(by[y]) for y in ys}
    data = {}
    for y in ys[1:]:
        r, _ = R[y - 1]
        data[y] = [(r[g['home']] - r[g['away']], 0.0 if g['neutral'] else 1.0, 1.0 if g['hs'] > g['as'] else 0.0, g['home'], g['away'])
                   for g in by[y] if g.get('conf') and g['home'] in r and g['away'] in r]

    arr = {}
    def ll(k, hca, D):
        a = arr.get(id(D))
        if a is None: a = arr[id(D)] = np.array([q[:3] for q in D], float)
        p = np.clip(vcdf(k * (a[:, 0] + hca * a[:, 1]) / SD), 1e-6, 1 - 1e-6)
        return -(a[:, 2] * np.log(p) + (1 - a[:, 2]) * np.log(1 - p))

    def fit(D):
        best = None
        for hca in np.arange(1.0, 9.01, 0.25):
            for k in np.arange(0.3, 1.31, 0.02):
                v = ll(k, hca, D).mean()
                if best is None or v < best[0]: best = (v, k, hca)
        return best[1], best[2]

    res = defaultdict(list); per = defaultdict(dict); ks = {}; wp = defaultdict(list)
    for y in [y for y in ys if y in data and y >= ys[0] + 3]:
        tr = [q for yy in data if yy < y for q in data[yy]]
        if len(tr) < 3000: continue
        k, hca = fit(tr); ks[y] = (round(float(k), 2), round(float(hca), 2))
        for nm, kk in (('k.68', 0.68), ('k1', 1.0), ('kfit', k)):
            e = ll(kk, hca, data[y]); res[nm].extend(e.tolist()); per[nm][y] = float(e.mean())
            # team conference win%: expected vs realized
            ex, wn, gm = defaultdict(float), defaultdict(float), defaultdict(int)
            for d, c, w, h, a in data[y]:
                p = ncdf(kk * (d + hca * c) / SD)
                ex[h] += p; ex[a] += 1 - p; wn[h] += w; wn[a] += 1 - w; gm[h] += 1; gm[a] += 1
            wp[nm].extend([(ex[t] / gm[t] - wn[t] / gm[t]) ** 2 for t in gm if gm[t] >= 10])
        print(y, ks[y], {m: round(per[m][y], 4) for m in per})
    base = np.array(res['k.68'])
    out = {'fits': {str(y): v for y, v in ks.items()}}
    for m in res:
        e = np.array(res[m]); d = e - base
        t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if m != 'k.68' else 0.0
        out[m] = {'n': len(e), 'logloss': round(float(e.mean()), 5), 't': round(t, 2),
                  'won': sum(1 for y in per[m] if per[m][y] < per['k.68'][y]), 'of': len(per[m]),
                  'teamWinPctRmse': round(float(np.sqrt(np.mean(wp[m]))), 4)}
        print(m, out[m])
    json.dump({'built': 'scripts/research/units_nov28/cbb_builder_xw.py', 'models': out}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
