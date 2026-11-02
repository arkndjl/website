#!/usr/bin/env python3
"""Does the close underprice practice news? (research; Nov 2 2026 lead from the Nov 1 sweep, PRACTICE_Q)

    python3 scripts/nfl_practice_close_research.py     # numpy; nflverse downloads + nfl_war ledgers (slow first run)
    -> data/nfl_practice_close_research.json

The term: each game's injury cost (non-QB game status report, nfl_games.injury_history's loop) priced two ways, a
questionable player at his last practice (nfl_games.PRACTICE_Q, live) and at the flat .75/.5 the model used before;
dprac = (away - home) under practice pricing minus the same under flat pricing, in points (the part of the inj
term that is practice news). Target: result minus the closing spread (nflverse spread_line), regular season and
playoffs, games in scripts/data/games_wf/nfl.json.gz (the walk-forward margins the picks layer reads), 2016-25.
Tests: (a) rr ~ dprac alone; (b) rr ~ (m - L) + dprac, the picks layer's edge plus the extra; fit on 2016-20,
judged on 2021-25 (coefficient, t by week clusters, and squared error of the held predictions vs edge-only, paired
t by week), and walk-forward 2018-25 (each season fit on the seasons before it).
Gate: tune t(dprac | edge) >= 1.5, held >= 2, held squared error paired t <= -1.5, walk-forward t <= -1.5.

RESULT (Nov 2 2026): FAIL, nothing wired into the picks. 2761 games (2608 with dprac != 0; sd .145 points).
    tune 2016-20 (n 1337): rr ~ dprac b 2.64, t 1.08; with the edge b 2.78, t 1.14 (edge b .38, t 3.1)
    held 2021-25 (n 1424): rr ~ dprac b 3.96, t 1.42; with the edge b 3.89, t 1.39 (edge b .15, t 1.1)
    held squared error with the tune coefficients 160.405 -> 160.141, t -0.84 (week clusters)
    walk-forward 2018-25: dSE +.072, t +0.25, 4/8 seasons better (2018-20 and 2023 worse)
    per-season b: 2016 9.4, 2017 2.6, 2018 -0.7, 2019 0.4, 2020 -1.8, 2021 6.2, 2022 5.5, 2023 -5.1, 2024 8.7, 2025 7.3
The sign is right in 7 of 10 seasons, but the term is small (b x sd ~ .5 point) and the Nov 1 sweep's t 1.6 / 2.5
(the model's change, iid errors) shrinks to 1.1 / 1.4 clustered by week. Retest after 2026 if it keeps its sign.
"""
import json
import os
import sys
import gzip
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nfl_games as N  # noqa: E402
import harness as H  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'nfl_practice_close_research.json')
WF = os.path.join(HERE, 'data', 'games_wf', 'nfl.json.gz')


def flat_prob(stt, played):
    if stt == 'Questionable':
        return 0.75 if played else 0.5
    return N.play_prob(stt, played)


