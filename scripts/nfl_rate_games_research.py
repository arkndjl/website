#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""pXP/60 as an NFL game-model input: research only, writes data/nfl_rate_games_research.json (numpy).

    python3 scripts/nfl_rate_research.py --prep     # once: board rows 2016-25 (scripts/.cache/nfl/rate_rows_<y>.json)
    python3 scripts/nfl_rate_games_research.py

Candidates (home minus away, points a game), each added to the live margin model's inputs (nfl_games.FEATS, injuries
from nfl_games.injury_history) and scored in the same walk-forward refit as scripts/nfl_games_research.py:
    rr     every player on the team's active roster that week (nflverse weekly rosters, status ACT), less those listed
           Out or Doubtful on the game status report, at his preseason pXP/60 (seasons S-1, S-2, S-3 at 1 / .7 / .5,
           shrunk to the sub-position mean by data/nfl_rate_fit.json K) x last season's share of team snaps on his side
           (points over an average regular a game at that role). QBs left out (the QB term carries the starter)
    rrQ    rr with QBs in
    rrE    rr fading as games are played: x .5 ** (games played / 4) (the ratings learn the roster)
    rrD    rr minus the same sum over the whole active roster (absences only: what the injury term prices at WAR)
Rule (the project's): a term gains on 2015-20 at t <= -1.5 and the held-out 2021-25 agrees (t < 0); else logged.
Rates exist from 2016, so 2015-16 rows read 0 (S-1 is 2016 at the earliest: the term is live from 2017).
The K and sub-position means come from a fit on next-season rates over 2016-24, so seasons inside the tuning window
saw a little of their own future in those 16 numbers; the held-out 2021-25 verdict carries the evidence.
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nfl_games as N   # noqa: E402
import nfl_war as W     # noqa: E402
import nfl_rate as R    # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'nfl_rate_games_research.json')
CACHE = os.path.join(HERE, '.cache', 'nfl')


def rows_by_year():
    D = {}
    for y in range(2016, 2026):
        p = os.path.join(CACHE, f'rate_rows_{y}.json')
        if os.path.exists(p):
            D[y] = {r['id']: r for r in json.load(open(p))}
    return D


def preseason(D, y, M):
    """{pfr: (pXP/60 from S-1..S-3, last season's share, group)} for season y"""
    out = {}
    for pid, r in D.get(y - 1, {}).items():
        g = r['grp']
        P, S = 0.0, 0.0
        for i, w in enumerate(M['marcel']):
            h = D.get(y - 1 - i, {}).get(pid)
            if h and h['grp'] == g:
                P += w * h['pts'] * 60; S += w * h['sn']
        k = M['K'][g]
        out[pid] = ((P + k * M['m'].get(r['sub'], 0.0)) / (S + k), min(1.0, r['shr']), g)
    return out


def team_sums(games, D, M):
    """game_id -> {rr, rrQ, rrAll} home minus away"""
    out = {}
    for y in range(2017, 2026):
        pre = preseason(D, y, M)
        by_pfr, _ = W.gsis_map(y)
        gs2 = {v: k for k, v in by_pfr.items()}
        pv = {}
        for gsis, pfr in gs2.items():
            if pfr in pre:
                pv[gsis] = pre[pfr]
        rep = {}
        for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
            rep[(N.team(r['team']), int(r['week']), r['gsis_id'])] = r['report_status']
        S = defaultdict(lambda: [0.0, 0.0, 0.0])   # (team, week) -> [rr, rrQ, all non-QB]
        for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv')):
            if r['status'] != 'ACT' or r['gsis_id'] not in pv:
                continue
            t, w = N.team(r['team']), int(r['week'])
            v, sh, g = pv[r['gsis_id']]
            c = v * sh
            a = S[(t, w)]
            if g != 'QB':
                a[2] += c
            if rep.get((t, w, r['gsis_id'])) in ('Out', 'Doubtful'):
                continue
            a[1] += c
            if g != 'QB':
                a[0] += c
        for g in games:
            if int(g['season']) != y:
                continue
            w = int(g['week'])
            h, a = S.get((N.team(g['home_team']), w), [0.0] * 3), S.get((N.team(g['away_team']), w), [0.0] * 3)
            out[g['game_id']] = {'rr': h[0] - a[0], 'rrQ': h[1] - a[1], 'rrD': (h[0] - h[2]) - (a[0] - a[2])}
        print('rate sums', y, flush=True)
    return out


def main():
    import numpy as np
    last = 2025
    F = json.load(open(N.FIT))
    params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, params)
    M = json.load(open(R.FIT))['model']
    RS = team_sums(games, rows_by_year(), M)
    gp = defaultdict(int); gpl = {}
    for g in games:
        h, aw = N.team(g['home_team']), N.team(g['away_team'])
        k = int(g['season'])
        gpl[g['game_id']] = (gp[(k, h)] + gp[(k, aw)]) / 2
        if g['home_score'] not in ('', 'NA'):
            gp[(k, h)] += 1; gp[(k, aw)] += 1
    D = []
    for g, x, _ in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        x = dict(x)
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1]); x['ir'] = r[5] - r[4]
        x.update(RS.get(g['game_id'], {'rr': 0.0, 'rrQ': 0.0, 'rrD': 0.0}))
        x['rrE'] = x['rr'] * 0.5 ** (gpl[g['game_id']] / 4)
        D.append((g, x))
    S = np.array([int(g['season']) for g, _ in D])
    y = np.array([N.num(g['result']) for g, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D])
    ok = ~np.isnan(line)
    A = (S >= 2015) & (S <= 2020) & ok; B = (S >= 2021) & ok; A17 = (S >= 2017) & (S <= 2020) & ok

    def wf(feats):
        X = np.array([[x[f] for f in feats] for _, x in D])
        pred = np.full(len(y), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        return np.abs(pred - y), pred, dict(zip(feats, b))

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)

    base = list(N.FEATS)
    e0, p0, _ = wf(base)
    res = {'base': {'feats': base, 'mae1520': round(float(e0[A].mean()), 3), 'mae2125': round(float(e0[B].mean()), 3)}, 'cands': {}}
    for k in ('rr', 'rrQ', 'rrE', 'rrD'):
        e1, p1, b = wf(base + [k])
        d1, d2 = cmp(e1, e0, A), cmp(e1, e0, B)
        sd = float(np.std([x[k] for g, x in D if int(g['season']) >= 2017]))
        res['cands'][k] = {'d1520': d1, 'd1720': cmp(e1, e0, A17), 'd2125': d2, 'coef': round(float(b[k]), 3), 'sd': round(sd, 3),
                           'pass': d1[1] <= -1.5 and d2[1] < 0}
        print(k, res['cands'][k], flush=True)
    # residual check: does the term predict the result over the closing line (what the market misses)?
    for k in ('rr', 'rrQ'):
        X = np.array([[1.0, x[k]] for _, x in D])[B]
        rr_ = (y - line)[B]   # nflverse spread_line: home favoured by +line, result home minus away
        b = np.linalg.lstsq(X, rr_, rcond=None)[0]
        e = rr_ - X @ b
        se = math.sqrt(float(e @ e) / (len(e) - 2) / float(((X[:, 1] - X[:, 1].mean()) ** 2).sum()))
        res['cands'][k]['vsClose2125'] = {'b': round(float(b[1]), 3), 't': round(float(b[1] / se), 2)}
    res['kept'] = [k for k, v in res['cands'].items() if v['pass']]
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
