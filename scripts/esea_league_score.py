#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Scores the league-wide forward log of the 1NT preview model (scripts/esea_league_log.mjs).

    python3 scripts/esea_league_score.py    # scripts/data/esea_league_log.jsonl -> data/esea_league_log.json

A line counts when it was logged before the match started, the match was played (not a forfeit) and has a winner.
Log loss and Brier for faction1's win chance against a coin flip, calibration by tenth of the favourite's chance,
and by match day, division and model version. Forward numbers only: nothing here is fit."""
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, 'scripts', 'data', 'esea_league_log.jsonl')
OUT = os.path.join(ROOT, 'data', 'esea_league_log.json')


def read(path=LOG):
    try:
        return list({l['id']: l for l in (json.loads(x) for x in open(path) if x.strip())}.values())   # a repeated id: the last line stands
    except FileNotFoundError:
        return []


def scored(l):
    r = l.get('res')
    return bool(r and r.get('w') in (0, 1) and not l.get('void') and r.get('maps') != 0 and l.get('p') is not None)


def summary(rows):
    n = len(rows)
    if not n:
        return {'n': 0, 'll': None, 'brier': None, 'hit': None, 'fav': None}
    ll = lambda p, y: -(y * math.log(max(1e-6, p)) + (1 - y) * math.log(max(1e-6, 1 - p)))
    return {'n': n, 'll': round(sum(ll(l['p'], l['res']['w']) for l in rows) / n, 4),
            'brier': round(sum((l['p'] - l['res']['w']) ** 2 for l in rows) / n, 4),
            'hit': round(sum((l['p'] >= 0.5) == (l['res']['w'] == 1) for l in rows) / n, 4),
            'fav': round(sum(max(l['p'], 1 - l['p']) for l in rows) / n, 4)}


def build(lines):
    ok = [l for l in lines if scored(l)]
    res = {'lines': len(lines), 'pending': sum(1 for l in lines if not l.get('res')), 'void': sum(1 for l in lines if l.get('void')),
           'forfeit': sum(1 for l in lines if (l.get('res') or {}).get('maps') == 0), 'coin': {'ll': round(math.log(2), 4), 'brier': 0.25},
           'all': summary(ok)}
    # calibration: the favourite's chance in tenths from .5 (each match once)
    bins = []
    for lo in (0.5, 0.6, 0.7, 0.8, 0.9):
        rs = [l for l in ok if lo <= max(l['p'], 1 - l['p']) < lo + 0.1 or (lo == 0.9 and max(l['p'], 1 - l['p']) == 1)]
        bins.append({'lo': lo, 'hi': round(lo + 0.1, 1), 'n': len(rs), 'p': round(sum(max(l['p'], 1 - l['p']) for l in rs) / len(rs), 4) if rs else None,
                     'won': round(sum((l['p'] >= 0.5) == (l['res']['w'] == 1) for l in rs) / len(rs), 4) if rs else None})
    res['calibration'] = bins
    by = defaultdict(list)
    for l in ok:
        by[dt.datetime.fromtimestamp(l['res'].get('started') or l['at'], dt.timezone.utc).strftime('%Y-%m-%d')].append(l)
    res['days'] = [{'day': d, **summary(rs)} for d, rs in sorted(by.items())]
    for key, name in (('div', 'by_div'), ('v', 'by_version')):
        g = defaultdict(list)
        for l in ok:
            g[l.get(key) or '?'].append(l)
        res[name] = {k: summary(v) for k, v in sorted(g.items())}
    return res


def test():
    mk = lambda p, w, **kw: {'id': str(p), 'div': 'main', 'v': 'x', 'at': 86400 * 3, 'p': p, 'res': {'w': w, 'started': 86400 * 3, 'maps': 1}, **kw}
    L = [mk(0.8, 1), mk(0.3, 0), mk(0.6, 0), mk(0.9, 1, void='late'), {'id': 'p', 'p': 0.5, 'res': None}, {**mk(0.7, 1), 'res': {'w': 1, 'maps': 0}}]
    r = build(L)
    assert r['all']['n'] == 3 and r['pending'] == 1 and r['void'] == 1 and r['forfeit'] == 1, r
    assert abs(r['all']['brier'] - (0.04 + 0.09 + 0.36) / 3) < 1e-4 and r['all']['hit'] == round(2 / 3, 4)
    assert [b['n'] for b in r['calibration']] == [0, 1, 1, 1, 0] and r['days'][0]['day'] == '1970-01-04'
    assert build([])['all']['n'] == 0
    print('esea_league_score: ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
    else:
        out = build(read())
        json.dump(out, open(OUT, 'w'), indent=1)
        print('league log:', out['all'], 'pending', out['pending'])
