#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Next up = underrated (Noah, Nov 23 2026: "can Tyran Stokes really be next up if he's already our highest graded
recruit? Next up should focus more on underrated / breakout players"). EDGE = BO% minus the breakout odds his status
alone gives (the odds a player with his recruiting rank / draft slot / market value breaks out), so a top recruit
whose breakout everyone expects sits near 0 and a low-pedigree player the model likes sits at the top.

    python3 scripts/next_up_status_research.py [sport ...]   # -> data/next_up_status.json

Status (what the market already knows about him), per sport, fit on the same breakout rows as the tab
(scripts/next_up_young_research.py capture), logistic, leave one season out:
  cbb     recruiting rank: -ln rank (500 = unranked), unranked flag, top-100 hinge
  cfb     recruiting stars, unrated flag
  nba     draft slot: -ln pick (undrafted = 61), undrafted flag
  nfl     draft slot: -ln pick (undrafted = 270 as the research rows carry it), undrafted flag
  soccer  ln market value (EUR M; missing = the median, flag)
NHL has no status input in these rows (draft capital is inside its model; the stats API pull is partial here): no EDGE.
Check, on the rows the tab shows (young): each held-out season's top 25 by EDGE against the top 25 by BO%, counting
breakouts beyond what their status implied (actual minus the status odds summed) and actual breakouts."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import next_up_young_research as Y  # noqa: E402
from cbb_freshman_bo_research import logit  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'next_up_status.json')
SPORTS = ('nba', 'soccer', 'nfl', 'cbb', 'cfb')
TOP = 25


def status(sport, a, DR):
    """the status columns of one breakout row (same rule as scripts/next_up.py status_x)"""
    if sport == 'cbb':
        return status_x(sport, math.exp(-a['rg_lrk']) if a.get('unranked2', 1) < 0.5 else None)
    if sport == 'cfb':
        return status_x(sport, None if a.get('unr') else a.get('stars'))
    if sport == 'nba':
        return status_x(sport, (DR.get(a.get('pid')) or [None, None])[1])
    if sport == 'nfl':
        pk = a.get('pick')
        return status_x(sport, None if pk is None or pk >= 270 else pk)
    if sport == 'soccer':
        return status_x(sport, a.get('mv'))


def status_x(sport, v):
    """v: recruit rank (cbb), stars (cfb), pick (nba, nfl), market value EUR M (soccer); None = unranked / undrafted / missing"""
    if sport == 'cbb':
        lr = -math.log(min(500.0, v)) if v else -math.log(500)
        return [lr, 0.0 if v else 1.0, max(0.0, lr + math.log(100))]
    if sport == 'cfb':
        return [float(v) if v else 2.0, 0.0 if v else 1.0]
    if sport in ('nba', 'nfl'):
        return [-math.log(v if v else (61 if sport == 'nba' else 270)), 0.0 if v else 1.0]
    if sport == 'soccer':
        return [math.log(v + 0.1) if v else math.log(5.1), 0.0 if v else 1.0]


def main():
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    Yc = json.load(open(Y.OUT))
    DR = json.load(open(os.path.join(ROOT, 'scripts', 'nba_draft_picks.json')))
    for sport in sys.argv[1:] or SPORTS:
        R = Y.capture(sport, full=True)
        keep = json.load(open(os.path.join(ROOT, 'data', '%s_breakout_fit.json' % sport)))['breakout']['keep']
        y = np.array([r['hit'] for r in R]); S = np.array([r['S'] for r in R])
        X = np.array([sum([r['f']['base']] + [r['f'][k] for k in keep], []) for r in R])
        Z = np.array([status(sport, r['a'], DR) for r in R])
        bo, st = np.zeros(len(y)), np.zeros(len(y))
        for s in sorted(set(S.tolist())):
            te = S == s
            b0, b = L.logit(X[~te], y[~te]); bo[te] = L.sig(b0 + X[te] @ b)
            c0, c = logit(Z[~te], y[~te]); st[te] = L.sig(c0 + Z[te] @ c)
        yc = Yc.get(sport, {})
        if yc.get('rule') == 'cls':
            young = np.array([(r['cls'] or 3) <= 2 for r in R])
        else:
            young = np.array([r['age'] is not None and int(r['age']) <= yc.get('max_age', 99) for r in R])
        edge = bo - st
        tally = {'edge': [0.0, 0.0, 0.0], 'bo': [0.0, 0.0, 0.0]}     # actual, status-implied, BO%-implied
        for s in sorted(set(S[young].tolist())):
            ix = np.where(young & (S == s))[0]
            for k, v in (('edge', edge), ('bo', bo)):
                t = ix[np.argsort(-v[ix])[:TOP]]
                tally[k][0] += y[t].sum(); tally[k][1] += st[t].sum(); tally[k][2] += bo[t].sum()
        c0, c = logit(Z, y)
        sn = len(set(S[young].tolist()))
        o = {'n': len(y), 'young': int(young.sum()), 'seasons': sn,
             'status_vs_flat': L.compare(L.loso(S, lambda tr, te: np.full(te.sum(), y[tr].mean()), lambda p, te: (
                 float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))),
                 L.loso(S, lambda tr, te: st[te], lambda p, te: (float(-(y[te] * np.log(np.clip(p, 1e-6, 1)) + (1 - y[te]) * np.log(np.clip(1 - p, 1e-6, 1))).sum()), float(te.sum())))),
             'top': TOP,
             'top_by_edge': {'breakouts': int(tally['edge'][0]), 'status_implied': round(tally['edge'][1], 1), 'bo_implied': round(tally['edge'][2], 1)},
             'top_by_bo': {'breakouts': int(tally['bo'][0]), 'status_implied': round(tally['bo'][1], 1), 'bo_implied': round(tally['bo'][2], 1)},
             'fit': {'b0': round(float(c0), 6), 'b': [round(float(v), 6) for v in c]}}
        res[sport] = o
        print(sport, json.dumps(o), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
