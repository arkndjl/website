#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""N1 (prereg.md): tour main-draw log loss Jul 1 - Nov 10 2026 with and without the Tennis Abstract rows."""
import sys, os, math, json, gzip
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import *
import numpy as np
P = live_P()
def load(f):
    h = json.load(gzip.open(os.path.join(os.path.dirname(CACHE), f)))
    return [r for r in h['rows'] if r[0] <= LOCK]
old, new = load('hist_nota.json.gz'), load('hist.json.gz')
print('rows', len(old), len(new))
rec0 = base_rec(old)
W = dict(P, **M.fit_blend(M.window(rec0, 20260000), M.ALL))
sc = lambda r: M.scored(r, 2026, 2026) and r[0] >= 20260622
res = {}
for nm, rr in (('without', old), ('with', new)):
    _, rc = M.run(rr, P, score=sc, cm_lag=M.CM_LAG)
    res[nm] = {(x[0][0], x[0][6], x[0][7], x[0][8]): (M.blend_p(W, x), x) for x in rc}
ks = [k for k in res['with'] if k in res['without']]
d = np.array([-math.log(res['with'][k][0]) + math.log(res['without'][k][0]) for k in ks])
g = {}
for k, v in zip(ks, d): g.setdefault(k[1], []).append(v)
s = np.array([sum(v) for v in g.values()])
print('n', len(ks), 'LL without', round(-np.mean([math.log(res['without'][k][0]) for k in ks]), 5), 'with', round(-np.mean([math.log(res['with'][k][0]) for k in ks]), 5),
      'd x1e4', round(d.mean() * 1e4, 1), 't', round(s.sum() / (s.std(ddof=1) * len(s) ** .5), 2), 'events', len(s))
pc = np.array([res['with'][k][1][0][14] or np.nan for k in ks], float)
m = ~np.isnan(pc)
for nm in ('without', 'with'):
    pm = np.array([res[nm][k][0] for k in ks])
    print(nm, 'vs close: n', int(m.sum()), 'model', round(-np.log(pm[m]).mean(), 5), 'close', round(-np.log(pc[m]).mean(), 5), 'gap', round((-np.log(pm[m]) + np.log(pc[m])).mean(), 5),
          'fav share', round(np.maximum(pm[m], 1 - pm[m]).mean(), 3))
# who moved: matches where either player has TA rows
