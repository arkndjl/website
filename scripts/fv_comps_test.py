#!/usr/bin/env python3
"""Player comps as an FV driver (Noah, Oct 30 2026): hockey (NHL draft picks), soccer and tennis prospects.

A comp term is the mean outcome FV of a prospect's nearest historical profiles (same position group), offered to each
board's kept model as one more input. Nothing is leaked: a row's comps never come from its own class/cohort, and in
every fold the held-out class's outcomes are out of the comp pool and the fit. Variants: k nearest (15/30/60), distance
weights equal on z-scored inputs or scaled by each input's base-model weight, and the comps' mean residual from the
kept model instead of their mean FV (the part a linear model misses).

    python3 scripts/fv_comps_test.py hockey     # -> scripts/.cache/comps/hockey.json
    python3 scripts/fv_comps_test.py soccer
    python3 scripts/fv_comps_test.py tennis

Gate per board (its own rule): fold-out MSE gain t >= 2 and 2/3 of folds won; the top of the board not worse; forward
(fit early, grade late) MSE not worse.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUTD = os.path.join(HERE, '.cache', 'comps')
KS = (15, 30, 60)
SIMPLE = '--simple' in sys.argv
STAGES = (1, 2, 3, 4) if '--stages' not in sys.argv else tuple(int(v) for v in sys.argv[sys.argv.index('--stages') + 1].split(','))
DRAFT = '--nodraft' not in sys.argv
ELIG = '--elig' in sys.argv


def ols(X, y, lam=1.0):
    X1 = np.column_stack([np.ones(len(X)), X])
    P = lam * np.eye(X1.shape[1]); P[0, 0] = 0
    return np.linalg.solve(X1.T @ X1 + P, X1.T @ y)


def pred(b, X):
    return b[0] + X @ b[1:]


L_NB = 240                          # neighbours kept per row: enough that k of them survive any one fold left out


def neighbours(Z, grp, fold, pool=None, L=L_NB):
    """each row's L nearest pool rows, nearest first (-1 pads): same group, never its own fold or player"""
    n = len(Z)
    pool = np.ones(n, bool) if pool is None else pool
    NB = np.full((n, L), -1, int)
    for g in np.unique(grp):
        qi = np.where(grp == g)[0]; pi = np.where((grp == g) & pool)[0]
        if len(pi) == 0:
            continue
        P = Zs_ = Z[pi]; pn = (P ** 2).sum(1); ll = min(L, len(pi))
        for s in range(0, len(qi), 1000):                       # blocks keep the distance matrix small
            q = qi[s:s + 1000]
            d = (Z[q] ** 2).sum(1)[:, None] + pn[None, :] - 2 * Z[q] @ P.T
            d[fold[q][:, None] == fold[pi][None, :]] = np.inf
            if PID is not None:
                d[PID[q][:, None] == PID[pi][None, :]] = np.inf
            nn = np.argpartition(d, ll - 1, axis=1)[:, :ll]
            dd = np.take_along_axis(d, nn, 1)
            o = np.argsort(dd, 1)
            nn, dd = np.take_along_axis(nn, o, 1), np.take_along_axis(dd, o, 1)
            NB[q, :ll] = np.where(np.isfinite(dd), pi[nn], -1)
    return NB


PID = None                          # player ids, when a player has several rows (soccer): never his own comp


def comp_mean(NB, v, k, fold=None, out_fold=None):
    """mean of v over each row's k nearest neighbours, skipping those in out_fold"""
    ok = NB >= 0
    if out_fold is not None:
        ok &= fold[np.maximum(NB, 0)] != out_fold
    use = ok & (np.cumsum(ok, 1) <= k)
    return (v[np.maximum(NB, 0)] * use).sum(1) / np.maximum(use.sum(1), 1)


def targets(y, fold, tr, base_X, resid):
    """what the comps carry: their outcome FV, or their residual from the kept model fit without their fold"""
    if not resid:
        return y
    vy = np.zeros(len(y))
    for f in np.unique(fold[tr]):
        m = tr & (fold == f); o = tr & (fold != f)
        vy[m] = y[m] - pred(ols(base_X[o], y[o]), base_X[m])
    return vy


def run_folds(X, y, fold, NB, k, resid, folds=None):
    """fold-out predictions of the kept model (base) and the kept model + comp term"""
    pb, pc = np.zeros(len(y)), np.zeros(len(y))
    for f in (folds if folds is not None else np.unique(fold)):
        te = fold == f; tr = ~te
        pb[te] = pred(ols(X[tr], y[tr]), X[te])
        c = comp_mean(NB, targets(y, fold, tr, X, resid), k, fold, f)
        Xc = np.column_stack([X, c])
        pc[te] = pred(ols(Xc[tr], y[tr]), Xc[te])
    return pb, pc


