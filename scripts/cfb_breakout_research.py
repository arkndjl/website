# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College football Potential Breakout research: workload scaling and breakout signals, leave-one-season-out
(scripts/breakout_lib.py).

    python3 scripts/cfb_breakout_research.py [--offline]   # -> data/cfb_breakout_fit.json

History: PFN impact rankings, FBS, 2019 on, at QB, RB, WR, TE, EDGE, DT and LB (OL, CB and S start in 2024: two pairs,
not enough seasons to hold out). Past seasons list PFN's qualifiers only, so the pairs are regulars and near-regulars;
snap counts exist for the front seven only, so workload is opportunities a game (scripts/cfb_breakout.py).

A. Workload scaling, offense and defense fit apart. Pairs of seasons, weight = the smaller reliability. Next-season
   efficiency z on this season's (shrunk by volume) + class + workload, then + the change in ln workload (dU), then
   + dU x context blocks. Held-out error on all pairs and on the pairs whose workload rose 25%+ (the case the tab
   projects).
B. Breakout odds. Quality bar L = the L_PCT quantile of regulars' score z shrunk to replacement by workload. Rows:
   base seasons 2019-2025 of players with no season so far at or over L (seasons on file, 2019 on). Breakout = next
   season a regular (T_REG a game, half the season's games) at or over L, shrunk the same way: the first time.
   Baseline logistic: shrunk z, ln workload games, position. Candidates one at a time, then the passers together."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import cfb_breakout as B  # noqa: E402

OUT = B.FIT
LAMS = (1e-3, 1e-2, 3e-2, 0.1, 0.3)
RISE = math.log(1.25)
TIER_PCT = (50, 80, 95)


def pick_lam(X, y, w, S):
    """ridge strength from an inner split of the training seasons (every other season held out)"""
    u = sorted(set(S.tolist()))
    hold = np.isin(S, u[1::2])
    best, bl = None, LAMS[0]
    for lam in LAMS:
        b0, b = L.wls(X[~hold], y[~hold], w[~hold], lam)
        e = float((w[hold] * (y[hold] - b0 - X[hold] @ b) ** 2).sum())
        if best is None or e < best:
            best, bl = e, lam
    return bl


def scaling(P, side):
    pos = B.OFF if side == 'off' else tuple(g for g in B.POS if g not in B.OFF)
    R = []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if not b or a['g'] not in pos or b['g'] != a['g']:
            continue
        R.append((pid, y, a, b))
    S = np.array([y + 1 for _, y, _, _ in R], float)
    w = np.array([min(a['rel'], b['rel']) for _, _, a, b in R])
    du = np.array([math.log(b['u'] / a['u']) for _, _, a, b in R])
    y = np.array([b['ez'] for _, _, a, b in R])
    cols = B.columns(side)
    F = np.array([B.scale_feats(a, B.history(P, pid, yy), d, side) for (pid, yy, a, b), d in zip(R, du)])
    ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
    base_c = B.BASE + B.DUMS[side]

    def blk_cols(k):
        out = []
        for t in B.block_traits(k, side):
            out.append('dU*' + t)
            if t not in base_c and t not in out:
                out.append(t)
        return out
    sets = {'base': base_c, 'dU': base_c + ['dU']}
    for k in B.BLOCKS:
        sets[k] = base_c + ['dU'] + blk_cols(k)
    sets['full'] = cols
    up = du >= RISE
    masks = {'all': np.ones(len(y), bool), 'up': up}

    def run(cs):
        X = F[:, ix(cs)]

        def fp(trn, te):
            lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
            b0, b = L.wls(X[trn], y[trn], w[trn], lam)
            return b0 + X[te] @ b
        out = {}
        for key, m in masks.items():
            def e(p, te, m=m):
                mm = m[te]
                return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
            out[key] = L.loso(S, fp, e)
        return out
    res = {nm: run(cs) for nm, cs in sets.items()}
    cmp = {'dU vs base (all)': L.compare(res['base']['all'], res['dU']['all']),
           'dU vs base (rose 25%+)': L.compare(res['base']['up'], res['dU']['up']),
           'full vs base (rose 25%+)': L.compare(res['base']['up'], res['full']['up']),
           'full vs dU (rose 25%+)': L.compare(res['dU']['up'], res['full']['up'])}
    blocks = {k: L.compare(res['dU']['up'], res[k]['up']) for k in B.BLOCKS}
    L.holm(blocks)
    keep = [k for k in B.BLOCKS if blocks[k]['pass']]
    fin = base_c + ['dU'] + sum([blk_cols(k) for k in keep], [])
    rk = run(fin)
    cmp['kept vs base (all)'] = L.compare(res['base']['all'], rk['all'])
    cmp['kept vs base (rose 25%+)'] = L.compare(res['base']['up'], rk['up'])
    cmp['kept vs dU (rose 25%+)'] = L.compare(res['dU']['up'], rk['up'])
    X = F[:, ix(fin)]
    lam = pick_lam(X, y, w, S)
    b0, b = L.wls(X, y, w, lam)
    # ship the tiers when the fitted model beats the no-workload baseline out of sample on the risers
    t = cmp['kept vs base (rose 25%+)']
    ship = bool(t['t'] >= 2 and t['won'] * 2 > t['seasons'])
    print(side, 'pairs', len(R), 'rose', int(up.sum()), flush=True)
    for k, v in cmp.items():
        print('  ', k, v, flush=True)
    for k, v in blocks.items():
        print('   block', k, v, flush=True)
    return {'n': len(R), 'n_up': int(up.sum()), 'tests': cmp, 'blocks': blocks, 'keep': keep, 'lam': lam,
            'ship': ship, 'du99': round(float(np.quantile(du, 0.99)), 3), 'du01': round(float(np.quantile(du, 0.01)), 3),
            'fit': {'b0': round(float(b0), 5), 'cols': fin, 'b': [round(float(v), 6) for v in b]}}


INT = {}


def breakout(P, N):
    left = lambda o: 0.0 if (o['id'], o['y'] + 1) in P and P[(o['id'], o['y'] + 1)]['tm'] == o['tm'] else 1.0  # noqa: E731
    V = B.vacated(P, left)
    last = max(y for _, y in P)
    reg = [B.shr(o['vz'], o['v']) for o in P.values() if o['y'] < last and o['u'] >= B.T_REG[o['g']]
           and o['gp'] >= 0.5 * N[f"{o['g']}|{o['y']}"]['gmax']]
    Lq = round(float(np.quantile(reg, B.L_PCT)), 3)
    seen = {}
    for (pid, y), o in sorted(P.items(), key=lambda kv: kv[0][1]):
        seen.setdefault(pid, []).append(o)
    R, n_all = [], 0
    for (pid, y), a in P.items():
        if y >= last:
            continue
        n_all += 1
        if B.best([o for o in seen[pid] if o['y'] <= y]) >= Lq:
            continue
        b = P.get((pid, y + 1))
        hist = B.history(P, pid, y)
        s0, mar = B.shr(a['vz'], a['v']), B.marcel(hist, y)
        hit = 0.0
        if b:
            n = N[f"{b['g']}|{y + 1}"]
            if b['u'] >= B.T_REG[b['g']] and b['gp'] >= 0.5 * n['gmax'] and B.shr(b['vz'], b['v']) >= Lq:
                hit = 1.0
        R.append((a, s0, hit, V[(pid, y)], mar))
    S = np.array([a['y'] + 1 for a, *_ in R], float)
    y = np.array([r[2] for r in R])
    rows = [B.bo_feats(a, s0, v, m) for a, s0, _, v, m in R]
    base = np.array([r['base'] for r in rows])
    cands = {k: np.array([r[k] for r in rows]) for k in B.BO_CANDS}

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
    keep = [k for k in cands if res[k]['pass']]
    X = np.column_stack([base] + [cands[k] for k in keep])
    final = L.compare(rb, run(X))
    # held-out calibration: every row scored by the fit that never saw its season
    ph = np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        b0, b = L.logit(X[~te], y[~te])
        ph[te] = L.sig(b0 + X[te] @ b)
    cal = []
    for lo, hi in ((0, .02), (.02, .04), (.04, .07), (.07, .1), (.1, .15), (.15, .25), (.25, 1)):
        m = (ph >= lo) & (ph < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(ph[m].mean()), 3), round(float(y[m].mean()), 3)])
    b0, b = L.logit(X, y)
    by_pos = {g: [int(sum(1 for r in R if r[0]['g'] == g)), round(float(np.mean([r[2] for r in R if r[0]['g'] == g])), 4)]
              for g in B.POS}
    by_season = {int(s): round(float(y[S == s].mean()), 4) for s in sorted(set(S.tolist()))}
    print('L', Lq, 'of', n_all, 'base rows; breakout rate', round(float(y.mean()), 4), 'n', len(y), by_pos, by_season, flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' final', keep, final, flush=True)
    print(' calib (held out)', cal, flush=True)
    INT.update(R=R, S=S, y=y, base=base, cands=cands, keep=keep, Lq=Lq, seen=seen, rb=rb)
    u0_min = {g: round(float(np.quantile([r[0]['u0'] for r in R if r[0]['g'] == g], 0.01)), 3) for g in B.POS}
    return {'L': Lq, 'l_pct': B.L_PCT, 'n_all': n_all, 'n': len(y), 'rate': round(float(y.mean()), 4), 'u0_min': u0_min, 'by_pos': by_pos, 'by_season': by_season, 'tests': res,
            'keep': keep, 'final': final, 'calib_heldout': cal,
            'fit': {'b0': round(float(b0), 5), 'b': [round(float(v), 6) for v in b],
                    'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


# ---------- improvement sweep (pre-registered: project files next-up/prereg-cfb.md) ----------
def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).sum())


