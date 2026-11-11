#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL rate metric on the WAR board (stdlib, called by scripts/nfl_war.py's build). Fit: scripts/nfl_rate_research.py.

Rows get
    xp    rXP/60: points of margin over an average regular at his sub-position per 60 scrimmage snaps, this season
          ((WAA - special teams WAR) x 35.5 / snaps x 60)
    pxp   pXP/60: the rate that carries forward (data/nfl_rate_fit.json form: seasons S to date, S-1, S-2 at snap weights
          1 / .7 / .5, shrunk to a prior by K snaps per group; the prior is the sub-position mean moved by playing time)
    q     1 when qualified: 40% of his team's snaps on his side so far (the XV regular line)
"""
import gzip
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIT = os.path.join(ROOT, 'data', 'nfl_rate_fit.json')
HIST = os.path.join(HERE, 'data', 'nfl_rate_hist.json.gz')
PTS_PER_WIN = 35.5
PER = 60
QUAL = 0.4
MARCEL = (1.0, 0.7, 0.5)
GROUPS = ('QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB')


def row_of(p):
    """the rate inputs of one board row (None for specialists and rows without a sub-position)"""
    if p.get('_sub') is None or p.get('_g') not in GROUPS or p.get('waa') is None or p['sn'] <= 0:
        return None
    waa = p['_war'] - (p.get('stw') or 0.0) - p['_avg']
    tg = max(1, p.get('_tg') or 17)
    return {'id': p['id'], 'sub': p['_sub'], 'grp': p['_g'], 'sn': p['sn'], 'pts': waa * PTS_PER_WIN,
            'shr': p['sh'] * 17 / tg, 'age': p.get('ax') or p.get('age')}


def rate(r):
    return r['pts'] / r['sn'] * PER if r['sn'] else 0.0


def attach(out, y):
    try:
        fit = json.load(open(FIT))
        with gzip.open(HIST, 'rt') as f:
            H = json.load(f)
    except (OSError, ValueError) as e:
        return print(f'nfl war: rate skipped ({e!r})')
    M = fit['model']
    use = fit.get('kept')
    n = 0
    for p in out:
        r = row_of(p)
        if not r:
            continue
        p['xp'] = round(rate(r), 2)
        if r['shr'] >= QUAL:
            p['q'] = 1
        if not use:
            continue
        g = r['grp']
        prior = M['m'].get(r['sub'], 0.0)
        if fit['form'] in ('marcelP', 'marcelA'):
            prior += M['b'].get(g, 0.0) * (r['shr'] - M['xb'].get(g, 0.0))
        P, S = r['pts'] * PER, r['sn']
        if fit['form'] != 'shrink1':
            for i, w in enumerate(M['marcel'][1:], 1):
                h = H.get(str(y - i), {}).get(p['id'])
                if h and h[2] == g:
                    P += w * h[1] * PER; S += w * h[0]
        k = M['K'][g]
        v = (P + k * prior) / (S + k)
        if fit['form'] == 'marcelA' and r['age'] is not None:
            c = M['age'].get(g, (0.0, 0.0))
            v += c[0] * max(0.0, r['age'] - 27) + c[1] * max(0.0, 27 - r['age'])
        p['pxp'] = round(v, 2)
        n += 1
    print(f'nfl war: rate for {n} players')
