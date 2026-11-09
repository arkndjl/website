#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL rating sd: rank odds (data/rank_sd.json) vs the season sims (nfl_games.rating_sd, 5 x sqrt(left)), Nov 2 2026
audit OPEN item. Research; numpy; reads scripts/data/games_wf/nfl.json.gz and data/nfl_season_backtest.json.

    python3 scripts/nfl_rank_sd_research.py     -> data/nfl_rank_sd_research.json

Scoring 1, rank odds' (scripts/rank_odds.py fit_sport): at 0/20/40/60/80% of each regular season, every team's rating
read back from the walk-forward margins, scored on its mean residual over the rest of the season, normal nll with
variance sd^2 x T/(T-1) + game noise / games left ('pure' noise, the fit's own fixed point). Each season 2016-26 scored
with sd^2 = a + b x left from the seasons before it (rank_odds' walk-forward fit) against fixed candidates: the sims'
25 x left, the committed data/rank_sd.json (10.5 + 5.5 x left), and a flat 18 (the pure-noise fit's own a, b).
Paired t over team-checkpoints, per-season mean differences.
Scoring 2, the season sims' (scripts/nfl_season_backtest.py simTest, already run, not rerun here): make the playoffs
+ win the division + final wins log loss at weeks 1-17, tune 2015-20 / held 2021-25; read from the file.

RESULT (Nov 2 2026): FAIL, neither made to match the other (no code change).
  Rank scoring, 1815 team-checkpoints 2016-26: the walk-forward fit (pure noise) vs the sims' 25 x left nll 3.1957 vs
    3.1980, t -0.83, 5/11 seasons; committed 10.5 + 5.5 x left t -1.75 (8/11); flat 18 (a, b from every season, so
    not out of sample) t -2.28 (7/11). The read-back sd is flat (4.23 open, 3.91 at 80%) where the sims' shrinks
    (5.0 -> 2.24); late checkpoints favor the flat sd, but the season-level gain does not clear t -1.5.
  Sim scoring (simTest, team-seasons): a flat 4 / 4.5 (the rank sd) vs 5 x sqrt(left): tune 2015-20 2.2234 / 2.2224
    vs 2.2197 (t +1.07 / +0.76, worse), held 2021-25 2.5870 / 2.5796 vs 2.5995 (t -2.49 / -2.87). Fails the tune split.
  The two answer different questions with different noise: the sims' sd also stands in for the margin model's full
  game noise (gameTest), the rank sd is net of it; each is best on its own scoring, so both stay.
  Found: data/rank_sd.json's NFL row (10.5 + 5.5 x left, no `noise` key) is the pre-audit 'own' fit: the Nov 2 refit
  (30c36dd) wrote over #712's pure-noise fit (a 18, b 0, sd 4.24, walk nll 3.1957 vs 3.1975). The current
  rank_odds.py --fit restores it.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rank_odds as RO  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'nfl_rank_sd_research.json')


def main():
    R = RO.checkpoints('nfl')
    Sx, ck, A, n, sh, gn, T = (R[:, i] for i in range(7))
    res = {'rows': int(len(A)), 'fits': {}}
    for mode in ('pure', 'own'):
        f = RO.fit_sport('nfl', R, mode)
        f.pop('_rows')
        res['fits'][mode] = {k: f[k] for k in ('a', 'b', 'sdOpen', 'sdEnd', 'byCheckpoint', 'gameSd', 'ownSd')}
        res['fits'][mode]['walk'] = {k: f['walk'][k] for k in ('nll', 'nllFlat')}
        res['fits'][mode]['ab'] = f['walk']['ab']
    ab = {int(k): v for k, v in res['fits']['pure']['ab'].items()}

    def noise(a, b):
        return np.maximum(0.3 * gn, gn - 2 * (a + b * 0.5) * T / (T - 1))

    def nll(s2, g_):
        v = np.maximum(s2, 0.05) * T / (T - 1) + g_ / n
        return 0.5 * (np.log(2 * np.pi * v) + A ** 2 / v)
    cands = {'walkFit': None, 'sim 25 x left': (0.0, 25.0), 'rank_sd.json 10.5 + 5.5 x left': (10.5, 5.5), 'flat 18': (18.0, 0.0)}
    seasons = sorted(ab)
    k = np.isin(Sx, seasons)
    L = {}
    for name, c in cands.items():
        out = np.zeros(len(A))
        for s in seasons:
            m = Sx == s
            a, b = ab[s]
            g_ = noise(a, b)                     # the same game noise for every candidate (the walk fit's, no peeking)
            aa, bb = (a, b) if c is None else c
            out[m] = nll(aa + bb * sh, g_)[m]
        L[name] = out[k]
    base = L['sim 25 x left']
    sc = {}
    for name, v in L.items():
        d = v - base
        per = {str(s): round(float(d[Sx[k] == s].mean()), 4) for s in seasons}
        sc[name] = {'nll': round(float(v.mean()), 4),
                    'vsSim': None if name == 'sim 25 x left' else {
                        'd': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
                        'better': f"{sum(x < 0 for x in per.values())}/{len(per)}", 'seasons': per}}
    # by checkpoint: the read-back sd vs the sim's sd
    res['byCheckpoint'] = {str(c): {'simSd': round(5 * math.sqrt(1 - c), 2), 'measuredSd': res['fits']['pure']['byCheckpoint'][str(c)],
                                    'dNll(walkFit - sim)': round(float((L['walkFit'] - base)[ck[k] == c].mean()), 4)}
                           for c in (0, .2, .4, .6, .8)}
    res['rankScoring'] = sc
    B = json.load(open(os.path.join(ROOT, 'data', 'nfl_season_backtest.json')))['simTest']['grid']
    res['simScoring'] = {r['cfg']: {'tune': r['tune']['llAll'], 'held': r['held']['llAll'], 'tTune': r['tTune'], 'tHeld': r['tHeld']}
                         for r in B if r['cfg'] in ('5 x left^0.5, floor 0', 'fixed 4', 'fixed 4.5', 'fixed 3', 'fixed 3.5')}
    print(json.dumps(res, indent=1))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
