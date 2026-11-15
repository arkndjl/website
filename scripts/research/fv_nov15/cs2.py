# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""C1: teammates' mean rating over the last year as a CS2 prospect input, on rating + age + S/A share."""
import sys, os, json, math, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np
import cs2_players as P

fj = json.loads(P.FIT.read_text()); p = fj['params']
M = P.Maps()
c = P.contributions(M, np.array([fj['beta'][k] for k in P.STATS]), np.array(fj['mline']), p.get('pm', 0.0))
pdir = P.load_pdir()
LOCK = dt.date(2026, 11, 11).toordinal()
cuts = []; d = dt.date(2024, 10, 1)
while d.toordinal() + 365 < LOCK:
    cuts.append(d.toordinal()); d = (d + dt.timedelta(days=92)).replace(day=1)
n = len(M.pids)
data = []
for T in cuts:
    pr = P.prospect_rows(M, c, p, T, pdir)
    thF, _ = P.ratings(M, c, T + 365, p)
    fut, rf = P.window_stats(M, c, thF, T, T + 365, p)
    i = pr['i'][rf[pr['i']] >= 600]
    m = (M.d >= T - 365) & (M.d < T)
    th = pr['th']
    mate = (th[M.p][M.five[M.g, M.side]].sum(1) - th[M.p]) / 4
    w = M.R * m
    tm = np.bincount(M.p, w * mate, n) / np.maximum(np.bincount(M.p, w, n), 1)
    data.append(dict(T=T, th=th[i], age=pr['age'][i], ss=pr['ss'][i], tm=tm[i], y=fut[i], w=np.minimum(rf[i], 3000), pid=i))
H0 = P.HELD[0]
tune = [x for x in data if dt.date.fromordinal(x['T']).isoformat() < H0]
held = [x for x in data if dt.date.fromordinal(x['T']).isoformat() >= H0]


def stack(xs, cols):
    X = np.concatenate([np.column_stack([np.ones(len(x['y']))] + [np.nan_to_num(x[k] - (22 if k == 'age' else 0)) for k in cols]) for x in xs])
    return X, np.concatenate([x['y'] for x in xs]), np.concatenate([x['w'] for x in xs])


out = {}
for nm, cols in (('base', ['th', 'age', 'ss']), ('tm', ['th', 'age', 'ss', 'tm'])):
    X, y, w = stack(tune, cols); b = P.ols(X, y, w)
    Xh, yh, wh = stack(held, cols); e = yh - Xh @ b
    out[nm] = dict(b=[round(float(v), 4) for v in b], mse=float((wh * e * e).sum() / wh.sum()), e=e, w=wh)
dl = out['tm']['w'] * (out['tm']['e'] ** 2 - out['base']['e'] ** 2)
t = float(dl.mean() / dl.std() * math.sqrt(len(dl)))
pid = np.concatenate([x['pid'] for x in held])
u = np.unique(pid); cl = np.array([dl[pid == q].sum() for q in u])          # clustered by player
tc = float(cl.mean() / cl.std(ddof=1) * math.sqrt(len(cl)))
res = dict(test='C1 teammates mean rating', cuts=[dt.date.fromordinal(x['T']).isoformat() for x in data], nTune=int(sum(len(x['y']) for x in tune)),
           nHeld=len(dl), base=dict(b=out['base']['b'], mse=round(out['base']['mse'], 4)), tm=dict(b=out['tm']['b'], mse=round(out['tm']['mse'], 4)),
           t=round(t, 2), tPlayer=round(tc, 2), players=len(u))
print(json.dumps(res, indent=1))
if len(sys.argv) > 1: json.dump(res, open(sys.argv[1], 'w'), indent=1)
