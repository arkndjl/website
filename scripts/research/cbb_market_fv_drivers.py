#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""FV driver test for the CBB market metrics (Nov 3 2026, thread "Add CBB NIL, coaches and team builder").

    python3 scripts/cbb_careers_kit.py                       # once: scripts/.cache/cbb/careers.json
    python3 scripts/research/cbb_market_fv_drivers.py        # -> scripts/data/cbb_market_fv_drivers.json

Each candidate goes through scripts/cbb_fv_drivers.py's bar on the shipped driver set (data/cbb_fit.json): out-of-sample
deviance over the FV ladder, two 5-fold player splits, gain in both, 4/5 folds, clustered t >= 2. Boards 2009-16
(outcomes mature). Candidates, built only from what was known before the board season:
  tp_move     Transfer% (scripts/cbb_market_fit.py move model, NIL-era coefficients) on last season's line
  col_value   college value, the xNIL basis: minutes share x (BPM + 3), last season
  xnil_rel    col_value over his level's mean (the price step: high / mid / low major)
  prog_lvl    program level, the NIL budget tilt: mean team strength over the five seasons before (newcomers too)
Not testable on mature outcomes: coach Over (records from 2015), coach Dev (school_dev's NBA-FV version was already
null, tau 0), zNIL and On3 valuations (2026 only).
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import cbb_data as D  # noqa: E402
import cbb_fit as F  # noqa: E402
import cbb_fv_drivers as V  # noqa: E402
import cbb_market_fit as MF  # noqa: E402

OUT = os.path.join(HERE, 'data', 'cbb_market_fv_drivers.json')
FIT = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_market_fit.json')))
HM = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}
MM = {'A10', 'MWC', 'WCC', 'Amer', 'MVC'}
_orig = V.extra
RANK = {}
PROG = {}
LV = {}


def prep(careers):
    G, ST, PR, CS = V.TM
    by = defaultdict(list)
    for c in careers:
        for s in c['seasons']:
            by[(s['team'], s['year'])].append(s)
    for k, ss in by.items():
        for i, s in enumerate(sorted(ss, key=lambda s: -(s.get('min_per') or 0))):
            RANK[(id(s))] = i + 1
    for (t, y) in ST:
        v = [ST[(t, z)] for z in range(y - 4, y + 1) if (t, z) in ST]
        PROG[(t, y)] = float(np.mean(v))
    lv = defaultdict(list)
    for c in careers:
        for s in c['seasons']:
            m = (s.get('min_per') or 0) / 100
            L = 'HM' if s.get('conf') in HM else 'MM' if s.get('conf') in MM else 'LM'
            lv[(L, s['year'])].append(max(0.0, m * ((s.get('bpm') or -3) + 3)))
    for k, v in lv.items():
        LV[k] = float(np.mean(v)) or 1.0


def extra(c, i, f):
    f = _orig(c, i, f)
    s = c['seasons'][i]
    G, ST, PR, CS = V.TM
    f['prog_lvl'] = PROG.get((s['team'], s['year'] - 1), PROG.get((s['team'], s['year']), 0.0)) / 10
    if f['newcomer']:
        return f
    p = c['seasons'][i - 1]
    m = (p.get('min_per') or 0) / 100
    f['col_value'] = max(0.0, m * ((p.get('bpm') or -3) + 3))
    L = 'HM' if p.get('conf') in HM else 'MM' if p.get('conf') in MM else 'LM'
    f['xnil_rel'] = f['col_value'] / LV.get((L, p['year']), 1.0)
    mv = FIT['move']
    r = {'bpm': p.get('bpm'), 'min_per': p.get('min_per'), 'usg': p.get('usg'), 'yr': p.get('yr'), 'rg_lrk': f.get('rg_lrk'),
         'hti': f.get('ht'), 'gp': p.get('gp'), 'age': f.get('age')}
    full = MF.feats_move(r, ST.get((p['team'], p['year']), 0.0) * 1.4, p.get('conf') in HM, RANK.get(id(p), 10), False, 0.0, 0.0)
    x = np.array([full[MF.MOVE_F.index(k)] for k in mv['feats']], float)
    P = MF.mnl_p(((x - np.array(mv['mu'])) / np.array(mv['sd']))[None, :], np.array(mv['B']))[0]
    f['tp_move'] = float(P[1])
    return f


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    V.TM = V.team_maps(careers)
    prep(careers)
    V.extra = extra
    thr = F.xpm_scale(careers)
    for c in careers:
        c['nba']['fvx'] = F.xpm_fv(c, thr)
    rows = []
    for c in careers:
        if c['last'] > 2020:
            continue
        for i, s in enumerate(c['seasons']):
            if s['year'] not in F.TRAIN:
                continue
            rows.append({'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'f': extra(c, i, F.features(c, i))})
    tops = [c['nba']['fvx'] for c in careers if c['last'] in F.SCALE_CLASSES and c['nba']['fvx'] >= 60]
    F.TOP_MEAN = round(float(np.mean(tops)), 2)
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    res = {}
    for grp, cands in (('returner', ['tp_move', 'col_value', 'xnil_rel', 'prog_lvl']), ('newcomer', ['prog_lvl'])):
        m = fit['models'][grp]
        rr = [r for r in rows if r['f']['newcomer'] == (grp == 'newcomer')]
        out = V.run(rr, list(m['kept']), cands, m['lam'], grp)
        res[grp] = out
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'bar': 'gain in both splits, >= 4/5 folds each, clustered t >= 2',
               'results': res}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
