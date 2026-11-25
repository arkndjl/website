#!/usr/bin/env python3
"""T-P1 (prereg.md): player x surface offsets on top of the live tennis match blend. -> tennis_surface.json
One walk-forward pass of scripts/tennis_model.py (round-1 changes in), every row from 2008 recorded before its update;
blend chances from walk-forward weights (as wf_probs: fit on the WIN seasons before, scored tour-level rows); offsets
from the residuals of every earlier row (all levels). Lockbox: rows after 20261110 never read."""
import json, math, os, pickle, sys, time
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
R1 = os.path.abspath(os.path.join(HERE, '..', '..', 'tennis'))
sys.path.insert(0, R1)
import passes as PS  # noqa: E402   (round-1 loader: matches.csv.gz up to the lockbox)
M = PS.M
CACHE = os.path.join(PS.OUT, 'port_surface_rec.pkl')
TUNE, HELD = (2012, 2019), (2020, 2026)


def record():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, 'rb'))
    rows, players = PS.load_rows()
    P = dict(M.DEFAULT, **json.load(open(M.FIT))['params'])
    m = M.Model(P, M.CM_LAG); m.set_bios(players)
    M.mark_two_week(rows)
    rec = []
    t0 = time.time()
    for i, r in enumerate(rows):
        m.release(r[0])
        if r[0] >= 20080000:
            day = M.dnum(r[0], r[4], r[2], r[6])
            _, pe, pp, gx, cx = m.predict(r[7], r[8], r[1], r[3], day, r[5])
            f = [M.logit(pe), M.logit(pp), gx * (1.25 if r[5] == 5 else 1.0)] + list(cx)
            rec.append((r[0], r[1], r[3], r[6], r[7], r[8], day, M.scored(r, 2000, 2100), f))
        m.update(r)
        if i % 200000 == 0: print('pass', i, round(time.time() - t0), flush=True)
    out = {'rec': rec, 'P': P}
    pickle.dump(out, open(CACHE, 'wb'))
    return out


def blend_z(rec, P):
    """walk-forward blend logit for every recorded row (weights from the scored rows of the WIN seasons before)"""
    F = np.array([x[8] for x in rec]); d = np.array([x[0] for x in rec]); sc = np.array([x[7] for x in rec])
    yr = d // 10000; z = np.zeros(len(rec))
    for y in np.unique(yr):
        win = np.where(sc & (d >= (y - M.WIN) * 10000) & (d < y * 10000))[0]
        if len(win) > 1000:
            W = fit(F[win][:, list(M.ALL)])
            w = np.zeros(F.shape[1]); w[list(M.ALL)] = W
        else:
            w = np.array([P.get(k, 0.0) for k in M.NAMES])
        idx = yr == y
        z[idx] = F[idx] @ w
    return z


def fit(F):
    """M.fit_blend on an array (each match twice, flipped; Newton with the same 1e-3 ridge)"""
    X = np.vstack([F, -F]); y = np.r_[np.ones(len(F)), np.zeros(len(F))]
    w = np.zeros(F.shape[1]); w[0] = 1.0
    for _ in range(30):
        p = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (y - p); H = (X * (p * (1 - p))[:, None]).T @ X
        w = w + np.linalg.solve(H + 1e-3 * np.eye(len(w)), g - 1e-3 * w)
    return w


def offsets(rec, z, k, h):
    """feature x per row = (o_w,s - o_l,s) before the row; o = R_s/(V_s+k) - R_all/(V_all+k)"""
    st = {}
    x = np.zeros(len(rec))
    lam = math.log(2) / h
    for i, r in enumerate(rec):
        _, _, sf, _, w, l, day, _, _ = r
        o = []
        for pid in (w, l):
            ss = st.get(pid)
            if ss is None:
                o.append(0.0); continue
            f = math.exp(-lam * (day - ss[4]))
            if f < 1:
                for key in ('H', 'C', 'G', 'A'): ss[key][0] *= f; ss[key][1] *= f
                ss[4] = day
            a = ss.get(sf)
            o.append((a[0] / (a[1] + k) - ss['A'][0] / (ss['A'][1] + k)) if a else 0.0)
        x[i] = o[0] - o[1]
        p = 1 / (1 + math.exp(-z[i])); v = p * (1 - p)
        for pid, res in ((w, 1 - p), (l, -(1 - p))):
            ss = st.get(pid)
            if ss is None:
                ss = st[pid] = {'H': [0.0, 0.0], 'C': [0.0, 0.0], 'G': [0.0, 0.0], 'A': [0.0, 0.0], 4: day}
            if sf in ss:
                ss[sf][0] += res; ss[sf][1] += v
            ss['A'][0] += res; ss['A'][1] += v
    return x


def nll(z): return np.logaddexp(0, -z)


def fit_c(z, x):
    c = 0.0
    for _ in range(25):
        p = 1 / (1 + np.exp(-(z + c * x)))
        g = np.sum((1 - p) * x); hh = np.sum(p * (1 - p) * x * x) + 1e-9
        c += g / hh
    return c


def main():
    R = record(); rec = R['rec']
    z = blend_z(rec, R['P'])
    d = np.array([x[0] for x in rec]); yr = d // 10000; sc = np.array([x[7] for x in rec])
    tid = np.array([f'{x[0]}|{x[3]}' for x in rec])
    tune = sc & (yr >= TUNE[0]) & (yr <= TUNE[1]); held = sc & (yr >= HELD[0]) & (yr <= HELD[1])
    print('base ll tune', nll(z[tune]).mean(), 'held', nll(z[held]).mean(), 'n', tune.sum(), held.sum(), flush=True)
    grid = []
    X = {}
    for k in (10, 30, 100):
        for h in (365, 1000):
            x = offsets(rec, z, k, h); X[(k, h)] = x
            c = fit_c(z[tune], x[tune])
            grid.append({'k': k, 'h': h, 'c': round(float(c), 4), 'tune_d_1e4': round(float((nll(z[tune] + c * x[tune]) - nll(z[tune])).mean() * 1e4), 3)})
            print(grid[-1], flush=True)
    best = min(grid, key=lambda g: g['tune_d_1e4'])
    x = X[(best['k'], best['h'])]; c = best['c']
    dd = nll(z[held] + c * x[held]) - nll(z[held])
    cl = defaultdict(float)
    for t, v in zip(tid[held], dd): cl[t] += v
    cv = np.array(list(cl.values())); n = len(dd)
    se = math.sqrt(len(cv) * np.sum((cv - cv.mean()) ** 2) / (len(cv) - 1)) / n
    t = float(dd.mean() / se)
    p1 = 0.5 * (1 + math.erf(t / math.sqrt(2)))
    by = {int(y): round(float(dd[yr[held] == y].mean() * 1e4), 2) for y in range(HELD[0], HELD[1] + 1)}
    out = {'candidate': 'T-P1 player x surface offsets', 'grid': grid, 'chosen': best,
           'held_base_ll': round(float(nll(z[held]).mean()), 6), 'held_cand_ll': round(float((nll(z[held]) + dd).mean()), 6),
           'd_ll_1e4': round(float(dd.mean() * 1e4), 3), 't_by_tournament': round(t, 2), 'p1': p1,
           'seasons_better': f'{sum(v < 0 for v in by.values())}/{len(by)}', 'by_season_1e4': by,
           'n_held': int(n), 'clusters': len(cv)}
    print(out)
    json.dump(out, open(os.path.join(HERE, 'tennis_surface.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
