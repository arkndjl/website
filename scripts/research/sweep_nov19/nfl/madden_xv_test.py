#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Madden launch overall as an OL quality part in XV (PREREG.md M5): the missed-games test and leave-one-season-out
team r, live parts against live parts + the OL part.

    python3 scripts/nfl_xv.py --prep
    python3 madden_xv_test.py <madden.json> <out json>"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import nfl_war as W   # noqa: E402
import nfl_xv as X    # noqa: E402
from madden_rate_test import roster, zmap   # noqa: E402


def residuals(S, val):
    """per-game squared residual of the missed-games model with one value column, and the game's (season, home) cluster"""
    SUBS = W.SUBS
    eqs, fe, cl = [], {}, []
    for y, d in S.items():
        P = d['players']
        regs = defaultdict(list)
        for i, p in enumerate(P):
            if 'reg' in p:
                regs[p['t']].append(i)
        acc = defaultdict(list)
        for t, L in regs.items():
            for i in L:
                acc[P[i]['sub']].append(val[y][i] / P[i]['reg']['gp'] * X.PTS_PER_WIN)
        mu = {s: sum(v) / len(v) for s, v in acc.items()}
        for g in d['sched']:
            x = np.zeros(len(SUBS) + 1)
            for t, sgn in ((g['h'], 1), (g['a'], -1)):
                gi = d['tg'][t].index(g['id'])
                for i in regs.get(t, []):
                    r = P[i]['reg']
                    if r['start'] <= gi < r['end'] and gi not in r['played']:
                        x[SUBS.index(P[i]['sub'])] += sgn
                        x[len(SUBS)] += sgn * (val[y][i] / r['gp'] * X.PTS_PER_WIN - mu[P[i]['sub']])
            eqs.append((fe.setdefault((y, g['h']), len(fe)), fe.setdefault((y, g['a']), len(fe)), 0 if g['neutral'] else 1, x,
                        max(-35.0, min(35.0, g['hs'] - g['as']))))
            cl.append(f"{y}{g['h']}")
    nf = len(fe)
    A = np.zeros((len(eqs), nf + 1 + len(SUBS) + 1)); Y = np.zeros(len(eqs))
    for i, (h, a_, hfa, x, m) in enumerate(eqs):
        A[i, h] = 1; A[i, a_] = -1; A[i, nf] = hfa; A[i, nf + 1:] = x; Y[i] = m
    reg = np.zeros(A.shape[1]); reg[:nf] = 2
    M = A.T @ A + np.diag(reg); cf = np.linalg.solve(M, A.T @ Y); res = Y - A @ cf
    cov = (res @ res / (len(Y) - A.shape[1])) * np.linalg.inv(M)
    return res ** 2, np.array(cl), float(-cf[-1]), float(-cf[-1] / math.sqrt(cov[-1, -1]))


def tclus(d, cl):
    u = np.unique(cl)
    s = np.array([d[cl == k].sum() for k in u]); n = np.array([(cl == k).sum() for k in u])
    m = d.mean()
    return m / (math.sqrt(((s - m * n) ** 2).sum() * len(u) / (len(u) - 1)) / len(d))


def xvs(S, lam, value):
    ys = sorted(S)
    xv, pr, ac, w_all = {}, [], [], None
    for y in ys:
        w = X.fit_w(S, [v for v in ys if v != y], lam)
        xv[y] = X.xv_of(S, y, w, value)
        T = defaultdict(float)
        for p, a in zip(S[y]['players'], xv[y]):
            T[p['t']] += a
        for t, tm in S[y]['teams'].items():
            pr.append(T[t]); ac.append((tm['pf'] - tm['pa']) / tm['g'])
    w_all = X.fit_w(S, ys, lam)
    return xv, X.corr(pr, ac), {f'{g}.{part}': round(float(v), 4) for (g, part), v in zip(X.COLS, w_all)}


def main():
    mad = json.load(open(sys.argv[1]))
    S = X.load(); X.zscore(S)
    _, value, _ = W.sub_lines()
    lam = json.load(open(X.OUT))['lambda'] if 'lambda' in json.load(open(X.OUT)) else 20
    base, r0, _ = xvs(S, lam, value)
    X.PARTS['OL'] = ['pen', 'mad']
    X.COLS[:] = [(g, part) for g in X.GROUPS for part in X.PARTS[g]]
    matched = {}
    for y, d in S.items():
        z = zmap(mad[str(y)], roster(y)) if str(y) in mad else {}
        n = 0
        for p in d['players']:
            if X.GROUP_OF[p['sub']] == 'OL':
                v = z.get(p['pfr'])
                p['z']['mad'] = 0.0 if v is None else max(-3.0, min(3.0, v))
                n += v is not None
        matched[y] = n
    cand, r1, w1 = xvs(S, lam, value)
    out = {'lambda': lam, 'matchedOL': matched, 'teamR': {'live': round(r0, 4), 'withMadden': round(r1, 4)}, 'weightOLmad': w1.get('OL.mad'),
           'weightOLpen': w1.get('OL.pen')}
    for lab, ys in (('tune 2018-21', (2018, 2019, 2020, 2021)), ('held 2022-24', (2022, 2023, 2024))):
        Sy = {y: S[y] for y in ys}
        e0, cl, c0, t0 = residuals(Sy, base)
        e1, _, c1, t1 = residuals(Sy, cand)
        d = e0 - e1
        out[lab] = {'games': len(d), 'live': {'coef': round(c0, 3), 't': round(t0, 2)}, 'withMadden': {'coef': round(c1, 3), 't': round(t1, 2)},
                    'sseGain': round(float(d.sum()), 1), 'tPaired': round(float(tclus(d, cl)), 2)}
    print(json.dumps(out, indent=1))
    json.dump(out, open(sys.argv[2], 'w'), indent=1)


if __name__ == '__main__':
    main()
