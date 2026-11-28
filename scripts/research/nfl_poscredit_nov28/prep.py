# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL position credit (Nov 28 2026): replay the WAR board for 2016-25 and keep each player's team, group, snaps and
points over an average regular (no special teams), plus each team's regular-season point margin a game.
python3 scripts/research/nfl_poscredit_nov28/prep.py -> scripts/.cache/nfl/poscredit_<y>.json"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import nfl_war as W
import nfl_rate as R

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl'); os.makedirs(CACHE, exist_ok=True)


def margins(y):
    m = {}
    for g in W.rows(W.get('games.csv', W.GAMES)):
        if g['season'] != str(y) or g['game_type'] != 'REG' or not g.get('home_score'): continue
        h, a, d = g['home_team'], g['away_team'], float(g['home_score']) - float(g['away_score'])
        for t, v in ((h, d), (a, -d)):
            s = m.setdefault(t, [0.0, 0]); s[0] += v; s[1] += 1
    return {t: v[0] / v[1] for t, v in m.items()}


for y in [int(a) for a in sys.argv[1:]] or range(2016, 2026):
    fn = os.path.join(CACHE, f'poscredit_{y}.json')
    if os.path.exists(fn): print(y, 'cached'); continue
    out, _, _ = W.board(y)
    rows = []
    for p in out:
        r = R.row_of(p)
        if r: rows.append(dict(r, tm=p.get('tm') or p.get('t')))
    json.dump({'rows': rows, 'margin': margins(y)}, open(fn, 'w'))
    print(y, len(rows), flush=True)
