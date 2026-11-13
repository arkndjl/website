#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT RWA: shrink toward the teammates' mean instead of the division prior alone (the pro CS2 rating's teammate
prior, scripts/cs2_nov13_research.py P1; pre-registered in research/cs2_nov13_prereg.md as conditional on it).

    python3 scripts/esea_tprior_research.py   -> data/esea_tprior_research.json (~3 min)

Shrink target = prior + tp x (rounds-weighted mean rating of the player's teammates - prior), tp picked on S54-S57
match log loss, then one held pass on S58-S59 against the shipped RWA: paired log loss, t over match days.
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esea_rwa_research as R  # noqa: E402
import esea_standin_research as SR  # noqa: E402

OUT = os.path.join(R.ROOT, 'data', 'esea_tprior_research.json')
TP = 0.0


def ratings(M, c, T, p):
    n = len(M.pid)
    m = M.d < T
    w = M.R * np.exp(-(T - M.d) / R.DAY * math.log(2) / p['h']) * m
    wsum = np.bincount(M.p, w, n)
    dlev = np.bincount(M.p, w * M.dv, n) / np.maximum(wsum, 1e-9)
    prior = p['g'] * dlev + p['nu']
    theta = prior.copy()
    key = M.g * 2 + M.side
    cnt = np.bincount(key, None, len(M.games) * 2)
    for _ in range(8):
        th = theta[M.p]
        opp = np.bincount(M.oa, th[M.ob], len(M.p)) / np.maximum(M.opp_cnt, 1)
        adj = c + p['opp'] * opp
        pri = prior
        if TP:
            mate = (np.bincount(key, th, len(M.games) * 2)[key] - th) / np.maximum(cnt[key] - 1, 1)
            pri = prior + TP * (np.bincount(M.p, w * mate, n) / np.maximum(wsum, 1e-9) - prior) * (wsum > 0)
        theta = (np.bincount(M.p, w * adj, n) + p['k'] * pri) / (wsum + p['k'])
    return theta, wsum


def main():
    global TP
    d, ms = SR.load()
    M = R.Maps(ms)
    cuts = R.weekly(ms)
    tune_g = (M.gseason >= 53) & (M.gseason <= R.TUNE[1])
    fit = json.load(open(R.OUT))
    p = fit['params']
    if p['w'] == 'ols':
        beta, ml, _, _ = R.stat_weights(M, tune_g)
        c = R.contributions(M, beta, ml, p['pm'])
    else:
        c = R.ark_values(M, tune_g)
    R.ratings = ratings
    gaps, grid = {}, []
    for tp in (0.0, .25, .5, .75, 1.0):
        TP = tp
        gaps[tp] = R.rwa_gaps(ms, M, c, p, cuts)
        grid.append([R.tune_ll(R.rows_of(ms, {'x': gaps[tp]}), ['x']), tp])
        print(grid[-1], file=sys.stderr)
    pick = min(grid[1:])[1]
    rows = R.rows_of(ms, {'rwa': gaps[0.0], 'tp': gaps[pick]})
    day = {m['id']: m['at'] // 86400 for m in ms}
    _, l0 = SR.split_fit(rows, ['rwa'], R.TUNE, R.HELD)
    _, l1 = SR.split_fit(rows, ['tp'], R.TUNE, R.HELD)
    by = {}
    for k in l0:
        by.setdefault(day[k], []).append(l1[k] - l0[k])
    a = np.array([sum(v) for v in by.values()]) / len(l0) * len(by)
    t = float(a.mean() / (a.std(ddof=1) + 1e-12) * math.sqrt(len(a)))
    res = {'grid': grid, 'pick': pick, 'tuneBetter': min(grid[1:])[0] < grid[0][0], 'n': len(l0), 'days': len(by),
           'held_ll': [sum(l0.values()) / len(l0), sum(l1.values()) / len(l1)], 'tDay': round(t, 2)}
    res['pass'] = bool(res['tuneBetter'] and t <= -2)
    json.dump(res, open(OUT, 'w'), indent=1)
    print(json.dumps(res))


if __name__ == '__main__':
    main()
