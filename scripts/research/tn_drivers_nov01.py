"""FV sweep Nov 1 2026, tennis prospects: constructed proxies (serve/return dominance, luck-stripped results, surface
versatility, quality of wins, durability, own extras) on top of the kept model, every snapshot.

Usage: python3 scripts/research/tn_drivers_nov01.py [comma list of inputs] [out.json]
Needs scripts/.cache/tennis/{base.pkl,rows.pkl} (tennis_prospects.py --download, then --rows).
Every input uses only matches whose event week is over at the snapshot (event date <= D - 7 days), like features()."""
import json, os, pickle, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tennis_prospects as tp  # noqa: E402

ONLY = sys.argv[1].split(',') if len(sys.argv) > 1 and sys.argv[1] not in ('', '-') else None
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(tp.CACHE, 'tn_drivers_nov01.json')
SNAPS = ['10-26', '01-15', '04-15', '07-01']
B = tp.base()
rows = pickle.load(open(tp.ROWS, 'rb'))
fit = json.load(open(tp.FIT))


def sets(score):
    """(a, b) games per set from the winner's side; match tiebreaks (10-8) count as a set"""
    out = []
    for st in str(score).split():
        a, _, b = st.partition('-')
        b = b.split('(')[0]
        if a.isdigit() and b.isdigit():
            out.append((int(a), int(b)))
    return out


def match_cols(M):
    """per match, winner's view: retired, deciding set played, winner lost the first set"""
    ret = M.score.astype(str).str.contains('RET|ABD|ABN', case=False, na=False).values
    bo = pd.to_numeric(M.best_of, errors='coerce').fillna(3).astype(int).values
    ds = np.zeros(len(M), bool)
    lfs = np.zeros(len(M), bool)
    for k, sc in enumerate(M.score.values):
        s = sets(sc)
        if not s:
            continue
        lfs[k] = s[0][0] < s[0][1]
        ds[k] = (len(s) == bo[k]) and not ret[k]
    return pd.DataFrame({'ret': ret, 'ds': ds, 'wlfs': lfs}, index=M.index)


def long_plus(tour):
    b = B[tour]
    M, L = b['M'], b['L']
    mc = match_cols(M)
    i = L.i.values
    me_w = L.won.values == 1
    pick = lambda w, l: np.where(me_w, M[w].reindex(i).values, M[l].reindex(i).values)  # noqa: E731
    L = L.assign(
        dd=L.date.values.astype('datetime64[D]').astype(np.int64),
        ret=mc.ret.reindex(i).values, ds=mc.ds.reindex(i).values,
        bpS=pick('w_bpSaved', 'l_bpSaved'), bpF=pick('w_bpFaced', 'l_bpFaced'),
        obpS=pick('l_bpSaved', 'w_bpSaved'), obpF=pick('l_bpFaced', 'w_bpFaced'),
        df=pick('w_df', 'l_df'), fin=pick('w_1stIn', 'l_1stIn'), fwon=pick('w_1stWon', 'l_1stWon'),
        swon=pick('w_2ndWon', 'l_2ndWon'), oage=pick('loser_age', 'winner_age'))
    # the loser's first set: he lost the first set iff the winner won it
    L['lfs'] = np.where(me_w, mc.wlfs.reindex(i).values, ~mc.wlfs.reindex(i).values)
    L['pelo'] = 1 / (1 + 10 ** ((L.oelo - L.elo_pre) / 400))
    L['eres'] = L.won - L.pelo
    st = (L.svpt > 0) & (L.rtpt > 0) & L.svw.notna() & L.rtw.notna()
    L['st'] = st
    return L


def window(L, cols, X, lo, hi=7):
    """sums of L[cols] per row over matches with event date in (D - lo, D - hi] days"""
    D = (pd.to_datetime(X.season.astype(str) + '-' + X.snap).values.astype('datetime64[D]').astype(np.int64))
    out = np.zeros((len(X), len(cols)))
    V = L[cols].astype(float).fillna(0).values
    order = np.argsort(L.pid.values, kind='stable')
    pids = L.pid.values[order]
    dd = L.dd.values[order]
    V = V[order]
    starts = np.searchsorted(pids, X.pid.values, 'left')
    ends = np.searchsorted(pids, X.pid.values, 'right')
    for k in range(len(X)):
        s, e = starts[k], ends[k]
        if s == e:
            continue
        d = dd[s:e]
        o = np.argsort(d, kind='stable')
        a = np.searchsorted(d[o], D[k] - lo, 'right')
        z = np.searchsorted(d[o], D[k] - hi, 'right')
        if z > a:
            out[k] = V[s:e][o][a:z].sum(0)
    return pd.DataFrame(out, columns=cols, index=X.index)


