# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""prereg T1/T2 (TD: train on unfinished cohorts, as-of walk-forward) and T3/T4 (gbm stack), October snapshot"""
import sys, os, json, math, pickle
sys.path.insert(0, '/home/user/website/scripts')
import numpy as np, pandas as pd
from scipy import stats
import tennis_prospects as T
from sklearn.ensemble import HistGradientBoostingRegressor as GB

rows = pickle.load(open(T.ROWS, 'rb')); B = T.base()
fit = json.load(open('/home/user/website/data/tennis_prospects_fit.json'))
snap = os.environ.get('SNAP', '%02d-%02d' % T.SEL_SNAP); PARTS = os.environ.get('PARTS', 'ab')
OUT = {}
which = sys.argv[1] if len(sys.argv) > 1 else 'all'


def tt(g):
    g = np.asarray(g, float); t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))
    return round(float(t), 2), round(float(stats.t.sf(t, len(g) - 1)), 4)


def flogit(X, y, w=None, l2=1e-3, it=60):
    w = np.ones(len(y)) if w is None else w
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        Hm = X.T @ (X * (w * p * (1 - p) + 1e-9)[:, None]) + l2 * np.eye(len(b))
        d = np.linalg.solve(Hm, X.T @ (w * (y - p)) - l2 * b); b += d
        if np.abs(d).max() < 1e-8: break
    return b


def wols(X, y, w):
    sw = np.sqrt(w); return np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]


def sig(z): return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


