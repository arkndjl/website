# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""PREREG.md M3b: the predicted share of kept, rebuilt ledger terms that keep their sign on the lockbox season.
Reads data/model_ledger.json only (no lockbox outcome). -> out/replication_forecast.json"""
import hashlib
import json
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
OUT = os.environ.get('METHODS_OUT', os.path.join(HERE, 'out'))
L = json.load(open(os.path.join(ROOT, 'data', 'model_ledger.json')))


def Phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


terms, et, eh = [], [], []
for name, m in L['models'].items():
    if m.get('source') != 'rebuilt':
        continue
    yrs = re.search(r'held (\d{4})-(\d{2,4})', m['split'])
    a, b = int(yrs.group(1)), int(yrs.group(2))
    b = b if b > 100 else 2000 + b
    k = b - a + 1
    for r in m['rows']:
        t, h = r.get('tune'), r.get('held')
        if r.get('verdict') != 'keep' or not t or not h or not t.get('n') or not h.get('n') or t.get('t') is None or h.get('t') is None:
            continue
        terms.append(dict(model=name, term=r['term'], heldSeasons=k, eTune=-t['t'] / math.sqrt(t['n']), eHeld=-h['t'] / math.sqrt(h['n']),
                          nHeld=h['n'], deff=h.get('deff') or 1.0, tTune=t['t'], tHeld=h['t']))
x = np.array([t['eTune'] for t in terms]); y = np.array([t['eHeld'] for t in terms])
s = float((x @ y) / (x @ x))
for t in terms:
    nL = t['nHeld'] / t['heldSeasons']
    t['pSame'] = round(Phi(s * t['eHeld'] * math.sqrt(nL) / math.sqrt(max(t['deff'], 1e-9))), 4)
p = np.array([t['pSame'] for t in terms])
rng = np.random.default_rng(20261119)
draws = (rng.random((20000, len(p))) < p).mean(1)
out = {'registered': '2026-11-19', 'ledgerAsof': L.get('asof'), 'ledgerSha256': hashlib.sha256(open(os.path.join(ROOT, 'data', 'model_ledger.json'), 'rb').read()).hexdigest(),
       'terms': len(terms), 'shrink': round(s, 3), 'corr': round(float(np.corrcoef(x, y)[0, 1]), 3),
       'expectedShareSameSign': round(float(p.mean()), 3), 'interval80': [round(float(np.percentile(draws, 10)), 3), round(float(np.percentile(draws, 90)), 3)],
       'byModel': {m: {'n': int(sum(t['model'] == m for t in terms)), 'expected': round(float(np.mean([t['pSame'] for t in terms if t['model'] == m])), 3)} for m in sorted({t['model'] for t in terms})},
       'scoring': 'season end, once: share of these terms whose lockbox drop-one d has the shipped sign; calibrated if inside interval80',
       'rows': [{k: (round(v, 5) if isinstance(v, float) else v) for k, v in t.items()} for t in terms]}
os.makedirs(OUT, exist_ok=True)
json.dump(out, open(os.path.join(OUT, 'replication_forecast.json'), 'w'), indent=1, sort_keys=True)
print({k: v for k, v in out.items() if k != 'rows'})
