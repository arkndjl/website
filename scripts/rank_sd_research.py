#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Rank odds' rating sd: the cross-product fit (rank_odds.fit_cross) against the 'pure' netting, scored on final rank.

    python3 scripts/rank_sd_research.py     -> data/rank_sd_research.json

1. Synthetic recovery (known truth): 32 teams, a rating error of sd sigma each, game noise sd 12, n games left against
   random opponents. The residual mean's variance is sigma^2 + (sigma^2 + noise^2) / n (the opponents' errors differ
   game to game, so they sit in the per-game noise). 'own' nets (2 sigma^2 + noise^2) / n, 'pure' nets noise^2 / n and
   is solved to rank_odds' fixed point, 'cross' is the mean product of two different games' residuals.
2. Walk-forward on final rank, NFL and CFB, seasons 2018-25: at each checkpoint (0/20/40/60/80% of the games played)
   the ratings read back as rank_odds.checkpoints does, the rank odds drawn at each rule's sd (a, b and the floor fit
   on the seasons before), and the log-likelihood of each team's final rank (its read-back rating over the last 15% of
   the season's games). New = fit_cross, live = fit_sport 'pure'. Ship rule: the new fit must not score worse; t is
   clustered by season. Also the 80% rank range's cover and width, and the Brier of P(#1).
"""
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rank_odds as RO  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'data', 'rank_sd_research.json')
CKS = (0, .2, .4, .6, .8)
SEASONS = (2018, 2025)
NS = 20000


def synthetic(sig, n, tau=12.0, T=32, reps=4000, seed=1):
    rng = np.random.default_rng(seed)
    A2, cp = [], []
    for _ in range(reps):
        d = rng.normal(0, sig, T)
        U = np.zeros((T, n))
        for j in range(n):
            p = rng.permutation(T)
            h, a = p[:T // 2], p[T // 2:]
            e = d[h] - d[a] + rng.normal(0, tau, T // 2)
            U[h, j], U[a, j] = e, -e
        A2.append(np.mean(U.mean(1) ** 2))
        cp.append(np.mean((U.sum(1) ** 2 - (U ** 2).sum(1)) / (n * (n - 1))))
    V, gn, k = float(np.mean(A2)), 2 * sig ** 2 + tau ** 2, T / (T - 1)
    s2 = 11.0
    for _ in range(50):
        s2 = (V - max(0.3 * gn, gn - 2 * s2 * k) / n) / k
    return {'sigma': sig, 'left': n, 'own': round(math.sqrt(max((V - gn / n) / k, 0)), 2),
            'pure': round(math.sqrt(max(s2, 0)), 2), 'cross': round(math.sqrt(max(float(np.mean(cp)), 0)), 2)}


def ratings(sport):
    """{(season, checkpoint): [(checkpoint rating, share left, final rating)]}: rank_odds.checkpoints' read-back"""
    G = [g for g in json.load(gzip.open(RO.WF.format(sport))) if not g.get('po') and g.get('m') is not None
         and g.get('res') is not None and not g.get('fcs')]
    by = defaultdict(list)
    for g in G:
        by[g['S']].append(g)

    def ridge(win, ix, T):
        X = np.zeros((len(win), T + 1))
        for j, g in enumerate(win):
            X[j, ix[g['home']]], X[j, ix[g['away']]] = 1, -1
            X[j, T] = 0 if g.get('neutral') else 1
        b = np.linalg.solve(X.T @ X + 0.3 * np.diag([1.0] * T + [1e-9]), X.T @ np.array([g['m'] for g in win], float))
        return b[:T] - b[:T].mean()
    out = {}
    for S, gs in sorted(by.items()):
        gs.sort(key=lambda g: g['date'])
        N = len(gs)
        teams = sorted({g['home'] for g in gs} | {g['away'] for g in gs})
        ix = {t: i for i, t in enumerate(teams)}
        tot = Counter([g['home'] for g in gs] + [g['away'] for g in gs])
        fw = gs[int(0.85 * N):]
        rf = ridge(fw, ix, len(teams))
        fseen = Counter([g['home'] for g in fw] + [g['away'] for g in fw])
        for f in CKS:
            i0 = int(f * N)
            d0 = RO._day(gs[i0]['date'])
            win = [g for g in gs[i0:] if (RO._day(g['date']) - d0).days < RO.WINDOW[sport]]
            r = ridge(win, ix, len(teams))
            seen = Counter([g['home'] for g in win] + [g['away'] for g in win])
            left = Counter([g['home'] for g in gs[i0:]] + [g['away'] for g in gs[i0:]])
            out[(S, f)] = [(r[ix[t]], left[t] / tot[t], rf[ix[t]]) for t in teams
                           if left[t] >= 3 and seen[t] >= 2 and fseen[t] >= 2]
    return out