class GBT:
    """log-loss gradient boosting on quantile-binned columns: depth 2, shrinkage 0.08, min leaf 40"""
    LR, DEPTH, LEAF, BINS, LAM, MAXR = 0.08, 2, 40, 32, 1.0, 400

    def __init__(self, X):
        self.thr = [np.unique(np.quantile(X[:, j], np.linspace(0, 1, self.BINS + 1)[1:-1])) for j in range(X.shape[1])]

    def bins(self, X):
        return np.column_stack([np.searchsorted(t, X[:, j], side='left') for j, t in enumerate(self.thr)])

    def _split(self, Bn, g, h, idx, depth):
        G, H = g[idx].sum(), h[idx].sum()
        leaf = [round(float(-self.LR * G / (H + self.LAM)), 6)]
        if depth == 0 or len(idx) < 2 * self.LEAF:
            return leaf
        F = Bn.shape[1]
        flat = (Bn[idx] + np.arange(F) * self.BINS).ravel()
        n = F * self.BINS
        cg = np.bincount(flat, np.repeat(g[idx], F), n).reshape(F, self.BINS).cumsum(1)
        ch = np.bincount(flat, np.repeat(h[idx], F), n).reshape(F, self.BINS).cumsum(1)
        cn = np.bincount(flat, minlength=n).reshape(F, self.BINS).cumsum(1)
        gain = cg ** 2 / (ch + self.LAM) + (G - cg) ** 2 / (H - ch + self.LAM) - G ** 2 / (H + self.LAM)
        gain[(cn < self.LEAF) | (len(idx) - cn < self.LEAF)] = -1
        j, b = np.unravel_index(np.argmax(gain), gain.shape)
        if gain[j, b] <= 1e-9 or b >= len(self.thr[j]):
            return leaf
        m = Bn[idx, j] <= b
        return [int(j), float(self.thr[j][b]), self._split(Bn, g, h, idx[m], depth - 1),
                self._split(Bn, g, h, idx[~m], depth - 1)]

    @staticmethod
    def _apply(t, X):
        if len(t) == 1:
            return np.full(len(X), t[0])
        m = X[:, t[0]] <= t[1]
        out = np.empty(len(X))
        out[m] = GBT._apply(t[2], X[m])
        out[~m] = GBT._apply(t[3], X[~m])
        return out

    def fit(self, X, y, rounds, Xv=None, yv=None):
        """returns (f0, trees, per-round validation loss when Xv is given)"""
        Bn = self.bins(X)
        p0 = float(np.clip(y.mean(), 1e-4, 1 - 1e-4))
        f0 = math.log(p0 / (1 - p0))
        f = np.full(len(y), f0)
        fv = np.full(len(Xv), f0) if Xv is not None else None
        trees, val, idx = [], [], np.arange(len(y))
        for _ in range(rounds):
            pr = L.sig(f)
            t = self._split(Bn, pr - y, pr * (1 - pr), idx, self.DEPTH)
            trees.append(t)
            f += self._apply(t, X)
            if fv is not None:
                fv += self._apply(t, Xv)
                val.append(logloss(L.sig(fv), yv))
        return f0, trees, val


