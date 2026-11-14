# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CS2 prospects, pre-registered with the player value batch (Holm over 2): does the cumulative metric add to the
prospect projection (next 12 months' RWA, scripts/cs2_players.py prospect_fit) beside rating + age + S/A share?
  rar   RWA x last year's rounds / 1000 (rounds above average, the board's RAR before its replacement shift)
  lr12  log of last year's rounds (volume alone)
Tune cutoffs before HELD, held cutoffs scored; paired t on round-weighted squared error (negative = better).
    python3 scripts/research/cs2_value_nov14/prospect_rar.py -> prospect_rar.json beside it"""
import datetime as dt, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import cs2_players as C

F = json.load(open(os.path.join(C.ROOT if hasattr(C, 'ROOT') else os.path.dirname(os.path.dirname(os.path.dirname(HERE))), 'data', 'cs2_players_fit.json')))
M = C.Maps()
beta = np.array([F['beta'][s] for s in C.STATS])
p = F['params']
c = C.contributions(M, beta, np.array(F['mline']), p['pm'])
pdir = C.load_pdir()
last = int(M.gd.max())
cuts, d = [], dt.date(2024, 10, 1)
while d.toordinal() + 365 <= last:
    cuts.append(d.toordinal()); d = (d + dt.timedelta(days=92)).replace(day=1)
data = []
for T in cuts:
    pr = C.prospect_rows(M, c, p, T, pdir)
    thF, _ = C.ratings(M, c, T + 365, p)
    fut, rf = C.window_stats(M, c, thF, T, T + 365, p)
    i = pr['i'][rf[pr['i']] >= 600]
    data.append({'T': T, 'th': pr['th'][i], 'age': pr['age'][i], 'ss': pr['ss'][i], 'y': fut[i], 'w': np.minimum(rf[i], 3000),
                 'rar': pr['th'][i] * pr['r12'][i] / 1000, 'lr12': np.log(pr['r12'][i])})
tune = [x for x in data if dt.date.fromordinal(x['T']).isoformat() < C.HELD[0]]
held = [x for x in data if dt.date.fromordinal(x['T']).isoformat() >= C.HELD[0]]


def stack(xs, cols):
    X = np.concatenate([np.column_stack([np.ones(len(x['y']))] + [np.nan_to_num(x[k] - (22 if k == 'age' else 0)) for k in cols]) for x in xs])
    return X, np.concatenate([x['y'] for x in xs]), np.concatenate([x['w'] for x in xs])


base = ['th', 'age', 'ss']
out = {}
X, y, w = stack(tune, base); b0 = C.ols(X, y, w)
Xh, yh, wh = stack(held, base); e0 = yh - Xh @ b0
for k in ('rar', 'lr12'):
    X, y, w = stack(tune, base + [k]); b = C.ols(X, y, w)
    Xh, yh, wh = stack(held, base + [k]); e = yh - Xh @ b
    dl = wh * (e ** 2 - e0 ** 2)
    out[k] = {'coef': round(float(b[-1]), 4), 'mse0': round(float((wh * e0 ** 2).sum() / wh.sum()), 4),
              'mse': round(float((wh * e ** 2).sum() / wh.sum()), 4), 'n': int(len(yh)),
              't': round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 2)}
    print(k, out[k], flush=True)
json.dump(out, open(os.path.join(HERE, 'prospect_rar.json'), 'w'), indent=1)
