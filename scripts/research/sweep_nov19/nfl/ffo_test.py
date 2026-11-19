#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ffopportunity expected stats as an input to the fantasy stat-line ridges (PREREG.md lead 8).

    python3 ffo_test.py <dir of ep_weekly_<y>.csv> <out json>

Baseline: nfl_fantasy's walk-forward ridges at the live memory params. Candidate: one more column in each of py, ptd,
ry, rtd, rc, wy, wtd: the player's trailing mean of the expected value of that stat over his last 8 games played
(this and last season, before the game), shrunk by 2.5 pseudo-games of zero. PPR absolute error by position, paired,
clustered by season-week; 2016-20 selection, 2021-25 held."""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import nfl_fantasy as F   # noqa: E402

COL = {'py': 'pass_yards_gained_exp', 'ptd': 'pass_touchdown_exp', 'ry': 'rush_yards_gained_exp', 'rtd': 'rush_touchdown_exp',
       'rc': 'receptions_exp', 'wy': 'rec_yards_gained_exp', 'wtd': 'rec_touchdown_exp'}
LAST_N, K0 = 8, 2.5


def tclus(d, cl):
    u = np.unique(cl)
    s = np.array([d[cl == k].sum() for k in u]); n = np.array([(cl == k).sum() for k in u])
    m = d.mean()
    return m / (math.sqrt(((s - m * n) ** 2).sum() * len(u) / (len(u) - 1)) / len(d))


def history(src):
    H = defaultdict(list)      # gsis -> [(season, week, {stat: expected})]
    for y in range(2012, 2026):
        for r in csv.DictReader(open(os.path.join(src, f'ep_weekly_{y}.csv'))):
            try:
                H[r['player_id']].append((int(r['season']), int(float(r['week'])), {c: float(r[k] or 0) if r[k] not in ('NA', '') else 0.0 for c, k in COL.items()}))
            except (ValueError, KeyError):
                continue
    for v in H.values():
        v.sort(key=lambda x: (x[0], x[1]))
    return H


def feature(H, gsis, s, w, c):
    L = [x[2][c] for x in H.get(gsis, ()) if (x[0] == s and x[1] < w) or x[0] == s - 1][-LAST_N:]
    return sum(L) / (len(L) + K0)


def main():
    src, out = sys.argv[1], sys.argv[2]
    last = 2025
    games, box, dst, status, inj, info = F.load(F.FIRST, last)
    model, _ = F.implied(last, walkforward=True, snaps_at=[])
    wars = F.war_history(F.SNAP0, last)
    best = json.load(open(F.FIT))['params']
    R, _ = F.collect(games, box, dst, info, model, best, status, inj, wars)
    A = F.arrays({k: v for k, v in R.items() if k in F.SKILL})
    seasons = list(range(F.TEST0, last + 1))
    P0 = F.walk_forward(A, seasons)
    H = history(src)
    for pos, a in A.items():
        for c in F.PROJ[pos]:
            if c in COL:
                x = np.array([feature(H, g, int(s), int(w), c) for g, s, w in zip(a['id'], a['s'], a['w'])])
                a['X'][c] = np.column_stack([a['X'][c], x])
    P1 = F.walk_forward(A, seasons)
    res = {}
    for pos, a in A.items():
        res[pos] = {}
        for lab, ss in (('tune 2016-20', range(2016, 2021)), ('held 2021-25', range(2021, 2026))):
            k = F.pool(a, ss, F.POOL[pos])
            k = k[~np.isnan(P0[pos][F.comps_of(pos)[0]][k])]
            y = F.points(pos, a, a['Y'], 'ppr', actual=True)[k]
            e0 = np.abs(F.points(pos, a, P0[pos], 'ppr')[k] - y); e1 = np.abs(F.points(pos, a, P1[pos], 'ppr')[k] - y)
            d = e1 - e0
            cl = a['s'][k] * 100 + a['w'][k]
            res[pos][lab] = {'n': int(len(k)), 'maeBase': round(float(e0.mean()), 4), 'maeNew': round(float(e1.mean()), 4), 'd': round(float(d.mean()), 4),
                             't': round(float(tclus(d, cl)), 2),
                             'bySeason': {int(s): round(float(d[a['s'][k] == s].mean()), 4) for s in ss}}
        print(pos, json.dumps(res[pos]), flush=True)
    json.dump(res, open(out, 'w'), indent=1)


if __name__ == '__main__':
    main()
