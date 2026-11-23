#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Next up, NBA rookies (Noah, Nov 23 2026: first-years were missing because the returner model starts from last
season's line). Odds of a rookie season at the breakout bar from the draft slot.

    python3 scripts/nba_rookie_bo_research.py [laker_history.json]   # -> data/nba_rookie_bo_fit.json

Rows: every pick of the 1990-2025 drafts (scripts/nba_draft_picks.json); rookie season = the season after the draft.
Breakout = that season 1,000+ MP at or over the returner model's bar (BPM shrunk to -2 by MP, k 600), the tab's
definition; a pick who never played is a row with no breakout. Base: -ln pick. Candidates (alone, LOSO by draft,
Holm): second-round flag, top-5 hinge. Calibration and top-decile share held out."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nba_breakout as B  # noqa: E402
import nba_breakout_research as R  # noqa: E402
from cbb_freshman_bo_research import logit  # noqa: E402  damped Newton

OUT = os.path.join(R.ROOT, 'data', 'nba_rookie_bo_fit.json')
CANDS = {'second round': lambda pk: [1.0 if pk > 30 else 0.0], 'top-5 hinge': lambda pk: [max(0.0, math.log(5) - math.log(pk))]}


def main():
    P = R.seasons(sys.argv[1] if len(sys.argv) > 1 else R.SRC)
    DR = json.load(open(os.path.join(R.ROOT, 'scripts', 'nba_draft_picks.json')))
    rows = []
    for pid, (yr, pk) in DR.items():
        if not (1990 <= yr <= 2025) or not pk:
            continue
        a = P.get((pid, yr + 1))
        hit = 1.0 if a and a['mp'] >= 1000 and R.shr(a['bpm'], a['mp']) >= B.BAR else 0.0
        rows.append((yr, float(pk), hit))
    S = np.array([r[0] for r in rows], float); pk = np.array([r[1] for r in rows]); y = np.array([r[2] for r in rows])
    base = -np.log(pk)[:, None]

    def err(p, te):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))

    def run(X, keep=None):
        def fp(tr, te):
            b0, b = logit(X[tr], y[tr])
            p = L.sig(b0 + X[te] @ b)
            if keep is not None:
                keep[te] = p
            return p
        return L.loso(S, fp, err)
    flat = L.loso(S, lambda tr, te: np.full(te.sum(), y[tr].mean()), err)
    rb = run(base)
    res = {k: L.compare(rb, run(np.column_stack([base, np.array([f(v) for v in pk])]))) for k, f in CANDS.items()}
    L.holm(res)
    keep = [k for k in CANDS if res[k]['pass']]
    X = np.column_stack([base] + [np.array([CANDS[k](v) for v in pk]) for k in keep])
    ho = np.zeros(len(y))
    rf = run(X, ho)
    cuts = [0, .02, .05, .1, .2, .35, 1.01]
    calib = [[lo, min(hi, 1), int(m.sum()), round(float(ho[m].mean()), 3), round(float(y[m].mean()), 3)]
             for lo, hi in zip(cuts, cuts[1:]) for m in [(ho >= lo) & (ho < hi)] if m.sum()]
    o = np.argsort(-ho)
    share = float(y[o[:len(o) // 10]].sum() / y.sum())
    b0, b = logit(X, y)
    print('picks', len(y), 'rate', round(float(y.mean()), 4), 'base vs flat', L.compare(flat, rb))
    for k, v in res.items():
        print(' ', k, v)
    print(' kept', keep, 'final vs flat', L.compare(flat, rf), '\n calibration', calib, '\n top decile share', round(share, 3))
    json.dump({'source': 'LAKER_history RS + NBA drafts 1990-2025', 'definition': 'rookie season 1,000+ MP at or over the bar',
               'L': B.BAR, 'n': len(y), 'rate': round(float(y.mean()), 4), 'tests': res, 'keep': keep,
               'final_vs_flat': L.compare(flat, rf), 'calib_heldout': calib, 'top_decile_share': round(share, 3),
               'fit': {'cols': ['-ln pick'] + keep, 'b0': round(float(b0), 6), 'b': [round(float(v), 6) for v in b]}},
              open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
