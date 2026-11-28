#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB VORX replacement level, Nov 28 2026: flat vs by position, fixed vs refit, and the shrink target.

VORX = (x - R) x minutes / 40 x .68 x WPP, x = rXPM shrunk 100 minutes toward the season's minutes-weighted mean.
Barttorvik season files 2010-26 (scripts/.cache/cbb/bt) and team records (scripts/.cache/awards/bt_<y>.json).
Pools, per season: q9 = the 9th man in team minutes (the live definition), bench = the 9th-12th men, newcomers = lines with
no D-I line (by Barttorvik pid) the season before. Positions: Barttorvik role (cbb_tabs POSMAP: G, F, C).
  T1  each pool's level forecast from earlier seasons (fixed -1.4, expanding, trailing 3), scored on the next season.
  T2  same-season team W% on team VORX, LOSO, with and without season fixed effects (a flat R drops out under FE).
  T3  next-season W% on returning VORX (season-n VORX of players on the n+1 roster, newcomers 0), LOSO; a nested R grid.
  S   shrink target: season mean (live) vs the replacement line vs a minutes role mean, on next-season x of returners
      (a held-out check of how far the shrink lifts low-minute players). Writes research/repl_nov28/cbb.json."""
import json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..', '..', '..'); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cbb_data as D, cbb_xpm as XP
from cbb_tabs import POSMAP
PACE, WPP, K = 0.68, 0.0187, 100.0
YRS = list(range(2010, 2027))
L, MU, REC = {}, {}, {}
for y in YRS:
    ls = [l for l in XP.rxpm_lines(D.load_bt(y)) if l.get('xpm') is not None and (l.get('gp') or 0) and (l.get('mp') or 0)]
    for l in ls: l['mins'] = l['gp'] * l['mp']; l['p3'] = POSMAP.get(l['role'], 'F')
    w = sum(l['mins'] for l in ls); MU[y] = sum(l['xpm'] * l['mins'] for l in ls) / w
    for l in ls: l['sx'] = (l['xpm'] * l['mins'] + K * MU[y]) / (l['mins'] + K)
    L[y] = ls
    for r in json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'awards', f'bt_{y}.json'))):
        try: wv, lv = (int(x) for x in str(r[3]).split('-')[:2])
        except ValueError: continue
        if wv + lv >= 20: REC[(y, r[1])] = (wv / (wv + lv), wv + lv)
PID = {y: {str(l['pid']) for l in L[y]} for y in YRS}


def pools(y):
    by = defaultdict(list)
    for l in L[y]: by[l['team']].append(l)
    q9, bench = [], []
    for t, g in by.items():
        g.sort(key=lambda l: -l['mins'])
        if len(g) >= 9: q9.append(g[8])
        bench += g[8:12]
    new = [l for l in L[y] if y - 1 in PID and str(l['pid']) not in PID[y - 1]] if y > YRS[0] else []
    return {'q9': q9, 'bench': bench, 'new': new}


def wm(ls, pos=None, k='sx'):
    ls = [l for l in ls if pos is None or l['p3'] == pos]; w = sum(l['mins'] for l in ls)
    return sum(l[k] * l['mins'] for l in ls) / w if w else float('nan')


PO = {y: pools(y) for y in YRS}
LV = {y: {f'{p}{"_" + g if g else ""}': wm(PO[y][p], g or None) for p in ('q9', 'bench', 'new') for g in ('', 'G', 'F', 'C')} for y in YRS}
WT = {y: sum(l['mins'] for l in PO[y]['bench']) for y in YRS}
out = {'levels': {y: {k: round(v, 2) for k, v in d.items() if v == v} for y, d in LV.items()}, 'mu': {y: round(v, 2) for y, v in MU.items()}}


def est(y, key, how):
    if how == 'fixed': return -1.4
    ys = [z for z in YRS if z < y and LV[z].get(key) == LV[z].get(key)]
    if how == 'trailing3': ys = ys[-3:]
    if not ys: return -1.4
    return float(np.average([LV[z][key] for z in ys], weights=[WT[z] for z in ys]))


t1 = {}
for key in ('q9', 'bench', 'new'):
    for how in ('fixed', 'expanding', 'trailing3'):
        e = [LV[y][key] - est(y, key, how) for y in range(2013, 2027) if LV[y][key] == LV[y][key]]
        t1[f'{key}_{how}'] = round(float(np.sqrt(np.mean(np.square(e)))), 3)
out['T1_pool_forecast_rmse'] = t1


def rline(y, form):
    if form == 'fixed': return {g: -1.4 for g in 'GFC'}
    if form == 'prod':   # the lines scripts/repl_levels.py writes (data/repl_levels.json bySeason)
        return PROD.get(str(y)) or {g: -1.4 for g in 'GFC'}
    if form.startswith('R='): return {g: float(form[2:]) for g in 'GFC'}
    pool, how, pos = form.split(':')
    if pos == 'flat': return {g: est(y, pool, how) for g in 'GFC'}
    if pos == 'pos': return {g: est(y, f'{pool}_{g}', how) for g in 'GFC'}
    if pos == 'off': return {g: -1.4 + est(y, f'{pool}_{g}', how) - est(y, pool, how) for g in 'GFC'}


def vx(l, R): return (l['sx'] - R[l['p3']]) * l['mins'] / 40 * PACE * WPP


def team_rows(n, form, nxt):
    R = rline(n, form); X = defaultdict(float)
    if not nxt:
        for l in L[n]: X[l['team']] += vx(l, R)
        return {t: (X[t], REC[(n, t)][0]) for t in X if (n, t) in REC}
    last = {str(l['pid']): l for l in L[n]}
    for l in L[n + 1]:
        p = last.get(str(l['pid']))
        if p: X[l['team']] += vx(p, R)
    return {t: (X[t], REC[(n + 1, t)][0]) for t in X if (n + 1, t) in REC}


def loso(form, nxt, fe):
    ys = [n for n in range(2012, 2026 if nxt else 2027) if n != 2020 and not (nxt and n + 1 == 2021)]
    Dd = {}
    for n in ys:
        a = np.array(list(team_rows(n, form, nxt).values()))
        Dd[n] = a - a.mean(axis=0) if fe else a
    per = {}
    for h in ys:
        tr = np.vstack([Dd[n] for n in ys if n != h]); b, a0 = np.polyfit(tr[:, 0], tr[:, 1], 1)
        per[h] = float(np.mean((Dd[h][:, 1] - a0 - b * Dd[h][:, 0]) ** 2))
    return per


PROD = json.load(open(os.path.join(ROOT, 'data', 'repl_levels.json')))['cbb']['bySeason']
FORMS = ['fixed', 'prod', 'q9:expanding:flat', 'bench:expanding:flat', 'bench:trailing3:flat', 'new:expanding:flat',
         'bench:expanding:pos', 'bench:expanding:off', 'q9:expanding:off', 'bench:trailing3:off']
res = {}
for nxt in (False, True):
    for fe in (False, True):
        k = f'{"next" if nxt else "same"}{"_fe" if fe else ""}'
        P_ = {f: loso(f, nxt, fe) for f in FORMS}; base = P_['fixed']; row = {}
        for f in FORMS:
            d = np.array([base[h] - P_[f][h] for h in base])
            t = float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if f != 'fixed' and d.std() > 0 else 0.0
            row[f] = {'rmse_wins31': round(float(np.sqrt(np.mean(list(P_[f].values())))) * 31, 4), 't': round(t, 2), 'better': int((d > 0).sum()), 'of': len(d)}
        res[k] = row; print(k, {f: (r['rmse_wins31'], r['t'], r['better']) for f, r in row.items()}, flush=True)
# nested flat-R grid on the next-season test (the C2 test of Nov 3, now on shrunk rXPM)
grid = [round(-0.5 * i, 1) for i in range(0, 13)]
G = {r: loso(f'R={r}', True, False) for r in grid}; base = loso('fixed', True, False)
d, picks = [], {}
for h in base:
    rp = min(grid, key=lambda r: sum(v for k_, v in G[r].items() if k_ != h)); picks[h] = rp; d.append(base[h] - G[rp][h])
d = np.array(d)
res['next_nestedR'] = {'picks': picks, 'sse_by_R': {r: round(float(np.mean(list(G[r].values()))) * 961, 3) for r in grid},
                       't': round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2), 'better': int((d > 0).sum()), 'of': len(d)}
print('nested', res['next_nestedR'])
out['T2_T3_team'] = res

# ---- S: how much the shrink lifts bad low-minute players, and which target predicts their next x ----
rows = []
for n in YRS[:-1]:
    nx = {str(l['pid']): l for l in L[n + 1]}
    for l in L[n]:
        q = nx.get(str(l['pid']))
        if q and q['mins'] >= 200: rows.append((l['xpm'], l['mins'], MU[n], est(n + 1, 'bench', 'expanding') if n + 1 > 2011 else -1.4, q['xpm'], q['mins']))
A = np.array(rows)
def sh(tgt, k=K): return (A[:, 0] * A[:, 1] + k * tgt) / (A[:, 1] + k)
srep = {}
for lab, tgt in (('mean', A[:, 2]), ('replacement', A[:, 3]), ('raw', None)):
    p = A[:, 0] if tgt is None else sh(tgt)
    for band, m in (('all', A[:, 1] > 0), ('under200', A[:, 1] < 200), ('under200_xlt-5', (A[:, 1] < 200) & (A[:, 0] < -5))):
        e = (A[m, 4] - p[m]); srep[f'{lab}_{band}'] = {'rmse': round(float(np.sqrt(np.average(e ** 2, weights=A[m, 5]))), 3),
                                                       'bias': round(float(np.average(e, weights=A[m, 5])), 3), 'n': int(m.sum())}
low = (A[:, 1] < 200) & (A[:, 0] < -5)
srep['lift_under200_xlt-5'] = {'raw_mean': round(float(A[low, 0].mean()), 2), 'shrunk_mean': round(float(sh(A[:, 2])[low].mean()), 2), 'next_mean': round(float(A[low, 4].mean()), 2)}
out['S_shrink'] = srep
out['now'] = {k: round(est(2027, k, 'expanding'), 2) for k in ('q9', 'bench', 'bench_G', 'bench_F', 'bench_C', 'new')}
json.dump(out, open(os.path.join(HERE, 'cbb.json'), 'w'), indent=1)
print(json.dumps({k: out[k] for k in ('T1_pool_forecast_rmse', 'S_shrink', 'now', 'mu')}, indent=1))
