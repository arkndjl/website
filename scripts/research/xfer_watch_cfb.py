#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Transfer watch, College Football: pre-registered D1 (/mnt/project-files/transfer-watch/prereg.md) on the landing
model's base terms (scripts/cfb_landing_fit.py NAMES; the coaching terms need Wikipedia head coaches, which answer
429 to the build container): one temperature on the utilities fit on one NIL-era cycle, scored on the other, both
ways; and the top-1 reliability (the model's top school: mean predicted share vs hit rate).

    python3 scripts/cfb_transfer_fit.py            # builds scripts/.cache/transfer/rows.json
    python3 scripts/research/xfer_watch_cfb.py     # -> data/xfer_watch_research.json ("cfb")
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import cfb_landing_fit as L  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'data', 'xfer_watch_research.json')


def lls(Xs, b):
    out, top, hit = [], [], []
    for X in Xs:
        u = X @ b; u -= u.max(); p = np.exp(u); p /= p.sum()
        out.append(math.log(p[0])); j = int(np.argmax(p)); top.append(p[j]); hit.append(j == 0)
    return np.array(out), np.array(top), np.array(hit, float)


def rel(top, hit):
    bins = [(0, .02), (.02, .05), (.05, .1), (.1, .2), (.2, 1.01)]
    return {'meanTop': round(float(top.mean()), 3), 'hitTop': round(float(hit.mean()), 3),
            'bins': [[a, b, round(float(top[(top >= a) & (top < b)].mean()), 3), round(float(hit[(top >= a) & (top < b)].mean()), 3), int(((top >= a) & (top < b)).sum())]
                     for a, b in bins if ((top >= a) & (top < b)).sum()]}


def main():
    rows = json.load(open(L.ROWS)); loc = json.load(open(L.LOC))
    S = L.schools(rows)
    movers = [r for r in rows if r['y'] == 'transfer' and r['home'] and r['to'] and not r['abroad']]
    old = [m for m in movers if m['season'] == 2024]; new = [m for m in movers if m['season'] == 2025]
    Xo, _ = L.design(old, S, loc); Xn, _ = L.design(new, S, loc)
    res = {}
    for name, A, B in (('2024->2025', Xo, Xn), ('2025->2024', Xn, Xo)):
        b, _ = L.clogit(A)
        best = max(np.arange(0.5, 1.81, 0.02), key=lambda t: lls(A, b * t)[0].sum())
        l0, t0, h0 = lls(B, b); l1, t1, h1 = lls(B, b * best)
        d = l1 - l0
        res[name] = {'n': len(B), 'llBase': round(float(l0.mean()), 4), 'tau': round(float(best), 2), 'll': round(float(d.mean()), 4),
                     't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'top1': rel(t0, h0), 'top1Temp': rel(t1, h1)}
        print(name, json.dumps(res[name]), flush=True)
    a, b2 = res['2024->2025'], res['2025->2024']
    res['gate'] = {'D1_temperature': {'pass': a['ll'] > 0 and a['t'] >= 2 and not (b2['ll'] < 0 and b2['t'] <= -1), 'A': [a['ll'], a['t']], 'B': [b2['ll'], b2['t']]},
                   'D3_reunion': 'untestable here: Wikipedia head-coach infoboxes answer 429 to the build container'}
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    out['cfb'] = res
    json.dump(out, open(OUT, 'w'), indent=1)
    print('gate', res['gate'])


if __name__ == '__main__':
    main()
