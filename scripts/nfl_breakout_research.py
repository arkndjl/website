#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL Potential Breakout research: workload scaling and breakout signals, leave-one-season-out (scripts/breakout_lib.py).

    python3 scripts/nfl_breakout_research.py      # -> data/nfl_breakout_fit.json (numpy; nflverse weekly files 2010 on)

Workload and efficiency: scripts/nfl_breakout.py (WR/TE target share and yards a target; RB share of the team's
carries + targets and scrimmage yards an opportunity). QB, OL and defense are not scaled.

A. Workload scaling, one fit a position. Rows: season pairs (both seasons with a real sample) and half pairs (a
   season's weeks 1-9 against weeks 10 on: a teammate's injury or a trade moves the share with no off-season between),
   weight = the smaller opportunity count, block = the season of the outcome. Next efficiency on this one's (shrunk by
   sample) + age + share + last season's, then + the share change (dU), then + dU x context blocks. Held-out error on
   all rows and on the rows whose share rose 3+ points (the case the tab projects).
B. Breakout odds. Rows: WR/TE/RB with 4+ games and 15+ opportunities. No season so far at the bar L (RB/WR 12, TE 9
   PPR points a game, shrunk to a depth player's by 4 games). Breakout = next season 8+ games at or over L.
   Baseline logistic: shrunk PPR/G, ln opportunities, position, share. Candidates one at a time, then the passers."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nfl_breakout as B  # noqa: E402

DATA0 = 2004                                        # first season loaded (career history for the early rows)
Y0, Y1 = 2010, 2025                                 # seasons with a known next season: Y0..Y1-1
ROSE = 3.0
LAMS = (1e-4, 1e-3, 1e-2, 3e-2, 0.1, 0.3)
ISO_LAM = 1e-2


def pick_lam(X, y, w, S):
    """ridge strength from an inner split of the training seasons (every third season held out)"""
    u = sorted(set(S.tolist()))
    hold = np.isin(S, u[1::3])
    best, bl = None, LAMS[0]
    for lam in LAMS:
        b0, b = L.wls(X[~hold], y[~hold], w[~hold], lam)
        e = float((w[hold] * (y[hold] - b0 - X[hold] @ b) ** 2).sum())
        if best is None or e < best:
            best, bl = e, lam
    return bl


def pairs(P, pos):
    R = []
    m = B.MINN[pos]
    for (pid, y), a in P.items():
        if a['pos'] != pos or y < Y0:
            continue
        hist = B.history(P, pid, y)
        b = P.get((pid, y + 1))
        if b and b['pos'] == pos and a['n'] >= m and b['n'] >= m:
            R.append((a, b, hist, 0.0, y + 1))
        g1 = [g for g in a['games'] if g['wk'] <= 9]
        g2 = [g for g in a['games'] if g['wk'] > 9]
        if len(g1) >= 3 and len(g2) >= 3:
            h1, h2 = B.part(a, g1), B.part(a, g2)
            if h1['n'] >= 0.6 * m and h2['n'] >= 0.6 * m:
                R.append((h1, h2, hist, 1.0, y))
    return R


def scaling(P, pos):
    R = pairs(P, pos)
    S = np.array([r[4] for r in R], float)
    w = np.array([min(a['n'], b['n']) for a, b, *_ in R], float)
    du = np.array([b['u'] - a['u'] for a, b, *_ in R])
    half = np.array([r[3] for r in R])
    y = np.array([b['x'] for a, b, *_ in R])
    F = np.array([B.features(a, h, d, hf) for (a, b, h, hf, _), d in zip(R, du)])
    cols = B.columns()
    ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
    sets = {'base': B.BASE, 'dU': B.BASE + ['dU']}
    for blk, tr in B.BLOCKS.items():
        sets[blk] = B.BASE + ['dU'] + sum([['dU*' + t, t] for t in tr], [])
    sets['full'] = cols
    up = du >= ROSE
    masks = {'all': np.ones(len(y), bool), 'rose': up, 'rose, seasons': up & (half == 0), 'rose, halves': up & (half == 1)}

    def run(cs):
        X = F[:, ix(cs)]

        def fp(trn, te):
            b0, b = L.wls(X[trn], y[trn], w[trn], pick_lam(X[trn], y[trn], w[trn], S[trn]))
            return b0 + X[te] @ b
        pred = {}
        for s in sorted(set(S.tolist())):
            te = S == s
            pred[s] = (te, fp(~te, te))
        out = {}
        for k, m in masks.items():
            out[k] = {s: (float((w[te][m[te]] * (y[te][m[te]] - p[m[te]]) ** 2).sum()), float(w[te][m[te]].sum()) or 1e-9)
                      for s, (te, p) in pred.items()}
        return out
    res = {nm: run(cs) for nm, cs in sets.items()}
    tests = {'dU vs base (all)': L.compare(res['base']['all'], res['dU']['all']),
             'dU vs base (rose)': L.compare(res['base']['rose'], res['dU']['rose']),
             'full vs base (all)': L.compare(res['base']['all'], res['full']['all']),
             'full vs base (rose)': L.compare(res['base']['rose'], res['full']['rose']),
             'full vs dU (rose)': L.compare(res['dU']['rose'], res['full']['rose'])}
    for t in tests.values():
        t['pass'] = bool(t['t'] >= 2 and t['won'] * 2 > t['seasons'])
    blocks = {k: L.compare(res['dU']['rose'], res[k]['rose']) for k in B.BLOCKS}
    L.holm(blocks)
    for k in B.BLOCKS:
        blocks[k]['all rows'] = {q: L.compare(res['dU']['all'], res[k]['all'])[q] for q in ('gain', 't', 'won')}
    keep = [k for k in B.BLOCKS if blocks[k]['pass']]
    fin = B.BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in B.BLOCKS[k]], []) for k in keep], [])
    if keep:
        rk = run(fin)
        for k in masks:
            tests[f'kept vs base ({k})'] = L.compare(res['base'][k], rk[k])
    X = F[:, ix(fin)]
    lam = pick_lam(X, y, w, S)
    b0, b = L.wls(X, y, w, lam)
    sp = du[half == 0]
    ib = ix(B.BASE)
    lb = pick_lam(F[:, ib], y, w, S)
    tb0, tb = L.wls(F[:, ib], y, w, lb)
    out = {'tier_fit': {'b0': round(float(tb0), 5), 'cols': B.BASE, 'b': [round(float(v), 7) for v in tb]},
           'causal': causal(P, pos), 'n': len(R), 'n_season': int((half == 0).sum()), 'n_half': int((half == 1).sum()), 'n_rose': int(up.sum()),
           'du99': round(float(np.percentile(sp, 99)), 1), 'tests': tests, 'blocks': blocks, 'keep': keep, 'lam': lam,
           'slope': {'dU': round(float(b[fin.index('dU')]), 4)},
           'fit': {'b0': round(float(b0), 5), 'cols': fin, 'b': [round(float(v), 7) for v in b]}}
    print(pos, 'rows', len(R), 'rose', int(up.sum()), 'du99', out['du99'], flush=True)
    for k, v in tests.items():
        print('  ', k, v, flush=True)
    for k, v in blocks.items():
        print('   block', k, v, flush=True)
    return out


