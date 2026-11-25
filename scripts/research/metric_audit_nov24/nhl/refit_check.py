#!/usr/bin/env python3
"""P3 confirmation on pWAR's own gate (nhl_players.fit): the team design built from raw vs flurry + score + venue
adjusted xG (5v5 on-ice evf/eva and ixg), the stored K / KG / Marcel weights / lambda and kept inputs, weights REFIT per
input set: leave one season out, and walk forward (train on seasons before, from 2012). Paired t on team-season
squared error. Seasons 2010 ... 2026 (no 2026-27). -> refit_check.json"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..')); sys.path.insert(0, HERE)
import nhl_players as P
from audit_variant import variant, _mp

FIT = json.load(open(P.FIT))
cols = [P.FIT_NAMES.index(c) for c in FIT['w']]
out = {}
pred = {}
for kind in ('raw', 'fsva'):
    P.mp_file = variant(kind)
    fd = P.fit_data()
    X, y, keys = P.team_design(fd, FIT['K'], FIT['KG'], tuple(FIT['wts']))
    P.mp_file = _mp
    S_ = np.array([k[0] for k in keys])
    lo, wf = np.zeros(len(y)), np.full(len(y), np.nan)
    for s in sorted(set(S_)):
        w = P.ridge_w(X[S_ != s], y[S_ != s], cols, FIT['lam'])
        b0 = float((y[S_ != s] - X[S_ != s][:, cols] @ w).mean())
        lo[S_ == s] = X[S_ == s][:, cols] @ w + b0
        if s >= 2012:
            tr = S_ < s; w = P.ridge_w(X[tr], y[tr], cols, FIT['lam']); b0 = float((y[tr] - X[tr][:, cols] @ w).mean())
            wf[S_ == s] = X[S_ == s][:, cols] @ w + b0
    pred[kind] = (lo, wf, y, S_)
    base = float(((y - y.mean()) ** 2).mean())
    out[kind] = {'loso': round(1 - float(((lo - y) ** 2).mean()) / base, 4),
                 'walk': round(1 - float(np.nanmean((wf - y) ** 2)) / float(np.mean((y[~np.isnan(wf)] - y[~np.isnan(wf)].mean()) ** 2)), 4),
                 'w': {c: round(float(v), 4) for c, v in zip(FIT['w'], P.ridge_w(X, y, cols, FIT['lam']))}}
    print(kind, out[kind], flush=True)
for j, nm in ((0, 'loso'), (1, 'walk')):
    a, b, y, S_ = pred['fsva'][j], pred['raw'][j], pred['raw'][2], pred['raw'][3]
    m = ~np.isnan(a)
    d = (a[m] - y[m]) ** 2 - (b[m] - y[m]) ** 2
    won = sum(1 for s in set(S_[m]) if d[S_[m] == s].sum() < 0)
    out[nm + 'Test'] = {'dMse': round(float(d.mean()), 5), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
                        'seasonsBetter': won, 'seasons': len(set(S_[m]))}
    print(nm, out[nm + 'Test'], flush=True)
json.dump(out, open(os.path.join(HERE, 'refit_check.json'), 'w'), indent=1)
