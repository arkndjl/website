#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Next up, CBB freshmen (Noah, Nov 23 2026: "why are no freshmen on the next up list?"). The returner model starts
from last season's line, so a freshman has no row. This fits a first-season model from what is known before he plays.

    python3 scripts/cbb_freshman_bo_research.py [research_seasons.csv]   # -> data/cbb_freshman_bo_fit.json

Rows: a D-I player's first season (no earlier line, class Fr), 2010-2026 (Barttorvik research table). Breakout =
that season at or over the returner model's bar L (shrunk BPM, data/cbb_breakout_fit.json) with 40%+ of minutes,
the same definition as the tab's. Barttorvik lists players who played, so a freshman who never got on the floor is
not a row; the live list carries ranked recruits only (top-300 by On3 / 247), where nearly all play.
Base: recruiting rank (-ln rank, the research table's rg_lrk, 500 = unranked) and an unranked flag.
Candidates, each alone on the base, leave one season out, season-block t, Holm: height (inches), team level (last
season's minutes-weighted BPM of his team), minutes open (share of his team's usage-minutes that left), arriving
transfers' usage-minutes, other top-100 freshmen on his team. Kept = Holm passers, then the calibration table
(held-out) and the share of breakouts in the top decile."""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import cbb_breakout as B  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC = '/mnt/project-files/cbb/backtest/research_seasons.csv'
OUT = os.path.join(ROOT, 'data', 'cbb_freshman_bo_fit.json')
Y0 = 2010
TOP100 = -math.log(100)


def rows(src):
    P = {}
    for r in csv.DictReader(open(src)):
        o = B.line(r)
        if abs(o['bpm']) < 40:
            P[(o['pid'], o['y'])] = o
    first = {}
    for (pid, y) in P:
        first[pid] = min(first.get(pid, 9999), y)
    by_y = defaultdict(list)
    for o in P.values():
        by_y[o['y']].append(o)
    bar = json.load(open(os.path.join(ROOT, 'data', 'cbb_breakout_fit.json')))['breakout']['L']
    R = []
    for y in range(Y0, max(by_y) + 1):
        nxt = {o['pid']: o['team'] for o in by_y[y]}
        T = B.team_tables(by_y.get(y - 1, []), nxt)
        tops = defaultdict(int)
        fr = [o for o in by_y[y] if first[o['pid']] == y and o['cls'] == 1]
        for o in fr:
            if o['rg_lrk'] >= TOP100:
                tops[o['team']] += 1
        for o in fr:
            t = T.get(o['team'], B.NO_TEAM)
            R.append({'y': y, 'hit': 1.0 if B.broke_out(o, bar) else 0.0, 'lrk': o['rg_lrk'], 'unr': o['unranked2'],
                      'ht': o['hti'], 'lvl': t['lvl'], 'vac': t['vac'], 'inc': t['inc'],
                      'top': float(tops[o['team']] - (1 if o['rg_lrk'] >= TOP100 else 0))})
    return R, bar


def logit(X, y, lam=1e-3, it=100):
    """ridge logistic, Newton with step halving (breakout_lib.logit's plain Newton oscillates here: 70% of
    freshmen share one value, unranked)"""
    mu, sd = L.zfit(X)
    A = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    R = lam * np.eye(A.shape[1]) * len(A)
    R[0, 0] = 0
    beta = np.zeros(A.shape[1])
    beta[0] = math.log(y.mean() / (1 - y.mean()))

    def obj(b):
        eta = A @ b
        return float((y * eta - np.logaddexp(0, eta)).sum() - 0.5 * b @ R @ b)
    f = obj(beta)
    for _ in range(it):
        p = L.sig(A @ beta)
        g = A.T @ (y - p) - R @ beta
        H = A.T @ (A * (p * (1 - p))[:, None]) + R
        step, t = np.linalg.solve(H, g), 1.0
        while t > 1e-6 and obj(beta + t * step) < f:
            t /= 2
        beta = beta + t * step
        f2 = obj(beta)
        if abs(f2 - f) < 1e-9:
            break
        f = f2
    b = beta[1:] / sd
    return beta[0] - float(mu @ b), b


CANDS = {'height': ['ht'], 'team level': ['lvl'], 'minutes open': ['vac'], 'arriving transfers': ['inc'],
         'other top-100 freshmen': ['top']}


def main():
    R, bar = rows(sys.argv[1] if len(sys.argv) > 1 else SRC)
    y = np.array([r['hit'] for r in R]); S = np.array([r['y'] for r in R], float)
    col = lambda ks: np.array([[r[k] for k in ks] for r in R], float)
    base = col(['lrk', 'unr'])
    base = np.column_stack([base, np.maximum(0, base[:, 0] - TOP100)])     # top-100 hinge: the top recruits' own slope

    def err(p, te):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))

    def run(X, keep_p=None):
        def fp(tr, te):
            b0, b = logit(X[tr], y[tr])
            p = L.sig(b0 + X[te] @ b)
            if keep_p is not None:
                keep_p[te] = p
            return p
        return L.loso(S, fp, err)
    p0 = np.full(len(y), y.mean())
    flat = L.loso(S, lambda tr, te: np.full(te.sum(), y[tr].mean()), err)
    rb = run(base)
    res = {k: L.compare(rb, run(np.column_stack([base, col(v)]))) for k, v in CANDS.items()}
    L.holm(res)
    keep = [k for k in CANDS if res[k]['pass']]
    X = np.column_stack([base] + [col(CANDS[k]) for k in keep])
    ho = np.zeros(len(y))
    rf = run(X, ho)
    vs_flat = L.compare(flat, rf)
    print('freshmen', len(y), 'rate', round(float(y.mean()), 4), 'bar', bar)
    print(' base vs flat rate', L.compare(flat, rb))
    for k, v in res.items():
        print(' ', k, v)
    print(' kept', keep, 'final vs flat', vs_flat)
    cuts = [0, .02, .05, .1, .2, .35, 1.01]
    calib = []
    for lo, hi in zip(cuts, cuts[1:]):
        m = (ho >= lo) & (ho < hi)
        if m.sum():
            calib.append([lo, min(hi, 1), int(m.sum()), round(float(ho[m].mean()), 3), round(float(y[m].mean()), 3)])
    print(' calibration (held out): [lo, hi, n, mean predicted, actual]', calib)
    o = np.argsort(-ho); top = o[:len(o) // 10]
    share = float(y[top].sum() / y.sum())
    b0, b = logit(X, y)
    names = ['-ln rank', 'unranked', 'top-100 hinge'] + sum([CANDS[k] for k in keep], [])
    json.dump({'source': 'Barttorvik research seasons %d-%d, first D-I season (class Fr)' % (Y0, int(S.max())),
               'definition': 'first season at or over L = %.1f shrunk BPM on 40%%+ of minutes' % bar, 'L': bar,
               'n': len(y), 'rate': round(float(y.mean()), 4), 'base_vs_flat': L.compare(flat, rb), 'tests': res,
               'keep': keep, 'final_vs_flat': vs_flat, 'calib_heldout': calib, 'top_decile_share': round(share, 3),
               'fit': {'cols': names, 'b0': round(float(b0), 6), 'b': [round(float(v), 6) for v in b]}},
              open(OUT, 'w'), indent=1)
    print(' top decile holds', round(share, 3), 'of breakouts; wrote', OUT)


if __name__ == '__main__':
    main()
