import json
import numpy as np
from run_basic import feats_from, run, load, W, OUT
P = {}
for f in (OUT + 'nfl_pace_2013.json', OUT + 'nfl_pace_2020.json'):
    P.update(json.load(open(f)))
games = []
for gid, v in P.items():
    if len(v) != 2:
        continue
    y, wk, a, h = gid.split('_')
    S = int(y)
    A, B = v.get(a), v.get(h)
    if not A or not B:
        continue
    games.append({'id': gid, 'S': S + 1 if False else S, 'h': h, 'a': a, 'day': y + wk.zfill(2),
                  'plays': A[0] + B[0], 'spp': (A[1] + B[1]) if A[1] and B[1] else None, 'nh': A[2] + B[2], 'drv': A[3] + B[3]})
wf = load(W + 'nfl.json.gz')
# wf S = season year? check
print(sorted(set(r['S'] for r in wf))[:3], wf[0]['id'])
out = {}
for nm in ('plays', 'spp', 'nh', 'drv'):
    gg = [g for g in games if g[nm] is not None]
    F = feats_from(gg, lambda x: x['id'], lambda x: x['S'], lambda x: x['h'], lambda x: x['a'], lambda x: x[nm], lambda x: x['day'], hl=6, carry=0.5)
    out[nm] = run('nfl ' + nm, wf, F, (2015, 2020), 2021, 2015)
json.dump(out, open(OUT + 'nfl.json', 'w'), indent=1)
