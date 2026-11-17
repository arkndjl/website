#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL ceiling WAR for the next up tab: the 80th percentile of next season's WAR a 1,000 minutes if ice time rises.

Rows: skater-seasons 2010-25 with 200+ minutes and 900+ minutes (per 82 team games) next season. Target = next
season's WAR a 1,000 minutes shrunk to replacement (k 600, the tab's scale; the raw-rate fit is kept in 'raw'), weight = next season's minutes. Workload = TOI a game. Base: shrunk WAR rate, Marcel,
age, age^2, ln minutes, D; candidates (scripts/breakout_lib.py ceiling_study, pinball loss at .80, held out by season,
Holm): TOI change, TOI change x (age, TOI, D, shrunk WAR rate, PP share, EV P/60), scaled spread. Writes
data/nhl_ceiling_fit.json (scripts/nhl_breakout.py reads it). numpy."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nhl_breakout as B  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'nhl_ceiling_fit.json')
Y0, SCEN, UP = 2010, 3.0, 1.5


def main():
    cur = B.D.current_season()
    P = {}
    for S in range(Y0, cur):
        for pid, o in B.season(S).items():
            P[(pid, S)] = o
    rows = []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if not b or a['war'] is None or b['war'] is None or a['tmin'] < B.ROW_MIN:
            continue
        if b['tmin'] * 82 / b['gmax'] < B.ROLE_MIN:
            continue
        rows.append((y + 1, B.ceil_inputs(a, B.history(P, pid, y)), B.shr(b), b['tmin'], b['toi'] - a['toi'],
                     b['war'] / b['tmin'] * 1000))
    S = np.array([r[0] for r in rows], float)
    y = np.array([r[2] for r in rows])
    w = np.array([r[3] for r in rows])
    du = np.array([r[4] for r in rows])
    F = {k: np.array([r[1][k] for r in rows], float) for k in rows[0][1]}
    spec = (['s0', 'mar', 'age', 'age2', 'lnm', 'd'], ['age', 'toi', 'd', 's0', 'pps', 'ev60'], ['age', 'lnm', 'toi', 'd'])
    out = L.ceiling_study(S, y, w, F, du, *spec, du >= UP)
    raw = L.ceiling_study(S, np.array([r[5] for r in rows]), w, F, du, *spec, du >= UP)
    out['raw'] = {k: raw[k] for k in ('tests', 'keep', 'final', 'coverage')}
    role = [(o['toi'], o['d']) for o in P.values() if o['tmin'] * 82 / o['gmax'] >= B.ROLE_MIN]
    out.update({'scen': SCEN, 'cap': {'F': round(float(np.quantile([t for t, d in role if not d], .99)), 1),
                                      'D': round(float(np.quantile([t for t, d in role if d], .99)), 1)},
                'du_up_median': round(float(np.median(du[du >= UP])), 2)})
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'fit'}, indent=1))
    print('fit', out['fit'])


if __name__ == '__main__':
    main()