def causal(P, pos):
    """The share's own effect on efficiency: two-stage least squares with the work teammates left behind as the
    instrument for the share change. Halves: same-group teammates' weeks 1-9 work a game that is gone in weeks 10 on;
    seasons: same-group teammates not on the team next season. Both sides are residualized on the rate model's
    inputs. SE: season-block jackknife."""
    team = {}
    for (pid, y), o in P.items():
        team.setdefault((o['tm0'], y), []).append(o)
    rb = pos == 'RB'
    op = (lambda g: g['tg'] + g['ca']) if rb else (lambda g: g['tg'])
    same = lambda q: (q['pos'] == 'RB') == rb  # noqa: E731
    R = []
    for (pid, y), a in P.items():
        if a['pos'] != pos or y < Y0 or len({g['tm'] for g in a['games']}) > 1:
            continue
        tm, m = a['tm0'], B.MINN[pos]
        mates = [q for q in team[(tm, y)] if q is not a and same(q)]
        g1 = [g for g in a['games'] if g['wk'] <= 9]
        g2 = [g for g in a['games'] if g['wk'] > 9]
        if len(g1) >= 3 and len(g2) >= 3:
            h1, h2 = B.part(a, g1), B.part(a, g2)
            if h1['n'] >= 0.6 * m and h2['n'] >= 0.6 * m:
                wks = max(g['wk'] for q in team[(tm, y)] for g in q['games']) - 10      # team games after week 9
                z = sum(max(0.0, sum(op(g) for g in q['games'] if g['wk'] <= 9 and g['tm'] == tm) / 9.0
                            - sum(op(g) for g in q['games'] if g['wk'] > 9 and g['tm'] == tm) / max(1, wks))
                        for q in mates) / h1['vol']
                R.append((y, h1, h2, 100 * z, 1.0))
        b = P.get((pid, y + 1))
        if b and b['pos'] == pos and b['tm0'] == tm and a['n'] >= m and b['n'] >= m:
            gone = sum(q['n'] / max(q['g'], 8) for q in mates
                       if (P.get((q['pid'], y + 1)) or {}).get('tm0') != tm)
            R.append((y + 1, a, b, 100 * gone / a['vol'], 0.0))
    S = np.array([r[0] for r in R], float)
    w = np.array([min(a['n'], b['n']) for _, a, b, *_ in R], float)
    X0 = np.array([[a['x'], a['x'] * a['n'] / (a['n'] + B.KREL[pos]), a['n'] / (a['n'] + B.KREL[pos]), a['u'], a['age'],
                    hf, hf * a['x']] for _, a, b, z, hf in R])

    def resid(v):
        b0, b = L.wls(X0, v, w, 1e-4)
        return v - b0 - X0 @ b
    ry = resid(np.array([b['x'] for _, a, b, *_ in R]))
    rd = resid(np.array([b['u'] - a['u'] for _, a, b, *_ in R]))
    rz = resid(np.array([r[3] for r in R]))
    half = np.array([r[4] for r in R])

    def est(m):
        iv = (w[m] * rz[m] * ry[m]).sum() / (w[m] * rz[m] * rd[m]).sum()
        jk = np.array([(w[k] * rz[k] * ry[k]).sum() / (w[k] * rz[k] * rd[k]).sum()
                       for k in (m & (S != s) for s in sorted(set(S[m].tolist())))])
        se = float(np.sqrt((len(jk) - 1) / len(jk) * ((jk - jk.mean()) ** 2).sum()))
        return {'n': int(m.sum()), 'ols': round(float((w[m] * rd[m] * ry[m]).sum() / (w[m] * rd[m] ** 2).sum()), 4),
                'first_stage': round(float((w[m] * rz[m] * rd[m]).sum() / (w[m] * rz[m] ** 2).sum()), 3),
                'iv': round(float(iv), 4), 'se': round(se, 4), 't': round(float(iv / se), 2)}
    out = est(np.ones(len(R), bool))
    out['halves'], out['seasons'] = est(half == 1), est(half == 0)
    print(pos, 'causal', out, flush=True)
    return out


