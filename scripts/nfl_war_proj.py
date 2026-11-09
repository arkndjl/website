#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Next-season and next-three-seasons WAR on the NFL WAR board (rows' p1, p3), stdlib, called by scripts/nfl_war.py's build.

Fit and test: scripts/nfl_war_proj_research.py -> data/nfl_war_proj_fit.json. Inputs per player, on a 17-game scale:
this season's WAR and snaps pace (pre special teams, x 17 / team games), the last two seasons' WAR and snaps
(scripts/data/pctl_hist_nfl.json.gz, written by player_pctl.py --fit, which rolls forward after each season), age on
Sept 1 and position group. Coefficients per share of the season played (f = team games / 17), linear in between.
Kickers and punters get none; a season whose last season is not in the history file gets none.
"""
import gzip
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIT = os.path.join(ROOT, 'data', 'nfl_war_proj_fit.json')
HIST = os.path.join(HERE, 'data', 'pctl_hist_nfl.json.gz')
GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB']
A0 = 27


def feats(form, g, W0, W1, W2, h1, h2, s0, s1, a):
    """the projection's inputs (forms in scripts/nfl_war_proj_research.py): group intercepts, WAR this season and the
    two before, whether he played them, log snaps this season and last; B a pooled age curve; C / D a curve per group
    (years past 27 and under it, and years past 27 x this season's WAR); D also this season's WAR by group"""
    x = [1.0 if g == G else 0.0 for G in GROUPS] + [W0, W1, W2, h1, h2, math.log1p(s0), math.log1p(s1)]
    if form == 'B':
        x += [max(0.0, a - 29), max(0.0, 25 - a), W0 * max(0.0, a - 29)]
    if form in ('C', 'D'):
        for G in GROUPS:
            d = 1.0 if g == G else 0.0
            x += [d * max(0.0, a - A0), d * max(0.0, A0 - a), d * W0 * max(0.0, a - A0)]
    if form == 'D':
        x += [(1.0 if g == G else 0.0) * W0 for G in GROUPS]
    return x


def coefs(grid, f, key):
    f = min(max(f, grid[0]['f']), 1.0)
    for a, b in zip(grid, grid[1:]):
        if f <= b['f']:
            w = (f - a['f']) / (b['f'] - a['f'])
            return [u + (v - u) * w for u, v in zip(a[key], b[key])]
    return grid[-1][key]


def attach(out, y, teamg):
    """add p1 (next season's WAR) and p3 (the next three seasons') to the board rows out (season y, before publish);
    teamg: {team: games played this season}"""
    try:
        fit = json.load(open(FIT))
        with gzip.open(HIST, 'rt') as f:
            H = json.load(f)
    except (OSError, ValueError) as e:
        return print(f'nfl war: projections skipped ({e!r})')
    if not fit.get('kept') or str(y - 1) not in H:
        return print('nfl war: projections skipped (no fit or no history for last season)')
    grid, form = fit['grid'], fit['form']

    def past(S, pid):
        h = H.get(str(S), {}).get(pid)
        if not h or not h.get('tl'):
            return 0.0, 0.0, 0.0
        return h['x'].get('war', 0.0) * 17 / h['tl'], h['e'] * 17 / h['tl'], 1.0

    n = 0
    for p in out:
        g, a = p.get('_g'), p.get('ax') or p.get('age')
        tg = teamg.get(p['t'], 0)
        if g not in GROUPS or a is None or tg <= 0:
            continue
        f = min(1.0, tg / 17)
        W0 = (p['_war'] - (p.get('stw') or 0.0)) * 17 / tg   # the fit is on WAR before special teams
        s0 = p['sn'] * 17 / tg
        W1, s1, h1 = past(y - 1, p['id'])
        W2, _, h2 = past(y - 2, p['id'])
        x = feats(form, g, W0, W1, W2, h1, h2, s0, s1, a)
        for k, key in (('p1', 'y1c'), ('p3', 'y3c')):
            p[k] = round(sum(c * v for c, v in zip(coefs(grid, f, key), x)), 2)
        n += 1
    print(f'nfl war: projections for {n} players')