def gbt_fold(X, y, S, trn, te):
    """held-out probabilities: rounds by early stopping on an inner split of the training seasons, then a refit"""
    u = sorted(set(S[trn].tolist()))
    hold = trn & np.isin(S, u[1::2])
    inn = trn & ~hold
    m = GBT(X[trn])
    _, _, val = m.fit(X[inn], y[inn], GBT.MAXR, X[hold], y[hold])
    rounds = int(np.argmin(val)) + 1
    f0, trees, _ = m.fit(X[trn], y[trn], rounds)
    f = np.full(int(te.sum()), f0)
    for t in trees:
        f += GBT._apply(t, X[te])
    return L.sig(f), rounds


def pav(x, y):
    """isotonic regression (pool adjacent violators) -> knots (x mean, y mean) of the blocks"""
    o = np.argsort(x)
    bl = [[float(a), float(b), 1.0] for a, b in zip(x[o], y[o])]
    out = []
    for b in bl:
        out.append(b)
        while len(out) > 1 and out[-2][1] >= out[-1][1]:
            a2, b2 = out[-2], out[-1]
            n = a2[2] + b2[2]
            out[-2:] = [[(a2[0] * a2[2] + b2[0] * b2[2]) / n, (a2[1] * a2[2] + b2[1] * b2[2]) / n, n]]
    return [round(b[0], 5) for b in out], [round(b[1], 5) for b in out]


