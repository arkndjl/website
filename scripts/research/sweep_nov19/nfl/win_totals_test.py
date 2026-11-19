#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Preseason win totals as an early-season input (PREREG.md lead 10, descriptive: the free lines end in 2020).

    python3 win_totals_test.py <wf_margins.json> <win_totals.csv> <out json>

Weeks 1-6 of 2016-20: margin = a x model + b x (home line - away line) x 36 / 16, a and b fit on weeks 1-6 of the
seasons from 2015 before the scored one."""
import csv
import json
import math
import sys

import numpy as np

FR = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA'}


def main():
    rows = json.load(open(sys.argv[1]))['rows']
    wt = {}
    for r in csv.DictReader(open(sys.argv[2])):
        wt[(int(r['season']), FR.get(r['team'], r['team']))] = float(r['line'])
    D = []
    for g in rows:
        h, a = wt.get((g['s'], g['h'])), wt.get((g['s'], g['a']))
        if g['gt'] == 'REG' and g['w'] <= 6 and h is not None and a is not None and 2015 <= g['s'] <= 2020:
            D.append((g['s'], g['w'], g['pred'], (h - a) * 36 / 16, g['y']))
    D = np.array(D)
    S = D[:, 0]
    e0, e1, W = [], [], {}
    for s in range(2016, 2021):
        tr, te = S < s, S == s
        b = np.linalg.lstsq(D[tr][:, 2:4], D[tr, 4], rcond=None)[0]
        W[s] = [round(float(x), 3) for x in b]
        e0 += list(np.abs(D[te, 2] - D[te, 4])); e1 += list(np.abs(D[te][:, 2:4] @ b - D[te, 4]))
    e0, e1 = np.array(e0), np.array(e1); d = e1 - e0
    k = S >= 2016
    cl = (S[k] * 100 + D[k, 1]).astype(int)
    u = np.unique(cl); sm = np.array([d[cl == c].sum() for c in u]); n = np.array([(cl == c).sum() for c in u])
    t = d.mean() / (math.sqrt(((sm - d.mean() * n) ** 2).sum() * len(u) / (len(u) - 1)) / len(d))
    out = {'n': int(len(d)), 'maeModel': round(float(e0.mean()), 3), 'maeBlend': round(float(e1.mean()), 3), 'd': round(float(d.mean()), 4), 't': round(float(t), 2),
           'bySeason': {int(s): round(float(d[S[k] == s].mean()), 4) for s in range(2016, 2021)}, 'weights': W, 'lastFreeSeason': max(s for s, _ in wt)}
    print(json.dumps(out, indent=1))
    json.dump(out, open(sys.argv[3], 'w'), indent=1)


if __name__ == '__main__':
    main()
