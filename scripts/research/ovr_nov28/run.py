# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""python3 scripts/research/ovr_nov28/run.py [nba nhl nfl soccer tennis cs2] -> research/ovr_research.json (merged by sport)"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
import suite
OUT = os.path.join(ROOT, 'research', 'ovr_research.json')


def strip(o):
    return o


def go(sport):
    if sport == 'nba':
        import nba
        rows = nba.rows()
        return suite.run(rows, cap=2000, repl=lambda r: nba.REPL, kgrid=[100, 250, 500, 1000, 2000, 4000, 8000])
    if sport.startswith('nhl'):
        import nhl
        g = sport[3:] or 'F'
        rows = nhl.rows(g)
        cap = 3000 if g == 'G' else 1200
        return suite.run(rows, cap=cap, repl=lambda r: 0.0, kgrid=[100, 250, 500, 1000, 2000, 4000], sub=False)
    if sport == 'soccer':
        import soccer
        # shrink needs career minutes, which the live board has no history for (the big-five files stop at 2021-22): left out
        return suite.run(soccer.rows(), cap=3000, repl=lambda r: 0.0, kgrid=[250, 500, 1000, 2000, 4000], sub=False, skip=('shrink',))
    raise SystemExit('unknown ' + sport)


if __name__ == '__main__':
    allr = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for sp in sys.argv[1:]:
        out, res = go(sp)
        allr[sp] = out
        print(sp, json.dumps(out, indent=1)[:6000])
    json.dump(allr, open(OUT, 'w'), indent=1)