def sweep(P, BO):
    R, S, y, rb = INT['R'], INT['S'], INT['y'], INT['rb']
    Lq, seen = INT['Lq'], INT['seen']
    D, ST = B.depth(P), B.staff_index()
    ex, raw = [], []
    for a, s0, _, _, mar in R:
        earlier = [o for o in seen[a['id']] if o['y'] < a['y']]
        ex.append(B.extra_feats(a, D[(a['id'], a['y'])], B.staff_feats(a, ST), earlier, Lq))
        raw.append(B.spline_raw(a, s0, mar))
    raw = np.array(raw)
    E = {k: np.array([r[k] for r in ex]) for k in B.EXTRA}
    Xk = np.column_stack([INT['base']] + [INT['cands'][k] for k in INT['keep']])
    seasons = sorted(set(S.tolist()))
    err = lambda p, te: (logloss(p, y[te]), float(te.sum()))  # noqa: E731

    def knots(m):
        return [[round(float(q), 4) for q in np.quantile(raw[m, j], [1 / 3, 2 / 3])] for j in range(raw.shape[1])]

    def hing(m_fit, rows):
        ks = knots(m_fit)
        return np.array([B.hinges(r, ks) for r in raw[rows]])

    def lg(X, spl=False):
        def fp(trn, te):
            A, T = X[trn], X[te]
            if spl:
                A, T = np.column_stack([A, hing(trn, trn)]), np.column_stack([T, hing(trn, te)])
            b0, b = L.logit(A, y[trn])
            return L.sig(b0 + T @ b)
        return fp

    def held(fp):
        """held-out probabilities for every row"""
        p = np.zeros(len(y))
        for s in seasons:
            te = S == s
            p[te] = fp(~te, te)
        return p

    def score(p):
        return {s: err(p[S == s], S == s) for s in seasons}
    ref_p = held(lg(Xk))
    ref = score(ref_p)
    tests = {k: L.compare(ref, score(held(lg(np.column_stack([Xk, E[k]]))))) for k in B.EXTRA}
    for k, v in tests.items():
        print('  signal', k, v, flush=True)
    Xall = np.column_stack([Xk] + [E[k] for k in B.EXTRA] + [INT['cands'][k] for k in B.BO_CANDS if k not in INT['keep']])
    add = [k for k in B.EXTRA if tests[k]['t'] >= 2 and tests[k]['won'] * 2 > tests[k]['seasons']]
    for _ in range(3):
        Xf = np.column_stack([Xk] + [E[k] for k in add])
        fin_p = held(lg(Xf))
        fin = score(fin_p)
        forms, rounds = {}, {}
        for nm, X in (('trees, same columns', Xf), ('trees, all columns', Xall)):
            p = np.zeros(len(y))
            rr = []
            for s in seasons:
                te = S == s
                p[te], r = gbt_fold(X, y, S, ~te, te)
                rr.append(r)
            forms[nm] = (p, L.compare(fin, score(p)))
            rounds[nm] = rr
        forms['logistic + splines'] = (held(lg(Xf, True)), None)
        forms['logistic + splines'] = (forms['logistic + splines'][0], L.compare(fin, score(forms['logistic + splines'][0])))
        okf = [k for k, (_, c) in forms.items() if c['t'] >= 2 and c['won'] * 2 > c['seasons']]
        form = max(okf, key=lambda k: forms[k][1]['gain']) if okf else 'logistic'
        ship_p = forms[form][0] if form != 'logistic' else fin_p
        shipped = score(ship_p)

        def fold_fit(trn, te):
            """one fold of the shipped form (used inside the training seasons for the recalibration)"""
            if form == 'logistic':
                return lg(Xf)(trn, te)
            if form == 'logistic + splines':
                return lg(Xf, True)(trn, te)
            return gbt_fold(Xf if form == 'trees, same columns' else Xall, y, S, trn, te)[0]
        pl, iso = np.zeros(len(y)), np.zeros(len(y))
        for s in seasons:
            te = S == s
            trn = ~te
            pin = np.zeros(len(y))
            for s2 in seasons:
                if s2 != s:
                    t2 = S == s2
                    pin[t2] = fold_fit(trn & ~t2, t2)
            lo = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))  # noqa: E731
            a0, bb = L.logit(lo(pin[trn])[:, None], y[trn], lam=0)
            pl[te] = L.sig(a0 + bb[0] * lo(ship_p[te]))
            kx, ky = pav(pin[trn], y[trn])
            iso[te] = np.interp(ship_p[te], kx, ky)
        cal = {'Platt': (pl, L.compare(shipped, score(pl))), 'isotonic': (iso, L.compare(shipped, score(iso)))}
        allt = dict(tests)
        allt.update({k: c for k, (_, c) in forms.items()})
        allt.update({'recalibration: ' + k: c for k, (_, c) in cal.items()})
        L.holm(allt)
        add2 = [k for k in B.EXTRA if allt[k]['pass']]
        if add2 == add:
            break
        add = add2
    for k in allt:
        if k not in tests:
            print('  ', k, allt[k], flush=True)
    form_ok = form != 'logistic' and allt[form]['pass']
    if not form_ok:
        form, ship_p = 'logistic', fin_p
    okc = [k for k in cal if allt['recalibration: ' + k]['pass']]
    calk = max(okc, key=lambda k: cal[k][1]['gain']) if okc else None
    out_p = cal[calk][0] if calk else ship_p
    vs_redo = L.compare(ref, score(out_p))
    vs_base = L.compare(rb, score(out_p))
    bins = []
    for lo_, hi in ((0, .02), (.02, .04), (.04, .07), (.07, .1), (.1, .15), (.15, .25), (.25, 1)):
        m = (out_p >= lo_) & (out_p < hi)
        if m.sum():
            bins.append([lo_, hi, int(m.sum()), round(float(out_p[m].mean()), 3), round(float(y[m].mean()), 3)])
    print('  shipped: signals', add, 'form', form, 'recalibration', calk, flush=True)
    print('  vs redo', vs_redo, '\n  vs baseline', vs_base, '\n  calib', bins, flush=True)
    # the full-data fit that the live board serves
    allm = np.ones(len(y), bool)
    fit = {'form': form, 'extra': add}
    if form in ('logistic', 'logistic + splines'):
        X = Xf
        if form != 'logistic':
            fit['knots'] = knots(allm)
            X = np.column_stack([Xf, hing(allm, allm)])
        b0, b = L.logit(X, y)
        fit.update(b0=round(float(b0), 5), b=[round(float(v), 6) for v in b], mu=[round(float(v), 5) for v in X.mean(axis=0)])
    else:
        X = Xf if form == 'trees, same columns' else Xall
        m = GBT(X)
        f0, trees, _ = m.fit(X, y, int(np.median(rounds[form])))
        fit.update(f0=round(f0, 5), trees=trees, all_columns=form == 'trees, all columns')
    if calk:
        pin = held(fold_fit)
        if calk == 'Platt':
            lo = np.log(np.clip(pin, 1e-6, 1 - 1e-6) / (1 - np.clip(pin, 1e-6, 1 - 1e-6)))
            a0, bb = L.logit(lo[:, None], y, lam=0)
            fit['cal'] = {'kind': 'platt', 'a': round(float(a0), 5), 'b': round(float(bb[0]), 5)}
        else:
            kx, ky = pav(pin, y)
            fit['cal'] = {'kind': 'isotonic', 'x': kx, 'y': ky}
    BO['redo'] = {'keep': BO['keep'], 'final': BO['final'], 'calib_heldout': BO['calib_heldout']}
    BO['sweep'] = {'prereg': 'project files next-up/prereg-cfb.md', 'tests': allt, 'signals': add, 'form': form,
                   'recalibration': calk, 'vs_redo': vs_redo, 'not_run': ['within-season trend', 'play-type / tracking']}
    BO['final'], BO['calib_heldout'], BO['fit'] = vs_base, bins, fit
    return BO


