#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research: in-season player BPM aggregated to the team as a CBB game-model input (pre-registered,
/mnt/project-files/cbb/audit-nov16/prereg.md, B family, Holm over 2).

    OMP_NUM_THREADS=1 python3 scripts/research/cbb_audit_nov16/tbpm.py   # -> data/cbb_tbpm_research.json
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import cbb_games as C

# B1/B2 read Barttorvik's opponent-adjusted game BPM (history adjusted with season-final ratings: a leak); B3, the raw
# box game score, is the leak-free version the amendment ships or not

OUT = os.path.join(C.ROOT, 'data', 'cbb_tbpm_research.json')
K, LASTN = 100.0, 3


def gmsc_logs(season):
    """bt_logs' shape with each row's value = Hollinger game score per 40 minutes from the raw box (no opponent
    adjustment), centered on the season's minute-weighted mean"""
    rows = C.bt_rows(season)
    by = defaultdict(lambda: defaultdict(dict))
    vals = []
    for r in rows:
        try:
            m = float(r[8] or 0)
            if m <= 0:
                continue
            fgm, fga = (r[23] or 0) + (r[25] or 0), (r[24] or 0) + (r[26] or 0)
            g = (r[33] or 0) + .4 * fgm - .7 * fga - .4 * ((r[28] or 0) - (r[27] or 0)) + .7 * (r[34] or 0) + .3 * (r[35] or 0) \
                + (r[40] or 0) + .7 * (r[36] or 0) + .7 * (r[41] or 0) - .4 * (r[42] or 0) - (r[37] or 0)
            d = str(r[0]); d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
            v = 40 * g / m
            by[r[47]][d][r[51]] = [m, v]; vals.append((m, v))
        except (IndexError, TypeError, ValueError):
            continue
    mu = sum(m * v for m, v in vals) / max(1e-9, sum(m for m, _ in vals))
    for t in by:
        for d in by[t]:
            for p in by[t][d]:
                by[t][d][p] = (by[t][d][p][0], by[t][d][p][1] - mu)
    return {t: sorted(v.items()) for t, v in by.items()}


def team_values(logs):
    """{(bt team, date): (B1 rotation-now value, B2 season value)} the morning of each game date (games before it)"""
    out = {}
    for t, gl in logs.items():
        mins, mb = defaultdict(float), defaultdict(float)
        recent = []
        for d, rows in gl:                       # in date order
            if mins:
                bp = {p: mb[p] / (mins[p] + K) for p in mins}
                tot = sum(mins.values())
                b2 = 5 * sum(mins[p] / tot * bp[p] for p in mins)
                rm = defaultdict(float)
                for r in recent[-LASTN:]:
                    for p, (m, _) in r.items():
                        rm[p] += m
                rt = sum(rm.values()) or 1.0
                b1 = 5 * sum(rm[p] / rt * bp.get(p, 0.0) for p in rm)
                out[(t, d)] = (b1, b2)
            for p, (m, g) in rows.items():
                if m and m > 0:
                    mins[p] += m; mb[p] += m * (g or 0.0)
            recent.append(rows)
    return out


def main():
    F = json.load(open(C.FIT))
    feats = list(F['feats'])
    games, btname, d1s, tprior, avs = C.load_all()
    _, rows = C.run_walk(F['params'], games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    tv = {}
    for s in sorted(set(S.tolist())):
        C.bt_logs(int(s))
        raw = team_values(gmsc_logs(int(s)))
        for (t, d), v in team_values(C.bt_logs(int(s))).items():
            tv[(int(s), t, d)] = (v[0], v[1], raw.get((t, d), (0.0, 0.0))[0])
    cols = np.zeros((len(D), 3)); have = np.zeros(len(D), bool)
    for i, (g, _, _) in enumerate(D):
        d = C.et_date(g['date']); s = int(g['season'])
        h, a = tv.get((s, btname.get(g['home']), d)), tv.get((s, btname.get(g['away']), d))
        if h and a:
            cols[i] = [0.7 * (h[0] - a[0]), 0.7 * (h[1] - a[1]), 0.7 * (h[2] - a[2])]; have[i] = True
    # the morning value: logs list a date only when the team played that day, which is every game day here
    p0 = C.walk_pred(Xm, y, S, d1)
    ok = ~np.isnan(p0) & d1
    tune, held = ok & (S >= C.SCORE0) & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    lined = held & ~np.isnan(line)
    e0 = np.abs(p0 - y)
    out = {'coverage': round(float(have[ok].mean()), 3), 'base': {'tune': round(float(e0[tune].mean()), 4), 'held': round(float(e0[held].mean()), 4)}, 'tests': {}}
    for j, name in enumerate(('B1', 'B2', 'B3')):
        p1 = C.walk_pred(np.column_stack([Xm, cols[:, j]]), y, S, d1)
        e1 = np.abs(p1 - y)
        dm = p1 - p0
        rl = (y - line)
        k = lined & (np.abs(dm) > 1e-9)
        slope = float(np.polyfit(dm[k], rl[k], 1)[0]) if k.sum() > 100 else None
        coef = np.linalg.lstsq(np.column_stack([Xm, cols[:, j]])[d1 & ~np.isnan(y)], y[d1 & ~np.isnan(y)], rcond=None)[0][-1]
        out['tests'][name] = {'tuneD': round(float(e1[tune].mean() - e0[tune].mean()), 4), 'tuneT': round(C.paired_t(e1[tune], e0[tune]), 2),
                              'heldD': round(float(e1[held].mean() - e0[held].mean()), 4), 'heldT': round(C.paired_t(e1[held], e0[held]), 2),
                              'linedD': round(float(e1[lined].mean() - e0[lined].mean()), 4), 'closeSlope': slope, 'coef': round(float(coef), 3),
                              'bySeasonHeldD': {int(s): round(float(e1[held & (S == s)].mean() - e0[held & (S == s)].mean()), 4) for s in range(C.TUNE_END + 1, C.LAST + 1)}}
        if name == 'B1':      # diagnostic: the gain by the home side's games played (a final-rating leak: largest early)
            ng = np.array([x.get('ng', np.nan) if isinstance(x, dict) else np.nan for _, x, _ in D])
            ngi = np.zeros(len(D)); cnt = defaultdict(int)
            for i, (g, _, _) in enumerate(D):
                k_ = (g['season'], g['home']); ngi[i] = cnt[k_]; cnt[k_] += 1
            out['tests'][name]['byGames'] = {f'{a}-{b}': round(float(e1[held & (ngi >= a) & (ngi < b)].mean() - e0[held & (ngi >= a) & (ngi < b)].mean()), 4)
                                             for a, b in ((0, 5), (5, 10), (10, 20), (20, 40))}
        print(name, out['tests'][name], flush=True)
    gate = lambda r, bar: r['tuneT'] <= -1.5 and r['heldT'] <= bar and r['linedD'] <= 0 and (r['closeSlope'] or -1) >= 0
    for name in ('B1', 'B2'):
        out['tests'][name]['passRaw'] = bool(gate(out['tests'][name], -1.96)); out['tests'][name]['pass'] = False   # leak (amendment)
    out['tests']['B3']['pass'] = bool(gate(out['tests']['B3'], -1.96))
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
