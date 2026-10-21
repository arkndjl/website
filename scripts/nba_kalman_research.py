"""Research: team ratings with their own uncertainty (scripts/kalman.py) in the NBA game model (numpy).

    python3 scripts/nba_kalman_research.py          # filter tuning, then each Kalman input against the fitted model

1. The filters' settings (observation noise R, drift a game q, offseason widening Q0, offseason keep) are tuned on
   2015-21 by the filter's own one-step-ahead log likelihood: the results filter on final margins, the market filter
   on closing spreads (the game's own line is never seen before the game).
2. Each Kalman input is tried against the fitted model (data/nba_games_fit.json feats and params), walk-forward,
   same rule as the fit: 2015-21 paired t <= -1.5 on absolute error and 2022-26 error also falls.
3. The rating gap's variance downstream: does the win probability's sd widen with it (log loss), and does the
   model's error against the close grow with it (what the DU shrink would need).
"""
import itertools
from collections import defaultdict
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as F
from kalman import Kalman

OUT = os.path.join(HERE, '.cache', 'nba', 'kalman_research.json')


def filt(games, R, q, Q0, keep, hca, obs, Rm=None):
    """per game id: (mean gap without home court, gap variance) before the game, and 2015-21 log likelihood.
    obs 'both': one rating seen through the closing spread (noise Rm) before the game and the margin (R) after"""
    k = Kalman(R, q, Q0, keep, P0=Q0 * 3, hca=hca)
    S0, ll, n, out = None, 0.0, 0, {}
    for g in games:
        if g['S'] != S0:
            k.new_season(); S0 = g['S']
        y = (g['hs'] - g['as']) if obs in ('res', 'both') else g.get('L')
        k.drift(g['h'], g['a'])
        m, v = k.pred(g['h'], g['a'], 1)
        out[g['id']] = (m, v)
        if obs == 'both' and g.get('L') is not None:
            k.update(g['h'], g['a'], g['L'], g['n'], R=Rm)
            k.n -= 1
        if y is None:
            continue
        e, Sv = k.update(g['h'], g['a'], y, g['n'])
        if N.SCORE_FROM <= g['S'] < N.HOLD_FROM:
            ll += -0.5 * (math.log(2 * math.pi * Sv) + e * e / Sv); n += 1
    return out, ll / max(n, 1)


def tune(games, obs, grid):
    best = max(((filt(games, *p, obs)[1], p) for p in grid), key=lambda z: z[0])
    return best


