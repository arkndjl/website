#!/usr/bin/env python3
"""CS2 prospects: a missing birth date is scored as age 22 (np.nan_to_num(age - 22)), train and serve. Does a
missing-age flag (or dropping missing rows from the age fit) project next-year rating better? Walk-forward as
cs2_players.prospect_fit: tune cutoffs before HELD, scored on held. Nov 18 2026 zero-snap audit."""
import datetime as dt, json, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cs2_players as C

fitj = json.loads(C.FIT.read_text()); p = fitj['params']
M = C.Maps(); beta = np.array([fitj['beta'][k] for k in C.STATS])
c = C.contributions(M, beta, np.array(fitj['mline']), p.get('pm', 0.0)); pdir = C.load_pdir()
last = int(M.gd.max()); cuts = []; d = dt.date(2024, 10, 1)
while d.toordinal() + 365 <= last:
    cuts.append(d.toordinal()); d = (d + dt.timedelta(days=92)).replace(day=1)
data = []
for T in cuts:
    pr = C.prospect_rows(M, c, p, T, pdir)
    thF, _ = C.ratings(M, c, T + 365, p); fut, rf = C.window_stats(M, c, thF, T, T + 365, p)
    i = pr['i'][rf[pr['i']] >= 600]
    data.append({'T': T, 'th': pr['th'][i], 'age': pr['age'][i], 'ss': pr['ss'][i], 'y': fut[i], 'w': np.minimum(rf[i], 3000)})
tune = [x for x in data if dt.date.fromordinal(x['T']).isoformat() < C.HELD[0]]
held = [x for x in data if dt.date.fromordinal(x['T']).isoformat() >= C.HELD[0]]
cat = lambda xs, k: np.concatenate([x[k] for x in xs])


def X(xs, flag):
    a = cat(xs, 'age'); na = np.isnan(a)
    cols = [np.ones(len(a)), cat(xs, 'th'), np.nan_to_num(a - 22), cat(xs, 'ss')]
    if flag: cols.append(na.astype(float))
    return np.column_stack(cols), na


out = {}
Xt, nat = X(tune, False); Xh, nah = X(held, False); yt, wt, yh, wh = cat(tune, 'y'), cat(tune, 'w'), cat(held, 'y'), cat(held, 'w')
bA = C.ols(Xt, yt, wt); eA = yh - Xh @ bA
Xt2, _ = X(tune, True); Xh2, _ = X(held, True); bB = C.ols(Xt2, yt, wt); eB = yh - Xh2 @ bB
dl = wh * (eB ** 2 - eA ** 2); t = float(dl.mean() / dl.std() * math.sqrt(len(dl)))
mse = lambda e, m=None: float((wh[m] * e[m] ** 2).sum() / wh[m].sum()) if m is not None else float((wh * e * e).sum() / wh.sum())
bias = lambda e, m: float((wh[m] * e[m]).sum() / wh[m].sum())
out = {'nTune': len(yt), 'nHeld': len(yh), 'missTune': int(nat.sum()), 'missHeld': int(nah.sum()),
       'meanAgeKnownTune': float(np.nanmean(cat(tune, 'age'))),
       'A': {'b': bA.round(4).tolist(), 'mse': mse(eA), 'mseMissing': mse(eA, nah), 'biasMissing': bias(eA, nah), 'biasKnown': bias(eA, ~nah)},
       'B': {'b': bB.round(4).tolist(), 'mse': mse(eB), 'mseMissing': mse(eB, nah), 'biasMissing': bias(eB, nah), 'biasKnown': bias(eB, ~nah)},
       't_B_vs_A': round(t, 2)}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cs2_age_missing.json'), 'w'), indent=1)
