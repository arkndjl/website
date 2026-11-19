# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 7: development effect by head coach (pre-registered in prereg.md). Needs scripts/.cache/dev/cfb_recruits.json
(cfb_recruit_retarget.dataset) and the committed coach seasons (scripts/data/coach_alltime_src.json.gz)."""
import gzip, json, math, os, re, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import school_dev as D
import names
D.FIXK = None
sq = lambda s: re.sub(r'[^a-z]', '', names.team_key(s) if s else '')
CO = {}
src = json.load(gzip.open(os.path.join(ROOT, 'scripts/data/coach_alltime_src.json.gz')))['cfb']['rows']
for r in src:
    if r.get('cs'): CO[(sq(r['t']), r['y'])] = max(r['cs'], key=lambda c: c[1])[0]
rows = D.cfb_rows()
key = 'fv'
D.loso_expect(rows, key); D.net_of_program(rows, key)
R = [r for r in rows if key in r.get('dn', {})]
hit = 0
for r in R:
    r['team0'] = r['school']; r['coach'] = CO.get((sq(r['school']), int(r['cls'])))
    hit += r['coach'] is not None
C = [dict(r, school=r['coach']) for r in R if r['coach']]
classes = sorted({r['cls'] for r in C})
out = {'rows': len(R), 'withCoach': hit, 'coaches': len({r['school'] for r in C}), 'classes': [classes[0], classes[-1]]}
for dk in ('dn', 'd'):
    t = D.tests(C, key, dk, classes)
    out['rolling_' + dk] = {k: v for k, v in t['rolling'].items() if k != 'byClass'}
    out['rolling_' + dk]['byClass'] = [(p['cls'], p['slope'], p['mseGainPct']) for p in t['rolling']['byClass']]
    out['split_' + dk] = {k: v for k, v in t['split'].items() if k != 'hyper'}
# school version on the same rows, for reference
S = [dict(r, school=r['team0']) for r in R if r['coach']]
out['school_rolling_dn'] = {k: v for k, v in D.tests(S, key, 'dn', classes)['rolling'].items() if k != 'byClass'}
# movers
bycoach = defaultdict(lambda: defaultdict(list))
for r in C: bycoach[r['school']][r['team0']].append(r)
e, u, cl = [], [], []
movers = 0
for co, by in bycoach.items():
    if len(by) < 2: continue
    order = sorted(by, key=lambda s: min(x['cls'] for x in by[s]))
    A = order[0]
    effA, _ = D.eb([dict(x, school=('A' if (x['coach'] == co and x['team0'] == A) else 'o|' + str(x['coach']) + '|' + x['team0'])) for x in C if x['cls'] <= max(y['cls'] for y in by[A])], key, 'dn')
    if 'A' not in effA: continue
    movers += 1
    for B in order[1:]:
        others = [dict(x, school=x['team0']) for x in S if x['coach'] != co]
        effS, _ = D.eb(others, key, 'dn')
        sB = effS.get(B, {'u': 0.0})['u']
        for x in by[B]:
            e.append(x['dn'][key] - sB); u.append(effA['A']['u']); cl.append(co)
e, u = np.array(e), np.array(u); ec = e - e.mean()
b = float(u @ ec / (u @ u)); res = ec - b * u
g = defaultdict(float)
for ui, ri, c in zip(u, res, cl): g[c] += ui * ri
se = math.sqrt(sum(v ** 2 for v in g.values())) / (u @ u)
out['movers'] = {'coaches': movers, 'n': len(e), 'slope': round(b, 3), 't': round(b / se, 2)}
print(json.dumps(out, indent=1))
