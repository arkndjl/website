#!/usr/bin/env python3
"""R1b (not pre-registered; a bug check found while shipping R1): the awards draw's newcomer prior read a board part
labelled 'BPM' that no longer exists, so a newcomer's prior was his own BPM to date (no shrink). Floor for the fix
(prior = preseason xXPM, K 300): a flat prior, the earlier seasons' mean rest-of-season game BPM of the same pool, K 300,
against no shrink. Players with no line the season before, same pool and checkpoints as R1 (importing it reruns R1).
 -> r1b.json"""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import r1_awards_rate as R
from h1_builder import tstat


def season(y):
    T = defaultdict(lambda: defaultdict(dict))
    for g in json.load(gzip.open(os.path.join(R.BTLOG, f'{y}.json.gz'))):
        if g[8] and g[44] is not None: T[g[47]][g[0]][str(int(g[51]))] = (float(g[8]), float(g[44]))
    out = []
    for t, G in T.items():
        ds = sorted(G)
        for cp in R.CPS:
            if len(ds) < cp + 5: continue
            a = defaultdict(lambda: [0.0, 0.0, 0]); b = defaultdict(lambda: [0.0, 0.0])
            for d in ds[:cp]:
                for p, (mn, gb) in G[d].items(): a[p][0] += mn; a[p][1] += mn * gb; a[p][2] += 1
            for d in ds[cp:]:
                for p, (mn, gb) in G[d].items(): b[p][0] += mn; b[p][1] += mn * gb
            for p, (m0, s0, gp) in a.items():
                if gp < .6 * cp or m0 / gp < 20 or b[p][0] < 50 or (p, y - 1) in R.H: continue
                out.append((cp, m0, s0 / m0, b[p][0], b[p][1] / b[p][0]))
    return np.array(out)


S = {y: season(y) for y in range(2017, 2027)}; res = []
for y in range(2018, 2027):
    mu = sum((S[k][:, 3] * S[k][:, 4]).sum() for k in S if k < y) / sum(S[k][:, 3].sum() for k in S if k < y)
    A = S[y]; w = A[:, 3]; f = lambda m: float((w * (m - A[:, 4]) ** 2).sum() / w.sum())
    res.append({'season': y, 'n': len(A), 'no_shrink': f(A[:, 2]), 'flat_prior_K300': f((A[:, 2] * A[:, 1] + mu * 300) / (A[:, 1] + 300)), 'mu': round(float(mu), 2)})
d = np.array([r['no_shrink'] - r['flat_prior_K300'] for r in res])
out = {'seasons': res, 'mse_no_shrink': round(float(np.mean([r['no_shrink'] for r in res])), 3), 'mse_flat_prior_K300': round(float(np.mean([r['flat_prior_K300'] for r in res])), 3),
       't': round(tstat(d), 2), 'k': int((d > 0).sum()), 'n': len(d)}
print({k: v for k, v in out.items() if k != 'seasons'})
json.dump(out, open(os.path.join(HERE, 'r1b.json'), 'w'), indent=1)
