#!/usr/bin/env python3
"""The market's preseason view for the college basketball game model's totals: last season's closing totals, team by
team (scripts/cbb_games.py 'tpri', 'tcar'), the test that NBA totals passed (scripts/nba_market_prior.py).

    python3 scripts/cbb_market_prior.py      # writes data/cbb_market_prior.json

No free history of college basketball futures exists (scripts/futures_hist.py), so a preseason prior from title or
conference odds can't be backtested yet; scripts/futures_archive.py keeps DraftKings' daily prices from 2026-27 on.
The margin's market terms were tested before (mrev, the market rating carried over, and mkteff, the market rating
weighted up over the first 10 games: both fail 2016-20; data/cbb_games_fit.json).
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_games as C
import harness as H

OUT = os.path.join(C.ROOT, 'data', 'cbb_market_prior.json')


def main():
    games, btname, d1s, tprior, avs = C.load_all()
    fit = json.load(open(C.FIT))
    P0 = {**fit['params'], 'tcar': 0.0}
    TF0 = [f for f in C.TFEATS if f != 'tpri']

    def run(extra):
        W, rows = C.run_walk({**P0, **extra}, games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, ['eff'], TF0 + ['tpri'])
        return D, TX, ty, S, tline, d1

    D, TX, ty, S, tline, d1 = run({})
    cnt, ng = {}, []
    for g, _, _ in D:
        k = lambda t: (g['season'], t)
        ng.append(min(cnt.get(k(g['home']), 0), cnt.get(k(g['away']), 0)))
        cnt[k(g['home'])] = cnt.get(k(g['home']), 0) + 1; cnt[k(g['away'])] = cnt.get(k(g['away']), 0) + 1
    ng = np.array(ng)
    day = np.array([str(g['date'])[:10] for g, _, _ in D])
    tune = (S >= C.SCORE0) & (S <= C.TUNE_END) & d1
    hold = (S > C.TUNE_END) & d1
    has = ~np.isnan(tline)
    nb = len(TF0)
    base = C.walk_pred(TX[:, :nb], ty, S, d1)

    def score(pr):
        out = {}
        for nm, k in (('tune', tune), ('hold', hold)):
            for lo, hi in ((0, 3), (3, 10), (10, 999), (0, 999)):
                m = k & has & (ng >= lo) & (ng < hi) & ~np.isnan(pr) & ~np.isnan(base)
                pt = H.paired(np.abs(pr[m] - ty[m]), np.abs(base[m] - ty[m]), cluster=day[m])
                out[f'{nm} {lo}-{hi if hi < 999 else "end"}'] = {
                    'n': int(m.sum()), 'mae': round(float(np.mean(np.abs(pr[m] - ty[m]))), 3), 'd': round(pt['d'], 4),
                    't': round(pt['t'], 2), 'toClose': round(float(np.mean(np.abs(pr[m] - tline[m]))), 3),
                    'toCloseBase': round(float(np.mean(np.abs(base[m] - tline[m]))), 3)}
        return out

    res = {'base': {'tfeats': TF0, 'total': score(base)}, 'total': {}}
    more = '--more' in sys.argv            # the carry alone, further out
    if more:
        res = json.load(open(OUT))
    for tc in ((0.75, 1.0) if more else (0.0, 0.25, 0.5)):
        for phl in ((5.0,) if more else (5.0, 15.0, 40.0, 1e9)):
            D2, TX2, *_ = run({'tcar': tc, 'tphl': phl})
            for nm, cols in (('carry only', list(range(nb))), ('tpri', list(range(nb + 1)))):
                if nm == 'carry only' and (tc == 0.0 or phl != 5.0) or nm == 'tpri' and more:
                    continue
                pr = C.walk_pred(TX2[:, cols], ty, S, d1)
                key = f'{nm} tcar {tc:g}' + (f' tphl {phl:g}' if nm == 'tpri' else '')
                res['total'][key] = a = score(pr)
                print(key, {k: (v['d'], v['t'], v['toClose'], v['toCloseBase']) for k, v in a.items() if k.endswith(' 0-3') or k.endswith('0-end')}, flush=True)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
