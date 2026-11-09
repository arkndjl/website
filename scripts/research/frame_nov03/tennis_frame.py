#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Tennis prospects: frame (height) as an FV driver, Nov 3 2026, without the Sackmann height leak.

    python3 scripts/tennis_prospects.py --rows                      # snapshot rows (scripts/.cache/tennis/rows.pkl)
    python3 scripts/research/frame_nov03/tennis_frame.py            # -> <out dir>/tennis_frame.json

Height is the only frame measure in the data (Sackmann's player files: no weight). It leaks on the full pool: Sackmann
fills heights for players who made it (Oct 26 2026: "no listed height" +3.4 FV ATP, +6.2 WTA out of sample). So:
  1. coverage by outcome: the share of rows with a height, by outcome FV band, in the full pool and among players
     already ranked inside the top R at the snapshot (R = 100, 150, 250): a subset whose coverage does not depend on
     the outcome (every band within 5 points of the subset's mean coverage) is one where a height can be tested.
  2. on each such subset (pre-registered: R = 100 and 150, Oct 26 snapshot, then Jan 15 as a check): the live kept model
     refit on the subset vs + height z (within tour, 2008-19 style: mean/sd of the tour's covered rows), birth-year-out
     (folds cluster by player), t >= 2 and 2/3 of years, top 50 (by season) not lower, forward (births <= 1993 fit,
     1994-97 graded) MSE and top 50 not worse. Holm across every fit.
  3. the full-pool height (missing -> 0) shown for reference only: it is the leak.
"""
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
import tennis_prospects as tp  # noqa: E402

OUTD = os.environ.get('FRAME_OUT') or '/mnt/project-files/fv/frame-nov03/tennis/'
BANDS = [(20, 20.5), (20.5, 40), (40, 50), (50, 81)]


def top50(pred, y, season):
    o = np.argsort(-pred)
    return float(pd.Series(y[o]).groupby(season[o]).head(50).mean())


def coverage(has, y):
    return {f'{lo:g}-{hi:g}': [int(((y >= lo) & (y < hi)).sum()), round(float(has[(y >= lo) & (y < hi)].mean()), 3) if ((y >= lo) & (y < hi)).any() else None]
            for lo, hi in BANDS}


def test(F, y, pos, by, se, kept, cols):
    P0, MU0, E0 = tp.loso(F, y, pos, by, kept)
    P1, MU1, E1 = tp.loso(F, y, pos, by, kept + cols)
    g = tp.gate(tp.fold_mse(E0, y, by), tp.fold_mse(E1, y, by))
    f0, f1 = tp.forward(F, y, pos, by, se, kept), tp.forward(F, y, pos, by, se, kept + cols)
    g.update(top50=round(top50(E1, y, se) - top50(E0, y, se), 3), fwd=round(f0[0] - f1[0], 3), fwdtop=round(f1[1] - f0[1], 3),
             mse0=round(float(np.mean((E0 - y) ** 2)), 3))
    bl, bo = tp.hurdle(F, y, pos, kept + cols, np.ones(len(F), bool))
    g['coefL'], g['coefO'] = round(float(bl[-1]), 3), round(float(bo[-1]), 3)
    g['p1'] = round(float(0.5 * math.erfc(g['t'] / math.sqrt(2))), 4)
    g['cv'] = bool(g['t'] >= 2 and g['wins'] >= 2 * g['of'] / 3)
    g['pass'] = bool(g['cv'] and g['top50'] >= 0 and g['fwd'] >= 0 and g['fwdtop'] >= 0)
    return g


def main():
    B = tp.base()
    rows = pickle.load(open(tp.ROWS, 'rb'))
    fit = json.load(open(tp.FIT))
    rep, allc = {}, {}
    for tour in tp.TOURS:
        X0 = rows[tour]
        kept = fit[tour]['kept']
        rep[tour] = {'kept': kept}
        for snap in ('10-26', '01-15'):
            Xs = X0[X0.snap == snap].reset_index(drop=True)
            y = tp.fv_rarity(Xs.pk.values, tp.scale(B, tour))
            has = Xs.ht.notna().values & (Xs.ht.fillna(0).values > 0)
            mu, sd = float(Xs.ht[has].mean()), float(Xs.ht[has].std())
            F = tp.design(Xs)
            F['htz'] = np.where(has, (Xs.ht.values - mu) / sd, 0.0)
            F['noht'] = (~has).astype(float)
            r = {'n': int(len(Xs)), 'htMeanSd': [round(mu, 1), round(sd, 1)], 'coverage': {'all': coverage(has, y)}}
            for R in (100, 150, 250):
                m = Xs['rank'].fillna(9999).values <= R
                r['coverage'][f'rank<={R}'] = coverage(has[m], y[m])
            # the full pool (the known leak), reference only
            pos, by, se = Xs.pk.values > 0, Xs.by.values, Xs.season.values
            r['fullPool'] = {'htz': test(F, y, pos, by, se, kept, ['htz']), 'noht': test(F, y, pos, by, se, kept, ['noht'])}
            r['subsets'] = {}
            for R in (100, 150):
                m = Xs['rank'].fillna(9999).values <= R
                cv = [v[1] for v in r['coverage'][f'rank<={R}'].values() if v[1] is not None and v[0] >= 30]
                mean_cov = float(has[m].mean())
                ok = bool(cv) and max(abs(c - mean_cov) for c in cv) <= .05
                Fm = F[m].reset_index(drop=True)
                Fm['htz'] = np.where(has[m], Fm.htz, 0.0)
                o = test(Fm, y[m], pos[m], by[m], se[m], kept, ['htz'])
                o.update(n=int(m.sum()), cov=round(mean_cov, 3), covFlat=ok)
                r['subsets'][f'rank<={R}'] = o
                allc[f'{tour} {snap} rank<={R} htz'] = o
                print(tour, snap, R, o, flush=True)
            rep[tour][snap] = r
            print(tour, snap, json.dumps(r['coverage']), r['fullPool'], flush=True)
    ks = sorted(allc, key=lambda k: allc[k]['p1'])
    for i, k in enumerate(ks):
        allc[k]['holm'] = bool(all(allc[j]['p1'] <= .05 / (len(ks) - n) for n, j in enumerate(ks[:i + 1])))
    rep['nTests'] = len(allc) + 4      # + the 4 full-pool reference fits per tour-snapshot pair counted as tests too
    rep['passed'] = [k for k, v in allc.items() if v['pass'] and v['holm'] and v['covFlat']]
    os.makedirs(OUTD, exist_ok=True)
    json.dump(rep, open(os.path.join(OUTD, 'tennis_frame.json'), 'w'), indent=1)
    print('passed', rep['passed'])


if __name__ == '__main__':
    main()
