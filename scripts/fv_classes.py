# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Draft classes ranked by strength (the all-time FV tab: CFB, CBB, hockey prospects).

Every draft class from the all-time FV lists (data/fv_alltime.json: each player once, at his draft-day grade), ranked on
  top     the class's 10 best draft-day grades, each as points over replacement: xP = E[(Out - 40)+ | FV], the FV
          points over 40 that grades like his became
  depth   the next 40 (grades 11-50)
  overall top + depth (the class's 50 best)
50 is about the number of players on the lists who go in the first two rounds of the NBA or NHL draft, or in the first
three NFL rounds at the seven CFB positions on the list; a fixed 50 keeps the lists' pool size (FBS seasons graded,
the box-score years thinner) out of the ranks. Became = the same sums on what the careers became (Out - 40)+, the
class's 10 and 50 best careers (a re-draft), shown once the class has an outcome.

Era: xP is fit by grading era (CFB box-score stand-ins, drafts 2015-19, then PFN; CBB out of sample by class through
2016, forward after; hockey one era), Out on (mu = c + b (FV - 40), sd) with E[(Y - 40)+] read from the normal, and a
class with an outcome takes the fit without its own class. A noisier era's grade of 45 is worth more than a sharper
era's 45, because more of them land well above 40 (the box-score classes read thin on one pooled fit). The check:
  calib  log(sum (Out - 40)+ / sum xP) over every listed player of a class (same pool both sides, own class held out),
         its trend on the draft year and its t; pooled fit vs fit by era
  era    Kruskal-Wallis H of the overall ranks across three era bins (earliest, middle, latest third of the classes)
         against the era-blind 95% line (10,000 shuffles); pass = H under the line
Ranks are descriptive (no held-out gate); the calibration and era checks are the sanity checks.

    python3 scripts/fv_classes.py      (after scripts/fv_alltime.py, which calls it) -> data/fv_classes.json
