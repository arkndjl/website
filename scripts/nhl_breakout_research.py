# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL Potential Breakout research: ice-time scaling and breakout signals, leave-one-season-out (scripts/breakout_lib.py).

    python3 scripts/nhl_breakout_research.py   # -> data/nhl_breakout_fit.json

History: NHL stats API skater reports 2009-10 on (scripts/nhl_breakout.py pull, cached in scripts/.cache/nhl/bo) and
the site's WAR (static/data/nhl-war/<season>.json). Skaters only.

A. Ice-time scaling, three relations (scripts/nhl_breakout.py TARGETS): even-strength points a 60 against even-strength
   minutes a game, power-play points a 60 against power-play minutes a game, power-play minutes against total minutes.
   Pairs of consecutive seasons over the sample floors, weight = next season's sample minutes (capped). Next season's
   value on this season's (shrunk by sample) + age + workload + D, then + the workload change (dU), then + dU x traits
   a block at a time. Held-out error on all pairs and on the pairs whose workload rose (the case the tab projects).
   Selection check: the same workload change instrumented by what the player did not choose (minutes vacated at his
   position and on the power play by team-mates who left, a change of team), two-stage least squares.
B. Breakout odds. Value = the site's WAR a 1,000 minutes shrunk to replacement by ice time (k 600 minutes). The bar L
   = the 78th percentile of that value over skater-seasons with a regular role (900+ minutes per 82 team games).
   Rows: 200+ minutes this season and no season to date (2008-09 on) at or over L; rows start in 2012-13 so the
   career-to-date check has seasons behind it. Breakout = next season at or over L with 900+ minutes (the first time).
   Baseline logistic: shrunk WAR rate, gap to his best, ln minutes, D. Candidates one at a time, Holm, then the
   passers together. Calibration is on the held-out predictions.
C. Improvement sweep (pre-registered: project files next-up/prereg-nhl.md), on B's rows, each on top of B's kept
   model: development curve, depth opportunity, departures ahead, coaching change, within-season trend, experience,
   offence / defence split; then gradient-boosted trees and hinge splines against the logistic, and a Platt step fit
   inside the training folds. Holm across all ten; the shipped model = B's kept signals + the passers."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nhl_breakout as B  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'nhl_breakout_fit.json')
Y0 = 2010
LAMS = (1e-4, 1e-3, 1e-2, 3e-2, 0.1)
DEFN = ('next season at or over L = {L:.2f} WAR a 1,000 minutes (shrunk to replacement by ice time, k 600 minutes; the '
        '{Q}th percentile of regular-role skater-seasons) with 900+ minutes (per 82 team games), for the first time.')
Q_BAR, Y_BO = 78, 2013


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


