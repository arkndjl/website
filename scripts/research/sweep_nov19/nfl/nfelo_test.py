#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""nfelo tests (PREREG.md lead 3): N1 open-line parity and 2022 coverage, N2 the public-model stack.

    python3 nfelo_test.py <dir with historic_projected_spreads.csv, nfelo_games.csv> <out json>"""
import csv
import gzip
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
WF = os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'nfl.json.gz')


def tclus(d, cl):
    u = np.unique(cl)
    s = np.array([d[cl == k].sum() for k in u]); n = np.array([(cl == k).sum() for k in u])
    m = d.mean()
    return m / (math.sqrt(((s - m * n) ** 2).sum() * len(u) / (len(u) - 1)) / len(d))


FR = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA'}


def gkey(gid):
    """season_week_away_home with each club on one franchise code (nfelo: LAR, OAK; nflverse: LA, LV and the old cities)"""
    s, w, a, h = gid.split('_')
    return f'{s}_{w}_{FR.get(a, a)}_{FR.get(h, h)}'


def main():
    src, out = sys.argv[1], sys.argv[2]
    rows = [g for g in json.load(gzip.open(WF)) if g['S'] <= 2025]
    by = {gkey(g['id']): g for g in rows}
    ng = {gkey(r['game_id']): r for r in csv.DictReader(open(os.path.join(src, 'nfelo_games.csv')))}
    # N1
    res = {}
    gaps = []
    for g in rows:
        n = ng.get(gkey(g['id']))
        if not n or n['home_line_open'] in ('', 'nan') or g.get('Lo') is None or g.get('Los') is None or g['po']:
            continue
        gaps.append((g['S'], -float(n['home_line_open']) - g['Lo'], g['Los']))
    G = np.array([x[1] for x in gaps])
    reg22 = [g for g in rows if g['S'] == 2022 and not g['po']]
    cov = sum(1 for g in reg22 if ng.get(gkey(g['id']), {}).get('home_line_open', '') not in ('', 'nan'))
    res['N1'] = {'n': len(G), 'meanGap': round(float(G.mean()), 3), 'mae': round(float(np.abs(G).mean()), 3),
                 'exact': round(float((G == 0).mean()), 3),
                 'bySource': {s: {'n': sum(1 for x in gaps if x[2] == s), 'mae': round(float(np.mean([abs(x[1]) for x in gaps if x[2] == s])), 3),
                                  'mean': round(float(np.mean([x[1] for x in gaps if x[2] == s])), 3)} for s in sorted({x[2] for x in gaps})},
                 'cov2022': [cov, len(reg22)]}
    res['N1']['pass'] = bool(abs(G.mean()) <= 0.15 and np.abs(G).mean() <= 0.85 and cov >= 0.95 * len(reg22))
    # N2
    led = {}
    for r in csv.DictReader(open(os.path.join(src, 'historic_projected_spreads.csv'))):
        if r['home_line_pre_regression'] not in ('', 'nan'):
            led[gkey(r['game_id'])] = (int(r['season']), int(r['week']), -float(r['home_line_pre_regression']))
    D = []
    for gid, (s, w, x) in led.items():
        g = by.get(gid)
        if g and g.get('res') is not None and g.get('m') is not None and g['wk'] == w and g['S'] == s:
            D.append((s, w, g['m'], x, g['res'], g.get('L')))
    D = np.array([[np.nan if v is None else v for v in r] for r in D], float)
    S = D[:, 0]
    res['N2'] = {'n': len(D), 'rNfeloResult': round(float(np.corrcoef(D[:, 3], D[:, 4])[0, 1]), 3),
                 'rNfeloModel': round(float(np.corrcoef(D[:, 3], D[:, 2])[0, 1]), 3)}
    e0 = np.full(len(D), np.nan); e1 = np.full(len(D), np.nan); en = np.abs(D[:, 3] - D[:, 4])
    W = {}
    for s in range(2022, 2026):
        tr, te = S < s, S == s
        b = np.linalg.lstsq(D[tr][:, 2:4], D[tr, 4], rcond=None)[0]
        W[s] = [round(float(v), 3) for v in b]
        e0[te] = np.abs(D[te, 2] - D[te, 4]); e1[te] = np.abs(D[te][:, 2:4] @ b - D[te, 4])
    for lab, ys in (('tune 2022-23', (2022, 2023)), ('held 2024-25', (2024, 2025))):
        k = np.isin(S, ys); d = e1[k] - e0[k]
        res['N2'][lab] = {'n': int(k.sum()), 'maeModel': round(float(e0[k].mean()), 3), 'maeStack': round(float(e1[k].mean()), 3),
                          'maeNfelo': round(float(en[k].mean()), 3),
                          'maeClose': round(float(np.nanmean(np.abs(D[k, 5] - D[k, 4]))), 3),
                          'd': round(float(d.mean()), 4), 't': round(float(tclus(d, (S[k] * 100 + D[k, 1]).astype(int))), 2),
                          'bySeason': {int(y): round(float((e1 - e0)[S == y].mean()), 4) for y in ys}}
    res['N2']['weights'] = W
    print(json.dumps(res, indent=1))
    json.dump(res, open(out, 'w'), indent=1)


if __name__ == '__main__':
    main()
