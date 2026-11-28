#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
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

Nov 28 2026 (--test2): three refits against the live pairs factors, each class graded with factors fit without its
careers and every NHLe input rebuilt (class strength and stage comps too), plus point in time (factors from seasons
through 2015-16, grade 2016-19). A ratio of summed points (fit_ratio), the same with a year of development, and the
pairs fit on pooled league names (H.canon: SHL / Sweden, NCAA conferences) all fail (draft t -1.98, -1.24, -2.41):
the API's era names carry era factors, so the live factors stay. A name the fit never saw (2025-26 renames) takes its
league's newest fitted name (--eras writes `last`). Retest after 2026-27: data/retests.json hockey_nhle_ratio.
"""
import datetime as dt
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


def lines(skip_ids=(), canon=False):
    """[(player index, league, age, gp, pts, season start year)] from the cached landing pages; skip_ids leaves careers out
    (class-out test); canon pools a league's spellings (H.canon)"""
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
            if canon:
                lg = H.canon(lg)
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


def fit_ratio(rows, age=False, maxyr=None):
    """the ratio version (Nov 28 2026, the shipped one): every pair of a player's lines in two different leagues in
    consecutive seasons (10+ games each); his points in the second league are Poisson around his games there times his
    rate in the first times f_A / f_B, so a factor is a ratio of summed points (what public NHLe does for the leagues
    that send players straight to the NHL), and every league is linked through the leagues its players move to. NHLe is
    then what it is in public use: NHL points over 82 games the next season at his rate this season. age=True adds a
    year of development by the first season's age (identified by the same-league pairs too) and reports the factor at
    the league's median mover age. maxyr keeps only pairs whose second season started by then (point in time).
    Returns the same shape as fit()."""
    by = {}
    for r in rows:
        if maxyr is None or r[5] <= maxyr:
            by.setdefault(r[0], {})[(r[5], r[1])] = r
    lgs = sorted({k[1] for d in by.values() for k in d}); li = {l: i for i, l in enumerate(lgs)}
    nL, nA = len(lgs), AGES[1] - AGES[0] + 1
    A_, B_, AG, OFF, Y = [], [], [], [], []
    links, ages = {}, {}
    for d in by.values():
        for (yr, la), a in d.items():
            if a[3] < MIN_GP or a[4] <= 0:
                continue
            for (yr2, lb), b in d.items():
                if yr2 != yr + 1 or b[3] < MIN_GP or (lb == la and not age):
                    continue
                A_.append(li[la]); B_.append(li[lb]); AG.append(a[2] - AGES[0])
                OFF.append(math.log(b[3] * a[4] / a[3])); Y.append(b[4])
                if la != lb:
                    links[la] = links.get(la, 0) + 1; links[lb] = links.get(lb, 0) + 1
                    ages.setdefault(la, []).append(a[2])
    A_, B_, AG, OFF, Y = map(np.array, (A_, B_, AG, OFF, Y))
    Y = Y.astype(float)
    n = nL + (nA if age else 0)
    nhl = li['NHL']
    # design: + phi_A - phi_B (+ gamma_age); phi_NHL = 0; Poisson IRLS with a small ridge for leagues with few links
    beta = np.zeros(n)
    rows_i = np.arange(len(Y))
    for it in range(60):
        eta = OFF + beta[A_] - beta[B_] + (beta[nL + AG] if age else 0)
        mu = np.exp(np.clip(eta, -30, 30))
        z = eta - OFF + (Y - mu) / mu
        G = np.zeros((n, n)); rhs = np.zeros(n)
        cols = [(A_, 1.0), (B_, -1.0)] + ([(nL + AG, 1.0)] if age else [])
        for ci, vi in cols:
            for cj, vj in cols:
                np.add.at(G, (ci, cj), mu * vi * vj)
            np.add.at(rhs, ci, mu * vi * z)
        G += 1e-4 * np.eye(n)
        G[nhl, :] = 0; G[nhl, nhl] = 1; rhs[nhl] = 0
        if age:                                     # development at 24 = 0 (the age term only moves the junior ages)
            j = nL + 24 - AGES[0]
            G[j, :] = 0; G[j, j] = 1; rhs[j] = 0
        new = np.linalg.solve(G, rhs)
        if np.abs(new - beta).max() < 1e-7:
            beta = new; break
        beta = new
    eta = OFF + beta[A_] - beta[B_] + (beta[nL + AG] if age else 0)
    mu = np.exp(eta)
    # a league's information: expected points in the pairs that touch it, halved for overdispersion
    info = (np.bincount(A_, mu * (A_ != B_), nL) + np.bincount(B_, mu * (A_ != B_), nL)) / 2
    gam = {AGES[0] + j: round(float(beta[nL + j]), 3) for j in range(nA)} if age else {}
    est = {}
    for lg in lgs:
        b = float(beta[li[lg]])
        if age and lg in ages:
            b += float(beta[nL + int(np.median(ages[lg])) - AGES[0]])      # a year of development at its movers' age
        est[lg] = (b, float(info[li[lg]]), links.get(lg, 0))
    return est, gam


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
    f = lambda lg: fac[lg] if lg in fac else fac[H.canon(lg)] if fac.get('_canon') and H.canon(lg) in fac else H.hand_of(lg) * fac.get('_unk', 1.0)
    out = []
    for r in rows:
        q = dict(r)
        for key in ('d0', 'dm1'):
            if q.get(key):
                q[key] = {**q[key], 'nhle': 82 * f(q[key]['lg']) * q[key]['ppg']}
        q['post'] = {k: (None if v is None else {**v, 'nhle': 82 * f(v['lg']) * v['ppg']}) for k, v in r['post'].items()}
        out.append(q)
    return out