for tour in T.TOURS:
    kept = fit[tour]['kept']; sc = T.scale(B, tour)
    # ---------------- T3/T4 gbm
    if which in ('all', 'gbm'):
        X, F, y, pos, by = T.snap_rows(rows, tour, snap); season = X.season.values
        gc = [c for c in F.columns if c not in T.LEAKS + ['lefty'] + os.environ.get('EXCL', '').split(',')]
        G = F[gc].values
        p0 = T.loso(F, y, pos, by, kept)[2]; pg = np.zeros(len(y))
        mk = lambda: GB(max_depth=3, learning_rate=.05, max_iter=300, min_samples_leaf=40, l2_regularization=1.0, random_state=0)
        for b in np.unique(by):
            te = by == b; pg[te] = np.clip(mk().fit(G[~te], y[~te]).predict(G[te]), 20, 80)
        p1 = .5 * p0 + .5 * pg
        g = T.fold_mse(p0, y, by) - T.fold_mse(p1, y, by)
        t50 = lambda p, m=slice(None): float(pd.Series(y[m][np.argsort(-p[m])]).groupby(season[m][np.argsort(-p[m])]).head(50).mean())
        tr, te = by <= T.FWD, by > T.FWD
        bl, bo = T.hurdle(F, y, pos, kept, tr); pp, mu = T.hpred(F[te], kept, bl, bo); f0 = (1 - pp) * 20 + pp * mu
        f1 = .5 * f0 + .5 * np.clip(mk().fit(G[tr], y[tr]).predict(G[te]), 20, 80)
        yt, st = y[te], season[te]
        ft = lambda p: float(pd.Series(yt[np.argsort(-p)]).groupby(st[np.argsort(-p)]).head(50).mean())
        t, p = tt(g)
        OUT['gbm_' + tour] = dict(mse=[round(float(np.mean((p0 - y) ** 2)), 3), round(float(np.mean((p1 - y) ** 2)), 3)], gain=round(float(g.mean()), 3), t=t, p=p,
                                  wins=int((g > 0).sum()), of=len(g), top50=[round(t50(p0), 2), round(t50(p1), 2)],
                                  fwd=[round(float(np.mean((f0 - yt) ** 2)), 3), round(float(np.mean((f1 - yt) ** 2)), 3)], fwd_top50=[round(ft(f0), 2), round(ft(f1), 2)],
                                  gbm_alone=round(float(np.mean((pg - y) ** 2)), 3))
        print(tour, 'gbm', OUT['gbm_' + tour], flush=True)
    # ---------------- T1/T2 td
    if which in ('all', 'td'):
        R = rows[tour]; R = R[(R.snap == snap) & (R.by >= T.COHORTS[0])].reset_index(drop=True)
        F = T.design(R); Xa = np.column_stack([np.ones(len(F)), F[kept].values])
        P = B[tour]['P']; S = B[tour]['S'].join(P[['dobd']], on='pid'); S = S[S.dobd.notna()].copy()
        S['ai'] = np.floor((pd.to_datetime(S.y.astype(str) + '-07-01') - S.dobd).dt.days / 365.25).astype(int)
        Wn = S[(S.ai >= 22) & (S.ai <= 28)][['pid', 'y', 'ts', 'ai']]
        dob = P.dobd.reindex(R.pid.unique())
        jul = pd.to_datetime(dob.dt.year.astype(int).astype(str) + '-07-01')
        y22 = (dob.dt.year + 22 + (dob > jul).astype(int)).astype(int)          # first season with age 22 on July 1
        pid = R.pid.values; seas = R.season.values; by = R.by.values
        yfull = T.fv_rarity(R.pk.values, sc)

        def pk_upto(last, m=None):
            """best-3 mean over window seasons <= last (and, with m, only the first m window seasons)"""
            w = Wn[Wn.y <= last]
            if m is not None: w = w[w.ai <= 21 + m]
            return w.groupby('pid').ts.apply(lambda s: np.sort(s.values)[::-1][:3].sum() / 3)

        res = []
        for N in range(2011, 2019):
            te = (seas == N) & (by <= T.COHORTS[1])
            fin = (by <= N - 29) & (seas < N)
            ypk = pd.Series(pid).map(pk_upto(N - 1)).fillna(0).values          # outcome as known at N-1
            yN = T.fv_rarity(ypk, sc); posN = ypk > 0
            bl = flogit(Xa[fin], posN[fin].astype(float)); bo = wols(Xa[fin], yN[fin], posN[fin].astype(float))
            base_pred = lambda m: (1 - sig(Xa[m] @ bl)) * 20 + sig(Xa[m] @ bl) * (Xa[m] @ bo)
            p0 = base_pred(te)
            gr = (1 - sig(Xa @ bl)) * 20 + sig(Xa @ bl) * (Xa @ bo)           # base-arm grade of every row
            D = pd.DataFrame({'pid': pid, 'seas': seas, 'by': by, 'gr': gr, 'i': np.arange(len(pid))})
            D['y22'] = D.pid.map(y22).values
            D['m'] = np.clip(N - D.y22, 0, 7)                                  # seen window seasons at N-1
            hist = D[D.seas < N]
            lastrow = hist.sort_values('seas').groupby('pid').tail(1).set_index('pid')
            tp = np.full(len(pid), np.nan); tm = np.full(len(pid), np.nan)
            # (a) aged out, 1..6 seen seasons: imputation fit per m on finished players
            finp = lastrow[lastrow.by <= N - 29]
            for m in range(1, 7):
                part = T.fv_rarity(finp.index.map(pk_upto(N - 1, m)).fillna(0).values if len(finp) else [], sc)
                yy = yN[finp.i.values]; pp_ = posN[finp.i.values]; anyv = part > 20; g_ = finp.gr.values
                A0 = np.column_stack([np.ones((~anyv).sum()), g_[~anyv]])
                b0 = flogit(A0, pp_[~anyv].astype(float))
                k = ~anyv & pp_
                c0 = np.linalg.lstsq(np.column_stack([np.ones(k.sum()), g_[k]]), yy[k], rcond=None)[0] if k.sum() > 20 else np.array([yy[k].mean() if k.any() else 25.0, 0.0])
                c1 = np.linalg.lstsq(np.column_stack([np.ones(anyv.sum()), part[anyv], g_[anyv]]), yy[anyv], rcond=None)[0]
                tg = lastrow[(lastrow.m == m) & (lastrow.by > N - 29)]
                if not len(tg): continue
                pt = T.fv_rarity(tg.index.map(pk_upto(N - 1)).fillna(0).values, sc); av = pt > 20
                Pm = np.where(av, 1.0, sig(c := (b0[0] + b0[1] * tg.gr.values)))
                Mm = np.where(av, c1[0] + c1[1] * pt + c1[2] * tg.gr.values, c0[0] + c0[1] * tg.gr.values)
                mp = dict(zip(tg.index, zip(Pm, np.clip(Mm, 20, 80))))
                for i_, q in zip(hist.i.values, hist.pid.values):
                    if q in mp: tp[i_], tm[i_] = mp[q]
            # (b) still under 22 at N-1 (m == 0): target = base grade parts on his season N-1 row; no N-1 row -> the
            # finished players' record after the same kind of gap
            young = lastrow[(lastrow.m == 0) & (lastrow.by > N - 29)]
            has = young[young.seas == N - 1]; gone = young[young.seas < N - 1]
            hp = sig(Xa[has.i.values] @ bl); hm = Xa[has.i.values] @ bo
            mp = dict(zip(has.index, zip(hp, np.clip(hm, 20, 80))))
            fh = D[(D.by <= N - 29) & (D.seas < N)]
            fl = fh.sort_values('seas').groupby('pid').tail(1)
            fl = fl[fl.seas < fl.y22 - 1]                                      # finished players whose last board row came before their last eligible season
            gp_ = posN[fl.i.values].mean() if len(fl) else 0.0
            gm_ = yN[fl.i.values][posN[fl.i.values]].mean() if len(fl) and posN[fl.i.values].any() else 25.0
            for q in gone.index: mp[q] = (gp_, gm_)
            for i_, q, s_ in zip(hist.i.values, hist.pid.values, hist.seas.values):
                if q in mp and not (q in has.index and s_ == N - 1): tp[i_], tm[i_] = mp[q]
            isa = pd.Series(pid).map(D.groupby('pid').m.first()).values > 0
            td = ~np.isnan(tp) & (seas < N) & ~fin & (isa if PARTS == 'a' else ~isa if PARTS == 'b' else True)
            a = fin | td
            yl = np.where(fin, posN.astype(float), tp); ym = np.where(fin, yN, tm); wm = np.where(fin, posN.astype(float), tp)
            bl1 = flogit(Xa[a], yl[a]); bo1 = wols(Xa[a], ym[a], wm[a] + 1e-9)
            p1 = (1 - sig(Xa[te] @ bl1)) * 20 + sig(Xa[te] @ bl1) * (Xa[te] @ bo1)
            yt = yfull[te]
            if os.environ.get('JOINT'):
                gc = [c for c in F.columns if c not in T.LEAKS + ['lefty'] + os.environ.get('EXCL', '').split(',')]
                gm = GB(max_depth=3, learning_rate=.05, max_iter=300, min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(F[gc].values[a if os.environ.get('JOINT') == 'td' else fin], (np.where(fin, yN, (1 - np.nan_to_num(tp)) * 20 + np.nan_to_num(tp) * np.nan_to_num(tm)))[a if os.environ.get('JOINT') == 'td' else fin])
                p0 = p1; p1 = .5 * p1 + .5 * np.clip(gm.predict(F[gc].values[te]), 20, 80)
            top = lambda p: float(yt[np.argsort(-p)[:50]].mean())
            res.append(dict(b0=float(np.mean(p0 - yt)), b1=float(np.mean(p1 - yt)), N=N, n=int(te.sum()), nfin=int(fin.sum()), ntd=int(td.sum()), mse0=float(np.mean((p0 - yt) ** 2)), mse1=float(np.mean((p1 - yt) ** 2)),
                            top0=top(p0), top1=top(p1), e0=((p0 - yt) ** 2), e1=((p1 - yt) ** 2), pid=pid[te]))
            print(tour, N, 'n', te.sum(), 'fin', fin.sum(), 'td', td.sum(), 'mse', round(res[-1]['mse0'], 3), round(res[-1]['mse1'], 3), 'top50', round(res[-1]['top0'], 2), round(res[-1]['top1'], 2), flush=True)
        g = np.array([r['mse0'] - r['mse1'] for r in res]); t, p = tt(g); t3, p3 = tt(g[-3:])
        dd = pd.DataFrame({'pid': np.concatenate([r['pid'] for r in res]), 'd': np.concatenate([r['e0'] - r['e1'] for r in res])}).groupby('pid').d.sum()
        tc = float(dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd))))
        OUT['td_' + tour] = dict(gain=round(float(g.mean()), 3), t=t, p=p, wins=int((g > 0).sum()), of=len(g), mse=[round(float(np.mean([r['mse0'] for r in res])), 3), round(float(np.mean([r['mse1'] for r in res])), 3)],
                                 top50=[round(float(np.mean([r['top0'] for r in res])), 2), round(float(np.mean([r['top1'] for r in res])), 2)],
                                 last3=dict(gain=round(float(g[-3:].mean()), 3), t=t3), t_player=round(tc, 2),
                                 bias=[round(float(np.mean([r['b0'] for r in res])), 3), round(float(np.mean([r['b1'] for r in res])), 3)], seasons=[dict(N=r['N'], n=r['n'], nfin=r['nfin'], ntd=r['ntd'], mse0=round(r['mse0'], 3), mse1=round(r['mse1'], 3), top0=round(r['top0'], 2), top1=round(r['top1'], 2)) for r in res])
        print(tour, 'td', {k: v for k, v in OUT['td_' + tour].items() if k != 'seasons'}, flush=True)
json.dump(OUT, open(f'/mnt/project-files/fv/sweep-nov09/tennis_{which}' + ('' if snap == '10-26' and PARTS == 'ab' else f'_{snap}_{PARTS}') + ('_live' if os.environ.get('EXCL') else '') + ('_joint' + os.environ.get('JOINT', '') if os.environ.get('JOINT') else '') + '.json', 'w'), indent=1)
