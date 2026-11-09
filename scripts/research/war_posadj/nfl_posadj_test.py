#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL WAR positional adjustment test (Nov 3 2026, Noah: both WAR boards are topped by mid QBs).

The board's WAR at a sub-position s for a player with share sh:  b = value[s] x sh + (b - value[s] x sh)
                                                                     level (positional)   spread (over an average regular)
A positional adjustment can move either part. This scores variants on held-out tests:
  level   L_s scales value[s] (the other spots rescaled so a team's level total is unchanged, team WAR = wins - 3)
  spread  M_s scales the part over an average regular

Tests (board value = .4 XV + .6 AV WAR, XV on weights fit with the season left out):
  missedPrior  game margin on team-season ratings + home field + each side's absent regulars, valued at LAST season's
               pace (points a game), no sub-position dummies: one slope for every position, then the residual drop per
               absence by group (0 = the positional level is right). Last season's value, so not read off the same games.
  missedQB     same games, sub dummies in, QB's value over an average QB alone: slope 1 = the spread is right
  forward      next season's team margin a game from returning players' value at their new team (leave one pair out)
  market       rank corr of the season's value with the next veteran contract's cap % (30%+ snaps), and the QB rank bias
  ranks        top 25 / top 50 counts of QBs in the 2025 season, and how many below-average QBs sit in the top 25

    python3 scripts/nfl_xv.py --prep        # caches 2018-25
    python3 scripts/research/war_posadj/nfl_posadj_test.py   # -> scripts/research/war_posadj/nfl_posadj_results.json
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np   # noqa: E402
import nfl_war as W   # noqa: E402
import nfl_xv as X   # noqa: E402

PTS = 35.5
OUT = os.path.join(HERE, 'nfl_posadj_results.json')


def base():
    S = X.load(); X.zscore(S)
    _, value, _ = W.sub_lines()
    with open(X.OUT) as f:
        model = json.load(f)['model']
    lam, alpha = model['lambda'], model['alpha']
    ys = sorted(S)
    for y in ys:
        w = X.fit_w(S, [v for v in ys if v != y], lam)
        xv = X.xv_of(S, y, w, value)
        for p, a in zip(S[y]['players'], xv):
            p['b'] = alpha * a + (1 - alpha) * p['war']
    return S, value, ys


def variant(S, value, L=None, M=None):
    """{y: [value per player row]} with levels x L[s] (rescaled to the same team total) and spreads x M[s]"""
    L, M = L or {}, M or {}
    # rescale levels so the mean team's level total holds: sum over rows of sh x value
    tot0 = defaultdict(float); tot1 = defaultdict(float)
    for d in S.values():
        for p in d['players']:
            tot0[p['sub']] += p['sh'] * value[p['sub']]
    t0 = sum(tot0.values()); fixed = sum(tot0[s] * L[s] for s in L)
    c = (t0 - fixed) / (t0 - sum(tot0[s] for s in L)) if L else 1.0
    v1 = {s: value[s] * (L[s] if s in L else c) for s in value}
    out = {}
    for y, d in S.items():
        out[y] = [p['sh'] * v1[p['sub']] + M.get(p['sub'], 1.0) * (p['b'] - p['sh'] * value[p['sub']]) for p in d['players']]
    return out, v1


GROUPS = {'QB': ['QB'], 'RB': ['RB'], 'WR': ['WR', 'SWR'], 'TE': ['TE'], 'OL': ['OT', 'IOL'], 'DL': ['EDGE', 'DT'], 'LB': ['LB'], 'DB': ['CB', 'NCB', 'S']}
GOF = {s: g for g, ss in GROUPS.items() for s in ss}


def missed(S, vals, ys, v1, mode):
    """mode 'level': one slope on absent regulars' last-season pace (pts a game), group dummies for the residual
    (pace missing: the sub-position's level a game). mode 'qb': sub dummies + QB pace over the average QB."""
    eqs, fe = [], {}
    gl = list(GROUPS)
    for y in ys:
        if y - 1 not in S:
            continue
        prev = defaultdict(lambda: [0.0, 0])
        for i, p in enumerate(S[y - 1]['players']):
            a = prev[p['pfr']]; a[0] += vals[y - 1][i]; a[1] += p['games'] if isinstance(p['games'], (int, float)) else len(p['games'])
        P = S[y]['players']
        regs = defaultdict(list)
        for i, p in enumerate(P):
            if 'reg' in p:
                regs[p['t']].append(i)
        for g in S[y]['sched']:
            x = np.zeros(1 + len(gl) + len(W.SUBS))
            for t, sgn in ((g['h'], 1), (g['a'], -1)):
                gi = S[y]['tg'][t].index(g['id'])
                for i in regs.get(t, []):
                    r = P[i]['reg']
                    if r['start'] <= gi < r['end'] and gi not in r['played']:
                        s = P[i]['sub']; pv = prev.get(P[i]['pfr'])
                        lvl = v1[s] / 17 * PTS * r['gsh']
                        pace = pv[0] / pv[1] * PTS if pv and pv[1] >= 4 else lvl
                        if mode == 'level':
                            x[0] += sgn * pace; x[1 + gl.index(GOF[s])] += sgn
                        else:
                            x[1 + len(gl) + W.SUBS.index(s)] += sgn
                            if s == 'QB':
                                x[0] += sgn * (pace - lvl)
            eqs.append((fe.setdefault((y, g['h']), len(fe)), fe.setdefault((y, g['a']), len(fe)), 0 if g['neutral'] else 1, x,
                        max(-35.0, min(35.0, g['hs'] - g['as']))))
    nf = len(fe); ne = len(eqs[0][3])
    A = np.zeros((len(eqs), nf + 1 + ne)); Y = np.zeros(len(eqs))
    for i, (h, a_, hfa, x, m) in enumerate(eqs):
        A[i, h] = 1; A[i, a_] = -1; A[i, nf] = hfa; A[i, nf + 1:] = x; Y[i] = m
    keep = np.abs(A).sum(0) > 0
    reg = np.zeros(A.shape[1]); reg[:nf] = 2
    A, reg = A[:, keep], reg[keep]
    idx = np.cumsum(keep) - 1
    M = A.T @ A + np.diag(reg); cf = np.linalg.solve(M, A.T @ Y); res = Y - A @ cf
    cov = (res @ res / (len(Y) - A.shape[1])) * np.linalg.inv(M)
    j = idx[nf + 1]
    out = {'games': len(eqs), 'slope': round(float(-cf[j]), 3), 'se': round(float(math.sqrt(cov[j, j])), 3)}
    if mode == 'level':
        out['residualDrop'] = {}
        for k, gname in enumerate(gl):
            c = nf + 2 + k
            if keep[c]:
                out['residualDrop'][gname] = [round(float(-cf[idx[c]]), 2), round(float(math.sqrt(cov[idx[c], idx[c]])), 2)]
    return out


def ranks(S, vals, y, value):
    """value: the variant's levels (v1), so below-average reads against the variant's own average QB"""
    agg = {}
    for i, p in enumerate(S[y]['players']):
        a = agg.setdefault(p['pfr'], {'n': p['n'], 'sub': p['sub'], 'v': 0.0, 'avg': 0.0})
        a['v'] += vals[y][i]; a['avg'] += S[y]['players'][i]['sh'] * value[p['sub']]
    P = sorted(agg.values(), key=lambda a: -a['v'])
    qb = [a for a in P if a['sub'] == 'QB']
    return {'qbTop25': sum(a['sub'] == 'QB' for a in P[:25]), 'qbTop50': sum(a['sub'] == 'QB' for a in P[:50]),
            'belowAvgQbTop25': sum(a['sub'] == 'QB' and a['v'] < a['avg'] for a in P[:25]),
            'top10': [f"{a['n']} {a['sub']} {a['v']:.2f}" for a in P[:10]]}


def score(S, value, ys, L=None, M=None, years=None):
    vals, v1 = variant(S, value, L, M)
    yy = years or ys
    sub = {y: S[y] for y in ys}
    f = X.forward_test({y: S[y] for y in yy}, {'v': {y: vals[y] for y in yy}})['v']['alone']['r2']
    fl = X.forward_test({y: S[y] for y in yy}, {'v': {y: vals[y] for y in yy}})['v']['withLast']['r2']
    mk = X.market_test({y: S[y] for y in yy}, {'v': {y: vals[y] for y in yy}})['v']
    return {'missedPrior': missed(sub, vals, yy, v1, 'level'), 'missedQB': missed(sub, vals, yy, v1, 'qb'),
            'forwardR2': f, 'forwardWithLastR2': fl, 'marketRankR': mk, 'ranks2025': ranks(S, vals, 2025, v1), 'qbLevel': round(v1['QB'], 3)}


if __name__ == '__main__':
    S, value, ys = base()
    res = {}
    grid = [('now', None, None)]
    for m in (1.5, 2, 2.5, 3):
        grid.append((f'qbSpread{m}', None, {'QB': m}))
    for l in (0.6, 0.8):
        grid.append((f'qbLevel{l}', {'QB': l}, None))
        grid.append((f'qbLevel{l}Spread2', {'QB': l}, {'QB': 2}))
    for name, L, M in grid:
        res[name] = {'all': score(S, value, ys, L, M), 'early': score(S, value, ys, L, M, [y for y in ys if y <= 2021]),
                     'late': score(S, value, ys, L, M, [y for y in ys if y >= 2022])}
        r = res[name]['all']
        print(name, 'lvl', r['qbLevel'], 'missed slope', r['missedPrior']['slope'], 'QBresid', r['missedPrior']['residualDrop'].get('QB'),
              'qbSlope', r['missedQB']['slope'], r['missedQB']['se'], 'fwd', r['forwardR2'], r['forwardWithLastR2'], 'mkt', r['marketRankR'],
              'qb25', r['ranks2025']['qbTop25'], 'below', r['ranks2025']['belowAvgQbTop25'], flush=True)
    with open(OUT, 'w') as f:
        f.write(json.dumps(res, indent=1).replace('NaN', 'null'))
        f.write('\n')