def variant_factors(kind, rows_all, skip, maxyr=None):
    if kind == 'hand':
        return {lg: H.hand_of(lg) for lg in {r[1] for r in rows_all}} | {'_unk': 1.0}
    if kind == 'stored':                                # the factors on file (no refit; the class-out leak is theirs)
        return dict(json.load(open(OUT))['factors'])
    if kind == 'pairs_canon':
        est, _ = fit_pairs(lines(skip, canon=True) if skip is not None else rows_all)
    elif kind in ('ratio', 'ratio_age'):
        est, _ = fit_ratio(lines(skip, canon=True) if skip is not None else rows_all, age=kind == 'ratio_age', maxyr=maxyr)
    else:
        est, _ = (fit_pairs if kind == 'pairs' else fit)(lines(skip) if skip is not None else rows_all)
    fac = factors(est)
    # a league with no fitted factor keeps its hand constant, scaled like the fitted leagues are (median ratio)
    rat = [fac[lg] / H.hand_of(lg) for lg in fac if lg != 'NHL']
    fac['_unk'] = float(np.median(rat))
    if kind in ('ratio', 'ratio_age', 'pairs_canon'):
        fac['_canon'] = 1
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
    raw_rows, can_rows = lines(), lines(canon=True)
    res = {}
    for kind in kinds:
        allrows = can_rows if kind.startswith('ratio') else raw_rows
        # strict: each class is graded with factors fit without that class's careers
        p = np.zeros(len(y)); per = []
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
        # point in time (Nov 28 2026): factors from the seasons through 2015-16 only, the draft model fit on 2008-15 and
        # graded on 2016-19, every line translated with what was known at the 2016 draft
        pit = variant_factors(kind, [r for r in allrows if r[5] <= 2015], None)
        rp = relabel(tr0, pit)
        Xp = np.array([[f[k] for k in cols] for f in (H.feats(r) for r in rp)])
        trm, tem = cls <= 2015, cls >= 2016
        qp = np.clip(H.pred(H.ols(Xp[trm], y[trm]), Xp[tem]), 20, 80)
        top = tem & (picks <= 64)
        ck['pitMse'] = round(float(np.mean((qp - y[tem]) ** 2)), 4)
        ck['pitTopMse'] = round(float(np.mean((qp[top[tem]] - y[top]) ** 2)), 4)
        ck['pitTopRho'] = round(FD.spearman(qp[top[tem]], y[top]), 4)
        res.setdefault('_pit', {})[kind] = (qp - y[tem]) ** 2
        st = {}
        for k in range(1, 5):
            sub = [i for i, r in enumerate(rr) if r['year'] + k < H.D.current_season()]
            Fk = [H.stage_feats(rr[i], k, float(p[i])) for i in sub]
            yk, ckk = y[sub], cls[sub]
            s, _ = H.score(Fk, yk, ckk, fitd['stages'][str(k)]['kept'])
            st[k] = s
        res[kind] = {'per': per, 'checks': ck, 'stages': st, 'p': p, 'fac': {k: full.get(k) for k in ('OHL', 'WHL', 'QMJHL', 'NCAA', 'USHL', 'NTDP', 'AHL', 'SHL', 'Liiga', 'KHL', 'J20 Nationell', 'U20 SM-sarja', 'MHL', 'Czechia', 'NL')} if kind != 'hand' else None}
        print(kind, 'draft class-out mse', round(per.mean(), 3), ck, {k: round(v.mean(), 3) for k, v in st.items()})
    out = {}
    base_kind = 'pairs' if 'pairs' in kinds else 'hand'
    h = res[base_kind]
    for kind in kinds:
        if kind == base_kind:
            continue
        d = h['per'] - res[kind]['per']
        t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
        sd = {}
        for k in range(1, 5):
            e = h['stages'][k] - res[kind]['stages'][k]
            sd[k] = {'gain': round(float(e.mean()), 3), 't': round(float(e.mean() / (e.std(ddof=1) / math.sqrt(len(e)))), 2), 'wins': int((e > 0).sum()), 'of': len(e)}
        out[kind] = {'draft': {'gain': round(float(d.mean()), 3), 't': round(float(t), 2), 'wins': int((d > 0).sum()), 'of': len(d),
                               'mse': round(float(res[kind]['per'].mean()), 3), 'mseHand': round(float(h['per'].mean()), 3)},
                     'vs': base_kind,
                     'pit': (lambda e: {'gain': round(float(e.mean()), 3), 't': round(float(e.mean() / (e.std(ddof=1) / math.sqrt(len(e)))), 2), 'n': len(e)})(res['_pit'][base_kind] - res['_pit'][kind]),
                     'checks': {k: round(res[kind]['checks'][k] - h['checks'][k], 4) for k in h['checks']}, 'stages': sd,
                     'factors': res[kind]['fac']}
        print(kind, out[kind])
    return out


