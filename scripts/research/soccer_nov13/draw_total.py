#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Does the totals ratings' match-to-match total sharpen the 1X2 draw chance? The game model's means keep their ratio
and their league-season average total; only each match's total relative to that average follows the totals ratings
(x a strength g). Scored on 1X2 log loss against the live chances."""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine as E
import soccer_data as D
import soccer_games as G


def collect(rows, P):
    recs = []

    def score(r, S, lh, la, R):
        mu = R.total(r, lh, la)
        if mu is None or r['st'] != 'FT':
            return
        recs.append({'S': S, 'day': r['day'], 'lg': r['lg'], 'lh': lh, 'la': la, 'mu': mu,
                     'y': 0 if r['hs'] > r['as'] else 1 if r['hs'] == r['as'] else 2})
    lgs = {r['lg'] for r in rows if r['lg'] not in D.EURO and r['lg'] not in D.CUPS and (r.get('ouc') or r.get('oubc') or r.get('ouac'))}
    G.run(rows, P, score, totals=True, scored=lgs)
    return recs


def test(recs, lo, hi, g, rho, big5=None):
    v = [r for r in recs if lo <= r['S'] <= hi and (big5 is None or (r['lg'] in D.BIG5) == big5)]
    # each league's running mean of log(mu / model total), earlier matches only
    run = defaultdict(lambda: [0.0, 0])
    d, days = [], []
    for r in sorted(recs, key=lambda r: r['day']):
        k = r['lg']
        z = math.log(r['mu'] / (r['lh'] + r['la']))
        m = run[k][0] / run[k][1] if run[k][1] >= 50 else None
        run[k][0] += z; run[k][1] += 1
        if m is None or not (lo <= r['S'] <= hi) or (big5 is not None and (r['lg'] in D.BIG5) != big5):
            continue
        f = math.exp(g * (z - m))
        a = G.wdl(r['lh'] * f, r['la'] * f, rho)[r['y']]
        b = G.wdl(r['lh'], r['la'], rho)[r['y']]
        d.append(-math.log(a) + math.log(b)); days.append(r['day'])
    return {'n': len(d), 'd': round(sum(d) / len(d), 6), 't': G.cl_t(d, days)}


if __name__ == '__main__':
    rows = E.load_rows()
    P = G.params()
    recs = collect(rows, P)
    lo, hi = (2023, 2026) if '--held' in sys.argv else (2021, 2022)
    for g in ((0.5,) if '--held' in sys.argv else (0.25, 0.5, 0.75, 1.0)):
        print(g, 'all', test(recs, lo, hi, g, P['rho']), 'big5', test(recs, lo, hi, g, P['rho'], True), 'other', test(recs, lo, hi, g, P['rho'], False))