def forward(X, y, fold, NBf, k, resid, cut):
    tr, te = fold <= cut, fold > cut
    pb = pred(ols(X[tr], y[tr]), X[te])
    c = comp_mean(NBf, targets(y, fold, tr, X, resid), k)
    Xc = np.column_stack([X, c])
    pc = pred(ols(Xc[tr], y[tr]), Xc[te])
    return te, pb, pc


def gate_stats(y, fold, pb, pc, top, lo=20, hi=80):
    pb, pc = np.clip(pb, lo, hi), np.clip(pc, lo, hi)
    fs = np.unique(fold)
    d = np.array([np.mean((pb[fold == f] - y[fold == f]) ** 2) - np.mean((pc[fold == f] - y[fold == f]) ** 2) for f in fs])
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std() > 0 else 0.0
    out = {'gain': round(float(d.mean()), 3), 't': round(float(t), 2), 'wins': int((d > 0).sum()), 'of': len(d),
           'mse': round(float(np.mean((pc - y) ** 2)), 3), 'mseBase': round(float(np.mean((pb - y) ** 2)), 3)}
    out['topGain'] = round(float(np.mean((pb[top] - y[top]) ** 2) - np.mean((pc[top] - y[top]) ** 2)), 3)
    return out


def weights_from(X, y, cols, zcols):
    """distance weight per comp input: |base-model coefficient| x the input's SD, normalised to mean 1"""
    b = ols(X, y)
    w = np.array([abs(b[1 + cols.index(c)]) * X[:, cols.index(c)].std() if c in cols else 0.0 for c in zcols])
    w = np.where(w > 0, w, w[w > 0].mean() * .25 if (w > 0).any() else 1.0)
    return w / w.mean()


def sweep(name, X, y, fold, Zraw, zcols, grp, top_of, fwd_cut, extra_X=None, cols=None, folds=None, fwd_fold=None):
    """every variant: k x weighting x target"""
    Zs = (Zraw - Zraw.mean(0)) / np.where(Zraw.std(0) > 0, Zraw.std(0), 1)
    W = {'eq': np.ones(len(zcols))}
    if cols is not None and extra_X is not None:
        W['coef'] = weights_from(extra_X, y, cols, zcols)
    res = {}
    for wn, w in W.items():
        Z = Zs * np.sqrt(w)
        ff = fold if fwd_fold is None else fwd_fold
        NB, NBf = neighbours(Z, grp, fold), neighbours(Z, grp, ff, ff <= fwd_cut)
        for resid in (False, True):
            for k in KS:
                key = f'{wn}/{"resid" if resid else "fv"}/k{k}'
                pb, pc = run_folds(X, y, fold, NB, k, resid, folds)
                top = top_of(pb)
                g = gate_stats(y, fold, pb, pc, top)
                te, fb, fc = forward(X, y, ff, NBf, k, resid, fwd_cut)
                ft = top_of(fb, te)
                fb, fc = np.clip(fb, 20, 80), np.clip(fc, 20, 80)
                g['fwd'] = round(float(np.mean((fb - y[te]) ** 2) - np.mean((fc - y[te]) ** 2)), 3)
                g['fwdTop'] = round(float(np.mean((fb[ft] - y[te][ft]) ** 2) - np.mean((fc[ft] - y[te][ft]) ** 2)), 3)
                g['pass'] = bool(g['t'] >= 2 and g['wins'] >= math.ceil(g['of'] * 2 / 3) and g['topGain'] >= 0
                                 and g['fwd'] >= 0 and g['fwdTop'] >= 0)
                res[key] = g
                print(name, key, g, flush=True)
    if 'coef' in W:
        res['_weights'] = dict(zip(zcols, [round(float(v), 3) for v in W['coef']]))
    return res


