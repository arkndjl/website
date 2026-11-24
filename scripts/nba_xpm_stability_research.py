#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""XPM stabilization study (Nov 24 2026, for the XPM stabilization article). Split-half reliability in the
Carleton / LumaHoops style: each team's first 2k games, odd vs even games, a player's value on each half, Pearson r.
Players need 5+ min per team game in each half (about 10 possessions). Seasons 2014-26 less 2020 and 2021.

    box XPM = the game-level version of XPM: per-48 box rates over the league's, ridge-fit on the seasons before
              (scripts/nba_inseason.coef, point in time). Also on-court +/- per 48 and single box rates.

Games to r = .50 (padding, M) from Spearman-Brown, r(k) = k / (k + M): M = k (1 - r) / r, the median over k = 10..41.
Games to .75 = 3M. Minutes = M x the sample's minutes per game; possessions = minutes x league possessions per minute.
Also: year-to-year r (500+ MP both seasons) and next-season RMSE of rXPM vs pXPM (nba_xpm shrink fits).
Box lines: scripts/nba_box_hist.json.gz (project files team-models/). -> data/nba_xpm_stability_research.json"""
import json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import nba_inseason as I, nba_games as N

KS = (5, 10, 15, 20, 25, 30, 41)
SEASONS = [s for s in range(2014, 2027) if s not in (2020, 2021)]
C = {c: i for i, c in enumerate(I.COLS)}


def metrics(v, lg, b):
    m = v[0]
    fga, fta = v[C['fga']], v[C['fta']]
    tsa = 2 * (fga + .44 * fta)
    return {'box XPM': I.box_xpm(v, b, lg), 'on-court +/-': v[C['pm']] / m * 48,
            'PTS/48': v[C['pts']] / m * 48, 'AST/48': v[C['ast']] / m * 48, 'OREB/48': v[C['oreb']] / m * 48,
            'DREB/48': v[C['dreb']] / m * 48, 'STL/48': v[C['stl']] / m * 48, 'BLK/48': v[C['blk']] / m * 48,
            'TOV/48': v[C['tov']] / m * 48, 'PF/48': v[C['pf']] / m * 48,
            '3PA rate': v[C['fg3a']] / fga if fga else None, 'TS%': v[C['pts']] / tsa if tsa else None}


def main():
    games, _ = I._hist(); bx = I.load_box()
    by = defaultdict(list)
    for g in games:
        if g['t'] == 2 and g['S'] in SEASONS and g['id'] in bx:
            by[g['S']].append(g)
    R = defaultdict(lambda: defaultdict(list)); mpg = defaultdict(list); ppm = []
    for S in SEASONS:
        b = I.coef(S)
        gs = sorted(by[S], key=lambda g: g['tip'])
        ppm += [g['poss'] / 48 for g in gs if g.get('poss')]
        gn = defaultdict(int); lines = defaultdict(list)          # (team, pid) -> [(team game no, line)]
        for g in gs:
            for t in (g['h'], g['a']):
                gn[t] += 1
                for r in bx[g['id']].get(t, []):
                    if r[0]: lines[(t, r[0])].append((gn[t], np.array(r[1:], float)))
        for k in KS:
            H = {}
            for key, ls in lines.items():
                a = sum((x for n, x in ls if n <= 2 * k and n % 2), np.zeros(len(I.COLS)))
                e = sum((x for n, x in ls if n <= 2 * k and not n % 2), np.zeros(len(I.COLS)))
                if a[0] >= 5 * k and e[0] >= 5 * k: H[key] = (a, e)
            lga = np.sum([h[0] for h in H.values()], 0); lge = np.sum([h[1] for h in H.values()], 0)
            for a, e in H.values():
                ma, me = metrics(a, lga, b), metrics(e, lge, b)
                for name in ma:
                    if ma[name] is not None and me[name] is not None: R[k][name].append((S, ma[name], me[name]))
                mpg[k].append((a[0] + e[0]) / (2 * k))
    out = {'seasons': SEASONS, 'poss_per_min': round(float(np.mean(ppm)), 3), 'byK': {}, 'stab': {}}
    names = list(R[KS[0]])
    for k in KS:
        out['byK'][k] = {n: round(float(np.corrcoef(np.array(R[k][n])[:, 1:].T)[0, 1]), 3) for n in names}
        out['byK'][k]['_n'] = len(R[k]['box XPM']); out['byK'][k]['_mpg'] = round(float(np.mean(mpg[k])), 1)
    for n in names:
        Ms = [k * (1 - out['byK'][k][n]) / out['byK'][k][n] for k in KS if k >= 10 and out['byK'][k][n] > 0]
        M = float(np.median(Ms)); mp = M * out['byK'][41]['_mpg']
        out['stab'][n] = {'g50': round(M), 'g75': round(3 * M), 'min50': round(mp, -1), 'poss50': round(mp * out['poss_per_min'], -1)}
    rng = np.random.default_rng(0)                         # 90% intervals: resample seasons, 2,000 draws
    A = {k: {n: np.array(R[k][n]) for n in names} for k in KS}
    for n in names:
        g = []
        for _ in range(2000):
            pick = rng.choice(SEASONS, len(SEASONS))
            Ms = []
            for k in KS:
                if k < 10: continue
                X = np.concatenate([A[k][n][A[k][n][:, 0] == s, 1:] for s in pick])
                r = np.corrcoef(X.T)[0, 1]
                if r > 0: Ms.append(k * (1 - r) / r)
            g.append(np.median(Ms))
        out['stab'][n]['g50_90'] = [round(float(np.percentile(g, 5)), 1), round(float(np.percentile(g, 95)), 1)]
        out['stab'][n]['g50x'] = round(float(np.median([k * (1 - out['byK'][k][n]) / out['byK'][k][n] for k in KS if k >= 10])), 1)
    # year to year, season box XPM (500+ MP both)
    yy = []
    for S in SEASONS:
        if S + 1 not in SEASONS: continue
        L = [I.season_lines(s) for s in (S, S + 1)]
        b0, b1 = I.coef(S), I.coef(S + 1); l0, l1 = I.league(L[0]), I.league(L[1])
        for pid, v in L[0].items():
            w = L[1].get(pid)
            if w is not None and v[0] >= 500 and w[0] >= 500: yy.append((I.box_xpm(v, b0, l0), I.box_xpm(w, b1, l1)))
    out['y2y_box_xpm'] = {'r': round(float(np.corrcoef(np.array(yy).T)[0, 1]), 3), 'n': len(yy)}
    json.dump(out, open(os.path.join(HERE, '..', 'data', 'nba_xpm_stability_research.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
