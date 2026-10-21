#!/usr/bin/env python3
"""Shape of the result around the line, every sport (Noah, Oct 21 2026: "factor in anything we aren't factoring in
regarding mean" vs median, skew and key numbers). Research only; writes data/skew_research.json.

    python3 scripts/skew_research.py

A. The final margin / total around the CLOSE (what scripts/clv.py prices every bet, CLV and Dengler Unit on). Each
   candidate is a probability on the integers around the close C: f(k - C), times a key weight by |k| (football margins:
   3, 7, 10, 14; tested for every sport and for totals too), a tie at 0 impossible in basketball (overtime).
       base   production: clv.pmf (discretized normal, sd from clv_fit.json / SD0, football margin keys)
       N      normal, sd refit on the tuning seasons
       T      Student t, scale and df refit
       KDE    the tuning seasons' own residuals, smoothed (carries their skew and tails)
       +key   key weights by |k| refit on the tuning seasons with that shape
   Scores, held-out seasons, paired against base with game days as clusters (scripts/harness.py):
       logs   -log P(result): the whole distribution
       cover  binary log loss of result > X at lines X = C +- 0.5..7 (pushes out): what a bet away from the close is
              priced at, i.e. what CLV and DU read
B. The model's total is a MEAN and the closing total sits at the MEDIAN: right-skewed totals (skew +.2 to +.3 around the
   close) put the mean ~0.4-0.9 points over it, so mean-minus-line leans to overs. Tested: the over chance from
   Phi(b (gap - d) / s) with d = the tuning seasons' mean-minus-median of the result around the model.
D. Football key numbers from our own history: the share of games decided by exactly each margin and the push chance
   when the close sits on it (what a half point there is worth).
C. The cover chance the NFL/NBA tables show (scripts/cover.py, Phi(b gap / s)) against the same chance read off the
   key-number distribution (clv.chances at the close the gap implies).
"""
import gzip
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clv as C  # noqa: E402
import harness as H  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'skew_research.json')
W = 110                                   # pmf window around the close, points
OFFS = [d / 2 for d in range(1, 15)]      # cover lines at C +- 0.5..7
SPORTS = ('nfl', 'cfb', 'nba', 'cbb')
KA = C.KA


def load(sport):
    return json.load(gzip.open(os.path.join(C.WF, sport + '.json.gz')))


def split(S):
    ss = sorted(set(S))
    held = ss[-1:] if len(ss) <= 3 else ss[-3:]
    return np.isin(S, ss[:len(ss) - len(held)]), np.isin(S, held), held


def ncdf(z):
    return 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))


def t_pdf(x, df):
    return (1 + x * x / df) ** (-(df + 1) / 2)


class Shape:
    """a residual shape on the half-point grid; dens(r) for residuals r = k - C"""

    def __init__(self, kind, **p):
        self.kind, self.p = kind, p
        self.grid = np.arange(-2 * W, 2 * W + 1) / 2.0
        if kind == 'N':
            g = self.grid / p['sd']
            self.d = ncdf(g + 0.5 / p['sd']) - ncdf(g - 0.5 / p['sd'])
        elif kind == 'T':
            self.d = t_pdf(self.grid / p['s'], p['df'])
        elif kind == 'KDE':
            r, h = p['res'], p['h']
            # gaussian KDE on the grid, from a histogram of the residuals on the same grid (fast, exact on the grid)
            hist = np.zeros(len(self.grid))
            ix = np.clip(np.round((r + W) * 2).astype(int), 0, len(self.grid) - 1)
            np.add.at(hist, ix, 1.0)
            ker = np.exp(-0.5 * (np.arange(-60, 61) / 2.0 / h) ** 2)
            self.d = np.convolve(hist, ker, mode='same') + 1e-9
        self.d = self.d / self.d.sum()

    def at(self, r):
        return self.d[np.clip(np.round((r + W) * 2).astype(int), 0, len(self.grid) - 1)]


def pmfs(cen, shape, key=None, notie=False, lo=None, scale=None):
    """rows x (2W+1) probabilities on k = round(C) + offs"""
    offs = np.arange(-W, W + 1)
    base = np.round(cen).astype(int)
    K = base[:, None] + offs[None, :]
    r = K - cen[:, None]
    P = shape.at(r)
    if key is not None:
        P = P * key[np.minimum(np.abs(K), len(key) - 1)]
    if notie:
        P = np.where(K == 0, 0.0, P)
    if lo is not None:
        P = np.where(K < lo, 0.0, P)
    P = P / P.sum(1, keepdims=True)
    return K, P