def eras(rows=None):
    """{league: last season start year it appears under that name}: the NHL API renames leagues between eras (Swe-Jr.
    2004-14, J20 SuperElit 2015-19, J20 Nationell 2020-24, U20 Nationell since), and a name the fit never saw takes the
    factor of its league's newest fitted name (hockey_prospects.nhle_of)"""
    out = {}
    for r in rows or lines():
        out[r[1]] = max(out.get(r[1], 0), r[5])
    return out


def main():
    """pairs fit (the shipped version) -> data/hockey_nhle.json; --test adds the class-out comparison; --test2 the strict
    comparison of the refit forms (Nov 28 2026); --eras only adds each league name's last season to the file"""
    if '--eras' in sys.argv:
        d = json.load(open(OUT)); e = eras()
        d['last'] = {k: v for k, v in sorted(e.items()) if k in d['factors']}
        json.dump(d, open(OUT, 'w'), indent=1, sort_keys=True)
        print('eras for', len(d['last']), 'leagues'); return
    if '--test2' in sys.argv:
        res, fac = test2()
        d = json.load(open(OUT)); d['test2'] = res
        json.dump(d, open(OUT, 'w'), indent=1, sort_keys=True)
        print('wrote test2 into', OUT); return
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



# -- strict test (Nov 28 2026) -------------------------------------------------------------------------------------
def _tt(d):
    d = np.asarray(d, float)
    return {'gain': round(float(d.mean()), 3), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2) if d.std() > 0 else 0.0,
            'wins': int((d > 0).sum()), 'of': len(d)}


