#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T6: soccer award voter models with SVAR in place of GAR (prereg.md). Shipped voter models only (test.pass in
data/awards_fit.json): Ballon d'Or, Serie A MVP, UNFP. Votes from Wikipedia (the awards cache), seasons 2015-2026.

    python3 scripts/research/ctx_nov27/soccer/aw.py     # -> aw.json here
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCR)
import awards_engine as E  # noqa: E402
import awards_soccer as SO  # noqa: E402
import awards_soccer_more as M  # noqa: E402
from awards_research import L2, t_sf  # noqa: E402

FIT = json.load(open(os.path.join(SCR, '..', 'data', 'awards_fit.json')))['soccer']
sw = lambda cols: ['svar' if c == 'gar' else c for c in cols]
res = {}


def run(a, races, cols, depth):
    races = [(s, [dict(r, svar=r.get('svar') or 0.0, age=r.get('age') or 26.0) for r in p], o) for s, p, o in races if o]
    S = [s for s, _, _ in races]
    if len(S) < 5:
        res[a] = {'blocked': 'votes page not fetched (Wikipedia 429)', 'seasons': len(S)}
        print(a, res[a], flush=True)
        return
    rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
    lo = lambda cs: E.loso(rr(cs), S, l2=L2, depth=depth)
    g, s, n0 = lo(cols), lo(sw(cols)), lo(['svar'])
    swap, null = E.paired(s, g), E.paired(s, n0)
    res[a] = {'seasons': len(S), 'll_gar': round(sum(x['ll'] for x in g) / len(g), 4), 'll_svar': round(sum(x['ll'] for x in s) / len(s), 4),
              'hit_gar': sum(x['hit'] for x in g), 'hit_svar': sum(x['hit'] for x in s),
              'svar_vs_gar': swap, 'svar_vs_null': dict(null, p=round(t_sf(null['t'], null['n'] - 1), 4)),
              'pass': bool(swap['gain'] >= 0 and null['gain'] > 0 and null['wins'] * 2 > null['n'])}
    print(a, json.dumps(res[a]), flush=True)


if FIT['ballon']['test'].get('pass'):
    R, _ = SO.races()
    run('ballon', R, SO.COLS, 3)
want = [a for a in M.AWARDS if (FIT.get(a) or {}).get('test', {}).get('pass')]
print('league races with a shipped voter model', want, flush=True)
R, _ = M.races(only=want)
for a in want:
    cols = {'goldenboy': M.YOUNG_COLS, 'kopa': M.KOPA_COLS, 'yashin': M.YASHIN_COLS}.get(a, M.LEAGUE_COLS)
    run(a, R[a], cols, M.AWARDS[a][3])
json.dump(res, open(os.path.join(HERE, 'aw.json'), 'w'), indent=1)
