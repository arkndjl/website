#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball breakout odds: the improvement sweep on the "not yet broken out" model
(scripts/cbb_breakout_research.py must have run first; this adds data/cbb_breakout_fit.json breakout.sweep).

    python3 scripts/cbb_breakout_sweep.py [research_seasons.csv]

Tests (pre-registered, leave one season out, Holm across all ten; scripts/breakout_lib.py):
  T1-T6  new signals, each added alone to the kept logistic (feature builders: scripts/cbb_breakout.py bo_extra);
         the pXPM gap (Nov 26 2026: next season's projected XPM, point in time, over his best level so far) is tested the
         same way after them
  T7     gradient-boosted trees (numpy, depth 3, early stopping on an inner split of the training seasons)
  T8     logistic + monotone hinge splines on the four strongest columns
  T9-T10 Platt and isotonic recalibration fit on predictions made inside the training seasons
Only passers ship: the live build reads breakout.sweep (extra signals, model, calibration) when it is there."""
import json
import math
import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import cbb_breakout as B  # noqa: E402
import cbb_breakout_research as R  # noqa: E402
import names as N  # noqa: E402

COACH = os.path.join(R.ROOT, 'scripts', 'data', 'cbb_coaches.json')
NTEST = 11
TN = lambda i, k: f'T11 {k}' if k == 'pXPM gap' else f'T{i + 1} {k}'   # the pXPM gap joined after T1-T10 were numbered


def new_coaches(teams):
    """(Barttorvik team, season) -> 1 if the head coach is in his first season there (Sports Reference)"""
    d = json.load(open(COACH))
    tk = {N.team_key(t): t for t in teams}
    out = {}
    for y, rows in d.items():
        for c in rows:
            t = tk.get(N.team_key(c['name']))
            if t:
                out[(t, int(y))] = 1.0 if c['since'] == f'{int(y) - 1}-{y[2:]}' else 0.0
    return out


def design(P, C, fit):
    bar, keep = fit['breakout']['L'], fit['breakout']['keep']
    by_y = defaultdict(list)
    for (pid, y), o in P.items():
        by_y[y].append(o)
    dep = {}
    for y, ls in by_y.items():
        nxt = {o['pid']: P[(o['pid'], y + 1)]['team'] for o in ls if (o['pid'], y + 1) in P}
        for pid, v in B.depth_tables(ls, nxt).items():
            dep[(pid, y)] = v
    NC = new_coaches({o['team'] for o in P.values()})
    S, yv, X, EX, has_c = [], [], [], {k: [] for k in B.BO_EXTRA}, []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if y < R.Y0 or not b or a['m'] < R.ROW_M or a['gp'] < R.ROW_GP:
            continue
        hist = B.history(P, pid, y)
        s0, cur = B.level(a, hist)
        if s0 >= bar:
            continue
        c = C[(pid, y)]
        f = B.bo_feats(a, s0, cur, B.marcel(hist, y), c, 0.0)
        X.append(sum([f['base']] + [f[k] for k in keep], []))
        nc = NC.get((b['team'], y + 1))
        e = B.bo_extra(a, cur, c, dep.get((pid, y), B.NO_DEP), nc or 0.0, s0, B.marcel(hist, y))
        for k in B.BO_EXTRA:
            EX[k].append(e[k])
        has_c.append(nc is not None)
        S.append(y + 1)
        yv.append(1.0 if B.broke_out(b, bar) else 0.0)
    return (np.array(S, float), np.array(yv), np.array(X), {k: np.array(v) for k, v in EX.items()},
            np.array(has_c))


def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def by_season(S, y, p, mask=None):
    out = {}
    for s in sorted(set(S.tolist())):
        te = S == s
        if mask is not None:
            te = te & mask
        if te.sum() >= 5:
            out[s] = (float(ll(p[te], y[te]).sum()), float(te.sum()))
    return out


def oos_logit(S, y, X):
    p = np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        b0, b = L.logit(X[~te], y[~te])
        p[te] = L.sig(b0 + X[te] @ b)
    return p


# ---------- gradient-boosted trees ----------
BINS, DEPTH, LR, MINLEAF, L2, ROUNDS, PATIENCE = 32, 3, 0.1, 100, 1.0, 300, 25


def cuts_of(X):
    return [np.unique(np.quantile(X[:, j], np.linspace(0, 1, BINS + 1)[1:-1])) for j in range(X.shape[1])]


def binned(X, cuts):
    return np.column_stack([np.searchsorted(c, X[:, j], side='left') for j, c in enumerate(cuts)])


def grow(Xb, g, h):
    """one depth-limited tree on binned columns: list of nodes [feature, bin, left, right] or [-1, value]"""
    n, F = Xb.shape
    off = np.arange(F) * BINS
    nodes = []

    def build(idx, depth):
        G, H = g[idx].sum(), h[idx].sum()
        me = len(nodes)
        nodes.append([-1, float(-G / (H + L2) * LR)])
        if depth == DEPTH or len(idx) < 2 * MINLEAF:
            return me
        flat = (Xb[idx] + off).ravel()
        gh = np.bincount(flat, weights=np.repeat(g[idx], F), minlength=F * BINS).reshape(F, BINS).cumsum(1)
        hh = np.bincount(flat, weights=np.repeat(h[idx], F), minlength=F * BINS).reshape(F, BINS).cumsum(1)
        ch = np.bincount(flat, minlength=F * BINS).reshape(F, BINS).cumsum(1)
        gain = gh ** 2 / (hh + L2) + (G - gh) ** 2 / (H - hh + L2) - G ** 2 / (H + L2)
        gain[(ch < MINLEAF) | (len(idx) - ch < MINLEAF)] = -1
        f, k = np.unravel_index(np.argmax(gain), gain.shape)
        if gain[f, k] <= 1e-9:
            return me
        m = Xb[idx, f] <= k
        le = build(idx[m], depth + 1)
        ri = build(idx[~m], depth + 1)
        nodes[me] = [int(f), int(k), le, ri]
        return me
    build(np.arange(n), 0)
    return nodes


def tree_pred(nodes, Xb):
    out = np.zeros(len(Xb))

    def go(i, idx):
        nd = nodes[i]
        if nd[0] == -1:
            out[idx] = nd[1]
            return
        m = Xb[idx, nd[0]] <= nd[1]
        go(nd[2], idx[m])
        go(nd[3], idx[~m])
    go(0, np.arange(len(Xb)))
    return out


def gbt_fit(Xb, y, rounds, Xv=None, yv=None):
    """returns (f0, trees, best number of rounds on the validation rows when given)"""
    p0 = float(np.clip(y.mean(), 1e-4, 1 - 1e-4))
    f0 = math.log(p0 / (1 - p0))
    F = np.full(len(y), f0)
    Fv = np.full(len(yv), f0) if Xv is not None else None
    trees, best, bi = [], None, 0
    for r in range(rounds):
        p = L.sig(F)
        t = grow(Xb, p - y, p * (1 - p))
        trees.append(t)
        F += tree_pred(t, Xb)
        if Xv is not None:
            Fv += tree_pred(t, Xv)
            e = float(ll(L.sig(Fv), yv).mean())
            if best is None or e < best - 1e-7:
                best, bi = e, r + 1
            elif r + 1 - bi >= PATIENCE:
                break
    return f0, trees, bi


def gbt_fold(args):
    S, y, X, s = args
    te = S == s
    Xt, yt, St = X[~te], y[~te], S[~te]
    cuts = cuts_of(Xt)
    Xb = binned(Xt, cuts)
    u = sorted(set(St.tolist()))
    hold = np.isin(St, u[1::3])
    _, _, n = gbt_fit(Xb[~hold], yt[~hold], ROUNDS, Xb[hold], yt[hold])
    f0, trees, _ = gbt_fit(Xb, yt, max(n, 10))
    Xe = binned(X[te], cuts)
    return s, L.sig(f0 + sum(tree_pred(t, Xe) for t in trees)), n


def oos_gbt(S, y, X):
    p, rounds = np.zeros(len(y)), {}
    with ProcessPoolExecutor(max(1, min(8, os.cpu_count() or 1))) as ex:
        for s, ps, n in ex.map(gbt_fold, [(S, y, X, s) for s in sorted(set(S.tolist()))]):
            p[S == s] = ps
            rounds[int(s)] = n
    return p, rounds


# ---------- logistic + monotone hinge splines ----------
def spline_cols(X, y, top=4):
    """hinge terms at the terciles of the strongest columns; a column whose piecewise slopes change sign is left linear"""
    b0, b = L.logit(X, y)
    sd = X.std(0)
    order = [j for j in np.argsort(-np.abs(b * sd)) if len(np.unique(X[:, j])) > 10][:top]
    spec = [(int(j), [float(q) for q in np.quantile(X[:, j], [1 / 3, 2 / 3])]) for j in order]
    while True:
        Z = expand(X, spec)
        z0, zb = L.logit(Z, y)
        bad, i = [], X.shape[1]
        for j, ks in spec:
            sl = np.cumsum([zb[j]] + [zb[i + t] for t in range(len(ks))])
            i += len(ks)
            if sl.min() < 0 < sl.max():
                bad.append(j)
        if not bad:
            return spec, z0, zb
        spec = [(j, ks) for j, ks in spec if j not in bad]


def expand(X, spec):
    return np.column_stack([X] + [np.maximum(0, X[:, j] - k) for j, ks in spec for k in ks]) if spec else X


def oos_spline(S, y, X):
    p = np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        spec, z0, zb = spline_cols(X[~te], y[~te])
        p[te] = L.sig(z0 + expand(X[te], spec) @ zb)
    return p


# ---------- calibration ----------
def pav(x, y):
    """isotonic fit: block means of y in x order -> (knots x, values)"""
    o = np.argsort(x)
    xs, ys = x[o], y[o]
    v, w, lo, hi = [], [], [], []
    for xi, yi in zip(xs, ys):
        v.append(yi); w.append(1.0); lo.append(xi); hi.append(xi)
        while len(v) > 1 and v[-2] >= v[-1]:
            a = (v[-2] * w[-2] + v[-1] * w[-1]) / (w[-2] + w[-1])
            w[-2] += w[-1]; v[-2] = a; hi[-2] = hi[-1]
            v.pop(); w.pop(); lo.pop(); hi.pop()
    return [(a + b) / 2 for a, b in zip(lo, hi)], v


def lg(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def oos_calib(S, y, X):
    """Platt and isotonic maps fit on leave-one-season-out predictions made inside each training set"""
    pl, iso = np.zeros(len(y)), np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        Xt, yt, St = X[~te], y[~te], S[~te]
        pin = oos_logit(St, yt, Xt)
        b0, b = L.logit(Xt, yt)
        pt = L.sig(b0 + X[te] @ b)
        a0, a1 = L.logit(lg(pin)[:, None], yt, lam=1e-6)
        pl[te] = L.sig(a0 + a1[0] * lg(pt))
        kx, kv = pav(pin, yt)
        iso[te] = np.interp(pt, kx, kv)
    return pl, iso


def bins(p, y):
    out = []
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .2), (.2, .35), (.35, 1)):
        m = (p >= lo) & (p < hi)
        if m.sum():
            out.append([lo, hi, int(m.sum()), round(float(p[m].mean()), 3), round(float(y[m].mean()), 3)])
    return out


def passed(r):
    """staging rule while the family is incomplete: the bar at the Bonferroni level for ten tests"""
    return r['t'] >= 2 and r['won'] * 2 > r['seasons'] and 0.5 * math.erfc(r['t'] / math.sqrt(2)) <= 0.05 / NTEST


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else R.SRC
    fit = json.load(open(R.OUT))
    P, _ = R.load(src)
    C = R.context(P)
    S, y, X, EX, has_c = design(P, C, fit)
    print('rows', len(y), 'rate', round(float(y.mean()), 4), 'cols', X.shape[1], flush=True)
    p_redo = oos_logit(S, y, X)
    e_redo = by_season(S, y, p_redo)
    T = {}
    for i, k in enumerate(B.BO_EXTRA):
        pk = oos_logit(S, y, np.column_stack([X, EX[k]]))
        if k == 'coaching change':
            T[TN(i, k)] = L.compare(by_season(S, y, p_redo, has_c), by_season(S, y, pk, has_c))
            T[TN(i, k)]['coach_rows'] = int(has_c.sum())
        else:
            T[TN(i, k)] = L.compare(e_redo, by_season(S, y, pk))
        print(' ', TN(i, k).split()[0], k, T[TN(i, k)], flush=True)
    extra = [k for i, k in enumerate(B.BO_EXTRA) if passed(T[TN(i, k)])]
    X2 = np.column_stack([X] + [EX[k] for k in extra])
    p_log = oos_logit(S, y, X2) if extra else p_redo
    e_log = by_season(S, y, p_log)
    print(' signals kept', extra, L.compare(e_redo, e_log), flush=True)
    p_gbt, rounds = oos_gbt(S, y, X2)
    T['T7 gradient-boosted trees'] = L.compare(e_log, by_season(S, y, p_gbt))
    T['T7 gradient-boosted trees']['rounds'] = rounds
    print('  T7', T['T7 gradient-boosted trees'], flush=True)
    p_spl = oos_spline(S, y, X2)
    T['T8 logistic + monotone splines'] = L.compare(e_log, by_season(S, y, p_spl))
    print('  T8', T['T8 logistic + monotone splines'], flush=True)
    form = 'logit'
    if passed(T['T8 logistic + monotone splines']):
        form = 'spline'
    if passed(T['T7 gradient-boosted trees']) and T['T7 gradient-boosted trees']['t'] > T['T8 logistic + monotone splines']['t']:
        form = 'gbt'
    spec = []
    if form == 'spline':
        # calibration is tested on the shipped columns: the spline columns of the full fit
        spec, _, _ = spline_cols(X2, y)
    X3 = expand(X2, spec)
    p_ship = {'logit': p_log, 'spline': p_spl, 'gbt': p_gbt}[form]
    e_ship = by_season(S, y, p_ship)
    if form == 'gbt':
        T['T9 Platt'] = T['T10 isotonic'] = None
    else:
        pl, iso = oos_calib(S, y, X3)
        base_c = by_season(S, y, oos_logit(S, y, X3))
        T['T9 Platt'] = L.compare(base_c, by_season(S, y, pl))
        T['T10 isotonic'] = L.compare(base_c, by_season(S, y, iso))
        print('  T9', T['T9 Platt'], '\n  T10', T['T10 isotonic'], flush=True)
    tests = {k: v for k, v in T.items() if v}
    L.holm(tests)
    cal = 'platt' if tests.get('T9 Platt', {}).get('pass') else None
    if tests.get('T10 isotonic', {}).get('pass') and (not cal or tests['T10 isotonic']['t'] > tests['T9 Platt']['t']):
        cal = 'isotonic'
    p_fin = p_ship if not cal else (pl if cal == 'platt' else iso)
    final = L.compare(e_redo, by_season(S, y, p_fin))
    top = p_fin >= np.quantile(p_fin, 0.9)
    out = {'prereg': '/mnt/project-files/next-up/prereg-cbb.md', 'n': len(y), 'tests': tests, 'extra': extra,
           'form': form, 'calibration': cal, 'final_vs_redo': final, 'calib_heldout': bins(p_fin, y),
           'calib_heldout_redo': bins(p_redo, y), 'top_decile_rate': round(float(y[top].mean()), 3),
           'not_run': ['within-season trend: no half-season splits in the history table',
                       'play-type / tracking rates: no free D-I source for 2010-2025']}
    b0, b = L.logit(X3, y)
    out['fit'] = {'b0': round(b0, 5), 'b': [round(float(v), 6) for v in b],
                  'mu': [round(float(v), 5) for v in X3.mean(axis=0)], 'spline': spec}
    if form == 'gbt':
        cuts = cuts_of(X2)
        n = int(np.median(list(rounds.values())))
        f0, trees, _ = gbt_fit(binned(X2, cuts), y, n)
        # bins -> raw thresholds so the live build needs no binning: x <= cut goes left
        ser = [[[nd[0], float(cuts[nd[0]][nd[1]]) if nd[1] < len(cuts[nd[0]]) else 1e30, nd[2], nd[3]] if nd[0] >= 0
                else [-1, round(nd[1], 6)] for nd in t] for t in trees]
        out['gbt'] = {'f0': f0, 'trees': ser}
    if cal == 'platt':
        a0, a1 = L.logit(lg(oos_logit(S, y, X3))[:, None], y, lam=1e-6)
        out['platt'] = [round(float(a0), 5), round(float(a1[0]), 5)]
    if cal == 'isotonic':
        kx, kv = pav(oos_logit(S, y, X3), y)
        out['isotonic'] = [[round(float(a), 5) for a in kx], [round(float(a), 5) for a in kv]]
    fit['breakout']['sweep'] = out
    json.dump(fit, open(R.OUT, 'w'), indent=1)
    for k, v in tests.items():
        print(k, 't', v['t'], f"{v['won']}/{v['seasons']}", 'gain', v['gain'], 'PASS' if v['pass'] else 'fail')
    print('form', form, 'calibration', cal, 'final vs redo', final)
    print('held-out calibration', out['calib_heldout'], 'top decile', out['top_decile_rate'])


if __name__ == '__main__':
    main()
