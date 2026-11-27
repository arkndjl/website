#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T3: the game model's injury term on p/90 (pg90 as rebuilt Nov 24) in place of prior-season GAR a 90. The Nov 23
harness (scripts/research/port_nov23/soccer/cells.py, cell C8) rerun as it was; the season files now carry the new pg90.

    python3 scripts/research/ctx_nov27/soccer/inj.py     # -> inj.json here (tune 2013-2022; held only if tune d < 0)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'port_nov23', 'soccer'))
import cells as C  # noqa: E402

rows = C.features([r for r in C.engine.load_rows() if r['day'] < C.LOCK])
P = C.G.params()
res = {}
base = C.walk(rows, P, 2013, 2022)
out = []
for q in C.GRID['C8']:
    Q = dict(P, **{k: v for k, v in q.items() if not k.startswith('_')})
    cmp_ = C.compare(base, C.walk(C.with_rows(rows, q), Q, 2013, 2022))
    out.append({'q': q, **cmp_})
    print(q, cmp_['d'], cmp_['t'], flush=True)
best = min(out, key=lambda x: x['d'])
res['tune'] = out
res['pick'] = best['q'] if best['d'] < 0 else None
if res['pick']:
    q = res['pick']
    hb = C.walk(rows, P, 2023, 2026)
    res['held'] = C.compare(hb, C.walk(C.with_rows(rows, q), dict(P, **{k: v for k, v in q.items() if not k.startswith('_')}), 2023, 2026))
    print('held', res['held'], flush=True)
json.dump(res, open(os.path.join(HERE, 'inj.json'), 'w'), indent=1)
