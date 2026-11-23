#!/usr/bin/env python3
"""B1-B4, B6, B7 (prereg.md): post-model overlays on the walk-forward rows scripts/data/games_wf/<sport>.json.gz."""
import os, sys, json, gzip, collections
import numpy as np
SCR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, SCR)
import harness as H
HERE = os.path.dirname(os.path.abspath(__file__))
SPLIT = {'nba': ((2015, 2021), 2022), 'cbb': ((2016, 2020), 2021)}


def load(s):
    R = json.load(gzip.open(os.path.join(SCR, 'data', 'games_wf', s + '.json.gz')))
    assert max(r['S'] for r in R) <= 2026, 'lockbox'
    R.sort(key=lambda r: (r['date'], r['id']))
    gp = collections.Counter()
    for r in R:                                    # games played before this one
        r['gh'], r['ga'] = gp[(r['S'], r['home'])], gp[(r['S'], r['away'])]
        gp[(r['S'], r['home'])] += 1; gp[(r['S'], r['away'])] += 1
        r['day'] = r['date'][:10]
    return R


def arr(R, k):
    return np.array([np.nan if r.get(k) is None else r[k] for r in R], float)


def judge(s, R, new, old, y, ok):
    (a, b), hf = SPLIT[s]
    S = arr(R, 'S'); cl = [np.array([r['day'] for r in R]), np.array([f"{r['home']}{r['S']}" for r in R])]
    out = {}
    for nm, k in (('tune', ok & (S >= a) & (S <= b)), ('held', ok & (S >= hf))):
        q = H.paired(np.abs(new[k] - y[k]), np.abs(old[k] - y[k]), cluster=[c[k] for c in cl])
        out[nm] = {'n': int(k.sum()), 'mae': round(float(np.abs(new[k] - y[k]).mean()), 4),
                   'base': round(float(np.abs(old[k] - y[k]).mean()), 4), 'd': round(q['d'], 5), 't': round(q['t'], 2),
                   'p': q['p']}
    return out


def tune_mae(s, R, new, y, ok):
    (a, b), _ = SPLIT[s]
    S = arr(R, 'S'); k = ok & (S >= a) & (S <= b)
    return float(np.abs(new[k] - y[k]).mean())


def stretch(s, R, Gs):
    m, y, L = arr(R, 'm'), arr(R, 'res'), arr(R, 'L')
    ok = ~np.isnan(m) & ~np.isnan(y) & (~np.isnan(L) if s == 'cbb' else True)
    gmin = np.minimum(arr(R, 'gh'), arr(R, 'ga'))
    best = None
    for G in Gs:
        for c in np.round(np.arange(1.0, 1.301, .01), 2):
            new = np.where(gmin < G, c * m, m)
            v = tune_mae(s, R, new, y, ok)
            if best is None or v < best[0] - 1e-12:
                best = (v, G, float(c))
    _, G, c = best
    new = np.where(gmin < G, c * m, m)
    return {'pick': {'G': G, 'c': c}, **judge(s, R, new, m, y, ok), 'close': close(s, R, new, m, ok)}


def close(s, R, new, old, ok):
    """held lined: MAE vs close and slope of (res - L) on the change"""
    _, hf = SPLIT[s]
    S, y, L = arr(R, 'S'), arr(R, 'res'), arr(R, 'L')
    k = ok & (S >= hf) & ~np.isnan(L)
    dx = (new - old)[k]; rl = (y - L)[k]
    sl = float(dx @ rl / (dx @ dx)) if (dx @ dx) > 0 else None
    return {'maeClose': round(float(np.abs(L[k] - y[k]).mean()), 4), 'slope': None if sl is None else round(sl, 3)}


def shrink(s, R, Gs):
    tm, y, T = arr(R, 'tm'), arr(R, 'tot'), arr(R, 'T')
    ok = ~np.isnan(tm) & ~np.isnan(y) & (~np.isnan(T) if s == 'cbb' else True)
    gmin = np.minimum(arr(R, 'gh'), arr(R, 'ga'))
    byd = collections.defaultdict(list)
    for i, r in enumerate(R):
        if not np.isnan(tm[i]):
            byd[r['day']].append(i)
    mbar = tm.copy()
    for d, ix in byd.items():
        if len(ix) > 1:
            mbar[ix] = tm[ix].mean()
    best = None
    for G in Gs:
        for sh in np.round(np.arange(0.5, 1.001, .05), 2):
            new = np.where(gmin < G, mbar + sh * (tm - mbar), tm)
            v = tune_mae(s, R, new, y, ok)
            if best is None or v < best[0] - 1e-12:
                best = (v, G, float(sh))
    _, G, sh = best
    new = np.where(gmin < G, mbar + sh * (tm - mbar), tm)
    return {'pick': {'G': G, 's': sh}, **judge(s, R, new, tm, y, ok)}


def dis(s, R, total, K=0.2):
    pk, lk, yk = ('tm', 'T', 'tot') if total else ('m', 'L', 'res')
    p, L, y = arr(R, pk), arr(R, lk), arr(R, yk)
    ok = ~np.isnan(p) & ~np.isnan(y)
    x = np.zeros(len(R))
    d = collections.defaultdict(float)
    byd = collections.defaultdict(list)
    for i, r in enumerate(R):
        byd[(r['S'], r['day'])].append(i)
    for key in sorted(byd, key=lambda k: k[1]):
        ix = byd[key]
        for i in ix:
            r = R[i]
            dh, da = d[(r['S'], r['home'])], d[(r['S'], r['away'])]
            x[i] = dh + da if total else dh - da
        for i in ix:
            r = R[i]
            if np.isnan(L[i]) or np.isnan(p[i]):
                continue
            e = (L[i] - p[i]) - x[i]
            d[(r['S'], r['home'])] += K * e
            d[(r['S'], r['away'])] += (K * e if total else -K * e)
    best = None
    for c in np.round(np.arange(0, 1.501, .05), 2):
        v = tune_mae(s, R, p + c * x, y, ok)
        if best is None or v < best[0] - 1e-12:
            best = (v, float(c))
    c = best[1]
    new = p + c * x
    out = {'pick': {'K': K, 'c': c}, **judge(s, R, new, p, y, ok)}
    if not total:
        out['close'] = close(s, R, new, p, ok)
    return out


if __name__ == '__main__':
    res = {}
    N, C = load('nba'), load('cbb')
    res['B1'] = stretch('nba', N, (6, 12, 20))
    res['B2'] = shrink('nba', N, (6, 12, 20))
    res['B3'] = dis('nba', N, False)
    res['B4'] = dis('nba', N, True)
    res['B6'] = stretch('cbb', C, (3, 6, 10))
    res['B7'] = shrink('cbb', C, (3, 6, 10))
    for k, v in res.items():
        print(k, json.dumps(v))
    json.dump(res, open(os.path.join(HERE, 'overlays_results.json'), 'w'), indent=1)
