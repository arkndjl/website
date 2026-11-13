#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Fit and test the NFL rate metric (rXP/60 raw, pXP/60 predictive) on the board's past seasons.

    python3 scripts/nfl_rate_research.py --prep    # replay the board for 2016-25 (scripts/.cache/nfl/rate_rows_<y>.json)
    python3 scripts/nfl_rate_research.py           # fit + test: data/nfl_rate_fit.json, history scripts/data/nfl_rate_hist.json.gz

rXP/60: points of team margin over an average regular at the player's sub-position per 60 scrimmage snaps, from the
board's WAA without special teams: (WAA - ST WAR) x 35.5 / snaps x 60.
pXP/60: the rate that carries to next season. Pre-registered forms, each scored on next season's rXP/60 (players with
100+ snaps next season, weighted by next season's snaps), leaving one target season out; K and the Marcel weights are
chosen inside the training seasons only:
    mean     the sub-position's snap-weighted rate (training seasons)
    raw      this season's rXP/60
    shrink1  this season's rate shrunk to the sub-position mean by snaps: (r s + K m) / (s + K), K per position group
    marcel   seasons S, S-1, S-2 at snap weights 1 / .7 / .5, shrunk the same way, K per group
    marcelP  marcel with the prior m by playing time: the sub-position mean + slope x this season's share (part-timers
             are worse than regulars, so the prior moves with the snaps a team gives him)
    marcelA  marcelP + an age hinge per group at 27, on the shrunk rate (fit on the training seasons' residuals)
    marcelM  marcel with the prior m moved by the market's read of him (scripts/nfl_market.py): his draft slot on a
             rookie deal (-ln pick), the cap share of his contract in force after it (ln cap %), a slope per group and
             kind fit like marcelP's (pre-registered, scripts/research/nfl_nov13/PREREG.md C1: weighted
             MSE .2485 -> .2438, paired t -4.85, 9 of 9 seasons, calibration slope 1.00)
The live form walks the nested chain shrink1 -> marcel -> marcelP -> marcelA, a step taken only when it beats the
form before it at paired t <= -2; marcelM then replaces it on the same bar. Kept: that form if it beats raw AND mean with paired t <= -2 (player-seasons, weighted;
against raw on players with 100+ snaps this season: a few one-snap rates sit 50+ points out and swamp the all-rows t,
which is reported as vsRaw), wins at least 7 of the 9 held-out seasons against raw, and its calibration slope on next season is .8-1.2.
After each season: extend YEARS, rerun --prep (adds the new season) and the fit, so the history file rolls forward
(the live build reads seasons S-1 and S-2 from it).
Also written: year-to-year r of the raw rate by group and its stabilization point (snaps where r reaches .5, the K
in s / (s + K) that fits the r by snaps bin), and the qualified line.
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import nfl_rate as R   # noqa: E402
import nfl_market as MK   # noqa: E402

CACHE = os.path.join(HERE, '.cache', 'nfl')
OUT = os.path.join(ROOT, 'data', 'nfl_rate_fit.json')
YEARS = list(range(2016, 2026))
KS = (50, 100, 200, 300, 450, 650, 900, 1300, 1800, 2600, 3600)
MIN_NEXT = 100


def prep():
    import nfl_war as W
    os.makedirs(CACHE, exist_ok=True)
    for y in YEARS:
        out, _, _ = W.board(y)
        rows = [R.row_of(p) for p in out]
        rows = [r for r in rows if r]
        with open(os.path.join(CACHE, f'rate_rows_{y}.json'), 'w') as f:
            json.dump(rows, f)
        print(y, len(rows))


def load():
    D = {}
    for y in YEARS:
        with open(os.path.join(CACHE, f'rate_rows_{y}.json')) as f:
            D[y] = {r['id']: r for r in json.load(f)}
    return D


def wmean(xs, ws):
    s = sum(ws)
    return sum(x * w for x, w in zip(xs, ws)) / s if s else 0.0


def means(D, ys):
    """sub-position snap-weighted mean rate, and the prior's slope on share per group (weighted LS of rate on share)"""
    acc = defaultdict(lambda: [0.0, 0.0])
    for y in ys:
        for r in D[y].values():
            acc[r['sub']][0] += r['pts']; acc[r['sub']][1] += r['sn']
    m = {s: a[0] / a[1] * 60 for s, a in acc.items() if a[1]}
    # slope: rate - m on share, weighted by snaps
    num, den = defaultdict(float), defaultdict(float)
    sx = defaultdict(lambda: [0.0, 0.0])
    for y in ys:
        for r in D[y].values():
            sx[r['grp']][0] += r['shr'] * r['sn']; sx[r['grp']][1] += r['sn']
    xb = {g: a[0] / a[1] for g, a in sx.items()}
    for y in ys:
        for r in D[y].values():
            g = r['grp']
            dx = r['shr'] - xb[g]
            num[g] += r['sn'] * dx * (R.rate(r) - m[r['sub']]); den[g] += r['sn'] * dx * dx
    b = {g: num[g] / den[g] if den[g] else 0.0 for g in num}
    return m, b, xb


