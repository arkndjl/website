#!/usr/bin/env python3
"""Next up / breakout odds (scripts/cbb_breakout_sweep.py protocol: leave one season out, log loss by season, kept logistic).
Candidates added alone to the kept columns, and in place of the Marcel term of 'projection gap':
  pXPM gap  = pXPM (core | board, point in time) - his best shrunk BPM so far
Also the same model scored on a breakout defined on rXPM (bar and outcome).  -> breakout.json"""
import json, os, sys
from collections import defaultdict
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import breakout_lib as L, cbb_breakout as B, cbb_breakout_research as R, cbb_breakout_sweep as SW
fit = json.load(open(R.OUT)); P, _ = R.load(R.SRC); CX = R.context(P)
bar, keep = fit['breakout']['L'], fit['breakout']['keep']
ig = [0]
for k in keep:
    f0 = B.bo_feats(next(iter(P.values())), 0, 0, 0, {'vac': 0, 'inc': 0, 'top': 0, 'lvl': 0, 'nlvl': 0, 'xfer': 0}, 0.0)
    break
S, yv, yx, X, G, MARCOL = [], [], [], [], {'px': [], 'px2': []}, None
for (pid, y), a in P.items():
    b = P.get((pid, y + 1))
    if y < R.Y0 or not b or a['m'] < R.ROW_M or a['gp'] < R.ROW_GP: continue
    hist = B.history(P, pid, y); s0, cur = B.level(a, hist)
    if s0 >= bar: continue
    f = B.bo_feats(a, s0, cur, B.marcel(hist, y), CX[(pid, y)], 0.0)
    cols = sum([f['base']] + [f[k] for k in keep], [])
    if MARCOL is None: MARCOL = len(sum([f['base']] + [f[k] for k in keep[:keep.index('projection gap')]], []))
    X.append(cols); S.append(y + 1); yv.append(1.0 if B.broke_out(b, bar) else 0.0)
    bx = C.get(pid, y + 1, 'xpm', b['bpm']); yx.append(1.0 if b['m'] >= B.ROLE_M and B.shr(bx, b['m']) >= bar else 0.0)
    for k in G: G[k].append(C.get(pid, y, k, B.marcel(hist, y)) - s0)
S, yv, yx, X = np.array(S, float), np.array(yv), np.array(yx), np.array(X); G = {k: np.array(v) for k, v in G.items()}
out = {'n': len(yv), 'rate': round(float(yv.mean()), 4), 'rate_rxpm_def': round(float(yx.mean()), 4), 'agree': round(float((yv == yx).mean()), 4)}
for nm, y in (('BPM definition', yv), ('rXPM outcome', yx)):
    e0 = SW.by_season(S, y, SW.oos_logit(S, y, X)); out[nm] = {}
    for k in G:
        Xs = X.copy(); Xs[:, MARCOL] = G[k]
        out[nm][k + ' added'] = L.compare(e0, SW.by_season(S, y, SW.oos_logit(S, y, np.column_stack([X, G[k]]))))
        out[nm][k + ' for Marcel'] = L.compare(e0, SW.by_season(S, y, SW.oos_logit(S, y, Xs)))
        print(nm, k, out[nm][k + ' added'], out[nm][k + ' for Marcel'], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'breakout.json'), 'w'), indent=1)
