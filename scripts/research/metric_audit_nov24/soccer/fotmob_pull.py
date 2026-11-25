#!/usr/bin/env python3
"""FotMob season stat lists (minutes, rating, goals, xG ...) for the big five, seasons 2017..2026 (2016-17 .. 2025-26),
through scripts/soccer_more.py's pull (cache scripts/.cache/soccer/fms, gitignored). Lockbox: 2027 never pulled."""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import soccer_more as M
for lg in M.FMB5:
    for S, base in sorted(M.season_files(lg).items()):
        if 2017 <= S <= 2026:
            rows = M.pull(lg, S, base)
            print(lg, S, len(rows), sum(1 for r in rows if r.get('rt') is not None), flush=True)