def sd_at(p, share):
    return np.maximum(p[2], np.sqrt(np.maximum(0.05, p[0] + p[1] * np.clip(share, 0, 1))))


def rank_test(sport):
    R, rat = RO.checkpoints(sport), ratings(sport)
    rng = np.random.default_rng(3)
    rows, fits = [], {}
    for s_ in sorted(set(R[:, 0].astype(int).tolist())):
        if not SEASONS[0] <= s_ <= SEASONS[1] or len(set(R[R[:, 0] < s_, 0])) < 2:
            continue
        lv = RO.fit_sport(None, R[R[:, 0] < s_][:, :7], 'pure')
        P = {'live': (lv['a'], lv['b'], lv['floor']), 'new': RO.fit_cross(R, upto=s_)}
        fits[s_] = {k: [round(float(x), 2) for x in v] for k, v in P.items()}
        for f in CKS:
            tl = rat[(s_, f)]
            r, sh, rf = (np.array([x[i] for x in tl]) for i in range(3))
            fr = np.argsort(np.argsort(-rf))
            Z = rng.normal(size=(NS, len(r)))
            for nm, p in P.items():
                rk = np.argsort(np.argsort(-(r[None, :] + Z * sd_at(p, sh)[None, :]), axis=1), axis=1)
                ll = -np.log(((rk == fr[None, :]).sum(0) + 0.5) / (NS + 0.5 * len(r)))
                lo, hi = np.quantile(rk, .1, axis=0, method='lower'), np.quantile(rk, .9, axis=0, method='higher')
                p1 = (rk == 0).mean(0)
                for i in range(len(r)):
                    rows.append((nm, s_, f, ll[i], float(lo[i] <= fr[i] <= hi[i]), float(hi[i] - lo[i] + 1), (p1[i] - (fr[i] == 0)) ** 2))

    def cell(f):
        a = {nm: np.array([x[3:] for x in rows if x[0] == nm and (f is None or x[2] == f)]) for nm in ('live', 'new')}
        S = np.array([x[1] for x in rows if x[0] == 'live' and (f is None or x[2] == f)])
        d = a['new'][:, 0] - a['live'][:, 0]
        ms = np.array([d[S == s].sum() for s in sorted(set(S))])
        g = len(ms)
        t = d.mean() / (math.sqrt(g / (g - 1) * ((ms - ms.mean()) ** 2).sum()) / len(d))
        return {'n': int(len(d)), 'llLive': round(float(a['live'][:, 0].mean()), 4), 'llNew': round(float(a['new'][:, 0].mean()), 4),
                't': round(float(t), 2), 'seasons': g, 'seasonsNewBetter': int((ms < 0).sum()),
                'cover80': [round(float(a[k][:, 1].mean()), 3) for k in ('live', 'new')],
                'width80': [round(float(a[k][:, 2].mean()), 1) for k in ('live', 'new')],
                'brier1': [round(float(a[k][:, 3].mean()), 5) for k in ('live', 'new')]}
    return {'all': cell(None), 'byCheckpoint': {str(f): cell(f) for f in CKS}, 'fits': fits,
            'ships': cell(None)['llNew'] <= cell(None)['llLive']}


def main():
    out = {'note': 'scripts/rank_sd_research.py: cross-product rating sd (new) vs the pure netting (live) on final rank, '
                   f'walk-forward {SEASONS[0]}-{SEASONS[1]}; cover80 / width80 / brier1 are [live, new]',
           'synthetic': [synthetic(s, n) for s, n in ((2.0, 3), (4.0, 3), (3.0, 5), (4.0, 16))]}
    for s in out['synthetic']:
        print(s, flush=True)
    for sp in ('nfl', 'cfb'):
        out[sp] = rank_test(sp)
        print(sp, out[sp]['all'], flush=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
