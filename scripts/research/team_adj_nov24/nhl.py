#!/usr/bin/env python3
"""NHL descriptive WAR (dr, goals a 60 over average) with the team adjustment to actual goal differential.
Exposure = ice time (hours) per team stint (stats-API game-log split, as nhl_players.describe_split); result = regular
season GD (shootout goal removed). Pairs 2009-10 ... 2025-26."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import core, nhl_players as P

D = {}
for S in range(P.FIRST, 2027):
    sk, gk = P.skaters(S), P.goalies(S)
    parts = P.describe_split(S, sk, gk, P.pen_value(S), P.team_split(S))
    res = P.team_results(S)
    D[S] = {'parts': [(x['id'], x['tm'], x['toi'] / 3600) for x in parts], 'val': {r['id']: r['dr'] for r in sk + gk},
            'team': {t: (gd * gp, gp) for t, (gd, ppg, gp) in res.items()}, 'grp': {r['id']: r['pos'] for r in sk + gk}}
    print(S, len(sk) + len(gk), flush=True)
out = {'metric': 'descriptive WAR (goals a 60 over average)'}
out.update(core.run(D, list(range(P.FIRST, 2026)), 300 / 60, 500 / 60, 'nhl'))
out['note'] = 'all players shift by one amount a 60 (skaters and goalies), as BPM'
json.dump(out, open(os.path.join(HERE, 'nhl.json'), 'w'), indent=1)
