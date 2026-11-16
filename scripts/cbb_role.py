#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Barttorvik's role (Pure PG ... C) from a season line's box rates and height, for lines CI rebuilds from game logs
(Barttorvik's season file, which carries his role, is bot-blocked on GitHub's runners, so every freshman's live line
had no role and was scored as a wing in ht_g, Stat+ and role BPM). Multinomial logit on height, assist, rebound,
block, steal, turnover, usage, FT rate and 3PA per 100 over Barttorvik's own roles 2008-26.

    python3 scripts/cbb_role.py --fit PATH/research_seasons.csv    # -> data/cbb_role_fit.json (class-held-out accuracy)
    cbb_role.predict(line) -> role or None
"""
import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_role_fit.json')
X = ['hti', 'ast', 'orb', 'drb', 'blk', 'stl', 'to', 'usg', 'ftr', 'tpa100']
_F = {}


def feats(r):
    try:
        v = [float(r[k]) for k in X]
    except (KeyError, TypeError, ValueError):
        return None
    return v if all(math.isfinite(x) for x in v) else None


def predict(line, hti=None):
    """the likeliest role for a line (dict with X's keys; hti may come separately), None without the fit or inputs"""
    if 'f' not in _F:
        _F['f'] = json.load(open(FIT)) if os.path.exists(FIT) else None
    F = _F['f']
    if not F:
        return None
    v = feats(dict(line, hti=hti if hti is not None else line.get('hti')))
    if v is None:
        return None
    z = [(x - m) / s for x, m, s in zip(v, F['mean'], F['sd'])]
    sc = [b[0] + sum(w * x for w, x in zip(b[1:], z)) for b in F['b']]
    return F['classes'][max(range(len(sc)), key=sc.__getitem__)]


def fit(path):
    import numpy as np
    sys.path.insert(0, HERE)
    from cbb_fit import ROLES, POS3
    rows = [r for r in csv.DictReader(open(path)) if r.get('role') in ROLES and float(r.get('min_per') or 0) >= 10]
    data = [(feats(r), r['role'], int(r['year'])) for r in rows]
    data = [d for d in data if d[0] is not None]
    classes = sorted(ROLES)
    Xa = np.array([d[0] for d in data]); y = np.array([classes.index(d[1]) for d in data]); yr = np.array([d[2] for d in data])
    mu, sd = Xa.mean(0), Xa.std(0) + 1e-9

    def train(Xt, yt, lam=1.0, it=300):
        Z = np.column_stack([np.ones(len(Xt)), (Xt - mu) / sd])
        B = np.zeros((len(classes), Z.shape[1])); Y = np.eye(len(classes))[yt]
        for _ in range(it):                       # gradient descent on the ridge softmax loss
            P = np.exp(Z @ B.T - (Z @ B.T).max(1, keepdims=True)); P /= P.sum(1, keepdims=True)
            G = (P - Y).T @ Z / len(Z) + lam / len(Z) * np.column_stack([np.zeros(len(classes)), B[:, 1:]])
            B -= 2.0 * G
        return B
    acc, acc3, accg = [], [], []
    for s in sorted(set(yr.tolist()))[::3]:          # every third season held out in turn
        tr, te = yr != s, yr == s
        B = train(Xa[tr], y[tr])
        Z = np.column_stack([np.ones(te.sum()), (Xa[te] - mu) / sd])
        p = (Z @ B.T).argmax(1)
        acc += list(p == y[te])
        acc3 += [POS3[classes[a]] == POS3[classes[b]] for a, b in zip(p, y[te])]
        accg += [ROLES[classes[a]] == ROLES[classes[b]] for a, b in zip(p, y[te])]
    B = train(Xa, y)
    out = {'classes': classes, 'feats': X, 'mean': [float(v) for v in mu], 'sd': [float(v) for v in sd], 'b': [[float(v) for v in r] for r in B],
           'n': int(len(y)), 'heldOut': {'role': round(float(np.mean(acc)), 3), 'pos3': round(float(np.mean(acc3)), 3), 'gwb': round(float(np.mean(accg)), 3)}}
    json.dump(out, open(FIT, 'w'), indent=1)
    print('wrote', FIT, out['n'], out['heldOut'])


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit(sys.argv[sys.argv.index('--fit') + 1])
