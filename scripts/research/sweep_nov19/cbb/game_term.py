#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 1b: rotation-weighted to-date own BPM as a cbb_games.py candidate, on the ESPN-built point-in-time logs
(scripts/cbb_box_hist.py; no season-final rating in any row). Pre-registered in impl/cbb/prereg.md (B1 of
scripts/research/cbb_audit_nov16/tbpm.py, unchanged).

    OMP_NUM_THREADS=1 python3 scripts/research/sweep_nov19/cbb/game_term.py
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'cbb_audit_nov16'))
import cbb_games as C
import cbb_box_hist as BH
C.BTLOG = BH.PIT
import tbpm as TB

OUT = os.environ.get('OUT', '/mnt/project-files/research-sweep-nov19/impl/cbb/game_term_results.json')


def ct(d, g):
    s = defaultdict(float)
    for x, k in zip(d, g): s[k] += x
    v = np.array(list(s.values()))
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v))))


def main():
    F = json.load(open(C.FIT))
    feats = list(F['feats'])
    assert C.BPI or True
    games, btname, d1s, tprior, avs = C.load_all()
    if not C.BPI: sys.exit('no BPI cache: restore scripts/.cache/cbb/bpi first')
    _, rows = C.run_walk(F['params'], games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    tv = {}
    for s in sorted(set(S.tolist())):
        for (t, d), v in TB.team_values(C.bt_logs(int(s))).items():
            tv[(int(s), t, d)] = v[0]
    col = np.zeros(len(D)); have = np.zeros(len(D), bool); day = []
    for i, (g, _, _) in enumerate(D):
        d = C.et_date(g['date']); s = int(g['season']); day.append(d)
        h, a = tv.get((s, btname.get(g['home']), d)), tv.get((s, btname.get(g['away']), d))
        if h is not None and a is not None:
            col[i] = 0.7 * (h - a); have[i] = True
    day = np.array(day)
    p0 = C.walk_pred(Xm, y, S, d1)
    p1 = C.walk_pred(np.column_stack([Xm, col]), y, S, d1)
    ok = ~np.isnan(p0) & d1 & ~np.isnan(line)
    tune, held = ok & (S >= C.SCORE0) & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    e0, e1 = np.abs(p0 - y), np.abs(p1 - y)
    d = e1 - e0
    dm = p1 - p0; k = held & (np.abs(dm) > 1e-9)
    by = {int(s): round(float(d[held & (S == s)].mean()), 4) for s in range(C.TUNE_END + 1, C.LAST + 1)}
    out = {'coverage': round(float(have[ok].mean()), 3), 'n_tune': int(tune.sum()), 'n_held': int(held.sum()),
           'base_mae': {'tune': round(float(e0[tune].mean()), 4), 'held': round(float(e0[held].mean()), 4)},
           'close_mae_held': round(float(np.abs(line[held] - y[held]).mean()), 4),
           'tuneD': round(float(d[tune].mean()), 4), 'tuneT_day': round(ct(d[tune], day[tune]), 2),
           'heldD': round(float(d[held].mean()), 4), 'heldT_day': round(ct(d[held], day[held]), 2), 'heldT_row': round(C.paired_t(e1[held], e0[held]), 2),
           'bySeasonHeldD': by, 'seasons_better': int(sum(v < 0 for v in by.values())),
           'closeSlope': round(float(np.polyfit(dm[k], (y - line)[k], 1)[0]), 3) if k.sum() > 100 else None,
           'coef': round(float(np.linalg.lstsq(np.column_stack([Xm, col])[d1 & ~np.isnan(y)], y[d1 & ~np.isnan(y)], rcond=None)[0][-1]), 3)}
    out['pass'] = bool(out['heldT_day'] <= -2 and out['tuneD'] < 0 and out['seasons_better'] >= 4 and (out['closeSlope'] or -1) >= 0)
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