def main():
    games, names = N.load_hist()
    games.sort(key=lambda g: g['tip'])
    rep = {}
    gr = tune(games, 'res', itertools.product([140, 160, 180], [0.05, 0.1, 0.15], [6, 8, 12], [0.4, 0.6], [2.4]))
    gm = tune(games, 'mkt', itertools.product([3, 4, 5], [0.3, 0.4, 0.6], [6, 8, 12], [0.4, 0.6], [2.4]))
    rep['tune'] = {'res': {'ll': round(gr[0], 4), 'R,q,Q0,keep,hca': gr[1]}, 'mkt': {'ll': round(gm[0], 4), 'R,q,Q0,keep,hca': gm[1]}}
    print('tuned', rep['tune'], flush=True)
    KR, _ = filt(games, *gr[1], 'res')
    KM, _ = filt(games, *gm[1], 'mkt')
    # fused: tuned on the margins it predicts, with the line seen before each game's result
    gf = max(((filt(games, 160, q, Q0, kp, 2.4, 'both', Rm)[1], (160, q, Q0, kp, 2.4, Rm)) for q in (0.1, 0.4) for Q0 in (6, 8)
              for kp in (0.6,) for Rm in (4, 16, 36)), key=lambda z: z[0])
    rep['tune']['both'] = {'ll': round(gf[0], 4), 'R,q,Q0,keep,hca,Rm': gf[1]}
    print('fused', rep['tune']['both'], flush=True)
    p = gf[1]
    KF, _ = filt(games, *p[:5], 'both', p[5])

    fit = json.load(open(F.N.FIT))
    params = {k: v for k, v in fit['params'].items()}
    feats = list(fit['feats'])
    inj = F.load_inj()
    import pickle
    pk = os.path.join(HERE, '.cache', 'nba', 'kalman_design.pkl')       # the fitted model's walk, cached between runs
    if os.path.exists(pk):
        D, X, TX, y, ty, S, line, tline = pickle.load(open(pk, 'rb'))
    else:
        D, X, TX, y, ty, S, line, tline = F.design(games, names, fit['P'], params, inj, feats)
        pickle.dump((D, X, TX, y, ty, S, line, tline), open(pk, 'wb'))
    ids = [g['id'] for g, _, _ in D]
    X['gpn'] = np.array([x['gpn'] for _, x, _ in D])
    X['kr'] = np.array([KR[i][0] for i in ids]); X['krv'] = np.array([KR[i][1] for i in ids])
    X['km'] = np.array([KM[i][0] for i in ids]); X['kmv'] = np.array([KM[i][1] for i in ids])
    X['kf'] = np.array([KF[i][0] for i in ids])
    early = np.maximum(0.0, 1 - X['gpn'] / 20)
    X['krE'] = X['kr'] * early; X['kmE'] = (X['km'] - X['mkt']) * early
    # uncertainty interactions: the results rating's weight rising with the market rating's variance (early season,
    # the market has seen little), and the market rating's weight falling with it
    X['krXv'] = X['kr'] * X['kmv'] / X['kmv'].mean()
    X['mktXv'] = X['mkt'] * X['kmv'] / X['kmv'].mean()
    X['kmXv'] = X['km'] * X['kmv'] / X['kmv'].mean()
    X['effXv'] = X['eff'] * X['krv'] / X['krv'].mean()
    k1, k2 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM), S >= N.HOLD_FROM
    base = F.wf(F.mat(X, feats), y, S)
    mae = lambda p, k: float(np.mean(np.abs(p[k] - y[k])))
    rep['base'] = {'feats': feats, 'mae2015_21': round(mae(base, k1), 4), 'mae2022_26': round(mae(base, k2), 4)}
    print('base', rep['base'], flush=True)
    trials = {'+kr': feats + ['kr'], '+km': feats + ['km'], 'km for mkt': [f if f != 'mkt' else 'km' for f in feats],
              'km for mkt, +kr': [f if f != 'mkt' else 'km' for f in feats] + ['kr'],
              'kr for elo': [f if f != 'elo' else 'kr' for f in feats], 'kr for elo,eff': [f for f in feats if f not in ('elo', 'eff')] + ['kr'],
              '+mktXv': feats + ['mktXv'], '+krXv': feats + ['krXv'], '+effXv': feats + ['effXv'],
              'km for mkt, +kmXv': [f if f != 'mkt' else 'km' for f in feats] + ['kmXv'],
              'km for mkt, +kmXv, +krXv': [f if f != 'mkt' else 'km' for f in feats] + ['kmXv', 'krXv'],
              '+kf': feats + ['kf'], 'kf for mkt': [f if f != 'mkt' else 'kf' for f in feats],
              # opening weeks only (set after the 'early' split above showed the Kalman gain there): the results
              # rating early, and the Kalman market rating's gap to the fixed-step one early
              '+krE': feats + ['krE'], '+kmE': feats + ['kmE'], '+krE,+kmE': feats + ['krE', 'kmE']}
    rep['trials'] = {}
    for nm, fs in trials.items():
        pr = F.wf(F.mat(X, fs), y, S)
        r = {'t2015_21': round(F.paired_t(np.abs(pr[k1] - y[k1]), np.abs(base[k1] - y[k1])), 2),
             'd2015_21': round(mae(pr, k1) - mae(base, k1), 4),
             'd2022_26': round(mae(pr, k2) - mae(base, k2), 4),
             't2022_26': round(F.paired_t(np.abs(pr[k2] - y[k2]), np.abs(base[k2] - y[k2])), 2)}
        r['pass'] = r['t2015_21'] <= -1.5 and r['d2022_26'] < 0
        for seg, ks in (('early', X['gpn'] < 10), ('rest', X['gpn'] >= 10)):
            a1, a2 = k1 & ks, k2 & ks
            r[seg] = {'d2015_21': round(mae(pr, a1) - mae(base, a1), 4), 't2015_21': round(F.paired_t(np.abs(pr[a1] - y[a1]), np.abs(base[a1] - y[a1])), 2),
                      'd2022_26': round(mae(pr, a2) - mae(base, a2), 4), 't2022_26': round(F.paired_t(np.abs(pr[a2] - y[a2]), np.abs(base[a2] - y[a2])), 2)}
        rep['trials'][nm] = r
        print(nm, r, flush=True)

    # 3. variance downstream: error against the close by variance quintile; win sd widened with the gap's variance
    ok = ~np.isnan(base) & ~np.isnan(line)
    v = X['kmv'] + X['krv'] * 0
    qs = np.quantile(v[ok & (S >= N.SCORE_FROM)], [0.2, 0.4, 0.6, 0.8])
    rows = []
    for b in range(5):
        lo = qs[b - 1] if b else -np.inf; hi = qs[b] if b < 4 else np.inf
        k = ok & (S >= N.SCORE_FROM) & (v >= lo) & (v < hi)
        e = base[k] - line[k]; r = y[k] - line[k]
        rows.append({'q': b + 1, 'n': int(k.sum()), 'kmv': round(float(v[k].mean()), 2), 'krv': round(float(X['krv'][k].mean()), 2),
                     'gp': round(float(X['gpn'][k].mean()), 1), 'maeModel': round(mae(base, k), 3), 'maeLine': round(float(np.mean(np.abs(line[k] - y[k]))), 3),
                     'sdModelMinusLine': round(float(np.std(e)), 3),
                     'slopeResOnGap': round(float(np.polyfit(e, r, 1)[0]), 3) if len(e) > 50 else None})
    rep['byVariance'] = rows
    for r in rows:
        print(r)
    win = (y > 0).astype(float)
    sd = fit['sd']

    def ll(c, k, w=X['krv']):
        s = np.sqrt(sd ** 2 + c * w[k])
        p = np.clip(np.array([N.phi(m / ss) for m, ss in zip(base[k], s)]), 1e-6, 1 - 1e-6)
        return float(-np.mean(win[k] * np.log(p) + (1 - win[k]) * np.log(1 - p)))
    kk1, kk2 = ok & k1, ok & k2
    grid = [(ll(c, kk1), c) for c in (-2, -1, 0, 1, 2, 4, 8)]
    c = min(grid)[1]
    rep['winSd'] = {'grid2015_21': [[c_, round(l, 5)] for l, c_ in grid], 'c': c, 'll2022_26': round(ll(c, kk2), 5), 'll2022_26c0': round(ll(0, kk2), 5)}
    print('win sd', rep['winSd'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rep, open(OUT, 'w'), indent=1)


if __name__ == '__main__' and not sys.argv[1:]:
    main()


def sims():
    """the season sims' rating sd: at checkpoints in each regular season (0, 200, ... 1000 games in), each team's
    rating as the season odds build it (nba_games_build.season_views' composite of the fitted inputs), then its mean
    residual over the rest of the regular season. That mean's variance = the rating's true error (sigma^2, what the
    sims draw once a season) x 30/29 + game noise / games left. Specs for sigma, fit on 2016-21 by likelihood and
    scored on 2022-26: the current 3.7 x sqrt(share left) floored at 1.5; a + b x share left; and per team from the
    fused Kalman rating's variance at the checkpoint (c x P_tt + d x share left)."""
    games, names = N.load_hist()
    games.sort(key=lambda g: g['tip'])
    fit = json.load(open(F.N.FIT))
    b = fit['coef']
    inj = F.load_inj()
    m = N.Model(names, fit['P'], inj=inj, **fit['params'])
    kf = Kalman(160, 0.4, 8, 0.6, P0=24, hca=2.4)
    CK = (0, 200, 400, 600, 800, 1000)
    snaps, S0, nreg = [], None, 0
    teams = sorted(N.ARENA)
    for g in games:
        if g['S'] != S0:
            kf.new_season(); S0 = g['S']; nreg = 0
        m.feats(g)
        if g['t'] == 2:
            if nreg in CK and g['S'] >= 2016 and g['S'] != 2020:
                L_ = m.lgp[0] / m.lgp[1]
                net = lambda t: m.rate(m.off, t) - m.rate(m.dfn, t)
                mk = sum(m.mkt[t] for t in teams) / len(teams)
                R = {}
                for t in teams:
                    V = m.lineup(t)
                    c = {'elo': (m.elo[t] - 1505) / 28, 'eff': net(t) * (L_ + m.rate(m.pace, t)) / 100, 'mkt': m.mkt[t] - mk,
                         'lin': V - m.rate(m.base, t, 1.0), 'roster': V}
                    R[t] = sum(b.get(f, 0.0) * v for f, v in c.items())
                av = sum(R.values()) / len(R)
                snaps.append({'S': g['S'], 'ck': nreg, 'R': {t: R[t] - av for t in teams},
                              'P': {t: kf.rating(t)[1] for t in teams}, 'res': defaultdict(list)})
            nreg += 1
        kf.drift(g['h'], g['a'])
        if g.get('L') is not None:
            kf.update(g['h'], g['a'], g['L'], g['n'], R=4)
        kf.update(g['h'], g['a'], g['hs'] - g['as'], g['n'])
        if g['t'] == 2:
            for sn in snaps:
                if sn['S'] == g['S']:
                    e = (g['hs'] - g['as']) - (sn['R'][g['h']] - sn['R'][g['a']] + (0 if g['n'] else b['home']))
                    sn['res'][g['h']].append(e); sn['res'][g['a']].append(-e)
        m.update(g)
    rows = []
    for sn in snaps:
        tot = max(len(v) for v in sn['res'].values()) or 1
        for t in teams:
            r = sn['res'].get(t) or []
            if len(r) < 10:
                continue
            rows.append((sn['S'], sn['ck'], t, float(np.mean(r)), len(r), len(r) / 82.0, sn['P'][t]))
    A = np.array([r[3] for r in rows]); n_ = np.array([r[4] for r in rows], float); sh = np.array([r[5] for r in rows])
    Pt = np.array([r[6] for r in rows]); Sx = np.array([r[0] for r in rows]); ck = np.array([r[1] for r in rows])
    # game noise: each season's residual variance around the model's own pre-game margins (it rose from 12.0 in
    # 2015 to 14.3 in 2026; data/nba_games_fit.json resSd is one pooled number)
    import pickle
    _, X_, _, y_, _, S_, _, _ = pickle.load(open(os.path.join(HERE, '.cache', 'nba', 'kalman_design.pkl'), 'rb'))
    pr_ = F.wf(F.mat(X_, fit['feats']), y_, S_)
    gnS = {int(s_): float(np.nanvar(pr_[S_ == s_] - y_[S_ == s_])) for s_ in set(S_.tolist()) if s_ >= N.SCORE_FROM}
    gn = np.array([gnS[s_] for s_ in Sx])
    k1, k2 = Sx < 2022, Sx >= 2022

    def nll(sig2, k):
        v = np.maximum(sig2, 0.05) * 30 / 29 + gn / n_
        return float(np.mean(0.5 * (np.log(2 * np.pi * v[k]) + A[k] ** 2 / v[k])))
    cur = np.maximum(1.5, 3.7 * np.sqrt(np.minimum(1.0, sh))) ** 2
    out = {'n': [int(k1.sum()), int(k2.sum())], 'current': [nll(cur, k1), nll(cur, k2)]}
    grid = [(nll(a + bb * sh, k1), a, bb) for a in np.arange(0, 6.01, 0.25) for bb in np.arange(0, 20.01, 0.5)]
    _, a, bb = min(grid)
    out['a+b share'] = {'a': a, 'b': bb, 'nll': [nll(a + bb * sh, k1), nll(a + bb * sh, k2)]}
    Pm = Pt / Pt[k1].mean()
    grid = [(nll(c * Pm + d * sh, k1), c, d) for c in np.arange(0, 12.01, 0.25) for d in np.arange(0, 20.01, 0.5)]
    _, c, d = min(grid)
    out['kalman'] = {'c': c, 'd': d, 'nll': [nll(c * Pm + d * sh, k1), nll(c * Pm + d * sh, k2)]}
    grid = [(nll(a + bb * sh + c * (Pm - 1), k1), a, bb, c) for a in np.arange(0, 6.01, 0.5) for bb in np.arange(0, 20.01, 1) for c in np.arange(-4, 8.01, 0.5)]
    _, a, bb, c = min(grid)
    out['a+b share+c team'] = {'a': a, 'b': bb, 'c': c, 'nll': [nll(a + bb * sh + c * (Pm - 1), k1), nll(a + bb * sh + c * (Pm - 1), k2)]}
    # walk-forward: each season's a, b from the seasons before it (weighted to recent seasons by half-life hl), the
    # honest version of the current 3.7, which was measured on 2016-26 including the seasons it scores
    def wfit(s_, hl):
        w = np.where(Sx < s_, 0.5 ** ((s_ - 1 - Sx) / hl) if hl else 1.0, 0.0)
        best = None
        for a in np.arange(0, 20.01, 0.5):
            for bb in np.arange(0, 20.01, 0.5):
                v = np.maximum(a + bb * sh, 0.05) * 30 / 29 + gn / n_
                l = float(np.sum(w * 0.5 * (np.log(2 * np.pi * v) + A ** 2 / v)))
                if best is None or l < best[0]:
                    best = (l, a, bb)
        return best[1], best[2]
    out['walk'] = {}
    for hl in (0, 3, 1.5):
        tot, cur_, n2, ab = 0.0, 0.0, 0, {}
        for s_ in range(2018, 2027):
            k = Sx == s_
            if not k.any():
                continue
            a, bb = wfit(s_, hl)
            ab[s_] = (a, bb)
            tot += nll(a + bb * sh, k) * k.sum(); cur_ += nll(cur, k) * k.sum(); n2 += k.sum()
        out['walk'][f'hl{hl}'] = {'nll2018_26': round(tot / n2, 4), 'current2018_26': round(cur_ / n2, 4), 'ab': ab}
    a, bb = wfit(int(Sx.max()) + 1, 3)
    out['live_hl3'] = {'a': a, 'b': bb, 'sd_open': round(math.sqrt(a + bb), 2), 'sd_end': round(math.sqrt(a), 2)}
    # the measured sd by checkpoint (moments: mean A^2 - noise, by checkpoint)
    msd = lambda k: round(float(math.sqrt(max(0.0, np.mean(A[k] ** 2 - gn[k] / n_[k]) * 29 / 30))), 2)
    out['byCheckpoint'] = {int(c_): {'sd': msd(ck == c_), 'sd2016_21': msd((ck == c_) & k1), 'sd2022_26': msd((ck == c_) & k2),
                                     'current': round(float(np.sqrt(np.mean(cur[ck == c_]))), 2)} for c_ in CK}
    if '--write' in sys.argv:
        with open(os.path.join(N.ROOT, 'data', 'nba_season_sd.json'), 'w') as f:
            json.dump({'a': float(a), 'b': float(bb), 'halfLife': 3, 'through': int(Sx.max()),
                       'sdOpen': round(math.sqrt(a + bb), 2), 'sdEnd': round(math.sqrt(a), 2),
                       'walk2018_26': out['walk']['hl3'], 'byCheckpoint': out['byCheckpoint'],
                       'note': 'season sims: a team rating sd^2 = a + b x share of the season left (scripts/nba_kalman_research.py --sims --write)'}, f, indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))
    return out


if __name__ == '__main__' and sys.argv[1:2] == ['--sims']:
    sims()