def scaling(P, last):
    out = {}
    for tgt, T in B.TARGETS.items():
        R = []
        for (pid, y), a in P.items():
            b = P.get((pid, y + 1))
            if y < Y0 or y >= last or not b:
                continue
            if a[T['n']] < T['minn'][0] * a['gmax'] / 82 or b[T['n']] < T['minn'][1] * b['gmax'] / 82:
                continue
            R.append((pid, y, a, b))
        S = np.array([y + 1 for _, y, _, _ in R], float)
        w = np.array([min(b[T['n']], 4 * T['k']) for _, _, a, b in R], float)
        du = np.array([b[T['u']] - a[T['u']] for _, _, a, b in R])
        y = np.array([b[T['x']] for _, _, a, b in R])
        F = np.array([B.features(tgt, a, B.history(P, pid, yy), d) for (pid, yy, a, b), d in zip(R, du)])
        cols = B.columns(tgt)
        ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
        sets = {'base': B.BASE, 'dU': B.BASE + ['dU']}
        for blk, traits in B.BLOCKS.items():
            sets[blk] = B.BASE + ['dU'] + sum([['dU*' + t, t] for t in traits], [])
        sets['full'] = cols
        up, up2 = du >= T['rose'], du >= 2 * T['rose']
        masks = {'all': np.ones(len(y), bool), 'up': up, 'up2': up2}

        def run(cs):
            X = F[:, ix(cs)]

            def fp(trn, te):
                lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
                b0, b = L.wls(X[trn], y[trn], w[trn], lam)
                return b0 + X[te] @ b
            r = {}
            for key, m in masks.items():
                def e(p, te, m=m):
                    mm = m[te]
                    return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
                r[key] = L.loso(S, fp, e)
            return r
        res = {nm: run(cs) for nm, cs in sets.items()}
        rl = f"rose {T['rose']}+"
        cmp = {'dU vs base (all)': L.compare(res['base']['all'], res['dU']['all']),
               f'dU vs base ({rl})': L.compare(res['base']['up'], res['dU']['up']),
               'full vs base (all)': L.compare(res['base']['all'], res['full']['all']),
               f'full vs dU ({rl})': L.compare(res['dU']['up'], res['full']['up']),
               f"full vs dU (rose {2 * T['rose']}+)": L.compare(res['dU']['up2'], res['full']['up2'])}
        blocks = {k: L.compare(res['dU']['up'], res[k]['up']) for k in B.BLOCKS}
        blocks_all = {k: L.compare(res['dU']['all'], res[k]['all']) for k in B.BLOCKS}
        L.holm(blocks)
        keep = [k for k in B.BLOCKS if blocks[k]['pass']]
        fin = B.BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in B.BLOCKS[k]], []) for k in keep], [])
        rk = run(fin)
        cmp['kept vs base (all)'] = L.compare(res['base']['all'], rk['all'])
        cmp[f'kept vs base ({rl})'] = L.compare(res['base']['up'], rk['up'])
        cmp[f'kept vs dU ({rl})'] = L.compare(res['dU']['up'], rk['up'])
        X = F[:, ix(fin)]
        lam = pick_lam(X, y, w, S)
        b0, b = L.wls(X, y, w, lam)
        out[tgt] = {'n': len(R), 'n_up': int(up.sum()), 'n_up2': int(up2.sum()), 'rose': T['rose'],
                    'du_q99': round(float(np.quantile(du, .99)), 2), 'tests': cmp, 'blocks': blocks,
                    'blocks_all_pairs': blocks_all, 'keep': keep, 'lam': lam,
                    'fit': {'b0': round(float(b0), 5), 'cols': fin, 'b': [round(float(v), 7) for v in b]}}
        print(tgt, 'n', len(R), 'up', int(up.sum()), flush=True)
        for k, v in cmp.items():
            print('  ', k, v, flush=True)
        for k, v in blocks.items():
            print('   block', k, v, flush=True)
    return out


def instrumented(P, last):
    """workload change coefficient: least squares against two-stage least squares (instruments: vacated position
    minutes share, vacated power-play minutes share, changed team)"""
    by = {}
    for (pid, y), o in P.items():
        by.setdefault(y, {})[pid] = o
    out = {}
    for tgt, T in B.TARGETS.items():
        X, Z, du, Y, w = [], [], [], [], []
        for y in range(Y0, last):
            V = B.vacated(by[y], by[y + 1])
            for pid, a in by[y].items():
                b = by[y + 1].get(pid)
                if (not b or not a['tm'] or not b['tm'] or a[T['n']] < T['minn'][0] * a['gmax'] / 82
                        or b[T['n']] < T['minn'][1] * b['gmax'] / 82):
                    continue
                X.append(B.features(tgt, a, B.history(P, pid, y), 0.0)[:len(B.BASE)])
                Z.append([V[pid][0], V[pid][1], 1.0 if a['tm'] != b['tm'] else 0.0])
                du.append(b[T['u']] - a[T['u']])
                Y.append(b[T['x']])
                w.append(min(b[T['n']], 4 * T['k']))
        X, Z, du, Y, w = np.array(X), np.array(Z), np.array(du), np.array(Y), np.sqrt(np.array(w))
        A = np.column_stack([np.ones(len(X)), X])
        AZ = np.column_stack([A, Z])
        ols = lambda M, v: np.linalg.lstsq(M * w[:, None], v * w, rcond=None)[0]  # noqa: E731
        b1, b0 = ols(AZ, du), ols(A, du)
        r1, r0 = (du - AZ @ b1) * w, (du - A @ b0) * w
        F = ((r0 @ r0 - r1 @ r1) / 3) / (r1 @ r1 / (len(du) - AZ.shape[1]))
        dh = AZ @ b1
        b2, bo = ols(np.column_stack([A, dh]), Y), ols(np.column_stack([A, du]), Y)
        res = (Y - np.column_stack([A, du]) @ b2) * w
        M = np.column_stack([A, dh]) * w[:, None]
        se = float(np.sqrt((res @ res / (len(Y) - M.shape[1])) * np.linalg.inv(M.T @ M)[-1, -1]))
        out[tgt] = {'n': len(Y), 'first_stage_F': round(float(F), 1), 'ols': round(float(bo[-1]), 4),
                    'iv': round(float(b2[-1]), 4), 'iv_se': round(se, 4)}
        print('instrumented', tgt, out[tgt], flush=True)
    return out


