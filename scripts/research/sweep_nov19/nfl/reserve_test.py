#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Reserve-list return hazard by list code and weeks served (PREREG.md lead 2, tests R1 and R2).

    python3 reserve_test.py <out json>

rows(): one row a player-week on a reserve list: (season, week, team, gsis, code, served, [miss_1..miss_4])."""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import nfl_games as N  # noqa: E402

RESERVE = {'RES', 'PUP', 'NWT', 'RSN', 'SUS', 'EXE'}
CODES = {'R01': 'R01', 'R48': 'R48', 'R04': 'R04', 'R05': 'R05', 'R06': 'R05', 'R27': 'other', 'R40': 'other', 'R30': 'other',
         'R33': 'other', 'W03': 'other'}
MAXJ = 4
M = 40.0


def bucket(served):
    return '0' if served <= 1 else '1-3' if served <= 4 else '4-7' if served <= 8 else '8+'


def rows(games, y, maxj=MAXJ):
    sch = defaultdict(set)
    for g in games:
        if int(g['season']) == y and g['game_type'] == 'REG':
            sch[N.team(g['home_team'])].add(int(g['week'])); sch[N.team(g['away_team'])].add(int(g['week']))
    sch = {t: sorted(v) for t, v in sch.items()}
    ros = {}
    for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv')):
        if r.get('game_type', 'REG') == 'REG' and r['gsis_id'] and r['week'] not in ('', 'NA'):
            ros[(int(r['week']), r['gsis_id'])] = (N.team(r['team']), r['status'], r.get('status_description_abbr', ''), r['position'])
    served = {}
    out = []
    for (w, gsis), (t, st, code, pos) in sorted(ros.items()):
        if st not in RESERVE:
            served.pop(gsis, None)
            continue
        p = served.get(gsis)
        n = p[2] + 1 if p and p[0] == w - 1 and p[1] == t else 1
        served[gsis] = (w, t, n)
        if w not in sch.get(t, ()):
            continue
        o = []
        for x in [x for x in sch[t] if x > w][:maxj]:
            tt, s2 = ros.get((x, gsis), (None, None, None, None))[:2]
            if tt != t or s2 not in ({'ACT', 'INA'} | RESERVE):
                break
            o.append(0 if s2 == 'ACT' else 1)
        if o:
            out.append((y, w, t, gsis, CODES.get(code, 'none'), n, o, pos))
    return out


def fit(R, use_code, use_bucket, maxj=MAXJ):
    """nested tables: j -> code x j -> code x bucket x j, each shrunk to its parent with M pseudo-rows"""
    c = defaultdict(lambda: np.zeros((2, maxj)))
    for r in R:
        o = r[6]
        for k in (('j',), ('c', r[4]), ('cb', r[4], bucket(r[5])), ('b', bucket(r[5]))):
            c[k][0, :len(o)] += o; c[k][1, :len(o)] += 1
    base = (c[('j',)][0] + 0.5) / (c[('j',)][1] + 1)
    tab = {'j': base}
    for k, v in c.items():
        if k[0] == 'c':
            tab[k] = (v[0] + M * base) / (v[1] + M)
        if k[0] == 'b':
            tab[k] = (v[0] + M * base) / (v[1] + M)
    for k, v in c.items():
        if k[0] == 'cb':
            par = tab.get(('c', k[1]), base)
            tab[k] = (v[0] + M * par) / (v[1] + M)
    return tab


def prob(tab, r, mode, j):
    if mode == 'j':
        v = tab['j']
    elif mode == 'b':
        v = tab.get(('b', bucket(r[5])), tab['j'])
    else:
        v = tab.get(('cb', r[4], bucket(r[5])), tab.get(('c', r[4]), tab['j']))
    return float(v[j])


def score(train, test, mode):
    tab = fit(train, True, True)
    d, cl, ss = [], [], []
    for r in test:
        for j, m in enumerate(r[6]):
            e = []
            for md in ('j', mode):
                p = min(max(prob(tab, r, md, j), 1e-3), 1 - 1e-3)
                e.append(-(m * math.log(p) + (1 - m) * math.log(1 - p)))
            d.append((e[0], e[1])); cl.append(r[0] * 100 + r[1]); ss.append(r[0])
    return np.array(d), np.array(cl), np.array(ss)


def tclus(d, cl):
    u = np.unique(cl)
    s = np.array([d[cl == k].sum() for k in u]); n = np.array([(cl == k).sum() for k in u])
    m = d.mean()
    se = math.sqrt(((s - m * n) ** 2).sum() * len(u) / (len(u) - 1)) / len(d)
    return m / se


def report(E, fit_y, held_y, mode):
    tr = [r for y in fit_y for r in E[y]]
    te = [r for y in held_y for r in E[y]]
    d, cl, ss = score(tr, te, mode)
    dd = d[:, 1] - d[:, 0]
    by = {int(y): round(float(dd[ss == y].mean()), 4) for y in held_y}
    # tune sign: leave one season out inside the fit seasons
    lo = []
    for y in fit_y:
        a, c2, _ = score([r for yy in fit_y if yy != y for r in E[yy]], E[y], mode)
        lo.append((a[:, 1] - a[:, 0], c2))
    td = np.concatenate([x[0] for x in lo]); tc = np.concatenate([x[1] for x in lo])
    return {'fit': f'{fit_y[0]}-{fit_y[-1]}', 'held': f'{held_y[0]}-{held_y[-1]}', 'n': int(len(dd)), 'rows': len(te),
            'llBase': round(float(d[:, 0].mean()), 4), 'llNew': round(float(d[:, 1].mean()), 4), 'd': round(float(dd.mean()), 4),
            't': round(float(tclus(dd, cl)), 2), 'bySeason': by, 'tuneD': round(float(td.mean()), 4), 'tuneT': round(float(tclus(td, tc)), 2)}


def main():
    games = list(N.rows(N.get('games.csv', N.GAMES)))
    E = {y: rows(games, y) for y in range(2016, 2026)}
    print({y: len(v) for y, v in E.items()})
    out = {'R1': report(E, list(range(2016, 2021)), list(range(2021, 2026)), 'b'),
           'R2': report(E, [2020, 2021, 2022], [2023, 2024, 2025], 'cb')}
    tab = fit([r for y in range(2021, 2026) for r in E[y]], True, True, 12) if False else None
    print(json.dumps(out, indent=1))
    json.dump(out, open(sys.argv[1], 'w'), indent=1)


if __name__ == '__main__':
    main()
