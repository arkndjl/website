#!/usr/bin/env python3
"""(d) post hoc, not in Holm: where the G5 gain comes from. Player r (n predictor vs n+1 cWAR, n+1 exposure weights) for
players who stay at their tier vs G5 -> P4 movers, at c = .75 (the value the folds chose 5 of 6 times); and the team
test with c applied as a team-level conference constant (every G5 team-season shifted by c x its returning SAV_W
exposure) to tell a player-level discount from a plain conference prior.   -> cfb_g5_diag.json"""
import json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cfb_port as CP
H, R, PAIRS = CP.H, CP.R, CP.PAIRS
c = .75
g5 = lambda n, p: 0.0 if CP.CONF.get((n, p), True) else 1.0
out = {}
for lab, cc in (('base', 0.0), ('g5', c)):
    grp = defaultdict(lambda: ([], [], []))
    for n in PAIRS:
        e1 = defaultdict(float); tn = {}
        for pid, t, x in H.PARTS[(n + 1, 7)]: e1[pid] += x; tn[pid] = t
        for pid, x in e1.items():
            if x < .4 or pid not in R[n] or (n, pid) not in CP.CONF or (n + 1, pid) not in CP.CONF: continue
            E = CP.E[n][pid]; v = (CP.CWAR_V[H.g_(pid)] + CP.SAV_W[H.g_(pid)] * (R[n][pid]['z'] - cc * g5(n, pid))) * E / (E + .2)
            k = 'G5->P4' if g5(n, pid) and not g5(n + 1, pid) else 'same tier' if g5(n, pid) == g5(n + 1, pid) else 'P4->G5'
            for kk in (k, 'all'):
                a = grp[kk]; a[0].append(v); a[1].append(H.M['cwar'](n + 1, pid)); a[2].append(x)
    out[lab] = {k: dict(r=round(H.core.wcorr(*v), 4), n=len(v[0])) for k, v in grp.items()}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, 'cfb_g5_diag.json'), 'w'), indent=1)
