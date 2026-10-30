#!/usr/bin/env python3
"""CBB game model research, Oct 30 2026: margin terms on the shipped walk (no rewalk), mostly season-stage interactions.

    python3 scripts/cbb_stage_research.py      # -> data/cbb_stage_research.json

stage = max(0, 1 - days since Nov 1 / 60) (1 on opening night, 0 from New Year on). Terms added to the shipped feats:
  <f>_st   f x stage for f in eff, elo, gm, bpi (each input's weight free to change through the season)
  effsq    eff x |eff| / 20 (big spreads compress or stretch)
  home_st  home x stage
Bar as cbb_oct30_research (tune 2016-20 t <= -1.5, held 2021-26 and lined held no worse).
"""
import json
import os
import sys
from datetime import datetime

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_games as C
import cbb_oct30_research as O

OUT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_stage_research.json')


def main():
    F = json.load(open(C.FIT))
    feats = list(F['feats'])
    games, btname, d1s, tprior, avs = C.load_all()
    W, rows = C.run_walk(F['params'], games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    pr = C.walk_pred(Xm, y, S, d1)
    st = np.array([max(0.0, 1 - (datetime.strptime(C.et_date(g['date']), '%Y-%m-%d') - datetime(g['season'] - 1, 11, 1)).days / 60) for g, _, _ in D])
    col = {f: Xm[:, feats.index(f)] for f in feats}
    T = {f'{f}_st': col[f] * st for f in ('eff', 'elo', 'gm', 'bpi', 'home')}
    T['effsq'] = col['eff'] * np.abs(col['eff']) / 20
    T['all_st'] = None
    ok = ~np.isnan(pr) & d1
    k1 = ok & (S >= C.SCORE0) & (S <= C.TUNE_END); k2 = ok & (S > C.TUNE_END)
    day = np.array([g['date'][:10] for g, _, _ in D]); team = np.array([f"{g['home']}|{g['season']}" for g, _, _ in D])
    early = st > 0.25
    masks = {'tune': k1, 'held': k2, 'tuneEarly': k1 & early, 'heldEarly': k2 & early,
             'held21_23': k2 & (S <= 2023), 'held24_26': k2 & (S >= 2024)}
    out = []
    for nm, v in T.items():
        if v is None:
            X2 = np.column_stack([Xm] + [T[f'{f}_st'] for f in ('eff', 'elo', 'gm', 'bpi')])
        else:
            X2 = np.column_stack([Xm, v])
        p2 = C.walk_pred(X2, y, S, d1)
        b = np.linalg.lstsq(X2[k1 | (S < C.SCORE0) & d1], y[k1 | (S < C.SCORE0) & d1], rcond=None)[0]
        out.append(O.score(nm, p2, pr, y, line, masks, [day, team], {'coefLast': round(float(b[-1]), 4)}))
    with open(OUT, 'w') as f:
        json.dump({'results': out, 'base': {nm: round(float(np.abs(pr[k] - y[k]).mean()), 4) for nm, k in masks.items()}}, f, indent=1)


if __name__ == '__main__':
    main()
