#!/usr/bin/env python3
"""N1 (early margin stretch) and N2 (early totals shrink) on the NFL walk-forward file; prereg.md beside this file."""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H
rows = [r for r in json.load(gzip.open(os.path.join(ROOT, 'scripts/data/games_wf/nfl.json.gz')))
        if not (r['S'] == 2026 and r['wk'] > 10) and r.get('po', 0) == 0]
tune = lambda r: 2015 <= r['S'] <= 2020
out = {}
# N1
R = [r for r in rows if r['wk'] <= 3 and r.get('m') is not None and r.get('res') is not None]
T = [r for r in R if tune(r)]
m = np.array([r['m'] for r in T]); y = np.array([r['res'] for r in T])
s = float(m @ y / (m @ m))
def score(sub, f):
    new = [abs(r['res'] - f(r)) for r in sub]; base = [abs(r['res'] - r['m']) for r in sub]
    return H.paired(new, base, cluster=np.array([f"{r['S']}-{r['wk']}" for r in sub]))
f = lambda r: s * r['m']
out['N1'] = {'s': round(s, 3), 'tune': score(T, f), 'held': score([r for r in R if not tune(r)], f),
             'byHeldSeason': {S: round(float(np.mean([abs(r['res'] - f(r)) - abs(r['res'] - r['m']) for r in R if r['S'] == S])), 3)
                              for S in range(2021, 2027)}}
# N2
R = [r for r in rows if 2 <= r['wk'] <= 6 and r.get('tm') is not None and r.get('tot') is not None]
wm = defaultdict(list)
for r in R: wm[(r['S'], r['wk'])].append(r['tm'])
for r in R: r['w'] = float(np.mean(wm[(r['S'], r['wk'])]))
T = [r for r in R if tune(r)]
a = np.array([r['tm'] - r['w'] for r in T]); b = np.array([r['tot'] - r['w'] for r in T])
c = float(a @ b / (a @ a))
g = lambda r: r['w'] + c * (r['tm'] - r['w'])
def tscore(sub):
    new = [abs(r['tot'] - g(r)) for r in sub]; base = [abs(r['tot'] - r['tm']) for r in sub]
    return H.paired(new, base, cluster=np.array([f"{r['S']}-{r['wk']}" for r in sub]))
out['N2'] = {'c': round(c, 3), 'tune': tscore(T), 'held': tscore([r for r in R if not tune(r)])}
json.dump(out, open(os.path.join(os.path.dirname(__file__), 'res_wf.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