def main():
    P = B.load('--offline' in sys.argv)
    N = B.season_norms(P)
    last = max(y for _, y in P)
    hist = {k: o for k, o in P.items() if k[1] < last}
    SD = B.sd_from(hist, N)
    P = B.standardize(P, N, SD)
    B.add_context(P)
    size = {}
    for g in B.POS:
        seen, hs, bs = set(), [], []
        for o in P.values():
            if o['g'] == g and o['_ht'] and o['id'] not in seen:
                seen.add(o['id'])
                hs.append(o['_ht'])
                bs.append(703.0 * o['_wt'] / o['_ht'] ** 2)
        size[g] = {'ht': [round(float(np.mean(hs)), 3), round(float(np.std(hs)), 3)],
                   'bmi': [round(float(np.mean(bs)), 3), round(float(np.std(bs)), 3)], 'n': len(hs)}
    for o in P.values():
        B.set_context(o, o['yrs'] if o['hasyrs'] else None, None if o['unr'] else o['stars'], o['_ht'], o['_wt'], size)
    cov = {k: round(float(np.mean([o[k] for o in P.values()])), 3) for k in ('hasyrs', 'hasfr')}
    cov['stars'] = round(float(np.mean([1 - o['unr'] for o in P.values()])), 3)
    print('player-seasons', len(P), 'coverage', cov, flush=True)
    A = {side: scaling(P, side) for side in ('off', 'def')}
    BO = breakout(P, N)
    BO = sweep(P, BO)
    tiers = {'pct': list(TIER_PCT), 'u': {}}
    for g in B.POS:
        us = sorted(o['u'] for o in P.values() if o['g'] == g and o['y'] < last and o['u'] >= B.T_REG[g]
                    and o['gp'] >= 0.5 * N[f"{g}|{o['y']}"]['gmax'])
        tiers['u'][g] = {str(p): round(float(np.quantile(us, p / 100)), 2) for p in TIER_PCT}
    f, so = BO['final'], A['off']
    kt = so['tests']['kept vs base (rose 25%+)']
    about = (f"breakout: next season a regular at or over the quality bar for the first time (PFN score z shrunk to "
             f"replacement by workload >= {BO['L']}, the {B.L_PCT * 100:g}th percentile of regulars); players already at "
             f"the bar this season or an earlier one are left out; base {last}; odds = logistic on shrunk z, workload, "
             f"position + {', '.join(BO['keep'] + BO['sweep']['signals']) or 'nothing else'}"
             f"{'' if BO['sweep']['form'] == 'logistic' else ', ' + BO['sweep']['form']}"
             f"{', ' + BO['sweep']['recalibration'] + ' recalibration' if BO['sweep']['recalibration'] else ''} (each passes leave-one-season-out 2019-{last}; final "
             f"t {f['t']}, {f['won']}/{f['seasons']} seasons). OPP/G = attempts (QB), carries + catches (RB), targets "
             f"(WR, TE), snaps (EDGE, DT, LB) a game; seniors and workloads below the fit's range left out. ")
    if so['ship']:
        about += (f"tiers = the position's P50 / P80 / P95 workload among regulars: next-season yards per opportunity "
                  f"at that workload from players whose workload changed ({', '.join(so['keep']) or 'workload change only'}"
                  f"; held out t {kt['t']}, {kt['won']}/{kt['seasons']} seasons on workloads up 25%+); offense only; "
                  f"dim = a jump beyond the 99th percentile")
    else:
        about += (f"no workload tiers: the change in workload did not predict next-season efficiency out of sample "
                  f"(t {kt['t']}, {kt['won']}/{kt['seasons']} seasons on workloads up 25%+)")
    json.dump({'source': f'PFN impact rankings, FBS 2019-{last}', 'definition': {
                   'breakout': 'next season: T_REG opportunities a game, half the season\'s games and shrunk score z >= L, with no season so far (2019 on, this one included) at or over L',
                   'L': BO['L'], 'l_pct': B.L_PCT, 'rep': B.REP, 'k_shrink_games': B.K_SHR, 't_reg': B.T_REG, 'min_opp': B.MIN_OPP},
               'coverage': cov, 'scaling': A, 'breakout': BO, 'tiers': tiers, 'size': size,
               'norms': {k: {a: round(b, 5) for a, b in v.items()} for k, v in N.items()},
               'sd': {g: {a: round(b, 5) for a, b in v.items()} for g, v in SD.items()}, 'about': about},
              open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
