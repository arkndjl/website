#!/usr/bin/env python3
"""Research: the college basketball game model's availability term ('inj') priced by measured sit-again rates.

    python3 scripts/cbb_inj_research.py     # writes data/cbb_inj_research.json (numpy; two full walks, ~10 min)

The live term counts each rotation player who sat the team's last game as sitting the next one, whatever his run of
missed games. Barttorvik's logs say how often he does (2016-20, weighted by the term's player value): .52 after one
missed game, .68 after two, .77 after three, .86 after four or more (cbb_games.SIT_STREAK). Variant 'streak': each
player at his streak's rate over the all-streak rate the weight was fit on (.644). Same walk-forward and selection
rule as cbb_games.py --fit: the live inputs, the term swapped, paired t on 2016-20 at <= -1.5 and 2021-26 no worse.
The same rates price a listed player in the live build (scripts/cbb_games_live.py, the Covers injury report).
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C

OUT = os.path.join(C.ROOT, 'data', 'cbb_inj_research.json')


def main():
    F = json.load(open(C.FIT))
    P, feats = F['params'], F['feats']
    games, btname, d1s, tprior, avs = C.load_all()
    avs1 = {s: C.avail(C.bt_logs(s), streak=True) for s in avs}
    res = {}
    preds = {}
    for lab, av in (('live', avs), ('streak', avs1)):
        _, rows = C.run_walk(P, games, tprior, btname, d1s, av)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        preds[lab] = C.walk_pred(Xm, y, S, d1)
        b = np.linalg.lstsq(Xm[d1], y[d1], rcond=None)[0]
        res[lab] = {'coef': round(float(b[feats.index('inj')]), 4)}
        print(lab, 'done', flush=True)
    ok = ~np.isnan(preds['live']) & d1
    tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    e0, e1 = np.abs(preds['live'] - y), np.abs(preds['streak'] - y)
    for lab, e in (('live', e0), ('streak', e1)):
        res[lab].update(tuneMae=round(float(e[tune].mean()), 4), heldMae=round(float(e[held].mean()), 4))
    res['streak'].update(t=round(C.paired_t(e1[tune], e0[tune]), 2), heldT=round(C.paired_t(e1[held], e0[held]), 2))
    res['streak']['kept'] = res['streak']['t'] <= -1.5 and res['streak']['heldMae'] <= res['live']['heldMae']
    res['rates'] = {'streak': C.SIT_STREAK, 'all': C.SIT_AGAIN}
    print(json.dumps(res, indent=1))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
