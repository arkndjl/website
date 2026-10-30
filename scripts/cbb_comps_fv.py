#!/usr/bin/env python3
"""Do historical comps add to the CBB board's FV model? (research, Oct 30 2026)

    python3 scripts/cbb_careers_kit.py
    python3 scripts/cbb_comps_fv.py [tune|test]      # -> data/cbb_comps_fv.json

A comp is the nearest earlier board row (another player) on a weighted z-score profile, as on the CFB board
(scripts/cfb_comps.py): production, style rates, age, height, pedigree, context. The candidate driver is the comps'
mean realized FV (K nearest, shrunk toward the pool mean), entered next to the shipped drivers (data/cbb_fit.json).
Leak guard: a row's comps never include the player himself, and in each test the comp pool holds only the rows the
model is fit on (out-of-fold class folds; forward: the 2009-16 boards grade the 2017-19 boards).
Gates (as cbb_fv_core.add_test): class-fold deviance gain, class-clustered t, folds better, top 30 per board; then
forward on the held-out 2017-19 boards (common-horizon outcome): deviance, top-300 corr, top 50.

Results (Oct 30 2026), nothing shipped:
  returners, comp mean FV (prod 3, age 3, pedigree 1, size .5, context .5, style 0; K 100; comp-only corr .53):
    class folds +0.10%, t 0.6, 3/5, top 30 37.35 -> 37.67; forward t 0.9, top 50 +0.6..+1.2 on 3/3, corr300 1/3
  returners, comps' 45+ share (COMP_Y=top): class folds t 0.45, 2/5; forward t 0.76
  newcomers (rank, services, height, class; K 100): class folds -0.23%, t -2.1, 0/5; forward t 1.4, top 50 flat
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
import cbb_fv_core as C
import harness as H

COMP_Y = os.environ.get('COMP_Y', 'fv')          # what the comps' mix averages: fv, top (45+ share), nba (30+ share)
FIXED = json.loads(os.environ['COMP_W']) if os.environ.get('COMP_W') else None   # {grp: [weights, K]} skips the tuning
ONLY = os.environ.get('COMP_GRP')
OUT = os.path.join(D.ROOT, 'data', f'cbb_comps_fv_{COMP_Y}.json')
# profile groups (each feature z-scored on the pool, clipped at 4 SD, missing = 0)
GROUPS = {
    'returner': {
        'prod': ['bpm', 'obpm', 'dbpm', 'bpm3', 'porpag', 'dporpag'],
        'style': ['usg', 'ast', 'to', 'stl', 'blk', 'orb', 'drb', 'ft', 'tp', 'tpa100', 'ftr', 'rim'],
        'age': ['age', 'nprev'],
        'size': ['ht', 'ht_g', 'big', 'guard'],
        'ped': ['rg_lrk'],
        'ctx': ['power', 'min_per'],
    },
    'newcomer': {
        'ped': ['rg_lrk', 'top', 'top5'],
        'svc': ['on3', 'r247', 'btrec'],
        'size': ['ht'],
        'age': ['yr'],
    },
}


def zmat(rows, cols, ref=None):
    X = F.matrix(rows, cols)
    R = X if ref is None else ref
    mu = np.nanmean(R, 0); sd = np.nanstd(R, 0); sd[~(sd > 0)] = 1
    Z = np.clip((X - mu) / sd, -4, 4)
    return np.nan_to_num(Z), (mu, sd)


def profile(rows, grp, w, ref_rows):
    cols, wv = [], []
    for g, ks in GROUPS[grp].items():
        if not w.get(g): continue
        cols += ks; wv += [w[g] / np.sqrt(len(ks))] * len(ks)
    _, (mu, sd) = zmat(ref_rows, cols)
    X = F.matrix(rows, cols)
    Z = np.nan_to_num(np.clip((X - mu) / sd, -4, 4))
    return Z * np.array(wv)


def comp_feat(q_rows, p_rows, grp, w, K, m=10):
    """for each query row: mean realized FV of its K nearest pool rows (other players), shrunk to the pool mean with m"""
    Zp = profile(p_rows, grp, w, p_rows); Zq = profile(q_rows, grp, w, p_rows)
    yp = np.array([r['y'] for r in p_rows], float)
    if COMP_Y == 'top': yp = (yp >= 45).astype(float)
    elif COMP_Y == 'nba': yp = (yp >= 30).astype(float)
    y0 = yp.mean()
    pid_p = np.array([hash(r['pid']) for r in p_rows]); pid_q = np.array([hash(r['pid']) for r in q_rows])
    out = np.zeros(len(q_rows)); pn = (Zp ** 2).sum(1)
    for a in range(0, len(q_rows), 1500):
        zq = Zq[a:a + 1500]
        d = (zq ** 2).sum(1)[:, None] + pn[None, :] - 2 * zq @ Zp.T
        d[pid_q[a:a + 1500, None] == pid_p[None, :]] = np.inf
        ix = np.argpartition(d, K, 1)[:, :K]
        out[a:a + 1500] = (yp[ix].sum(1) + m * y0) / (K + m)
    return out


def set_cand(rows, v):
    for r, x in zip(rows, v): r['f']['comp'] = float(x)


def oof_comp(rows, kept, lam, folds, grp, w, K, with_comp=True):
    """class-fold out-of-fold rung probabilities; the comp pool in each fold = the fold's training rows"""
    cols = kept + (['comp'] if with_comp else [])
    P = np.zeros((len(rows), len(F.LADDER)))
    for k in sorted(set(folds)):
        tr = [r for r, f in zip(rows, folds) if f != k]; te = [r for r, f in zip(rows, folds) if f == k]
        if with_comp:
            set_cand(tr, comp_feat(tr, tr, grp, w, K)); set_cand(te, comp_feat(te, tr, grp, w, K))
        Xtr, Xte = F.matrix(tr, cols), F.matrix(te, cols)
        P[folds == k] = F.predict(F.fit(tr, Xtr, list(range(len(cols))), lam), Xte)[1]
    return P


