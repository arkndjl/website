#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL WAR staple audit (Nov 3 2026): the .6 AV WAR / .4 XV blend and the .091 wins-per-AV scale, out of sample.

    python3 scripts/nfl_xv.py --prep          # once: scripts/.cache/nfl/xv_<y>.json (2018-25)
    python3 scripts/nfl_war_research_nov03.py # -> data/nfl_war_research_nov03.json

Pre-registered (written before any run):
  N1  XV weight alpha on NEXT-season team margin: team value = sum over season-y players of last season's value rate
      (value / (share + .2), shrunk to replacement) x his actual season-y share; XV weights fit with y-1 and y left out.
      margin a game = c0 + c1 x value, c fit leaving the target season out. alpha* picked on the other target seasons'
      SSE (nested), against alpha .4: paired t over target seasons 2019-25 on team SSE.
  N2  XV weight alpha on missed games with LAST season's values (the same-season test is circular for AV, whose team
      pool includes the games a player missed): absent regulars' value a game = rate(y-1) x his snap share when he
      plays / 17 x 35.5 points; no prior season = his sub-position's mean. Game margin ~ team-season effects + home +
      absent counts by sub-position + value. Score: per-season SSE drop over the counts-only model; nested alpha* vs .4.
  N3  wins per AV (.091): leave-one-season-out wins RMSE (2019-25 team seasons, wins = a + k x team AV), k fit on the
      other seasons against k fixed at .091 (a refit both ways); paired t over seasons.
Pass: Holm over the three at .05 (two-sided t on 6 df per-season differences), the new value ahead in most seasons.
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np   # noqa: E402
import nfl_war as W  # noqa: E402
import nfl_xv as X   # noqa: E402

OUT = os.path.join(W.ROOT, 'data', 'nfl_war_research_nov03.json')
ALPHAS = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
BASE = 0.4
SHRINK = 0.2


def tstat(d):
    d = np.asarray(d, float)
    if len(d) < 2 or d.std(ddof=1) == 0:
        return None
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


def pval(t, df):
    """two-sided p for a t on df degrees of freedom (Student t CDF by the regularized incomplete beta)"""
    if t is None:
        return None
    x = df / (df + t * t)
    # continued fraction for I_x(a, b)
    a, b = df / 2, 0.5

    def betacf(a, b, x):
        qab, qap, qam = a + b, a + 1, a - 1
        c, d = 1.0, 1 - qab * x / qap
        d = 1 / (d if abs(d) > 1e-30 else 1e-30); h = d
        for m in range(1, 300):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30); c = 1 + aa / c; h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30); c = 1 + aa / c; de = d * c; h *= de
            if abs(de - 1) < 1e-12:
                break
        return h
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    I = bt * betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * betacf(b, a, 1 - x) / b
    return float(I)


