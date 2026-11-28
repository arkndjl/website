#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL WAR replacement lines (Nov 28 2026, cross-sport port of the CBB/NBA tests): the descriptive lines by position
(F / D / G: players outside each team's top 13 / 7 / 2 by ice time, scripts/nhl_players.py fit_desc) are pooled over every
season since 2009. Pooled (expanding) vs the last three seasons, scored on each next season's line, 2013-26.
Writes research/repl_nov28/nhl.json."""
import json, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..', '..', '..'); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import nhl_players as NP
import nhl_data as D
lv = {}
for S in range(NP.FIRST, D.current_season()):
    sk, gk = NP.skaters(S), NP.goalies(S)
    if not sk: continue
    pv = NP.pen_value(S)
    parts = NP.describe_split(S, sk, gk, pv)
    for x in parts: x['S'] = S
    lv[S] = {}
    for pos, top in (('F', 13), ('D', 7), ('G', 2)):
        rest = NP.depth_rest(parts, pos, top)
        m = sum(r['toi'] for r in rest)
        lv[S][pos] = (sum(r['dr'] * r['toi'] for r in rest) / m, m) if m else None
    print(S, {k: round(v[0], 3) for k, v in lv[S].items() if v}, flush=True)
out, ys = {'bySeason': {S: {k: round(v[0], 4) for k, v in d.items() if v} for S, d in lv.items()}}, sorted(lv)
for how in ('expanding', 'trailing3'):
    for pos in 'FDG':
        e = []
        for S in ys[4:]:
            pr = [z for z in ys if z < S and lv[z].get(pos)]
            if how == 'trailing3': pr = pr[-3:]
            est = sum(lv[z][pos][0] * lv[z][pos][1] for z in pr) / sum(lv[z][pos][1] for z in pr)
            e.append((lv[S][pos][0] - est) ** 2)
        out[f'{how}_{pos}_rmse'] = round((sum(e) / len(e)) ** .5, 4)
json.dump(out, open(os.path.join(HERE, 'nhl.json'), 'w'), indent=1)
print({k: v for k, v in out.items() if k != 'bySeason'})
