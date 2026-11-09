#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research: the college basketball game model's availability term ('inj') priced by measured sit-again rates.

    python3 scripts/cbb_inj_research.py     # writes data/cbb_inj_research.json (numpy; two full walks, ~10 min)

Before Oct 21 2026 the live term counted each rotation player who sat the team's last game as sitting the next one, whatever his run of
missed games. Barttorvik's logs say how often he does (2016-20, weighted by the term's player value): .52 after one
missed game, .68 after two, .77 after three, .86 after four or more (cbb_games.SIT_STREAK). Variant 'streak': each
player at his streak's rate over the all-streak rate the weight was fit on (.644). Same walk-forward and selection
rule as cbb_games.py --fit: the live inputs, the term swapped, paired t on 2016-20 at <= -1.5 and 2021-26 no worse.
The same rates price a listed player in the live build (scripts/cbb_games_live.py, the Covers injury report).
Variants 'bench150' / 'bench400': the value lost is the absent player's BPM over his team's own bench (its non-rotation
players' minutes-weighted BPM to date, shrunk to the flat -3 by 150 or 400 minutes), not over a flat -3.
    python3 scripts/cbb_inj_research.py bench150 bench400     # just those (earlier results kept in the file)
Variants 'absorb1' / 'absorb.5' (Nov 2 2026, base: the live term, bench 400): the ratings already hold the games a
sitter has missed (hl 0, lam 4: out the last 10 of 30, a third of him is priced out), so each sitter's value is cut by
absorb x his games missed / (team games + 4). Base 'live' then is the shipped term (bench 400).
    python3 scripts/cbb_inj_research.py absorb1 absorb.5
Result: absorb1 passes 2016-20 (MAE t -2.48) but not 2021-26 (MAE 9.5756 both, t -0.3; the edge shrunk to the close
8.9631 both; further from the close, t +1.65), absorb.5 t -0.87: not shipped (cbb_games.ABSORB stays 0).
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C

OUT = os.path.join(C.ROOT, 'data', 'cbb_inj_research.json')


VARIANTS = {'streak': {'streak': True, 'bench': 0.0}, 'bench150': {'bench': 150.0}, 'bench400': {'bench': 400.0},
            'absorb1': {'absorb': 1.0}, 'absorb.5': {'absorb': 0.5}}
ABSORB_V = ('absorb1', 'absorb.5')


_ARGS = {}


def _one(lab):
    P, feats, games, tprior, btname, d1s, avs, base = _ARGS['a']
    av = {s: C.avail(C.bt_logs(s), **(base if lab == 'live' else VARIANTS[lab])) for s in avs}
    _, rows = C.run_walk(P, games, tprior, btname, d1s, av)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    b = np.linalg.lstsq(Xm[d1], y[d1], rcond=None)[0]
    print(lab, 'done', flush=True)
    return lab, (C.walk_pred(Xm, y, S, d1), round(float(b[feats.index('inj')]), 4), (y, S, line, d1))


def main():
    F = json.load(open(C.FIT))
    P, feats = F['params'], F['feats']
    games, btname, d1s, tprior, avs = C.load_all()
    want = [v for v in VARIANTS if v in sys.argv[1:]] or list(VARIANTS)
    try:
        res = json.load(open(OUT))
    except (OSError, ValueError):
        res = {}
    preds = {}
    new = all(v in ABSORB_V for v in want)          # the absorb tests run against the shipped term (bench 400)
    base = {'absorb': 0.0} if new else {'bench': 0.0, 'absorb': 0.0}
    _ARGS['a'] = (P, feats, games, tprior, btname, d1s, avs, base)
    import multiprocessing as mp                   # one walk per variant, in parallel (forked: the loaded inputs shared)
    with mp.get_context('fork').Pool(int(os.environ.get('PROCS', 3))) as pool:
        out = dict(pool.map(_one, ['live'] + want))
    for lab, (pr, cf, mats) in out.items():
        preds[lab] = pr
        res[lab] = {'coef': cf}
        y, S, line, d1 = mats
    ok = ~np.isnan(preds['live']) & d1
    tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    e0 = np.abs(preds['live'] - y)
    lk = ok & ~np.isnan(line)                  # against the close: |model - close| (closer to the close is better)
    c0 = np.abs(preds['live'] - line)
    res['live'].update(tuneMae=round(float(e0[tune].mean()), 4), heldMae=round(float(e0[held].mean()), 4),
                       tuneClose=round(float(c0[tune & lk].mean()), 4), heldClose=round(float(c0[held & lk].mean()), 4))
    for lab in want:
        e1 = np.abs(preds[lab] - y)
        c1 = np.abs(preds[lab] - line)
        res[lab].update(tuneMae=round(float(e1[tune].mean()), 4), heldMae=round(float(e1[held].mean()), 4),
                        t=round(C.paired_t(e1[tune], e0[tune]), 2), heldT=round(C.paired_t(e1[held], e0[held]), 2),
                        tuneClose=round(float(c1[tune & lk].mean()), 4), heldClose=round(float(c1[held & lk].mean()), 4),
                        closeT=round(C.paired_t(c1[tune & lk], c0[tune & lk]), 2), heldCloseT=round(C.paired_t(c1[held & lk], c0[held & lk]), 2))
        res[lab]['kept'] = res[lab]['t'] <= -1.5 and res[lab]['heldMae'] <= res['live']['heldMae']
        if new:
            # value against the close: the edge (model - close) shrunk at its 2016-20 slope on result - close, scored
            # on 2021-26 (the prediction a bet reads); kept only if that improves held out too
            def edge(pr):
                d, r = pr - line, y - line
                b = float((d[tune & lk] * r[tune & lk]).sum() / (d[tune & lk] ** 2).sum())
                return b, np.abs(line + b * d - y)
            b0, v0 = edge(preds['live']); b1, v1 = edge(preds[lab])
            res['live'].update(edgeSlope=round(b0, 4), heldEdgeMae=round(float(v0[held & lk].mean()), 4))
            res[lab].update(edgeSlope=round(b1, 4), heldEdgeMae=round(float(v1[held & lk].mean()), 4),
                            heldEdgeT=round(C.paired_t(v1[held & lk], v0[held & lk]), 2))
            res[lab]['kept'] = res[lab]['kept'] and res[lab]['heldT'] < 0 and res[lab]['heldEdgeT'] < 0
        print(lab, res[lab], flush=True)
    if new:
        res['absorbBase'] = 'live = the shipped term (bench 400) for the absorb variants'
    res['rates'] = {'streak': C.SIT_STREAK, 'all': C.SIT_AGAIN}
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
