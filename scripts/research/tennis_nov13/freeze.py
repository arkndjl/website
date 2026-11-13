# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Ablation: what does losing Challenger / ITF results after Jun 1 cost the tour-level chances in Jun-Nov?"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import *
import numpy as np
rows, players, tn = load_rows()
rec = base_rec(rows); P = live_P()
# walk-forward weights per season from the base pass
W = {}
for y in (2022, 2023, 2024, 2025):
    W[y] = dict(P, **M.fit_blend(M.window(rec, y * 10000), M.ALL))
for y in (2022, 2023, 2024, 2025):
    cut = y * 10000 + 601
    sc = lambda r: M.scored(r, y, y) and r[0] >= cut + 7
    full = [r for r in rows if r[0] < (y + 1) * 10000]
    froz = [r for r in full if not (r[0] >= cut and r[2] in ('C', 'S'))]
    out = {}
    for nm, rr in (('full', full), ('frozen', froz)):
        _, rc = M.run(rr, P, score=sc, cm_lag=M.CM_LAG)
        out[nm] = {(x[0][0], x[0][6], x[0][7], x[0][8]): math.log(M.blend_p(W[y], x)) for x in rc}
    ks = [k for k in out['full'] if k in out['frozen']]
    d = np.array([out['full'][k] - out['frozen'][k] for k in ks])
    # cluster by tournament
    g = {}
    for k, v in zip(ks, d): g.setdefault(k[1], []).append(v)
    s = np.array([sum(v) for v in g.values()])
    t = s.sum() / (s.std(ddof=1) * len(s) ** .5)
    print(y, 'n', len(ks), 'LL full', round(-np.mean([out['full'][k] for k in ks]), 5), 'frozen', round(-np.mean([out['frozen'][k] for k in ks]), 5),
          'gain from data x1e4', round(d.mean() * 1e4, 1), 't', round(t, 2))
    # by month
    for mth in range(6, 12):
        dm = [out['full'][k] - out['frozen'][k] for k in ks if k[0] // 100 % 100 == mth]
        if dm: print('   month', mth, len(dm), round(np.mean(dm) * 1e4, 1))
