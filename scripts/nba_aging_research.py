#!/usr/bin/env python3
"""Research (Oct 30 2026): an age term on the NBA lineup values, in the form that passed for the NHL (PR #583).

    python3 scripts/nba_aging_research.py     # writes data/nba_aging_research.json (numpy)

The game model's player value (nba_games.values) is last season's XPM plus the one before at half weight, shrunk
toward -1 with 600 minutes; it has no age term. The Oct 21 test (age=1: the delta-method curve, scaled by the prior's
reliability) helped the player priors but hurt games 2015-21 (t +1.7). The NHL form fits the prior's own miss on age:
each season's XPM minus the player's prior for it, minutes-weighted, on age, walk-forward, net of the overall mean.
    age=2   one line (about -.09 XPM a year, centred 27)
    age=3   quadratic
    age=4   a line per position group (G / F / C from last season's listed position)
Player level: the prior's minutes-weighted squared error on the season's XPM, 2015-21 and 2022-26. Game level: same
walk-forward as the fit (nba_roster_research.py), MAE and log loss of the win chance, paired t by game and seasons won.
Kept by the fit's rule: paired MAE t <= -1.5 on 2015-21 and 2022-26 no worse.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as Fit

OUT = os.path.join(N.ROOT, 'data', 'nba_aging_research.json')


def player_level(base):
    n0, rook = base.get('n0', 600.0), base.get('rook', -1.0)
    F = {y: {p['id']: p for p in json.load(open(os.path.join(N.XPM, f'{y}.json')))['players']
             if p.get('xpm') is not None and not p.get('pr')} for y in range(2010, 2027)}
    res = {}
    for age in (0, 1, 2, 3, 4):
        rows = []
        for S in range(2015, 2027):
            cv = N.aging_curve(S) if age == 1 else None
            al = N.age_line(S, n0, rook, 0.5, {2: 'lin', 3: 'quad', 4: 'pos'}[age]) if age >= 2 else None
            for pid, p in F[S].items():
                a, b = F[S - 1].get(pid), F[S - 2].get(pid)
                if not a or not a.get('age') or p['mp'] < 100:
                    continue
                num, den = rook * n0 + a['xpm'] * a['mp'], n0 + a['mp']
                if b:
                    num += b['xpm'] * b['mp'] * 0.5; den += b['mp'] * 0.5
                v = num / den
                if cv:
                    v += cv(a['age'] + 1) * a['mp'] / (a['mp'] + n0)
                if al:
                    v += al(a['age'] + 1, a.get('pos'))
                rows.append((S, (v - p['xpm']) ** 2 * p['mp']))
        res[age] = np.array(rows)
    out = {}
    for age in (1, 2, 3, 4):
        r = {}
        for nm, lo, hi in (('2015_21', 2015, 2022), ('2022_26', 2022, 2027)):
            k = (res[0][:, 0] >= lo) & (res[0][:, 0] < hi)
            e, e0 = res[age][k, 1], res[0][k, 1]
            r[nm] = {'relRmse': round(math.sqrt(e.sum() / e0.sum()) - 1, 4), 't': round(Fit.paired_t(e, e0), 2)}
        out[f'age={age}'] = r
        print('player', age, r, flush=True)
    return out


def run():
    F = json.load(open(N.FIT))
    games, names = N.load_hist()
    inj = Fit.load_inj()
    P, feats, base = F['P'], F['feats'], F['params']
    out = {'player': player_level(base)}

    def design(params):
        _, data = N.walk(games, names, P, params, inj=inj)
        D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
        X = {f: np.array([x[f] for _, x in D], float) for f in D[0][1]}
        y = np.array([g['hs'] - g['as'] for g, _ in D], float)
        S = np.array([g['S'] for g, _ in D])
        return X, y, S
    X0, y, S = design(base)
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(X0, feats), y, S)
    sd = F.get('sd', 12.25)
    win = (y > 0).astype(float); keep = y != 0

    def ll(pr):
        p = np.clip(np.array([N.phi(v / sd) for v in pr]), 1e-6, 1 - 1e-6)
        return -(win * np.log(p) + (1 - win) * np.log(1 - p))
    l0 = ll(ref)

    def score(pr, lab):
        r = {'label': lab}
        e, e0, l = np.abs(pr - y), np.abs(ref - y), ll(pr)
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            kk = k & keep
            r[nm] = {'n': int(k.sum()), 'mae': round(float(e[k].mean()), 4), 'd': round(float(e[k].mean() - e0[k].mean()), 4),
                     't': round(Fit.paired_t(e[k], e0[k]), 2), 'll': round(float(l[kk].mean()), 5),
                     'llD': round(float(l[kk].mean() - l0[kk].mean()), 5), 'llT': round(Fit.paired_t(l[kk], l0[kk]), 2)}
        r['seasonsBetterMAE'] = f"{sum(e[S == s].mean() < e0[S == s].mean() for s in range(N.SCORE_FROM, int(S.max()) + 1))}/{int(S.max()) - N.SCORE_FROM + 1}"
        r['kept'] = r['2015_21']['t'] <= -1.5 and r['2022_26']['d'] <= 0
        print(json.dumps(r), flush=True)
        return r
    out['games'] = []
    for age in (1, 2, 3, 4):
        X, _, _ = design({**base, 'age': age})
        out['games'].append(score(Fit.wf(Fit.mat(X, feats), y, S), f'age={age}'))
        out['games'][-1]['linCoef'] = None
    with open(OUT, 'w') as fh:
        json.dump(out, fh, indent=1)


if __name__ == '__main__':
    run()
