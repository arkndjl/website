#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Team special teams rating as an NFL game-model input (Nov 2 2026): the model's own walk-forward (nfl_games.fit's
run, the fitted params) with the shrunk ST rating (scripts/st_teams.py, pre-game, home minus away, points a game)
added, or in place of the Return Game term, or only its non-return units on top of it. Margin MAE on 2015-20
(tune) and 2021-25 (held), paired t clustered by week, and the edge slope against the close.
    python3 scripts/st_teams_nfl_model.py   -> data/st_teams_nfl_model.json
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nfl_games as NG  # noqa: E402
import harness as H  # noqa: E402
import st_teams_research as R  # noqa: E402


def main():
    ev = R.events('nfl')
    _, n0 = R.n0s('nfl', ev)
    pre = R.pregame(ev, n0)
    last = 2025
    games, box, qbs = NG.load(last)
    NG.index_qbs(qbs, games); NG.load_qb_teams(last)
    inj = NG.injury_history(games, range(NG.INJ_FIRST, last + 1))
    params = json.load(open(NG.FIT))['params']
    _, data = NG.walk(games, box, qbs, params)
    D = []
    for g, x, _ in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        p = pre.get(g['game_id'])
        st = lambda k: (p['h'][k] - p['a'][k]) if p and p['h'].get(k) is not None and p['a'].get(k) is not None else 0.0
        x['st'] = st('st')
        x['nonret'] = x['st'] - st('kr') - st('pr')
        D.append((g, x))
    y = np.array([NG.num(g['result']) for g, _ in D])
    S = np.array([int(g['season']) for g, _ in D])
    wk = np.array([f"{g['season']}_{g['week']}" for g, _ in D])
    line = np.array([NG.num(g['spread_line'], np.nan) for g, _ in D])

    def wf(feats):
        X = np.array([[x[f] for f in feats] for _, x in D])
        pred = np.full(len(y), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
            pred[te] = X[te] @ b
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        e = y - X @ b
        cov = (e @ e / (len(y) - len(b))) * np.linalg.inv(X.T @ X)
        return pred, {f: [round(float(v), 3), round(float(v / np.sqrt(cov[i, i])), 1)] for i, (f, v) in enumerate(zip(feats, b))}

    base = NG.FEATS
    variants = {'add st': base + ['st'], 'st for ret': [f for f in base if f != 'ret'] + ['st'], 'add non-return units': base + ['nonret']}
    p0, c0 = wf(base)
    out = {'base': {'feats': base, 'coef': c0}, 'n0': n0['st']}
    for nm, fs in variants.items():
        p1, c1 = wf(fs)
        o = {'feats': fs, 'coef': c1}
        for lab, k in (('2015-20', (S >= 2015) & (S <= 2020)), ('2021-25', S >= 2021)):
            k = k & ~np.isnan(line)
            pr = H.paired(np.abs(p1[k] - y[k]), np.abs(p0[k] - y[k]), cluster=wk[k])
            sl = lambda p: float(np.polyfit(p[k] - line[k], y[k] - line[k], 1)[0])
            o[lab] = {'mae': [round(float(np.mean(np.abs(p0[k] - y[k]))), 3), round(float(np.mean(np.abs(p1[k] - y[k]))), 3)],
                      'd': round(float(pr['d']), 4), 't': round(pr['t'], 2), 'edgeSlope': [round(sl(p0), 3), round(sl(p1), 3)]}
        o['pass'] = bool(o['2015-20']['t'] <= -1.5 and o['2021-25']['d'] < 0)
        out[nm] = o
        print(nm, o, flush=True)
    json.dump(out, open(os.path.join(os.path.dirname(HERE), 'data', 'st_teams_nfl_model.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
