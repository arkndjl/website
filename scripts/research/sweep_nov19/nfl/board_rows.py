#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The NFL board replayed for past seasons, value columns only (for the honours label table).

    python3 board_rows.py <out json> 2018 ... 2025"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import nfl_war as W   # noqa: E402

KEEP = ('id', 'name', 'pos', 'team', 'sn', 'war', 'wav', 'xv', 'waa', 'xp', 'pxp', '_g', '_sub', 'g', 'gs')
out = {}
for y in (int(a) for a in sys.argv[2:]):
    rows, _, _ = W.board(y)
    out[y] = [{k: p.get(k) for k in KEEP} for p in rows]
    print(y, len(rows), {k: rows[0].get(k) for k in KEEP}, flush=True)
json.dump(out, open(sys.argv[1], 'w'))