def gaps(L, X):
    """longest gap (days) between matches (walkovers too) in the last year, counting the gap to the snapshot; count of
    90+ day gaps in the last two years"""
    D = (pd.to_datetime(X.season.astype(str) + '-' + X.snap).values.astype('datetime64[D]').astype(np.int64)) - 7
    g = {p: np.unique(v) for p, v in L.groupby('pid').dd}
    mx = np.zeros(len(X))
    n90 = np.zeros(len(X))
    for k, (p, d) in enumerate(zip(X.pid.values, D)):
        a = g.get(p)
        if a is None:
            continue
        w = a[(a > d - 730) & (a <= d)]
        if not len(w):
            mx[k] = 365
            continue
        w2 = np.concatenate([w, [d]])
        gp = np.diff(w2)
        n90[k] = (gp >= 90).sum()
        w1 = w2[w2 > d - 365]
        prev = w[w <= d - 365]
        if len(prev):
            w1 = np.concatenate([[prev[-1]], w1])
        mx[k] = np.diff(w1).max() if len(w1) > 1 else min(d - w1[0], 365)
    return pd.Series(np.minimum(mx, 365), index=X.index), pd.Series(n90, index=X.index)


def surf(L, X, lo=730):
    """Elo residual (won - Elo chance) per surface over two years, shrunk n/(n+10); spread, worst, surfaces played"""
    L = L.assign(sf=L.surface.astype(str).replace({'Carpet': 'Grass'}))
    R, N = {}, {}
    for s in ('Hard', 'Clay', 'Grass'):
        q = L[L.sf == s].assign(one=1.0)
        W = window(q, ['eres', 'one'], X, lo)
        N[s] = W.one.values
        R[s] = W.eres.values / (W.one.values + 10)
    Rm = np.column_stack([R[s] for s in R])
    Nm = np.column_stack([N[s] for s in N])
    ok = Nm >= 5
    k = ok.sum(1)
    hi = np.where(ok, Rm, -np.inf).max(1)
    lo_ = np.where(ok, Rm, np.inf).min(1)
    spread = np.where(k >= 2, hi - lo_, 0)
    worst = np.where(k >= 1, lo_, 0)
    return spread, worst, k