def contexts(P, by, y, CS):
    """{pid: ctx} for season y: depth, departures ahead, coaching change, within-season trend"""
    dp, ag = B.depth(by[y]), B.ahead_gone(by[y], by[y + 1])
    tr = B.trend(B.D._logs('skater', y, 2, False))
    return {pid: {'depth': dp[pid], 'ahead': ag[pid], 'coach': B.coach_changed(CS, a['tm'], y) or 0.0,
                  'trend': tr.get(pid, [0.0, 0.0, 0.0])} for pid, a in by[y].items()}


def logloss(y):
    def err(p, te):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))
    return err


def run_logit(X, y, S, keep_pred=None):
    def fp(trn, te):
        b0, b = L.logit(X[trn], y[trn])
        p = L.sig(b0 + X[te] @ b)
        if keep_pred is not None:
            keep_pred[te] = p
        return p
    return L.loso(S, fp, logloss(y))


def calib(ho, y):
    cal = []
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .15), (.15, .25), (.25, 1)):
        m = (ho >= lo) & (ho < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(ho[m].mean()), 3), round(float(y[m].mean()), 3)])
    return cal


def breakout(P, last):
    by = {}
    for (pid, y), o in P.items():
        by.setdefault(y, {})[pid] = o
    C = B.career(last=last)
    CS = B.coach_stints()
    reg = [B.shr(o) for o in P.values() if o['war'] is not None and o['y'] <= last
           and o['tmin'] >= B.ROLE_MIN * o['gmax'] / 82]
    Lq = round(float(np.percentile(reg, Q_BAR)), 2)
    R, seen = [], 0
    for y in range(Y_BO, last):
        V = B.vacated(by[y], by[y + 1])
        CX = contexts(P, by, y, CS)
        for pid, a in by[y].items():
            if a['war'] is None or a['tmin'] < B.ROW_MIN * a['gmax'] / 82:
                continue
            seen += 1
            if max(B.peak(C, pid, y) or -9, B.shr(a)) >= Lq:
                continue
            b = by[y + 1].get(pid)
            hit = 1.0 if (b and b['war'] is not None and b['tmin'] >= B.ROLE_MIN * b['gmax'] / 82
                          and B.shr(b) >= Lq) else 0.0
            R.append((a, hit, B.bo_feats(a, B.history(P, pid, y), V[pid], CX[pid])))
    print('L', Lq, 'regular-role seasons', len(reg), 'rows', len(R), 'of', seen, flush=True)
    S = np.array([a['y'] + 1 for a, _, _ in R], float)
    y = np.array([h for _, h, _ in R])
    base = np.array([f['base'] for _, _, f in R])
    cands = {k: np.array([f[k] for _, _, f in R]) for k in B.BO_CANDS}
    rb = run_logit(base, y, S)
    res = {k: L.compare(rb, run_logit(np.column_stack([base, X]), y, S)) for k, X in cands.items()}
    L.holm(res)
    keep = [k for k in cands if res[k]['pass']]
    X = np.column_stack([base] + [cands[k] for k in keep])
    ho = np.zeros(len(y))
    r0 = run_logit(X, y, S, ho)
    final = L.compare(rb, r0)
    d = np.array([a['d'] for a, _, _ in R])
    print('breakout rate', round(float(y.mean()), 4), 'n', len(y), 'F', round(float(y[d == 0].mean()), 4), 'D',
          round(float(y[d == 1].mean()), 4), flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' redo final', keep, final, flush=True)
    print(' redo calib (held out)', calib(ho, y), flush=True)

    # ---------- C. improvement sweep ----------
    new = {k: np.array([f[k] for _, _, f in R]) for k in B.BO_NEW}
    sw = {k: L.compare(r0, run_logit(np.column_stack([X, Z]), y, S)) for k, Z in new.items()}
    prov = [k for k in B.BO_NEW if sw[k]['t'] >= 2 and sw[k]['won'] * 2 > sw[k]['seasons']]
    Xf = np.column_stack([X] + [new[k] for k in prov])
    rf = run_logit(Xf, y, S)
    sw['M1 boosted trees'] = L.compare(rf, L.loso(S, lambda trn, te: gbt_fold(Xf, y, S, trn, te), logloss(y)))
    sp = np.array([B.hinges(a) for a, _, _ in R])
    sw['M2 hinge splines'] = L.compare(rf, run_logit(np.column_stack([Xf, sp]), y, S))

    def platt(trn, te):
        inner = np.zeros(len(y))
        for s in sorted(set(S[trn].tolist())):
            m = trn & (S == s)
            t2 = trn & ~m
            b0, b = L.logit(Xf[t2], y[t2])
            inner[m] = L.sig(b0 + Xf[m] @ b)
        z = np.log(np.clip(inner[trn], 1e-6, 1 - 1e-6) / (1 - np.clip(inner[trn], 1e-6, 1 - 1e-6)))
        a0, a1 = L.logit(z[:, None], y[trn], lam=1e-6)
        b0, b = L.logit(Xf[trn], y[trn])
        return L.sig(a0 + a1[0] * (b0 + Xf[te] @ b))
    sw['C1 Platt step'] = L.compare(rf, L.loso(S, platt, logloss(y)))
    L.holm(sw)
    for k, v in sw.items():
        print('  sweep', k, v, flush=True)
    add = [k for k in B.BO_NEW if sw[k]['pass']]
    keep2 = keep + add
    X2 = np.column_stack([X] + [new[k] for k in add])
    use_sp = sw['M2 hinge splines']['pass']
    if use_sp:
        X2 = np.column_stack([X2, sp])
    ho2 = np.zeros(len(y))
    r2 = run_logit(X2, y, S, ho2)
    final2 = L.compare(rb, r2)
    vs = L.compare(r0, r2)
    b0, b = L.logit(X2, y)
    print(' final', keep2, 'splines', use_sp, final2, flush=True)
    print(' final vs redo', vs, flush=True)
    print(' calib (held out)', calib(ho2, y), flush=True)
    allc = dict(cands, **new)
    return {'L': Lq, 'n_all': seen, 'n': len(y), 'rate': round(float(y.mean()), 4), 'tests': res,
            'redo': {'keep': keep, 'final': final, 'calib_held_out': calib(ho, y)},
            'sweep': {'prereg': 'project files next-up/prereg-nhl.md', 'tests': sw, 'provisional': prov,
                      'not_tested': 'play-type / tracking rates: NHL EDGE starts 2021-22, no free source for the window',
                      'final_vs_redo': vs},
            'keep': keep2, 'splines': bool(use_sp), 'final': final2, 'calib_held_out': calib(ho2, y),
            'width': {k: int(allc[k].shape[1]) for k in keep2},
            'fit': {'b0': round(float(b0), 5), 'b': [round(float(v), 6) for v in b],
                    'mu': [round(float(v), 5) for v in X2.mean(axis=0)]}}


