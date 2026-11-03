#!/usr/bin/env python3
"""College basketball market models: Transfer% and landing odds (NIL era), coaching jobs (which head jobs open, who
fills them) and coach pay (what the market pays a coach's profile). Fit by hand; scored daily by scripts/cbb_market.py.

    python3 scripts/cbb_market_fit.py        # -> data/cbb_market_fit.json (coefficients + out-of-sample tests)

Data (all committed): player seasons /mnt/project-files/cbb/backtest/research_seasons.csv (Barttorvik, 2008-26; the
committed slice scripts/data/cbb_market_rows.json.gz is written on the first run and used when the CSV is absent),
games scripts/data/cbb_games_hist.json.gz (records, SRS, NCAA tournament), head coaches by season
scripts/data/cbb_coaches.json (Sports Reference), coach records against the preseason projection
scripts/data/cbb_coach_miss.json, arenas scripts/data/cbb_venues.json, pay scripts/data/cbb_market_src.json.gz
(USA Today, from scripts/cbb_market_pull.py).

Models
  move     multinomial logit, each player-season: back at the same school / on another D-I roster (moved) / gone (out
           of D-I: eligibility, the draft, quit). NIL era only (Noah's rule: July 2021 on), so the 2022->23 to
           2025->26 offseasons; fit 2022-24, tested on 2025->26, refit on all four.
  landing  conditional logit over every D-I team for each mover, same seasons and split: the step in team level
           against his production, conference, distance, his coach moving there, a new coach there, minutes open there.
  vacancy  multinomial logit, each school-season 2016-25: same head coach next season / hired away by another D-I
           school / out (fired, retired, the NBA). Fit 2016-21, tested on 2022-25, refit on all.
  hires    conditional logit over every sitting D-I head coach for each opening filled by one: step up in program
           level, his results, conference, distance. Same split.
  value    ridge on log(USA Today head coach pay), inputs kept only if they lower leave-one-school-out error.
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cbb_games as C  # noqa: E402
import cbb_roster as R  # noqa: E402

CSV = '/mnt/project-files/cbb/backtest/research_seasons.csv'
ROWS = os.path.join(HERE, 'data', 'cbb_market_rows.json.gz')
SRC = os.path.join(HERE, 'data', 'cbb_market_src.json.gz')
MISS = os.path.join(HERE, 'data', 'cbb_coach_miss.json')
VEN = os.path.join(HERE, 'data', 'cbb_venues.json')
OUT = os.path.join(ROOT, 'data', 'cbb_market_fit.json')
P6 = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}
NIL0 = 2022            # first offseason fully in the NIL era (spring 2022; NIL began July 2021)
COLS = ('pid', 'name', 'team', 'conf', 'year', 'yr', 'gp', 'min_per', 'bpm', 'obpm', 'dbpm', 'usg', 'hti', 'rg_lrk', 'age', 'guard', 'big')


# ---- data ------------------------------------------------------------------------------------------------------
def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def player_rows(write=False):
    """season -> [row]; the CSV when present (and the committed slice refreshed from it), else the slice"""
    if write and os.path.exists(CSV):
        out = []
        for r in csv.DictReader(open(CSV)):
            if int(r['year']) < 2014:
                continue
            out.append({k: (r[k] if k in ('name', 'team', 'conf', 'yr') else fnum(r[k])) for k in COLS})
        with gzip.open(ROWS, 'wt') as h:
            json.dump(out, h, separators=(',', ':'))
    else:
        out = json.load(gzip.open(ROWS))
    by = defaultdict(list)
    for r in out:
        r['year'] = int(r['year']); r['pid'] = int(r['pid'])
        by[r['year']].append(r)
    return by


def team_seasons():
    """(season, Barttorvik team) -> record, SRS (margin-based rating, D-I games), NCAA tournament games won/bid,
    ESPN id; and the id <-> name maps"""
    games = C.load_hist()
    bt = C.bt_map(games)
    by = defaultdict(list)
    for g in games:
        by[g['season']].append(g)
    TS = {}
    for s, G in by.items():
        d1 = C.d1_set(G)
        rec = defaultdict(lambda: [0, 0])
        ncaa = defaultdict(int); bid = set()
        rows, ys, idx = [], [], {}
        for g in G:
            if g.get('hs') is None or g.get('as') is None:
                continue
            h, a = g['home'], g['away']
            hw = g['hs'] > g['as']
            rec[h][0 if hw else 1] += 1; rec[a][1 if hw else 0] += 1
            note = (g.get('note') or '')
            if "NCAA Men's Basketball Championship" in note:
                bid.update((h, a)); ncaa[h if hw else a] += 1
            if h in d1 and a in d1:
                for t in (h, a):
                    idx.setdefault(t, len(idx))
                rows.append((idx[h], idx[a], 0 if g.get('neutral') else 1)); ys.append(max(-30, min(30, g['hs'] - g['as'])))
        n = len(idx)
        if not n:
            continue
        X = np.zeros((len(rows), n + 1))
        for i, (h, a, hm) in enumerate(rows):
            X[i, h] = 1; X[i, a] = -1; X[i, n] = hm
        A = X.T @ X + 1e-2 * np.eye(n + 1)
        b = np.linalg.solve(A, X.T @ np.array(ys, float))
        r = b[:n] - b[:n].mean()
        for t, i in idx.items():
            nm = bt.get(t)
            if not nm:
                continue
            w, l = rec[t]
            TS[(s, nm)] = {'id': t, 'w': w, 'l': l, 'wp': w / max(1, w + l), 'srs': float(r[i]), 'ncaa': ncaa.get(t, 0), 'bid': t in bid}
    return TS, bt


def prog_norm(TS, s, t, k=5):
    """program level going into season s: mean SRS and win% over up to k seasons before"""
    v = [TS[(y, t)] for y in range(s - k, s) if (y, t) in TS]
    if not v:
        return None, None
    return float(np.mean([x['srs'] for x in v])), float(np.mean([x['wp'] for x in v]))


def geo(bt):
    V = json.load(open(VEN))['teams']
    inv = defaultdict(set)
    for i, n in bt.items():
        inv[n].add(i)
    out = {}
    for n, ids in inv.items():
        for i in ids:
            if i in V and V[i][0] is not None:
                out[n] = (V[i][0], V[i][1]); break
    return out


def miles(a, b):
    if not a or not b:
        return None
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3959 * 2 * math.asin(min(1, math.sqrt(h)))


def coaches():
    tprior = json.load(open(C.TPRIOR))
    raw = R.coach_feats(R.load_coaches(), tprior, raw=True)
    miss = json.load(open(MISS)) if os.path.exists(MISS) else {}
    return raw, miss


def cres(miss, coach, s, K=2.0):
    h = [m for ss, _, m in miss.get(coach, []) if ss < s]
    return sum(h) / (len(h) + K)


# ---- fitters ---------------------------------------------------------------------------------------------------
def mnl(X, y, K, lam=1.0, it=60):
    """multinomial logit (class 0 base), L2 on everything but the intercepts (column 0), Newton with step halving"""
    n, p = X.shape
    B = np.zeros((K - 1, p))
    pen = np.full(p, lam); pen[0] = 1e-6
    Y = np.zeros((n, K)); Y[np.arange(n), y] = 1

    def obj(B):
        Z = np.hstack([np.zeros((n, 1)), X @ B.T])
        m = Z.max(1, keepdims=True)
        lse = (m + np.log(np.exp(Z - m).sum(1, keepdims=True))).ravel()
        return float(Z[np.arange(n), y].sum() - lse.sum() - 0.5 * (B * B * pen).sum())
    f = obj(B)
    for _ in range(it):
        Z = np.hstack([np.zeros((n, 1)), X @ B.T])
        Z -= Z.max(1, keepdims=True)
        P = np.exp(Z); P /= P.sum(1, keepdims=True)
        G = ((Y - P)[:, 1:].T @ X) - B * pen
        H = np.zeros(((K - 1) * p, (K - 1) * p))
        for a in range(1, K):
            for b in range(1, K):
                w = P[:, a] * ((a == b) - P[:, b])
                H[(a - 1) * p:a * p, (b - 1) * p:b * p] = -(X * w[:, None]).T @ X
        H -= np.diag(np.tile(pen, K - 1))
        step = np.linalg.solve(H, G.ravel()).reshape(K - 1, p)
        t = 1.0
        while t > 1e-4:
            nB = B - t * step
            nf = obj(nB)
            if nf >= f - 1e-9:
                break
            t /= 2
        B, f0, f = nB, f, nf
        if abs(f - f0) < 1e-8:
            break
    return B


def mnl_p(X, B):
    Z = np.hstack([np.zeros((X.shape[0], 1)), X @ B.T])
    Z -= Z.max(1, keepdims=True)
    P = np.exp(Z)
    return P / P.sum(1, keepdims=True)


def clogit(X, ev, ch, lam=1.0, it=60):
    """conditional logit: rows X (alternatives), ev = event index of each row (sorted, 0..E-1), ch = 1 on the chosen.
    Newton with step halving on the penalised log-likelihood"""
    n, p = X.shape
    b = np.zeros(p)
    starts = np.r_[0, np.flatnonzero(np.diff(ev)) + 1]

    def obj(b):
        u = X @ b
        m = np.maximum.reduceat(u, starts)
        s = np.add.reduceat(np.exp(u - m[ev]), starts)
        return float(u[ch == 1].sum() - (m + np.log(s)).sum() - lam / 2 * b @ b)
    f = obj(b)
    for _ in range(it):
        u = X @ b
        m = np.maximum.reduceat(u, starts)
        e = np.exp(u - m[ev])
        s = np.add.reduceat(e, starts)
        pr = e / s[ev]
        xbar = np.add.reduceat(X * pr[:, None], starts)
        G = X[ch == 1].sum(0) - xbar.sum(0) - lam * b
        H = -(X * pr[:, None]).T @ X + xbar.T @ xbar - lam * np.eye(p)
        step = np.linalg.solve(H, G)
        t = 1.0
        while t > 1e-4:
            nb = b - t * step
            nf = obj(nb)
            if nf >= f - 1e-9:
                break
            t /= 2
        b, f0, f = nb, f, nf
        if abs(f - f0) < 1e-8:
            break
    return b


def clogit_p(X, ev, b):
    starts = np.r_[0, np.flatnonzero(np.diff(ev)) + 1]
    u = X @ b
    m = np.maximum.reduceat(u, starts)
    e = np.exp(u - m[ev])
    return e / np.add.reduceat(e, starts)[ev]


def auc(y, s):
    o = np.argsort(s); y = np.asarray(y)[o]
    n1 = y.sum(); n0 = len(y) - n1
    if not n1 or not n0:
        return None
    r = np.arange(1, len(y) + 1)
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def std(X, cols):
    """column means/sds (column 0 = intercept left alone)"""
    mu = X.mean(0); sd = X.std(0); mu[0] = 0; sd[0] = 1; sd[sd == 0] = 1
    return mu, sd


# ---- move (Transfer%) ------------------------------------------------------------------------------------------
MOVE_F = ['1', 'bpm', 'bpm_pos', 'min', 'min2', 'usg', 'so', 'jr', 'sr', 'srs', 'bpm_x_srs', 'p6', 'rec', 'ht', 'trans',
          'cc_next', 'cc_now', 'minrk', 'gp', 'age']


def move_rows(by, TS, raw):
    """(season, features, label 0 back / 1 moved / 2 gone, pid, team) for seasons y with y+1 known"""
    out = []
    years = sorted(by)
    nxt = {y: {r['pid']: r['team'] for r in by[y]} for y in years}
    for y in years:
        if y + 1 not in nxt or y < 2015:
            continue
        T = defaultdict(list)
        for r in by[y]:
            T[r['team']].append(r)
        rk = {}
        for t, ps in T.items():
            for i, r in enumerate(sorted(ps, key=lambda r: -(r['min_per'] or 0))):
                rk[r['pid']] = i + 1
        prev = nxt.get(y - 1, {})
        for r in by[y]:
            if (r['min_per'] or 0) <= 0:
                continue
            t = r['team']
            lab = 0 if nxt[y + 1].get(r['pid']) == t else 1 if r['pid'] in nxt[y + 1] else 2
            co, cn, cp = raw.get(y, {}).get(t), raw.get(y + 1, {}).get(t), raw.get(y - 1, {}).get(t)
            f = feats_move(r, TS.get((y, t), {}).get('srs'), r['conf'] in P6, rk.get(r['pid'], 15), prev.get(r['pid']) not in (None, t),
                           1.0 if co and cn and co['coach'] != cn['coach'] else 0.0, 1.0 if co and cp and co['coach'] != cp['coach'] else 0.0)
            out.append((y, f, lab, r['pid'], t))
    return out


def feats_move(r, srs, p6, minrk, trans, cc_next, cc_now):
    b = max(-15.0, min(15.0, r.get('bpm') or 0.0))
    m = (r.get('min_per') or 0) / 100
    yr = r.get('yr') or 'Fr'
    s = (srs or 0.0) / 10
    rec = r.get('rg_lrk')
    return [1, b / 5, max(0.0, b) / 5, m, m * m, ((r.get('usg') or 18) - 18) / 5, yr == 'So', yr == 'Jr', yr == 'Sr', s, b / 5 * s, float(p6),
            (rec if rec is not None else -6.2) + 5.5, ((r.get('hti') or 77) - 77) / 3, float(trans), cc_next, cc_now,
            min(minrk, 13) / 13, min(1.0, (r.get('gp') or 0) / 30), ((r.get('age') or 21) - 21) / 2]


def recal(X, y, B, K, it=50):
    """shift the intercepts so the mean predicted class shares on (X, y) equal the observed ones (the latest
    offseason's level: transfer and coaching churn trend up, so scoring uses the newest season's base rates)"""
    B = B.copy()
    obs = np.bincount(y, minlength=K) / len(y)
    for _ in range(it):
        pr = mnl_p(X, B).mean(0)
        B[:, 0] += np.log(obs[1:] / obs[0]) - np.log(pr[1:] / pr[0])
    return B


def ll_of(P, y):
    return float(-np.mean(np.log(P[np.arange(len(y)), y] + 1e-12)))


def select(rows, feats, fit_yrs, val_yrs, K=3, lam=2.0):
    """greedy backward elimination on a validation split inside the training seasons: drop the input whose removal
    lowers validation log loss most, until none does"""
    tr = [x for x in rows if x[0] in fit_yrs]; va = [x for x in rows if x[0] in val_yrs]
    Xa = np.array([x[1] for x in tr], float); ya = np.array([x[2] for x in tr])
    Xv = np.array([x[1] for x in va], float); yv = np.array([x[2] for x in va])

    def score(keep):
        mu, sd = std(Xa[:, keep], None)
        B = mnl((Xa[:, keep] - mu) / sd, ya, K, lam=lam)
        B = recal((Xa[:, keep] - mu) / sd, ya, B, K) if False else B
        return ll_of(mnl_p((Xv[:, keep] - mu) / sd, B), yv)
    keep = list(range(len(feats)))
    best = score(keep); dropped = []
    while True:
        c = [(score([k for k in keep if k != j]), j) for j in keep if j]
        if not c:
            break
        e, j = min(c)
        if e >= best - 1e-5:
            break
        keep.remove(j); best = e; dropped.append([feats[j], round(e, 5)])
    return keep, dropped


def fit_mnl_model(rows, feats, fit_yrs, test_yrs, last_yrs, all_yrs, sel_fit, sel_val, lam=2.0):
    keep, dropped = select(rows, feats, sel_fit, sel_val, lam=lam)
    F = [feats[k] for k in keep]
    tr = [x for x in rows if x[0] in fit_yrs]; te = [x for x in rows if x[0] in test_yrs]
    X = np.array([[x[1][k] for k in keep] for x in tr], float); y = np.array([x[2] for x in tr])
    mu, sd = std(X, None)
    B = mnl((X - mu) / sd, y, 3, lam=lam)
    lastm = np.array([x[0] in last_yrs[0] for x in tr])
    Br = recal(((X - mu) / sd)[lastm], y[lastm], B, 3)
    Xt = np.array([[x[1][k] for k in keep] for x in te], float); yt = np.array([x[2] for x in te])
    P = mnl_p((Xt - mu) / sd, B); Pr = mnl_p((Xt - mu) / sd, Br)
    base = np.bincount(y[lastm], minlength=3) / lastm.sum()
    ll0 = float(-np.mean(np.log(base[yt] + 1e-12)))
    test = {'n': len(yt), 'logloss': round(ll_of(P, yt), 4), 'loglossRecal': round(ll_of(Pr, yt), 4), 'base': round(ll0, 4),
            'skill': round(1 - ll_of(Pr, yt) / ll0, 3), 'dropped': dropped, 'auc': [round(auc((yt == k).astype(int), Pr[:, k]) or 0, 3) for k in range(3)],
            'aucChange': round(auc((yt > 0).astype(int), 1 - Pr[:, 0]) or 0, 3), 'rate': [round(float(v), 3) for v in np.bincount(yt, minlength=3) / len(yt)],
            'pred': [round(float(v), 3) for v in Pr.mean(0)]}
    for k in (1, 2):
        q = np.quantile(Pr[:, k], 0.9)
        test[f'top10_{k}'] = round(float((yt[Pr[:, k] >= q] == k).mean()), 3)
    test['calib1'] = [[round(float(Pr[:, 1][(Pr[:, 1] >= a) & (Pr[:, 1] < b)].mean()), 3), round(float((yt == 1)[(Pr[:, 1] >= a) & (Pr[:, 1] < b)].mean()), 3),
                       int(((Pr[:, 1] >= a) & (Pr[:, 1] < b)).sum())] for a, b in ((0, .1), (.1, .2), (.2, .35), (.35, .5), (.5, 1.01)) if ((Pr[:, 1] >= a) & (Pr[:, 1] < b)).sum()]
    al = [x for x in rows if x[0] in all_yrs]
    X = np.array([[x[1][k] for k in keep] for x in al], float); y = np.array([x[2] for x in al])
    mu, sd = std(X, None)
    B = mnl((X - mu) / sd, y, 3, lam=lam)
    lastm = np.array([x[0] in last_yrs[1] for x in al])
    B = recal(((X - mu) / sd)[lastm], y[lastm], B, 3)
    return {'feats': F, 'mu': mu.round(5).tolist(), 'sd': sd.round(5).tolist(), 'B': B.round(5).tolist(), 'n': len(al),
            'rates': {str(z): [round(float(v), 3) for v in np.bincount([x[2] for x in al if x[0] == z], minlength=3) / max(1, sum(1 for x in al if x[0] == z))] for z in sorted(all_yrs)},
            'test': test}


def fit_move(rows):
    m = fit_mnl_model(rows, MOVE_F, fit_yrs={2022, 2023, 2024}, test_yrs={2025}, last_yrs=({2024}, {2025}), all_yrs={2022, 2023, 2024, 2025},
                      sel_fit={2022, 2023}, sel_val={2024})
    m['test'].update({'train': '2022-24 offseasons', 'test': '2025->26', 'select': 'fit 2022-23, validate 2024'})
    return m


# ---- landing ---------------------------------------------------------------------------------------------------
LAND_F = ['dstr', 'dstr2', 'dstr_x_bpm', 'up_x_lowbpm', 'sameconf', 'logmi', 'near', 'follow', 'newhc', 'open', 'p6', 'p6_x_frp6']


def land_events(by, TS, raw, loc, years):
    """per move (season y -> y+1): every D-I team in y+1 except his old one, features, chosen flag"""
    ev, X, ch, info = [], [], [], []
    e = 0
    for y in years:
        if y + 1 not in by:
            continue
        nxt = {r['pid']: r for r in by[y + 1]}
        teams = sorted({r['team'] for r in by[y + 1]})
        conf = {r['team']: r['conf'] for r in by[y + 1]}
        # minutes open at each team: share of y's minutes not back in y+1
        open_ = {}
        T = defaultdict(list)
        for r in by[y]:
            T[r['team']].append(r)
        for t, ps in T.items():
            tot = sum((r['min_per'] or 0) for r in ps) or 1
            open_[t] = sum((r['min_per'] or 0) for r in ps if (nxt.get(r['pid']) or {}).get('team') != t) / tot
        coach_y1 = {t: v['coach'] for t, v in raw.get(y + 1, {}).items()}
        coach_y = {t: v['coach'] for t, v in raw.get(y, {}).items()}
        for r in by[y]:
            n = nxt.get(r['pid'])
            if not n or n['team'] == r['team'] or (r['min_per'] or 0) <= 0:
                continue
            o = r['team']
            for t in teams:
                if t == o:
                    continue
                X.append(feats_land(r, o, t, TS.get((y, t), {}).get('srs'), TS.get((y, o), {}).get('srs'), r['conf'], conf.get(t), loc.get(o), loc.get(t),
                                    coach_y.get(o) is not None and coach_y1.get(t) == coach_y.get(o),
                                    coach_y.get(t) is not None and coach_y1.get(t) is not None and coach_y.get(t) != coach_y1.get(t), open_.get(t, 0.5)))
                ev.append(e); ch.append(1 if t == n['team'] else 0)
            info.append((y, r['pid'], o, n['team']))
            e += 1
    return np.array(X, float), np.array(ev), np.array(ch), info


def feats_land(r, o, t, dsrs, osrs, oconf, dconf, ol, dl, follow, newhc, open_):
    b = max(-10.0, min(15.0, r.get('bpm') or 0.0))
    d = (dsrs if dsrs is not None else -5.0) / 10
    od = (osrs if osrs is not None else -5.0) / 10
    mi = miles(ol, dl)
    return [d, d * d, d * b / 5, max(0.0, d - od) * max(0.0, -b) / 5, float(oconf == dconf), math.log1p(mi if mi is not None else 800) - 6.5,
            float(mi is not None and mi < 150), float(follow), float(newhc), open_, float(dconf in P6), float(dconf in P6) * float(oconf in P6)]


def fit_land(by, TS, raw, loc):
    Xa, eva, cha, ia = land_events(by, TS, raw, loc, range(NIL0, 2025))
    Xt, evt, cht, it_ = land_events(by, TS, raw, loc, [2025])
    b = clogit(Xa, eva, cha, lam=1.0)
    p = clogit_p(Xt, evt, b)
    starts = np.r_[0, np.flatnonzero(np.diff(evt)) + 1]
    ranks, lp, lp0 = [], 0.0, 0.0
    for i, s0 in enumerate(starts):
        s1 = starts[i + 1] if i + 1 < len(starts) else len(evt)
        pp = p[s0:s1]; c = np.flatnonzero(cht[s0:s1])
        if not len(c):
            continue
        ranks.append(int((pp > pp[c[0]]).sum()) + 1); lp += math.log(pp[c[0]] + 1e-12); lp0 += math.log(1 / (s1 - s0))
    ranks = np.array(ranks)
    test = {'train': '2022-24 moves', 'test': '2025->26 moves', 'n': len(ranks), 'medianRank': float(np.median(ranks)), 'top10': round(float((ranks <= 10).mean()), 3),
            'top25': round(float((ranks <= 25).mean()), 3), 'teams': int(np.diff(np.r_[starts, len(evt)]).mean()),
            'llPerMove': round(lp / len(ranks), 3), 'llUniform': round(lp0 / len(ranks), 3)}
    X2, ev2, ch2, _ = land_events(by, TS, raw, loc, range(NIL0, 2026))
    b = clogit(X2, ev2, ch2, lam=1.0)
    return {'feats': LAND_F, 'b': b.round(5).tolist(), 'n': int(ev2.max() + 1), 'test': test}


# ---- vacancy ---------------------------------------------------------------------------------------------------
VAC_F = ['1', 'wp', 'vsnorm', 'srs', 'dsrs', 'ten1', 'ten2', 'logten', 'p6', 'mid_x_wp', 'ncaa', 'bid', 'cres']


def vac_rows(TS, raw, miss):
    out = []
    for y in sorted(raw):
        if y + 1 not in raw or y < 2016:
            continue
        hc_next = {v['coach']: t for t, v in raw[y + 1].items()}
        for t, v in raw[y].items():
            ts = TS.get((y, t))
            if not ts:
                continue
            c = v['coach']
            nx = raw[y + 1].get(t)
            if not nx:
                continue
            lab = 0 if nx['coach'] == c else 1 if c in hc_next else 2
            conf = conf_of(y, t)
            out.append((y, feats_vac(TS, y, t, ts['wp'], ts['srs'], v.get('ten') or 1, conf in P6, ts['ncaa'], ts['bid'], cres(miss, c, y + 1)), lab, t, c))
    return out


CONF = {}


def conf_of(y, t):
    return CONF.get((y, t)) or CONF.get((y - 1, t))


def feats_vac(TS, y, t, wp, srs, ten, p6, ncaa, bid, cr):
    srsn, wpn = prog_norm(TS, y, t)
    prev = TS.get((y - 1, t))
    ten = max(1, int(ten))
    return [1, wp - .5, wp - (wpn if wpn is not None else wp), srs / 10, (srs - prev['srs']) / 10 if prev else 0.0, float(ten == 1), float(ten == 2),
            math.log(ten), float(p6), (1 - float(p6)) * (wp - .5), min(ncaa, 4) / 2, float(bid), cr / 5]


def fit_vac(rows):
    m = fit_mnl_model(rows, VAC_F, fit_yrs=set(range(2016, 2022)), test_yrs=set(range(2022, 2026)), last_yrs=(set(range(2019, 2022)), set(range(2023, 2026))),
                      all_yrs=set(range(2016, 2026)), sel_fit=set(range(2016, 2020)), sel_val={2020, 2021})
    m['test'].update({'train': '2016-21', 'test': '2022-25', 'select': 'fit 2016-19, validate 2020-21'})
    return m


# ---- hires -----------------------------------------------------------------------------------------------------
HIRE_F = ['step', 'step2', 'down', 'wp', 'srs', 'cres', 'sameconf', 'logmi', 'ten', 'p6up']


def hire_events(TS, raw, miss, loc, years):
    X, ev, ch, info = [], [], [], []
    e = 0; srcs = Counter()
    for y in years:
        if y + 1 not in raw:
            continue
        sit = {v['coach']: t for t, v in raw[y].items()}
        for t, v in raw[y + 1].items():
            old = raw[y].get(t)
            if not old or old['coach'] == v['coach']:
                continue
            frm = sit.get(v['coach'])
            srcs['hc' if frm else 'other'] += 1
            if not frm:
                continue
            for c, s in sit.items():
                if s == t:
                    continue
                X.append(feats_hire(TS, y, t, s, cres(miss, c, y + 1), loc, raw[y][s].get('ten') or 1))
                ev.append(e); ch.append(1 if c == v['coach'] else 0)
            info.append((y, t, v['coach'], frm))
            e += 1
    return np.array(X, float), np.array(ev), np.array(ch), info, srcs


def feats_hire(TS, y, t, s, cr, loc, ten):
    lt, _ = prog_norm(TS, y + 1, t); ls, _ = prog_norm(TS, y + 1, s)
    lt = lt if lt is not None else -5.0; ls = ls if ls is not None else -5.0
    st = (lt - ls) / 10
    ts = TS.get((y, s), {})
    mi = miles(loc.get(t), loc.get(s))
    return [st, st * st, max(0.0, -st), ts.get('wp', .5) - .5, ts.get('srs', -5.0) / 10, cr / 5, float(conf_of(y, t) == conf_of(y, s)),
            math.log1p(mi if mi is not None else 800) - 6.5, min(10, ten) / 10, float(conf_of(y, t) in P6 and conf_of(y, s) not in P6)]


def fit_hires(TS, raw, miss, loc):
    Xa, eva, cha, _, src_a = hire_events(TS, raw, miss, loc, range(2016, 2022))
    Xt, evt, cht, _, _ = hire_events(TS, raw, miss, loc, range(2022, 2026))
    b = clogit(Xa, eva, cha, lam=1.0)
    p = clogit_p(Xt, evt, b)
    starts = np.r_[0, np.flatnonzero(np.diff(evt)) + 1]
    ranks = []
    for i, s0 in enumerate(starts):
        s1 = starts[i + 1] if i + 1 < len(starts) else len(evt)
        pp = p[s0:s1]; c = np.flatnonzero(cht[s0:s1])
        if len(c):
            ranks.append(int((pp > pp[c[0]]).sum()) + 1)
    ranks = np.array(ranks)
    X2, ev2, ch2, _, srcs = hire_events(TS, raw, miss, loc, range(2016, 2026))
    b = clogit(X2, ev2, ch2, lam=1.0)
    return {'feats': HIRE_F, 'b': b.round(5).tolist(), 'n': int(ev2.max() + 1), 'fromHC': round(srcs['hc'] / max(1, sum(srcs.values())), 3),
            'test': {'train': '2016-21 hires', 'test': '2022-25 hires', 'n': len(ranks), 'medianRank': float(np.median(ranks)),
                     'top10': round(float((ranks <= 10).mean()), 3), 'top3': round(float((ranks <= 3).mean()), 3), 'pool': int(np.diff(np.r_[starts, len(evt)]).mean())}}


# ---- coach pay value -------------------------------------------------------------------------------------------
UT_ALIAS = {'uconn': 'Connecticut', 'ole miss': 'Mississippi', 'nc state': 'N.C. State', 'north carolina state': 'N.C. State', 'lsu': 'LSU', 'ucf': 'UCF', 'usc': 'USC', 'ucla': 'UCLA',
            'miami (fla.)': 'Miami FL', 'miami': 'Miami FL', 'miami (ohio)': 'Miami OH', 'pitt': 'Pittsburgh', 'unlv': 'UNLV', 'utep': 'UTEP', 'uab': 'UAB',
            'vcu': 'VCU', 'byu': 'BYU', 'smu': 'SMU', 'tcu': 'TCU', 'fiu': 'FIU', 'fau': 'Florida Atlantic', 'umass': 'Massachusetts',
            'louisiana-monroe': 'Louisiana Monroe', 'ul monroe': 'Louisiana Monroe', 'southern miss': 'Southern Miss', 'app state': 'Appalachian St.',
            'appalachian state': 'Appalachian St.', 'texas a&m': 'Texas A&M', 'utsa': 'UTSA', 'unc greensboro': 'UNC Greensboro', 'uncg': 'UNC Greensboro',
            'unc wilmington': 'UNC Wilmington', 'unc asheville': 'UNC Asheville', 'charlotte': 'Charlotte', 'little rock': 'Little Rock',
            'texas-arlington': 'UT Arlington', 'ut arlington': 'UT Arlington', 'cal state fullerton': 'Cal St. Fullerton', 'long beach state': 'Long Beach St.',
            'umbc': 'UMBC', 'iupui': 'IU Indy', 'siue': 'SIU Edwardsville', 'liu': 'LIU', 'uic': 'Illinois Chicago'}


def team_key(s):
    import re
    s = (s or '').lower().replace('&amp;', '&').strip()
    s = re.sub(r'\bstate\b', 'st', s)
    s = re.sub(r'\bst\.', 'st', s)
    return re.sub(r'[^a-z&]', '', s)


def match_team(name, names):
    if not name:
        return None
    a = UT_ALIAS.get(name.lower().strip())
    if a and a in names:
        return a
    k = team_key(name)
    idx = {team_key(n): n for n in names}
    return idx.get(k)


VAL_F = ['p6', 'lvl', 'wp1', 'wp3', 'srs1', 'ncaa3', 'bid3', 'ten', 'cres']


def val_feats(TS, y, t, ten, cr, p6):
    """pay for season y set on what was known going in: results through y-1, program level, tenure"""
    lvl, _ = prog_norm(TS, y, t, k=5)
    r1 = TS.get((y - 1, t), {})
    r3 = [TS[(z, t)] for z in range(y - 3, y) if (z, t) in TS]
    return [float(p6), (lvl if lvl is not None else -5.0) / 10, r1.get('wp', .5) - .5, (np.mean([x['wp'] for x in r3]) if r3 else .5) - .5,
            r1.get('srs', -5.0) / 10, sum(x['ncaa'] for x in r3) / 3, sum(x['bid'] for x in r3) / 3, min(10, ten) / 10, cr / 5]


def ridge(X, y, lam):
    A = X.T @ X + lam * np.diag([0] + [1] * (X.shape[1] - 1))
    return np.linalg.solve(A, X.T @ y)


def fit_value(TS, raw, miss):
    src = json.load(gzip.open(SRC))['pay']
    names = {t for (_, t) in TS}
    rows = []
    unmatched = Counter()
    for r in src['list']:
        t = match_team(r['school'], names)
        if not t:
            unmatched[r['school']] += 1
            continue
        for y, cid, nm, pay in src['schools'].get(r['sid'], []):
            if not pay or y < 2015 or y > 2026:
                continue
            co = raw.get(y, {}).get(t)
            ten = co.get('ten') if co else 3
            rows.append((y, t, cid, nm, math.log(pay), val_feats(TS, y, t, ten or 3, cres(miss, co['coach'], y) if co else 0.0, conf_of(y, t) in P6 if conf_of(y, t) else True)))
    yrs = sorted({r[0] for r in rows})
    schools = sorted({r[1] for r in rows})

    def design(rs, keep):
        return np.array([[1.0] + [float(r[0] == z) for z in yrs[1:]] + [r[5][VAL_F.index(k)] for k in keep] for r in rs])

    yv = np.array([r[4] for r in rows])

    def loso(keep, lam=1.0):
        err = []
        for s in schools:
            m = np.array([r[1] == s for r in rows])
            X = design(rows, keep)
            b = ridge(X[~m], yv[~m], lam)
            err.extend((X[m] @ b - yv[m]).tolist())
        return float(np.sqrt(np.mean(np.square(err))))

    keep, best = [], loso([])
    base = best
    steps = []
    while True:
        cand = [(loso(keep + [k]), k) for k in VAL_F if k not in keep]
        if not cand:
            break
        e, k = min(cand)
        if e >= best - 1e-4:
            break
        keep.append(k); best = e; steps.append([k, round(e, 4)])
    X = design(rows, keep)
    b = ridge(X, yv, 1.0)
    ss = float(np.sum((yv - yv.mean()) ** 2))
    return {'feats': keep, 'years': yrs, 'b': b.round(5).tolist(), 'n': len(rows), 'schools': len(schools), 'looRmse': round(best, 4), 'baseRmse': round(base, 4),
            'looR2': round(1 - best ** 2 * len(rows) / ss, 3), 'steps': steps, 'unmatched': sorted(unmatched)}


def main():
    by = player_rows(write=True)
    for y, rs in by.items():
        for r in rs:
            CONF[(y, r['team'])] = r['conf']
    TS, bt = team_seasons()
    loc = geo(bt)
    raw, miss = coaches()
    print('player seasons', {y: len(v) for y, v in sorted(by.items()) if y >= 2021}, 'team seasons', len(TS), 'located', len(loc), flush=True)
    mr = move_rows(by, TS, raw)
    move = fit_move(mr)
    print('move', json.dumps(move['test']), flush=True)
    land = fit_land(by, TS, raw, loc)
    print('land', json.dumps(land['test']), dict(zip(LAND_F, land['b'])), flush=True)
    vac = fit_vac(vac_rows(TS, raw, miss))
    print('vacancy', json.dumps(vac['test']), flush=True)
    hires = fit_hires(TS, raw, miss, loc)
    print('hires', json.dumps(hires['test']), hires['fromHC'], dict(zip(HIRE_F, hires['b'])), flush=True)
    value = fit_value(TS, raw, miss)
    print('value', {k: value[k] for k in ('feats', 'n', 'schools', 'looRmse', 'baseRmse', 'looR2', 'steps', 'unmatched')}, flush=True)
    # development: next-season BPM change for returners by class (NIL era), for the team builder
    dev = defaultdict(list)
    for y in range(NIL0, 2026):
        nx = {r['pid']: r for r in by.get(y + 1, [])}
        for r in by[y]:
            n = nx.get(r['pid'])
            if n and (r['min_per'] or 0) >= 20 and (n['min_per'] or 0) >= 20 and r['bpm'] is not None and n['bpm'] is not None:
                dev[r['yr']].append(n['bpm'] - r['bpm'])
    devc = {k: round(float(np.mean(v)), 2) for k, v in dev.items()}
    # transfers: next-season BPM change on the step in team strength (SRS / 10, new team's season before minus old
    # team's), net of the class change; NIL era, 20%+ minutes both seasons
    X, yv = [], []
    for y in range(NIL0, 2026):
        nx = {r['pid']: r for r in by.get(y + 1, [])}
        for r in by[y]:
            n = nx.get(r['pid'])
            if n and n['team'] != r['team'] and (r['min_per'] or 0) >= 20 and (n['min_per'] or 0) >= 20 and r['bpm'] is not None and n['bpm'] is not None:
                a, b = TS.get((y, n['team'])), TS.get((y, r['team']))
                if a and b:
                    X.append([1.0, (a['srs'] - b['srs']) / 10]); yv.append(n['bpm'] - r['bpm'] - devc.get(r['yr'], 0.5))
    X = np.array(X); yv = np.array(yv)
    bt_ = np.linalg.lstsq(X, yv, rcond=None)[0]
    se = float(np.sqrt(np.sum((yv - X @ bt_) ** 2) / (len(yv) - 2) * np.linalg.inv(X.T @ X)[1, 1]))
    step = {'a': round(float(bt_[0]), 3), 'b': round(float(bt_[1]), 3), 'se': round(se, 3), 'n': len(yv)}
    print('transfer step', step)
    # freshmen: first-season BPM on recruiting rank (-ln rank), NIL era, minutes-weighted
    fr = [(r['rg_lrk'], r['bpm'], r['min_per']) for y in range(NIL0, 2027) for r in by.get(y, []) if r['yr'] == 'Fr' and r['rg_lrk'] is not None and r['bpm'] is not None and (r['min_per'] or 0) >= 10]
    A = np.array([[1, a] for a, _, _ in fr]); w = np.array([m for _, _, m in fr]); yb = np.array([b for _, b, _ in fr])
    frc = np.linalg.solve((A * w[:, None]).T @ A, (A * w[:, None]).T @ yb)
    frm = np.array([[1, a] for a, _, _ in fr]); frm_c = np.linalg.lstsq(frm, np.array([m for _, _, m in fr]), rcond=None)[0]
    # minutes by rank within the team (NIL era): the builder's rotation
    ms = defaultdict(list)
    for y in range(NIL0, 2027):
        T = defaultdict(list)
        for r in by.get(y, []):
            T[r['team']].append(r['min_per'] or 0)
        for v in T.values():
            for i, m in enumerate(sorted(v, reverse=True)[:13]):
                ms[i].append(m / 100)
    minsched = [round(float(np.mean(ms[i])), 3) for i in range(13)]
    out = {'asof': __import__('time').strftime('%Y-%m-%d'), 'minsched': minsched, 'move': move, 'land': land, 'vacancy': vac, 'hires': hires, 'value': value,
           'dev': devc, 'step': step, 'fresh': {'bpm': frc.round(4).tolist(), 'min': frm_c.round(4).tolist(), 'n': len(fr)},
           '_readme': 'scripts/cbb_market_fit.py: Transfer% (move), landing, coaching vacancies, hires, coach pay value; NIL-era player models'}
    with open(OUT, 'w') as h:
        json.dump(out, h, separators=(',', ':'))
    print('dev', devc, 'fresh', out['fresh'])


if __name__ == '__main__':
    main()
