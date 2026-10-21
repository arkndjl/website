"""Research: a college basketball team's preseason prior weighted by how uncertain it is (numpy).

    python3 scripts/cbb_kalman_research.py

The efficiency solve (cbb_games.Ratings) pulls every team toward its preseason prior with the same weight (lam, in
games). In a Kalman filter the pull is the prior's precision, so a roster the prior reads poorly (most minutes gone,
many transfers, a new coach) should give way to its games sooner. Here the prior's error variance is modelled per
team: log((final net - prior net)^2) on the roster terms, fit walk-forward on the seasons before (each season's prior
residuals are out of sample: its coefficients come from earlier seasons). Each team's weight is lam x mean variance /
its variance, clipped to [1/4, 4]. Scored like the fit: walk-forward margin error, 2016-20 paired t <= -1.5 and
2021-26 error also falls, the fitted inputs (data/cbb_games_fit.json) unchanged.
Also: the win probability's sd fit walk-forward on recent seasons in place of one sd for all.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_games as C

VF = ['one', 'retmin', 'trmin', 'tenure', 'abslast']
OUT = os.path.join(HERE, '.cache', 'cbb', 'kalman_research.json')


class VWalk(C.Walk):
    def __init__(self, *a, power=1.0, **k):
        super().__init__(*a, **k)
        self.power = power
        self.vrows = []                 # (season, variance features, log squared prior error)

    def vfeats(self, f):
        return {'one': 1.0, 'retmin': f.get('retmin', 0.0), 'trmin': f.get('trmin', 0.0),
                'tenure': min(f.get('tenure', 0.0), 10.0), 'abslast': abs(f.get('last', 0.0))}

    def season_prior(self, s, teams):
        out, feats = super().season_prior(s, teams)
        # last season's rows: their residual against the prior they were given (out of sample)
        c = self.pcoef.get(s - 1)
        if c:
            for (ss, t, f, y) in self.prior_rows:
                if ss == s - 1:
                    r = y - sum(c[k] * f[k] for k in C.PRIOR_F)
                    self.vrows.append((ss, self.vfeats(f), math.log(r * r + 0.25)))
        if self.power and len({r[0] for r in self.vrows}) >= 2:
            Xv = np.array([[r[1][k] for k in VF] for r in self.vrows]); yv = np.array([r[2] for r in self.vrows])
            b = np.linalg.solve(Xv.T @ Xv + np.diag([0.0] + [1.0] * (len(VF) - 1)), Xv.T @ yv)
            lv = {t: float(np.dot(b, [self.vfeats(feats[t])[k] for k in VF])) for t in out if t in feats}
            if lv:
                mu = sum(lv.values()) / len(lv)
                for t, v in lv.items():
                    out[t]['lm'] = float(min(4.0, max(0.25, math.exp(-(v - mu) * self.power))))
            self.vcoef = dict(zip(VF, b.tolist()))
        return out, feats


def walk(P, games, tprior, btname, d1s, avs, power):
    W = VWalk(P, tprior, btname, power=power)
    by_s = {}
    for g in games:
        by_s.setdefault(g['season'], []).append(g)
    out = []
    for s in sorted(by_s):
        gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))
        C.season_walk(W, s, gs, d1s[s], avs.get(s), lambda g, x, tx, R: out.append((g, x, tx)) if g.get('hs') is not None else None)
    return W, out


def main():
    games, btname, d1s, tprior, avs = C.load_all()
    fit = json.load(open(C.FIT))
    P, feats = fit['params'], fit['feats']
    rep = {'feats': feats}
    base = None
    for power in (0.0, 0.5, 1.0):
        W, rows = walk(P, games, tprior, btname, d1s, avs, power)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        pred = C.walk_pred(Xm, y, S, d1)
        k1 = (S >= C.SCORE0) & (S <= C.TUNE_END) & d1 & ~np.isnan(pred)
        k2 = (S > C.TUNE_END) & d1 & ~np.isnan(pred)
        ng = np.array([0 for _ in D])
        r = {'mae2016_20': round(float(np.mean(np.abs(pred[k1] - y[k1]))), 4), 'mae2021_26': round(float(np.mean(np.abs(pred[k2] - y[k2]))), 4),
             'vcoef': getattr(W, 'vcoef', None)}
        if base is None:
            base = (pred, y, k1, k2, S, D)
        else:
            bp = base[0]
            r['t2016_20'] = round(C.paired_t(np.abs(pred[k1] - y[k1]), np.abs(bp[k1] - y[k1])), 2)
            r['t2021_26'] = round(C.paired_t(np.abs(pred[k2] - y[k2]), np.abs(bp[k2] - y[k2])), 2)
            r['pass'] = r['t2016_20'] <= -1.5 and r['mae2021_26'] < rep['power0.0']['mae2021_26']
            # the opening weeks, where the prior matters
            early = np.array([i for i in range(len(D))])
            dates = np.array([D[i][0]['date'][5:10] for i in range(len(D))])
            e = (dates >= '11-01') & (dates <= '12-15')
            for nm, kk in (('early2016_20', k1 & e), ('early2021_26', k2 & e)):
                r[nm] = {'d': round(float(np.mean(np.abs(pred[kk] - y[kk])) - np.mean(np.abs(bp[kk] - y[kk]))), 4),
                         't': round(C.paired_t(np.abs(pred[kk] - y[kk]), np.abs(bp[kk] - y[kk])), 2)}
        rep[f'power{power}'] = r
        print(power, r, flush=True)
    # win sd walk-forward (recent seasons weighted, half-life 2) vs the fixed sd
    pred, y, k1, k2, S, D = base
    win = (y > 0).astype(float)
    ok = ~np.isnan(pred) & np.array([g['home'] != C.X and g['away'] != C.X for g, _, _ in D])
    grid = np.arange(9.0, 14.01, 0.25)

    def ll(sd, k):
        p = np.clip(0.5 * (1 + np.vectorize(math.erf)(pred[k] / sd / math.sqrt(2))), 1e-6, 1 - 1e-6)
        return float(-np.sum(win[k] * np.log(p) + (1 - win[k]) * np.log(1 - p)))
    seas = sorted({int(s) for s in S[ok]})
    LL = {s: np.array([ll(x, ok & (S == s)) for x in grid]) for s in seas}
    fixed = fit['sd']
    tot_w, tot_f, n, sds = 0.0, 0.0, 0, {}
    for s in seas:
        prev = [t for t in seas if t < s]
        if not prev:
            continue
        sd = float(grid[np.argmin(sum(0.5 ** ((s - 1 - t) / 2) * LL[t] for t in prev))])
        sds[s] = sd
        if s > C.TUNE_END:
            k = ok & (S == s)
            tot_w += ll(sd, k); tot_f += ll(fixed, k); n += int(k.sum())
    sd_live = float(grid[np.argmin(sum(0.5 ** ((max(seas) - t) / 2) * LL[t] for t in seas))])
    rep['winSd'] = {'fixed': fixed, 'll2021_26_fixed': round(tot_f / n, 5), 'll2021_26_walk': round(tot_w / n, 5), 'bySeason': sds, 'live': sd_live}
    print('win sd', rep['winSd'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rep, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