def comp_only_dev(rows, folds, grp, w, K):
    """comp-mix fit on its own: class-fold out-of-fold MSE of the comp mean against the outcome (weight tuning)"""
    y = np.array([r['y'] for r in rows], float); e = np.zeros(len(rows))
    for k in sorted(set(folds)):
        tr = [r for r, f in zip(rows, folds) if f != k]; te = [r for r, f in zip(rows, folds) if f == k]
        e[folds == k] = comp_feat(te, tr, grp, w, K)
    return float(((e - y) ** 2).mean()), float(np.corrcoef(e, y)[0, 1])


def top_board(P, rows, y, N):
    e = F.expected(P); yrs = np.array([r['year'] for r in rows])
    return float(np.mean([y[np.where(yrs == b)[0][np.argsort(-e[yrs == b])[:N]]].mean() for b in sorted(set(yrs))]))


def main(mode='test'):
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    careers, rows, sc = C.load(range(2009, 2020))
    res = {}
    for grp in ('returner', 'newcomer'):
        if ONLY and grp != ONLY: continue
        m = fit['models'][grp]; kept, lam = m['kept'], m['lam']
        g = [r for r in rows if r['f']['newcomer'] == (grp == 'newcomer')]
        tr = [dict(r, y=r['yfull']) for r in g if r['year'] <= 2016 and r['last'] <= 2020]
        for r in tr: r['f'] = dict(r['f'])
        folds = np.array([C.class_fold(r['last']) for r in tr])
        # weight tuning on the comp mix alone (coordinate descent over group weights, then K), 2009-16 boards only
        w = {k: 1.0 for k in GROUPS[grp]}; K = 50
        if FIXED and grp in FIXED: w, K = FIXED[grp]
        best = comp_only_dev(tr, folds, grp, w, K)
        print(grp, len(tr), 'rows; comp-only start', best, flush=True)
        for _ in range(0 if FIXED and grp in FIXED else 2):
            for k in GROUPS[grp]:
                for v in (0.0, 0.5, 2.0, 3.0):
                    w2 = dict(w, **{k: v})
                    if not any(w2.values()): continue
                    s = comp_only_dev(tr, folds, grp, w2, K)
                    if s[0] < best[0] - 1e-4: best, w = s, w2
            print('  weights', w, best, flush=True)
        for K2 in (() if FIXED and grp in FIXED else (25, 100, 200)):
            s = comp_only_dev(tr, folds, grp, w, K2)
            if s[0] < best[0] - 1e-4: best, K = s, K2
        print('  K', K, best, flush=True)
        y = np.array([r['y'] for r in tr], float)
        Pb = oof_comp(tr, kept, lam, folds, grp, w, K, False); Pc = oof_comp(tr, kept, lam, folds, grp, w, K, True)
        db, dc = C.row_dev(Pb, y).sum(1), C.row_dev(Pc, y).sum(1)
        pt = H.paired(dc, db, np.array([r['last'] for r in tr]))
        fb = sum(1 for k in set(folds) if dc[folds == k].sum() < db[folds == k].sum())
        r1 = {'weights': w, 'K': K, 'comp_only_mse_corr': best, 'gain_pct': round((db.sum() - dc.sum()) * 100, 3), 't': round(-pt['t'], 2),
              'folds': f'{fb}/5', 'top30_base': round(top_board(Pb, tr, y, 30), 2), 'top30_comp': round(top_board(Pc, tr, y, 30), 2),
              'top10_base': round(top_board(Pb, tr, y, 10), 2), 'top10_comp': round(top_board(Pc, tr, y, 10), 2)}
        print('  class folds 2009-16:', r1, flush=True)
        # forward: fit on 2009-16, grade the 2017-19 boards on the common-horizon outcome
        te = [dict(r, y=r['yk']) for r in g if 2017 <= r['year'] <= 2019 and r['yk'] is not None]
        for r in te: r['f'] = dict(r['f'])
        set_cand(tr, comp_feat(tr, tr, grp, w, K)); set_cand(te, comp_feat(te, tr, grp, w, K))
        yt = np.array([r['y'] for r in te], float)
        out = {}
        for nm, cols in (('base', kept), ('comp', kept + ['comp'])):
            P = F.predict(F.fit(tr, F.matrix(tr, cols), list(range(len(cols))), lam), F.matrix(te, cols))[1]
            e = F.expected(P); bs = []
            for b in (2017, 2018, 2019):
                ix = np.array([r['year'] == b for r in te]); o = np.argsort(-e[ix])
                bs.append((float(np.corrcoef(e[ix][o[:300]], yt[ix][o[:300]])[0, 1]), float(yt[ix][o[:50]].mean())))
            out[nm] = {'P': P, 'dev': C.row_dev(P, yt).sum(1), 'boards': bs}
        pt = H.paired(out['comp']['dev'], out['base']['dev'], np.array([r['pid'] for r in te]))
        r2 = {'gain_pct': round((out['base']['dev'].sum() - out['comp']['dev'].sum()) * 100, 3), 't': round(-pt['t'], 2),
              'corr300': [[round(a[0], 3), round(b[0], 3)] for a, b in zip(out['base']['boards'], out['comp']['boards'])],
              'top50': [[round(a[1], 2), round(b[1], 2)] for a, b in zip(out['base']['boards'], out['comp']['boards'])]}
        print('  forward 2017-19 (base, comp):', r2, flush=True)
        res[grp] = {'class_folds': r1, 'forward': r2}
    json.dump(res, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main(*(sys.argv[1:2] or ['test']))
