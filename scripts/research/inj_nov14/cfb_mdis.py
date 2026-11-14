#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""G4 of PREREG.md: market disagreement on the committed CFB walk-forward margins (scripts/data/games_wf/cfb.json.gz).
Writes data/inj_nov14_mdis.json."""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..')
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import harness as H
K = 0.2
rows = [r for r in json.load(gzip.open(os.path.join(ROOT, 'scripts/data/games_wf/cfb.json.gz'))) if not (r['S'] == 2026 and r['wk'] >= 11)]
rows.sort(key=lambda r: r['date'])
d, season = defaultdict(float), None
x = np.zeros(len(rows))
for i, r in enumerate(rows):
    if r['S'] != season:
        d, season = defaultdict(float), r['S']
    x[i] = d[r['home']] - d[r['away']]
    if r.get('L') is not None and r.get('m') is not None:
        e = (r['L'] - r['m']) - x[i]
        d[r['home']] += K * e; d[r['away']] -= K * e
S = np.array([r['S'] for r in rows]); m = np.array([r['m'] for r in rows], float); res = np.array([r['res'] for r in rows], float)
L = np.array([np.nan if r.get('L') is None else r['L'] for r in rows], float)
day = np.array([r['date'][:10] for r in rows]); ok = ~np.isnan(L) & ~np.isnan(m)
pred = m.copy(); coef = {}
for s in sorted(set(S)):
    tr = (S < s) & ~np.isnan(m)
    c = float((x[tr] @ (res[tr] - m[tr])) / (x[tr] @ x[tr])) if tr.sum() > 100 and x[tr] @ x[tr] > 0 else 0.0
    coef[int(s)] = round(c, 3); pred[S == s] = m[S == s] + c * x[S == s]
out = {'k': K, 'coefBySeason': coef, 'sdInput': round(float(x[ok].std()), 2)}
for nm, k in (('tune', (S >= 2017) & (S <= 2020) & ok), ('held', (S >= 2021) & ok), ('heldWk4plus', (S >= 2021) & ok & np.array([r['wk'] >= 4 for r in rows]))):
    r = H.paired(np.abs(pred[k] - res[k]), np.abs(m[k] - res[k]), cluster=day[k])
    out[nm] = {'n': int(k.sum()), 'maeBase': round(float(np.abs(m[k] - res[k]).mean()), 3), 'maeCand': round(float(np.abs(pred[k] - res[k]).mean()), 3),
               'maeClose': round(float(np.abs(L[k] - res[k]).mean()), 3), 't': round(r['t'], 2), 'p': r['p']}
out['bySeason'] = {int(s): round(float((np.abs(pred - res) - np.abs(m - res))[(S == s) & ok].mean()), 3) for s in sorted(set(S))}
print(json.dumps(out, indent=1))
json.dump({'prereg': 'scripts/research/inj_nov14/PREREG.md', 'G4': out}, open(os.path.join(ROOT, 'data/inj_nov14_mdis.json'), 'w'), indent=1)