def xtd_fit(P):
    out = {}
    for pos in B.POS:
        R = [o for (pid, y), o in P.items() if o['pos'] == pos and Y0 <= y <= Y1]
        X = np.array([[o['tg'], o['wy'], o['ca'], o['ry']] for o in R])
        t = np.array([o['wtd'] + o['rtd'] for o in R])
        out[pos] = [round(float(v), 6) for v in np.linalg.lstsq(X, t, rcond=None)[0]]
    return out


def breakout(P, fit):
    R = []
    rooms = {y: B.room(P, y) for y in range(Y0, Y1)}
    for (pid, y), a in P.items():
        if not (Y0 <= y < Y1) or a['g'] < B.BO_MIN_G or a['n'] < B.BO_MIN_N or not B.eligible(P, a):
            continue
        b = P.get((pid, y + 1))
        hit = float(B.broke_out(a, b))
        old, vac = rooms[y]
        R.append((a, hit, B.bo_feats(fit, a, B.history(P, pid, y), old[pid], vac[pid])))
    S = np.array([a['y'] + 1 for a, *_ in R], float)
    y = np.array([h for _, h, _ in R])
    base = np.array([f['base'] for *_, f in R])
    cands = {k: np.array([f[k] for *_, f in R]) for k in B.BO_CANDS}
    pos = np.array([a['pos'] for a, *_ in R])

    def run(X):
        def fp(trn, te):
            b0, b = L.logit(X[trn], y[trn])
            return L.sig(b0 + X[te] @ b)

        def err(p, te):
            p = np.clip(p, 1e-6, 1 - 1e-6)
            return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))
        return L.loso(S, fp, err)
    rb = run(base)
    res = {k: L.compare(rb, run(np.column_stack([base, X]))) for k, X in cands.items()}
    L.holm(res)
    keep = [k for k in cands if res[k]['pass'] and k not in B.LIVE_OFF]
    X = np.column_stack([base] + [cands[k] for k in keep])
    final = L.compare(rb, run(X))
    # held-out predictions for calibration
    ph = np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        b0, b = L.logit(X[~te], y[~te])
        ph[te] = L.sig(b0 + X[te] @ b)
    cal = []
    for lo, hi in ((0, .03), (.03, .07), (.07, .15), (.15, .3), (.3, 1)):
        m = (ph >= lo) & (ph < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(ph[m].mean()), 3), round(float(y[m].mean()), 3)])
    b0, b = L.logit(X, y)
    print('breakout rate', round(float(y.mean()), 4), 'n', len(y),
          {p: round(float(y[pos == p].mean()), 3) for p in B.POS}, flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' final', keep, final, flush=True)
    print(' calib (held out)', cal, flush=True)
    return {'L': B.LINE, 'L_pct': '79th (RB, WR) and 81st (TE) percentile',
            'L_basis': f'PPR points a game shrunk to a depth player (RB/WR 4, TE 2.5) by {B.K_SHR:g} games; percentile of '
                       f'2010-25 seasons with 8+ games and 60+ (RB) / 40+ (WR) / 25+ (TE) opportunities',
            'definition': f'next season {B.G_NEXT}+ games and shrunk PPR points a game at or over L, for the first time',
            'rows': f'WR/TE/RB, {B.BO_MIN_G}+ games, {B.BO_MIN_N}+ opportunities, no season so far (this one included, any '
                    f'role) at or over L shrunk; career = seasons since {DATA0}',
            'seasons': f'{Y0 + 1}-{Y1}',
            'n': len(y), 'rate': round(float(y.mean()), 4),
            'rate_pos': {p: round(float(y[pos == p].mean()), 4) for p in B.POS}, 'tests': res, 'keep': keep,
            'research_only': [k for k in B.LIVE_OFF if res[k]['pass']], 'final': final, 'calib_held_out': cal,
            'fit': {'b0': round(float(b0), 5), 'b': [round(float(v), 6) for v in b],
                    'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


# ---------- C. improvement sweep (pre-registered: project files next-up/prereg-nfl.md) ----------
def pav(x, y, increasing=True):
    """isotonic fit of y on x (pool adjacent violators) -> (knots x, fitted values) for np.interp"""
    o = np.argsort(x, kind='stable')
    xs, ys = x[o], (y[o] if increasing else -y[o])
    v, wt, lo = [], [], []
    for i in range(len(xs)):
        v.append(float(ys[i])); wt.append(1.0); lo.append(i)
        while len(v) > 1 and v[-2] > v[-1]:
            w2 = wt[-2] + wt[-1]
            v[-2] = (v[-2] * wt[-2] + v[-1] * wt[-1]) / w2
            wt[-2] = w2
            v.pop(); wt.pop(); lo.pop()
    kx, kv = [], []
    for j, i in enumerate(lo):
        hi = (lo[j + 1] - 1) if j + 1 < len(lo) else len(xs) - 1
        kx += [xs[i], xs[hi]]
        kv += [v[j], v[j]]
    kv = np.array(kv) if increasing else -np.array(kv)
    return np.array(kx, float), kv


def gbt_fit(X, y, rounds, depth=2, lr=0.05, leaf=40, bins=24, Xv=None, yv=None):
    """gradient-boosted depth-2 trees on log loss (Newton leaves). With a validation set returns the best round count."""
    n, m = X.shape
    edges = [np.unique(np.quantile(X[:, j], np.linspace(0, 1, bins + 1)[1:-1])) for j in range(m)]
    B_ = np.column_stack([np.searchsorted(edges[j], X[:, j], side='right') for j in range(m)])
    f0 = float(np.log(y.mean() / (1 - y.mean())))
    F = np.full(n, f0)
    Fv = np.full(len(Xv), f0) if Xv is not None else None
    trees, best, bi = [], 1e9, 0

    def split(idx, g, h):
        G, H = g[idx].sum(), h[idx].sum()
        top = (0.0, None)
        for j in range(m):
            nb = len(edges[j]) + 1
            if nb < 2:
                continue
            b = B_[idx, j]
            gs = np.cumsum(np.bincount(b, g[idx], nb))[:-1]
            hs = np.cumsum(np.bincount(b, h[idx], nb))[:-1]
            cs = np.cumsum(np.bincount(b, minlength=nb))[:-1]
            ok = (cs >= leaf) & (len(idx) - cs >= leaf)
            if not ok.any():
                continue
            gain = np.where(ok, gs ** 2 / (hs + 1) + (G - gs) ** 2 / (H - hs + 1) - G ** 2 / (H + 1), -1)
            k = int(gain.argmax())
            if gain[k] > top[0]:
                top = (float(gain[k]), (j, float(edges[j][k])))
        return top[1]

    def grow(idx, g, h, d):
        sp = split(idx, g, h) if d > 0 and len(idx) >= 2 * leaf else None
        if sp is None:
            return [round(float(lr * g[idx].sum() / (h[idx].sum() + 1)), 6)]
        j, thr = sp
        L_ = idx[X[idx, j] < thr]
        R_ = idx[X[idx, j] >= thr]
        return [j, thr, grow(L_, g, h, d - 1), grow(R_, g, h, d - 1)]
    allidx = np.arange(n)
    for r in range(rounds):
        p = L.sig(F)
        t = grow(allidx, y - p, p * (1 - p), depth)
        trees.append(t)
        F += tree_eval(t, X)
        if Xv is not None:
            Fv += tree_eval(t, Xv)
            pv = np.clip(L.sig(Fv), 1e-6, 1 - 1e-6)
            e = float(-(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)).mean())
            if e < best - 1e-6:
                best, bi = e, r + 1
            elif r + 1 - bi >= 60:
                break
    return (f0, trees) if Xv is None else bi


def tree_eval(t, X):
    if len(t) == 1:
        return np.full(len(X), t[0])
    m = X[:, t[0]] < t[1]
    out = np.empty(len(X))
    out[m] = tree_eval(t[2], X[m])
    out[~m] = tree_eval(t[3], X[~m])
    return out


def sweep(P, fit, info):
    bo = fit['breakout']
    Kc = B.load_contracts(info)
    C = B.team_context()
    R = []
    ctx = {y: (B.room(P, y), B.depth(P, y, Kc), B.offense(P, y)) for y in range(Y0, Y1)}
    for (pid, y), a in P.items():
        if not (Y0 <= y < Y1) or a['g'] < B.BO_MIN_G or a['n'] < B.BO_MIN_N or not B.eligible(P, a):
            continue
        (old, vac), D, off = ctx[y]
        b = P.get((pid, y + 1))
        f = B.bo_feats(fit, a, B.history(P, pid, y), old[pid], vac[pid])
        R.append((a, float(B.broke_out(a, b)), f, B.sweep_feats(a, D[pid], C, off), B.op_row(a, D[pid]), b['u'] if b else 0.0))
    S = np.array([r[0]['y'] + 1 for r in R], float)
    y = np.array([r[1] for r in R])
    X0 = np.array([r[2]['base'] + sum([r[2][k] for k in bo['keep']], []) for r in R])
    OP = np.array([r[4] for r in R])
    u1 = np.array([r[5] for r in R])
    ref = np.array([B.UREF[r[0]['pos']] for r in R])

    def ll(p, te):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))

    def lg(X):
        def fp(trn, te):
            b0, b = L.logit(X[trn], y[trn])
            return L.sig(b0 + X[te] @ b)
        return fp

    def op_feats(trn):
        b0, b = L.wls(OP[trn], u1[trn], np.ones(int(trn.sum())), 1e-2)
        ph = (b0 + OP @ b) / ref
        return np.column_stack([ph, ph - OP[:, 0]]), (b0, b)

    def fp_op(trn, te):
        Z = np.column_stack([X0, op_feats(trn)[0]])
        b0, b = L.logit(Z[trn], y[trn])
        return L.sig(b0 + Z[te] @ b)
    r0 = L.loso(S, lg(X0), ll)
    A = {k: np.array([r[3][k] for r in R]) for k in B.SWEEP if k != 'opportunity model'}
    res = {}
    for k in B.SWEEP:
        res[k] = L.compare(r0, L.loso(S, fp_op, ll) if k == 'opportunity model' else L.loso(S, lg(np.column_stack([X0, A[k]])), ll))
        print(' A', k, res[k], flush=True)

    # provisional passers (per-test bar) define the columns the model-form tests run on; Holm over all 18 comes last
    def cols_for(keep):
        return np.column_stack([X0] + [A[k] for k in keep if k != 'opportunity model'])
    prov = [k for k in B.SWEEP if res[k]['t'] >= 2 and res[k]['won'] * 2 > res[k]['seasons'] and k not in B.SWEEP_RO
            and k != 'opportunity model']
    XA = cols_for(prov)
    rA = L.loso(S, lg(XA), ll)

    def fp_gbt(trn, te):
        u = sorted(set(S[trn].tolist()))
        hold = trn & np.isin(S, u[1::3])
        n = gbt_fit(XA[trn & ~hold], y[trn & ~hold], 400, Xv=XA[hold], yv=y[hold]) or 1
        f0, trees = gbt_fit(XA[trn], y[trn], n)
        return L.sig(f0 + sum(tree_eval(t, XA[te]) for t in trees))
    res['gradient-boosted trees'] = L.compare(rA, L.loso(S, fp_gbt, ll))
    print(' B gbt', res['gradient-boosted trees'], flush=True)
    mono = [(0, True), (X0.shape[1] - 7, False), (X0.shape[1] - 1, False)]       # s0, age, ln pick in K0's columns

    def iso_cols(trn):
        out = []
        for j, inc in mono:
            kx, kv = pav(X0[trn, j], y[trn], inc)
            out.append(np.interp(X0[:, j], kx, kv))
        return np.column_stack(out)

    def fp_iso(trn, te):
        Z = np.column_stack([XA, iso_cols(trn)])
        # the default ridge (1e-3) diverges here (the in-fold step functions nearly separate the training rows; the
        # first run scored 1.46): 1e-2 is the weakest of the grid that converges in every fold
        b0, b = L.logit(Z[trn], y[trn], lam=ISO_LAM)
        return L.sig(b0 + Z[te] @ b)
    res['logistic + monotone transforms'] = L.compare(rA, L.loso(S, fp_iso, ll))
    print(' B iso', res['logistic + monotone transforms'], flush=True)

    # calibration: inner leave-one-season-out predictions of each training fold
    def inner(trn):
        ph = np.zeros(len(y))
        for s in sorted(set(S[trn].tolist())):
            te = trn & (S == s)
            tr = trn & (S != s)
            b0, b = L.logit(XA[tr], y[tr])
            ph[te] = L.sig(b0 + XA[te] @ b)
        return ph

    def lo(p):
        p = np.clip(p, 1e-5, 1 - 1e-5)
        return np.log(p / (1 - p))

    def fp_platt(trn, te):
        ph = inner(trn)
        a0, a1 = L.logit(lo(ph[trn])[:, None], y[trn], lam=1e-6)
        return L.sig(a0 + a1[0] * lo(lg(XA)(trn, te)))

    def fp_isocal(trn, te):
        ph = inner(trn)
        kx, kv = pav(ph[trn], y[trn])
        return np.clip(np.interp(lg(XA)(trn, te), kx, kv), 0.002, 0.9)
    res['Platt calibration'] = L.compare(rA, L.loso(S, fp_platt, ll))
    res['isotonic calibration'] = L.compare(rA, L.loso(S, fp_isocal, ll))
    print(' C platt', res['Platt calibration'], '\n C iso', res['isotonic calibration'], flush=True)
    L.holm(res)
    keep = [k for k in B.SWEEP if res[k]['pass'] and k not in B.SWEEP_RO]
    print(' sweep passers after Holm (18 tests):', [k for k in res if res[k]['pass']], flush=True)
    out = {'prereg': 'project files next-up/prereg-nfl.md', 'tests': res, 'keep': keep,
           'provisional_columns': prov, 'k0': L.compare(r0, r0)['base']}
    return out, R, S, y, X0, A, op_feats