# ---------- gradient-boosted trees (numpy) ----------
def gbt_bins(X, nb=32):
    return [np.unique(np.quantile(X[:, j], np.linspace(0, 1, nb + 1)[1:-1])) for j in range(X.shape[1])]


def gbt_bin(X, edges):
    return np.column_stack([np.searchsorted(e, X[:, j], side='right') for j, e in enumerate(edges)])


def gbt_tree(Xb, g, h, idx, depth, lr, minh=5.0, lam=1.0, nb=33):
    G, H = g[idx].sum(), h[idx].sum()
    if depth == 0 or len(idx) < 20:
        return float(lr * G / (H + lam))
    best = (1e-9, None, None)
    for j in range(Xb.shape[1]):
        col = Xb[idx, j]
        gl = np.cumsum(np.bincount(col, g[idx], nb))[:-1]
        hl = np.cumsum(np.bincount(col, h[idx], nb))[:-1]
        ok = (hl >= minh) & (H - hl >= minh)
        if not ok.any():
            continue
        gain = np.where(ok, gl ** 2 / (hl + lam) + (G - gl) ** 2 / (H - hl + lam) - G ** 2 / (H + lam), -1)
        k = int(gain.argmax())
        if gain[k] > best[0]:
            best = (float(gain[k]), j, k)
    if best[1] is None:
        return float(lr * G / (H + lam))
    _, j, k = best
    m = Xb[idx, j] <= k
    return (j, k, gbt_tree(Xb, g, h, idx[m], depth - 1, lr, minh, lam, nb),
            gbt_tree(Xb, g, h, idx[~m], depth - 1, lr, minh, lam, nb))


