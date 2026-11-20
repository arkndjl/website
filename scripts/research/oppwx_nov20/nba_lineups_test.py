# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA lineups / on-off: opponent adjustment of Net (points per 100 possessions), Nov 20 2026.

    python3 scripts/nba_lineups.py --pull 2023 2026 && python3 scripts/research/oppwx_nov20/nba_lineups_test.py

A unit's game row = its possessions and net points in that game; opponent = the net that team allowed per possession in
its other games (its own net rating, sign flipped), shrunk (oppadj.py). Fives, trios, pairs, a player's on-court net and
his on-off. Tune 2023-24, held 2025-26, regular season.
"""
import itertools, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import oppadj as OA
import nba_lineups as L

def rows_for(size):
    rows = []
    off = []
    for S in (2023, 2024, 2025, 2026):
        gs, res = L.season(S)
        for g in gs:
            r = res.get(g['id'])
            if not r or g.get('t', 2) != 2: continue
            acc = defaultdict(lambda: [0.0, 0.0]); tt = defaultdict(lambda: [0.0, 0.0])
            for h5, a5, sec, hp, ap, ph, pa, *_ in r['st']:
                poss = (ph + pa) / 2
                for t, o, five, pf, pg in ((r['h'], r['a'], h5, hp, ap), (r['a'], r['h'], a5, ap, hp)):
                    if len(five) != 5: continue
                    tt[(t, o)][0] += poss; tt[(t, o)][1] += pf - pg
                    for u in ([tuple(sorted(five))] if size == 5 else itertools.combinations(sorted(five), size)):
                        a = acc[(t, o, u)]; a[0] += poss; a[1] += pf - pg
            for (t, o, u), (p, n) in acc.items():
                if p > 0:
                    rows.append((S, g['id'], g['tip'], (t, u), o, p, n, t == r['h']))
                    if size == 1:
                        T = tt[(t, o)]
                        off.append((T[0] - p, T[1] - n))
    return rows, off

out = {}
for size, MIN, MINH in ((5, 300, 100), (3, 1500, 500), (2, 2500, 800), (1, 2500, 800)):
    rows, off = rows_for(size)
    raw = np.array([r[6] for r in rows])
    res = {}
    for part, seas in (('tune', {2023, 2024}), ('held', {2025, 2026})):
        V = {'raw': raw}
        for K in (0, 500, 1000, 2000, 4000):
            V[f'opp K{K}'] = OA.adjust(rows, K, 1.0)
            V[f'opp+home K{K}'] = OA.adjust(rows, K, 1.0, home=True)
        res[part] = {'split': OA.split(rows, V, MIN, MINH, seas), 'ahead50': OA.ahead(rows, V, MIN, MINH, 0.5, seas)}
        for k, v in res[part].items():
            print(size, part, k, 'n', v['n'])
            for a, o in v.items():
                if a != 'n': print('   ', a, o)
    out[str(size)] = res
    if size == 1:
        # on-off: on rate minus off rate, each half; the off rows carry the same opponent in the same game
        offrows = [(r[0], r[1], r[2], r[3], r[4], o[0], o[1], r[7]) for r, o in zip(rows, off)]
        offraw = np.array([r[6] for r in offrows])
        for part, seas in (('tune', {2023, 2024}), ('held', {2025, 2026})):
            oo = {}
            for nm, K in (('raw', None), ('opp K1000', 1000), ('opp K2000', 2000), ('opp K4000', 4000)):
                von = raw if K is None else OA.adjust(rows, K, 1.0)
                # the off possessions get the same opponent rate: D from the on rows (all players' on rows = the team x 5)
                D = OA.defence(rows, K if K is not None else 0)
                voff = offraw if K is None else np.array([r[6] - r[5] * D.get((r[0], 0, r[4], r[1]), 0.0) for r in offrows])
                keys, A, B = OA._halves(rows, von, 2500, 800, seas)
                byu = defaultdict(list)
                for i, r in enumerate(rows): byu[(r[0], r[3])].append(i)
                xa, xb = [], []
                for k_, (a, ea), (b, eb) in zip(keys, A, B):
                    a = np.array(a); b = np.array(b)
                    fa = sum(offrows[i][5] for i in a); fb = sum(offrows[i][5] for i in b)
                    if fa < 500 or fb < 500: continue
                    xa.append(von[a].sum() / ea - voff[a].sum() / fa); xb.append(von[b].sum() / eb - voff[b].sum() / fb)
                oo[nm] = (np.array(xa), np.array(xb))
            rng = np.random.default_rng(3); n = len(oo['raw'][0]); idx = rng.integers(0, n, (2000, n))
            r0 = np.array([np.corrcoef(oo['raw'][0][i], oo['raw'][1][i])[0, 1] for i in idx])
            for nm, (a, b) in oo.items():
                d = np.array([np.corrcoef(a[i], b[i])[0, 1] for i in idx]) - r0
                print('onoff', part, nm, 'n', n, 'r', round(float(np.corrcoef(a, b)[0, 1]), 4), 'P', round(float((d > 0).mean()), 3))
                out.setdefault('onoff', {}).setdefault(part, {})[nm] = {'n': n, 'r': round(float(np.corrcoef(a, b)[0, 1]), 4), 'P': round(float((d > 0).mean()), 3)}
json.dump(out, open(os.path.join(HERE, 'nba_lineups_results.json'), 'w'), indent=1)