_SIG = {}


def sig(y, pid):
    k = (y, pid)
    if k not in _SIG:
        _SIG[k] = MK.signal(pid, y)
    return _SIG[k]


def mslopes(D, ys, m):
    """the market prior: per group and kind (r rookie deal, v later contract) the signal's snap-weighted mean and the
    weighted LS slope of rate - sub-position mean on it"""
    acc = defaultdict(lambda: [0.0, 0.0])
    for y in ys:
        for pid, r in D[y].items():
            s = sig(y, pid)
            if s:
                a = acc[(r['grp'], s[0])]; a[0] += s[1] * r['sn']; a[1] += r['sn']
    xb = {k: a[0] / a[1] for k, a in acc.items() if a[1]}
    num, den = defaultdict(float), defaultdict(float)
    for y in ys:
        for pid, r in D[y].items():
            s = sig(y, pid)
            if s:
                k = (r['grp'], s[0]); dx = s[1] - xb[k]
                num[k] += r['sn'] * dx * (R.rate(r) - m[r['sub']]); den[k] += r['sn'] * dx * dx
    return xb, {k: num[k] / den[k] if den[k] else 0.0 for k in num}


def pred(D, y, pid, form, K, m, b, xb, age_c=None, wts=R.MARCEL, mq=None):
    r = D[y][pid]
    sub, g = r['sub'], r['grp']
    prior = m.get(sub, 0.0)
    if form == 'marcelM' and mq:
        s = sig(y, pid)
        if s and (g, s[0]) in mq[1]:
            prior += mq[1][(g, s[0])] * (s[1] - mq[0][(g, s[0])])
    if form in ('marcelP', 'marcelA'):
        prior += b.get(g, 0.0) * (r['shr'] - xb.get(g, 0.0))
    if form == 'mean':
        return m.get(sub, 0.0)
    if form == 'raw':
        return R.rate(r)
    k = K[g]
    if form == 'shrink1':
        return (r['pts'] * 60 + k * prior) / (r['sn'] + k)
    P, S = 0.0, 0.0
    for i, w in enumerate(wts):
        h = D.get(y - i, {}).get(pid)
        if h and h['grp'] == g:
            P += w * h['pts'] * 60; S += w * h['sn']
    v = (P + k * prior) / (S + k)
    if form == 'marcelA' and age_c and r.get('age') is not None:
        c = age_c.get(g, (0.0, 0.0))
        a = r['age']
        v += c[0] * max(0.0, a - 27) + c[1] * max(0.0, 27 - a)
    return v


def pairs(D, ys):
    for y in ys:
        if y + 1 not in D:
            continue
        for pid, r in D[y].items():
            n = D[y + 1].get(pid)
            if n and n['sn'] >= MIN_NEXT and n['grp'] == r['grp']:
                yield y, pid, R.rate(n), n['sn']


def sse(D, ys, form, K, m, b, xb, age_c=None, grp=None, mq=None):
    s, w = 0.0, 0.0
    for y, pid, t, sn in pairs(D, ys):
        if grp and D[y][pid]['grp'] != grp:
            continue
        e = pred(D, y, pid, form, K, m, b, xb, age_c, mq=mq) - t
        s += sn * e * e; w += sn
    return s / w if w else 0.0


def fit_k(D, ys, form, m, b, xb, mq=None):
    K = {g: 600 for g in R.GROUPS}
    for g in R.GROUPS:
        K[g] = min(KS, key=lambda k: sse(D, ys, form, {**K, g: k}, m, b, xb, grp=g, mq=mq))
    return K


def fit_age(D, ys, K, m, b, xb):
    """per group OLS of (target - marcelP) on (age-27)+, (27-age)+, weighted by next snaps"""
    import numpy as np
    out = {}
    for g in R.GROUPS:
        X, Y, Wt = [], [], []
        for y, pid, t, sn in pairs(D, ys):
            r = D[y][pid]
            if r['grp'] != g or r.get('age') is None:
                continue
            X.append([max(0.0, r['age'] - 27), max(0.0, 27 - r['age'])])
            Y.append(t - pred(D, y, pid, 'marcelP', K, m, b, xb)); Wt.append(sn)
        if len(Y) < 50:
            out[g] = (0.0, 0.0); continue
        X, Y, Wt = np.array(X), np.array(Y), np.sqrt(np.array(Wt))
        c, *_ = np.linalg.lstsq(X * Wt[:, None], Y * Wt, rcond=None)
        out[g] = (float(c[0]), float(c[1]))
    return out


