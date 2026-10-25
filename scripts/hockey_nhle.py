#!/usr/bin/env python3
"""Fitted NHLe (audit item 44, Oct 25 2026): league translation factors from the careers of every NHL draft pick.

    python3 scripts/hockey_fv_drivers.py --pull   # landing pages of every pick 2008-26 -> scripts/.cache/hockey/full
    python3 scripts/hockey_nhle.py                # -> data/hockey_nhle.json (read by scripts/hockey_prospects.py)
    python3 scripts/hockey_nhle.py --test         # + class-out test against the hand constants (and the fixed-effects form)

Network fit: every regular-season club line of 10+ games (skaters, every season of a pick's career, junior to NHL) is
one row, points ~ Poisson(games x exp(player + league + age)). The player term holds talent, the age term (one a year,
16 to 34) holds development, so a league's term is what a point there is worth at the same age: the factor is
exp(league - NHL). Leagues are linked by players who moved between them, in the same season or the next, so every pair
of consecutive leagues in ~5,000 careers enters at once. A league's term is shrunk toward the hand constant it replaces
(log scale, prior sd PRIOR_SD) by its information (movers' expected points there, halved for overdispersion): thin leagues stay near the published factor.
"""
import datetime as dt
import gzip
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import hockey_prospects as H

FULL = os.path.join(H.CACHE, 'full')
OUT = os.path.join(ROOT, 'data', 'hockey_nhle.json')
MIN_GP, AGES, PRIOR_SD = 10, (16, 34), 0.25