def extra(tour):
    L = long_plus(tour)
    X = rows[tour]
    X = X[(X.by >= tp.COHORTS[0]) & (X.by <= tp.COHORTS[1])].reset_index(drop=True)
    nw = L[~L.walk].copy()
    s = nw[nw.st].copy()
    # point-share slope on the Elo gap (population constant, like GSLOPE; no outcomes involved)
    tpw = (s.svw + s.rtw) / (s.svpt + s.rtpt)
    gap = (s.elo_pre - s.oelo).clip(-600, 600)
    slope = float(np.polyfit(gap, tpw, 1)[0])
    s['tpx'] = (tpw - (.5 + slope * gap)) * (s.svpt + s.rtpt)
    s['pts'] = s.svpt + s.rtpt
    s['tbn'] = s.tbw + s.tbl
    s['dsn'] = s.ds.astype(float)
    s['dsw'] = (s.ds & (s.won == 1)).astype(float)
    E = pd.DataFrame(index=X.index)
    W = window(s, ['svpt', 'svw', 'rtpt', 'rtw', 'ace', 'df', 'fin', 'fwon', 'swon', 'bpS', 'bpF', 'obpS', 'obpF',
                   'tpx', 'pts', 'tbw', 'tbn', 'dsw', 'dsn', 'won'], X, 365)
    W['n'] = window(s.assign(one=1.0), ['one'], X, 365).one
    E = E.join(W.add_prefix('s_'))
    # every level: games, tiebreaks, deciding sets, comebacks, quality, bad losses, opponent age
    nw['one'] = 1.0
    nw['gt'] = nw.gw + nw.gl
    nw['tbn'] = nw.tbw + nw.tbl
    nw['dsn'] = nw.ds.astype(float)
    nw['dsw'] = (nw.ds & (nw.won == 1)).astype(float)
    nw['lfs1'] = nw.lfs.astype(float)
    nw['cbk'] = (nw.lfs & (nw.won == 1)).astype(float)
    nw['n100'] = (nw.orank <= 100).astype(float)
    nw['w100'] = ((nw.orank <= 100) & (nw.won == 1)).astype(float)
    nw['wo'] = np.where(nw.won == 1, nw.oelo, 0)
    nw['lo'] = np.where(nw.won == 0, nw.oelo, 0)
    nw['bad'] = ((nw.won == 0) & (nw.oelo < nw.elo_pre - 150)).astype(float)
    nw['oagd'] = (nw.oage - nw.age).fillna(0)
    nw['oagn'] = (nw.oage.notna() & nw.age.notna()).astype(float)
    A = window(nw, ['one', 'won', 'gw', 'gt', 'tbw', 'tbn', 'dsw', 'dsn', 'lfs1', 'cbk', 'n100', 'w100', 'wo', 'lo',
                    'bad', 'oagd', 'oagn'], X, 365)
    E = E.join(A.add_prefix('a_'))
    # best opponent beaten (last year)
    wins = nw[nw.won == 1]
    D = (pd.to_datetime(X.season.astype(str) + '-' + X.snap).values.astype('datetime64[D]').astype(np.int64))
    g = {p: (v.dd.values, v.oelo.values) for p, v in wins.groupby('pid')}
    best = np.full(len(X), np.nan)
    for k, (p, d) in enumerate(zip(X.pid.values, D)):
        a = g.get(p)
        if a is None:
            continue
        m = (a[0] > d - 365) & (a[0] <= d - 7)
        if m.any():
            best[k] = a[1][m].max()
    E['best'] = best
    # durability: retirements and walkovers lost, two years (walkover rows are in L)
    Ld = L.assign(rl=((L.won == 0) & (L.ret | L.walk)).astype(float), one=1.0)
    Dd = window(Ld, ['rl', 'one'], X, 730)
    E['d_rl'], E['d_n'] = Dd.rl, Dd.one
    E['gapmx'], E['gap90'] = gaps(L, X)
    E['sspread'], E['sworst'], E['nsurf'] = surf(nw, X)
    return X, E, slope


def p_game(p):
    return p ** 4 * (15 - 4 * p - 10 * p * p / (1 - 2 * p * (1 - p)))


def p_tb(ps, pr):
    """first to 7 by two, alternating serve every two points (start serving); ps / pr = serve / return point prob"""
    from functools import lru_cache

    @lru_cache(None)
    def f(a, b):
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if a + b >= 12 and a == b:
            # deuce-like: two points, one on each serve
            w = ps * pr
            l = (1 - ps) * (1 - pr)
            return w / (w + l)
        n = a + b
        p = ps if ((n + 1) // 2) % 2 == 0 else pr
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)


def p_set(ps, pr):
    from functools import lru_cache
    h, br, t = p_game(ps), p_game(pr), p_tb(ps, pr)

    @lru_cache(None)
    def f(a, b):
        if (a >= 6 and a - b >= 2) or a == 7:
            return 1.0
        if (b >= 6 and b - a >= 2) or b == 7:
            return 0.0
        if a == 6 and b == 6:
            return t
        p = h if (a + b) % 2 == 0 else br
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return .5 * (f(0, 0) + _flip(ps, pr))


def _flip(ps, pr):
    """set win prob when the opponent serves first"""
    from functools import lru_cache
    h, br, t = p_game(ps), p_game(pr), p_tb(ps, pr)

    @lru_cache(None)
    def f(a, b):
        if (a >= 6 and a - b >= 2) or a == 7:
            return 1.0
        if (b >= 6 and b - a >= 2) or b == 7:
            return 0.0
        if a == 6 and b == 6:
            return t
        p = br if (a + b) % 2 == 0 else h
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)


