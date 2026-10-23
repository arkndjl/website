#!/usr/bin/env python3
"""Research: in-season player values for the college basketball availability term ('inj'), team idea 4 (Oct 23 2026).

The live term values a rotation player who sat at his BPM to date shrunk to a flat -1 by 150 minutes: no prior.
Variants shrink a player with a line last season toward that season's BPM instead (cbb_games.last_bpm), with pk minutes'
weight. Same walk-forward and rule as cbb_inj_research.py: tune 2016-20 paired t <= -1.5, 2021-26 no worse.

    OMP_NUM_THREADS=1 python3 scripts/cbb_inseason_research.py [pk ...]   # data/cbb_inseason_research.json, ~2 min

Result (Oct 23 2026): FAILED, not shipped (cbb_games.avail prior/pk stay off). pk 150 / 400 / 1000: tune t +1.7 /
+1.1 / +0.8, held out t +0.5 / -0.2 / -0.0 (MAE within .0002). The term only prices who sat, and by the time a
player is a rotation regular (3+ games, 60% of them) his to-date BPM already outweighs last season's.
"""
import json
import os
import sys
from multiprocessing import get_context

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C

OUT = os.path.join(C.ROOT, 'data', 'cbb_inseason_research.json')
_A = {}


def one(pk):
    games, btname, d1s, tprior, avs, P, feats = _A['a']
    if pk:
        av = {s: C.avail(C.bt_logs(s), prior=C.last_bpm(s), pk=pk) for s in avs}
    else:
        av = avs
    _, rows = C.run_walk(P, games, tprior, btname, d1s, av)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    return pk, (C.walk_pred(Xm, y, S, d1), y, S, d1, [g['id'] for g, _, _ in D])


def main():
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    _A['a'] = (games, btname, d1s, tprior, avs, F['params'], list(F['feats']))
    pks = [float(a) for a in sys.argv[1:]] or [150.0, 400.0, 1000.0]
    with get_context('fork').Pool(int(os.environ.get('PROCS', 4))) as pool:
        res = dict(pool.map(one, [0.0] + pks))
    p0, y, S, d1, ids = res[0.0]
    ok = ~np.isnan(p0) & d1
    tune, held = ok & (S >= C.SCORE0) & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    e0 = np.abs(p0 - y)
    out = {'live': {'tuneMae': round(float(e0[tune].mean()), 4), 'heldMae': round(float(e0[held].mean()), 4)}, 'variants': []}
    for pk in pks:
        p1 = res[pk][0]
        assert res[pk][4] == ids
        e1 = np.abs(p1 - y)
        r = {'pk': pk, 'tuneD': round(float(e1[tune].mean() - e0[tune].mean()), 4), 'heldD': round(float(e1[held].mean() - e0[held].mean()), 4),
             't': round(C.paired_t(e1[tune], e0[tune]), 2), 'heldT': round(C.paired_t(e1[held], e0[held]), 2)}
        r['kept'] = r['t'] <= -1.5 and r['heldD'] <= 0
        out['variants'].append(r)
        print(r, flush=True)
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
