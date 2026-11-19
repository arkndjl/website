#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Past Bracket Matrix pages (matrix_YYYY.html in a folder): summary and the pre-reveal check for lead 2.

    python3 scripts/research/sweep_nov19/cbb/bracket_matrix.py DIR
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
from cbb_bracket_matrix import parse  # noqa: F401

if __name__ == '__main__':
    d = sys.argv[1]
    for f in sorted(os.listdir(d)):
        if f.startswith('matrix_') and f.endswith('.html'):
            rows = parse(os.path.join(d, f))
            fld = [x for x in rows if x['seed']]
            same = sum(1 for x in fld if abs(x['avg'] - x['seed']) < 1e-9)
            print(f, len(rows), 'teams', len(fld), 'seeded', 'brackets', max((x['n'] for x in rows), default=0), 'avg == official on', same)
