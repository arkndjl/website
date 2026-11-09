#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA game model: the lineup term (lin) in points per 100 possessions against the matchup's expected possessions
(math audit Nov 2 2026, "NBA lin per-100 vs pace"). lin enters the margin regression per 100 while eff is scaled by
the matchup's pace; this scales lin by pace too and scores it walk-forward on the shipped params (data/nba_games_fit.json).

    lin       shipped: tonight's lineup value minus baseline (+ rs x report part), per 100
    linP      lin x pace / league pace (relative scale: the level stays in the coefficient)
    linA      lin x pace / 100 (absolute possessions, so league pace drift across seasons moves it too)
    mktP      linA, and the market rating nets out half the pace-scaled lineup term too (lk_mkt on points)

Each arm: the shipped inputs with lin swapped, weights fit on earlier seasons (walk-forward), margin MAE paired t on
2015-21 (tuning) and 2022-26 (held out), log loss at the fit's season sd, per season. Needs the injury report history
(scripts/.cache/nba/inj_hist.json, scripts/nba_inj_hist.py). Writes data/nba_lin_pace_research.json.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as NF

OUT = os.path.join(N.ROOT, 'data', 'nba_lin_pace_research.json')


class PaceModel(N.Model):
    mkt_pace = False

    def feats(self, g):
        x, tx = super().feats(g)
        P = self.lgp[0] / self.lgp[1]
        pace = self._ctx[2]
        x['linP'] = x['lin'] * pace / P
        x['linA'] = x['lin'] * pace / 100
        if self.mkt_pace:
            self._lin[g['id']] = (x['linA'], pace)
        return x, tx


def walk(games, names, P, params, inj, mkt_pace):
    m = PaceModel(names, P, inj=inj, **params)
    m.mkt_pace = mkt_pace
    out = []
    for g in games:
        x, tx = m.feats(g)
        out.append((g, x))
        m.update(g)
    return [(g, x) for g, x in out if g.get('fin') and g['S'] >= N.FIRST + 1]


def main():
    F = json.load(open(N.FIT))
    games, names = N.load_hist()
    inj = NF.load_inj()
    if not inj:
        sys.exit('no injury report history: run scripts/nba_inj_hist.py 2020 2026 first')
    params, P, feats = F['params'], F['P'], F['feats']
    sdby = {int(k): v for k, v in F['sdBySeason'].items()}
    arms = {}
    for mp in (False, True):
        D = walk(games, names, P, params, inj, mp)
        y = np.array([g['hs'] - g['as'] for g, _ in D], float)
        S = np.array([g['S'] for g, _ in D])
        X = {f: np.array([x[f] for _, x in D]) for f in set(feats) | {'linP', 'linA'}}
        if not mp:
            arms['lin'] = NF.wf(NF.mat(X, feats), y, S)
            for f in ('linP', 'linA'):
                arms[f] = NF.wf(NF.mat(X, [f if c == 'lin' else c for c in feats]), y, S)
        else:
            arms['mktP'] = NF.wf(NF.mat(X, [('linA' if c == 'lin' else c) for c in feats]), y, S)
    win = (y > 0).astype(float)
    sd = np.array([sdby.get(int(s), F['sd']) for s in S])
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM)
    k2 = S >= N.HOLD_FROM

    def ll(pr, k):
        p = np.clip(np.array([N.phi(m / s) for m, s in zip(pr[k], sd[k])]), 1e-6, 1 - 1e-6)
        return -(win[k] * np.log(p) + (1 - win[k]) * np.log(1 - p))
    base = arms['lin']
    res = {'feats': feats, 'arms': {}}
    for a, pr in arms.items():
        e, e0 = np.abs(pr - y), np.abs(base - y)
        r = {}
        for nm, k in (('2015-21', k1), ('2022-26', k2)):
            l, l0 = ll(pr, k), ll(base, k)
            r[nm] = {'n': int(k.sum()), 'mae': round(float(e[k].mean()), 4), 'dMae': round(float((e[k] - e0[k]).mean()), 4),
                     't': round(NF.paired_t(e[k], e0[k]), 2) if a != 'lin' else None,
                     'logLoss': round(float(l.mean()), 5), 'dLogLoss': round(float((l - l0).mean()), 5),
                     'tLogLoss': round(NF.paired_t(l, l0), 2) if a != 'lin' else None}
        r['bySeason'] = {int(s): {'n': int((S == s).sum()), 'dMae': round(float((e[S == s] - e0[S == s]).mean()), 4)}
                         for s in range(N.SCORE_FROM, int(S.max()) + 1)}
        r['seasonsBetter'] = sum(1 for v in r['bySeason'].values() if v['dMae'] < 0)
        res['arms'][a] = r
        print(a, json.dumps({k: v for k, v in r.items() if k != 'bySeason'}), flush=True)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
