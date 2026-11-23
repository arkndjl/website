#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""M1: age-adjusted rookie rate aGAR90 = GAR/90 - b (age - 21) (prereg.md amendment 2). -> agar.json here."""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
SD = os.path.join(ROOT, 'static', 'data', 'soccer-war')


def load():
    F = {}
    for S in range(2015, 2027):
        m = {}
        for o in json.load(open(os.path.join(SD, f'{S}.json')))['players']:
            x = m.setdefault(o['p'], {'min': 0, 'gar': 0.0, 'age': o.get('age')})
            x['min'] += o['min']; x['gar'] += o['gar']
            if x['age'] is None:
                x['age'] = o.get('age')
        F[S] = m
    return F


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    F = load()
    R = []
    for S in range(2017, 2025):
        seen = set().union(*[F[s].keys() for s in range(2015, S)])
        for p, x in F[S].items():
            if p in seen or x['min'] < 900 or x['age'] is None:
                continue
            mn = sum(F[S + k].get(p, {}).get('min', 0) for k in (1, 2))
            if mn < 900:
                continue
            g = sum(F[S + k].get(p, {}).get('gar', 0.0) for k in (1, 2))
            R.append((S, p, x['gar'] / x['min'] * 90, x['age'], g / mn * 90))
    S_ = np.array([r[0] for r in R]); r90 = np.array([r[2] for r in R]); age = np.array([r[3] for r in R])
    y = np.array([r[4] for r in R])
    seasons = sorted(set(S_.tolist()))
    pa, pr, bs, sa, sr = np.zeros(len(y)), np.zeros(len(y)), {}, [], []
    for s in seasons:
        tr, te = S_ != s, S_ == s
        X = np.c_[np.ones(tr.sum()), r90[tr], age[tr] - 21]
        c = np.linalg.lstsq(X, y[tr], rcond=None)[0]
        b = -c[2] / c[1]                       # aGAR90 = r90 - b (age - 21) in the rate's own units
        bs[s] = round(float(b), 4)
        a = r90 - b * (age - 21)
        ca = np.polyfit(a[tr], y[tr], 1); cr = np.polyfit(r90[tr], y[tr], 1)
        pa[te] = np.polyval(ca, a[te]); pr[te] = np.polyval(cr, r90[te])
        sa.append(spearman(a[te], y[te])); sr.append(spearman(r90[te], y[te]))
    d = (pa - y) ** 2 - (pr - y) ** 2
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    won = int(sum(d[S_ == s].mean() < 0 for s in seasons))
    X = np.c_[np.ones(len(y)), r90, age - 21]
    c = np.linalg.lstsq(X, y, rcond=None)[0]
    # split half: b from odd vs even seasons
    bh = []
    for m in (S_ % 2 == 1, S_ % 2 == 0):
        cc = np.linalg.lstsq(X[m], y[m], rcond=None)[0]
        bh.append(round(float(-cc[2] / cc[1]), 4))
    res = {'n': len(y), 'seasons': seasons, 'b_all': round(float(-c[2] / c[1]), 4), 'b_loso': bs, 'b_halves': bh,
           'spearman_agar': round(float(np.mean(sa)), 4), 'spearman_raw': round(float(np.mean(sr)), 4),
           'mse_agar': round(float(((pa - y) ** 2).mean()), 5), 'mse_raw': round(float(((pr - y) ** 2).mean()), 5),
           't': round(t, 2), 'won': f'{won}/{len(seasons)}'}
    res['pass'] = bool(res['spearman_agar'] > res['spearman_raw'] and t <= -2 and won >= len(seasons) * 2 / 3)
    print(json.dumps(res))
    json.dump(res, open(os.path.join(HERE, 'agar.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
