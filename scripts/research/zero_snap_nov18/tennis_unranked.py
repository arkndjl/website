#!/usr/bin/env python3
"""Tennis prospects: are unranked (provisional) players graded above what such players became? See prereg.md.
Needs scripts/.cache/tennis/rows.pkl (tennis_prospects.py --download, --rows)."""
import json, math, os, pickle, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import tennis_prospects as T

rows = pickle.load(open(T.ROWS, 'rb')); fitj = json.load(open(T.FIT)); snap = '%02d-%02d' % T.SEL_SNAP
out = {}
for tour in T.TOURS:
    kept = fitj[tour]['kept']
    X, F, y, pos, by = T.snap_rows(rows, tour, snap)
    P, MU, E = T.loso(F, y, pos, by, kept)
    unr = X['rank'].isna().values; elo = X.elo.fillna(1500).values; n = X.n.values
    cells = {'ranked': ~unr, 'unranked': unr, 'unranked elo 1700+': unr & (elo >= 1700), 'unranked idle (n 0)': unr & (n == 0),
             'unranked elo 1600-1699': unr & (elo >= 1600) & (elo < 1700), 'unranked elo 1800+': unr & (elo >= 1800)}
    res = {}
    for k, m in cells.items():
        d = [float((E[m & (by == b)] - y[m & (by == b)]).mean()) for b in np.unique(by) if (m & (by == b)).sum()]
        t = np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d)) + 1e-12) if len(d) > 2 else float('nan')
        res[k] = {'n': int(m.sum()), 'pred': round(float(E[m].mean()), 2) if m.any() else None, 'real': round(float(y[m].mean()), 2) if m.any() else None,
                  'bias': round(float((E[m] - y[m]).mean()), 2) if m.any() else None, 't': round(float(t), 2), 'years': len(d),
                  'p40': round(float((y[m] >= 40).mean()), 3) if m.any() else None}
    # candidate B: unr x elo and idle flag
    F2 = F.copy(); e = (elo - 1500) / 100
    F2['unr_elo'] = unr * e; F2['unr_idle'] = (unr & (n == 0)).astype(float)
    m0 = T.fold_mse(E, y, by)
    cand = {}
    for add in (['unr_elo'], ['unr_idle'], ['unr_elo', 'unr_idle']):
        m1 = T.fold_mse(T.loso(F2, y, pos, by, kept + add)[2], y, by)
        g = T.gate(m0, m1)
        f0 = T.forward(F2, y, pos, by, X.season.values, kept); f1 = T.forward(F2, y, pos, by, X.season.values, kept + add)
        cand['+'.join(add)] = dict(g, fwd=[round(f0[0], 3), round(f1[0], 3)])
    out[tour] = {'rows': int(len(y)), 'mse': round(float(m0.mean()), 3), 'cells': res, 'B': cand}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, 'tennis_unranked.json'), 'w'), indent=1)