def gbt_eval(t, Xb):
    if not isinstance(t, tuple):
        return np.full(len(Xb), t)
    j, k, lo, hi = t
    m = Xb[:, j] <= k
    out = np.empty(len(Xb))
    out[m] = gbt_eval(lo, Xb[m])
    out[~m] = gbt_eval(hi, Xb[~m])
    return out


def gbt(Xb, y, n, Xv=None, yv=None, depth=2, lr=0.1):
    """n trees; with a validation set returns the validation log loss after each tree, else the trees"""
    p0 = float(np.clip(y.mean(), 1e-4, 1 - 1e-4))
    f0 = np.log(p0 / (1 - p0))
    F = np.full(len(y), f0)
    Fv = np.full(len(Xv), f0) if Xv is not None else None
    idx = np.arange(len(y))
    trees, losses = [], []
    for _ in range(n):
        p = L.sig(F)
        t = gbt_tree(Xb, y - p, p * (1 - p), idx, depth, lr)
        F += gbt_eval(t, Xb)
        trees.append(t)
        if Xv is not None:
            Fv += gbt_eval(t, Xv)
            pv = np.clip(L.sig(Fv), 1e-6, 1 - 1e-6)
            losses.append(float(-(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)).mean()))
    return losses if Xv is not None else (f0, trees)


def gbt_fold(X, y, S, trn, te, nmax=300):
    edges = gbt_bins(X[trn])
    Xb = gbt_bin(X, edges)
    u = sorted(set(S[trn].tolist()))
    hold = trn & np.isin(S, u[1::3])
    fit = trn & ~hold
    n = int(np.argmin(gbt(Xb[fit], y[fit], nmax, Xb[hold], y[hold]))) + 1
    f0, trees = gbt(Xb[trn], y[trn], n)
    F = np.full(int(te.sum()), f0)
    for t in trees:
        F += gbt_eval(t, Xb[te])
    return L.sig(F)


def main():
    cur = B.D.current_season()
    last = cur - 1          # the last finished season
    P = {}
    for S in range(Y0, cur):
        for pid, o in B.season(S).items():
            P[(pid, S)] = o
        print(S, sum(1 for k in P if k[1] == S), flush=True)
    A = scaling(P, last)
    IV = instrumented(P, last)
    Bo = breakout(P, last)
    json.dump({'source': f'NHL stats API skater reports + site WAR, {Y0 - 1}-{Y0 % 100:02d} to {last - 1}-{last % 100}',
               'workload': 'ice time a game by state (even strength, power play); goalies not modelled',
               'definition': DEFN.format(L=Bo['L'], Q=Q_BAR), 'L': Bo['L'], 'L_pct': Q_BAR, 'scaling': A, 'scaling_instrumented': IV, 'breakout': Bo, 'k_shrink': B.K_SHR,
               'role_min': B.ROLE_MIN}, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