def main():
    info, pfr = B.load_players()
    P = B.load(DATA0, Y1, info, pfr)
    fit = {'source': f'nflverse stats_player_week {DATA0}-{Y1} + snap_counts 2013-{Y1}, REG; rows {Y0} on',
           'workload': 'WR/TE: targets / team targets in games played; RB: (carries + targets) / team (carries + targets)',
           'efficiency': 'WR/TE receiving yards a target; RB scrimmage yards a carry or target',
           'not_scaled': 'QB, OL, defense', 'xtd': xtd_fit(P)}
    fit['scaling'] = {pos: scaling(P, pos) for pos in B.POS}
    # the share's own effect ships where the pooled estimate clears t 2 and Holm across the three positions; the
    # slope used is the halves' (the strong instrument: first stage 3-10x the seasons'), the smaller of the two
    order = sorted(B.POS, key=lambda p: -abs(fit['scaling'][p]['causal']['t']))
    alive = True
    for i, p in enumerate(order):
        c = fit['scaling'][p]['causal']
        c['p'] = round(math.erfc(abs(c['t']) / math.sqrt(2)) / 2, 4)
        alive = alive and abs(c['t']) >= 2 and c['p'] <= 0.05 / (len(order) - i)
        c['pass'] = bool(alive)
        c['use'] = c['halves']['iv'] if alive else 0.0
        print(p, 'causal slope used', c['use'], 'pooled t', c['t'], 'p', c['p'])
    fit['breakout'] = breakout(P, fit)
    fit['sweep'] = sweep(P, fit, info)[0]
    json.dump(fit, open(B.FIT, 'w'), indent=1)
    print('wrote', B.FIT)


if __name__ == '__main__':
    main()
