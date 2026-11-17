#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pages behind the all-time team and player rankings (scripts/alltime.py). Cache scripts/.cache/alltime (not committed).

    python3 scripts/alltime_pull.py [sr|nfl|tennis|cbbp|all]

  sr      Sports Reference: CBB season ratings 1950-, NBA league + advanced pages 1947-, NHL league, skaters, goalies 1918-
          (one request every 3.6 s, as scripts/coach_alltime_pro.py)
  nfl     FiveThirtyEight nfl-elo-game scores 1920-2019, nflverse nfldata games.csv 1999- and draft_picks (career AV)
  tennis  Sackmann archive (Hugging Face mirror) tour-level singles 1968-
  cbbp    Barttorvik player seasons 2008-
"""
import os, sys, time, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import coach_alltime_pro as cap
CACHE = os.path.join(HERE, '.cache', 'alltime')
cap.CACHE = os.path.join(CACHE, 'sr')
BB, HR, CB = cap.BB, cap.HR, 'https://www.sports-reference.com/cbb'
LAST = 2026
SACK = 'https://huggingface.co/datasets/Aneeshers/tennis-sackmann-archive/resolve/main/'


def sr_urls():
    out = []
    for y in range(LAST, 1946, -1):
        lg = 'BAA' if y <= 1949 else 'NBA'
        out += [f'{BB}/leagues/{lg}_{y}.html', f'{BB}/leagues/{lg}_{y}_advanced.html']
    for y in range(LAST, 1917, -1):
        if y == 2005: continue
        out += [f'{HR}/leagues/NHL_{y}.html', f'{HR}/leagues/NHL_{y}_skaters-misc.html', f'{HR}/leagues/NHL_{y}_goalies.html']
    out += [f'{CB}/seasons/men/{y}-ratings.html' for y in range(LAST, 1949, -1)]
    return out


def dl(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = subprocess.run(['curl', '-sL', '-m', '120', '-A', cap.UA, '-o', path + '.tmp', '-w', '%{http_code}', url], capture_output=True, text=True)
    if r.stdout == '200': os.replace(path + '.tmp', path)
    else:
        print('status', r.stdout, url, flush=True)
        if os.path.exists(path + '.tmp'): os.remove(path + '.tmp')


def nfl():
    dl('https://raw.githubusercontent.com/fivethirtyeight/nfl-elo-game/master/data/nfl_games.csv', os.path.join(CACHE, 'nfl', '538.csv'))
    dl('https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv', os.path.join(CACHE, 'nfl', 'games.csv'))
    dl('https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv', os.path.join(CACHE, 'nfl', 'draft_picks.csv'))


def tennis():
    for y in range(1968, LAST + 1):
        for t in ('atp', 'wta'):
            dl(SACK + f'{t}/{t}_matches_{y}.csv', os.path.join(CACHE, 'tennis', f'{t}_{y}.csv'))
    for t in ('atp', 'wta'): dl(SACK + f'{t}/{t}_players.csv', os.path.join(CACHE, 'tennis', f'{t}_players.csv'))


def cbbp():
    for y in range(2008, LAST + 1):
        dl(f'https://barttorvik.com/getadvstats.php?year={y}&csv=1', os.path.join(CACHE, 'cbbp', f'{y}.csv')); time.sleep(1)


if __name__ == '__main__':
    a = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if a in ('nfl', 'all'): nfl()
    if a in ('tennis', 'all'): tennis()
    if a in ('cbbp', 'all'): cbbp()
    if a in ('sr', 'all'):
        for i, u in enumerate(sr_urls()):
            cap.get(u)
            if i % 25 == 0: print(i, u, flush=True)
