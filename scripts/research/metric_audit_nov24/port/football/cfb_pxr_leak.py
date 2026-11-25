#!/usr/bin/env python3
"""Lead's leakage check on CFB (b) pXR form: base cWAR, pXR form and one constant (k a share, k = the mean CWAR_V a share,
no position information, added unshrunk like the pXR line) on raw n+1 starter-slot exposure and on n+1 exposure rescaled to
a full lineup (each team's seven-position shares scaled to 12 slots).  -> cfb_pxr_leak.json"""
import json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cfb_port as CP
H, R, PAIRS, E = CP.H, CP.R, CP.PAIRS, CP.E
val = H.M['cwar']
k = float(np.mean([CP.CWAR_V[H.g_(p)] for y in CP.YEARS for p, t, e in H.PARTS[(y, 7)] for _ in [0]]))
arms = {'base': (None, .2), 'pxr': (lambda n, p: CP.CWAR_V[H.g_(p)] + CP.SAV_W[H.g_(p)] * R[n][p]['z'] * E[n][p] / (E[n][p] + .2), 0),
        'const': (lambda n, p: k + (val(n, p) - k) * E[n][p] / (E[n][p] + .2), 0)}
orig = dict(H.PARTS); out = {'k': round(k, 4)}
for lab in ('raw', 'lineup'):
    if lab == 'lineup':
        for y in CP.YEARS:
            tot = defaultdict(float)
            for pid, t, e in orig[(y, 7)]: tot[t] += e
            H.PARTS[(y, 7)] = [(pid, t, e * 12 / tot[t]) for pid, t, e in orig[(y, 7)]]
    res = {a: H.predict(val, 7, PAIRS, pval=f, pk=pk) for a, (f, pk) in arms.items()}
    out[lab] = {a: {'teamOOS': r[0]['teamOOS'], 'playerR': r[0]['playerR'], 'within': r[0]['playerRwithinPos']} for a, r in res.items()}
    out[lab]['pxr vs base'] = H.paired(res['base'][1], res['pxr'][1]); out[lab]['const vs base'] = H.paired(res['base'][1], res['const'][1])
    out[lab]['pxr vs const'] = H.paired(res['const'][1], res['pxr'][1])
    print(lab, json.dumps(out[lab]), flush=True)
json.dump(out, open(os.path.join(HERE, 'cfb_pxr_leak.json'), 'w'), indent=1)