def inj_both(games, years):
    """game_id -> [home prac, away prac, home flat, away flat] injury cost in points (nfl_games.injury_history loop)"""
    import nfl_war as W
    cp = os.path.join(N.CACHE, 'inj_hist_pracflat.json')
    try:
        cache = json.load(open(cp))
    except (OSError, ValueError):
        cache = {}
    for y in years:
        if str(y) in cache:
            continue
        maps = W.gsis_map(y)
        prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
        top = max([int(g['week']) for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')] + [1])
        led = {w: W.war_ledger(y, thru=w, maps=maps) for w in range(1, min(top + 1, 19) + 1)}
        rep = defaultdict(list)
        for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
            if r['report_status'] and r['position'] != 'QB':
                rep[(N.team(r['team']), int(r['week']))].append((r['gsis_id'], r['report_status'], N.practice_of(r['practice_status'])))
        sg = [g for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')]
        last_wk, out = {}, {}
        for g in sg:
            w = int(g['week'])
            vals = {}
            for side in ('home', 'away'):
                t = N.team(g[f'{side}_team'])
                pw = last_wk.get(t)
                cp_, cf_ = 0.0, 0.0
                for gsis, stt, prac in rep.get((t, w), []):
                    L = led[min(w, 19, top + 1)]
                    v = N.player_value(prev.get(gsis, (0.0, 0)), L.get(gsis, (0.0, 0)))
                    played = True if (pw is None or pw >= 18 or w > 18) else led[pw + 1].get(gsis, (0, 0))[1] > led[pw].get(gsis, (0, 0))[1]
                    cp_ += (1 - N.play_prob(stt, played, prac)) * max(v, 0.0) * N.PTS_PER_WIN
                    cf_ += (1 - flat_prob(stt, played)) * max(v, 0.0) * N.PTS_PER_WIN
                vals[side] = (cp_, cf_)
                last_wk[t] = w
            out[g['game_id']] = [round(vals['home'][0], 4), round(vals['away'][0], 4), round(vals['home'][1], 4), round(vals['away'][1], 4)]
        cache[str(y)] = out
        json.dump(cache, open(cp, 'w'))
        print('injuries', y, len(out), flush=True)
    return {gid: v for y in years for gid, v in cache[str(y)].items()}


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cl_t(X, y, cl):
    """OLS (no intercept) and week-clustered t (CR1)"""
    b = ols(X, y)
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    meat = np.zeros((X.shape[1], X.shape[1]))
    G = 0
    for k in set(cl.tolist()):
        m = cl == k
        s = X[m].T @ e[m]
        meat += np.outer(s, s)
        G += 1
    n, p = X.shape
    V = XtXi @ meat @ XtXi * G / (G - 1) * (n - 1) / (n - p)
    return b, b / np.sqrt(np.diag(V))


def main():
    games = [g for g in N.rows(N.get('games.csv', N.GAMES)) if N.FIRST <= int(g['season']) <= 2025]
    games.sort(key=lambda g: (g['gameday'], g['gametime'], g['game_id']))
    inj = inj_both(games, range(N.INJ_FIRST, 2026))
    wf = [r for r in json.load(gzip.open(WF)) if 2016 <= r['S'] <= 2025 and r['id'] in inj and r['L'] is not None]
    S = np.array([r['S'] for r in wf])
    wk = np.array([f"{r['S']}-{r['wk']}" for r in wf])
    rr = np.array([r['res'] - r['L'] for r in wf])
    edge = np.array([r['m'] - r['L'] for r in wf])
    I = np.array([inj[r['id']] for r in wf])
    dprac = (I[:, 1] - I[:, 0]) - (I[:, 3] - I[:, 2])
    res = {'n': len(wf), 'nonzero': int((np.abs(dprac) > 1e-9).sum()), 'sdDprac': round(float(dprac.std()), 3), 'bySeason': {}}
    for s in range(2016, 2026):
        k = S == s
        res['bySeason'][str(s)] = {'n': int(k.sum()), 'nonzero': int((np.abs(dprac[k]) > 1e-9).sum()),
                                   'b': round(float(ols(dprac[k, None], rr[k])[0]), 3)}
    tune, held = (S <= 2020), (S >= 2021)
    for lab, k in (('tune 2016-20', tune), ('held 2021-25', held)):
        b, t = cl_t(dprac[k, None], rr[k], wk[k])
        b2, t2 = cl_t(np.c_[edge[k], dprac[k]], rr[k], wk[k])
        res[lab] = {'n': int(k.sum()), 'alone': {'b': round(float(b[0]), 3), 't': round(float(t[0]), 2)},
                    'withEdge': {'bEdge': round(float(b2[0]), 3), 'tEdge': round(float(t2[0]), 2),
                                 'bDprac': round(float(b2[1]), 3), 'tDprac': round(float(t2[1]), 2)}}
    # out of sample: coefficients from 2016-20, scored on 2021-25 (squared error of result - close)
    be = ols(edge[tune, None], rr[tune])
    b2 = ols(np.c_[edge, dprac][tune], rr[tune])
    p0 = edge[held] * be[0]
    p1 = np.c_[edge, dprac][held] @ b2
    r = H.paired((rr[held] - p1) ** 2, (rr[held] - p0) ** 2, cluster=wk[held])
    res['heldSE'] = {'bTune': [round(float(x), 3) for x in b2], 'mse0': round(float(np.mean((rr[held] - p0) ** 2)), 3),
                     'mse1': round(float(np.mean((rr[held] - p1) ** 2)), 3), 'd': round(r['d'], 4), 't': round(r['t'], 2)}
    # walk-forward 2018-25
    ds, ws, per = [], [], {}
    for s in range(2018, 2026):
        tr, te = S < s, S == s
        be = ols(edge[tr, None], rr[tr])
        b2 = ols(np.c_[edge, dprac][tr], rr[tr])
        d = (rr[te] - np.c_[edge, dprac][te] @ b2) ** 2 - (rr[te] - edge[te] * be[0]) ** 2
        ds.append(d)
        ws.append(wk[te])
        per[str(s)] = {'n': int(te.sum()), 'bDprac': round(float(b2[1]), 3), 'dSE': round(float(d.mean()), 4)}
    D = np.concatenate(ds)
    r = H.paired(D, np.zeros(len(D)), cluster=np.concatenate(ws))
    res['walk'] = {'seasons': per, 'dSE': round(r['d'], 4), 't': round(r['t'], 2),
                   'better': f"{sum(v['dSE'] < 0 for v in per.values())}/{len(per)}"}
    res['passes'] = bool(res['tune 2016-20']['withEdge']['tDprac'] >= 1.5 and res['held 2021-25']['withEdge']['tDprac'] >= 2
                         and res['heldSE']['t'] <= -1.5 and res['walk']['t'] <= -1.5)
    print(json.dumps(res, indent=1))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