def fit_key(K, P, res, tune, n, absval=True):
    obs, ex = np.zeros(n + 1), np.zeros(n + 1)
    a = np.minimum(np.abs(res[tune]).astype(int), n) if absval else np.minimum(res[tune].astype(int), n)
    np.add.at(obs, a, 1)
    kk = np.minimum(np.abs(K[tune]), n) if absval else np.clip(K[tune], 0, n)
    np.add.at(ex, kk.ravel(), P[tune].ravel())
    return (obs + KA) / (ex + KA)


def scores(K, P, res, cen):
    """per-row log score and mean cover log loss over the off-close lines"""
    j = (res - K[:, 0]).astype(int)
    ok = (j >= 0) & (j < K.shape[1])
    pr = np.where(ok, P[np.arange(len(res)), np.clip(j, 0, K.shape[1] - 1)], 1e-9)
    logs = -np.log(np.maximum(pr, 1e-9))
    cum = np.cumsum(P, 1)                 # P(result <= K)
    ll, cnt = np.zeros(len(res)), np.zeros(len(res))
    for d in OFFS:
        for sg in (1, -1):
            X = cen + sg * d
            if np.all(X == np.round(X)):
                pass
            # P(result > X) = 1 - P(result <= floor(X)); push when X integer and result == X
            fx = np.floor(X).astype(int)
            jx = np.clip(fx - K[:, 0], -1, K.shape[1] - 1)
            le = np.where(jx >= 0, cum[np.arange(len(res)), np.maximum(jx, 0)], 0.0)
            push_p = np.where((X == fx) & (jx >= 0), P[np.arange(len(res)), np.maximum(jx, 0)], 0.0)
            pw = 1 - le
            pl = le - push_p
            p = pw / np.maximum(pw + pl, 1e-12)
            y = (res > X).astype(float)
            m = res != X
            l_ = H.logloss(p, y)
            ll += np.where(m, l_, 0); cnt += m
    return logs, ll / np.maximum(cnt, 1)


def mle_grid(fn, grid, tune):
    best = None
    for g in grid:
        v = fn(g)[tune].mean()
        if best is None or v < best[0]:
            best = (v, g)
    return best[1]


