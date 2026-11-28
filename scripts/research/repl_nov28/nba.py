#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA VORX replacement level, Nov 28 2026: flat vs by position, fixed vs refit each season.

VORX = .030 x (rXPM - R) x MP / 48. A flat R cannot be fit on same-season team results (every team plays the same
minutes, so R only moves the intercept); it shows up where minutes are not fixed:
  T1  pool: R from seasons < n scored on season n's freely available players (age 24+, under 250 MP the season
      before; the Oct 18 pool), minutes-weighted, flat and by position. The qualified-minutes form (the 10th-13th man by
      team minutes, 100+ MP) is scored the same way.
  T2  next season's team W% and net rating on returning VORX (season n VORX of the players on the n+1 roster, at n+1
      minutes share for the rate part; rookies and players with no season n carry 0 = replacement). Leave one season out.
  T3  same season W% / net on team VORX (only the position split can move it; a flat R is a constant there).
Positions: bbref PG/SG = G, SF/PF = F, C = C. Writes research/repl_nov28/nba.json."""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..', '..', '..')
PF = '/mnt/project-files/cbb/xpm'
K = 0.030
G3 = {'PG': 'G', 'SG': 'G', 'SF': 'F', 'PF': 'F', 'C': 'C'}
def g3(p): return G3.get(str(p).split('-')[0], 'F')

S = {}
for y in range(2010, 2027):
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{y}.json')))
    S[y] = {p['id']: p for p in d['players'] if not p.get('pr') and p.get('xpm') is not None}
def xv(p): return p['txpm'] if p.get('txpm') is not None else p['xpm']
P = pd.read_csv(f'{PF}/players.csv', low_memory=False, usecols=['year', 'pid', 'tm', 'pos', 'age', 'mp'])
P = P[~P.tm.astype(str).str.match(r'^\dTM$|^TOT$')].copy(); P['mp'] = pd.to_numeric(P.mp, errors='coerce').fillna(0)
T = pd.read_csv(f'{PF}/teams.csv'); T['net'] = pd.to_numeric(T.net_rtg.astype(str).str.replace('+', '', regex=False), errors='coerce')
WP = {(r.year, r.tm): r.wins / (r.wins + r.losses) for r in T.itertuples()}; NET = {(r.year, r.tm): r.net for r in T.itertuples()}
TMP = P.groupby(['year', 'tm']).mp.sum().to_dict()
YRS = list(range(2011, 2027))


def pools(y):
    """season y: (x, mp, pos) rows of the freely available pool and of the qualified-minutes bench pool"""
    fa, q = [], []
    for pid, p in S[y].items():
        prev = S.get(y - 1, {}).get(pid); pm = prev['mp'] if prev else 0
        if (p.get('age') or 0) >= 24 and pm < 250 and p['mp'] > 0: fa.append((xv(p), p['mp'], g3(p['pos'])))
    st = P[P.year == y]
    for tm, g in st.groupby('tm'):
        g = g.sort_values('mp', ascending=False).reset_index(drop=True)
        for i, r in g.iterrows():
            if 9 <= i <= 12 and r.mp >= 100 and r.pid in S[y]: q.append((xv(S[y][r.pid]), r.mp, g3(S[y][r.pid]['pos'])))
    return fa, q


def wmean(rows, pos=None):
    r = [(x, m) for x, m, p in rows if pos is None or p == pos]
    return float(np.average([a for a, _ in r], weights=[b for _, b in r])) if r else float('nan')


PO = {y: pools(y) for y in YRS}
lvl = {y: {'fa': wmean(PO[y][0]), 'q': wmean(PO[y][1]), **{f'fa_{g}': wmean(PO[y][0], g) for g in 'GFC'},
           **{f'q_{g}': wmean(PO[y][1], g) for g in 'GFC'}, 'fa_mp': sum(m for _, m, _ in PO[y][0])} for y in YRS}
out = {'levels': {y: {k: round(v, 2) for k, v in d.items()} for y, d in lvl.items()}}


# ---- T1: forecast season n's pool from seasons before n ----
def est(y, pool, how, pos=None):
    key = pool if pos is None else f'{pool}_{pos}'
    yrs = [z for z in YRS if z < y] if how == 'expanding' else [z for z in YRS if y - 3 <= z < y]
    if how == 'fixed': return -1.4
    return float(np.average([lvl[z][key] for z in yrs], weights=[lvl[z]['fa_mp'] for z in yrs]))


t1 = {}
for how in ('fixed', 'expanding', 'trailing3'):
    for posw in (False, True):
        e = []
        for y in range(2014, 2027):
            if posw:   # each FA player's error against his position's line
                for x_, m, p in PO[y][0]: e.append((wmean(PO[y][0], p) - est(y, 'fa', how, p), m))
            else:
                e.append((lvl[y]['fa'] - est(y, 'fa', how), lvl[y]['fa_mp']))
        t1[f'{how}{"_pos" if posw else ""}'] = round(float(np.sqrt(np.average([a * a for a, _ in e], weights=[b for _, b in e]))), 3)
# does a position line explain the FA pool's players better than the flat line? (player-level, minutes-weighted, held out)
pl = {'flat': [], 'pos': []}
for y in range(2014, 2027):
    for x_, m, p in PO[y][0]:
        pl['flat'].append(((x_ - est(y, 'fa', 'trailing3')) ** 2, m)); pl['pos'].append(((x_ - est(y, 'fa', 'trailing3', p)) ** 2, m))
t1['player_mse'] = {k: round(float(np.average([a for a, _ in v], weights=[b for _, b in v])), 3) for k, v in pl.items()}
out['T1_pool_forecast_rmse'] = t1


# ---- T2 / T3: team tests ----
def rline(y, form):
    """the replacement line(s) a season-y VORX uses under each form (estimated on seasons before y)"""
    if form == 'fixed': return {g: -1.4 for g in 'GFC'}
    if form == 'flat3': return {g: est(y, 'fa', 'trailing3') for g in 'GFC'}
    if form == 'pos3': return {g: est(y, 'fa', 'trailing3', g) for g in 'GFC'}
    if form == 'q3': return {g: est(y, 'q', 'trailing3') for g in 'GFC'}
    if form == 'qpos3': return {g: est(y, 'q', 'trailing3', g) for g in 'GFC'}
    if form == 'flatx': return {g: est(y, 'fa', 'expanding') for g in 'GFC'}
    if form == 'posx': return {g: est(y, 'fa', 'expanding', g) for g in 'GFC'}
    if form == 'posoff':   # the fixed line, moved by each position's expanding offset from the flat pool
        return {g: -1.4 + est(y, 'fa', 'expanding', g) - est(y, 'fa', 'expanding') for g in 'GFC'}
    if form == 'qposoff3':   # the form that passed in CBB: the fixed line + trailing-3 bench offsets
        return {g: -1.4 + est(y, 'q', 'trailing3', g) - est(y, 'q', 'trailing3') for g in 'GFC'}
    if form == 'qposoff':
        return {g: -1.4 + est(y, 'q', 'expanding', g) - est(y, 'q', 'expanding') for g in 'GFC'}
    raise KeyError(form)


FORMS = ('fixed', 'flatx', 'flat3', 'posx', 'pos3', 'q3', 'qpos3', 'posoff', 'qposoff', 'qposoff3')


def team_x(n, form, nxt):
    R = rline(n, form); yy = n + 1 if nxt else n; X = {}
    for r in P[P.year == yy].itertuples():
        p = S[n].get(r.pid)
        if nxt:   # returning VORX: season-n count, newcomers 0
            v = K * (xv(p) - R[g3(p['pos'])]) * p['mp'] / 48 if p else 0.0
            share = 1.0 if p else 0.0
            # split a multi-team returner's VORX by his n+1 minutes share on this team
            tot = P[(P.year == yy) & (P.pid == r.pid)].mp.sum() if p else 0
            v = v * (r.mp / tot) if tot else 0.0
        else:
            v = K * (xv(p) - R[g3(p['pos'])]) * r.mp / 48 if p else 0.0
        X[r.tm] = X.get(r.tm, 0.0) + v
    return {t: X[t] for t in X if (yy, t) in WP}


def loso(form, nxt, tgt, fe=False):
    ys = [n for n in range(2014, 2026 if nxt else 2027) if n not in (2020, 2021) and (not nxt or n + 1 not in (2020, 2021))]
    D = {}
    for n in ys:
        yy = n + 1 if nxt else n; tx = team_x(n, form, nxt)
        D[n] = np.array([[tx[t], (WP if tgt == 'wp' else NET)[(yy, t)]] for t in tx])
        if fe: D[n] = D[n] - D[n].mean(axis=0)   # season fixed effect: a flat line drops out, only the split is left
    per, e = {}, []
    for h in ys:
        tr = np.vstack([D[n] for n in ys if n != h]); b, a = np.polyfit(tr[:, 0], tr[:, 1], 1)
        r = D[h][:, 1] - (a + b * D[h][:, 0]); e += list(r); per[h] = float(np.mean(r ** 2))
    sc = 82 if tgt == 'wp' else 1
    return {'rmse': round(float(np.sqrt(np.mean(np.square(e)))) * sc, 4), 'per': per}


res = {}
for nxt in (False, True):
    for tgt, fe in (('wp', False), ('net', False), ('wp', True), ('net', True)):
        k = f'{"next" if nxt else "same"}_{tgt}{"_fe" if fe else ""}'
        R_ = {f: loso(f, nxt, tgt, fe) for f in FORMS}
        base = R_['fixed']['per']; row = {}
        for f in FORMS:
            d = np.array([base[h] - R_[f]['per'][h] for h in base])
            t = float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if f != 'fixed' and d.std() > 0 else 0.0
            row[f] = {'rmse': R_[f]['rmse'], 't_vs_fixed': round(t, 2), 'better': int((d > 0).sum()), 'of': len(d)}
        res[k] = row
        print(k, {f: (row[f]['rmse'], row[f]['t_vs_fixed'], row[f]['better']) for f in FORMS}, flush=True)
out['T2_T3_team'] = res
out['now'] = {'flat3_2027': round(est(2027, 'fa', 'trailing3'), 2), **{f'pos3_2027_{g}': round(est(2027, 'fa', 'trailing3', g), 2) for g in 'GFC'},
              'q3_2027': round(est(2027, 'q', 'trailing3'), 2)}
json.dump(out, open(os.path.join(HERE, 'nba.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != 'levels'}, indent=1))
print({y: (d['fa'], d['fa_G'], d['fa_F'], d['fa_C'], d['q']) for y, d in out['levels'].items()})
