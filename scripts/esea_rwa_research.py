#!/usr/bin/env python3
"""1NT RWA (Nov 3 2026): round win % added per round for ESEA league players, the pro CS2 rating
(scripts/cs2_players.py) ported to FACEIT box lines, and its test against the shipped player Elo.

    python3 scripts/esea_rwa_research.py           # reads research/esea_matches.json.gz -> data/esea_rwa_fit.json (~15 min)
    python3 scripts/esea_rwa_research.py --fixed   # same tests at the saved settings (no grid)

RWA:
  1. Stat weights: a team's round share on a map regressed on the sum of its five per-round lines (kills, deaths,
     assists, ADR, multi-kill rounds, opening kills, opening deaths, clutch wins, utility damage, enemies flashed),
     fit on the tune seasons. FACEIT has no KAST, trades or round-by-round data; MVPs are left out (they go to
     round winners). A player's line x weights minus the average line's, x100, is his round win % added; the five
     sum to the team's round share above .5, plus pm x (the team's residual) / 5.
  2. Opponents: each line is credited with the opposing five's mean rating (x opp), solved iteratively.
  3. Prior: g x the player's decayed mean division level (Open -2 .. Advanced +1) + nu; every division's lines are
     zero-sum and divisions barely meet, so the prior is what sets each division's level.
  4. Decay half-life h days, shrink k rounds toward the prior; a player with no maps = g x the match division + nu.
Walk forward: ratings at each Monday predict that week's matches (first map's five). Grid on S54-S57 match log
loss; held S58-S59 against the shipped player Elo (scripts/esea_standin_research.py C2) and FACEIT level.
"""
import datetime as dt
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esea_standin_research as SR  # noqa: E402
import esea_ark_research as ARK  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'esea_rwa_fit.json')
STATS = ['k', 'd', 'a', 'adr', 'mk', 'fk', 'fd', 'cl', 'ud', 'ef']
PELO = dict(K=128, Kmin=26, n0=50, span=0.5, kmap=1.0, mu_new=-100, gap=100)   # shipped (PR #755)
TUNE, HELD = (54, 57), (58, 59)
DAY = 86400


def line(p):
    """FACEIT archive row [id, k, d, a, adr, full26] -> totals in STATS order (adr stays a per-round rate)"""
    f = p[5] if len(p) > 5 and p[5] else None
    if not f:
        return None
    return [f[0], f[6], f[7], f[8], f[9] + f[10] + f[11] + f[12], f[13], f[2] - f[13], f[14] + f[15], f[16], f[17]]


class Maps:
    def __init__(self, ms):
        P, X, R, D, G, S, Y, DV, A = [], [], [], [], [], [], [], [], []
        self.pid = {}
        self.games = []          # (match index, map index)
        five = []
        for mi, m in enumerate(ms):
            for mp in m['maps']:
                rr = mp['s1'] + mp['s2']
                if rr < 13:
                    continue
                lines = [[line(p) for p in mp['p1']], [line(p) for p in mp['p2']]]
                if any(x is None for s in lines for x in s):
                    continue
                gi = len(self.games)
                self.games.append(mi)
                fv = [[], []]
                for side, ps in enumerate((mp['p1'], mp['p2'])):
                    y = (mp['s1'] if side == 0 else mp['s2']) / rr
                    rf, ra = (mp['s1'], mp['s2']) if side == 0 else (mp['s2'], mp['s1'])
                    full = [p[5] for p in ps]
                    cred = ARK.credit_of(full, rr, rf, ra)
                    for p, ln, cr in zip(ps, lines[side], cred):
                        A.append([ARK.feats(ARK.counts(p[5], rr, rf, ra, 0))[f] for f in ARK.FEATS] + [cr])
                        q = self.pid.setdefault(p[0], len(self.pid))
                        fv[side].append(len(P))
                        P.append(q)
                        X.append([v / rr if j != 3 else v for j, v in enumerate(ln)])
                        R.append(rr)
                        D.append(m['at'])
                        G.append(gi)
                        S.append(side)
                        Y.append(y)
                        DV.append(m['div_r'])
                five.append(fv)
        self.p, self.X, self.R, self.d = np.array(P), np.array(X, float), np.array(R, float), np.array(D, float)
        self.g, self.side, self.y, self.dv = np.array(G), np.array(S), np.array(Y), np.array(DV, float)
        self.A = np.array(A, float)   # ARK features (live ARK 2 order) + the page's outcome credit
        self.five = five
        self.gseason = np.array([ms[mi]['season'] for mi in self.games])
        # opponents' rows, for the opponent-credit mean (variable team sizes)
        n = len(self.p)
        self.opp_cnt = np.zeros(n)
        idx_a, idx_b = [], []
        for fv in five:
            for s in (0, 1):
                for i in fv[s]:
                    for j in fv[1 - s]:
                        idx_a.append(i)
                        idx_b.append(j)
        self.oa, self.ob = np.array(idx_a), np.array(idx_b)
        self.opp_cnt = np.bincount(self.oa, minlength=n).astype(float)
        print(f'maps {len(self.games)}, player-maps {n}, players {len(self.pid)}', file=sys.stderr)