def logit_(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def design_new(E, tour):
    F = pd.DataFrame(index=E.index)
    sv, rt = E.s_svpt, E.s_rtpt
    ok = (sv >= 150).values
    # shrunk point rates (prior 100 points at the tour mean)
    mspw = (E.s_svw.sum() / sv.sum())
    mrpw = (E.s_rtw.sum() / rt.sum())
    spw = (E.s_svw + 100 * mspw) / (sv + 100)
    rpw = (E.s_rtw + 100 * mrpw) / (rt + 100)
    F['ldr'] = np.where(ok, np.log(rpw / (1 - spw)), 0)
    F['tpw'] = np.where(ok, ((E.s_svw + E.s_rtw + 100) / (sv + rt + 200) - .5) * 10, 0)
    F['tpx'] = np.where(ok, E.s_tpx / (E.s_pts + 300) * 10, 0)
    F['fsin'] = np.where(ok, (E.s_fin + 50 * .6) / (sv + 50) - .6, 0) * 10
    F['sv2w'] = np.where(ok, ((E.s_swon + 50 * .5) / (sv - E.s_fin + 50) - .5) * 10, 0)
    F['dfr'] = np.where(ok, (E.s_df + 5) / (sv + 100) * 10, 0)
    # break points: saved above own serve-point rate, converted above own return-point rate (clutch / luck)
    bpc, bpo = E.s_obpF - E.s_obpS, E.s_obpF
    F['bpluck'] = np.where(ok, (E.s_bpS - spw * E.s_bpF + bpc - rpw * bpo) / (E.s_bpF + bpo + 20), 0)
    # 2. luck-stripped results
    # (a) point level: tiebreaks + deciding sets won minus their chance from the player's own serve / return point
    # rates through the Markov chain (stats matches only)
    pt = np.array([p_tb(a, b) if o else .5 for a, b, o in zip(spw.fillna(.6), rpw.fillna(.4), ok)])
    pst = np.array([p_set(a, b) if o else .5 for a, b, o in zip(spw.fillna(.6), rpw.fillna(.4), ok)])
    F['pluck'] = np.where(ok, (E.s_tbw - pt * E.s_tbn + E.s_dsw - pst * E.s_dsn) / (E.s_tbn + E.s_dsn + 6), 0)
    # (b) every level: tiebreaks + deciding sets won minus a coin flip moved by the game share (iid games -> set)
    gsh = (E.a_gw + 10) / (E.a_gt + 20)
    gs = np.array([_set_iid(x) for x in gsh])
    tbx = np.clip(.5 + 1.6 * (gsh - .5), .05, .95)  # tiebreak chance ~ point edge: set-level game share mapping
    F['gluck'] = (E.a_tbw - tbx * E.a_tbn + E.a_dsw - gs * E.a_dsn) / (E.a_tbn + E.a_dsn + 6)
    # (c) match wins over what the year's game share says (pythagorean exponent fit on all rows; no outcome)
    m = E.a_one >= 10
    lw = logit_((E.a_won + .5) / (E.a_one + 1))
    lg = logit_(gsh)
    bfit = np.polyfit(lg[m], lw[m], 1, w=np.sqrt(E.a_one[m]))
    exp = 1 / (1 + np.exp(-(bfit[1] + bfit[0] * lg)))
    F['mluck'] = (E.a_won - exp * E.a_one) / (E.a_one + 10)
    # point-level match luck: matches won over the best-of-3 chance from own point rates
    pm = pst * pst * (3 - 2 * pst)
    F['pluck_m'] = np.where(ok, (E.s_won - pm * E.s_n) / (E.s_n + 10), 0)
    # 3. surface versatility
    F['sspread'] = E.sspread
    F['sworst'] = E.sworst
    F['nsurf'] = E.nsurf
    # 4. quality of wins
    F['bestw'] = ((E.best.fillna(1500) - 1500) / 100)
    F['w100sh'] = E.a_w100 / (E.a_won + 3)
    F['t100'] = ((E.a_w100 + 1) / (E.a_n100 + 2) - .5) * np.log1p(E.a_n100)
    nwn, nl = E.a_won, E.a_one - E.a_won
    F['wq'] = np.where((nwn > 0) & (nl > 0), (E.a_wo / nwn.clip(lower=1) - E.a_lo / nl.clip(lower=1)) / 100, 0) * E.a_one / (E.a_one + 10)
    F['badl'] = E.a_bad / (E.a_one + 5)
    # 5. durability
    F['rl'] = np.log1p(E.d_rl)
    F['rlsh'] = E.d_rl / (E.d_n + 5)
    F['gapmx'] = E.gapmx / 365
    F['gap90'] = np.log1p(E.gap90)
    # extras: comebacks, opponents' age
    F['cbk'] = ((E.a_cbk + 1) / (E.a_lfs1 + 2) - .5) * np.log1p(E.a_lfs1)
    F['oage'] = np.where(E.a_oagn > 0, E.a_oagd / E.a_oagn.clip(lower=1), 0) * E.a_oagn / (E.a_oagn + 10) / 5
    F['cov'] = ok.astype(float)
    return F


def _set_iid(g):
    from functools import lru_cache

    @lru_cache(None)
    def f(a, b):
        if (a >= 6 and a - b >= 2) or a == 7:
            return 1.0
        if (b >= 6 and b - a >= 2) or b == 7:
            return 0.0
        if a == 6 and b == 6:
            return g
        return g * f(a + 1, b) + (1 - g) * f(a, b + 1)
    return f(0, 0)


def top50(pred, y, season):
    o = np.argsort(-pred)
    return float(pd.Series(y[o]).groupby(season[o]).head(50).mean())


AGEX = {'tpx_age': 'tpx', 'ldr_age': 'ldr', 'tpw_age': 'tpw', 'mluck_age': 'mluck', 'sspread_age': 'sspread',
        'bestw_age': 'bestw', 'gapmx_age': 'gapmx'}

res = {}
for tour in tp.TOURS:
    X, E, slope = extra(tour)
    Fn = design_new(E, tour)
    a = (X.age - 18).values
    for k, v in AGEX.items():
        Fn[k] = Fn[v] * a
    Fn['ldr_cov'] = Fn['ldr']  # paired with cov below
    kept = fit[tour]['kept']
    res[tour] = {'_slope': slope}
    lv = {c: round(float((Fn[c] != 0).mean()), 4) for c in Fn.columns}
    print(tour, 'point slope', round(slope, 6), 'nonzero share', lv, flush=True)
    # stats coverage by level, last-year matches of board rows (Oct)
    for snap in SNAPS:
        m = (X.snap == snap).values
        Xs = X[m].reset_index(drop=True)
        F = pd.concat([tp.design(Xs), Fn[m].reset_index(drop=True)], axis=1)
        y = tp.fv_rarity(Xs.pk.values, tp.scale(B, tour))
        pos = Xs.pk.values > 0
        by = Xs.by.values
        se = Xs.season.values
        P0, MU0, E0 = tp.loso(F, y, pos, by, kept)
        m0 = tp.fold_mse(E0, y, by)
        f0 = tp.forward(F, y, pos, by, se, kept)
        t0 = top50(E0, y, se)
        base = dict(mse=round(float(np.mean((E0 - y) ** 2)), 3), top50=round(t0, 3), fwd=[round(f0[0], 3), round(f0[1], 3)],
                    n=int(len(y)), cov=round(float(F['cov'].mean()), 4),
                    cov_top=round(float(F['cov'][np.argsort(-E0)][:int(len(y) * .1)].mean()), 4),
                    cov_pos=round(float(F['cov'][pos].mean()), 4))
        out = {'_base': base}
        print(tour, snap, 'base', base, flush=True)
        cands = [c for c in Fn.columns if c != 'cov' and (ONLY is None or c in ONLY)] + [c for c in (ONLY or []) if '+' in c]
        if snap != SNAPS[0] and not os.environ.get('ALLSNAPS'):
            # a candidate that fails October already fails the gate: other snapshots only for Oct t >= 1.5
            cands = [c for c in cands if res[tour][SNAPS[0]][c]['t'] >= 1.5]
        for c in cands:
            cols = kept + ([c, 'cov'] if c == 'ldr_cov' else c.split('+'))  # 'a+b' = joint test of two inputs
            P1, MU1, E1 = tp.loso(F, y, pos, by, cols)
            g = tp.gate(m0, tp.fold_mse(E1, y, by))
            f1 = tp.forward(F, y, pos, by, se, cols)
            g.update(top50=round(top50(E1, y, se) - t0, 3), fwd=round(f0[0] - f1[0], 3), fwdtop=round(f1[1] - f0[1], 3))
            bl, bo = tp.hurdle(F, y, pos, cols, np.ones(len(F), bool))
            g['coefL'], g['coefO'] = round(float(bl[len(kept) + 1]), 3), round(float(bo[len(kept) + 1]), 3)
            g['pass'] = bool(g['t'] >= 2 and g['wins'] >= 2 * g['of'] / 3 and g['top50'] >= 0 and g['fwd'] >= 0
                             and g['fwdtop'] >= 0)
            out[c] = g
            print(tour, snap, c, g, flush=True)
        res[tour][snap] = out
json.dump(res, open(OUT, 'w'), indent=1)
print('wrote', OUT)
