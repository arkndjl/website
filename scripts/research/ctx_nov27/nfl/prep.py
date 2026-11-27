#!/usr/bin/env python3
"""Board replay for the Nov 27 context audit: full rows 2016-25 (whole season and through week 9), pre-lockbox only.

    python3 scripts/research/ctx_nov27/nfl/prep.py     # scripts/.cache/nfl/ctx27_rows_<y>[_w9].json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCR)
import nfl_war as W   # noqa: E402

CACHE = os.path.join(SCR, '.cache', 'nfl')
KEEP = ('n', 'id', 't', 'tm', 'pos', 'g', 'sn', 'war', 'wav', 'xv', 'waa', 'sh', 'age', 'ax', 'rook', 'stw', '_sub', '_g',
        '_war', '_avg', '_tg', 'pace')

if __name__ == '__main__':
    os.makedirs(CACHE, exist_ok=True)
    for y in range(2016, 2026):
        for thru, tag in ((None, ''), (10, '_w9')):
            fn = os.path.join(CACHE, f'ctx27_rows_{y}{tag}.json')
            if os.path.exists(fn):
                continue
            out, _, _ = W.board(y, thru=thru)
            with open(fn, 'w') as f:
                json.dump([{k: p[k] for k in KEEP if k in p} for p in out], f)
            print(y, tag, len(out), flush=True)
