#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA ceiling XPM for the next up tab: the 80th percentile of next season's XPM if a player's usage rises.

Rows: player-seasons 2010-25 with 300+ MP and 1,000+ MP the next season. Target = next season's raw XPM
(static/data/nba-xpm), weight = next season's MP; usage and shot profile from the LAKER history.
Base: shrunk XPM (sx0, the Nov 4 shrink; the board's sxpm is pXPM since Nov 24), age, age^2, ln MP; ceiling = mean + the 80th percentile of residuals.
Candidates added alone (scripts/breakout_lib.py ceiling_tests: pinball loss at .80, held out by season, Holm):
usage change (dU, dU^2), usage change x context (dU x age, usage, 2P%+, 3PA rate+, sxpm), scaled spread (residual size
on age, ln MP, |dU|, usage). Writes the 'ceiling' block of data/nba_ceiling_fit.json, which scripts/nba_breakout.py
reads. numpy."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nba_breakout_research as R  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
XPM = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
OUT = os.path.join(ROOT, 'data', 'nba_ceiling_fit.json')
SCEN = 5.0           # usage points added in the live scenario (one tab tier)
UCAP = 32.0          # scenario usage cap (99th percentile of 1,000+ MP seasons is about 32)


def xpm_seasons():
    X = {}
    for f in os.listdir(XPM):
        if f[:4].isdigit():
            d = json.load(open(os.path.join(XPM, f)))
            for p in d['players']:
                X[(p['id'], d['season'])] = p
    return X


def main():
    P = R.seasons(R.SRC)
    X = xpm_seasons()
    rows = []
    for (pid, y), a in X.items():
        b = X.get((pid, y + 1))
        la, lb = P.get((pid, y)), P.get((pid, y + 1))
        if not b or not la or not lb or a['mp'] < 300 or b['mp'] < 1000 or a.get('sx0', a.get('sxpm')) is None or b.get('xpm') is None:
            continue
        rows.append((y + 1, a, b, la, lb))
    S = np.array([r[0] for r in rows], float)
    y = np.array([r[2]['xpm'] for r in rows], float)
    w = np.array([r[2]['mp'] for r in rows], float)
    sx = np.array([r[1].get('sx0', r[1]['sxpm']) for r in rows], float)      # sx0: the Nov 4 shrink the build serves (pXPM here: t 1.34, Nov 27)
    age = np.array([r[1]['age'] or 25 for r in rows], float)
    lmp = np.log([r[1]['mp'] for r in rows])
    u = np.array([r[3]['usage_pct'] for r in rows], float)
    du = np.array([r[4]['usage_pct'] - r[3]['usage_pct'] for r in rows], float)
    fg2 = np.array([r[3]['fg2_plus'] for r in rows], float)
    tpar = np.array([r[3]['threepar_plus'] for r in rows], float)
    X0 = np.column_stack([sx, age, age ** 2, lmp])
    cands = {
        'usage change': (np.column_stack([du, du ** 2]), None, ['dU', 'dU2']),
        'usage change x context': (np.column_stack([du, du * age, du * u, du * fg2, du * tpar, du * sx]), None,
                                   ['dU', 'dU*age', 'dU*usg', 'dU*fg2+', 'dU*3par+', 'dU*sxpm']),
        'scaled spread': (None, np.column_stack([age, lmp, np.abs(du), u]), []),
    }
    tests, keep, final, cov, fit, extra = L.ceiling_tests(S, y, w, X0, cands, du >= 3)
    cols = ['sxpm', 'age', 'age2', 'lnmp'] + extra
    fit.update({'cols': cols, 'scol': ['age', 'lnmp', 'absdU', 'usg'] if 'scaled spread' in keep else []})
    out = {'n': len(rows), 'seasons': [int(S.min()), int(S.max())], 'scen': SCEN, 'ucap': UCAP,
           'du_up_median': round(float(np.median(du[du >= 3])), 2), 'tests': tests, 'keep': keep, 'final': final,
           'coverage': cov, 'fit': fit}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'fit'}, indent=1))
    print('fit', fit)


if __name__ == '__main__':
    main()
