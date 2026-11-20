# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA: opponent adjustment of the per-game box value (box XPM, scripts/nba_inseason.py), Nov 20 2026.

    python3 scripts/research/oppwx_nov20/nba_test.py      # needs scripts/nba_box_hist.json.gz (nba_inseason.py --pull)

Game value = the box-XPM weights (fit on the seasons before) on the game's box line over the league's rates, so a
player's season rate is his box XPM. Two forms: with the on-court plus-minus term (the in-season value) and box only.
Opponent = what that team allowed opposing players per minute in its other games (oppadj.py). Tune 2015-21, held 2022-26.
"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import oppadj as OA
import nba_inseason as I

games, names = I._hist()
bx = I.load_box()
COLS = I.COLS
out = {}
for form in ('pm', 'box'):
    rows = []
    for S in range(2015, 2027):
        b = I.coef(S).copy()
        if form == 'box':
            b[I.RATES.index('pm')] = 0.0
        sl = I.season_lines(S); lg = I.league(sl); lgr = lg[I.IX] / lg[0]
        for g in games:
            if g['S'] != S or g['t'] != 2 or g['id'] not in bx:
                continue
            tm = list(bx[g['id']])
            if len(tm) != 2:
                continue
            for t in tm:
                opp = tm[1 - tm.index(t)]
                for r in bx[g['id']][t]:
                    v = np.array(r[1:], float)
                    if not r[0] or v[0] <= 0:
                        continue
                    val = float(((v[I.IX] - lgr * v[0]) * 48.0) @ b[:-1])
                    rows.append((S, g['id'], g['tip'], r[0], opp, v[0], val, t == g['h']))
    print(form, 'rows', len(rows), flush=True)
    raw = np.array([r[6] for r in rows])
    res = {}
    for nm, seas in (('tune', set(range(2015, 2022))), ('held', set(range(2022, 2027)))):
        V = {'raw': raw}
        for K in (0, 1200, 2400, 4800, 9600):
            for c in (0.5, 1.0):
                V[f'opp K{K} c{c}'] = OA.adjust(rows, K, c)
        res[nm] = {'split1000': OA.split(rows, V, 1000, 300, seas), 'split300': OA.split(rows, V, 300, 100, seas),
                   'ahead25': OA.ahead(rows, V, 500, 100, 0.25, seas), 'ahead50': OA.ahead(rows, V, 500, 150, 0.5, seas)}
        for k, v in res[nm].items():
            print(form, nm, k, 'n', v['n'])
            for a, o in v.items():
                if a != 'n': print('   ', a, o)
    out[form] = res
json.dump(out, open(os.path.join(HERE, 'nba_results.json'), 'w'), indent=1)
