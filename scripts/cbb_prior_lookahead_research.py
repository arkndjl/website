#!/usr/bin/env python3
"""CBB game model: history's preseason rosters and pinj against live (math audit Nov 2 2026 "CBB prior row filter vs
live"; bug sweep "CBB roster prior / pinj history use later-played players").

History builds each team's roster terms from the research seasons, which hold only players who logged minutes that
season, and its pinj from the players who play for the team later in the season. Live builds both from the preseason
rosters and the injury report, which also hold players who never play. The players history drops by knowing they
won't play: a lost season (injury, redshirt) between two lines for the same team. cbb_games.ABSENT puts them back on
the season's roster with no line (roster terms) and counts them out all season (pinj), as live would have them.

Arms (shipped params and inputs, data/cbb_games_fit.json; every prior term rebuilt from the research seasons, cres kept):
    base     ABSENT off
    roster   ABSENT on for the roster terms
    pinj     ABSENT on for pinj
    both
Scored like cbb_roster.py --test: walk-forward margin MAE on D-I games, 2016-20 (tuning) and 2021-26 (held out),
paired t, lined games, per season. Writes data/cbb_prior_lookahead_research.json.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_games as C

OUT = os.path.join(C.ROOT, 'data', 'cbb_prior_lookahead_research.json')


def prior(absent, old):
    C.ABSENT = absent
    tp = C.team_prior_hist()
    for y, T in tp.items():
        for t, v in T.items():
            c = (old.get(y) or {}).get(t, {}).get('cres')
            if c is not None:
                v['cres'] = c
    C.ABSENT = False
    return tp


def pinj(absent):
    C.ABSENT = absent
    C.PINJ.clear()
    out = C.load_all()
    C.ABSENT = False
    return dict(C.PINJ), out


def main():
    F = json.load(open(C.FIT))
    P, feats = F['params'], F['feats']
    old = json.load(open(C.TPRIOR))
    pj = {}
    pj[True], _ = pinj(True)
    pj[False], (games, btname, d1s, _, avs) = pinj(False)
    tps = {False: prior(False, old), True: prior(True, old)}
    diff = max(abs(tps[False][y][t].get(k, 0.0) - old[y][t].get(k, 0.0)) for y in old if y in tps[False]
               for t in old[y] if t in tps[False][y] for k in C.PRIOR_F if k in old[y][t])
    print('rebuilt base prior vs committed: max abs diff', round(diff, 4), flush=True)
    nz = lambda d: sum(1 for v in d.values() if v)
    print('pinj nonzero (team, date) keys: base', nz(pj[False]), 'absent', nz(pj[True]), flush=True)

    def run(ra, pa):
        C.PINJ.clear(); C.PINJ.update(pj[pa])
        W, rows = C.run_walk(P, games, tps[ra], btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        pred = C.walk_pred(Xm, y, S, d1)
        pe = {}
        for s in range(C.SCORE0, C.LAST + 1):
            c = W.pcoef.get(s); R = [r for r in W.prior_rows if r[0] == s]
            if c and R:
                pe[s] = float(np.mean(np.abs(np.array([sum(c[k] * r[2][k] for k in C.PRIOR_F) for r in R]) - np.array([r[3] for r in R]))))
        return pred, y, S, d1, line, pe, {k: round(float(v), 3) for k, v in W.prior_coef(C.LAST + 1).items()}
    arms = {'base': (False, False), 'roster': (True, False), 'pinj': (False, True), 'both': (True, True)}
    R = {a: run(*v) for a, v in arms.items()}
    b, y, S, d1, line, pe0, _ = R['base']
    ok = ~np.isnan(b) & d1
    tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    lined = ~np.isnan(line)
    res = {'arms': {}}
    for a, (p, _, _, _, _, pe, coef) in R.items():
        e1, e0 = np.abs(p - y), np.abs(b - y)
        r = {'tune': {'n': int(tune.sum()), 'mae': round(float(e1[tune].mean()), 4), 'dMae': round(float((e1 - e0)[tune].mean()), 4)},
             'held': {'n': int(held.sum()), 'mae': round(float(e1[held].mean()), 4), 'dMae': round(float((e1 - e0)[held].mean()), 4)},
             'heldLined': {'n': int((held & lined).sum()), 'mae': round(float(e1[held & lined].mean()), 4),
                           'dMae': round(float((e1 - e0)[held & lined].mean()), 4)},
             'priorMae': {str(s): round(v, 3) for s, v in pe.items()}, 'priorCoef2027': coef}
        if a != 'base':
            r['tune']['t'] = round(C.paired_t(e1[tune], e0[tune]), 2)
            r['held']['t'] = round(C.paired_t(e1[held], e0[held]), 2)
            r['heldLined']['t'] = round(C.paired_t(e1[held & lined], e0[held & lined]), 2)
        r['bySeason'] = {str(s): {'n': int((ok & (S == s)).sum()), 'dMae': round(float((e1 - e0)[ok & (S == s)].mean()), 4)}
                         for s in range(C.SCORE0, C.LAST + 1)}
        r['heldSeasonsBetter'] = sum(1 for s, v in r['bySeason'].items() if int(s) > C.TUNE_END and v['dMae'] < 0)
        res['arms'][a] = r
        print(a, json.dumps({k: v for k, v in r.items() if k not in ('bySeason', 'priorMae', 'priorCoef2027')}), flush=True)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
