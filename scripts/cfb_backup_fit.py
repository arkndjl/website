#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ESPN roster backups graded on what recruits became in the NFL (Noah Nov 18 2026; test + prereg in
scripts/research/backups_nov18/).

    python3 scripts/cfb_backup_fit.py            # rows from scripts/cfb_recruit_retarget.py dataset() (cached pulls)
    python3 scripts/cfb_backup_fit.py --rows F   # rows saved by scripts/research/backups_nov18/build.py

A backup (a roster player the board doesn't grade: no snaps worth a PFN line) is graded by the drivers he has:
position, height, weight and BMI against the position, his 247 composite and its national rank, and his school's
level. The fit is a hurdle on the 2011-19 ESPN signees: P(drafted) (ridge logit) x realized FV if drafted (ridge),
the rest at the 20 floor, so its value is the expected realized FV, the board's headline mean. It replaces the
earlier ridge copy of the board's own grade on rows that only lacked a snap count (1 QB in 1,723 rows set every
backup QB's level). Held out by class: MSE 71.7 -> 44.5, 9/9 classes, t 18.7.
Writes data/cfb_backup_fit.json, read by scripts/cfb_espn_backups.mjs (same features, same order).
"""
import gzip
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'cfb_backup_fit.json')
POSS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']
LAM = 30.0   # standardized ridge penalty, as the recruit fits (scripts/cfb_recruit_fit.py LAM)
NAMES = [*('pos_' + p for p in POSS), 'htz', 'wtz', 'bmiz', 'rating', 'rated', 'lrank', 'FCS', 'G5']


def norms(rows):
    out = {}
    for p in POSS:
        hs = [r['ht'] for r in rows if r['g'] == p and r['ht']]; ws = [r['wt'] for r in rows if r['g'] == p and r['wt']]
        bm = [703 * r['wt'] / r['ht'] ** 2 for r in rows if r['g'] == p and r['ht'] and r['wt']]
        out[p] = [[round(float(np.mean(v)), 3), round(float(np.std(v)), 3)] for v in (hs, ws, bm)]
    return out


def feats(n, g, ht, wt, comp, crank, level):
    """n: norms; g: position group; ht inches; wt lb; comp: 247 composite 0-1 or None; crank: its national rank;
    level: 'P4' | 'G5' | 'FCS'"""
    c3 = lambda v: max(-3.0, min(3.0, v)); m = n[g]
    hz = c3((ht - m[0][0]) / m[0][1]) if ht else 0.0
    wz = c3((wt - m[1][0]) / m[1][1]) if wt else 0.0
    bz = c3((703 * wt / ht ** 2 - m[2][0]) / m[2][1]) if ht and wt else 0.0
    has = comp is not None
    return [*(float(g == p) for p in POSS), hz, wz, bz, (comp - .85) * 10 if has else 0.0, float(has),
            6 - math.log(crank) if has and crank else 0.0, float(level == 'FCS'), float(level == 'G5')]


def _std(X):
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1
    return mu, sd


def logit(X, y, lam=LAM, it=80):
    """ridge logit on standardized X; coefficients returned on the raw scale [b0, b]"""
    mu, sd = _std(X); A = np.c_[np.ones(len(X)), (X - mu) / sd]
    b = np.zeros(A.shape[1]); b[0] = math.log(y.mean() / (1 - y.mean())); P = np.eye(A.shape[1]) * lam; P[0, 0] = 0
    for _ in range(it):
        q = 1 / (1 + np.exp(-np.clip(A @ b, -30, 30)))
        st = np.linalg.solve(A.T @ (A * (q * (1 - q) + 1e-9)[:, None]) + P, A.T @ (q - y) + P @ b)
        b -= np.clip(st, -1, 1)
        if np.abs(st).max() < 1e-8: break
    return float(b[0] - (b[1:] * mu / sd).sum()), b[1:] / sd


def ridge(X, y, lam=LAM):
    mu, sd = _std(X); A = np.c_[np.ones(len(X)), (X - mu) / sd]; P = np.eye(A.shape[1]) * lam; P[0, 0] = 0
    b = np.linalg.solve(A.T @ A + P, A.T @ y)
    return float(b[0] - (b[1:] * mu / sd).sum()), b[1:] / sd


def fit(rows, n=None):
    n = n or norms(rows)
    X = np.array([feats(n, r['g'], r['ht'], r['wt'], r.get('comp'), r.get('cRank'), r['level']) for r in rows])
    on = np.array([r['drafted'] for r in rows], float); y = np.array([r['rfv'] for r in rows])
    a0, a = logit(X, on); d = on == 1; f0, f = ridge(X[d], y[d])
    return {'names': NAMES, 'norms': n, 'on': {'b0': round(a0, 5), 'coef': [round(float(v), 5) for v in a]},
            'fv': {'b0': round(f0, 4), 'coef': [round(float(v), 4) for v in f]}}


def predict(m, x):
    x = np.atleast_2d(x)
    p = 1 / (1 + np.exp(-(m['on']['b0'] + x @ np.array(m['on']['coef']))))
    f = np.maximum(20, m['fv']['b0'] + x @ np.array(m['fv']['coef']))
    return p * f + (1 - p) * 20


def load_rows(argv):
    if '--rows' in argv:
        rows = json.load(gzip.open(argv[argv.index('--rows') + 1], 'rt'))['rows']
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import cfb_recruit_retarget as T
        rows = T.dataset()[0]
    return [r for r in rows if r['g'] in POSS]


if __name__ == '__main__':
    rows = load_rows(sys.argv)
    m = fit(rows)
    m.update({'classes': [min(r['year'] for r in rows), max(r['year'] for r in rows)], 'n': len(rows),
              'drafted': int(sum(r['drafted'] for r in rows)), 'P4': ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12'],
              'test': json.load(open(os.path.join(ROOT, 'scripts', 'research', 'backups_nov18', 'results.json')))['primary']
              if os.path.exists(os.path.join(ROOT, 'scripts', 'research', 'backups_nov18', 'results.json')) else None})
    json.dump(m, open(OUT, 'w'), indent=1)
    print('wrote', OUT, 'rows', m['n'], 'drafted', m['drafted'])
