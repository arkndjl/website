#!/usr/bin/env python3
"""Penalty discipline check (Oct 26 2026): do accepted penalties a team game in a player's final college season
(scripts/cfb_game_splits.py, ESPN play text) say anything about NFL AV a season beyond draft slot, for drafted OL,
CB and S (drafts 2016-23)? OL, CB and S have no FV history before PFN's 2024 lines, so this is the only test possible
now. Held out one draft class at a time; t over classes.   python3 scripts/cfb_penalty_check.py"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cfb_game_splits import nm, school, UNIT, PICKS, OUT  # noqa: E402

G = json.load(open(OUT))
pen = defaultdict(dict)
for k, v in G.items():
    s, n, sc = k.split('|')
    pen[(n, sc)][int(s)] = v.get('pen', 0.0)
grp = {'OL': UNIT['OL'], 'DB': UNIT['DB']}
rows = []
for r in csv.DictReader(open(PICKS)):
    try:
        d, pk = int(r['season']), int(r['pick'])
    except ValueError:
        continue
    if not 2016 <= d <= 2023:
        continue
    g = next((u for u, ps in grp.items() if r['position'] in ps), None)
    if not g:
        continue
    p = pen.get((nm(r['pfr_player_name']), school(r['college'])), {})
    rows.append({'d': d, 'g': g, 'lp': math.log(pk), 'av': (float(r['w_av'] or 0)) / (2025 - d + 1), 'pen': p.get(d - 1, 0.0),
                 'pen2': np.mean([p.get(d - k, 0.0) for k in (1, 2)])})
out = {}
for g in ('OL', 'DB'):
    R = [r for r in rows if r['g'] == g]
    for f in ('pen', 'pen2'):
        X1 = np.array([[1, r['lp'], r[f]] for r in R]); X0 = X1[:, :2]; y = np.array([r['av'] for r in R]); cl = np.array([r['d'] for r in R])
        gains = []
        for c in sorted(set(cl)):
            tr, te = cl != c, cl == c
            b1 = np.linalg.lstsq(X1[tr], y[tr], rcond=None)[0]; b0 = np.linalg.lstsq(X0[tr], y[tr], rcond=None)[0]
            gains.append(float(np.mean((y[te] - X0[te] @ b0) ** 2 - (y[te] - X1[te] @ b1) ** 2)))
        gains = np.array(gains); b = np.linalg.lstsq(X1, y, rcond=None)[0]
        res = y - X0 @ np.linalg.lstsq(X0, y, rcond=None)[0]
        out[f'{g} {f}'] = {'n': len(R), 'with_pen': int(sum(r[f] > 0 for r in R)), 'partial': round(float(np.corrcoef(X1[:, 2], res)[0, 1]), 3),
                           'coef': round(float(b[2]), 3), 't': round(float(gains.mean() / (gains.std(ddof=1) / math.sqrt(len(gains)))), 2),
                           'won': int((gains > 0).sum()), 'classes': len(gains)}
        print(f'{g} {f}', out[f'{g} {f}'])
json.dump(out, open(os.path.join(HERE, '.cache', 'fvrefit', 'penalty_check.json'), 'w'), indent=1)
