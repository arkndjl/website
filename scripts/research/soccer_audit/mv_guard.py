#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""OLS market-value survivor guard: lmv/nomv from values dated on the player's own lineups (as the trees) vs the
dump's valuation history. Oct 24 rows 2013-20, cohort-out (s22) folds, kept drivers fixed."""
import sys, json, math, numpy as np, pandas as pd
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..'))
import soccer_prospects as SP
F = json.load(open('data/soccer_prospects_fit.json'))
kept = F['kept']
G, A, P, V = SP.load()
R = SP.club_ratings(G, A, V); A = SP.add_value(A, R)
O, scale = SP.outcome(A, P); TG = SP.team_games(G)
done = O[O.s22 <= SP.COHORTS[1]]
Vs = SP.sym_values(A)
md = SP.SEL_SNAP
xs = []
for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
    X = SP.features(A, P, V, R, TG, t, SP.snapdate(t, md), Vs=Vs)
    X['mvlvl'] = SP.mv_level(X.mv); X['mvlvls'] = SP.mv_level(X.mvs)
    X = X[X.index.isin(done.index) & X.old]
    X['fv_out'] = done.fv.reindex(X.index); X['s22'] = done.s22.reindex(X.index)
    xs.append(X.reset_index().rename(columns={'index': 'player_id'}))
S = pd.concat(xs, ignore_index=True)
ref = round(float(S.groupby('t').mvlvl.first().mean()), 4); refs = round(float(S.groupby('t').mvlvls.first().mean()), 4)
S['mvd'] = S.mv * np.exp(ref - S.mvlvl)
y, co, t = S.fv_out.values.astype(float), S.s22.values, S.t.values
print('rows', len(S))
onlyd = S.mv.notna() & S.mvs.isna()
print('mv from dump history only (no own-lineup value):', int(onlyd.sum()), 'mean outcome', round(y[onlyd].mean(), 2),
      '| both', round(y[S.mv.notna() & S.mvs.notna()].mean(), 2), '| neither', round(y[S.mv.isna()].mean(), 2), int(S.mv.isna().sum()))
print('nomv rate: dump-history', round(S.mv.isna().mean(), 3), 'own-lineup', round(S.mvs.isna().mean(), 3))
F0 = SP.design(S)
S2 = S.copy(); S2['mv'] = S.mvs; S2['mvd'] = S.mvs * np.exp(refs - S.mvlvls)
F1 = SP.design(S2)
e0, _ = SP.loso(F0, y, co, kept); e1, _ = SP.loso(F1, y, co, kept)
per = np.array([(e1[t == s] ** 2).mean() - (e0[t == s] ** 2).mean() for s in np.unique(t)])
print('cohort-out MSE live', round((e0 ** 2).mean(), 3), 'guard', round((e1 ** 2).mean(), 3), 'per-season worse by', per.round(3))
b0, b1 = SP.ols(F0, y, kept), SP.ols(F1, y, kept)
for c in ('lmv', 'nomv', 'lmv2', 'lmv_fwd', 'lmv_gk'):
    i = kept.index(c) + 1
    print(c, round(b0[i], 3), '->', round(b1[i], 3))
# what the live board sees
B = json.load(open('data/soccer_prospects.json'))
