# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Tennis prospects FV, pre-registered with the player value batch (Holm over 4: two drivers x two tours):
  war  wins above replacement, last 52 weeks, every level: wins - sum P(a replacement player beats the opponent),
       replacement = the median Elo of opponents ranked 101-150 (the prospects board's own Elo), / (matches + 10)
  pax  points won over what the Elo gap predicts (serve + return points, matches with statistics), a 100 points,
       shrunk by 300 points; slope per Elo point fit on all matches with statistics 2010-19
Each added to the kept drivers (data/tennis_prospects_fit.json), the board's gate: leave-one-birth-year-out MSE t >= 2,
two thirds of the years, forward test not worse. October rows only (the selection snapshot).
    python3 scripts/research/tennis_value_nov14/prospect_drivers.py -> prospect_drivers.json beside it"""
import json, os, sys
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import tennis_prospects as T

B = T.base()
fit = json.load(open(T.FIT))
out = {}
orig = T.features
for tour in T.TOURS:
    b = B[tour]
    L = b['L']
    rrep = float(L.loc[L.orank.between(101, 150), 'oelo'].median())
    st = L[(L.svpt > 0) & (L.rtpt > 0) & (L.date.dt.year.between(2010, 2019)) & ~L.walk]
    ps = (st.svw + st.rtw) / (st.svpt + st.rtpt) - .5
    gap = (st.elo_pre - st.oelo).clip(-600, 600)
    slope = float((ps * gap).sum() / (gap * gap).sum())
    print(tour, 'repl Elo', round(rrep), 'point slope', slope, flush=True)
    pk, _ = T.peaks(b['S'], b['P'])
    rows = []
    for season in range(1993, 2027):
        D = T.snapdate(season, T.SEL_SNAP)
        if D > L.date.max():
            continue
        X = orig(b['R'], L, b['P'], D, season, tour)
        if not len(X):
            continue
        Dt = pd.Timestamp(D)
        Ly = L[(L.date <= Dt - pd.Timedelta(days=7)) & (L.date > Dt - pd.Timedelta(days=365)) & L.pid.isin(X.index) & ~L.walk]
        pr = 1 / (1 + 10 ** ((Ly.oelo - rrep) / 400))
        X['war'] = ((Ly.won - pr).groupby(Ly.pid).sum() / (Ly.groupby('pid').size() + 10)).reindex(X.index).fillna(0)
        s = Ly[(Ly.svpt > 0) & (Ly.rtpt > 0)]
        n = s.svpt + s.rtpt
        exp = (.5 + slope * (s.elo_pre - s.oelo).clip(-600, 600)) * n
        X['pax'] = (100 * (s.svw + s.rtw - exp).groupby(s.pid).sum() / (n.groupby(s.pid).sum() + 300)).reindex(X.index).fillna(0)
        X['snap'] = '%02d-%02d' % T.SEL_SNAP
        rows.append(X)
    X = pd.concat(rows).reset_index()
    X['by'] = b['P'].dobd.reindex(X.pid).dt.year.values
    X['pk'] = X.pid.map(pk).fillna(0)
    Xs, F, y, pos, by = T.snap_rows({tour: X}, tour, '%02d-%02d' % T.SEL_SNAP)
    F = F.copy()
    F['war'] = Xs['war'].values
    F['pax'] = Xs['pax'].values
    cur = fit[tour]['kept']
    m0 = T.fold_mse(T.loso(F, y, pos, by, cur)[2], y, by)
    f0 = T.forward(F, y, pos, by, Xs.season.values, cur)
    res = {}
    for c in ('war', 'pax'):
        m1 = T.fold_mse(T.loso(F, y, pos, by, cur + [c])[2], y, by)
        e = T.gate(m0, m1)
        f1 = T.forward(F, y, pos, by, Xs.season.values, cur + [c])
        e['fwd'] = [round(f0[0], 3), round(f1[0], 3)]
        res[c] = e
        print(tour, c, e, flush=True)
    out[tour] = {'kept': cur, 'replElo': round(rrep), 'pointSlope': slope, 'tests': res}
json.dump(out, open(os.path.join(HERE, 'prospect_drivers.json'), 'w'), indent=1)