def part_a(sport, rows):
    out = {}
    for mk, (ka, kl) in (('spread', ('res', 'L')), ('total', ('tot', 'T'))):
        R = [r for r in rows if r.get(ka) is not None and r.get(kl) is not None]
        if mk == 'total':
            R = [r for r in R if r[kl] > 20]
        S = np.array([r['S'] for r in R])
        res = np.array([float(r[ka]) for r in R])
        cen = np.array([float(r[kl]) for r in R])
        day = np.array([str(r.get('date', ''))[:10] for r in R])
        tune, held, hs = split(S)
        fb = sport in C.FOOTBALL
        notie = (mk == 'spread' and not fb)
        lo = 0 if mk == 'total' else None
        sd0, sdT0, key0 = C.params(sport)
        sd_base = sd0 if mk == 'spread' else sdT0
        kb = np.array(key0) if (mk == 'spread' and key0) else None
        Kb, Pb = pmfs(cen, Shape('N', sd=sd_base), kb, notie, lo)
        base = scores(Kb, Pb, res, cen)
        r_t = res[tune] - cen[tune]
        cands = {}

        def run(shape, key=None):
            return pmfs(cen, shape, key, notie, lo)

        # N refit
        sd_hat = mle_grid(lambda s: scores(*run(Shape('N', sd=s)), res, cen)[0], np.arange(0.85, 1.16, 0.03) * r_t.std(), tune)
        shN = Shape('N', sd=round(float(sd_hat), 2))
        # T refit
        bestT = None
        for df in (3, 4, 6, 8, 12, 20, 40):
            for f in (0.8, 0.85, 0.9, 0.95, 1.0):
                sh = Shape('T', s=f * r_t.std(), df=df)
                v = scores(*run(sh), res, cen)[0][tune].mean()
                if bestT is None or v < bestT[0]:
                    bestT = (v, df, f)
        shT = Shape('T', s=bestT[2] * r_t.std(), df=bestT[1])
        # KDE on tuning residuals (bandwidth by tuning log score, leave-in; held out judges)
        bestK = None
        for h in (1.0, 1.5, 2.0, 3.0, 4.0):
            sh = Shape('KDE', res=r_t, h=h)
            v = scores(*run(sh), res, cen)[0][tune].mean()
            if bestK is None or v < bestK[0]:
                bestK = (v, h)
        shK = Shape('KDE', res=r_t, h=bestK[1])
        nkey = 70 if mk == 'spread' else 400
        for nm, sh in (('N', shN), ('T', shT), ('KDE', shK)):
            K, P = run(sh)
            cands[nm] = scores(K, P, res, cen)
            key = fit_key(K, P, res, tune, nkey, absval=(mk == 'spread'))
            if mk == 'total':
                # totals: a weight per total (not per |k|); index by the total itself
                Pk = P * key[np.clip(K, 0, nkey)]
                Pk = Pk / Pk.sum(1, keepdims=True)
                cands[nm + '+key'] = scores(K, Pk, res, cen)
            else:
                cands[nm + '+key'] = scores(*run(sh, key), res, cen)
        rep = {'n': {'tune': int(tune.sum()), 'held': int(held.sum())}, 'heldSeasons': [int(x) for x in hs],
               'resid': {'mean': round(float((res - cen).mean()), 3), 'median': round(float(np.median(res - cen)), 3),
                         'sd': round(float((res - cen).std()), 3),
                         'skew': round(float((((res - cen) - (res - cen).mean()) ** 3).mean() / (res - cen).std() ** 3), 3),
                         'exkurt': round(float((((res - cen) - (res - cen).mean()) ** 4).mean() / (res - cen).std() ** 4 - 3), 3)},
               'fit': {'baseSd': sd_base, 'N': shN.p, 'T': {'df': bestT[1], 's': round(bestT[2] * float(r_t.std()), 2)},
                       'KDE': {'h': bestK[1]}},
               'base': {'logs': round(float(base[0][held].mean()), 5), 'cover': round(float(base[1][held].mean()), 5)}, 'cands': {}}
        for nm, (lg, cv) in cands.items():
            d = {}
            for sc, a, b in (('logs', lg, base[0]), ('cover', cv, base[1])):
                pt = H.paired(a[tune], b[tune], cluster=day[tune])['t']
                ph = H.paired(a[held], b[held], cluster=day[held])
                d[sc] = {'dTune': round(float(a[tune].mean() - b[tune].mean()), 6), 'held': round(float(a[held].mean()), 5), 'd': round(float(ph['d'] if 'd' in ph else a[held].mean() - b[held].mean()), 5),
                         't_tune': round(float(pt), 2), 't_held': round(float(ph['t']), 2)}
            rep['cands'][nm] = d
        # the shape clv.py prices with (data/clv_fit.json via clv.fit): enters on the tuning seasons by the cover score
        # (t <= -1.65), held out may only veto (d > 0); lowest tuning loss wins. Football margins keep the production
        # normal x key table (no reshaped candidate entered); the KDE stays research (h picked in sample)
        pick = None
        if not (fb and mk == 'spread'):
            ok = [(rep['cands'][nm]['cover']['dTune'], nm) for nm in ('N', 'T')
                  if rep['cands'][nm]['cover']['t_tune'] <= -1.65 and rep['cands'][nm]['cover']['d'] <= 0]
            if ok:
                nm = min(ok)[1]
                pick = {'kind': 'N', 'sd': rep['fit']['N']['sd']} if nm == 'N' else {'kind': 'T', **rep['fit']['T']}
        rep['pick'] = pick
        out[mk] = rep
        print(sport, mk, json.dumps(rep['resid']), 'base', rep['base'], 'PICK', pick)
        for nm, d in rep['cands'].items():
            print('   ', nm.ljust(8), 'logs d %+.5f t %+.2f/%+.2f | cover d %+.5f t %+.2f/%+.2f' % (
                d['logs']['d'], d['logs']['t_tune'], d['logs']['t_held'], d['cover']['d'], d['cover']['t_tune'], d['cover']['t_held']))
    return out


def part_b(sport, rows):
    """over chance off the model's total: mean vs median"""
    R = [r for r in rows if r.get('tm') is not None and r.get('T') and r.get('tot') is not None and r['tot'] != r['T']]
    S = np.array([r['S'] for r in R])
    tm, T, tot = (np.array([float(r[k]) for r in R]) for k in ('tm', 'T', 'tot'))
    day = np.array([str(r.get('date', ''))[:10] for r in R])
    tune, held, _ = split(S)
    y = (tot > T).astype(float)
    g = tm - T
    em = (tot - tm)[tune]
    d_med = float(em.mean() - np.median(em))
    out = {'meanMinusMedian': round(d_med, 3)}

    def fitp(gap):
        b = np.polyfit(gap[tune], (tot - T)[tune], 1)[0]
        b = min(1.0, max(0.0, b))
        s = float(np.std((tot - T)[tune] - b * gap[tune]))
        return b, s

    for nm, gap in (('base', g), ('median', g - d_med)):
        b, s = fitp(gap)
        p = ncdf(b * gap / s)
        out[nm] = {'b': round(b, 4), 's': round(s, 3), 'll': H.logloss(p, y), 'overShare': None}
    # recentred (the shipped NBA/CFB totals treatment): gap minus its own trailing mean is a separate, live fix; here
    # the question is only whether mean -> median adds anything on top of the line
    a, b0 = out['median']['ll'], out['base']['ll']
    pt = H.paired(a[tune], b0[tune], cluster=day[tune])['t']
    ph = H.paired(a[held], b0[held], cluster=day[held])
    pick_b = held & (np.abs(g) >= 3)
    res = {'meanMinusMedian': out['meanMinusMedian'], 'gapMean': round(float(g.mean()), 3),
           'held': {'base': round(float(b0[held].mean()), 5), 'median': round(float(a[held].mean()), 5),
                    't_tune': round(float(pt), 2), 't_held': round(float(ph['t']), 2)},
           'overShareGap3': round(float((g[pick_b] > 0).mean()), 3) if pick_b.any() else None,
           'overHitGap3': round(float(y[pick_b & (g > 0)].mean()), 3) if (pick_b & (g > 0)).any() else None,
           'underHitGap3': round(float(1 - y[pick_b & (g < 0)].mean()), 3) if (pick_b & (g < 0)).any() else None}
    print(sport, 'B', json.dumps(res))
    return res


