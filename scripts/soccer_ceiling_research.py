#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer ceiling GAR for the next up tab: the 80th percentile of next season's GAR a 90 if shot involvement rises.

Rows: big-five outfield seasons with 450+ minutes and 5+ involvements, 1,500+ minutes next season. Target = next
season's GAR a 90 shrunk to replacement (k 600, the tab's scale), weight = next season's minutes. Workload = SI% (shots
+ key passes per 100 team shots on the pitch). Base: shrunk GAR a 90, Marcel, age, age^2, ln minutes; candidates
(scripts/breakout_lib.py ceiling_study, pinball loss at .80, held out by season, Holm): SI% change, SI% change x (age,
SI%, xG+xA per involvement, shrunk GAR a 90, club npxG a 90, forward), scaled spread. Writes
data/soccer_ceiling_fit.json (scripts/soccer_breakout.py reads it). numpy."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import soccer_breakout as B  # noqa: E402
import soccer_breakout_research as R  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'soccer_ceiling_fit.json')
SCEN, UP = 10.0, 5.0


def main():
    P, _, _, last = R.data()
    rows = []
    for (p, s), a in P.items():
        b = P.get((p, s + 1))
        if s + 1 > last or not b or a['pos'] == 'GK' or a['min'] < B.MIN_BASE or a['inv'] < 5 or b['min'] < B.MIN_NEXT:
            continue
        rows.append((s + 1, B.ceil_inputs(a, B.history(P, p, s)), B.shr(b['g90'], b['min']), b['min'], b['U'] - a['U']))
    S = np.array([r[0] for r in rows], float)
    y = np.array([r[2] for r in rows])
    w = np.array([r[3] for r in rows], float)
    du = np.array([r[4] for r in rows])
    F = {k: np.array([r[1][k] for r in rows], float) for k in rows[0][1]}
    out = L.ceiling_study(S, y, w, F, du, ['s0', 'mar', 'age', 'age2', 'lnm'], ['age', 'U', 'eff', 's0', 'tx', 'fw'],
                          ['age', 'lnm', 'U'], du >= UP)
    role = [o['U'] for (p, s), o in P.items() if s <= last and o['pos'] != 'GK' and o['min'] >= B.MIN_NEXT]
    out.update({'scen': SCEN, 'cap': round(float(np.quantile(role, .99)), 1),
                'du_up_median': round(float(np.median(du[du >= UP])), 2)})
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'fit'}, indent=1))
    print('fit', out['fit'])


if __name__ == '__main__':
    main()
