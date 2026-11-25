#!/usr/bin/env python3
"""Team ratings on the same pairs: season-n Barttorvik adjEM / win% -> n+1 adjEM (pooled R2, centred by season), the
team analogue of the player harness's predict test. -> team.json"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit as A
out = {}
for name, key in (('Barttorvik adjEM (season n)', 'em'), ('win% (season n)', 'wp')):
    xs, ys, per = [], [], {}
    for n in A.PAIRS:
        a, b = A.S[n][key], A.S[n + 1]['em']
        T = [t for t in a if t in b]
        x = np.array([a[t][0] / a[t][1] for t in T]); y = np.array([b[t][0] / b[t][1] for t in T])
        x -= x.mean(); y -= y.mean(); xs += list(x); ys += list(y); per[n] = round(float(np.corrcoef(x, y)[0, 1] ** 2), 4)
    out[name] = {'predictR2': round(float(np.corrcoef(xs, ys)[0, 1] ** 2), 4), 'byPair': per}
print(out); json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'team.json'), 'w'), indent=1)
