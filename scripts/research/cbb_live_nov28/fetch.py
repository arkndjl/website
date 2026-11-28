#!/usr/bin/env python3
"""Barttorvik game logs, season files and conference-only season files (conyes=1), 2009-10 to 2026-27, into
scripts/.cache/cbb (not committed). The conference-only file is Barttorvik's own line on a known subset of a player's
games: the only past-season stand-in for his file on part of a season."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import cbb_data as D

for y in [2027] + list(range(2010, 2027)):
    g = os.path.join(D.CACHE, 'games', f'{y}.json.gz')
    a = os.path.join(D.CACHE, 'bt', f'adv{y}.csv')
    c = os.path.join(D.CACHE, 'bt', f'conf{y}.csv')
    if not os.path.exists(g) or os.path.getsize(g) < 10000:
        D.fetch(f'https://barttorvik.com/{y}_all_advgames.json.gz', g, 1, binary=True)
    if not os.path.exists(a) or os.path.getsize(a) < 1000:
        D.fetch(f'https://barttorvik.com/getadvstats.php?year={y}&csv=1', a, 1)
    if y < 2027 and (not os.path.exists(c) or os.path.getsize(c) < 1000):
        D.fetch(f'https://barttorvik.com/getadvstats.php?year={y}&csv=1&conyes=1', c, 1)
    print(y, os.path.getsize(g), os.path.getsize(a), os.path.getsize(c) if os.path.exists(c) else 0, flush=True)
