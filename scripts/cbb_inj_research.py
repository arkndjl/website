#!/usr/bin/env python3
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
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C

OUT = os.path.join(C.ROOT, 'data', 'cbb_inj_research.json')


VARIANTS = {'streak': {'streak': True, 'bench': 0.0}, 'bench150': {'bench': 150.0}, 'bench400': {'bench': 400.0}}


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
    for lab in ['live'] + want:
        av = {s: C.avail(C.bt_logs(s), bench=0.0) for s in avs} if lab == 'live' else {s: C.avail(C.bt_logs(s), **VARIANTS[lab]) for s in avs}
        _, rows = C.run_walk(P, games, tprior, btname, d1s, av)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        preds[lab] = C.walk_pred(Xm, y, S, d1)
        b = np.linalg.lstsq(Xm[d1], y[d1], rcond=None)[0]
        res[lab] = {'coef': round(float(b[feats.index('inj')]), 4)}
        print(lab, 'done', flush=True)
    ok = ~np.isnan(preds['live']) & d1
    tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    e0 = np.abs(preds['live'] - y)
    res['live'].update(tuneMae=round(float(e0[tune].mean()), 4), heldMae=round(float(e0[held].mean()), 4))
    for lab in want:
        e1 = np.abs(preds[lab] - y)
        res[lab].update(tuneMae=round(float(e1[tune].mean()), 4), heldMae=round(float(e1[held].mean()), 4),
                        t=round(C.paired_t(e1[tune], e0[tune]), 2), heldT=round(C.paired_t(e1[held], e0[held]), 2))
        res[lab]['kept'] = res[lab]['t'] <= -1.5 and res[lab]['heldMae'] <= res['live']['heldMae']
        print(lab, res[lab], flush=True)
    res['rates'] = {'streak': C.SIT_STREAK, 'all': C.SIT_AGAIN}
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
