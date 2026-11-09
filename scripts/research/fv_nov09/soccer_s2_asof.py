# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
#!/usr/bin/env python3
"""FV sweep Nov 9 2026 (soccer), beside S2: how much hindsight is in the profile position? The profile shows a player's
current main position. For players on Transfermarkt-API lineup sheets (feeder, academy and reserve leagues; the dump's
lineups are not used here) the position he STARTED at in games before the snapshot is known as of the day. Reports the
agreement of the two, and the S2 block built from each on the rows that have both.

    python3 scripts/research/fv_nov09/soccer_s2_asof.py
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_prospect_data as SD   # noqa: E402
import soccer_prospects as SP       # noqa: E402
import soccer_tests as T            # noqa: E402

SHORT = {'CB': 'CB', 'LB': 'FB', 'RB': 'FB', 'DM': 'DM', 'CM': 'CM', 'AM': 'AM', 'LW': 'W', 'RW': 'W', 'LM': 'W', 'RM': 'W',
         'CF': 'ST', 'SS': 'ST', 'GK': 'GK'}


def main():
    D = pickle.load(open(T.ROWS, 'rb'))
    S = D['S']; S['old'] = S.old.astype(bool)
    B = T.board_rows(S)
    G, A = SP.tm_games(SD.FEED + SP.NEWC, range(SP.FIRST, SP.ROWS[1] + 1))
    A = A.merge(G[['game_id', 'date']], on='game_id')
    A = A[A.pos.notna() & A.start.eq(1) & A.player_id.isin(B.player_id.unique())]
    A['cat'] = A.pos.map(SHORT)
    print('unmapped lineup positions', A.pos[A.cat.isna()].value_counts().to_dict())
    A = A[A.cat.notna()]
    print('lineup starts with a position', len(A), 'positions per player (mean distinct)', round(float(A.groupby('player_id').pos.nunique().mean()), 2), flush=True)
    asof = []
    for t in sorted(B.t.unique()):
        a = A[A.date < SP.snapdate(int(t), SP.SEL_SNAP)]
        m = a.groupby('player_id').cat.agg(lambda s: s.value_counts().index[0])
        n = a.groupby('player_id').size()
        asof.append(pd.DataFrame({'player_id': m.index, 't': t, 'cat_asof': m.values, 'n_asof': n.reindex(m.index).values}))
    B = B.merge(pd.concat(asof), on=['player_id', 't'], how='left')
    B['cat_prof'] = B.subpos.map(T.SUB).fillna(B.subpos.map({'Goalkeeper': 'GK'}))
    both = B.cat_asof.notna() & B.cat_prof.notna()
    out = {'rows': int(len(B)), 'withAsof': int(B.cat_asof.notna().sum()), 'both': int(both.sum()),
           'agree': round(float((B.cat_asof[both] == B.cat_prof[both]).mean()), 4),
           'agree5plusStarts': round(float((B.cat_asof[both & (B.n_asof >= 5)] == B.cat_prof[both & (B.n_asof >= 5)]).mean()), 4),
           'n5plus': int((both & (B.n_asof >= 5)).sum())}
    y = B.fv_out.values.astype(float)
    out['agreeByOutcome'] = {lab: [int((both & m).sum()), round(float((B.cat_asof[both & m] == B.cat_prof[both & m]).mean()), 4)]
                             for lab, m in (('fv20', y <= 20), ('fv20-40', (y > 20) & (y < 40)), ('fv40+', y >= 40))}
    out['cross'] = pd.crosstab(B.cat_asof[both], B.cat_prof[both]).to_dict()
    print(json.dumps({k: v for k, v in out.items() if k != 'cross'}), flush=True)
    print(pd.crosstab(B.cat_asof[both], B.cat_prof[both]))
    # the S2 block from each source on the rows that have both (season-out, as S2)
    K = B[both].reset_index(drop=True)
    F = SP.design(K)
    kept = list(json.load(open(SP.FIT))['kept'])
    yk, tk = K.fv_out.values.astype(float), K.t.values
    for src in ('cat_prof', 'cat_asof'):
        Z = pd.concat([F, pd.DataFrame({c: (K[src] == c[3:]).astype(float).values for c in T.BLOCK}, index=K.index)], axis=1)
        _, pb = SP.loso(Z, yk, tk, kept)
        _, pc = SP.loso(Z, yk, tk, kept + T.BLOCK)
        tr = (tk >= T.FWD[0]) & (tk <= T.FWD[1]); te = ~tr
        fb = SP.pred(Z[te], kept, SP.ols(Z[tr], yk[tr], kept))
        fc = SP.pred(Z[te], kept + T.BLOCK, SP.ols(Z[tr], yk[tr], kept + T.BLOCK))
        coef = dict(zip(['const'] + kept + T.BLOCK, SP.ols(Z, yk, kept + T.BLOCK)))
        out[src] = T.report('S2 on rows with both, block from ' + src, yk, tk, pb, pc, fb, fc, te, {'coef': {c: round(float(coef[c]), 3) for c in T.BLOCK}})
    json.dump(out, open(os.path.join(SP.CACHE, 'nov09_soccer_s2_asof.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
