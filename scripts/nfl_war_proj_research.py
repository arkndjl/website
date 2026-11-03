#!/usr/bin/env python3
"""Research + fit (Nov 3 2026): next-season and next-three-seasons WAR for the NFL WAR board, from WAR history, age by
position group and snaps.

    python3 scripts/player_pctl.py --frames nfl      # once: the board replayed per season and checkpoint (scripts/.cache/pctl)
    python3 scripts/nfl_war_proj_research.py         # writes data/nfl_war_proj_fit.json (numpy)

Rows: every board player (pfr id) with snaps at a prediction point: season S's end (f = 1) or a checkpoint inside S
(the frames' weeks 3-15, 2016 on; f = team games played / season length). The board's WAR (pre special teams, as the
percentile frames). Everything on a 17-game scale (x 17 / the team's season length; to date: x 17 / team games, the pace).
    W0  WAR pace this season, s0 snaps pace; W1, W2 / s1 last two full seasons (0 and has = 0 when absent)
    age on Sept 1 of S (roster birth dates); group = the board's QB RB WR TE OL DL LB DB
Targets: y1 = WAR in S+1, y3 = WAR in S+1..S+3 (0 for a season off the board: out of the league is replacement).
S = 2015-24 for y1, 2015-22 for y3 (2013 is the first board, so S-2 exists from 2015).

Baselines (the site's):
    flat     last season's WAR held flat: f W0 + (1 - f) W1 (at f = 1, this season's WAR); x 3 for y3
    marcel   scripts/player_pctl.py's WAR rate: Marcel 1 / .7 / .5 over (S to date, S-1, S-2) WAR and snaps, shrunk to the
             group's veteran rate with K = 800 snaps (data/pctl_fit_nfl.json), x expected snaps f s0 + (1 - f) s1; x 3 for y3
    marcelC  marcel, calibrated (a + b x marcel, fit leaving the season out)
Forms (pre-registered, 4), OLS leaving one season S out, per f on the checkpoint grid:
    A   group intercepts + W0, W1, W2, has1, has2, ln(1 + s0), ln(1 + s1)
    B   A + pooled age: (age - 29)+, (25 - age)+, W0 (age - 29)+   (scripts/nfl_roster.py's pooled curve)
    C   A + by group: (age - 27)+, (27 - age)+, W0 (age - 27)+     (RBs can fall off early, QBs late)
    D   C + W0 by group (how much of a season's WAR carries differs by spot)
Live form: D if it is the best at every grid point for both targets, else C (scripts/nfl_war_proj.py reads it).
Kept: the best of C / D beats the strongest baseline on held-out RMSE at every f with paired t <= -2 (player-seasons),
wins most held-out seasons, calibration slope .8-1.2, for both targets. Also reported: C vs B (position curves vs pooled)
and a time split (fit S <= 2018, test 2019+).
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as NM   # noqa: E402  the shared player-name key
from nfl_war_proj import A0, GROUPS, feats   # noqa: E402  the live build's inputs
OUT = os.path.join(ROOT, 'data', 'nfl_war_proj_fit.json')
FRAMES = os.path.join(HERE, '.cache', 'pctl', 'frames_nfl.json.gz')
MARCEL = (1.0, 0.7, 0.5)


def births():
    """{pfr id: birth date} and {(season, name key, team): birth date} from the season rosters (a third of roster rows
    have no PFR id, nearly every lineman: the board joins those by name and team, so this does too)"""
    out, by_name = {}, {}
    d = os.path.join(HERE, '.cache', 'nfl')
    for y in range(2013, 2027):
        p = os.path.join(d, f'roster_{y}.csv')
        if not os.path.exists(p):
            continue
        with open(p, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                bd = r.get('birth_date') or ''
                if not bd or bd == 'NA':
                    continue
                if r.get('pfr_id') and r['pfr_id'] != 'NA':
                    out[r['pfr_id']] = bd[:10]
                else:
                    by_name[(y, NM.key(r['full_name']), r['team'])] = bd[:10]
    return out, by_name


def age_on(bd, y):
    try:
        by, bm, bdd = map(int, bd.split('-'))
    except (AttributeError, ValueError):
        return None
    return y - by + ((9 - bm) * 30.4 + (1 - bdd)) / 365.25


FORMS = ('A', 'B', 'C', 'D')


def load():
    with gzip.open(FRAMES, 'rt') as f:
        F = {int(k): v for k, v in json.load(f).items()}
    rate = json.load(open(os.path.join(ROOT, 'data', 'pctl_fit_nfl.json')))['rates']['war']
    return F, rate, births()


def season_tab(F):
    """{S: {pid: (WAR17, snaps17, grp, raw war, raw snaps)}} season totals"""
    T = {}
    for S, fr in F.items():
        T[S] = {}
        for pid, p in fr['end'].items():
            tl = fr['tlen'].get(p['tm'], 17) or 17
            T[S][pid] = (p['x']['war'] * 17 / tl, p['e'] * 17 / tl, p['grp'], p['x']['war'], p['e'])
    return T


def rows_at(F, T, B, rate, S, w):
    """prediction rows for season S at checkpoint w ('end' = the full season)"""
    fr = F[S]
    d = fr['end'] if w == 'end' else fr['cp'].get(w)
    if not d:
        return [], None
    out, fs = [], []
    K, mu = rate['K'], rate['mu']
    for pid, p in d.items():
        if p['e'] < 1 or p['grp'] not in GROUPS:
            continue
        tl = fr['tlen'].get(p['tm'], 17) or 17
        tg = tl if w == 'end' else p['tg']
        if tg <= 0:
            continue
        f = min(1.0, tg / tl)
        a = age_on(B[0].get(pid) or B[1].get((S, NM.key(p['n']), p['tm'])), S)
        if a is None:
            continue
        W0, s0 = p['x']['war'] * 17 / tg, p['e'] * 17 / tg
        h1, h2 = T.get(S - 1, {}).get(pid), T.get(S - 2, {}).get(pid)
        W1, s1 = (h1[0], h1[1]) if h1 else (0.0, 0.0)
        W2, s2 = (h2[0], h2[1]) if h2 else (0.0, 0.0)
        g = p['grp']
        # baselines
        flat = f * W0 + (1 - f) * W1
        num = MARCEL[0] * p['x']['war'] + (MARCEL[1] * h1[3] if h1 else 0) + (MARCEL[2] * h2[3] if h2 else 0)
        den = MARCEL[0] * p['e'] + (MARCEL[1] * h1[4] if h1 else 0) + (MARCEL[2] * h2[4] if h2 else 0)
        r = (num + K * mu.get(g + ':v', 0.0)) / (den + K)
        marcel = r * (f * s0 + (1 - f) * s1)
        ys = []
        for k in (1, 2, 3):
            t = T.get(S + k)
            ys.append(None if t is None else (t[pid][0] if pid in t else 0.0))
        y1 = ys[0]
        y3 = None if None in ys else sum(ys)
        out.append({'pid': pid, 'S': S, 'f': f, 'g': g, 'a': a, 'W0': W0, 'W1': W1, 'W2': W2, 'h1': 1.0 if h1 else 0.0,
                    'h2': 1.0 if h2 else 0.0, 's0': s0, 's1': s1, 'flat': flat, 'marcel': marcel, 'y1': y1, 'y3': y3})
        fs.append(f)
    return out, float(np.median(fs)) if fs else None


def X_of(form, R):
    return np.array([feats(form, r['g'], r['W0'], r['W1'], r['W2'], r['h1'], r['h2'], r['s0'], r['s1'], r['a']) for r in R])


def loso(X, y, S, ridge=1e-6):
    p = np.zeros_like(y)
    for s in sorted(set(S)):
        tr, te = S != s, S == s
        A = X[tr]
        b = np.linalg.solve(A.T @ A + ridge * np.eye(A.shape[1]), A.T @ y[tr])
        p[te] = X[te] @ b
    return p


def fit_all(X, y, ridge=1e-6):
    return np.linalg.solve(X.T @ X + ridge * np.eye(X.shape[1]), X.T @ y)


def tstat(d):
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


def evaluate(R, tgt, forward=False):
    R = [r for r in R if r[tgt] is not None and r['S'] >= 2015]
    y = np.array([r[tgt] for r in R])
    S = np.array([r['S'] for r in R])
    m = 3 if tgt == 'y3' else 1
    pr = {'flat': np.array([r['flat'] for r in R]) * m, 'marcel': np.array([r['marcel'] for r in R]) * m}
    mc = np.column_stack([np.ones(len(R)), pr['marcel']])
    pr['marcelC'] = loso(mc, y, S)
    Xs = {f_: X_of(f_, R) for f_ in FORMS}
    for f_ in FORMS:
        pr[f_] = loso(Xs[f_], y, S)
    e = {k: (v - y) ** 2 for k, v in pr.items()}
    rmse = {k: round(float(np.sqrt(v.mean())), 4) for k, v in e.items()}
    base = min(('flat', 'marcel', 'marcelC'), key=lambda k: rmse[k])
    best = min(('C', 'D'), key=lambda k: rmse[k])
    seasons = sorted(set(S))
    res = {'n': len(R), 'seasons': [int(seasons[0]), int(seasons[-1])], 'rmse': rmse, 'base': base, 'best': best}
    for a_, b_ in ((best, base), ('C', 'B'), ('B', 'A'), ('D', 'C'), (best, 'marcel')):
        d = e[a_] - e[b_]
        ds = np.array([d[S == s].mean() for s in seasons])
        res[f't_{a_}_vs_{b_}'] = round(tstat(d), 2)
        res[f'tSeason_{a_}_vs_{b_}'] = round(tstat(ds), 2)
        res[f'won_{a_}_vs_{b_}'] = f'{int((ds < 0).sum())}/{len(seasons)}'
    res['slope'] = round(float(np.polyfit(pr[best], y, 1)[0]), 3)
    big = np.array([r['s0'] >= 300 for r in R])
    res['rmse300'] = {k: round(float(np.sqrt(e[k][big].mean())), 4) for k in ('flat', 'marcel', 'marcelC', 'B', best)}
    res['n300'] = int(big.sum())
    # by group: best vs base
    res['byGroup'] = {}
    G = np.array([r['g'] for r in R])
    for g in GROUPS:
        k = G == g
        d = e[best][k] - e[base][k]
        res['byGroup'][g] = [round(float(np.sqrt(e[best][k].mean())), 3), round(float(np.sqrt(e[base][k].mean())), 3), round(tstat(d), 2)]
    if forward:   # time split: fit seasons <= 2018, test 2019 on
        tr, te = S <= 2018, S >= 2019
        fw = {}
        for f_ in ('B', best):
            b = fit_all(Xs[f_][tr], y[tr])
            fw[f_] = (Xs[f_][te] @ b - y[te]) ** 2
        bc = fit_all(mc[tr], y[tr])
        fw['marcelC'] = (mc[te] @ bc - y[te]) ** 2
        fw['flat'], fw['marcel'] = e['flat'][te], e['marcel'][te]
        res['forward'] = {k: round(float(np.sqrt(v.mean())), 4) for k, v in fw.items()}
        res['forward']['t_best_vs_' + base] = round(tstat(fw[best] - fw[base]), 2)
    return res, {f_: [round(float(c), 5) for c in fit_all(Xs[f_], y)] for f_ in ('C', 'D')}


def main():
    F, rate, B = load()
    T = season_tab(F)
    grid = []
    for w in ['3', '5', '7', '9', '11', '13', '15', 'end']:
        R, fs = [], []
        for S in sorted(F):
            rs, f = rows_at(F, T, B, rate, S, w)
            R += rs
            if f is not None and S >= 2015:
                fs.append(f)
        g = {'w': w, 'f': round(float(np.median(fs)), 3)}
        for tgt in ('y1', 'y3'):
            res, coef = evaluate(R, tgt, forward=(w in ('9', 'end')))
            g[tgt] = res
            g[tgt + 'c'] = coef
        grid.append(g)
        print(w, g['f'], json.dumps({k: g[k]['rmse'] for k in ('y1', 'y3')}),
              {k: (g[k]['best'], g[k]['base'], g[k][f"t_{g[k]['best']}_vs_{g[k]['base']}"], g[k][f"won_{g[k]['best']}_vs_{g[k]['base']}"], g[k]['slope']) for k in ('y1', 'y3')}, flush=True)
    grid.sort(key=lambda g: g['f'])
    ok = lambda r: r['rmse'][r['best']] < r['rmse'][r['base']] and r[f"t_{r['best']}_vs_{r['base']}"] <= -2 and \
        int(r[f"won_{r['best']}_vs_{r['base']}"].split('/')[0]) * 2 > int(r[f"won_{r['best']}_vs_{r['base']}"].split('/')[1]) and 0.8 <= r['slope'] <= 1.2
    out = {'A0': A0, 'groups': GROUPS, 'forms': list(FORMS), 'formsTried': 4,
           'note': 'pred = c . feats(form): 8 group intercepts, W0, W1, W2, has1, has2, ln(1 + s0), ln(1 + s1), then by group '
                   '(age - 27)+, (27 - age)+, W0 (age - 27)+ [, W0 by group for D]; WAR and snaps per 17 games; interpolate on f',
           'kept': all(ok(g['y1']) and ok(g['y3']) for g in grid),
           'grid': grid}
    for g in grid:
        g['y1']['pass'] = ok(g['y1']); g['y3']['pass'] = ok(g['y3'])
    # one form for the live build: D if it is the best at every grid point for both targets, else C
    out['form'] = 'D' if all(g[t]['best'] == 'D' for g in grid for t in ('y1', 'y3')) else 'C'
    for g in grid:   # the live form's coefficients, fit on every season
        for t in ('y1c', 'y3c'):
            g[t] = g[t][out['form']]
    json.dump(out, open(OUT, 'w'), indent=1)
    print('kept', out['kept'], 'form', out['form'])


if __name__ == '__main__':
    main()
