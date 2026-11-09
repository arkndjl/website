# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
#!/usr/bin/env python3
"""FV sweep Nov 9 2026 (soccer): the board's Oct 24 rows 2013-20 for the whole pool (not only finished cohorts), the
outcomes, per-season GAR at ages 22-26 and detailed positions, built with scripts/soccer_prospects.py's own functions.

    python3 scripts/research/fv_nov09/soccer_rows.py      -> scripts/.cache/soccer_prospects/nov09_rows.pkl
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_prospects as SP       # noqa: E402

OUT = os.path.join(SP.CACHE, 'nov09_rows.pkl')


def main():
    G, A, P, V = SP.load()
    for c in ('mins', 'gl', 'ast', 'mv', 'age', 'start'):
        A[c] = pd.to_numeric(A[c], errors='coerce').astype(float)
    V['mv'] = pd.to_numeric(V.mv, errors='coerce').astype(float)
    print('loaded', len(G), len(A), len(P), flush=True)
    R = SP.club_ratings(G, A, V)
    A = SP.add_value(A, R)
    O, scale = SP.outcome(A, P)
    TG = SP.team_games(G)
    xs = []
    for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
        X = SP.features(A, P, V, R, TG, t, SP.snapdate(t, SP.SEL_SNAP))
        X['mvlvl'] = SP.mv_level(X.mv)
        X['fv_out'], X['peak'], X['s22'] = O.fv.reindex(X.index), O.peak.reindex(X.index), O.s22.reindex(X.index)
        X['subpos'] = P.sub_position.reindex(X.index)
        X['in_dump'] = X.index.isin(SP.rd('players', usecols=['player_id']).player_id)
        xs.append(X.reset_index().rename(columns={'index': 'player_id'}))
        print('rows', t, len(X), int(X.old.sum()), flush=True)
    S = pd.concat(xs, ignore_index=True)
    # season GAR at ages 22-26, as SP.outcome counts it
    s = A[A.gar > 0].groupby(['player_id', 'season']).gar.sum().reset_index()
    s['age'] = np.floor((pd.to_datetime(s.season.astype(str) + '-07-01') - s.player_id.map(P.dob)).dt.days / 365.25)
    s = s[s.age.between(*SP.PEAK_AGES) & s.player_id.isin(S.player_id.unique())]
    pickle.dump({'S': S, 'gar': s, 'scale': scale, 'O': O.loc[O.index.isin(S.player_id.unique()), ['s22', 'peak', 'fv', 'grp']]},
                open(OUT, 'wb'))
    print('wrote', OUT, len(S))


if __name__ == '__main__':
    main()