# ------------------------------------------------------------------------------------------------ hockey
def hockey():
    import hockey_prospects as H
    W = H.war_tables(); rows = H.read_rows(W); H.nhl_so_far(rows, W)
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr])
    F = [H.feats(r) for r in tr]
    fit = json.load(open(H.FIT))
    babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
    S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
    kept = fit['kept']
    X = np.array([[f[c] for c in kept] for f in F])
    # comp space: what a scout compares at the draft (slot, scoring level, age, size, league type, growth)
    zc = ['ls', 'nhle', 'age', 'ht', 'wt', 'chl', 'ncaa', 'epro', 'grow', 'gsh']
    Zraw = np.array([[f[c] for c in zc] for f in F])
    grp = np.array([2 if r['G'] else (1 if r['D'] else 0) for r in tr])
    allc = sorted(set(zc) | set(kept))
    XA = np.array([[f[c] for c in allc] for f in F])
    picks = np.array([r['pick'] for r in tr])

    def top_of(p, te=None):
        return (picks <= 64) if te is None else (picks[te] <= 64)

    out = {'draft': sweep('hockey draft', X, y, cls, Zraw, zc, grp, top_of, 2015, XA, allc)} if DRAFT else {}
    # post-draft stages 1-2: comps on the stage inputs (the draft grade, NHLe that season, pro games, WJC)
    p0 = H.score(F, y, cls, kept)[1]
    oof = {id(r): float(p) for r, p in zip(tr, p0)}
    for k in STAGES:
        idx = [i for i, r in enumerate(tr) if r['year'] + k < H.D.current_season()
               and (not ELIG or r['gp_k'].get(k, 0) < (50 if r['G'] else 100))]   # still on the board (not graduated)
        sub = [tr[i] for i in idx]
        Fk = [H.stage_feats(r, k, oof[id(r)]) for r in sub]
        kk = fit['stages'][str(k)]['kept']
        Fk2 = []
        for f, r in zip(Fk, sub):
            f = dict(f); x = (r.get('px') or {}).get(k) or {}
            f['ahls'] = 0.0 if r['G'] or x.get('ahls') is None else x['ahls']
            wl = sorted(r['war_k'].get(k, []), reverse=True)
            f['nany'] = int(r['gp_k'].get(k, 0) > 0)              # any NHL game: the outcome's 30+ floor is set
            f['wpk'] = sum((wl + [0, 0, 0])[:3]) / 3                # the outcome's peak so far (top 3 seasons / 3)
            Fk2.append(f)
        if SIMPLE:
            kk = kk + ['nany', 'wpk']
        Xk = np.array([[f[c] for c in kk] for f in Fk2])
        zk = ['fv0', 'nh', 'nh_na', 'pro', 'progp', 'wjc', 'gp', 'war', 'age'] + (['nany'] if SIMPLE else [])
        Zk = np.array([[f[c] for c in zk] for f in Fk2])
        yk, ck = y[idx], cls[idx]; gk = grp[idx]; pk = picks[idx]
        allk = sorted(set(zk) | set(kk))
        XAk = np.array([[f[c] for c in allk] for f in Fk2])

        def top_k(p, te=None, pk=pk):
            return (pk <= 64) if te is None else (pk[te] <= 64)
        out[f'stage{k}'] = sweep(f'hockey k{k}', Xk, yk, ck, Zk, zk, gk, top_k, 2015, XAk, allk)
    return out


# ------------------------------------------------------------------------------------------------ soccer
def soccer():
    global PID
    import pandas as pd
    import soccer_prospects as SP
    fn = os.path.join(OUTD, 'soccer_rows.pkl')
    if os.path.exists(fn):
        S = pd.read_pickle(fn)
    else:                                  # the board's October rows, built as SP.fit builds them
        G, A, P, V = SP.load()
        R = SP.club_ratings(G, A, V); A = SP.add_value(A, R)
        O, scale = SP.outcome(A, P); TG = SP.team_games(G)
        done = O[O.s22 <= SP.COHORTS[1]]
        xs = []
        for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
            X = SP.features(A, P, V, R, TG, t, SP.snapdate(t, SP.SEL_SNAP))
            X['mvlvl'] = SP.mv_level(X.mv)
            X = X[X.index.isin(done.index)]
            X['fv_out'] = done.fv.reindex(X.index); X['s22'] = done.s22.reindex(X.index)
            xs.append(X.reset_index().rename(columns={'index': 'player_id'}))
        S = pd.concat(xs, ignore_index=True)
        ref = S.groupby('t').mvlvl.first().mean()
        S['mvd'] = S.mv * np.exp(ref - S.mvlvl)
        S.to_pickle(fn)
    F = SP.design(S)
    fit = json.load(open(SP.FIT))
    kept = list(fit['models']['%02d-%02d' % SP.SEL_SNAP]['coef'])[1:]
    y, t, co = S.fv_out.values.astype(float), S.t.values, S.s22.values
    PID = S.player_id.values
    zc = ['age', 'lmv', 'nomv', 'share1', 'rclub1', 'share_td', 'lg_share', 'ga90_1', 'ga90_td', 'emins', 'ymins', 'ht',
          'tier2', 'noseen']
    X = F[kept].values.astype(float)
    Zraw = F[zc].values.astype(float)
    grp = S.grp.map({'G': 0, 'D': 1, 'M': 2, 'F': 3}).fillna(2).values.astype(int)
    allc = sorted(set(zc) | set(kept))
    XA = F[allc].values.astype(float)
    tt = t

    def top_of(p, te=None):                 # each season's top 50 by the base grade
        tv = tt if te is None else tt[te]
        m = np.zeros(len(p), bool)
        for s in np.unique(tv):
            i = np.where(tv == s)[0]
            m[i[np.argsort(-p[i])[:50]]] = True
        return m
    print('soccer rows', len(y), 'kept', kept, flush=True)
    # cohort folds (a player's every row out together) for the gate; the forward test is by season with the player's
    # own rows kept out of his comps (PID)
    out = {'cohort': sweep('soccer', X, y, co, Zraw, zc, grp, top_of, 2017, XA, allc, fwd_fold=t)}
    out['_n'] = int(len(y))
    return out


