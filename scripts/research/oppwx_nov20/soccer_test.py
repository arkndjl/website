# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer: opponent (and home) adjustment of the per-match inputs of GAR (scripts/soccer_players.py), Nov 20 2026.

    python3 scripts/research/oppwx_nov20/soccer_test.py     # needs the Understat match cache (soccer_data.py usm)

Inputs per player-match: on-pitch team xG for (onf) and against (ona, signed so fewer = higher), own non-penalty xG
(npxg), xA (xas), xGBuildup (bup). Opponent = what that club allowed (per player-minute, by position class for the
own-production rates) in its other league matches that season (oppadj.py). Tune 2015-21, held 2022-26.
"""
import json, os, sys, pickle
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import oppadj as OA
import soccer_data as D
import soccer_players as SP

PK = '/tmp/claude-0/ow/soccer_rows.pkl'
if os.path.exists(PK):
    R = pickle.load(open(PK, 'rb'))
else:
    R = []
    for S in range(2015, 2027):
        for lg in D.BIG5:
            d = D.us_league(lg, S)
            if not d: continue
            for mt in d['matches']:
                if not mt['res']: continue
                m = D.us_match(mt['id'])
                if not m: continue
                pens = SP.penalties(m)
                for r in SP.parse_match(m, lg, S, mt['id']):
                    tid = mt['hid'] if r['side'] == 'h' else mt['aid']
                    opp = mt['aid'] if r['side'] == 'h' else mt['hid']
                    R.append((lg, S, mt['id'], mt['t'], r['p'], tid, opp, r['min'], r['side'] == 'h', SP.POS.get(r['pos'], 'S'),
                              r['xf'], -r['xa'], r['x'] - pens.get(r['p'], 0.0), r['xA'], r['bu']))
        print(S, len(R), flush=True)
    pickle.dump(R, open(PK, 'wb'))
MET = {'onf': 10, 'ona': 11, 'npxg': 12, 'xas': 13, 'bup': 14}
out = {}
for nm, ix in MET.items():
    # season key = (league, season) so the league rate is the league-season's; unit = player at club
    rows = [((r[0], r[1]), r[2], r[3], (r[4], r[5]), r[6], r[7], r[ix], r[8], r[9]) for r in R]
    by = (lambda r: r[8]) if nm in ('npxg', 'xas', 'bup') else None
    raw = np.array([r[6] for r in rows])
    res = {}
    for part, seas in (('tune', range(2015, 2022)), ('held', range(2022, 2027))):
        ss = {(lg, S) for lg in D.BIG5 for S in seas}
        V = {'raw': raw, 'home': OA.home_adjust(rows, by)}
        for K in (0, 2000, 5000, 10000):
            V[f'opp K{K}'] = OA.adjust(rows, K, 1.0, by)
            V[f'opp+home K{K}'] = OA.adjust(rows, K, 1.0, by, home=True)
        V['opp+home K5000 c.5'] = OA.adjust(rows, 5000, 0.5, by, home=True)
        res[part] = {'split900': OA.split(rows, V, 900, 300, ss), 'split300': OA.split(rows, V, 300, 100, ss),
                     'ahead33': OA.ahead(rows, V, 600, 150, 1 / 3, ss), 'ahead50': OA.ahead(rows, V, 600, 200, 0.5, ss)}
        for k, v in res[part].items():
            print(nm, part, k, 'n', v['n'])
            for a, o in v.items():
                if a != 'n': print('   ', a, o)
        sys.stdout.flush()
    out[nm] = res
json.dump(out, open(os.path.join(HERE, 'soccer_results.json'), 'w'), indent=1)
