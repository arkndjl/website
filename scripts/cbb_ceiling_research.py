#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball ceiling BPM for the next up tab: the 80th percentile of next season's BPM if usage rises.

Rows: Barttorvik seasons 2010-25 with 10%+ of minutes and 10+ games, next season on 40%+ of team minutes (the
breakout role). Target = next season's raw BPM, weight = next min%. Base: shrunk BPM, 3-season Marcel, age, age^2,
ln min%; candidates added alone (scripts/breakout_lib.py ceiling_tests: pinball loss at .80, held out by season,
Holm): usage change (dU, dU^2), usage change x context (dU x age, usage, rim rate, 3PA rate, assist %, shrunk BPM),
scaled spread. Writes data/cbb_ceiling_fit.json, which scripts/cbb_breakout.py reads. numpy."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import cbb_breakout as B  # noqa: E402
import cbb_breakout_research as R  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'cbb_ceiling_fit.json')
SCEN, UCAP = 5.0, 32.0


def matrix(F, du):
    age = F['age']
    base = np.column_stack([F['s0'], F['mar'], age, age ** 2, F['lnm']])
    c1 = np.column_stack([du, du ** 2])
    c2 = np.column_stack([du, du * age, du * F['usg'], du * F['rimr'], du * F['tpar'], du * F['ast'], du * F['s0']])
    sx = np.column_stack([age, F['lnm'], np.abs(du), F['usg']])
    return base, c1, c2, sx


def main():
    P, _ = R.load(R.SRC)
    rows = []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if not b or y < 2010 or a['m'] < 10 or a['gp'] < 10 or b['m'] < 40:
            continue
        hist = [P[(pid, s)] for s in range(y - 4, y) if (pid, s) in P]
        rows.append((y + 1, B.ceil_feats(a, hist), b, b['usg'] - a['usg']))
    S = np.array([r[0] for r in rows], float)
    y = np.array([r[2]['bpm'] for r in rows], float)
    w = np.array([r[2]['m'] for r in rows], float)
    du = np.array([r[3] for r in rows], float)
    F = {k: np.array([r[1][k] for r in rows], float) for k in rows[0][1]}
    X0, c1, c2, sx = matrix(F, du)
    cands = {'usage change': (c1, None, ['dU', 'dU2']),
             'usage change x context': (c2, None, ['dU', 'dU*age', 'dU*usg', 'dU*rimr', 'dU*tpar', 'dU*ast', 'dU*s0']),
             'scaled spread': (None, sx, [])}
    tests, keep, final, cov, fit, extra = L.ceiling_tests(S, y, w, X0, cands, du >= 3)
    fit.update({'cols': ['s0', 'mar', 'age', 'age2', 'lnm'] + extra,
                'scol': ['age', 'lnm', 'absdU', 'usg'] if 'scaled spread' in keep else []})
    out = {'n': len(rows), 'seasons': [int(S.min()), int(S.max())], 'scen': SCEN, 'ucap': UCAP,
           'du_up_median': round(float(np.median(du[du >= 3])), 2), 'tests': tests, 'keep': keep, 'final': final,
           'coverage': cov, 'fit': fit}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'fit'}, indent=1))
    print('fit', fit)


if __name__ == '__main__':
    main()