"""
import json
import math
import os
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
OUT = P('data', 'fv_classes.json')
REPL = 40.0         # replacement: FV 40
TOPN, DEPN = 10, 50
# grading eras: class year -> era (each sport's own board history; see the docstring)
ERA = {'cfb': lambda y: 'box' if y <= 2019 else 'pfn', 'cbb': lambda y: 'oof' if y <= 2016 else 'fwd', 'hockey': lambda y: 'one'}
ERA_LAB = {'box': 'box-score line (drafts 2015-19)', 'pfn': 'PFN line (drafts 2020 on)', 'oof': 'held out by class (2009-16)',
           'fwd': 'forward from the 2009-16 fit (2017 on)', 'one': 'one era, each class held out'}


def year_of(sp, r):
    if sp == 'cfb': return r.get('draft') or r['last'] + 1
    return r.get('draft') or r['season']


def ncdf(z):
    # Abramowitz-Stegun 7.1.26 erf, |err| < 1.5e-7
    x = np.abs(z) / math.sqrt(2); t = 1 / (1 + 0.3275911 * x)
    e = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return 0.5 * (1 + np.sign(z) * e)


def ex_over(x, th):
    """E[(Y - 40)+] with Y ~ N(c + b (x - 40), s)"""
    c, b, s = th
    mu = c + b * (np.asarray(x, float) - REPL); d = (mu - REPL) / s
    return (mu - REPL) * ncdf(d) + s * np.exp(-d * d / 2) / math.sqrt(2 * math.pi)


def fit(x, y):
    """least squares of (Out - 40)+ on ex_over, coarse grid then two finer passes"""
    x, y = np.asarray(x, float), np.clip(np.asarray(y, float) - REPL, 0, None)
    best = None
    C, B, S = np.linspace(10, 50, 21), np.linspace(.2, 1.6, 15), np.linspace(3, 25, 12)
    for _ in range(3):
        for c in C:
            for b in B:
                for s in S:
                    l = float(((ex_over(x, (c, b, s)) - y) ** 2).sum())
                    if best is None or l < best[0]: best = (l, (c, b, s))
        c0, b0, s0 = best[1]; dc, db, ds = (C[1] - C[0]), (B[1] - B[0]), (S[1] - S[0])
        C, B, S = np.linspace(c0 - dc, c0 + dc, 9), np.linspace(max(.05, b0 - db), b0 + db, 9), np.linspace(max(1, s0 - ds), s0 + ds, 9)
    return best[1]


def kw(ranks, bins):
    """Kruskal-Wallis H of ranks by bin"""
    n = len(ranks); m = (n + 1) / 2
    return 12 / (n * (n + 1)) * sum(len(g) * (np.mean(g) - m) ** 2 for g in (ranks[bins == b] for b in np.unique(bins)))


def era_gate(years, score, rng):
    o = np.argsort(years); s = np.asarray(score, float)[o]
    bins = np.array([min(2, i * 3 // len(s)) for i in range(len(s))])
    rk = np.argsort(np.argsort(-s)) + 1.0
    h = kw(rk, bins)
    null = [kw(rng.permutation(rk), bins) for _ in range(10000)]
    return round(float(h), 2), round(float(np.quantile(null, .95)), 2)


def trend(years, g):
    years, g = np.asarray(years, float), np.asarray(g, float)
    b = np.polyfit(years, g, 1); res = g - np.polyval(b, years)
    se = math.sqrt(res.var(ddof=2) / ((years - years.mean()) ** 2).sum())
    return round(float(b[0]), 4), round(float(b[0] / se), 2)


def realized_pool(sp, rows):
    """rows the Became side reads: the listed players, plus (hockey) the later picks the past list carries for reaching 45+"""
    if sp != 'hockey': return rows
    H = json.load(open(P('data', 'hockey.json')))['past']
    have = {(r['name'], r['draft']) for r in rows}
    return rows + [{'name': r['name'], 'draft': r['year'], 'season': r['year'], 'fvx': r.get('fvx', r['fv']), 'out': r['out'], 'team': r['team'], 'pos': r['pos']}
                   for r in H if (r['name'], r['year']) not in have and r.get('out') is not None]


def sport(sp, d, rng):
    rows = [r for r in d['rows'] if r.get('fvx') is not None]
    by = defaultdict(list)
    for r in rows: by[year_of(sp, r)].append(r)
    rp = defaultdict(list)
    for r in realized_pool(sp, rows): rp[year_of(sp, r)].append(r)
    years = sorted(by)
    mature = {y for y in years if sum(r.get('out') is not None for r in by[y]) >= .9 * len(by[y])}
    era = ERA[sp]
    # fits: pooled (one era) and by era, each class with an outcome fit without its own class
    def fits(eraf):
        out = {}
        for y in years:
            tr = [r for z in mature if eraf(z) == eraf(y) and z != y for r in by[z] if r.get('out') is not None]
            out[y] = fit([r['fvx'] for r in tr], [r['out'] for r in tr])
        return out
    F_era, F_pool = fits(era), fits(lambda y: 'all')
    calib = {}
    for name, F in (('pooled', F_pool), ('era', F_era)):
        ys = sorted(mature); g = []
        for y in ys:
            R = [r for r in by[y] if r.get('out') is not None]
            g.append(math.log(sum(max(0, r['out'] - REPL) for r in R) / ex_over([r['fvx'] for r in R], F[y]).sum()))
        calib[name] = {'trend': trend(ys, g), 'mean': round(float(np.mean(g)), 3), 'sd': round(float(np.std(g, ddof=1)), 3)}
    C = []
    for y in years:
        R = sorted(by[y], key=lambda r: -r['fvx'])
        xp = ex_over([r['fvx'] for r in R], F_era[y]); xq = ex_over([r['fvx'] for r in R], F_pool[y])
        best = R[0]
        c = {'y': y, 'n': len(R), 'top': round(float(xp[:TOPN].sum()), 1), 'dep': round(float(xp[TOPN:DEPN].sum()), 1),
             'all': round(float(xp[:DEPN].sum()), 1), 'raw': round(float(xq[:DEPN].sum()), 1),
             'fv10': round(float(np.mean([r['fvx'] for r in R[:TOPN]])), 1), 'n50': sum(r['fvx'] >= 50 for r in R),
             'n45': sum(r['fvx'] >= 45 for r in R), 'best': best['name'], 'bestFv': best['fv'], 'bestTeam': best.get('team'),
             'era': era(y)}
        if y in mature:
            o = np.clip(np.array(sorted([r['out'] for r in rp[y] if r.get('out') is not None], reverse=True)) - REPL, 0, None)
            bo = max((r for r in rp[y] if r.get('out') is not None), key=lambda r: (r['out'], r['fvx']))
            c.update(otop=round(float(o[:TOPN].sum()), 1), odep=round(float(o[TOPN:DEPN].sum()), 1), oall=round(float(o[:DEPN].sum()), 1),
                     obest=bo['name'], obestOut=round(bo['out']))
        C.append(c)
    for k in ('top', 'dep', 'all', 'raw', 'otop', 'odep', 'oall'):
        S = sorted([c for c in C if k in c], key=lambda c: -c[k])
        for i, c in enumerate(S): c[k + 'R'] = i + 1
    M = [c for c in C if 'oall' in c]
    corr = lambda a, b: round(float(np.corrcoef([c[a] for c in M], [c[b] for c in M])[0, 1]), 2) if len(M) > 3 else None
    gate = {'adj': era_gate([c['y'] for c in C], [c['all'] for c in C], rng), 'raw': era_gate([c['y'] for c in C], [c['raw'] for c in C], rng)}
    gate['became'] = era_gate([c['y'] for c in M], [c['oall'] for c in M], rng) if len(M) >= 6 else None
    for k in ('adj', 'raw', 'became'):
        if gate[k]: gate[k] = {'h': gate[k][0], 'line': gate[k][1], 'pass': gate[k][0] <= gate[k][1]}
    eras = sorted({era(y) for y in years}, key=lambda e: min(y for y in years if era(y) == e))
    return {'classes': sorted(C, key=lambda c: c['allR']), 'years': [years[0], years[-1]], 'mature': sorted(mature),
            'eras': {e: {'lab': ERA_LAB[e], 'fit': [round(float(v), 2) for v in fit([r['fvx'] for z in mature if era(z) == e for r in by[z] if r.get('out') is not None],
                                                                            [r['out'] for z in mature if era(z) == e for r in by[z] if r.get('out') is not None])]}
                     for e in eras if any(era(z) == e for z in mature)},
            'pts': {str(v): round(float(ex_over([v], F_era[years[-1]])[0]), 1) for v in (45, 50, 60, 70)},
            'calib': calib, 'gate': gate, 'corr': {'all': corr('all', 'oall'), 'top': corr('top', 'otop'), 'dep': corr('dep', 'odep')}}


def main():
    d = json.load(open(P('data', 'fv_alltime.json')))
    rng = np.random.default_rng(7)
    out = {'asof': d['asof'], 'method': 'scripts/fv_classes.py', 'repl': REPL, 'top': TOPN, 'depth': DEPN}
    for sp in ('cfb', 'cbb', 'hockey'):
        if sp not in d: continue
        out[sp] = s = sport(sp, d[sp], rng)
        print(sp, 'classes', len(s['classes']), 'with an outcome', len(s['mature']), 'eras', {k: v['fit'] for k, v in s['eras'].items()})
        print('   calib pooled', s['calib']['pooled'], 'by era', s['calib']['era'])
        print('   era gate', s['gate'], 'corr draft-day vs became', s['corr'])
        for c in s['classes'][:5]: print('   ', c['allR'], c['y'], 'top', c['top'], c['topR'], 'dep', c['dep'], c['depR'], 'all', c['all'], 'raw', c['raw'], 'became', c.get('oall'), c.get('oallR'), c['best'])
    s = json.dumps(out, separators=(',', ':'), allow_nan=False)
    open(OUT, 'w').write(s)
    print('wrote', OUT, len(s) // 1024, 'KB')


if __name__ == '__main__':
    main()
