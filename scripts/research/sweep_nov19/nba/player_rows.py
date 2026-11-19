# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The shipped player walk's rows (nba_players.collect with the fit's play calibration), pickled for the sweep tests.

    python3 player_rows.py OUT.pkl"""
import json, pickle, sys
import common as C
import nba_players as NP
import nba_games as N

F = json.load(open(NP.FIT))
NP.PCAL = F['pcal']
rows = NP.collect()
G, names = N.load_hist()
tip = {g['id']: g['tip'] for g in G}
num, seen = {}, {}
for g in G:
    for t in (g['h'], g['a']):
        k = (g['S'], t)
        if g.get('t') == 2 or g.get('t') is None:
            seen[k] = seen.get(k, 0) + 1
        num[(g['id'], t)] = seen.get(k, 0)
for r in rows:
    r['tip'] = tip[r['g']]; r['gn'] = num[(r['g'], r['t'])]
pickle.dump({'rows': rows, 'names': names, 'feats': {s: F['stats'][s]['feats'] for s in F['stats'] if 'feats' in F['stats'][s]}}, open(sys.argv[1], 'wb'))
print(len(rows), 'rows')