def main():
    S = X.load(); X.zscore(S)
    ys = sorted(S)
    _, value, _ = W.sub_lines()
    targets = [y for y in ys if y - 1 in S]
    # last season's value rates by player for each target season, by alpha: {y: {alpha: {pfr: rate}}}
    rates = {}
    for y in targets:
        w = X.fit_w(S, [v for v in ys if v not in (y - 1, y)], 20)
        wd = {f'{g}.{part}': float(v) for (g, part), v in zip(X.COLS, w)}
        qm = X.q_means({k: S[k] for k in S if k != y}, wd)
        xv = X.xv_of(S, y - 1, wd, value, qm)
        V, SH = defaultdict(lambda: [0.0, 0.0]), defaultdict(float)
        for p, xvv in zip(S[y - 1]['players'], xv):
            V[p['pfr']][0] += xvv; V[p['pfr']][1] += p['war']; SH[p['pfr']] += p['sh']
        rates[y] = {a: {k: (a * v[0] + (1 - a) * v[1]) / (SH[k] + SHRINK) for k, v in V.items()} for a in ALPHAS}
    res = {'pre': 'N1 forward team margin, N2 missed games on last-season values, N3 wins per AV; Holm at .05', 'alphas': ALPHAS}

    # ---- N1: next-season team margin
    rowsN1 = {a: [] for a in ALPHAS}
    for y in targets:
        T = {a: defaultdict(float) for a in ALPHAS}
        for p in S[y]['players']:
            for a in ALPHAS:
                T[a][p['t']] += rates[y][a].get(p['pfr'], 0.0) * p['sh']
        for t, tm in S[y]['teams'].items():
            for a in ALPHAS:
                rowsN1[a].append((y, T[a][t], (tm['pf'] - tm['pa']) / tm['g']))
    sse = {a: {} for a in ALPHAS}
    for a in ALPHAS:
        R = rowsN1[a]
        for y in targets:
            tr = np.array([[1, r[1]] for r in R if r[0] != y]); yt = np.array([r[2] for r in R if r[0] != y])
            cf = np.linalg.lstsq(tr, yt, rcond=None)[0]
            te = [(r[2] - cf[0] - cf[1] * r[1]) ** 2 for r in R if r[0] == y]
            sse[a][y] = float(sum(te))
    tot = np.array([r[2] for r in rowsN1[0]]); var = float(tot.var())
    n1 = {'teams': len(tot), 'r2': {str(a): round(1 - sum(sse[a].values()) / len(tot) / var, 4) for a in ALPHAS}}
    pick, d = {}, []
    for y in targets:
        a_ = min(ALPHAS, key=lambda a: sum(v for k, v in sse[a].items() if k != y))
        pick[y] = a_; d.append(sse[BASE][y] - sse[a_][y])
    n1.update({'nestedPick': pick, 'dSseNestedVsBase': [round(x, 2) for x in d], 't': tstat(d), 'better': sum(x > 0 for x in d), 'seasons': len(d)})
    # each alpha against .4 per season (descriptive)
    n1['vsBase'] = {str(a): {'t': None if a == BASE else round(tstat([sse[BASE][y] - sse[a][y] for y in targets]) or 0, 2),
                             'better': sum(sse[BASE][y] > sse[a][y] for y in targets)} for a in ALPHAS}
    res['N1'] = n1

    # ---- N2: missed games, last season's values
    SUBS = W.SUBS
    eqs, fe = [], {}
    for y in targets:
        d_ = S[y]; P = d_['players']
        regs = defaultdict(list)
        for i, p in enumerate(P):
            if 'reg' in p:
                regs[p['t']].append(i)
        val = {a: {} for a in ALPHAS}
        for a in ALPHAS:
            acc = defaultdict(list)
            for L in regs.values():
                for i in L:
                    r = rates[y][a].get(P[i]['pfr'])
                    if r is not None:
                        v = r * P[i]['reg']['gsh'] / 17 * X.PTS_PER_WIN
                        val[a][i] = v; acc[P[i]['sub']].append(v)
            mu = {s: sum(v) / len(v) for s, v in acc.items()}
            val[a] = {i: v - mu[P[i]['sub']] for i, v in val[a].items()}
        for g in d_['sched']:
            x = np.zeros(len(SUBS) + len(ALPHAS))
            for t, sgn in ((g['h'], 1), (g['a'], -1)):
                gi = d_['tg'][t].index(g['id'])
                for i in regs.get(t, []):
                    r = P[i]['reg']
                    if r['start'] <= gi < r['end'] and gi not in r['played']:
                        x[SUBS.index(P[i]['sub'])] += sgn
                        for j, a in enumerate(ALPHAS):
                            x[len(SUBS) + j] += sgn * val[a].get(i, 0.0)
            eqs.append((y, fe.setdefault((y, g['h']), len(fe)), fe.setdefault((y, g['a']), len(fe)), 0 if g['neutral'] else 1, x,
                        max(-35.0, min(35.0, g['hs'] - g['as']))))
    nf = len(fe)

    def run(j):
        ne = len(SUBS) + (0 if j is None else 1)
        A = np.zeros((len(eqs), nf + 1 + ne)); Y = np.zeros(len(eqs))
        for k, (_, h, a_, hfa, x, m) in enumerate(eqs):
            A[k, h] = 1; A[k, a_] = -1; A[k, nf] = hfa; A[k, nf + 1:nf + 1 + len(SUBS)] = x[:len(SUBS)]
            if j is not None:
                A[k, -1] = x[len(SUBS) + j]
            Y[k] = m
        reg = np.zeros(A.shape[1]); reg[:nf] = 2
        M = A.T @ A + np.diag(reg); cf = np.linalg.solve(M, A.T @ Y); res_ = Y - A @ cf
        cov = (res_ @ res_ / (len(Y) - A.shape[1])) * np.linalg.inv(M)
        se = defaultdict(float)
        for k, e in enumerate(eqs):
            se[e[0]] += float(res_[k] ** 2)
        return cf, cov, se
    _, _, se0 = run(None)
    n2 = {'games': len(eqs), 'alpha': {}}
    drop = {}
    for j, a in enumerate(ALPHAS):
        cf, cov, se = run(j)
        drop[a] = {y: se0[y] - se[y] for y in targets}
        n2['alpha'][str(a)] = {'coef': round(float(-cf[-1]), 3), 't': round(float(-cf[-1] / math.sqrt(cov[-1, -1])), 2), 'sseDrop': round(sum(drop[a].values()), 1)}
    pick, d = {}, []
    for y in targets:
        a_ = max(ALPHAS, key=lambda a: sum(v for k, v in drop[a].items() if k != y))
        pick[y] = a_; d.append(drop[a_][y] - drop[BASE][y])
    n2.update({'nestedPick': pick, 'dSseNestedVsBase': [round(x, 1) for x in d], 't': tstat(d), 'better': sum(x > 0 for x in d), 'seasons': len(d)})
    res['N2'] = n2

    # ---- N3: wins per team AV, leave one season out
    games = [g for g in W.rows(W.get('games.csv', W.GAMES)) if g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    Wn = defaultdict(float)
    for g in games:
        y, hs, as_ = int(g['season']), float(g['home_score']), float(g['away_score'])
        for t, dd in ((g['home_team'], hs - as_), (g['away_team'], as_ - hs)):
            Wn[(y, t)] += 1 if dd > 0 else 0.5 if dd == 0 else 0
    TR = []
    for y in ys:
        av = defaultdict(float)
        for p in S[y]['players']:
            av[p['t']] += p['av']
        for t, tm in S[y]['teams'].items():
            TR.append((y, av[t], Wn[(y, t)] * 17 / tm['g']))
    out3 = {'k': {}, 'rmse': {}}
    dk = []
    for y in ys:
        tr = [r for r in TR if r[0] != y]; te = [r for r in TR if r[0] == y]
        x = np.array([r[1] for r in tr]); yy = np.array([r[2] for r in tr])
        k = float(np.cov(x, yy, bias=True)[0, 1] / x.var()); a = yy.mean() - k * x.mean()
        a0 = yy.mean() - W.NWAR_PER_AV * x.mean()
        e1 = math.sqrt(np.mean([(r[2] - a - k * r[1]) ** 2 for r in te])); e0 = math.sqrt(np.mean([(r[2] - a0 - W.NWAR_PER_AV * r[1]) ** 2 for r in te]))
        out3['k'][y] = round(k, 4); out3['rmse'][y] = [round(e0, 3), round(e1, 3)]
        dk.append(e0 ** 2 - e1 ** 2)
    x = np.array([r[1] for r in TR]); yy = np.array([r[2] for r in TR])
    out3.update({'kAll': round(float(np.cov(x, yy, bias=True)[0, 1] / x.var()), 4), 'r': round(float(np.corrcoef(x, yy)[0, 1]), 3),
                 'used': W.NWAR_PER_AV, 'teams': len(TR), 't': tstat(dk), 'better': sum(v > 0 for v in dk), 'seasons': len(dk)})
    res['N3'] = out3

    # Holm over the three
    ps = {k: pval(res[k]['t'], res[k]['seasons'] - 1) for k in ('N1', 'N2', 'N3')}
    order = sorted(ps, key=lambda k: ps[k] if ps[k] is not None else 1)
    holm, ok = {}, True
    for i, k in enumerate(order):
        thr = 0.05 / (len(order) - i)
        passed = ok and ps[k] is not None and ps[k] < thr and res[k]['t'] > 0 and res[k]['better'] > res[k]['seasons'] / 2
        ok = ok and passed
        holm[k] = {'p': None if ps[k] is None else round(ps[k], 4), 'thr': round(thr, 4), 'pass': passed}
    res['holm'] = holm
    for k in ('N1', 'N2', 'N3'):
        if res[k]['t'] is not None:
            res[k]['t'] = round(res[k]['t'], 2)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1, default=str)
        f.write('\n')
    print(json.dumps(res, indent=1, default=str))


if __name__ == '__main__':
    main()
