#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Next up, international prospects (Noah, Nov 23 2026: "add international prospects to BO% too, like Adam Atamna").

    tar xzf /mnt/project-files/research/fpm-nov07/bbref_intl_cache.tgz    # once: scripts/.cache/cbb/intl
    python3 scripts/cbb_intl_bo_research.py      # -> data/cbb_intl_bo_fit.json

Lines: Basketball-Reference totals in the 12 pro leagues scripts/cbb_intl.py pulls, per 100 possessions, Game Score
translated to EuroLeague level with the shipped league offsets (scripts/data/cbb_intl_fit.json factors), a season's
leagues pooled by minutes, shrunk to -4 (replacement) by 100 minutes: 'EL GmSc'.
The bar L = the 80th percentile of EL GmSc among 500+ minute seasons (as the college bar is the 80th of real roles).
Rows: early-career players (season 1-3 of his line in these leagues, first season after the league's first pulled
one, so a veteran arriving with a newly pulled league isn't counted as new), 100+ minutes, never at the bar so far,
with a line next season. Breakout = next season 500+ minutes at or over L. Bbref has no ages on these pages, so career
season stands in for age. Base: EL GmSc, ln minutes. Candidates (alone, leave one season out, Holm): career season,
league level (minutes-weighted offset of where he played), EuroLeague/EuroCup share. Calibration held out."""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import cbb_intl as I  # noqa: E402
from cbb_freshman_bo_research import logit  # noqa: E402

OUT = os.path.join(I.D.ROOT, 'data', 'cbb_intl_bo_fit.json')
K, REP, REG = 100.0, -4.0, 500.0


def lines():
    LF = json.load(open(I.FIT))['factors']
    Lg = I.load_leagues()
    S = defaultdict(dict)       # slug -> season -> {mp, gm (EL GmSc raw pooled), lvl, el}
    for (lg, y), d in Lg.items():
        for slug, r in d['players'].items():
            if r['mp'] <= 0:
                continue
            x = I.per100(r, d['pace'])
            t = I.translate(x, lg, LF)
            o = S[slug].setdefault(y, {'mp': 0.0, 'gw': 0.0, 'lv': 0.0, 'el': 0.0, 'lg0': lg})
            o['mp'] += r['mp']; o['gw'] += r['mp'] * t['gmsc']; o['lv'] -= r['mp'] * LF['gmsc'][lg]
            o['el'] += r['mp'] if lg in ('euroleague', 'eurocup') else 0.0
    for slug, ss in S.items():
        for y, o in ss.items():
            o['gm'] = (o['gw'] + REP * K) / (o['mp'] + K)
            o['lvl'] = o['lv'] / o['mp']
            o['elsh'] = o['el'] / o['mp']
    return S


def table(S):
    reg = [o['gm'] for ss in S.values() for o in ss.values() if o['mp'] >= REG]
    bar = round(float(np.percentile(reg, 80)), 2)
    R = []
    for slug, ss in S.items():
        ys = sorted(ss)
        y0 = ys[0]
        if y0 <= I.LEAGUES[ss[y0]['lg0']][1]:
            continue                          # first seen in a league's first pulled season: may be a veteran
        best = -99.0
        for y in ys:
            o = ss[y]
            c = y - y0 + 1
            best = max(best, o['gm']) if o['mp'] >= 100 else best
            if c > 3 or o['mp'] < 100 or best >= bar or y + 1 not in ss:
                continue
            b = ss[y + 1]
            R.append({'slug': slug, 'y': y, 'c': float(c), 'gm': o['gm'], 'lm': math.log(o['mp']), 'lvl': o['lvl'],
                      'el': o['elsh'], 'hit': 1.0 if b['mp'] >= REG and b['gm'] >= bar else 0.0})
    return R, bar


CANDS = {'career season': ['c'], 'league level': ['lvl'], 'EuroLeague share': ['el']}


def main():
    S = lines()
    R, bar = table(S)
    y = np.array([r['hit'] for r in R]); Sy = np.array([r['y'] + 1 for r in R], float)
    col = lambda ks: np.array([[r[k] for k in ks] for r in R], float)  # noqa: E731
    base = col(['gm', 'lm'])

    def err(p, te):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))

    def run(X, keep=None):
        def fp(tr, te):
            b0, b = logit(X[tr], y[tr])
            p = L.sig(b0 + X[te] @ b)
            if keep is not None:
                keep[te] = p
            return p
        return L.loso(Sy, fp, err)
    flat = L.loso(Sy, lambda tr, te: np.full(te.sum(), y[tr].mean()), err)
    rb = run(base)
    res = {k: L.compare(rb, run(np.column_stack([base, col(v)]))) for k, v in CANDS.items()}
    L.holm(res)
    keep = [k for k in CANDS if res[k]['pass']]
    X = np.column_stack([base] + [col(CANDS[k]) for k in keep])
    ho = np.zeros(len(y))
    rf = run(X, ho)
    cuts = [0, .02, .05, .1, .2, .35, 1.01]
    calib = [[lo, min(hi, 1), int(m.sum()), round(float(ho[m].mean()), 3), round(float(y[m].mean()), 3)]
             for lo, hi in zip(cuts, cuts[1:]) for m in [(ho >= lo) & (ho < hi)] if m.sum()]
    o = np.argsort(-ho)
    share = float(y[o[:len(o) // 10]].sum() / max(1, y.sum()))
    b0, b = logit(X, y)
    print('rows', len(y), 'rate', round(float(y.mean()), 4), 'bar', bar, 'base vs flat', L.compare(flat, rb))
    for k, v in res.items():
        print(' ', k, v)
    print(' kept', keep, 'final vs flat', L.compare(flat, rf), '\n calibration', calib, '\n top decile share', round(share, 3))
    json.dump({'source': 'Basketball-Reference international totals, 12 leagues, EuroLeague-level Game Score per 100',
               'L': bar, 'k': K, 'rep': REP, 'reg': REG, 'n': len(y), 'rate': round(float(y.mean()), 4),
               'base_vs_flat': L.compare(flat, rb), 'tests': res, 'keep': keep, 'final_vs_flat': L.compare(flat, rf),
               'calib_heldout': calib, 'top_decile_share': round(share, 3),
               'fit': {'cols': ['EL GmSc', 'ln min'] + sum([CANDS[k] for k in keep], []), 'b0': round(float(b0), 6),
                       'b': [round(float(v), 6) for v in b]}}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
