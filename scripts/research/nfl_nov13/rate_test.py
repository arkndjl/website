#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""C1 of PREREG.md: pXP/60 with the prior mean moved by the market's read (draft slot on a rookie deal, cap share after).

    python3 scripts/nfl_rate_research.py --prep            # once
    python3 scripts/research/nfl_nov13/rate_test.py        # data/nfl_audit_nov13.json ('rate')
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import nfl_rate as R             # noqa: E402
import nfl_rate_research as RR   # noqa: E402
import market as MK              # noqa: E402

OUT = os.path.join(RR.ROOT, 'data', 'nfl_audit_nov13.json')
SIG = {}


def sig(y, pid):
    k = (y, pid)
    if k not in SIG:
        SIG[k] = MK.signal(pid, y)
    return SIG[k]


def slopes(D, ys, m):
    """per group and kind: the signal's weighted mean, and the weighted LS slope of rate - sub mean on it"""
    acc = defaultdict(lambda: [0.0, 0.0])
    for y in ys:
        for pid, r in D[y].items():
            s = sig(y, pid)
            if s:
                a = acc[(r['grp'], s[0])]; a[0] += s[1] * r['sn']; a[1] += r['sn']
    xb = {k: a[0] / a[1] for k, a in acc.items() if a[1]}
    num, den = defaultdict(float), defaultdict(float)
    for y in ys:
        for pid, r in D[y].items():
            s = sig(y, pid)
            if s:
                k = (r['grp'], s[0]); dx = s[1] - xb[k]
                num[k] += r['sn'] * dx * (R.rate(r) - m[r['sub']]); den[k] += r['sn'] * dx * dx
    return xb, {k: num[k] / den[k] if den[k] else 0.0 for k in num}


def pred_m(D, y, pid, K, m, xb, b):
    r = D[y][pid]
    g = r['grp']
    prior = m.get(r['sub'], 0.0)
    s = sig(y, pid)
    if s and (g, s[0]) in b:
        prior += b[(g, s[0])] * (s[1] - xb[(g, s[0])])
    P, S = 0.0, 0.0
    for i, w in enumerate(R.MARCEL):
        h = D.get(y - i, {}).get(pid)
        if h and h['grp'] == g:
            P += w * h['pts'] * 60; S += w * h['sn']
    return (P + K[g] * prior) / (S + K[g])


def fit_k(D, ys, m, xb, b):
    K = {}
    for g in R.GROUPS:
        def sse(k):
            s = w = 0.0
            for y, pid, t, sn in RR.pairs(D, ys):
                if D[y][pid]['grp'] == g:
                    e = pred_m(D, y, pid, {g: k}, m, xb, b) - t
                    s += sn * e * e; w += sn
            return s / w if w else 0.0
        K[g] = min(RR.KS, key=sse)
    return K


def main():
    D = RR.load()
    targets = list(RR.YEARS[:-1])
    E = {'marcel': [], 'marcelM': []}
    by = {'marcel': {}, 'marcelM': {}}
    P = []
    for ty in targets:
        tr = [y for y in targets if y != ty]
        m, b0, xb0 = RR.means(D, tr)
        K0 = RR.fit_k(D, tr, 'marcel', m, b0, xb0)
        xb, b = slopes(D, tr, m)
        K1 = fit_k(D, tr, m, xb, b)
        s0 = s1 = w = 0.0
        for y, pid, t, sn in RR.pairs(D, [ty]):
            p0 = RR.pred(D, y, pid, 'marcel', K0, m, b0, xb0); p1 = pred_m(D, y, pid, K1, m, xb, b)
            E['marcel'].append((sn, (p0 - t) ** 2, y, pid)); E['marcelM'].append((sn, (p1 - t) ** 2, y, pid))
            P.append((p1, t, sn))
            s0 += sn * (p0 - t) ** 2; s1 += sn * (p1 - t) ** 2; w += sn
        by['marcel'][ty] = s0 / w; by['marcelM'][ty] = s1 / w
        print(ty, round(s0 / w, 4), round(s1 / w, 4), flush=True)

    def paired(keep=None):
        d = [(a[0], a[1] - c[1]) for a, c in zip(E['marcelM'], E['marcel']) if keep is None or keep(a)]
        W = sum(x for x, _ in d)
        mu = sum(x * v for x, v in d) / W
        var = sum(x * (v - mu) ** 2 for x, v in d) / W
        neff = W ** 2 / sum(x * x for x, _ in d)
        return round(mu, 5), round(mu / math.sqrt(var / neff), 2), int(neff)

    W = sum(p[2] for p in P)
    mx = sum(p[0] * p[2] for p in P) / W; my = sum(p[1] * p[2] for p in P) / W
    slope = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in P) / sum(p[2] * (p[0] - mx) ** 2 for p in P)
    wm = lambda f: sum(a * e for a, e, *_ in E[f]) / sum(a for a, *_ in E[f])
    d, t, neff = paired()
    wins = sum(1 for y in targets if by['marcelM'][y] < by['marcel'][y])
    import harness as H
    p = H.t_cdf(t, neff - 1)
    m_all, _, _ = RR.means(D, targets)
    xb_all, b_all = slopes(D, targets, m_all)
    res = {'wmse': {'marcel': round(wm('marcel'), 4), 'marcelM': round(wm('marcelM'), 4)}, 'd': d, 't': t, 'p': p, 'neff': neff,
           'wins': f'{wins}/{len(targets)}', 'slope': round(slope, 3),
           'pass': t <= -2 and wins >= 7 and 0.8 <= slope <= 1.2,
           'bySeason': {str(y): [round(by['marcel'][y], 4), round(by['marcelM'][y], 4)] for y in targets},
           'byGroup': {g: paired(lambda a, g=g: D[a[2]][a[3]]['grp'] == g)[:2] for g in R.GROUPS},
           'byKind': {k: paired(lambda a, k=k: (sig(a[2], a[3]) or ('n',))[0] == k)[:2] for k in ('r', 'v', 'n')},
           'slopes': {f'{g}:{k}': round(v, 4) for (g, k), v in sorted(b_all.items())},
           'K': fit_k(D, targets, m_all, xb_all, b_all)}
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    old['rate'] = res
    json.dump(old, open(OUT, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
