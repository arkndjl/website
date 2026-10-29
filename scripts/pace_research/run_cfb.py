import gzip, json
from collections import defaultdict
import numpy as np
from run_basic import feats_from, run, load, W, OUT
import os
SC = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/'
d = load(SC + 'data/cfb_hist_md.json.gz')
when = {}
for S, gs in d['games'].items():
    for g in gs:
        when[str(g['id'])] = g['startDate']
G = defaultdict(dict)
for S, rs in d['adv'].items():
    for r in rs:
        o = r.get('offense') or {}
        G[str(r['gameId'])][r['team']] = (int(S), o.get('plays'), o.get('drives'), r['opponent'])
games = []
for gid, v in G.items():
    if len(v) != 2 or gid not in when:
        continue
    (t1, a), (t2, b) = v.items()
    if a[1] is None or b[1] is None:
        continue
    games.append({'id': gid, 'S': a[0], 'h': t1, 'a': t2, 'plays': a[1] + b[1], 'drives': (a[2] or 0) + (b[2] or 0) or None, 'day': when[gid]})
print(len(games))
wf = load(W + 'cfb.json.gz')
out = {}
for nm in ('plays', 'drives'):
    gg = [g for g in games if g[nm]]
    F = feats_from(gg, lambda x: x['id'], lambda x: x['S'], lambda x: x['h'], lambda x: x['a'], lambda x: x[nm], lambda x: x['day'], hl=5, carry=0.5)
    out[nm] = run('cfb ' + nm, wf, F, (2017, 2021), 2022, 2017)
json.dump(out, open(OUT + 'cfb.json', 'w'), indent=1)
