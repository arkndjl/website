#!/usr/bin/env python3
"""CS2 RWA: full BPM-style team adjustment (pm 1: each map's team residual split equally over the five) vs shipped pm .5.
Held months (Jul 2025+), shipped params otherwise, stat weights + scale a fit on tune months only.
  predict : walk-forward next-month map round share (the RWA backtest), paired t on per-map squared error
  playerR : rating at month start vs that month's raw box contribution (pm 0), rounds-weighted, players 100+ rounds
  describe: same-window team sum of the month's own contributions vs round share (by construction for pm 1)"""
import datetime as dt, json, math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import cs2_players as P

M = P.Maps(); last = dt.date.fromordinal(int(M.gd.max()))
tune_g = M.gd < P.ordd(P.TUNE[1]); beta, ml, _ = P.stat_weights(M, tune_g)
tm, hm = P.months(*P.TUNE, last), P.months(*P.HELD, last)
base = dict(json.loads(P.FIT.read_text())['params'])
c0 = P.contributions(M, beta, ml, 0.0)
res = {}
for pm in (0.5, 1.0):
    c = P.contributions(M, beta, ml, pm); p = dict(base, pm=pm); p['a'] = P.fit_scale(M, c, p, tm[::2])
    e = P.map_sq(M, c, p, hm)
    xs, ys, ws = [], [], []
    for mo in hm:
        T = P.ordd(mo + '-01'); T2 = P.ordd((dt.date.fromordinal(T) + dt.timedelta(days=32)).replace(day=1).isoformat())
        th, _ = P.ratings(M, c, T, p); m = (M.d >= T) & (M.d < T2)
        n = len(M.pids); R = np.bincount(M.p, M.R * m, n); raw = np.bincount(M.p, c0 * M.R * m, n) / np.maximum(R, 1)
        k = R >= 100; xs += list(th[k]); ys += list(raw[k]); ws += list(R[k])
    x, y, w = map(np.array, (xs, ys, ws)); mx, my = np.average(x, weights=w), np.average(y, weights=w)
    r = np.average((x - mx) * (y - my), weights=w) / math.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w))
    tot = np.zeros((len(M.games), 2)); np.add.at(tot, (M.g, M.side), c)
    yy = 100 * (M.y[M.five[:, 0, 0]] - .5)
    desc = float(np.corrcoef(tot[:, 0], yy)[0, 1] ** 2)
    res[pm] = {'e': e, 'predictMSE': float(e.mean()), 'playerR': float(r), 'describe': desc, 'a': p['a']}
    print(pm, {k: v for k, v in res[pm].items() if k != 'e'}, flush=True)
d = res[1.0]['e'] - res[0.5]['e']
out = {'metric': 'RWA', 'candidate': 'pm 1 (full team adjustment)', 'baseline': 'pm .5 (shipped)', 'heldMonths': len(hm), 'maps': len(d),
       'baseline_': {k: round(v, 5) for k, v in res[0.5].items() if k != 'e'}, 'candidate_': {k: round(v, 5) for k, v in res[1.0].items() if k != 'e'},
       't': round(float(d.mean() / d.std() * math.sqrt(len(d))), 2)}
out['pass'] = bool(out['t'] <= 0 and res[1.0]['playerR'] >= res[0.5]['playerR'] - .01)
print(json.dumps(out, indent=1))
json.dump(out, open(Path(__file__).with_suffix('.json'), 'w'), indent=1)
