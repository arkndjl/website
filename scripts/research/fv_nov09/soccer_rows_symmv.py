# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
#!/usr/bin/env python3
"""FV sweep Nov 9 2026 (soccer), leak guard for S3: market values with the same visibility for every player.
The board reads a value from the dump's valuation history (kept only for players who at some time reached a dump
league) or from a lineup sheet. Here a value is known only as it stood at a player's own lineup dates in the covered
competitions (the lineup's value, else the dump history as of that game), so "has a value / has a value a year back"
no longer depends on whether the player later reached a dump league.

    python3 scripts/research/fv_nov09/soccer_rows_symmv.py   -> scripts/.cache/soccer_prospects/nov09_symmv.pkl
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_prospects as SP       # noqa: E402

OUT = os.path.join(SP.CACHE, 'nov09_symmv.pkl')


def main():
    G, A, P, V = SP.load()
    A['mv'] = pd.to_numeric(A.mv, errors='coerce').astype(float)
    v = SP.rd('player_valuations', usecols=['player_id', 'date', 'market_value_in_eur']).rename(columns={'market_value_in_eur': 'dv'})
    v['date'] = pd.to_datetime(v.date)
    v['dv'] = v.dv.astype(float)
    a = A[['player_id', 'date', 'mv']].sort_values('date')
    a = pd.merge_asof(a, v.sort_values('date'), on='date', by='player_id', direction='backward')
    a['mv'] = a.mv.fillna(a.dv)
    V2 = a[a.mv.notna()][['player_id', 'date', 'mv']].sort_values('date')
    print('values', len(V), '->', len(V2), flush=True)
    xs = []
    for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
        snap = SP.snapdate(t, SP.SEL_SNAP)
        w = A[(A.season.eq(t - 1)) | (A.season.eq(t) & (A.date < snap))]
        dob = P.dob.reindex(pd.Index(w.player_id.unique()))
        age = (pd.Timestamp(f'{t}-07-01') - dob).dt.days / 365.25
        ids = age[(age < SP.AGE_CUT) & (age >= 15)].index
        X = pd.DataFrame(index=ids)
        X['mv_sym'] = V2[V2.player_id.isin(ids) & (V2.date <= snap)].groupby('player_id').mv.last()
        X['mv1_sym'] = V2[V2.player_id.isin(ids) & (V2.date <= snap - pd.Timedelta(days=365))].groupby('player_id').mv.last()
        X['mvlvl_sym'] = SP.mv_level(X.mv_sym)
        X['t'] = t
        xs.append(X.reset_index().rename(columns={'index': 'player_id'}))
        print(t, len(X), round(float(X.mv_sym.notna().mean()), 3), round(float(X.mv1_sym.notna().mean()), 3), flush=True)
    pd.concat(xs, ignore_index=True).to_pickle(OUT)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
