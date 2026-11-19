# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Split conformal bands by group (numpy only), shared by the coverage scorecard.

    signed form   lower = f + q_g(alpha / 2), upper = f + q_g(1 - alpha / 2) of calibration residuals y - f in group g
    band form     score = max(lo - y, y - hi); new band = [lo - Q_g, hi + Q_g]   (conformalized quantile regression)
Quantiles carry the finite-sample correction ceil((n + 1) q) / n. Calibration residuals must be out of fold.

    python3 scripts/conformal.py --test
"""
import math

import numpy as np


def _q_hi(v, q):
    """the ceil((n + 1) q) / n empirical quantile (inf when n is too small for the level)"""
    v = np.sort(np.asarray(v, float))
    n = len(v)
    k = math.ceil((n + 1) * q)
    return float('inf') if k > n or n == 0 else float(v[k - 1])


def _q_lo(v, q):
    return -_q_hi(-np.asarray(v, float), 1 - q)


def signed(res_cal, g_cal, f_new, g_new, alpha=0.2):
    """bands for f_new from calibration residuals; a group with no calibration rows falls back to all rows"""
    res_cal, g_cal, f_new, g_new = np.asarray(res_cal, float), np.asarray(g_cal), np.asarray(f_new, float), np.asarray(g_new)
    lo, hi = np.empty(len(f_new)), np.empty(len(f_new))
    for g in np.unique(g_new):
        r = res_cal[g_cal == g]
        if len(r) < 10:
            r = res_cal
        m = g_new == g
        lo[m], hi[m] = f_new[m] + _q_lo(r, alpha / 2), f_new[m] + _q_hi(r, 1 - alpha / 2)
    return lo, hi


def band(lo_cal, hi_cal, y_cal, g_cal, lo_new, hi_new, g_new, alpha=0.2):
    lo_cal, hi_cal, y_cal, g_cal = (np.asarray(v) for v in (lo_cal, hi_cal, y_cal, g_cal))
    lo_new, hi_new, g_new = np.asarray(lo_new, float), np.asarray(hi_new, float), np.asarray(g_new)
    s = np.maximum(lo_cal - y_cal, y_cal - hi_cal)
    lo, hi = lo_new.copy(), hi_new.copy()
    for g in np.unique(g_new):
        r = s[g_cal == g]
        if len(r) < 10:
            r = s
        Q = _q_hi(r, 1 - alpha)
        m = g_new == g
        lo[m], hi[m] = lo_new[m] - Q, hi_new[m] + Q
    return lo, hi


def coverage(lo, hi, y, groups=None):
    lo, hi, y = np.asarray(lo, float), np.asarray(hi, float), np.asarray(y, float)
    inb = (y >= lo - 1e-9) & (y <= hi + 1e-9)
    out = {'n': int(len(y)), 'cover': round(float(inb.mean()), 4), 'width': round(float((hi - lo).mean()), 3)}
    if groups is not None:
        groups = np.asarray(groups)
        out['groups'] = {str(g): {'n': int((groups == g).sum()), 'cover': round(float(inb[groups == g].mean()), 4),
                                  'width': round(float((hi - lo)[groups == g].mean()), 3)} for g in np.unique(groups)}
    return out


def test():
    rng = np.random.default_rng(1)
    g = rng.integers(0, 3, 6000)
    f = rng.normal(size=6000)
    y = f + rng.normal(size=6000) * (1 + g) + (g == 2) * 0.5
    lo, hi = signed((y - f)[:3000], g[:3000], f[3000:], g[3000:])
    c = coverage(lo, hi, y[3000:], g[3000:])
    assert abs(c['cover'] - .8) < .03 and all(abs(v['cover'] - .8) < .05 for v in c['groups'].values()), c
    l0, h0 = f - 0.5, f + 0.5
    lo, hi = band(l0[:3000], h0[:3000], y[:3000], g[:3000], l0[3000:], h0[3000:], g[3000:])
    c = coverage(lo, hi, y[3000:], g[3000:])
    assert abs(c['cover'] - .8) < .03, c
    assert _q_hi([1, 2, 3], .8) == float('inf') and _q_hi(list(range(1, 10)), .8) == 8
    print('conformal ok')


if __name__ == '__main__':
    test()