FORMS = ['mean', 'raw', 'shrink1', 'marcel', 'marcelP', 'marcelA', 'marcelM']


def stability(D):
    """year-to-year r of the raw rate (same group both seasons, 100+ snaps both), by group; K where r = s/(s+K) fits
    the r in snap bins (harmonic mean of the two seasons' snaps)"""
    out = {}
    for g in R.GROUPS:
        P = []
        for y in YEARS[:-1]:
            for pid, r in D[y].items():
                n = D[y + 1].get(pid)
                if r['grp'] == g and n and n['grp'] == g and r['sn'] >= 100 and n['sn'] >= 100:
                    P.append((R.rate(r), R.rate(n), 2 / (1 / r['sn'] + 1 / n['sn'])))
        bins = [(100, 300), (300, 600), (600, 900), (900, 2000)]
        rb = []
        for lo, hi in bins:
            Q = [p for p in P if lo <= p[2] < hi]
            if len(Q) < 30:
                continue
            rb.append((sum(q[2] for q in Q) / len(Q), corr([q[0] for q in Q], [q[1] for q in Q]), len(Q)))
        k = min(KS + (5000, 8000), key=lambda k: sum(n * (rr - s / (s + k)) ** 2 for s, rr, n in rb)) if rb else None
        out[g] = {'r': round(corr([p[0] for p in P], [p[1] for p in P]), 3), 'n': len(P), 'stab': k,
                  'bins': [{'snaps': round(s), 'r': round(rr, 3), 'n': n} for s, rr, n in rb]}
    return out


