#!/usr/bin/env python3
"""Offseason roster prior for the NFL game model: does the opening rating need the roster (Oct 21 2026)?

    python3 scripts/nfl_offseason_research.py     # numpy; writes data/nfl_offseason_research.json

The live model (scripts/nfl_games.py) opens each season from last season's team: Elo regressed a third to the mean,
the EPA ratings carried at .7, the market rating at .4. The QB term already reads a new starter from week 1 (his
own EPA line against the team's recent QB play). Nothing else about the roster moves the opening rating: free agents,
trades, cuts and the draft class only show up once games are played.

This tests a roster prior on top of the live model, by the project's bar: tune on 2015-20 walk-forward, keep at
paired t <= -1.5 on the games it targets (weeks 1-4 and the full season), not worse on 2021-25.

Each player's WAR for the new season is projected from his last two seasons (AV WAR, nfl_war.war_ledger), his age
and, for players two seasons in or less, his draft slot; rookies from draft slot alone. Fit each season on the seasons
before it (player level, least squares). Then for each team, at its week-1 roster (nflverse weekly rosters, active):

    moves   projected WAR of the week-1 roster minus the projected WAR of last season's players (each at his share of
            last season's games with the team): what free agency, trades, cuts and the draft changed
    rook    projected WAR of the rookies on the week-1 roster (the draft class alone)
    aging   projected WAR of last season's players minus the WAR they posted: the kept roster's expected regression
            and aging, team by team (the live model regresses every team the same third)
    total   moves + aging: the roster's projection against last season's WAR

Each enters home minus away, times 0.5 ** (games the team has played this season / half-life), so the prior fades
as the ratings learn the new team. QBs are left out of the roster sums by default (the QB term has them); a variant
keeps them. Points: WAR x 36 / 17 (a win is 36 points of season margin) so coefficients read as shares.

Results (Oct 21 2026). Refit as an input, every variant is worse on 2015-20 (the roster history starts in 2014, so the
early folds fit the weight on one or two seasons). At fixed shares picked on 2015-20, offseason moves at .25 with a
half-life of 8 games clear the bar: all games 2015-20 -0.012 MAE (t -1.58), 2021-25 -0.009 (t -1.33), better in 8 of 11
seasons; weeks 1-4 -0.015 / -0.003 (t -0.7 / -0.1). Shipped (scripts/nfl_roster.py). Rookies alone, aging, the
total against last season, QBs in the sums and the QB term weighted up early all fail. Season check: moves vs the
season's mean residual r .12 (2015-20), .09 (2021-25).
Aging in the player projection: one pooled curve beats none on 2015-20 (t -2.3) and 2021-25 (t -1.9); a curve per
position group ties on 2015-20 (t -0.8) and is better on 2021-25 (t -4.0), so pooled ships. Rookies come from draft
slot: college FV can't be tested on this bar (past grades exist for the 2020-23 classes only, none in 2015-20).
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N   # noqa: E402
import nfl_war as W     # noqa: E402, F401
from nfl_roster import (team_ledger, rosters, pfeat, age, pick, GROUPS, RPOS, team_moves, ROSTER,  # noqa: E402
                        FIT as ROSTER_FIT)

OUT = os.path.join(N.ROOT, 'data', 'nfl_offseason_research.json')
FIRST = 2013           # snap counts (and so WAR) start here


def main():
    import numpy as np
    last = 2025
    L = {y: team_ledger(y) for y in range(FIRST, last + 1)}
    for y in L:
        print('ledger', y, len(L[y]), flush=True)
    R = {y: rosters(y) for y in range(FIRST, last + 1)}
    pw = {y: defaultdict(float) for y in L}        # gsis -> WAR (all teams)
    pos = {}
    for y, led in L.items():
        for (g, t), v in led.items():
            pw[y][g] += v[0]; pos[g] = v[2]

    # player rows for the projection: every player on a week-1 roster in y, with his y-1 and y-2 WAR
    def rowsfor(y, aging):
        X, ids, Y, tms = [], [], [], []
        for t, ros in R[y].items():
            for g, r in ros.items():
                ry = int(r['rookie_year']) if r.get('rookie_year', '').isdigit() else (int(r['entry_year']) if r.get('entry_year', '').isdigit() else y)
                rk = 1.0 if ry >= y else 0.0
                w1 = pw.get(y - 1, {}).get(g, 0.0); w2 = pw.get(y - 2, {}).get(g, 0.0)
                has2 = 1.0 if (y - 2) in pw else 0.0
                grp = pos.get(g) or RPOS.get(r['position'], 'DB')
                X.append(pfeat(w1, w2, has2, age(r, y), rk, y - ry, pick(r), grp, aging))
                ids.append(g); tms.append(t); Y.append(pw[y].get(g, 0.0))
        return np.array(X), ids, np.array(Y), tms

    def project(aging, lam_=5.0):
        PR = {y: rowsfor(y, aging) for y in range(FIRST + 1, last + 1)}
        proj, pfit, err = {}, {}, {}
        for y in range(FIRST + 1, last + 1):
            tr = [PR[k] for k in PR if k < y]
            X, ids, Y, _ = PR[y]
            if not tr:
                b = np.zeros(X.shape[1]); b[1] = 0.5
            else:
                Xt = np.vstack([t[0] for t in tr]); Yt = np.concatenate([t[2] for t in tr])
                lam = np.eye(Xt.shape[1]) * lam_; lam[0, 0] = 0
                b = np.linalg.solve(Xt.T @ Xt + lam, Xt.T @ Yt)
            pfit[y] = b
            p = X @ b
            proj[y] = dict(zip(ids, p))
            err[y] = (p - Y) ** 2
        return PR, proj, pfit, err

    variants = {a: project(a) for a in ('none', 'pooled', 'pos')}
    pacc = {}
    for a, (PR, proj, _, err) in variants.items():
        for lab, ys in (('1520', range(2015, 2021)), ('2125', range(2021, last + 1))):
            e = np.concatenate([err[y] for y in ys])
            base_e = np.concatenate([variants['none'][3][y] for y in ys])
            d = e - base_e
            pacc[f'{a}/{lab}'] = {'rmse': round(float(np.sqrt(e.mean())), 4), 'vsNone': round(float(d.mean()), 5),
                                  't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2) if a != 'none' else 0.0,
                                  'r': round(float(np.corrcoef(np.concatenate([variants[a][0][y][0] @ variants[a][2][y] for y in ys]),
                                                               np.concatenate([variants[a][0][y][2] for y in ys]))[0, 1]), 3)}
    print('projection', pacc, flush=True)
    # the aging choice is made on 2015-20 alone
    AGING = min(('none', 'pooled', 'pos'), key=lambda a: pacc[f'{a}/1520']['rmse'])
    PR, proj, pfit, _ = variants[AGING]
    curves = {}
    if AGING == 'pos' or True:
        b = variants['pos'][2][last]
        for i, G in enumerate(GROUPS):
            o = 9 + 5 * i
            curves[G] = {str(a): round(float(b[o + 1] * max(0, a - 27) + b[o + 2] * max(0, a - 27) ** 2 + b[o + 3] * max(0, 27 - a)
                                             + b[o + 4] * 1.0 * max(0, a - 27)), 3) for a in (23, 25, 27, 29, 31, 33, 35)}
    print('aging', AGING, curves, flush=True)
    coefs = [round(float(v), 3) for v in pfit[last]]

    # team quantities, with and without QBs
    TQ = {}
    for y in range(FIRST + 1, last + 1):
        for qbs_in in (False, True):
            TQ[(y, qbs_in)] = team_moves(y, L.get(y - 1, {}), R[y], proj[y], pw.get(y - 1, {}), pos, qbs_in)
    # the live projection: fit on every season through the last
    Xa = np.vstack([PR[k][0] for k in PR]); Ya = np.concatenate([PR[k][2] for k in PR])
    lam = np.eye(Xa.shape[1]) * 5.0; lam[0, 0] = 0
    blive = np.linalg.solve(Xa.T @ Xa + lam, Xa.T @ Ya)
    # live model walk
    F = json.load(open(N.FIT)); params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, params)
    gp = defaultdict(int)
    D = []
    for g, x, _ in data:
        s = int(g['season']); h, a = N.team(g['home_team']), N.team(g['away_team'])
        before = (gp[(s, h)], gp[(s, a)])
        if g['home_score'] not in ('', 'NA'):
            gp[(s, h)] += 1; gp[(s, a)] += 1
        if g['home_score'] in ('', 'NA') or s < 2012:
            continue
        x = dict(x)
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D.append((g, x, before))
    S = np.array([int(g['season']) for g, _, _ in D]); WK = np.array([int(g['week']) for g, _, _ in D])
    y = np.array([N.num(g['result']) for g, _, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _, _ in D]); ok = ~np.isnan(line)
    base = list(N.FEATS)
    XB = np.array([[x[f] for f in base] for _, x, _ in D])

    def feat(kind, hl, qbs_in):
        v = np.zeros(len(D))
        for i, (g, x, (nh, na)) in enumerate(D):
            s = int(g['season'])
            T = TQ.get((s, qbs_in))
            if not T:
                continue
            h, a = N.team(g['home_team']), N.team(g['away_team'])
            fh = 0.5 ** (nh / hl) if hl else 1.0; fa = 0.5 ** (na / hl) if hl else 1.0
            if g['game_type'] != 'REG':
                fh = fa = (0.5 ** (17 / hl) if hl else 1.0)
            v[i] = (fh * T.get(h, {}).get(kind, 0.0) - fa * T.get(a, {}).get(kind, 0.0)) * N.PTS_PER_WIN / 17
        return v

    def wf(X, first=2015):
        pred = np.full(len(y), np.nan)
        for s in range(first, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        b = np.linalg.lstsq(X[S >= 2012], y[S >= 2012], rcond=None)[0]
        return np.abs(pred - y), pred, b

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return [round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2), int(k.sum())]

    e0, p0, _ = wf(XB)
    A = (S >= 2015) & (S <= 2020) & ok; B = (S >= 2021) & ok
    early = WK <= 4
    blocks = {'all1520': A, 'all2125': B, 'wk1_4_1520': A & early, 'wk1_4_2125': B & early, 'wk1_1520': A & (WK == 1), 'wk1_2125': B & (WK == 1)}
    res = {'base': {k: round(float(e0[m].mean()), 3) for k, m in blocks.items()},
           'line': {k: round(float(np.abs(line[m] - y[m]).mean()), 3) for k, m in blocks.items()},
           'projection': {'acc': pacc, 'aging': AGING, 'posCurves (WAR vs 27, at 1 WAR last season)': curves, 'coef2025': coefs}}
    print('base', res['base'], 'line', res['line'], flush=True)
    cand = {}
    for kind in ('moves', 'rook', 'aging', 'total'):
        for qbs_in in (False, True):
            for hl in (1, 2, 4, 8, 0):
                f = feat(kind, hl, qbs_in)
                e1, p1, b = wf(np.column_stack([XB, f]))
                key = f'{kind}{"+QB" if qbs_in else ""}/hl{hl or "flat"}'
                cand[key] = {'coef': round(float(b[-1]), 3), **{k: cmp(e1, e0, m) for k, m in blocks.items()}}
                print(key, cand[key], flush=True)
    # the pieces together (moves and aging as two inputs), each half-life
    for hl in (2, 4, 8):
        for qbs_in in (False, True):
            f1, f2 = feat('moves', hl, qbs_in), feat('aging', hl, qbs_in)
            e1, _, b = wf(np.column_stack([XB, f1, f2]))
            key = f'moves+aging{"+QB" if qbs_in else ""}/hl{hl}'
            cand[key] = {'coef': [round(float(b[-2]), 3), round(float(b[-1]), 3)], **{k: cmp(e1, e0, m) for k, m in blocks.items()}}
            print(key, cand[key], flush=True)
    # the QB term weighted more while the ratings haven't seen the new team (a QB change early in the season)
    for hl in (2, 4):
        f = np.array([x['qb'] * (0.5 ** (((nh + na) / 2) / hl)) for _, x, (nh, na) in D])
        e1, _, b = wf(np.column_stack([XB, f]))
        cand[f'qbEarly/hl{hl}'] = {'coef': round(float(b[-1]), 3), **{k: cmp(e1, e0, m) for k, m in blocks.items()}}
        print(f'qbEarly/hl{hl}', cand[f'qbEarly/hl{hl}'], flush=True)
    res['cand'] = cand
    # fixed shares (no refit): the base walk-forward plus c x the prior, so a thin training history (the roster
    # inputs start in 2014) can't decide the weight; c picked on 2015-20
    fixed = {}
    for kind in ('moves', 'total', 'rook'):
        for qbs_in in (False, True):
            for hl in (2, 4, 8):
                f = feat(kind, hl, qbs_in)
                for c in ((0.1, 0.15, 0.2, 0.25, 0.3, 0.5, 1.0) if kind == 'moves' and not qbs_in else (0.25, 0.5, 1.0)):
                    e1 = np.abs(p0 + c * f - y)
                    key = f'{kind}{"+QB" if qbs_in else ""}/hl{hl}/c{c}'
                    fixed[key] = {k: cmp(e1, e0, m) for k, m in blocks.items()}
                sdv = float(np.std(f[(S >= 2015) & (WK == 1)]))
                fixed[f'{kind}{"+QB" if qbs_in else ""}/hl{hl}/sdWeek1'] = round(sdv, 3)
    res['fixed'] = fixed
    f = feat('moves', ROSTER['hl'], False)
    e1 = np.abs(p0 + ROSTER['c'] * f - y)
    res['shipped'] = {'cell': f"moves/hl{ROSTER['hl']:g}/c{ROSTER['c']}", **{k: cmp(e1, e0, m) for k, m in blocks.items()},
                      'bySeason': {int(s_): round(float((e1 - e0)[(S == s_) & ok].mean()), 4) for s_ in range(2015, last + 1)}}
    print('shipped', res['shipped'], flush=True)
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'method': 'scripts/nfl_offseason_research.py',
               'aging': AGING, 'inputs': ['one', 'war1', 'war2', 'has2', 'rookie', 'rookie x log pick', 'year 1-2',
                                          'year 1-2 x log pick', 'undrafted', 'years past 29', 'years under 25'],
               'coef': [round(float(v), 5) for v in blive], **ROSTER, 'test': res['shipped']}, open(ROSTER_FIT, 'w'), indent=1)
    for k, v in fixed.items():
        print('fixed', k, v, flush=True)
    # team-season check: does the roster change predict the season's margin over what the opening ratings said?
    open_ = {}
    for i, (g, x, (nh, na)) in enumerate(D):
        s = int(g['season'])
        if g['game_type'] != 'REG':
            continue
        for t, sign in ((N.team(g['home_team']), 1), (N.team(g['away_team']), -1)):
            o = open_.setdefault((s, t), [0.0, 0.0, 0])
            o[0] += sign * (y[i] - (p0[i] if not np.isnan(p0[i]) else 0)); o[2] += 1
    seas = {}
    for qbs_in in (False, True):
        for kind in ('moves', 'aging', 'total', 'rook'):
            xs, ys, ss = [], [], []
            for (s, t), o in open_.items():
                T = TQ.get((s, qbs_in))
                if T and t in T and s >= 2015:
                    xs.append(T[t][kind]); ys.append(o[0] / o[2]); ss.append(s)
            xs, ys, ss = np.array(xs), np.array(ys), np.array(ss)
            out = {}
            for lab, k in (('1520', (ss <= 2020)), ('2125', ss >= 2021)):
                r = float(np.corrcoef(xs[k], ys[k])[0, 1])
                out[lab] = {'r': round(r, 3), 't': round(r * math.sqrt((k.sum() - 2) / (1 - r * r)), 2), 'n': int(k.sum())}
            seas[f'{kind}{"+QB" if qbs_in else ""}'] = out
    res['seasonResidual'] = seas
    print('season residual', seas, flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
