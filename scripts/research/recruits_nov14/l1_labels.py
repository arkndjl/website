# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L1 + L2: the index fit on the old labels against the corrected ones, both scored on the corrected outcome held out."""
import json
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data as D      # noqa: E402
import rh as H   # noqa: E402
R, T = H.R, H.T

new = D.load(); old = pickle.load(open(os.path.join(os.path.dirname(D.PK), 'retarget_rows_old.pkl'), 'rb'))
assert len(new) == len(old)
sz = R.size_norms(new)
res = {'rows': len(new), 'drafted_old': sum(r['drafted'] for r in old), 'drafted_new': sum(r['drafted'] for r in new)}
yo = np.array([r['out'] for r in new]); cls = np.array([r['year'] for r in new])
for nm, rows in (('old', old), ('new', new)):
    H.prep(rows)
    # train on `rows` labels, score on the corrected outcome
    p, f = H.cv(rows, H.BASE['on'], H.BASE['fv'], sz)
    e = p * np.maximum(f, R.FLOOR) + (1 - p) * R.FLOOR
    res[nm] = {'rho': round(T.spear(e, yo), 4), 'byClass': {int(c): round(T.spear(e[cls == c], yo[cls == c]), 4) for c in sorted(set(cls))}}
dd = H.dedupe(new); H.prep(dd)
res['dedupe'] = {'rows': len(dd), 'drafted': sum(r['drafted'] for r in dd)}
print(json.dumps(res, indent=1))
