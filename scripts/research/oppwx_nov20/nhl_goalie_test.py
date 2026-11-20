# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL goalies: opponent adjustment of GSAx (goals saved above expected), Nov 20 2026.

    python3 scripts/research/oppwx_nov20/nhl_goalie_test.py

A goalie-game row = the xG he faced (exposure) and xG - goals against (value), from scripts/nhl_games_hist.json.gz
(gl, gx). Opponent = how the goalies facing that team did per xG in its other games (the team's finishing, sign
flipped), shrunk (oppadj.py). Regular season. Tune 2011-18, held 2019-26.
"""
import gzip, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import oppadj as OA
hist = json.load(gzip.open(os.path.join(HERE, '..', '..', 'nhl_games_hist.json.gz')))
rows = []
for g in hist:
    if g.get('po') or not g.get('final') or 'gx' not in g: continue
    for s, o in (('h', 'a'), ('a', 'h')):
        for gl in g['gl'].get(s, []):
            x = g['gx'].get(s, {}).get(str(gl[0]))
            if x is None or x <= 0: continue
            rows.append((g['S'], g['id'], g['day'], gl[0], g[o], x, x - gl[5], s == 'h'))
print(len(rows), 'goalie-games', min(r[0] for r in rows), max(r[0] for r in rows))
raw = np.array([r[6] for r in rows])
out = {}
for part, seas in (('tune', set(range(2011, 2019))), ('held', set(range(2019, 2027)))):
    V = {'raw': raw, 'home': OA.home_adjust(rows)}
    for K in (0, 50, 100, 200, 400):
        for c in (0.5, 1.0):
            V[f'opp K{K} c{c}'] = OA.adjust(rows, K, c)
    V['opp+home K100 c1.0'] = OA.adjust(rows, 100, 1.0, home=True)
    out[part] = {'split60': OA.split(rows, V, 60, 20, seas), 'split25': OA.split(rows, V, 25, 8, seas),
                 'ahead50': OA.ahead(rows, V, 60, 20, 0.5, seas), 'ahead33': OA.ahead(rows, V, 60, 15, 1 / 3, seas)}
    for k, v in out[part].items():
        print(part, k, 'n', v['n'])
        for a, o in v.items():
            if a != 'n': print('   ', a, o)
json.dump(out, open(os.path.join(HERE, 'nhl_goalie_results.json'), 'w'), indent=1)
