#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Can pXPM be the most predictive NBA metric? (Nov 24 2026)

Season-n value of each candidate -> (a) team season-(n+1) net rating R2 (scripts/nba_xpm_predictive_research.py:
value x n+1 share of team minutes x5, players with no season-n value take the metric's under-500-MP mean; the nine
pairs) and (b) player next-season XPM RMSE (250+ MP next season, weighted by those minutes, 2011-26 pairs).
Candidates use only seasons <= n (aging curve: nba_games.aging_curve(n+1), fit on pairs ending <= n).
Family 'proj' (per side o, d): (k x mu_role + sum_j w_j MP_{n-j} x_{n-j}) / (k + sum_j w_j MP_{n-j}) + a x cv(age+1),
w_0 = 1. Leave-one-pair-out: params picked on the other pairs, scored on the held-out pair, predictions pooled.
-> data/nba_pxpm_research.json"""
import itertools, json, math, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..'); sys.path.insert(0, HERE)
import nba_games as N
import nba_xpm as X
PF = sys.argv[1] if len(sys.argv) > 1 else '/mnt/project-files'

S = {}
for y in range(2010, 2027):
    d = json.load(open(os.path.join(X.OUT, f'{y}.json')))
    S[y] = {'g': d['games'], 'p': {p['id']: p for p in d['players'] if not p.get('pr') and p.get('oxpm') is not None}}
P = pd.read_csv(f'{PF}/cbb/xpm/players.csv', low_memory=False, usecols=['year', 'pid', 'tm', 'mp'])
P = P[~P.tm.astype(str).str.match(r'^\dTM$|^TOT$')].copy(); P['mp'] = pd.to_numeric(P.mp, errors='coerce').fillna(0)
T = pd.read_csv(f'{PF}/cbb/xpm/teams.csv')
T['net'] = pd.to_numeric(T.net_rtg.astype(str).str.replace('+', '', regex=False), errors='coerce')
NET = {(r.year, r.tm): r.net for r in T.itertuples()}
TMP = P.groupby(['year', 'tm']).mp.sum().to_dict()
TEAMPAIRS = [n for n in range(2014, 2026) if n not in (2020, 2021) and n + 1 not in (2020, 2021)]
PLPAIRS = list(range(2011, 2026))
CV = {n: N.aging_curve(n + 1) for n in range(2010, 2026)}


def arrays(n):
    """season n: ids, then per side (o, d) MP and value rows for n, n-1, n-2, lm (role-mean minutes term), aging"""
    ids = list(S[n]['p']); A = {'ids': ids}
    for j in (0, 1, 2):
        q = [S.get(n - j, {'p': {}})['p'].get(pid) for pid in ids]
        A[f'm{j}'] = np.array([r['mp'] if r and r.get('oxpm') is not None else 0.0 for r in q], float)
        for side in ('oxpm', 'dxpm'):
            A[f'{side}{j}'] = np.array([r[side] if r and r.get(side) is not None else 0.0 for r in q], float)
    A['lm'] = np.log(1 + A['m0'] * 82 / max(S[n]['g'], 1) / 100)
    A['cv'] = np.array([CV[n](S[n]['p'][pid]['age'] + 1) if CV[n] and S[n]['p'][pid].get('age') else 0.0 for pid in ids])
    return A


AR = {}


def proj(n, k=600, w1=0.0, w2=0.0, age=0.0, a0=0.0, b0=1.0):
    """pid -> value for season n. Role mean per side: (MU0 + a0 x share) + b0 x MU1 x lm, share .75 o / .25 d"""
    if n not in AR: AR[n] = arrays(n)
    A = AR[n]; v = age * A['cv']
    for side, key, sh in (('o', 'oxpm', .75), ('d', 'dxpm', .25)):
        a, b = X.SHRINK_MU[side]; mu = a + a0 * sh + b0 * b * A['lm']
        num, den = k * mu, k + 0 * mu
        for j, w in ((0, 1.0), (1, w1), (2, w2)):
            if w: num = num + w * A[f'm{j}'] * A[f'{key}{j}']; den = den + w * A[f'm{j}']
        v = v + num / den
    return dict(zip(A['ids'], v.tolist()))


def field(n, key):
    return {pid: p[key] for pid, p in S[n]['p'].items() if p.get(key) is not None}


def team_rows(vals, n):
    fill = np.mean([v for pid, v in vals.items() if S[n]['p'][pid]['mp'] < 500] or [0])
    rows = {}
    for r in P[P.year == n + 1].itertuples():
        rows[r.tm] = rows.get(r.tm, 0.0) + vals.get(r.pid, fill) * 5 * r.mp / TMP[(n + 1, r.tm)]
    return [(rows[t], NET[(n + 1, t)]) for t in rows if (n + 1, t) in NET]


def pl_rows(vals, n):
    nx = S[n + 1]['p']
    return [(vals[pid], q['xpm'], q['mp']) for pid, q in nx.items() if q['mp'] >= 250 and pid in vals]


def r2(rows):
    a = np.array(rows); return float(np.corrcoef(a[:, 0], a[:, 1])[0, 1] ** 2)


def rmse(rows):
    a = np.array(rows); return float(np.sqrt(np.average((a[:, 0] - a[:, 1]) ** 2, weights=a[:, 2])))


def season_rmse(rows): return {n: rmse(r) for n, r in rows.items()}


def main():
    """Primary (fixed before scoring the team test): each fold picks the grid point with the lowest player RMSE on the
    other seasons (pXPM's own target, next-season XPM); that pick's held-out values are then scored on both tests.
    Pass: held-out player RMSE below live pXPM in a paired per-season t-test (t <= -2) and team R2 above rXPM and BPM
    on the nine pairs (paired resample of pairs, P(better) >= .9)."""
    base = {'rXPM': lambda n: field(n, 'xpm'), 'pXPM (live)': lambda n: field(n, 'sxpm'), 'BPM': lambda n: field(n, 'bpm'),
            'DPM': lambda n: field(n, 'dpm')}
    grid = list(itertools.product((100, 150, 200, 300, 450, 600), (0, .25, .35, .5), (0, .1, .2), (0, .75, 1.0, 1.25),
                                  (-1.5, -1, -.5, 0), (1, 1.5, 2, 2.5, 3)))
    print(len(grid), 'grid points', flush=True)
    L_ = {g: {n: pl_rows(proj(n, *g), n) for n in PLPAIRS} for g in grid}
    res = {'grid': 'k x w1 x w2 x age x a0 x b0', 'base': {}, 'loo': {}}
    TR, PR = {}, {}
    for m, f in base.items():
        TR[m] = {n: team_rows(f(n), n) for n in TEAMPAIRS}; PR[m] = {n: pl_rows(f(n), n) for n in PLPAIRS}
        res['base'][m] = {'team': round(r2(sum(TR[m].values(), [])), 4), 'player': round(rmse(sum(PR[m].values(), [])), 4)}
        print(m, res['base'][m], flush=True)
    picks, th, ph = {}, {}, {}
    for h in PLPAIRS:
        best = min(grid, key=lambda g: rmse(sum((L_[g][n] for n in PLPAIRS if n != h), [])))
        picks[h] = list(best); ph[h] = L_[best][h]
        if h in TEAMPAIRS: th[h] = team_rows(proj(h, *best), h)
    TR['pXPM (new)'], PR['pXPM (new)'] = th, ph
    full = min(grid, key=lambda g: rmse(sum(L_[g].values(), [])))
    res['ship'] = list(full)
    res['loo'] = {'picks': picks, 'team': round(r2(sum(th.values(), [])), 4), 'player': round(rmse(sum(ph.values(), [])), 4)}
    print('held out', res['loo'], 'full-sample pick', full, flush=True)
    a, b = season_rmse(PR['pXPM (new)']), season_rmse(PR['pXPM (live)'])
    d = np.array([a[n] - b[n] for n in PLPAIRS])
    res['playerTest'] = {'diff': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
                         'better': int((d < 0).sum()), 'of': len(d),
                         'perSeason': {n: [round(a[n], 3), round(b[n], 3)] for n in PLPAIRS}}
    rng = np.random.default_rng(0); pk = [rng.choice(TEAMPAIRS, len(TEAMPAIRS)) for _ in range(2000)]
    new = np.array([r2(sum((th[n] for n in p), [])) for p in pk])
    res['teamTest'] = {}
    for m in ('rXPM', 'BPM', 'pXPM (live)', 'DPM'):
        o = np.array([r2(sum((TR[m][n] for n in p), [])) for p in pk])
        res['teamTest'][m] = {'diff': round(float(np.median(new - o)), 4), 'p_better': round(float((new > o).mean()), 3),
                              'pairsBetter': int(sum(r2(th[n]) > r2(TR[m][n]) for n in TEAMPAIRS))}
    res['teamPair'] = {m: {n: round(r2(TR[m][n]), 3) for n in TEAMPAIRS} for m in TR}
    # what each piece adds (full-sample pick with one piece switched off), both tests
    k, w1, w2, ag, a0, b0 = full; res['ablate'] = {}
    for name, g in (('ship', full), ('no aging', (k, w1, w2, 0, a0, b0)), ('one season', (k, 0, 0, ag, a0, b0)),
                    ('old role mean', (k, w1, w2, ag, 0, 1)), ('k 600', (600, w1, w2, ag, a0, b0))):
        res['ablate'][name] = [round(r2(sum((team_rows(proj(n, *g), n) for n in TEAMPAIRS), [])), 4), round(rmse(sum(L_[g].values(), [])) if g in L_ else rmse(sum((pl_rows(proj(n, *g), n) for n in PLPAIRS), [])), 4)]
    print(json.dumps({k_: res[k_] for k_ in ('playerTest', 'teamTest', 'ablate')}, indent=1))
    json.dump(res, open(os.path.join(ROOT, 'data', 'nba_pxpm_research.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
