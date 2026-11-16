#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Cross-sport FV driver ports on the CBB returner ladder (research only; prereg.md C1-C3).

    python3 scripts/cbb_careers_kit.py
    python3 scripts/research/fv_port_nov16/cbb_port.py      # -> scripts/research/fv_port_nov16/cbb_results.json

C1 role block (soccer's detailed position block): last-season Barttorvik role dummies, base Wing F.
C2 tshare (soccer's lg_share): (z team strength + 2.5) x minutes share, team strength = minutes-weighted mean BPM.
C3 tree blend (soccer's .5 linear + .5 GBM): every rung's conditional chance averaged with a HistGBM on the kept columns.
Gates and folds: scripts/cbb_fv_sweep2.py (class folds + two player splits, held 2017-19 tops, forward 2020-23)."""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
import cbb_data as D
import cbb_fit as F
import cbb_fv_drivers as H
import cbb_fv_sweep2 as S2

ROLE_D = {'PG': ('Pure PG', 'Scoring PG'), 'CG': ('Combo G',), 'WG': ('Wing G',), 'S4': ('Stretch 4',), 'PFC': ('PF/C',), 'C': ('C',)}
BLOCK = ['r_' + k for k in ROLE_D]
OUT = os.path.join(HERE, 'cbb_results.json')


def team_strength(careers):
    acc = defaultdict(lambda: [0.0, 0.0])
    for c in careers:
        for s in c['seasons']:
            w = s.get('min_per') or 0
            if w > 0 and s.get('bpm') is not None:
                a = acc[(s['year'], s['team'])]; a[0] += w * s['bpm']; a[1] += w
    ts = {k: v[0] / v[1] for k, v in acc.items() if v[1] > 0}
    v = np.array(list(ts.values())); m, sd = v.mean(), v.std()
    return {k: (x - m) / sd for k, x in ts.items()}


def colset(kept, cand):
    if cand == 'block': return kept + BLOCK
    if cand == 'tree': return kept
    return kept + [cand]


# ---- C3: the blend's own out-of-fold and held passes ---------------------------------------------------------------
def gbm():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_depth=3, max_iter=300, learning_rate=0.05, min_samples_leaf=40, l2_regularization=1.0, random_state=0)


def fit_blend(rows, X, idx, lam, cols):
    m = H.fit_m(rows, X, idx, lam, cols)
    y = np.array([r['y'] for r in rows], float); trees = []
    for j, t in enumerate(F.LADDER):
        on = y >= (F.LADDER[j - 1] if j else -1); o = (y[on] >= t).astype(int)
        trees.append(gbm().fit(X[on][:, idx], o) if 0 < o.sum() < len(o) else None)
    return m, trees


def pred_blend(mt, X):
    m, trees = mt
    Z = m['std'](X[:, m['idx']]); A = np.hstack([np.ones((len(Z), 1)), Z])
    C = []
    for j, w in enumerate(m['w']):
        cl = 1 / (1 + np.exp(-np.clip(A @ w, -30, 30)))
        ct = trees[j].predict_proba(X[:, m['idx']])[:, 1] if trees[j] is not None else cl
        C.append(0.5 * cl + 0.5 * ct)
    return np.cumprod(np.column_stack(C), axis=1)


def cv_tree(rows, kept, lam, cache):
    import hashlib
    y = np.array([r['y'] for r in rows], float); pid = [r['pid'] for r in rows]
    splits = {'cls': np.array([r['cls'] for r in rows]), 'md5': np.array([F.fold_of(p) for p in pid]),
              'salt': np.array([int(hashlib.md5(('s' + str(p)).encode()).hexdigest(), 16) % F.FOLDS for p in pid])}
    X = F.matrix(rows, kept); idx = list(range(len(kept))); res = {}
    for n, fo in splits.items():
        if n not in cache: cache[n] = F.row_dev(H.oof(rows, X, idx, lam, fo, kept), y)
        P = np.zeros((len(rows), len(F.LADDER)))
        for k in range(F.FOLDS):
            tr, te = fo != k, fo == k
            P[te] = pred_blend(fit_blend([r for r, q in zip(rows, tr) if q], X[tr], idx, lam, kept), X[te])
        RD = cache[n] - F.row_dev(P, y); d = RD.sum(1)
        res[n] = {'gain': round(float(d.sum() * 100), 3), 'folds': int(sum(d[fo == k].sum() > 0 for k in range(F.FOLDS))),
                  't': round(S2.ctstat(d, pid), 2), 'rungs': [round(float(x * 100), 3) for x in RD.sum(0)]}
    return res


def held_tree(rows, hr, kept, lam, base_cache):
    out = {}; X = F.matrix(rows, kept); idx = list(range(len(kept)))
    mt = fit_blend(rows, X, idx, lam, kept)
    for tag, lo, hi in (('held', 2017, 2019), ('fwd', 2020, 2023)):
        sub = [r for r in hr if lo <= r['year'] <= hi]; yh = np.array([r['yh'] for r in sub], float)
        P0, T0 = base_cache[tag]
        P1 = pred_blend(mt, F.matrix(sub, kept)); T1 = S2.board_tops(sub, F.expected(P1), yh)
        d = F.row_dev(P0, yh).sum(1) - F.row_dev(P1, yh).sum(1); yrs = np.array([r['year'] for r in sub])
        o = {'gain': round(float(d.sum() * 100), 3), 't': round(S2.ctstat(d, [r['pid'] for r in sub]), 2),
             'years': f"{sum(d[yrs == Y].sum() > 0 for Y in sorted(set(yrs)))}/{len(set(yrs))}"}
        for k in T0:
            o[k] = (round(float(T0[k].mean()), 3), round(float(T1[k].mean()), 3), int((T1[k] > T0[k]).sum()), int((T1[k] < T0[k]).sum()))
        out[tag] = o
    return out


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    TS = team_strength(careers)
    fitj = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    M = fitj['models']['returner']; F.TOP_MEAN = M['topMean']
    rows, hr = [], []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if not (2009 <= s['year'] <= 2023) or i == 0: continue
            f = F.features(c, i); p = c['seasons'][i - 1]
            for k, roles in ROLE_D.items(): f['r_' + k] = 1.0 if p.get('role') in roles else 0.0
            z = TS.get((p['year'], p['team']))
            f['tshare'] = (z + 2.5) * (p.get('min_per') or 0) / 100 if z is not None else None
            r = {'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'], 'last': c['last'],
                 'cls': (c['last'] - 2009) % F.FOLDS, 'f': f}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            elif s['year'] >= 2017 and c['nba']['fvh'] is not None: hr.append(r)
    seen = {r['pid'] for r in rows}; hr = [r for r in hr if r['pid'] not in seen]
    print(f'returner rows: train {len(rows)}, held {sum(r["year"] <= 2019 for r in hr)}, fwd {sum(r["year"] >= 2020 for r in hr)}')
    for k in BLOCK + ['tshare']:
        v = np.array([r['f'].get(k) for r in rows], dtype=float); nba = np.array([r['y'] >= 30 for r in rows])
        print(f'  {k}: mean {np.nanmean(v):.3f}, NBA {np.nanmean(v[nba]):+.3f} vs non {np.nanmean(v[~nba]):+.3f}, missing {int(np.isnan(v).sum())}')
    S2.colset = colset
    res = {}; cvc = {}; hc = {}
    pick = sys.argv[1].split(',') if len(sys.argv) > 1 else ['block', 'tshare', 'tree']
    for cnd in pick:
        if cnd == 'tree':
            if 'held' not in hc: S2.held(rows, hr, M['kept'], M['lam'], 'tshare', hc)   # fills the base cache
            res[cnd] = {'cv': cv_tree(rows, M['kept'], M['lam'], cvc), **held_tree(rows, hr, M['kept'], M['lam'], hc)}
        else:
            res[cnd] = {'cv': S2.cv(rows, M['kept'], M['lam'], cnd, cvc), **S2.held(rows, hr, M['kept'], M['lam'], cnd, hc)}
        print(cnd, json.dumps(res[cnd])); sys.stdout.flush()
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    prev.update(res); json.dump(prev, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
