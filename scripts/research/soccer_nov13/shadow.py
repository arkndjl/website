#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The close as teacher: a linear map from pre-match features to the close's lean off the game model (shadow_feats.py),
fit on earlier seasons only, added to the model's log goals each way and scored on results (1X2 log loss)."""
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_games as G

RHO = G.params()['rho']


def ll(r, d=0.0):
    pw, pd, pl = G.wdl(r['lh'] * math.exp(d), r['la'] * math.exp(-d), RHO)
    return -math.log(max(1e-9, (pl, pd, pw)[r['res'] + 1]))


def fit(train, keys, lam=1.0):
    v = [r for r in train if r['t'] is not None]
    X = np.array([[r['X'][k] for k in keys] for r in v])
    t = np.array([r['t'] for r in v])
    return np.linalg.solve(X.T @ X + lam * np.eye(len(keys)) * 1e-6, X.T @ t)


def apply(rs, keys, b, cap=0.3):
    return [max(-cap, min(cap, float(sum(bb * r['X'][k] for k, bb in zip(keys, b))))) for r in rs]


def paired(rs, ds):
    diff = [ll(r, d) - ll(r) for r, d in zip(rs, ds)]
    return sum(diff) / len(diff), G.cl_t(diff, [r['day'] for r in rs]), len(diff)


def walk(recs, keys, lo, hi, first=2013):
    """season S in lo..hi scored with the map fit on seasons first..S-1"""
    rs, ds = [], []
    for S in range(lo, hi + 1):
        tr = [r for r in recs if first <= r['S'] < S]
        te = [r for r in recs if r['S'] == S]
        if not tr or not te:
            continue
        b = fit(tr, keys)
        rs += te
        ds += apply(te, keys, b)
    return rs, ds


if __name__ == '__main__':
    recs = pickle.load(open(os.environ['SHADOW_PKL'], 'rb'))
    sets = {'stakes': ['any3', 'any6', 'champ'], 'gm': ['gm'], 'form': ['g3'], 'mlag': ['m3'],
            'stakes+gm': ['any3', 'any6', 'champ', 'gm'], 'stakes+gm+form+mlag': ['any3', 'any6', 'champ', 'gm', 'g3', 'm3'],
            'r3': ['r3'], 'avz': ['avz'], 'mvz': ['mvz'], 'all': sorted(recs[0]['X'])}
    for nm, keys in sets.items():
        rs, ds = walk(recs, keys, 2015, 2022)
        m, t, n = paired(rs, ds)
        by = defaultdict(list)
        for r, d in zip(rs, ds):
            by[r['S']].append(ll(r, d) - ll(r))
        wins = sum(sum(v) < 0 for v in by.values())
        print(f'{nm:22s} tune walk 2015-22 n {n} dLL {m:+.5f} t {t} seasons better {wins}/{len(by)}')
