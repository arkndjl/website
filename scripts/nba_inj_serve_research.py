#!/usr/bin/env python3
"""NBA game model: past games' injury reports in the live walk (basketball audit, Nov 4 2026).

The fit walks every game 2019-20 on with its official report (scripts/.cache/nba/inj_hist.json), so each game's
expected lineup ('lin'), and through lk_mkt the market rating's update after it, sees who was listed. The daily build
(nba_games_build.py) walks the same games with no reports at all (the cache is local; the walk's Model gets no inj), and
only the slate's games get statuses. So in live the market rating absorbs listed absences the fit netted out.

    fit    every game with its report (as fit)
    live   each game's own projection with its report, but the walk past it (its lineup term in the market update) without

Shipped params and inputs (data/nba_games_fit.json); walk-forward margin MAE (nba_games_fit.wf), 2015-21 / 2022-26,
paired t, lined games. Writes data/nba_inj_serve_research.json. Needs the report history (nba_inj_hist.py 2020 2026).

Result (Nov 4 2026, the refit with reports): live MAE 2022-26 10.7361 vs 10.7247 (t +2.01), 2020-26 t +2.13, 2015-21
flat (no reports then), mean |live - fit| .19 pts. So the daily build now walks past games with their reports
(nba_games.load_inj).
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as NF

OUT = os.path.join(N.ROOT, 'data', 'nba_inj_serve_research.json')


def walk(games, names, P, params, inj, live):
    m = N.Model(names, P, inj=inj, **params)
    out = []
    for g in games:
        x, tx = m.feats(g)
        out.append((g, x, tx))
        if live and g['id'] in m.inj:
            rep = m.inj.pop(g['id'])
            m.feats(g)                       # the lineup term the market update reads, with no report
            m.inj[g['id']] = rep
        m.update(g)
    return out


def main():
    F = json.load(open(N.FIT))
    games, names = N.load_hist()
    inj = NF.load_inj()
    if not inj:
        sys.exit('no report history: run scripts/nba_inj_hist.py 2020 2026 first')
    res = {}
    X = {}
    for arm in ('fit', 'live'):
        rows = walk(games, names, F['P'], F['params'], inj, arm == 'live')
        D = [(g, x) for g, x, _ in rows if g.get('fin') and g['S'] >= N.FIRST + 1]
        X[arm] = np.column_stack([np.array([x[f] for _, x in D]) for f in F['feats']])
        y = np.array([g['hs'] - g['as'] for g, _ in D], float)
        S = np.array([g['S'] for g, _ in D])
        line = np.array([g['L'] if g.get('L') is not None else np.nan for g, _ in D])
    # walk-forward weights fit on the fit arm (what live serves), applied to each arm's inputs
    p0, p1 = np.full(len(y), np.nan), np.full(len(y), np.nan)
    for s in range(N.SCORE_FROM, int(S.max()) + 1):
        tr, te = S < s, S == s
        if te.any():
            b = np.linalg.lstsq(X['fit'][tr], y[tr], rcond=None)[0]
            p0[te], p1[te] = X['fit'][te] @ b, X['live'][te] @ b
    ok = ~np.isnan(p0)
    e0, e1 = np.abs(p0 - y), np.abs(p1 - y)
    for nm, k in (('2015-21', ok & (S < N.HOLD_FROM)), ('2022-26', ok & (S >= N.HOLD_FROM)),
                  ('2022-26 lined', ok & (S >= N.HOLD_FROM) & ~np.isnan(line)), ('2020-26', ok & (S >= 2020))):
        res[nm] = {'n': int(k.sum()), 'maeFit': round(float(e0[k].mean()), 4), 'maeLive': round(float(e1[k].mean()), 4),
                   't': round(NF.paired_t(e1[k], e0[k]), 2)}
        print(nm, res[nm], flush=True)
    res['bySeason'] = {str(s): round(float((e1 - e0)[ok & (S == s)].mean()), 4) for s in range(N.SCORE_FROM, int(S.max()) + 1)}
    res['meanAbsGap'] = round(float(np.abs(p1 - p0)[ok].mean()), 3)
    print(res['bySeason'], 'mean |live - fit|', res['meanAbsGap'])
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
