#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL win model: one combined strength term in place of Elo, xG rating and lineup value?

    python3 scripts/nhl_factor_research.py   -> data/nhl_factor_research.json (~1 min)

The win model's chances have been spread 17-26% wider than the closing line since 2022-23, and its Elo and xG terms now
move together (correlation .6 -> .85). Rescaling each input failed; the overlap is the suspect, not the size. One
pre-registered form: the first principal component of the three standardized terms (loadings and scale from the
seasons before each test season, walk-forward) replaces them; rest, back-to-back and home stay. Gate: the game model's
(paired t on log loss, tuning 2017-23 and held out 2024-26, both <= -1.5). Also reported: 'shrunk', the same three
terms with one shared walk-forward weight (their equal-weight mean), a second pre-registered form.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import nhl_games as G  # noqa: E402

OUT = os.path.join(G.ROOT, 'data', 'nhl_factor_research.json')
THREE = ['elo', 'xg', 'rv']


def main():
    fj = json.load(open(G.FIT))
    hist = G.load_hist()
    _, rows, _ = G.walk(hist, fj['params'], moves=G.hist_moves(hist))
    S, y, mg, tot, pc, tc, day = G.arrays(rows)
    feats = fj['feats']
    X = G.design(rows, feats)
    names = list(feats)
    ix = [names.index(k) for k in THREE]
    rest = [i for i in range(X.shape[1]) if i not in ix]
    first = G.SCORE_FROM + 1
    base = G.walk_logit(X, y, S, first)

    def variant(kind):
        p = np.full(len(y), np.nan)
        for s in range(first, int(S.max()) + 1):
            tr, te = S < s, S == s
            if not te.any() or tr.sum() <= 200:
                continue
            Z = X[:, ix]
            mu, sd = Z[tr].mean(0), Z[tr].std(0) + 1e-9
            Zs = (Z - mu) / sd
            if kind == 'pc1':
                w = np.linalg.svd(Zs[tr], full_matrices=False)[2][0]
                w = w * np.sign(w.sum())
            else:
                w = np.ones(3) / 3
            F = np.column_stack([X[:, rest], Zs @ w])
            p[te] = G.sig(F[te] @ G.logit_fit(F[tr], y[tr]))
        return p
    out = {'feats': feats, 'gate': 'paired t <= -1.5 on tuning 2017-23 and held out 2024-26'}
    for kind in ('pc1', 'shrunk'):
        p = variant(kind)
        ok = ~np.isnan(p) & ~np.isnan(base)
        r = {}
        for nm, m in (('tune', ok & (S <= 2023)), ('held', ok & (S >= 2024))):
            pr = H.paired(H.logloss(p[m], y[m]), H.logloss(base[m], y[m]), day[m])
            lg = lambda q: np.log(q / (1 - q))  # noqa: E731
            lm = m & ~np.isnan(pc)
            r[nm] = {'n': int(m.sum()), 'd': round(float(pr['d']) if 'd' in pr else float((H.logloss(p[m], y[m]) - H.logloss(base[m], y[m])).mean()), 5),
                     't': round(float(pr['t']), 2),
                     'sdRatioVsMarket': round(float(lg(p[lm]).std() / lg(pc[lm]).std()), 3) if lm.sum() > 100 else None,
                     'sdRatioBase': round(float(lg(base[lm]).std() / lg(pc[lm]).std()), 3) if lm.sum() > 100 else None}
        r['seasonsBetter'] = [int(sum((H.logloss(p[ok & (S == s)], y[ok & (S == s)]).mean() < H.logloss(base[ok & (S == s)], y[ok & (S == s)]).mean()) for s in sorted(set(S[ok])))), len(set(S[ok]))]
        r['pass'] = bool(r['tune']['t'] <= -1.5 and r['held']['t'] <= -1.5)
        out[kind] = r
    out['shipped'] = [k for k in ('pc1', 'shrunk') if out[k]['pass']]
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