def part_c(sport, rows):
    """the tables' cover chance: Phi(b gap / s) vs the key-number distribution at the implied close"""
    R = [r for r in rows if r.get('m') is not None and r.get('L') is not None and r.get('res') is not None]
    S = np.array([r['S'] for r in R])
    m, L, res = (np.array([float(r[k]) for r in R]) for k in ('m', 'L', 'res'))
    day = np.array([str(r.get('date', ''))[:10] for r in R])
    tune, held, _ = split(S)
    g = m - L
    b = min(1.0, max(0.0, np.polyfit(g[tune], (res - L)[tune], 1)[0]))
    s = float(np.std((res - L)[tune] - b * g[tune]))
    side = np.where(g >= 0, 1, -1)
    nop = res != L
    y = ((res - L) * side > 0).astype(float)
    p0 = ncdf(b * np.abs(g) / s)
    sd, _, key = C.params(sport)
    p1 = []
    for gi, Li in zip(g, L):
        w, pu, l_ = C.chances(sport, 'spread', 'home' if gi >= 0 else 'away', Li, Li + b * gi)
        p1.append(w / max(w + l_, 1e-12))
    p1 = np.array(p1)
    l0, l1 = H.logloss(p0, y), H.logloss(p1, y)
    mt, mh = tune & nop, held & nop
    out = {'b': round(float(b), 4), 's': round(s, 3),
           'held': {'phi': round(float(l0[mh].mean()), 5), 'key': round(float(l1[mh].mean()), 5),
                    't_tune': round(float(H.paired(l1[mt], l0[mt], cluster=day[mt])['t']), 2),
                    't_held': round(float(H.paired(l1[mh], l0[mh], cluster=day[mh])['t']), 2)}}
    # on key numbers specifically: lines of 3/7 (+-.5) where the half point matters most
    on = mh & np.isin(np.abs(L), (2.5, 3, 3.5, 6.5, 7, 7.5))
    if on.sum() > 30:
        out['keyLines'] = {'n': int(on.sum()), 'phi': round(float(l0[on].mean()), 5), 'key': round(float(l1[on].mean()), 5)}
    print(sport, 'C', json.dumps(out))
    return out


def part_d(sport, rows):
    """football key numbers from our own history: how often the final margin lands exactly on each number, and what a
    half point is worth there (the push chance at the close, off clv.py's key-number distribution)"""
    R = [r for r in rows if r.get('res') is not None]
    n = len(R)
    share = {k: round(sum(abs(round(r['res'])) == k for r in R) / n, 4) for k in range(1, 18)}
    push = {}
    for k in range(1, 18):
        w, pu, l_ = C.chances(sport, 'spread', 'home', float(k), float(k))
        push[k] = round(pu, 4)
    out = {'games': n, 'marginShare': share, 'pushAtClose': push}
    print(sport, 'D', 'exactly 3: %.3f, 7: %.3f, 10: %.3f, 14: %.3f' % (share[3], share[7], share[10], share[14]),
          'push at -3: %.3f, -7: %.3f' % (push[3], push[7]))
    return out


def main():
    rep = {'note': __doc__.split('\n\n')[0], 'sports': {}}
    for sp in SPORTS:
        rows = load(sp)
        rep['sports'][sp] = {'A': part_a(sp, rows), 'B': part_b(sp, rows)}
        if sp in C.FOOTBALL:
            rep['sports'][sp]['C'] = part_c(sp, rows)
            rep['sports'][sp]['D'] = part_d(sp, rows)
    with open(OUT, 'w') as f:
        json.dump(rep, f, indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