def lines(skip_ids=()):
    """[(player index, league, age, gp, pts)] from the cached landing pages; skip_ids leaves careers out (class-out test)"""
    out, pid = [], {}
    for fn in os.listdir(FULL):
        try:
            L = json.load(open(os.path.join(FULL, fn)))
        except ValueError:
            continue
        if L.get('position') == 'G' or str(L.get('playerId')) in skip_ids:
            continue
        try:
            b = dt.date.fromisoformat(L.get('birthDate') or '')
        except ValueError:
            continue
        agg = {}
        for s in L.get('seasons') or []:
            lg = s.get('leagueAbbrev') or ''
            if s.get('gameTypeId') != 2 or H.TOURN.match(lg):
                continue
            a = agg.setdefault((s['season'], lg), [0, 0])
            a[0] += s.get('gamesPlayed') or 0; a[1] += s.get('points') or 0
        for (sid, lg), (gp, pts) in agg.items():
            if gp < MIN_GP:
                continue
            age = (dt.date(sid // 10000, 12, 31) - b).days / 365.25
            out.append((pid.setdefault(fn, len(pid)), lg, min(max(int(age), AGES[0]), AGES[1]), gp, pts, sid // 10000))
    return out


def fit(rows, iters=200):
    """alternating Poisson fixed effects; returns {league: (log factor vs NHL, points of information)}"""
    p = np.array([r[0] for r in rows]); lgs = sorted({r[1] for r in rows}); li = {l: i for i, l in enumerate(lgs)}
    l = np.array([li[r[1]] for r in rows]); a = np.array([r[2] - AGES[0] for r in rows])
    gp = np.array([r[3] for r in rows], float); y = np.array([r[4] for r in rows], float)
    nP, nL, nA = p.max() + 1, len(lgs), AGES[1] - AGES[0] + 1
    P, Lg, A = np.zeros(nP), np.zeros(nL), np.zeros(nA)
    sy = lambda idx, n: np.bincount(idx, y, n)
    YP, YL, YA = sy(p, nP), sy(l, nL), sy(a, nA)
    for it in range(iters):
        old = Lg.copy()
        e = gp * np.exp(Lg[l] + A[a]); P = np.log((YP + .1) / (np.bincount(p, e, nP) + .1 / max(e.mean(), 1e-9)))
        e = gp * np.exp(P[p] + A[a]); Lg = np.log((YL + .5) / np.bincount(l, e, nL))
        e = gp * np.exp(P[p] + Lg[l]); A = np.log((YA + .5) / np.bincount(a, e, nA))
        A -= A[24 - AGES[0]]
        if np.abs(Lg - old).max() < 1e-6:
            break
    nhl = Lg[li['NHL']]
    mu = gp * np.exp(P[p] + Lg[l] + A[a])
    # a league's term is identified only by players with lines in another league: its information is their expected points
    # there (Poisson), halved for overdispersion
    nlg = {}
    for i, j in zip(p, l):
        nlg.setdefault(i, set()).add(j)
    mv = np.array([len(nlg[i]) > 1 for i in p])
    info = np.bincount(l, mu * mv, nL) / 2
    links = {}
    for i, s in nlg.items():
        if len(s) > 1:
            for j in s:
                links[lgs[j]] = links.get(lgs[j], 0) + 1
    # NHLe factor = NHL points a point in the league: exp(NHL term - league term)
    return {lg: (float(nhl - Lg[li[lg]]), float(info[li[lg]]), links.get(lg, 0)) for lg in lgs}, {AGES[0] + k: round(float(v), 3) for k, v in enumerate(A)}


def fit_pairs(rows):
    """the pair version: every two lines of a player in the same season or consecutive seasons; log points a game in B over
    A = league B - league A (+ a year of development at A's age when B is the next season), weighted least squares by the
    harmonic mean of games; returns the same shape as fit()"""
    by = {}
    for r in rows:
        by.setdefault(r[0], []).append(r)
    lgs = sorted({r[1] for r in rows}); li = {l: i for i, l in enumerate(lgs)}
    nL, nA = len(lgs), AGES[1] - AGES[0] + 1
    I, J, V, Y, Wt = [], [], [], [], []
    links = {}
    k = 0
    for ls in by.values():
        for a in ls:
            for b in ls:
                if b is a or not (b[5] == a[5] + 1 or (b[5] == a[5] and b[1] > a[1])) or (b[5] == a[5] and b[1] == a[1]):
                    continue
                y = math.log((b[4] + .5) / b[3]) - math.log((a[4] + .5) / a[3])
                w = 2 / (1 / a[3] + 1 / b[3])
                cols = {}
                if a[1] != b[1]:
                    cols[li[b[1]]] = 1.0; cols[li[a[1]]] = -1.0
                    links[a[1]] = links.get(a[1], 0) + 1; links[b[1]] = links.get(b[1], 0) + 1
                if b[5] == a[5] + 1:
                    cols[nL + a[2] - AGES[0]] = 1.0
                if not cols:
                    continue
                for c, v in cols.items():
                    I.append(k); J.append(c); V.append(v)
                Y.append(y); Wt.append(w); k += 1
    n = nL + nA
    # normal equations accumulated from the (at most three) nonzeros of each pair
    I, J, V, Wt, Y = map(np.array, (I, J, V, Wt, Y))
    G = np.zeros((n, n)); rhs = np.zeros(n)
    order = np.argsort(I, kind='stable')
    rowcols = np.split(np.column_stack([J[order], V[order]]), np.flatnonzero(np.diff(I[order])) + 1)
    for q, cv in enumerate(rowcols):
        c, v = cv[:, 0].astype(int), cv[:, 1]
        G[np.ix_(c, c)] += Wt[q] * np.outer(v, v)
        rhs[c] += Wt[q] * Y[q] * v
    G += 1e-6 * np.eye(n)
    nhl = li['NHL']
    G[nhl, :] = 0; G[nhl, nhl] = 1                  # NHL = 0
    rhs[nhl] = 0
    beta = np.linalg.solve(G, rhs)
    info = np.array([links.get(l, 0) for l in lgs]) * 6.0      # shrink weight: a link's log ratio has sd ~.4
    return ({lg: (float(-beta[li[lg]]), float(info[li[lg]]), links.get(lg, 0)) for lg in lgs},
            {AGES[0] + j: round(float(beta[nL + j]), 3) for j in range(nA)})


def factors(est):
    """shrink each league's log factor toward the hand constant it replaces; leagues with no hand constant shrink toward
    the default for an unlisted league"""
    tau = 1 / PRIOR_SD ** 2
    out = {}
    for lg, (b, info, links) in est.items():
        if links < 5 or lg == 'NHL':
            continue
        pr = math.log(H.hand_of(lg))
        w = info
        out[lg] = round(math.exp((w * b + tau * pr) / (w + tau)), 4)
    out['NHL'] = 1.0
    return out


# -- class-out test ------------------------------------------------------------------------------------------------
def relabel(rows, fac):
    """copy of the pick rows with every line's NHLe recomputed from the factors ({} = the hand constants)"""
    f = lambda lg: fac.get(lg, H.hand_of(lg) * fac.get('_unk', 1.0))
    out = []
    for r in rows:
        q = dict(r)
        for key in ('d0', 'dm1'):
            if q.get(key):
                q[key] = {**q[key], 'nhle': 82 * f(q[key]['lg']) * q[key]['ppg']}
        q['post'] = {k: (None if v is None else {**v, 'nhle': 82 * f(v['lg']) * v['ppg']}) for k, v in r['post'].items()}
        out.append(q)
    return out


def variant_factors(kind, rows_all, skip):
    if kind == 'hand':
        return {lg: H.hand_of(lg) for lg in {r[1] for r in rows_all}} | {'_unk': 1.0}
    est, _ = (fit_pairs if kind == 'pairs' else fit)(lines(skip) if skip is not None else rows_all)
    fac = factors(est)
    # a league with no fitted factor keeps its hand constant, scaled like the fitted leagues are (median ratio)
    rat = [fac[lg] / H.hand_of(lg) for lg in fac if lg != 'NHL']
    fac['_unk'] = float(np.median(rat))
    return fac


def test(kinds=('hand', 'fe', 'pairs')):
    import hockey_fv_drivers as FD
    W = H.war_tables()
    base = H.read_rows(W)
    H.nhl_so_far(base, W)
    sc = H.outcome_scale(base)
    fitd = json.load(open(H.FIT))
    cols = fitd['kept']
    tr0 = [r for r in base if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr0]); cls = np.array([r['year'] for r in tr0]); picks = np.array([r['pick'] for r in tr0])
    ids = {c: {str(r['id']) for r in base if r['year'] == c and r.get('id')} for c in sorted(set(cls))}
    allrows = lines()
    res = {}
    for kind in kinds:
        # strict: each class is graded with factors fit without that class's careers
        p = np.zeros(len(y)); per = []
        stage_p = {k: {} for k in range(1, 5)}
        facs = {c: variant_factors(kind, allrows, ids[c]) for c in sorted(set(cls))}
        for c in sorted(set(cls)):
            rr = relabel(tr0, facs[c])
            F = [H.feats(r) for r in rr]
            X = np.array([[f[k] for k in cols] for f in F]); m = cls == c
            b = H.ols(X[~m], y[~m]); p[m] = np.clip(H.pred(b, X[m]), 20, 80)
        per = np.array([np.mean((p[cls == c] - y[cls == c]) ** 2) for c in sorted(set(cls))])
        # the checks and stages on the full-sample factors (the in-sample leak there is the same for every variant)
        full = variant_factors(kind, allrows, None)
        rr = relabel(tr0, full)
        F = [H.feats(r) for r in rr]
        ck = FD.checks(F, y, cls, picks, cols)
        st = {}
        for k in range(1, 5):
            sub = [i for i, r in enumerate(rr) if r['year'] + k < H.D.current_season()]
            Fk = [H.stage_feats(rr[i], k, float(p[i])) for i in sub]
            yk, ckk = y[sub], cls[sub]
            s, _ = H.score(Fk, yk, ckk, fitd['stages'][str(k)]['kept'])
            st[k] = s
        res[kind] = {'per': per, 'checks': ck, 'stages': st, 'p': p, 'fac': {k: full.get(k) for k in ('OHL', 'WHL', 'QMJHL', 'NCAA', 'USHL', 'NTDP', 'AHL', 'SHL', 'Liiga', 'KHL', 'J20 Nationell', 'MHL')} if kind != 'hand' else None}
        print(kind, 'draft class-out mse', round(per.mean(), 3), ck, {k: round(v.mean(), 3) for k, v in st.items()})
    out = {}
    h = res['hand']
    for kind in kinds:
        if kind == 'hand':
            continue
        d = h['per'] - res[kind]['per']
        t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
        sd = {}
        for k in range(1, 5):
            e = h['stages'][k] - res[kind]['stages'][k]
            sd[k] = {'gain': round(float(e.mean()), 3), 't': round(float(e.mean() / (e.std(ddof=1) / math.sqrt(len(e)))), 2), 'wins': int((e > 0).sum()), 'of': len(e)}
        out[kind] = {'draft': {'gain': round(float(d.mean()), 3), 't': round(float(t), 2), 'wins': int((d > 0).sum()), 'of': len(d),
                               'mse': round(float(res[kind]['per'].mean()), 3), 'mseHand': round(float(h['per'].mean()), 3)},
                     'checks': {k: round(res[kind]['checks'][k] - h['checks'][k], 4) for k in h['checks']}, 'stages': sd,
                     'factors': res[kind]['fac']}
        print(kind, out[kind])
    return out


def main():
    """pairs fit (the shipped version) -> data/hockey_nhle.json; --test adds the class-out comparison"""
    rows = lines()
    est, age = fit_pairs(rows)
    fac = variant_factors('pairs', rows, None)
    print(len(rows), 'lines', len({r[0] for r in rows}), 'players')
    print('development a year by age', age)
    for lg, (b, info, links) in sorted(est.items(), key=lambda kv: -kv[1][2])[:40]:
        print(f'{lg:20s} fit {math.exp(b):.3f}  shrunk {fac.get(lg, float("nan")):.3f}  hand {H.hand_of(lg):.3f}  movers {links}')
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    out = {'asof': dt.date.today().isoformat(), 'method': 'pairs', 'lines': len(rows), 'players': len({r[0] for r in rows}),
           'priorSd': PRIOR_SD, 'growth': age, 'raw': {lg: [round(math.exp(b), 4), links] for lg, (b, info, links) in est.items() if links >= 5},
           'factors': {k: round(v, 4) for k, v in fac.items()}, 'test': old.get('test')}
    if '--test' in sys.argv:
        out['test'] = test()
    json.dump(out, open(OUT, 'w'), indent=1, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