def corr(a, b):
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a)); sb = math.sqrt(sum((x - mb) ** 2 for x in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else 0.0


def main():
    D = load()
    targets = [y for y in YEARS[:-1]]
    res = {f: {'err': [], 'by': {}} for f in FORMS}
    chosen = {}
    for ty in targets:
        tr = [y for y in targets if y != ty]
        m, b, xb = means(D, tr)
        mq = mslopes(D, tr, m)
        Ks = {}
        for f in FORMS:
            K = fit_k(D, tr, f, m, b, xb, mq=mq) if f not in ('mean', 'raw') else {g: 0 for g in R.GROUPS}
            if f == 'marcelA':
                K = Ks['marcelP']
            Ks[f] = K
        age_c = fit_age(D, tr, Ks['marcelP'], m, b, xb)
        chosen[ty] = {'K': Ks, 'age': age_c, 'mq': mq}
        for f in FORMS:
            s, w = 0.0, 0.0
            for y, pid, t, sn in pairs(D, [ty]):
                e = pred(D, y, pid, f, Ks[f], m, b, xb, age_c, mq=mq) - t
                res[f]['err'].append((sn, e * e, y, pid))
                s += sn * e * e; w += sn
            res[f]['by'][ty] = s / w
        print(ty, {f: round(res[f]['by'][ty], 3) for f in FORMS})
    summ = {}
    for f in FORMS:
        e = res[f]['err']
        summ[f] = {'wmse': round(sum(a * b_ for a, b_, *_ in e) / sum(a for a, *_ in e), 4)}

    def paired(f, g, keep=None):
        d = [(a[0], a[1] - b_[1]) for a, b_ in zip(res[f]['err'], res[g]['err']) if keep is None or keep(D[a[2]][a[3]])]
        W = sum(x for x, _ in d)
        mu = sum(x * v for x, v in d) / W
        var = sum(x * (v - mu) ** 2 for x, v in d) / W
        neff = W ** 2 / sum(x * x for x, _ in d)
        return round(mu / math.sqrt(var / neff), 2), sum(1 for y in targets if res[f]['by'][y] < res[g]['by'][y])

    for f in FORMS:   # qualified this season (the rate view's players)
        e = [x for x in res[f]['err'] if D[x[2]][x[3]]['shr'] >= R.QUAL]
        summ[f]['wmseQual'] = round(sum(a * b_ for a, b_, *_ in e) / sum(a for a, *_ in e), 4)
    cands = ['shrink1', 'marcel', 'marcelP', 'marcelA', 'marcelM']
    # parsimony: each nested step (shrink1 -> marcel -> marcelP -> marcelA) must beat the one before at paired t <= -2
    best = 'shrink1'
    for f in ('marcel', 'marcelP', 'marcelA'):
        if paired(f, best)[0] <= -2:
            best = f
    if MK.load() and paired('marcelM', best)[0] <= -2 and paired('marcelM', best)[1] >= 7:   # the market prior, same bar
        best = 'marcelM'
    for f in cands:
        summ[f]['vsRaw'] = dict(zip(('t', 'wins'), paired(f, 'raw')))
        summ[f]['vsMean'] = dict(zip(('t', 'wins'), paired(f, 'mean')))
        summ[f]['vsRaw100'] = paired(f, 'raw', lambda r: r['sn'] >= 100)[0]   # raw on 100+ snaps this season
        summ[f]['vsRawQual'] = paired(f, 'raw', lambda r: r['shr'] >= R.QUAL)[0]
        dd = [res[f]['by'][y] - res['raw']['by'][y] for y in targets]   # season-level paired t (the raw tail is heavy)
        mu = sum(dd) / len(dd); sdv = math.sqrt(sum((x - mu) ** 2 for x in dd) / (len(dd) - 1))
        summ[f]['vsRawSeasonT'] = round(mu / (sdv / math.sqrt(len(dd))), 2)
        if f != 'shrink1':
            summ[f]['vsShrink1'] = dict(zip(('t', 'wins'), paired(f, 'shrink1')))
    # calibration slope of the best form, pooled held out
    m_all, b_all, xb_all = means(D, targets)
    mq_all = mslopes(D, targets, m_all)
    K_all = fit_k(D, targets, best if best != 'marcelA' else 'marcelP', m_all, b_all, xb_all, mq=mq_all)
    age_all = fit_age(D, targets, K_all, m_all, b_all, xb_all)
    P = []
    for ty in targets:
        tr = [y for y in targets if y != ty]
        m, b, xb = means(D, tr)
        for y, pid, t, sn in pairs(D, [ty]):
            P.append((pred(D, y, pid, best, chosen[ty]['K'][best], m, b, xb, chosen[ty]['age'], mq=chosen[ty]['mq']), t, sn))
    W = sum(p[2] for p in P)
    mx = sum(p[0] * p[2] for p in P) / W; my = sum(p[1] * p[2] for p in P) / W
    slope = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in P) / sum(p[2] * (p[0] - mx) ** 2 for p in P)
    v = summ[best]['vsRaw']
    for f, g in (('marcelP', 'marcel'), ('marcelA', 'marcel'), ('marcelA', 'marcelP'), ('marcelM', 'marcel')):
        summ[f]['vs_' + g] = dict(zip(('t', 'wins'), paired(f, g)))
    kept = summ[best]['vsRaw100'] <= -2 and summ[best]['vsMean']['t'] <= -2 and v['wins'] >= 7 and 0.8 <= slope <= 1.2
    stab = stability(D)
    fit = {'asof': __import__('datetime').date.today().isoformat(), 'years': [YEARS[0], YEARS[-1]], 'minNext': MIN_NEXT,
           'form': best, 'kept': kept, 'slope': round(slope, 3), 'forms': summ,
           'byseason': {f: {str(y): round(res[f]['by'][y], 3) for y in targets} for f in FORMS},
           'model': {'K': K_all, 'm': {k: round(v_, 4) for k, v_ in m_all.items()}, 'b': {k: round(v_, 4) for k, v_ in b_all.items()},
                     'xb': {k: round(v_, 4) for k, v_ in xb_all.items()},
                     'age': {k: [round(c, 4) for c in v_] for k, v_ in age_all.items()} if best == 'marcelA' else {},
                     'mq': {'xb': {f'{g}:{k}': round(v_, 4) for (g, k), v_ in mq_all[0].items()},
                            'b': {f'{g}:{k}': round(v_, 4) for (g, k), v_ in mq_all[1].items()}} if best == 'marcelM' else {},
                     'marcel': list(R.MARCEL), 'per': R.PER, 'qual': R.QUAL},
           'stability': stab}
    with open(OUT, 'w') as f:
        json.dump(fit, f, indent=1)
    # history the live build reads for the Marcel seasons (last three seasons)
    H = {str(y): {pid: [r['sn'], round(r['pts'], 3), r['grp']] for pid, r in D[y].items()} for y in YEARS[-3:]}
    with gzip.open(os.path.join(HERE, 'data', 'nfl_rate_hist.json.gz'), 'wt') as f:
        json.dump(H, f, separators=(',', ':'))
    print(json.dumps({k: fit[k] for k in ('form', 'kept', 'slope', 'forms')}, indent=1))
    print(json.dumps({g: (s['r'], s['stab']) for g, s in stab.items()}))


if __name__ == '__main__':
    prep() if '--prep' in sys.argv else main()
