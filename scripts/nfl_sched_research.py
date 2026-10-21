#!/usr/bin/env python3
"""Kickoff time in the NFL game model: primetime, the late Sunday window, the body clock in primetime, international
morning kickoffs, on margins and totals.

    python3 scripts/nfl_sched_research.py      # writes data/nfl_sched_research.json (numpy; ~1 min with a warm cache)

The fit's walk-forward (scripts/nfl_games.py fit): every season 2015-25 scored by weights fit on the seasons before,
with the shipped settings and inputs; 2015-20 tunes, 2021-25 is held out. A candidate is kept only if it cuts
2015-20 error at paired per-game t <= -1.5 and 2021-25 does not get worse. Each candidate's plain effect (points,
full-sample t) and the same input against the closing line (result minus close) are reported too.
Earlier failures not redone: travel, time zones, the 1 PM body clock for west visitors, short week, bye
(data/nfl_games_research.json).
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N
from nfl_games_research import CITY

OUT = os.path.join(N.ROOT, 'data', 'nfl_sched_research.json')


def kick(g):
    t = g['gametime'] or '13:00'
    return int(t[:2]) + int(t[3:5]) / 60


def sched(g):
    h, a = N.team(g['home_team']), N.team(g['away_team'])
    H, A = CITY.get(h), CITY.get(a)
    k = kick(g)
    neutral = g['location'] == 'Neutral'
    home = 0.0 if neutral else 1.0
    prime = 1.0 if k >= 19 else 0.0
    late = 1.0 if 16 <= k < 19 else 0.0
    west = (A[2] - H[2]) if (H and A and not neutral) else 0.0     # hours the visitor's clock runs behind the home's
    x = {'prime': home * prime, 'late': home * late, 'primeBody': prime * west, 'lateBody': late * west,
         'primeDiv': home * prime * (1.0 if g.get('div_game') == '1' else 0.0)}
    tx = {'tprime': prime, 'tlate': late, 'tintl': 1.0 if k < 12 else 0.0,
          'tmnf': 1.0 if g['weekday'] == 'Monday' else 0.0, 'ttnf': 1.0 if g['weekday'] == 'Thursday' else 0.0}
    return x, tx


def coef(Xm, y, names):
    b = np.linalg.lstsq(Xm, y, rcond=None)[0]
    r = y - Xm @ b
    cov = (r @ r / (len(y) - len(b))) * np.linalg.inv(Xm.T @ Xm)
    return {f: {'pts': round(float(v), 3), 't': round(float(v / math.sqrt(cov[i, i])), 2)} for i, (f, v) in enumerate(zip(names, b))}


def main():
    last = 2025
    F = json.load(open(N.FIT))
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, F['params'])
    D = []
    for g, x, tx in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        sx, stx = sched(g)
        D.append((g, {**x, **sx}, {**tx, **stx}))
    S = np.array([int(g['season']) for g, _, _ in D])
    y = np.array([N.num(g['result']) for g, _, _ in D]); ty = np.array([N.num(g['total']) for g, _, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _, _ in D]); tline = np.array([N.num(g['total_line'], np.nan) for g, _, _ in D])
    A = (S >= 2015) & (S <= 2020); B = S >= 2021

    def wf(feats, tot=False):
        X = np.array([[(tx if tot else x)[f] for f in feats] for _, x, tx in D]); yy = ty if tot else y
        pred = np.full(len(yy), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            pred[te] = X[te] @ np.linalg.lstsq(X[tr], yy[tr], rcond=None)[0]
        return pred, X

    def cmp(p1, p0, yy):
        out = {}
        for lab, k in (('2015_20', A), ('2021_25', B)):
            d = np.abs(p1[k] - yy[k]) - np.abs(p0[k] - yy[k])
            out['mae' + lab] = round(float(np.abs(p1[k] - yy[k]).mean()), 4)
            out['d' + lab] = round(float(d.mean()), 4)
            out['t' + lab] = round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)
        out['passes'] = bool(out['t2015_20'] <= -1.5 and out['d2021_25'] <= 0)
        return out

    res = {}
    base, tbase = list(N.FEATS), list(N.TFEATS)
    p0, _ = wf(base)
    t0, _ = wf(tbase, True)
    res['base'] = {'feats': base, 'tfeats': tbase, 'mae2015_20': round(float(np.abs(p0[A] - y[A]).mean()), 4),
                   'mae2021_25': round(float(np.abs(p0[B] - y[B]).mean()), 4),
                   'tmae2015_20': round(float(np.abs(t0[A] - ty[A]).mean()), 4), 'tmae2021_25': round(float(np.abs(t0[B] - ty[B]).mean()), 4)}
    ok = ~np.isnan(line); okt = ~np.isnan(tline)
    M = {}
    for c in ('prime', 'late', 'primeBody', 'lateBody', 'primeDiv'):
        p1, X = wf(base + [c])
        M[c] = cmp(p1, p0, y)
        M[c]['games'] = int((X[:, -1] != 0).sum())
        M[c]['effect'] = coef(X[S >= 2015], y[S >= 2015], base + [c])[c]
        Z = np.column_stack([np.ones(ok.sum()), X[ok, -1]])
        M[c]['vsClose'] = coef(Z, (y - line)[ok], ['one', c])[c]
        print(c, M[c], flush=True)
    res['margin'] = M
    T = {}
    for c in ('tprime', 'tlate', 'tintl', 'tmnf', 'ttnf'):
        p1, X = wf(tbase + [c], True)
        T[c] = cmp(p1, t0, ty)
        T[c]['games'] = int((X[:, -1] != 0).sum())
        T[c]['effect'] = coef(X[S >= 2015], ty[S >= 2015], tbase + [c])[c]
        Z = np.column_stack([np.ones(okt.sum()), X[okt, -1]])
        T[c]['vsClose'] = coef(Z, (ty - tline)[okt], ['one', c])[c]
        print(c, T[c], flush=True)
    res['totals'] = T
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
