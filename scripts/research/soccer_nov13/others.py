#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The game model outside the scored set: 1X2 log loss on league matches with a close in the leagues shown on the
page but never tuned on (second tiers, the thirteen more top flights, MLS), under changed settings."""
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine as E
import soccer_data as D
import soccer_games as G

rows = E.load_rows()
P = G.params()
LGS = {r['lg'] for r in rows if r['lg'] not in G.SCORED and r['lg'] not in D.CUPS and r['lg'] not in D.EURO
       and (r.get('pc') or r.get('bc') or r.get('ac') or r.get('nc'))}


def losses(Q, lo, hi):
    out = {}

    def score(r, S, lh, la, R):
        if not (lo <= S <= hi) or r['st'] != 'FT':
            return
        c = G.close_probs(r) or G.novig(r.get('nc'))
        if not c:
            return
        p = G.wdl(lh, la, Q['rho'])
        i = 0 if r['hs'] > r['as'] else 1 if r['hs'] == r['as'] else 2
        out[r['id']] = (r['day'], -math.log(max(1e-9, p[i])), -math.log(c[i]), r['lg'])
    G.run(rows, Q, score, scored=LGS)
    return out


def ev(kw):
    lo, hi = kw.pop('_span')
    return kw, losses(dict(P, **kw), lo, hi)


if __name__ == '__main__':
    span = (2023, 2026) if '--held' in sys.argv else (2013, 2022)
    grid = [{}] + [{k: P[k] * f} for k in ('km', 'kn', 'mv', 'wx', 'kx', 'k') for f in (0.7, 1.4)] + [{'sp': 1.03}, {'sp': 1.06}, {'boost': 2.5}, {'boost': 0.5}]
    if '--held' in sys.argv:
        grid = [{}] + [eval(a) for a in sys.argv[sys.argv.index('--held') + 1:]]
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(ev, [dict(g, _span=span) for g in grid]))
    base = res[0][1]
    n = len(base)
    print('leagues', sorted(LGS))
    print('base n', n, 'model', round(sum(v[1] for v in base.values()) / n, 5), 'close', round(sum(v[2] for v in base.values()) / n, 5))
    for kw, o in res[1:]:
        ids = [i for i in base if i in o]
        d = [o[i][1] - base[i][1] for i in ids]
        print(kw, 'd', round(sum(d) / len(d), 6), 't', G.cl_t(d, [base[i][0] for i in ids]), flush=True)
