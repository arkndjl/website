# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL lines: opponent adjustment of 5-on-5 xG difference per 60 for forward trios, defence pairs and skaters' on-ice
lines (Nov 20 2026).   python3 scripts/nhl_lines.py --pull 2025 2026 && python3 scripts/research/oppwx_nov20/nhl_lines_test.py

A unit's game row = its 5v5 seconds and xG for - against; opponent = the 5v5 xG difference per second that team gave
up in its other games, shrunk (oppadj.py). Tune 2024-25, held 2025-26, regular season.
"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import oppadj as OA
import nhl_lines as L
S_ = {S: L.summarize(S) for S in (2025, 2026)}
out = {}
for kind, MIN, MINH in (('F', 9000, 3000), ('D', 15000, 5000), ('P', 30000, 10000)):
    for what, f in (('xGD', lambda v: v[3] - v[4]), ('xGF', lambda v: v[3]), ('xGA', lambda v: -v[4])):
        rows = []
        for S, gs in S_.items():
            for g in gs:
                if g['po'] or not g['xg']: continue
                for t, o in ((g['h'], g['a']), (g['a'], g['h'])):
                    for k, v in g['t'][t][kind].items():
                        if v[0] > 0: rows.append((S, g['id'], g['day'], (t, k), o, v[0], f(v), t == g['h']))
        raw = np.array([r[6] for r in rows])
        res = {}
        for part, seas in (('tune', {2025}), ('held', {2026})):
            V = {'raw': raw}
            for K in (0, 30000, 60000, 120000, 240000):
                V[f'opp K{K}'] = OA.adjust(rows, K, 1.0)
            V['opp+home K60000'] = OA.adjust(rows, 60000, 1.0, home=True)
            res[part] = {'split': OA.split(rows, V, MIN, MINH, seas), 'ahead50': OA.ahead(rows, V, MIN, MINH, 0.5, seas)}
            for k, v in res[part].items():
                print(kind, what, part, k, 'n', v['n'])
                for a, o in v.items():
                    if a != 'n': print('   ', a, o)
        out[kind + ' ' + what] = res
json.dump(out, open(os.path.join(HERE, 'nhl_lines_results.json'), 'w'), indent=1)
