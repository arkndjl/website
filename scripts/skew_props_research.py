#!/usr/bin/env python3
"""NBA player props: is the over/under chance shaped right? (Oct 21 2026, with scripts/skew_research.py)

Points per player game are right-skewed (skew ~+1, mean over the median; 56% of games finish under the mean), so a
chance read off the mean with a symmetric curve leans to the over. The props model already prices with a negative
binomial (scripts/nba_players.nb_over, variance a mu + b mu^2 fit on 2021-23). This checks that against the
alternatives on the held-out seasons (2024-26), at prop-like lines (the half point at, under and over his projection,
and the season-average stand-in the fit's calibration uses):
    normal   same mean and variance, symmetric (what "mean vs line" amounts to)
    nb       production
    nbcal    nb, then a logistic recalibration of its chance fit on 2021-23 (per stat)
    emp      the 2021-23 rows' own shape: y / mu by projection band, applied to this row's mu
    nbr      nb with the variance by role (minutes band): starters' minutes are left-skewed, bench minutes all over

    python3 scripts/skew_props_research.py      # needs scripts/.cache/nba/inj_hist.json (scripts/nba_inj_hist.py)
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import nba_players as NP  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'skew_props_research.json')
CACHE = os.path.join(HERE, '.cache', 'skew_props_rows.npz')
STATS = ('pts', 'reb', 'ast', 'pra')


def rows():
    if os.path.exists(CACHE):
        z = np.load(CACHE)
        return {k: z[k] for k in z.files}
    F = json.load(open(NP.FIT))
    NP.PCAL = F.get('pcal')
    D = [r for r in NP.collect() if r['y'] and r['nv'] and r['mS'] >= 10 and not r['po']]
    S = np.array([r['S'] for r in D])
    out = {'S': S, 'g': np.array([r['g'] for r in D]), 'mS': np.array([r['mS'] for r in D], float)}
    for i, s in enumerate(('min',) + NP.PSTATS):
        y = np.array([r['y'][i] for r in D], float)
        feats = F['stats'][s]['feats']
        A = np.column_stack([np.array([r['fx'][s][f] for r in D], float) for f in feats])
        pred = np.full(len(S), np.nan)
        for yr in sorted(set(S)):
            tr, te = S < yr, S == yr
            if tr.sum() < 1000:
                continue
            pred[te] = A[te] @ np.linalg.lstsq(A[tr], y[tr], rcond=None)[0]
        out['y_' + s], out['mu_' + s] = y, pred
        out['nv_' + s] = np.array([r['nv'][i] for r in D], float)
    for k in ('y', 'mu', 'nv'):
        out[k + '_pra'] = out[k + '_pts'] + out[k + '_reb'] + out[k + '_ast']
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    np.savez_compressed(CACHE, **out)
    return out


def ncdf(z):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(z, float) / math.sqrt(2)))


def nb_vec(mu, var, L):
    return np.array([NP.nb_over(a, v, l) for a, v, l in zip(mu, var, L)])


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def main():
    Z = rows()
    S = Z['S']
    tune, hold = np.isin(S, NP.TUNE), np.isin(S, NP.HOLD)
    rep = {'note': __doc__.split('\n\n')[0], 'stats': {}}
    for s in STATS:
        ok = ~np.isnan(Z['mu_' + s]) & (Z['mu_' + s] > 0.5) & (tune | hold)
        mu, y, nv, G, mS = Z['mu_' + s][ok], Z['y_' + s][ok], Z['nv_' + s][ok], Z['g'][ok], Z['mS'][ok]
        t_, h_ = tune[ok], hold[ok]
        # variance a mu + b mu^2 on tune (production)
        ab = np.linalg.lstsq(np.column_stack([mu[t_], mu[t_] ** 2]), (y[t_] - mu[t_]) ** 2, rcond=None)[0]
        var = np.maximum(mu * 1.0001, ab[0] * mu + ab[1] * mu * mu)
        # by role: minutes band (starter-like 28+, rotation 18-28, bench <18)
        band = np.digitize(mS, (18, 28))
        varR = var.copy()
        abR = {}
        for b_ in range(3):
            m_ = t_ & (band == b_)
            c = np.linalg.lstsq(np.column_stack([mu[m_], mu[m_] ** 2]), (y[m_] - mu[m_]) ** 2, rcond=None)[0]
            abR[b_] = [round(float(x), 4) for x in c]
            sel = band == b_
            varR[sel] = np.maximum(mu[sel] * 1.0001, c[0] * mu[sel] + c[1] * mu[sel] ** 2)
        # empirical shape: y / mu by projection band (tune), quantiles of the ratio
        qb = np.quantile(mu[t_], np.linspace(0, 1, 11)[1:-1])
        bandmu = np.digitize(mu, qb)
        ratios = {b_: np.sort(y[t_ & (bandmu == b_)] / mu[t_ & (bandmu == b_)]) for b_ in range(10)}
        offs = (-2, -1, 0, 1, 2) if s in ('pts', 'pra') else (-1, 0, 1)
        lines = [('savg', np.floor(nv) + 0.5)] + [('mu%+d' % o, np.floor(mu) + 0.5 + o) for o in offs]
        L_all = {nm: L for nm, L in lines}
        P = {k: {} for k in ('normal', 'nb', 'nbr', 'emp')}
        for nm, L in lines:
            P['normal'][nm] = 1 - ncdf((L - mu) / np.sqrt(var))
            P['nb'][nm] = nb_vec(mu, var, L)
            P['nbr'][nm] = nb_vec(mu, varR, L)
            pe = np.zeros(len(mu))
            for b_ in range(10):
                sel = bandmu == b_
                rr = ratios[b_]
                pe[sel] = 1 - np.searchsorted(rr, L[sel] / mu[sel], side='right') / len(rr)
            P['emp'][nm] = pe
        # nb recalibrated: logistic on logit(p_nb) and the line's distance from the mean, all tune lines pooled
        Xc = np.concatenate([np.column_stack([np.ones(t_.sum()), logit(P['nb'][nm][t_])]) for nm, _ in lines])
        Yc = np.concatenate([(y[t_] > L_all[nm][t_]).astype(float) for nm, _ in lines])
        w = np.zeros(2)
        for _ in range(25):                              # Newton
            pz = 1 / (1 + np.exp(-Xc @ w))
            Hm = (Xc * (pz * (1 - pz))[:, None]).T @ Xc
            w += np.linalg.solve(Hm, Xc.T @ (Yc - pz))
        P['nbcal'] = {nm: 1 / (1 + np.exp(-(w[0] + w[1] * logit(P['nb'][nm])))) for nm, _ in lines}
        # nbcal2: the recalibration also bends with the projection's size (log mu): small means are the most skewed
        def X2(nm, m_):
            return np.column_stack([np.ones(m_.sum()), logit(P['nb'][nm][m_]), np.log(mu[m_]), logit(P['nb'][nm][m_]) * np.log(mu[m_])])
        Xc = np.concatenate([X2(nm, t_) for nm, _ in lines])
        w2 = np.zeros(4)
        for _ in range(25):
            pz = 1 / (1 + np.exp(-Xc @ w2))
            Hm = (Xc * (pz * (1 - pz))[:, None]).T @ Xc
            w2 += np.linalg.solve(Hm, Xc.T @ (Yc - pz))
        allm = np.ones(len(mu), bool)
        P['nbcal2'] = {nm: 1 / (1 + np.exp(-(X2(nm, allm) @ w2))) for nm, _ in lines}
        loss = {k: np.mean([H.logloss(P[k][nm], (y > L_all[nm]).astype(float)) for nm, _ in lines], axis=0) for k in P}
        bri = {k: np.mean([H.brier(P[k][nm], (y > L_all[nm]).astype(float)) for nm, _ in lines], axis=0) for k in P}
        d = {'var': [round(float(x), 4) for x in ab], 'varByRole': abR, 'recal': [round(float(x), 4) for x in w], 'recal2': [round(float(x), 4) for x in w2],
             'n': {'tune': int(t_.sum()), 'hold': int(h_.sum())}, 'skew': {}, 'held': {}}
        r_ = y[h_]
        d['skew'] = {'mean': round(float(r_.mean()), 2), 'median': round(float(np.median(r_)), 2),
                     'underMean': round(float((r_ < r_.mean()).mean()), 3),
                     'skew': round(float(((r_ - r_.mean()) ** 3).mean() / r_.std() ** 3), 2),
                     'underOwnMu': round(float((y[h_] < mu[h_]).mean()), 3),
                     'underMuLine': round(float((y[h_] < np.floor(mu[h_]) + 0.5).mean()), 3),
                     'nbUnderMuLine': round(float(1 - P['nb']['mu+0'][h_].mean()), 3),
                     'normalUnderMuLine': round(float(1 - P['normal']['mu+0'][h_].mean()), 3)}
        for k in P:
            pt = H.paired(loss[k][t_], loss['nb'][t_], cluster=G[t_])
            ph = H.paired(loss[k][h_], loss['nb'][h_], cluster=G[h_])
            d['held'][k] = {'dTune': round(pt['d'], 5), 'logloss': round(float(loss[k][h_].mean()), 5), 'brier': round(float(bri[k][h_].mean()), 5),
                            'd': round(ph['d'], 5), 't_tune': round(pt['t'], 2), 't_held': round(ph['t'], 2)}
        # calibration at his own projection's half point (the prop-like line), held out
        p0, o0 = P['nb']['mu+0'][h_], (y[h_] > L_all['mu+0'][h_]).astype(float)
        pc = P['nbcal']['mu+0'][h_]
        d['calibAtMu'] = []
        for lo_, hi_ in ((0, .4), (.4, .45), (.45, .5), (.5, .55), (.55, .6), (.6, 1.01)):
            b_ = (p0 >= lo_) & (p0 < hi_)
            if b_.sum() >= 100:
                d['calibAtMu'].append({'nb': round(float(p0[b_].mean()), 3), 'nbcal': round(float(pc[b_].mean()), 3),
                                       'hit': round(float(o0[b_].mean()), 3), 'n': int(b_.sum())})
        rep['stats'][s] = d
        print(s, json.dumps(d['skew']))
        for k, v in d['held'].items():
            print('   ', k.ljust(7), v)
        print('    calib at mu:', d['calibAtMu'], 'recal', d['recal'])
    with open(OUT, 'w') as f:
        json.dump(rep, f, indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
