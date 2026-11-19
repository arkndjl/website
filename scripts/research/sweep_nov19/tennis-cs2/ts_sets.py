#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""TS: exact set-score chances from the walk-forward match chance, sets iid vs one overdispersion parameter tau
(per-set logit = x + tau * e, e ~ N(0,1) once per match, x solved so the match chance is unchanged)."""
import pickle, re
from tcommon import *
B = pickle.load(open(os.path.join(CACHE, 'base_z.pkl'), 'rb'))
GH_X, GH_W = np.polynomial.hermite_e.hermegauss(21); GH_W = GH_W / GH_W.sum()
TAUS = [round(.1 * i, 1) for i in range(13)]


def setscore(s):
    """(winner sets, loser sets) from a score string; None when not a completed match"""
    if not s or re.search(r'RET|W/O|DEF|ABN|UNF|WO|Def|Walk', s, re.I): return None
    w = l = 0
    for part in s.split():
        m = re.match(r'^\[?(\d+)-(\d+)', part)
        if not m: return None
        a, b = int(m.group(1)), int(m.group(2))
        if a > b: w += 1
        elif b > a: l += 1
        else: return None
    return w, l


def dist(s, need):
    """P(winner side wins need-k) for k = 0..need-1 and P(loses k-need), per-set chance s (array over nodes)"""
    from math import comb
    win = [comb(need - 1 + k, k) * s ** need * (1 - s) ** k for k in range(need)]
    lose = [comb(need - 1 + k, k) * (1 - s) ** need * s ** k for k in range(need)]
    return win, lose


_memo = {}


def probs(p, need, tau):
    k = (round(p, 3), need, tau)
    if k not in _memo: _memo[k] = _probs(min(max(k[0], .001), .999), need, tau)
    return _memo[k]


def _probs(p, need, tau):
    """mixture set-score chances with match chance p: bisection on x"""
    lo, hi = -12.0, 12.0
    for _ in range(50):
        x = (lo + hi) / 2
        s = 1 / (1 + np.exp(-(x + tau * GH_X)))
        win, _ = dist(s, need)
        if float(sum((w * GH_W).sum() for w in win)) < p: lo = x
        else: hi = x
    s = 1 / (1 + np.exp(-(x + tau * GH_X)))
    win, lose = dist(s, need)
    return [float((w * GH_W).sum()) for w in win], [float((w * GH_W).sum()) for w in lose]


z, y, tid, bo = B['z'], B['y'], B['tid'], B['bo']
rows = []
for i, sc in enumerate(B['score']):
    ss = setscore(sc)
    if ss is None or np.isnan(z[i]) or y[i] < 2012: continue
    need = 3 if bo[i] == 5 else 2
    if ss[0] != need or ss[1] >= need: continue
    rows.append((i, need, ss[1]))
idx = np.array([r[0] for r in rows]); yy, tt = y[idx], tid[idx]
pm = 1 / (1 + np.exp(-z[idx]))
L = {}
for tau in TAUS:
    v = np.empty(len(rows))
    for j, (i, need, k) in enumerate(rows):
        win, _ = probs(float(pm[j]), need, tau)
        v[j] = -np.log(max(win[k], 1e-12))
    L[tau] = v
    print(tau, round(float(v[(yy <= 2022)].mean()), 5), round(float(v[yy >= 2023].mean()), 5), flush=True)
tune, held = yy <= 2022, yy >= 2023
best = min(TAUS, key=lambda t: L[t][tune].mean())
d = L[best] - L[0.0]
out = {'n': len(rows), 'best_tau': best, 'tune_ll': {t: round(float(L[t][tune].mean()), 5) for t in TAUS},
       'tune': tclust(d[tune], tt[tune]), 'held': tclust(d[held], tt[held]) if best else None,
       'seasons': {int(s): round(float(d[yy == s].mean() * 1e4), 2) for s in range(2012, 2027)},
       'll': {'iid_held': round(float(L[0.0][held].mean()), 5), 'tau_held': round(float(L[best][held].mean()), 5)}}
out['held_better'] = sum(out['seasons'][s] < 0 for s in range(2023, 2027))
out['pass'] = bool(best and out['held']['t'] <= -2 and out['tune']['d1e4'] < 0 and out['held_better'] >= 3)
print(json.dumps(out, indent=1)); save('ts_results', out)