# ------------------------------------------------------------------------------------------------ tennis
def tennis():
    import pickle
    import pandas as pd
    import tennis_prospects as T
    rows = pickle.load(open(T.ROWS, 'rb'))
    fit = json.load(open(T.FIT))
    snap = '%02d-%02d' % T.SEL_SNAP
    zc = ['age', 'lr', 'unr', 'elo', 'lelon', 'wpall', 'first', 'lnS', 'lnQ', 'lnC', 'lnT', 'dr', 'delo']
    out = {}
    for tour in T.TOURS:
        X, F, y, pos, by = T.snap_rows(rows, tour, snap)
        kept = fit[tour]['kept']
        season = X.season.values
        Zraw = F[zc].values.astype(float)
        Zs = (Zraw - Zraw.mean(0)) / np.where(Zraw.std(0) > 0, Zraw.std(0), 1)
        XA = F[sorted(set(zc) | set(kept))].values.astype(float)
        Wt = {'eq': np.ones(len(zc)), 'coef': weights_from(XA, y, sorted(set(zc) | set(kept)), zc)}
        grp = np.zeros(len(y), int)
        Xk = F[kept].values.astype(float)

        def hfit(c, tr, te):
            F2 = F[kept].copy()
            F2['comp'] = c
            bl, bo = T.hurdle(F2, y, pos, kept + ['comp'], tr)
            p, mu = T.hpred(F2[te], kept + ['comp'], bl, bo)
            return (1 - p) * 20 + p * mu

        _, _, Eb = T.loso(F, y, pos, by, kept)
        bl, bo = T.hurdle(F, y, pos, kept, by <= T.FWD)
        p, mu = T.hpred(F[by > T.FWD], kept, bl, bo); fb = (1 - p) * 20 + p * mu

        def top50(E, m=None):
            m = np.ones(len(y), bool) if m is None else m
            o = np.argsort(-E)
            return float(pd.Series(y[m][o]).groupby(season[m][o]).head(50).mean())
        res = {}
        for wn, w in Wt.items():
            Z = Zs * np.sqrt(w)
            NB, NBf = neighbours(Z, grp, by), neighbours(Z, grp, by, by <= T.FWD)
            for resid in (False, True):
                for k in KS:
                    key = f'{wn}/{"resid" if resid else "fv"}/k{k}'
                    Ec = np.zeros(len(y))
                    for b in np.unique(by):
                        te = by == b; tr = ~te
                        c = comp_mean(NB, targets(y, by, tr, Xk, resid), k, by, b)
                        Ec[te] = hfit(c, tr, te)
                    m0, m1 = T.fold_mse(Eb, y, by), T.fold_mse(Ec, y, by)
                    g = T.gate(m0, m1)
                    g['mse'], g['mseBase'] = round(float(np.mean((Ec - y) ** 2)), 3), round(float(np.mean((Eb - y) ** 2)), 3)
                    g['top50'], g['top50Base'] = round(top50(Ec), 3), round(top50(Eb), 3)
                    tr, te = by <= T.FWD, by > T.FWD
                    c = comp_mean(NBf, targets(y, by, tr, Xk, resid), k)
                    fc = hfit(c, tr, te)
                    g['fwd'] = round(float(np.mean((fb - y[te]) ** 2) - np.mean((fc - y[te]) ** 2)), 3)
                    g['fwdTop50'] = [round(top50(fc, te), 3), round(top50(fb, te), 3)]
                    g['pass'] = bool(g['t'] >= 2 and g['wins'] >= math.ceil(g['of'] * 2 / 3) and g['top50'] >= g['top50Base']
                                     and g['fwd'] >= 0 and g['fwdTop50'][0] >= g['fwdTop50'][1])
                    res[key] = g
                    print(tour, key, g, flush=True)
        res['_weights'] = dict(zip(zc, [round(float(v), 3) for v in Wt['coef']]))
        res['_n'] = int(len(y))
        out[tour] = res
    return out


if __name__ == '__main__':
    os.makedirs(OUTD, exist_ok=True)
    which = sys.argv[1]
    res = globals()[which]()
    tag = ('-simple' if SIMPLE else '') + ('-elig' if ELIG else '')
    json.dump(res, open(os.path.join(OUTD, f'{which}{tag}.json'), 'w'), indent=1)
