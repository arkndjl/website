#!/usr/bin/env python3
"""The board as each run since Nov 20 wrote it (git history of static/data/cbb-all.json): how often a player's FV went
one way and then back while his line's games did not drop, and how often his shown BPM moved 2.5+ in a run that
added no more than one game. The old rule's record in production.

    python3 scripts/research/cbb_live_nov28/history.py      # -> history.json
"""
import json, os, subprocess, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
P = 'static/data/cbb-all.json'

revs = subprocess.run(['git', '-C', ROOT, 'log', '--since=2026-11-20', '--format=%h %aI', '--', P], capture_output=True, text=True).stdout.split('\n')
revs = [r.split() for r in revs if r.strip()][::-1]
hist = defaultdict(list)
for h, d in revs:
    try: b = json.loads(subprocess.run(['git', '-C', ROOT, 'show', f'{h}:{P}'], capture_output=True, text=True).stdout)
    except ValueError: continue
    ci = {c: j for j, c in enumerate(b['cols'])}
    for r in b['rows']:
        now = r[ci['now']] if 'now' in ci else None
        hist[(r[ci['name']], r[ci['team']])].append((d[:16], r[ci['fv']], now.get('gp') if now else None, now.get('bpm') if now else None))
out = {'runs': len(revs), 'players': len(hist), 'backAndForth': 0, 'playersBackAndForth': 0, 'bpmJumps': 0, 'examples': {}}
for k, h in hist.items():
    mv = [(y[1] - x[1]) for x, y in zip(h, h[1:]) if y[1] != x[1] and x[2] is not None and y[2] is not None and y[2] >= x[2]]
    b = sum(1 for x, y in zip(mv, mv[1:]) if x * y < 0)
    j = sum(1 for x, y in zip(h, h[1:]) if x[3] is not None and y[3] is not None and 0 <= (y[2] or 0) - (x[2] or 0) <= 1 and abs(y[3] - x[3]) >= 2.5)
    out['backAndForth'] += b; out['playersBackAndForth'] += b > 0; out['bpmJumps'] += j
    if k == ('Ethan Brown', 'Illinois'): out['examples']['Ethan Brown|Illinois'] = h
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, 'history.json'), 'w'), indent=1)
