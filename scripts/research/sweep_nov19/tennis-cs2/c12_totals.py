#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""C12: pro CS2 round totals. Rounds to 13 with a per-map logit-normal round chance (tau) and an overtime mass, the
map-win chance held at the live map scale, against a flat distribution of the loser's rounds."""
import json, math, os, sys
from collections import defaultdict
import numpy as np
from scipy import stats
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cs_maps  # noqa: E402
C0 = json.load(open(os.path.join(cs_maps.SCRIPTS, '..', 'data', 'cs2_scale_research.json')))['cFinal']
GX, GW = np.polynomial.hermite_e.hermegauss(15); GW = GW / GW.sum()
K = np.arange(12); CB = np.array([math.comb(12 + k, k) for k in K], float); C24 = math.comb(24, 12)
TAUS = [0, .1, .2, .3, .4, .5, .6, .7, .8]; OMS = [0, .01, .02, .03, .04, .05]


def parts(g, tau):
    """A wins 13-k (12), B wins 13-k (12), overtime A, overtime B, at round logit g (mixture over tau)"""
    p = 1 / (1 + np.exp(-(g + tau * GX)))[:, None]
    a = (CB * p ** 13 * (1 - p) ** K) ; b = (CB * (1 - p) ** 13 * p ** K)
    ot = C24 * (p[:, 0] * (1 - p[:, 0])) ** 12
    q = p[:, 0]
    w6 = sum(math.comb(6, j) * q ** j * (1 - q) ** (6 - j) for j in (4, 5, 6)); t6 = 20 * (q * (1 - q)) ** 3
    po = w6 / (1 - t6)
    return GW @ a, GW @ b, float(GW @ (ot * po)), float(GW @ (ot * (1 - po)))


def solve(pwin, tau):
    lo, hi = -3.0, 3.0
    for _ in range(40):
        g = (lo + hi) / 2
        a, b, oa, ob = parts(g, tau)
        if a.sum() + oa < pwin: lo = g
        else: hi = g
    return a, b, oa, ob


def tclust(d, g):
    s = defaultdict(float)
    for v, k in zip(d, g): s[k] += v
    a = np.array(list(s.values())); t = a.sum() / (a.std(ddof=1) * len(a) ** .5)
    return {'n': int(len(d)), 'd': round(float(np.mean(d)), 5), 't': round(float(t), 2), 'p1': float(stats.t.cdf(t, len(a) - 1))}


R = [r for r in cs_maps.rows() if r['d'] >= '2024-01-01']
tune = np.array([r['d'] <= '2025-06-30' for r in R]); held = ~tune
bk = np.array([min(r['lr'], 12) if r['wr'] == 13 else 12 for r in R])        # loser rounds 0-11, 12 = overtime
ya = np.array([r['ya'] for r in R]); day = np.array([r['d'] for r in R]); mon = np.array([r['d'][:7] for r in R])
pw = 1 / (1 + np.exp(-C0 * np.array([r['z'] for r in R])))
cnt = np.bincount(bk[tune], minlength=13) + 1.0; flat = cnt / cnt.sum()
l_flat = -np.log(flat[bk])
# margin baseline: flat loser distribution x live map chance for the winner's side
l_flat_m = l_flat - np.log(np.where(ya == 1, pw, 1 - pw))
# candidate on a grid of the map chance (interpolation over 201 points)
grid = np.linspace(.005, .995, 199)
gi = np.clip(np.round((pw - .005) / .005).astype(int), 0, 198)
res = {}
for tau in TAUS:
    T = [solve(float(g), tau) for g in grid]
    tot = np.array([np.r_[a + b, oa + ob] for a, b, oa, ob in T])            # 13 buckets
    sgnA = np.array([np.r_[a, oa] for a, b, oa, ob in T]); sgnB = np.array([np.r_[b, ob] for a, b, oa, ob in T])
    for om in OMS:
        pt = (1 - om) * tot[gi, bk] + om * (bk == 12)
        otA = sgnA[gi, 12] / (sgnA[gi, 12] + sgnB[gi, 12])
        pm_ = np.where(ya == 1, (1 - om) * sgnA[gi, bk], (1 - om) * sgnB[gi, bk]) + om * (bk == 12) * np.where(ya == 1, otA, 1 - otA)
        res[(tau, om)] = (-np.log(pt), -np.log(pm_))
best = min(res, key=lambda k: res[k][0][tune].mean())
d = res[best][0] - l_flat; dm = res[best][1] - l_flat_m
months = sorted(set(mon[held]))
out = {'n_tune': int(tune.sum()), 'n_held': int(held.sum()), 'c0': C0, 'best': {'tau': best[0], 'omega': best[1]},
       'tune_grid': {f'{k[0]}/{k[1]}': round(float(v[0][tune].mean()), 5) for k, v in res.items() if k[1] in (0, best[1])},
       'flat': {'tune': round(float(l_flat[tune].mean()), 5), 'held': round(float(l_flat[held].mean()), 5)},
       'cand': {'tune': round(float(res[best][0][tune].mean()), 5), 'held': round(float(res[best][0][held].mean()), 5)},
       'iid_held': round(float(res[(0, 0)][0][held].mean()), 5),
       'tune': tclust(d[tune], day[tune]), 'held': tclust(d[held], day[held]),
       'months_better': f"{sum(d[held & (mon == m)].mean() < 0 for m in months)}/{len(months)}",
       'margin': {'tune': tclust(dm[tune], day[tune]), 'held': tclust(dm[held], day[held])},
       'vs_iid_held': tclust((res[best][0] - res[(0, 0)][0])[held], day[held])}
nb = sum(d[held & (mon == m)].mean() < 0 for m in months)
out['pass'] = bool(out['held']['t'] <= -2 and out['tune']['d'] < 0 and nb > len(months) / 2)
print(json.dumps(out, indent=1))
for p in (HERE, '/mnt/project-files/research-sweep-nov19/impl/tennis-cs2/'):
    json.dump(out, open(os.path.join(p, 'c12_results.json'), 'w'), indent=1)