def stat_weights(M, gmask, l2=1e-4):
    rows = np.where(gmask[M.g])[0]
    key = M.g[rows] * 2 + M.side[rows]
    uk, inv = np.unique(key, return_inverse=True)
    Xs = np.zeros((len(uk), M.X.shape[1]))
    np.add.at(Xs, inv, M.X[rows])
    cnt = np.bincount(inv)
    ok = cnt == 5
    ys = np.zeros(len(uk))
    ys[inv] = M.y[rows]
    X, y = Xs[ok], ys[ok]
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    w = np.linalg.solve(Z.T @ Z + l2 * len(X) * np.diag([0] + [1] * (Z.shape[1] - 1)), Z.T @ y)
    r2 = 1 - ((Z @ w - y) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return w[1:] / sd, mu / 5, float(r2), int(ok.sum())


def contributions(M, beta, mline, pm):
    c = (M.X - mline) @ beta * 100
    if pm:
        key = M.g * 2 + M.side
        tot = np.bincount(key, c, len(M.games) * 2)
        cnt = np.bincount(key, None, len(M.games) * 2)
        c = c + pm * (100 * (M.y - 0.5) - tot[key]) / cnt[key]
    return c


def ark_values(M, gmask):
    """ARK Rating as the page computes it (data/esea_ark_research.json beta_live weights, outcome credit), x100:
    round win % added per round over the average line, no opponent or division terms"""
    beta = json.load(open(os.path.join(ROOT, 'data', 'esea_ark_research.json')))['beta_live']
    b = np.array([beta[f] for f in ARK.FEATS])
    F = M.A[:, :-1]
    mu = F[gmask[M.g]].mean(0)
    return ((F - mu) @ b + M.A[:, -1]) * 100


def ratings(M, c, T, p):
    """-> (theta incl. division lift, rounds weight) per player from rows before T"""
    n = len(M.pid)
    m = M.d < T
    w = M.R * np.exp(-(T - M.d) / DAY * math.log(2) / p['h']) * m
    wsum = np.bincount(M.p, w, n)
    dlev = np.bincount(M.p, w * M.dv, n) / np.maximum(wsum, 1e-9)
    prior = p['g'] * dlev + p['nu']
    theta = prior.copy()
    for _ in range(8):
        th = theta[M.p]
        opp = np.bincount(M.oa, th[M.ob], len(M.p)) / np.maximum(M.opp_cnt, 1)
        adj = c + p['opp'] * opp
        theta = (np.bincount(M.p, w * adj, n) + p['k'] * prior) / (wsum + p['k'])
    return theta, wsum


def weekly(ms):
    """Monday 00:00 UTC cutoffs covering the matches"""
    t0 = dt.datetime.fromtimestamp(ms[0]['at'], dt.timezone.utc).date()
    t0 -= dt.timedelta(days=t0.weekday())
    out, t = [], dt.datetime(t0.year, t0.month, t0.day, tzinfo=dt.timezone.utc).timestamp()
    while t <= ms[-1]['at']:
        out.append(t)
        t += 7 * DAY
    return out


def rwa_gaps(ms, M, c, p, cuts):
    """match id -> (sum theta five1 - sum theta five2) / 100, ratings from before the match's week"""
    out = {}
    j = 0
    pidx = M.pid
    for k, T in enumerate(cuts):
        T2 = cuts[k + 1] if k + 1 < len(cuts) else 9e12
        week = []
        while j < len(ms) and ms[j]['at'] < T2:
            if ms[j]['at'] >= T:
                week.append(ms[j])
            j += 1
        if not week:
            continue
        th, ws = ratings(M, c, T, p)

        def val(q, m):
            i = pidx.get(q)
            if i is None or ws[i] <= 0:
                return p['g'] * m['div_r'] + p['nu']
            return th[i]
        for m in week:
            a = sum(val(q, m) for q in m['five1'][:5]) / len(m['five1'][:5]) * 5
            b = sum(val(q, m) for q in m['five2'][:5]) / len(m['five2'][:5]) * 5
            out[m['id']] = (a - b) / 100
    return out


def rows_of(ms, feats):
    rows = []
    for m in ms:
        if m['season'] <= SR.BURN or any(m['id'] not in f for f in feats.values()):
            continue
        r = {'id': m['id'], 'y': m['y'], 'season': m['season']}
        for k, f in feats.items():
            r[k] = f[m['id']]
        rows.append(r)
    return rows


def tune_ll(rows, cols):
    _, lls = SR.split_fit(rows, cols, TUNE, TUNE)
    return sum(lls.values()) / len(lls)


def main():
    d, ms = SR.load()
    M = Maps(ms)
    cuts = weekly(ms)
    tune_g = (M.gseason >= 53) & (M.gseason <= TUNE[1])
    beta, ml, r2, nfit = stat_weights(M, tune_g)
    print('weights', dict(zip(STATS, np.round(beta, 4))), 'r2', round(r2, 3), file=sys.stderr)
    res = {'asof': d.get('asof'), 'stats': STATS, 'beta': {k: round(float(b), 5) for k, b in zip(STATS, beta)},
           'mline': [round(float(x), 5) for x in ml], 'weights_r2': round(r2, 3), 'weights_n': nfit}

    # player Elo (shipped) + FACEIT level of the five, as in the C2 test
    gp, _ = SR.run_pelo(ms, **PELO)
    lvd = {}
    for m in ms:
        def lv(f):
            v = [m['lv'].get(q) for q in f[:5] if m['lv'].get(q)]
            return sum(v) / len(v) if v else None
        a, b = lv(m['five1']), lv(m['five2'])
        if a is not None and b is not None:
            lvd[m['id']] = a - b

    cs = {pm: contributions(M, beta, ml, pm) for pm in (0.0, 0.5, 1.0)}
    quick = '--quick' in sys.argv

    def search(c_of, space, fixed):
        grid = []
        keys = list(space)
        import itertools
        for vals in itertools.product(*[space[k] for k in keys]):
            p = dict(fixed, **dict(zip(keys, vals)))
            rg = rwa_gaps(ms, M, c_of(p), p, cuts)
            v = tune_ll(rows_of(ms, {'x': rg}), ['x'])
            grid.append((v, p))
            print(p, round(v, 4), file=sys.stderr)
        grid.sort(key=lambda x: x[0])
        return grid
    one = lambda xs: xs[:1] if quick else xs
    old = json.load(open(OUT)) if '--fixed' in sys.argv and os.path.exists(OUT) else None   # rerun at the saved settings

    def pin(space, keys):
        if not old:
            return space
        out = {k: sorted({old[kk][k] for kk in keys if k in old.get(kk, {})}) or v for k, v in space.items()}
        return out
    av = ark_values(M, tune_g)
    cw = lambda p: cs[p['pm']] if p['w'] == 'ols' else av
    gr = search(cw, pin({'w': ['ark', 'ols'], 'h': [100000], 'k': one([15, 50]), 'pm': [0.0],
                         'g': one([2.0, 4.0]), 'nu': one([-3.0, -1.0])}, ('params', 'params_ols')), {'opp': 1.0})
    best = gr[0][1]
    res['grid_top'] = old['grid_top'] if old else [{**p, 'tune_ll': round(v, 4)} for v, p in gr[:6]]
    res['params'] = best
    rg = rwa_gaps(ms, M, cw(best), best, cuts)
    bo = next(p for v, p in gr if p['w'] == 'ols')
    res['params_ols'] = bo
    rgo = rwa_gaps(ms, M, cw(bo), bo, cuts)
    # ARK Rating (the page's 1NTERLYTICS player rating) through the same walk-forward, its own h/k tuned, no
    # opponent or division terms (as the page shows it)
    ga = search(lambda p: av, pin({'h': one([100000, 365]), 'k': one([50, 150]), 'nu': [0.0]}, ('ark_params',)), {'opp': 0.0, 'g': 0.0, 'pm': 0.0})
    res['ark_params'] = ga[0][1]
    res['ark_grid_top'] = old['ark_grid_top'] if old else [{**p, 'tune_ll': round(v, 4)} for v, p in ga[:4]]
    ra = rwa_gaps(ms, M, av, ga[0][1], cuts)

    rows = rows_of(ms, {'rwa': rg, 'ark': ra, 'rwa_ols': rgo, 'pelo': gp, 'lv': lvd})
    held = {}
    sets = {'pelo': ['pelo'], 'rwa': ['rwa'], 'ark': ['ark'], 'rwa_ols': ['rwa_ols'], 'pelo+rwa': ['pelo', 'rwa'],
            'pelo+ark': ['pelo', 'ark'], 'pelo+lv': ['pelo', 'lv'], 'pelo+lv+rwa': ['pelo', 'lv', 'rwa'],
            'pelo+lv+ark': ['pelo', 'lv', 'ark'], 'rwa+lv': ['rwa', 'lv'], 'ark+lv': ['ark', 'lv']}
    L = {}
    for name, cols in sets.items():
        b, lls = SR.split_fit(rows, cols, TUNE, HELD)
        L[name] = lls
        held[name] = {'coef': [round(x, 3) for x in b], 'held_ll': round(sum(lls.values()) / len(lls), 4), 'n': len(lls)}
    res['held'] = held
    hr = [r for r in rows if HELD[0] <= r['season'] <= HELD[1]]

    def t(a, b):
        return {**SR.paired(L[a], L[b]), 'seasons': SR.season_folds(L[a], L[b], hr)}
    res['tests'] = {
        'rwa_vs_ark': t('rwa', 'ark'), 'rwa_ols_vs_ark': t('rwa_ols', 'ark'), 'rwa_vs_rwa_ols': t('rwa', 'rwa_ols'),
        'rwa_vs_pelo': t('rwa', 'pelo'), 'ark_vs_pelo': t('ark', 'pelo'),
        'pelo+rwa_vs_pelo': t('pelo+rwa', 'pelo'), 'pelo+ark_vs_pelo': t('pelo+ark', 'pelo'),
        'pelo+lv+rwa_vs_pelo+lv': t('pelo+lv+rwa', 'pelo+lv'), 'pelo+lv+ark_vs_pelo+lv': t('pelo+lv+ark', 'pelo+lv'),
        'rwa+lv_vs_ark+lv': t('rwa+lv', 'ark+lv'),
    }
    # split-half reliability (odd vs even maps per player, S58-S59, 300+ rounds each half): how much is signal
    rel = {}
    for name, v in (('ols', cs[0.0]), ('ark', av)):
        hm = M.gseason[M.g] >= HELD[0]
        par = M.g % 2
        out = []
        for half in (0, 1):
            sel = hm & (par == half)
            w = np.bincount(M.p[sel], M.R[sel], len(M.pid))
            out.append((np.bincount(M.p[sel], M.R[sel] * v[sel], len(M.pid)) / np.maximum(w, 1), w))
        ok = (out[0][1] >= 300) & (out[1][1] >= 300)
        rel[name] = {'r': round(float(np.corrcoef(out[0][0][ok], out[1][0][ok])[0, 1]), 3), 'players': int(ok.sum())}
    res['split_half'] = rel
    # the page's own S59 preview inputs (data/esea.json history, as in the C2 test): does RWA add to elo/talent + pelo?
    snaps = SR.snapshots()
    live = []
    for m in ms:
        if m['season'] != 59 or not snaps or m['id'] not in rg:
            continue
        prior = [x for x in snaps if x[0] < m['at'] - 60]
        if not prior:
            continue
        S = prior[-1][1]
        a, b = S.get(m['f1']['id']), S.get(m['f2']['id'])
        if not a or not b or not a.get('elo') or not b.get('elo'):
            continue
        ta, tb = (a.get('talent') or {}).get('exact'), (b.get('talent') or {}).get('exact')
        pe = 1 / (1 + 10 ** (-(a['elo'] - b['elo']) / 600))
        pv = SR.sig(0.8 * SR.lg(pe) + 0.2 * SR.lg(SR.sig(0.48 * (ta - tb)))) if ta is not None and tb is not None else pe
        live.append({'id': m['id'], 'y': m['y'], 'season': 59, 'day': m['at'] // 86400, 'pv': SR.lg(pv), 'prs': gp[m['id']], 'rwa': rg[m['id']]})
    LV = {'n': len(live)}
    if len(live) >= 30:
        base = SR.lodo(live, ['pv', 'prs'])
        for name, cols in (('pv+prs+rwa', ['pv', 'prs', 'rwa']), ('pv+rwa', ['pv', 'rwa']), ('rwa', ['rwa'])):
            B = SR.lodo(live, cols)
            full = SR.logit_fit([[r[c] for c in cols] for r in live], [r['y'] for r in live])
            LV[name] = {'lodo_vs_pv+prs': SR.paired(B, base), 'coef': [round(x, 3) for x in full]}
        LV['as_is'] = SR.paired(SR.lodo(live, ['pv', 'prs', 'rwa']), {r['id']: SR.ll(SR.sig(0.746 * r['pv'] + 4.792 * r['prs']), r['y']) for r in live})
        # model coefficients for the preview: pv + prs + rwa on the held seasons' scale (S58-S59 research rows), pv
        # from the live set
    res['live_s59'] = LV
    print('live', LV, file=sys.stderr)
    tt = res['tests']['rwa_vs_ark']
    res['head'] = 'rwa' if tt['t'] < -2 and int(tt['seasons'].split('/')[0]) * 2 > int(tt['seasons'].split('/')[1]) else 'ark'
    res['note'] = 'held = fit on S54-S57, scored on S58-S59 matches; t < -2 and most seasons = passes'
    for k, v in res['tests'].items():
        print(k, v, file=sys.stderr)
    json.dump(res, open(OUT, 'w'), indent=1)
    print('wrote', OUT, file=sys.stderr)


if __name__ == '__main__':
    main()
