# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T1: tree blend on the hockey stage models (.5 live linear + .5 boosted trees on every stage input), class held out."""
import sys, os, json, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor as GB
import hockey_prospects as H
D = H.D

TCOLS = ['wjc', 'progp', 'ahls', 'nhgrow', 'fv0', 'nh', 'nh_na', 'nhD', 'pro', 'age', 'gp', 'war', 'G', 'D', 'nany', 'dur', 'gsvc']
SET = dict(max_depth=3, learning_rate=.05, max_iter=300, min_samples_leaf=40, l2_regularization=1.0, random_state=0)
W = H.war_tables(); rows = H.read_rows(W); H.nhl_so_far(rows, W); sc = H.outcome_scale(rows)
tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr]); F = [H.feats(r) for r in tr]
babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
fit = json.load(open(H.FIT)); kept = fit['kept']
_, p0 = H.score(F, y, cls, kept); oof = {id(r): float(p) for r, p in zip(tr, p0)}
rho = lambda u, v: float(stats.spearmanr(u, v)[0])
C = sorted(set(cls)); OUT = {}; G = {c: [] for c in C}
for k in range(1, 5):
    st = fit['stages'][str(k)]; kk = st['kept']
    sub = [r for r in tr if r['year'] + k < D.current_season() and H.onboard(r, k)]
    Fk = [H.stage_feats(r, k, oof[id(r)]) for r in sub]
    yk = np.array([H.fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub]); pk = np.array([r['pick'] for r in sub])
    if 'comp' in kk:
        pre = kk[:kk.index('comp')]
        pool = H.comp_pool(Fk, yk - np.clip(H.loco(Fk, yk, ck, pre), 20, 80), [H.comp_grp(r) for r in sub], ck, [r['name'] for r in sub], yk)
        for f, r, c in zip(Fk, sub, ck): f['comp'] = H.comp_of(pool, f, H.comp_grp(r), own=c)
    X = np.array([[f[c] for c in kk] for f in Fk]); T = np.array([[f[c] for c in TCOLS] for f in Fk])
    kp = (st.get('pre') or {}).get('kept')
    if kp:
        H.pre_fill(Fk, sub, k); Xp = np.array([[f[c] for c in kp] for f in Fk])
    lin = lambda X_, a, b: np.clip(H.pred(H.ols(X_[a], yk[a]), X_[b]), 20, 80)
    tree = lambda a, b: np.clip(GB(**SET).fit(T[a], yk[a]).predict(T[b]), 20, 80)
    l0 = np.zeros(len(yk)); tr_ = np.zeros(len(yk)); lp = np.zeros(len(yk))
    for c in sorted(set(ck)):
        b = ck == c; l0[b] = lin(X, ~b, b); tr_[b] = tree(~b, b)
        if kp: lp[b] = lin(Xp, ~b, b)
    p1 = .5 * l0 + .5 * tr_
    e0, e1 = (l0 - yk) ** 2, (p1 - yk) ** 2
    cs_ = sorted(set(ck)); g = np.array([e0[ck == c].mean() - e1[ck == c].mean() for c in cs_])
    for c, v in zip(cs_, g): G[c].append(v)
    t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g))); top = pk <= 64
    a, b = ck <= 2015, ck > 2015
    f0 = lin(X, a, b); f1 = .5 * f0 + .5 * tree(a, b); tb = pk[b] <= 64
    t32 = lambda p: float(np.mean([yk[np.where(ck == c)[0][np.argsort(-p[ck == c])[:32]]].mean() for c in cs_]))
    res = dict(n=len(yk), kept=kk, mse=[round(float(e0.mean()), 3), round(float(e1.mean()), 3)], tree_only=round(float(((tr_ - yk) ** 2).mean()), 3),
               t=round(float(t), 2), wins=int((g > 0).sum()), of=len(g), top64=[round(float(e0[top].mean()), 2), round(float(e1[top].mean()), 2)],
               top64rho=[round(rho(l0[top], yk[top]), 4), round(rho(p1[top], yk[top]), 4)],
               fwd=[round(float(np.mean((f0 - yk[b]) ** 2)), 3), round(float(np.mean((f1 - yk[b]) ** 2)), 3)],
               fwd_top64=[round(float(np.mean((f0 - yk[b])[tb] ** 2)), 2), round(float(np.mean((f1 - yk[b])[tb] ** 2)), 2)],
               fwd_top64rho=[round(rho(f0[tb], yk[b][tb]), 4), round(rho(f1[tb], yk[b][tb]), 4)],
               top32real=[round(t32(l0), 2), round(t32(p1), 2)])
    if kp:
        pp = .5 * lp + .5 * tr_; ep0, ep1 = (lp - yk) ** 2, (pp - yk) ** 2
        gp = np.array([ep0[ck == c].mean() - ep1[ck == c].mean() for c in cs_])
        res['pre'] = dict(mse=[round(float(ep0.mean()), 3), round(float(ep1.mean()), 3)], t=round(float(gp.mean() / (gp.std(ddof=1) / math.sqrt(len(gp)))), 2), wins=int((gp > 0).sum()))
    OUT[k] = res; print(k, json.dumps(res))
g = np.array([np.mean(G[c]) for c in C]); t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))
OUT['family'] = dict(gain=round(float(g.mean()), 3), t=round(float(t), 2), p=float(stats.t.sf(t, len(g) - 1)), wins=int((g > 0).sum()), of=len(g), byClass=[round(float(v), 2) for v in g])
print('family', json.dumps(OUT['family']))
if len(sys.argv) > 1: json.dump(OUT, open(sys.argv[1], 'w'), indent=1)