def test2(kinds=('hand', 'pairs', 'pairs_canon', 'ratio', 'ratio_age'), base_kind='pairs'):
    """every input that reads NHLe is rebuilt from each variant's factors, class strength (cs) included, and the stage
    models with their comps. Draft and stages: each class graded by a fit that left it out, its lines translated with
    factors fit without that class's careers. Point in time: factors from seasons through 2015-16 only, models fit on
    2008-15, graded on 2016-19. Kept inputs are the live ones (data/hockey_fit.json); only the coefficients refit."""
    import hockey_fv_drivers as FD
    W = H.war_tables()
    base = H.read_rows(W)
    H.nhl_so_far(base, W)
    sc = H.outcome_scale(base)
    fitd = json.load(open(H.FIT))
    cols = fitd['kept']
    tr0 = [r for r in base if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr0]); cls = np.array([r['year'] for r in tr0]); picks = np.array([r['pick'] for r in tr0])
    C = sorted(set(cls))
    ids = {c: {str(r['id']) for r in base if r['year'] == c and r.get('id')} for c in C}
    raw_rows, can_rows = lines(), lines(canon=True)
    cur = H.D.current_season()

    def prep(fac):
        rr = relabel(tr0, fac)
        F = [H.feats(r) for r in rr]
        babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
        S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
        return rr, F, np.array([[f[c] for c in cols] for f in F])

    def stage_rows(rr, k, fv):
        sub = [i for i, r in enumerate(rr) if r['year'] + k < cur and H.onboard(r, k)]
        Fk = [H.stage_feats(rr[i], k, float(fv[i])) for i in sub]
        return np.array(sub), Fk

    def add_comp(Fk, sub, kk):
        if 'comp' not in kk:
            return
        yk, ck = y[sub], cls[sub]
        base_cols = [c for c in kk if c != 'comp']
        pool = H.comp_pool(Fk, yk - np.clip(H.loco(Fk, yk, ck, base_cols), 20, 80), [H.comp_grp(tr0[i]) for i in sub], ck)
        for f, i in zip(Fk, sub):
            f['comp'] = H.comp_of(pool, f, H.comp_grp(tr0[i]), own=cls[i])

    res = {}
    for kind in kinds:
        allrows = can_rows if kind.startswith('ratio') or kind.endswith('canon') else raw_rows
        facs = {c: variant_factors(kind, allrows, ids[c]) for c in C}
        preps = {c: prep(facs[c]) for c in C}
        p = np.zeros(len(y))
        for c in C:
            X = preps[c][2]; m = cls == c
            p[m] = np.clip(H.pred(H.ols(X[~m], y[~m]), X[m]), 20, 80)
        per = np.array([np.mean((p[cls == c] - y[cls == c]) ** 2) for c in C])
        top = picks <= 64
        pertop = np.array([np.mean((p[(cls == c) & top] - y[(cls == c) & top]) ** 2) for c in C])
        rho = float(np.mean([FD.spearman(p[(cls == c) & top], y[(cls == c) & top]) for c in C]))
        # point in time
        pit = variant_factors(kind, [r for r in allrows if r[5] <= 2015], None)
        rrp, Fp, Xp = prep(pit)
        trm, tem = cls <= 2015, cls >= 2016
        qp = np.clip(H.pred(H.ols(Xp[trm], y[trm]), Xp[tem]), 20, 80)
        pit_err = (qp - y[tem]) ** 2
        tt = top[tem]
        st, stp = {}, {}
        for k in range(1, 5):
            kk = fitd['stages'][str(k)]['kept']
            e_c = []
            for c in C:
                sub, Fk = stage_rows(preps[c][0], k, p)
                if c not in set(cls[sub]):
                    continue
                add_comp(Fk, sub, kk)
                Xk = np.array([[f[q] for q in kk] for f in Fk]); m = cls[sub] == c
                pk = np.clip(H.pred(H.ols(Xk[~m], y[sub][~m]), Xk[m]), 20, 80)
                e_c.append(float(np.mean((pk - y[sub][m]) ** 2)))
            st[k] = np.array(e_c)
            sub, Fk = stage_rows(rrp, k, p)
            add_comp(Fk, sub, kk)
            Xk = np.array([[f[q] for q in kk] for f in Fk]); a, b_ = cls[sub] <= 2015, cls[sub] >= 2016
            if b_.sum():
                pk = np.clip(H.pred(H.ols(Xk[a], y[sub][a]), Xk[b_]), 20, 80)
                stp[k] = (pk - y[sub][b_]) ** 2
        res[kind] = {'per': per, 'pertop': pertop, 'rho': rho, 'pit': pit_err, 'pitTop': pit_err[tt], 'pitRho': FD.spearman(qp[tt], y[tem][tt]),
                     'st': st, 'stp': stp, 'fac': {q: round(v, 4) for q, v in sorted(variant_factors(kind, allrows, None).items()) if not q.startswith('_')}}
        print(kind, 'draft', round(per.mean(), 3), 'top64', round(pertop.mean(), 3), 'rho', round(rho, 4), 'pit', round(pit_err.mean(), 3),
              'stages', {k: round(v.mean(), 3) for k, v in st.items()}, 'pit stages', {k: round(v.mean(), 3) for k, v in stp.items()}, flush=True)
    out = {}
    h = res[base_kind]
    for kind in kinds:
        if kind == base_kind:
            continue
        r = res[kind]
        out[kind] = {'vs': base_kind, 'draft': _tt(h['per'] - r['per']) | {'mse': round(float(r['per'].mean()), 3), 'mseBase': round(float(h['per'].mean()), 3)},
                     'top64': _tt(h['pertop'] - r['pertop']), 'rho': round(r['rho'] - h['rho'], 4),
                     'pit': _tt(h['pit'] - r['pit']), 'pitTop': _tt(h['pitTop'] - r['pitTop']), 'pitRho': round(r['pitRho'] - h['pitRho'], 4),
                     'stages': {k: _tt(h['st'][k] - r['st'][k]) for k in r['st']},
                     'pitStages': {k: _tt(h['stp'][k] - r['stp'][k]) for k in r['stp']}}
        print(kind, 'vs', base_kind, json.dumps(out[kind]))
    return out, {k: v['fac'] for k, v in res.items() if k != 'hand'}


if __name__ == '__main__':
    main()
