#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Which pick value chart balances real draft-day trades (PREREG.md lead 6).

    python3 draft_charts_test.py <dir with draft_values.csv, trades.csv> <out json>"""
import csv
import itertools
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

CHARTS = ['live', 'stuart', 'johnson', 'hill', 'otc', 'pff']
FUT = 0.48


def charts(p):
    V = {c: {} for c in CHARTS}
    R = list(csv.DictReader(open(p)))
    top = {c: float(R[0][c]) for c in CHARTS[1:]}
    for r in R:
        k = int(r['pick'])
        V['live'][k] = math.exp(-0.148 * max(0, k - 1) ** 0.698)
        for c in CHARTS[1:]:
            V[c][k] = max(float(r[c]) / top[c], 1e-4)
    return V


def deals(p):
    R = list(csv.DictReader(open(p)))
    n = Counter((r['season'], r['trade_date']) for r in R if r['pick_season'] == r['season'] and r['pick_number'] and r['trade_date'][5:7] in ('04', '05'))
    days = {s: set(sorted([d for (y, d) in n if y == str(s)], key=lambda d: -n[(str(s), d)])[:3]) for s in range(2011, 2026)}
    by = defaultdict(list)
    for r in R:
        s = int(r['season'])
        if s in days and r['trade_date'] in days[s]:
            by[r['trade_id']].append(r)
    out = []
    for rs in by.values():
        s = int(rs[0]['season'])
        if len({r['gave'] for r in rs} | {r['received'] for r in rs}) != 2 or any(not r['pick_season'] for r in rs):    # a row with no pick is a player
            continue
        if any(not r['pick_round'] for r in rs):
            continue
        cur = [(int(r['pick_number']), r['received']) for r in rs if r['pick_season'] == str(s) and r['pick_number']]
        if not cur:
            continue
        b, U = min(cur)
        items = []      # (to the team moving up?, pick or mid-round pick, years out)
        ok = True
        for r in rs:
            yo = int(r['pick_season']) - s
            if yo == 0 and r['pick_number']:
                k = int(r['pick_number'])
            elif yo >= 0:
                k = (int(r['pick_round']) - 1) * 32 + 16
            else:
                ok = False; break
            items.append((r['received'] == U, min(k, 262), yo))
        if ok and any(not u for u, _, _ in items):
            out.append((s, b, items))
    return out


def imb(V, w, d, top_only):
    """ln(value the team moving down receives / value it gives), chart = geometric blend with weights w"""
    val = lambda k, yo: math.exp(sum(wc * math.log(V[c][k]) for c, wc in zip(CHARTS, w) if wc)) * FUT ** yo
    s, b, items = d
    down_gets = sum(val(k, yo) for u, k, yo in items if not u)
    down_gives = val(b, 0) if top_only else sum(val(k, yo) for u, k, yo in items if u)
    return math.log(down_gets / down_gives)


def tclus(d, cl):
    u = np.unique(cl)
    s = np.array([d[cl == k].sum() for k in u]); n = np.array([(cl == k).sum() for k in u])
    m = d.mean()
    return m / (math.sqrt(((s - m * n) ** 2).sum() * len(u) / (len(u) - 1)) / len(d))


def main():
    src, out = sys.argv[1], sys.argv[2]
    V = charts(os.path.join(src, 'draft_values.csv'))
    D = deals(os.path.join(src, 'trades.csv'))
    S = np.array([d[0] for d in D])
    tune, held = S <= 2018, S >= 2019
    res = {'n': len(D), 'nTune': int(tune.sum()), 'nHeld': int(held.sum())}
    for lab, top_only in (('topPick', True), ('totals', False)):
        one = lambda w: np.array([abs(imb(V, w, d, top_only)) for d in D])
        grid = [w for w in itertools.product(range(11), repeat=6) if sum(w) == 10]
        best = min(grid, key=lambda w: one([x / 10 for x in w])[tune].mean())
        wb = [x / 10 for x in best]
        e0 = one([1, 0, 0, 0, 0, 0]); e1 = one(wb)
        d = e0 - e1
        r = {'weights': dict(zip(CHARTS, wb)),
             'single': {c: {'tune': round(float(one([1.0 if x == c else 0 for x in CHARTS])[tune].mean()), 4),
                            'held': round(float(one([1.0 if x == c else 0 for x in CHARTS])[held].mean()), 4)} for c in CHARTS},
             'tune': {'live': round(float(e0[tune].mean()), 4), 'blend': round(float(e1[tune].mean()), 4)},
             'held': {'live': round(float(e0[held].mean()), 4), 'blend': round(float(e1[held].mean()), 4), 'd': round(float(d[held].mean()), 4),
                      't': round(float(tclus(d[held], S[held])), 2),
                      'byYear': {int(y): round(float(d[S == y].mean()), 4) for y in sorted(set(S[held]))}},
             'signedHeld': {c: round(float(np.mean([imb(V, [1.0 if x == c else 0 for x in CHARTS], dd, top_only) for dd in np.array(D, dtype=object)[held]])), 4) for c in CHARTS}}
        res[lab] = r
    print(json.dumps(res, indent=1))
    json.dump(res, open(out, 'w'), indent=1)


if __name__ == '__main__':
    main()
