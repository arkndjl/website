# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Placebo calibration of the ship gate (PREREG.md M3).

    python3 scripts/research/sweep_nov19/methods/placebo.py [sport ...]   # -> out/placebo.json

Null inputs that keep a real input's day and team dependence go through the walk-forward stack test and both gates;
the share that passes is the gate's measured false-pass rate.
"""
import gzip
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H  # noqa: E402

OUT = os.environ.get('METHODS_OUT', os.path.join(HERE, 'out'))
SEED = 20261119
SPLIT = {'nba': (2016, 2021, 2022, 2026), 'nfl': (2016, 2020, 2021, 2026), 'cbb': (2017, 2020, 2021, 2026),
         'cfb': (2018, 2020, 2021, 2026), 'nhl': (2018, 2023, 2024, 2026), 'soccer': (2014, 2022, 2023, 2026)}
FOOT = ('nfl', 'cfb')


def load(sp):
    d = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', sp + '.json.gz')))
    rows = []
    for g in d:
        S = g['S']
        if sp in FOOT:
            if S > 2026 or (S == 2026 and (g.get('wk') is None or g['wk'] > 10)):
                continue
        elif S > 2026:
            continue
        day = (g.get('date') or g.get('day'))[:10]
        h, a = g.get('home', g.get('h')), g.get('away', g.get('a'))
        if sp == 'nhl':
            if g.get('p') is None or g.get('hs') is None:
                continue
            p = min(max(g['p'], 1e-4), 1 - 1e-4)
            y, m = float(g['hs'] > g['as']), math.log(p / (1 - p))
            miss = y - p
        elif sp == 'soccer':
            if g.get('l') is None or g.get('hs') is None:
                continue
            y, m = float(g['hs'] - g['as']), g['l'][0] - g['l'][1]
            miss = y - m
        else:
            if g.get('m') is None or g.get('res') is None:
                continue
            y, m = float(g['res']), float(g['m'])
            miss = y - m
        rows.append(dict(S=S, day=day, h=str(h), a=str(a), y=y, m=m, miss=miss, wk=g.get('wk'), neutral=g.get('neutral', 0)))
    rows.sort(key=lambda r: (r['day'], r['h']))
    return rows


def sources(rows):
    """rest, form5, formS as home minus away, each from games before this one"""
    import datetime as dt
    last, hist = {}, {}
    out = np.zeros((len(rows), 3))
    for i, r in enumerate(rows):
        d = dt.date.fromisoformat(r['day'])
        v = []
        for side, sg in ((r['h'], 1), (r['a'], -1)):
            k = (side, r['S'])
            rest = min(10, (d - last[k]).days) if k in last else 10
            hs = hist.get(k, [])
            v.append((rest, float(np.mean(hs[-5:])) if hs else 0.0, float(np.mean(hs)) if hs else 0.0))
        out[i] = [v[0][j] - v[1][j] for j in range(3)]
        for side, sg in ((r['h'], 1), (r['a'], -1)):
            k = (side, r['S'])
            last[k] = d
            hist.setdefault(k, []).append(sg * r['miss'])
    return out


def placebo(kind, col, rows, slate, hts, rng):
    z = np.empty(len(col))
    if kind == 'P1':
        for idx in slate:
            z[idx] = col[rng.permutation(idx)]
    else:
        for S, teams in hts.items():
            keys = list(teams)
            n = len(keys)
            if n < 2:
                for k in keys:
                    z[teams[k]] = col[teams[k]]
                continue
            while True:
                perm = rng.permutation(n)
                if not (perm == np.arange(n)).any():
                    break
            for j, k in enumerate(keys):
                src = col[teams[keys[perm[j]]]]
                z[teams[k]] = src[np.arange(len(teams[k])) % len(src)]
    sd = z.std()
    return (z - z.mean()) / sd if sd > 0 else z * 0


def walk(X, y, S, seasons, logistic=False):
    pred = np.full(len(y), np.nan)
    for s in seasons[1:]:
        tr, te = S < s, S == s
        if logistic:
            b = np.zeros(X.shape[1])
            for _ in range(25):
                p = 1 / (1 + np.exp(-X[tr] @ b))
                w = p * (1 - p)
                step = np.linalg.solve((X[tr] * w[:, None]).T @ X[tr] + 1e-8 * np.eye(X.shape[1]), X[tr].T @ (y[tr] - p))
                b += step
                if np.abs(step).max() < 1e-9:
                    break
            pred[te] = 1 / (1 + np.exp(-X[te] @ b))
        else:
            pred[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
    return pred


def cp(k, n, a=0.05):
    """Clopper-Pearson interval by bisection on the binomial cdf"""
    from math import comb

    def cdf(x, p):
        return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, x + 1))

    def solve(f):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) else (lo, mid)
        return (lo + hi) / 2
    lo = 0.0 if k == 0 else solve(lambda p: 1 - cdf(k - 1, p) < a / 2)
    hi = 1.0 if k == n else solve(lambda p: cdf(k, p) > a / 2)
    return [round(lo, 4), round(hi, 4)]


def run(sp, n_each=100, design=None):
    rows = load(sp)
    S = np.array([r['S'] for r in rows])
    y = np.array([r['y'] for r in rows])
    m = np.array([r['m'] for r in rows])
    seasons = sorted(set(S.tolist()))
    t0, t1, h0, h1 = SPLIT[sp]
    tune, held = (S >= t0) & (S <= t1), (S >= h0) & (S <= h1)
    day = np.array([r['day'] for r in rows])
    ht = np.array([f"{r['h']}|{r['S']}" for r in rows])
    _, dayc = np.unique(day, return_inverse=True)
    _, htc = np.unique(ht, return_inverse=True)
    both = dayc.astype(np.int64) * (htc.max() + 1) + htc
    src = sources(rows)
    skey = np.array([f"{r['S']}|{r['wk']}" if sp in FOOT else r['day'] for r in rows])
    slate = [np.flatnonzero(skey == k) for k in np.unique(skey)]
    hts = {}
    for i, r in enumerate(rows):
        hts.setdefault(r['S'], {}).setdefault(r['h'], []).append(i)
    hts = {s: {k: np.array(v) for k, v in t.items()} for s, t in hts.items()}
    logistic = sp == 'nhl'
    one = np.ones(len(y))
    loss = (lambda p: H.logloss(p, y)) if logistic else (lambda p: H.ae(p, y))
    base = loss(walk(np.column_stack([one, m]), y, S, seasons, logistic))

    def pt(mask, d):
        # multiway CGM with integer keys (same estimator as harness.paired, floored at the largest one-way)
        dd = d[mask]
        n = len(dd)
        va, Ga = H._cr_var(dd, dayc[mask])
        vb, Gb = H._cr_var(dd, htc[mask])
        vab, _ = H._cr_var(dd, both[mask])
        v = max(va + vb - vab, va, vb)
        G = min(Ga, Gb)
        t = float(dd.mean() / math.sqrt(v)) if v > 0 else 0.0
        return t, float(dd.mean()), G

    rng = np.random.default_rng(SEED + sum(map(ord, sp)))
    res = []
    hs = [s for s in seasons if h0 <= s <= h1]
    for kind in ('P1', 'P2'):
        for _ in range(n_each):
            j = int(rng.integers(3))
            z = placebo(kind, src[:, j], rows, slate, hts, rng)
            d = loss(walk(np.column_stack([one, m, z]), y, S, seasons, logistic)) - base
            tt, dt_, _ = pt(tune, d)
            th, dh, G = pt(held, d)
            maj = sum(d[S == s].mean() < 0 for s in hs) > len(hs) / 2
            res.append(dict(kind=kind, src=j, tt=tt, th=th, dt=dt_, dh=dh, maj=bool(maj)))
    th = np.array([r['th'] for r in res])
    tt = np.array([r['tt'] for r in res])
    maj = np.array([r['maj'] for r in res])
    dtn = np.array([r['dt'] for r in res])
    g_old = (tt <= -1.5) & (th <= -2) & maj
    g_new = (th <= -2) & (dtn < 0) & maj
    n = len(res)
    out = {'sport': sp, 'rows': len(rows), 'tune': int(tune.sum()), 'held': int(held.sum()), 'heldSeasons': hs, 'n': n,
           'G_old': {'k': int(g_old.sum()), 'rate': round(float(g_old.mean()), 4), 'ci': cp(int(g_old.sum()), n)},
           'G_brief': {'k': int(g_new.sum()), 'rate': round(float(g_new.mean()), 4), 'ci': cp(int(g_new.sum()), n)},
           'heldT2': {'k': int((th <= -2).sum()), 'rate': round(float((th <= -2).mean()), 4), 'ci': cp(int((th <= -2).sum()), n)},
           'heldT': {'mean': round(float(th.mean()), 3), 'sd': round(float(th.std(ddof=1)), 3),
                     'p2.5': round(float(np.percentile(th, 2.5)), 2), 'p5': round(float(np.percentile(th, 5)), 2),
                     'p97.5': round(float(np.percentile(th, 97.5)), 2)},
           'tuneT': {'mean': round(float(tt.mean()), 3), 'sd': round(float(tt.std(ddof=1)), 3)},
           'byKind': {k: {'G_brief': int(g_new[[r['kind'] == k for r in res]].sum()),
                          'heldTsd': round(float(th[[r['kind'] == k for r in res]].std(ddof=1)), 3)} for k in ('P1', 'P2')},
           'detail': [[r['kind'], r['src'], round(r['tt'], 3), round(r['th'], 3), int(r['maj'])] for r in res]}
    return out


def main(args):
    os.makedirs(OUT, exist_ok=True)
    sports = args or list(SPLIT)
    path = os.path.join(OUT, 'placebo.json')
    allr = json.load(open(path)) if os.path.exists(path) else {}
    for sp in sports:
        r = run(sp)
        allr[sp] = r
        print(sp, r['rows'], 'G_old', r['G_old'], 'G_brief', r['G_brief'], 'heldT2', r['heldT2'], r['heldT'], r['byKind'], flush=True)
        json.dump(allr, open(path, 'w'), indent=0)
    done = [s for s in SPLIT if s in allr]
    if len(done) == len(SPLIT):
        n = sum(allr[s]['n'] for s in done)
        pool = {}
        for g in ('G_old', 'G_brief', 'heldT2'):
            k = sum(allr[s][g]['k'] for s in done)
            pool[g] = {'k': k, 'n': n, 'rate': round(k / n, 4), 'ci': cp(k, n)}
        th = np.concatenate([[d[3] for d in allr[s]['detail']] for s in done])
        pool['heldT'] = {'mean': round(float(th.mean()), 3), 'sd': round(float(th.std(ddof=1)), 3)}
        allr['pooled'] = pool
        print('pooled', pool)
        json.dump(allr, open(path, 'w'), indent=0)


if __name__ == '__main__':
    main(sys.argv[1:])
