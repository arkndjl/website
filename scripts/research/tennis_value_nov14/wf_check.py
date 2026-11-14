# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Walk-forward check of the player value terms inside scripts/tennis_model.py (WIN-season blend refits): base
(no CP / CW), + CP, + CW, + both. Held 2023-26 and against the close 2025-26, t by tournament.
    python3 scripts/research/tennis_value_nov14/wf_check.py -> scripts/research/tennis_value_nov14/wf_check.json"""
import json, math, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import tennis_model as M
import tennis_data as TD

rows, players, tn = TD.load()
P = dict(M.DEFAULT, **json.load(open(M.FIT))['params'])
P['CP'] = P['CW'] = 0.0
_, rec = M.run(rows, P, score=lambda r: M.scored(r, 2012 - M.WIN, 2100), cm_lag=M.CM_LAG)
keep = [i for i, x in enumerate(rec) if x[0][0] // 10000 >= 2012]
out = {}
probs = {}
for name, use in (('base', tuple(range(8))), ('cp', tuple(range(9))), ('cw', tuple(range(8)) + (9,)), ('both', tuple(range(10)))):
    M.ALL = use
    pw = M.wf_probs(rec, P)
    probs[name] = [pw[i] for i in keep]
R = [rec[i] for i in keep]


def tstat(d):
    n = len(d); m = sum(d) / n; sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)); return m / (sd / math.sqrt(n))


for name in ('cp', 'cw', 'both'):
    o = {}
    for lab, f in (('tune', lambda x: x[0][0] // 10000 <= 2022), ('held', lambda x: x[0][0] // 10000 >= 2023),
                   ('close', lambda x: x[0][14] is not None and 0 < x[0][14] < 1)):
        idx = [i for i, x in enumerate(R) if f(x)]
        by = defaultdict(float)
        for i in idx:
            by[R[i][0][6]] += -math.log(probs[name][i]) + math.log(probs['base'][i])
        o[lab] = {'dll_x1e4': round(1e4 * sum(by.values()) / len(idx), 2), 't': round(tstat(list(by.values())), 2), 'n': len(idx)}
        if lab == 'close':
            o[lab]['gap_model_minus_close_base'] = round(sum(-math.log(probs['base'][i]) + math.log(R[i][0][14]) for i in idx) / len(idx), 5)
            o[lab]['gap_model_minus_close_new'] = round(sum(-math.log(probs[name][i]) + math.log(R[i][0][14]) for i in idx) / len(idx), 5)
    out[name] = o
    print(name, json.dumps(o), flush=True)
json.dump(out, open(os.path.join(HERE, 'wf_check.json'), 'w'), indent=1)
