# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Forward block tests on the recruit index (scripts/cfb_recruit_retarget.py's hurdle on NFL outcomes): a candidate
block is added to the baseline and scored on school-held-out folds, paired over recruits and by class."""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import cfb_recruit_fit as R          # noqa: E402
import cfb_recruit_retarget as T     # noqa: E402  (sets R.logit to the damped fit)

BASE = {'on': ['grade', 'hinge', 'size', 'level', 'elo', 'comp', 'gap'], 'fv': ['grade', 'elo']}
EXTRA = {}   # block -> fn(row) -> {name: value}


def dedupe(data):
    """one row per ESPN id: the earliest listing with a grade, else the earliest"""
    best = {}
    for i, r in enumerate(data):
        k = r['id'] or ('rid', r['rid'])
        key = (0 if r['grade'] >= 60 else 1, r['year'])
        if k not in best or key < best[k][0]: best[k] = (key, i)
    keep = {i for _, i in best.values()}
    return [r for i, r in enumerate(data) if i in keep]


def prep(data):
    for r in data:
        r.pop('_bc', None); r['k'] = 3; r['on'] = r['drafted']; r['fv'] = r['rfv'] if r['drafted'] else None
    return data


def X_of(rows, use, sz):
    out = []
    for r in rows:
        if '_b0' not in r: r['_b0'] = R.blocks0(r, sz)
        row = []
        for u in use:
            b = EXTRA[u](r) if u in EXTRA else r['_b0'][u]
            row += list(b.values())
        out.append(row)
    return np.array(out, float)


def cv(data, use_on, use_fv, sz, lam=R.LAM, parts=('on', 'fv')):
    fo = R.folds(data); p_on = np.zeros(len(data)); p_fv = np.zeros(len(data))
    Xo = X_of(data, use_on, sz) if 'on' in parts else None
    Xf = X_of(data, use_fv, sz) if 'fv' in parts else None
    y = np.array([r['on'] for r in data], float); fv = np.array([r['fv'] or 0 for r in data], float)
    for f in range(5):
        tr = fo != f; te = ~tr
        if 'on' in parts:
            a, b = R.logit(Xo[tr], y[tr], lam); p_on[te] = R.sig(a + Xo[te] @ b)
        if 'fv' in parts:
            m = tr & (y == 1); a, b = R.ridge(Xf[m], fv[m], lam); p_fv[te] = a + Xf[te] @ b
    return p_on, p_fv


def losses(data, p_on, p_fv):
    y = np.array([r['on'] for r in data], float); fv = np.array([r['fv'] or 0 for r in data], float)
    ll = -(y * np.log(np.clip(p_on, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p_on, 1e-6, 1)))
    se = (fv - p_fv) ** 2
    return ll, se, y == 1


def paired(d, cls):
    """mean gain, t over recruits, classes won, t over classes"""
    by = np.array([d[cls == c].mean() for c in sorted(set(cls))])
    return {'gain': round(float(d.mean()), 6), 't': round(float(d.mean() / (d.std() / math.sqrt(len(d)) or 1)), 2),
            'won': f'{int((by > 0).sum())}/{len(by)}', 'tClass': round(float(by.mean() / (by.std(ddof=1) / math.sqrt(len(by)) or 1)), 2)}


def test(data, sz, add, base=None, drop=()):
    """the block(s) `add` on top of base (less `drop`), each part"""
    base = base or BASE
    cls = np.array([r['year'] for r in data])
    p0, f0 = cv(data, base['on'], base['fv'], sz)
    l0, s0, m = losses(data, p0, f0)
    out = {}
    uo = [b for b in base['on'] if b not in drop] + list(add); uf = [b for b in base['fv'] if b not in drop] + list(add)
    p1, _ = cv(data, uo, base['fv'], sz, parts=('on',)); l1, _, _ = losses(data, p1, f0)
    out['on'] = paired(l0 - l1, cls)
    _, f1 = cv(data, base['on'], uf, sz, parts=('fv',)); _, s1, _ = losses(data, p0, f1)
    out['fv'] = paired((s0 - s1)[m], cls[m])
    # expected FV: the held-out Spearman with the outcome, by class (the block in both parts)
    e0 = p0 * np.maximum(f0, R.FLOOR) + (1 - p0) * R.FLOOR; e1 = p1 * np.maximum(f1, R.FLOOR) + (1 - p1) * R.FLOOR
    yo = np.array([r['out'] for r in data])
    d = np.array([T.spear(e1[cls == c], yo[cls == c]) - T.spear(e0[cls == c], yo[cls == c]) for c in sorted(set(cls))])
    out['rho'] = {'base': round(T.spear(e0, yo), 4), 'new': round(T.spear(e1, yo), 4), 'won': f'{int((d > 0).sum())}/{len(d)}',
                  't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)) or 1)), 2)}
    return out
