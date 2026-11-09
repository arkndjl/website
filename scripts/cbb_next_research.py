#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB next-season player value (Nov 3 2026): research for a "next" WAR column on the CBB WAR / stats tabs.

Target: next season's CBB WAR at a 31-game season, (BPM + 2) x min% / 100 x 31 x .68 x WPP (scripts/cbb_tabs.py WAR,
pace 68, replacement -2), for returners and D-I transfers who play D-I the next season (Barttorvik research seasons).
Units: player seasons y-1 -> y, walk-forward: every model is fit on target seasons before y and scored on y
(y = 2016..2026, 11 held-out seasons).

Baselines
    flat     this season's WAR held flat (scaled to 31 games)
    prior    the game model's roster prior player projection (scripts/cbb_roster.py: BPM and minutes from last line,
             class, transfer team strength, recruit rank; minutes normalised to the team's 500 with every newcomer):
             (BPM_hat + 2) x share_hat x 31 x .68 x WPP
Pre-registered forms (4, no others tried)
    M1   one-stage WAR: OLS of next WAR on the prior's inputs + this WAR (same information, value target)
    M2   M1 + age, age^2, seasons played, BPM over position mean, OBPM, usage, height
    M3   two-stage: the prior's BPM and minutes models with M2's added inputs, normalised to 500 as the prior
    M4   stack: prior's projection (WAR_hat, BPM_hat, share_hat) + M2's added inputs + this WAR
Gate: held-out RMSE below the prior, paired t (players) <= -2, wins most seasons, calibration slope .8-1.2.

In season (the live view's next season): the same target from this season's line to date, fit per season share f
(team games played / its full schedule; Barttorvik all_advgames logs) like the NBA rookie 3Y grid. Inputs to date:
minute-weighted game BPM and OBPM, share of team minutes, usage; plus last season's 3-year BPM, class, rank, age,
seasons, height (no transfer terms: next season's school isn't known). Scored leave-one-season-out against this
season's WAR pace held flat and against the same model with no in-season line (f 0).

    python3 scripts/cbb_next_research.py [--logs DIR]   -> data/cbb_next_fit.json   (DIR: {year}.json.gz Barttorvik
        all_advgames files for 2015-2025; without it the in-season grid is skipped)
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_roster as R
import gzip
from cbb_next import war, line, pxrow, POSMAP, K, NX

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cbb_next_fit.json')
REPL = -2.0
NEXT = os.path.join(HERE, 'data', 'cbb_next_2027.json')
FIRST, LAST = 2016, 2026
f = R.f


def posmeans(by):
    """year -> position -> minutes-weighted BPM mean (10%+ minute players)"""
    out = {}
    for y, rows in by.items():
        acc = defaultdict(lambda: [0.0, 0.0])
        for r in rows.values():
            m, b = f(r['min_per'], 0), f(r['bpm'])
            if m >= 10 and b is not None:
                a = acc[POSMAP.get(r['role'], 'F')]; a[0] += m * b; a[1] += m
        out[y] = {p: a[0] / a[1] for p, a in acc.items()}
    return out


def extra(p, pm):
    """M2's added inputs from last season's line p (nothing from the target season)"""
    a = f(p.get('age'), 21.0)
    b = f(p['bpm'], REPL)
    return [a - 21, (a - 21) ** 2, min(f(p.get('seasons'), 2), 6) - 2, b - pm.get(POSMAP.get(p['role'], 'F'), 0.0),
            f(p.get('obpm'), 0.0), f(p.get('usg'), 18.0) - 18, f(p.get('hti'), 78) - 78]


def ols(X, y, lam=1.0):
    X, y = np.array(X, float), np.array(y, float)
    A = X.T @ X + lam * np.eye(X.shape[1]); A[0, 0] -= lam
    return np.linalg.solve(A, X.T @ y)


def main():
    by = R.load_seasons()
    ts = R.team_strength(by)
    pm = posmeans(by)
    # every player of season y (all kinds, for the minutes normalisation), with last season's line
    rows = defaultdict(list)
    for y in sorted(by):
        if y - 1 not in by:
            continue
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            k = R.kind(r, p, h)
            x = R.xrow(k, r, h if h else p, ts, y)
            d = {'k': k, 'x': x, 'team': r['team'], 'bpm': max(-15, min(15, f(r['bpm'], REPL))), 'mp': f(r['min_per'], 0), 'pid': pid}
            d['war'] = war(f(r['bpm'], REPL), d['mp'])
            if k in ('ret', 'tr'):
                d['cur'] = war(f(p['bpm'], REPL), f(p['min_per'], 0))
                d['e'] = extra(p, pm[y - 1])
            rows[y].append(d)

    def fitkind(Q, xs):
        bw = R.wls([xs(q) for q in Q], [q['bpm'] for q in Q], [q['mp'] / 100 + 0.02 for q in Q])
        mw = R.wls([xs(q) for q in Q], [q['mp'] for q in Q], [1.0] * len(Q))
        return bw, mw

    res = defaultdict(list)          # model -> [(season, pred, actual)]
    coefs = {}
    for y in range(FIRST, LAST + 1):
        tr = [q for yy in rows if yy < y for q in rows[yy]]
        te = rows[y]
        # ---- prior (and M3: same with M2's inputs for ret/tr)
        preds = {}
        for name, use_e in (('prior', False), ('M3', True)):
            M = {}
            for k in ('ret', 'tr', 'fr', 'new', 'back'):
                Q = [q for q in tr if q['k'] == k]
                if Q:
                    xs = (lambda q: q['x'] + q['e']) if use_e and k in ('ret', 'tr') else (lambda q: q['x'])
                    M[k] = (fitkind(Q, xs), xs)
            tot = defaultdict(float)
            P = []
            for q in te:
                (bw, mw), xs = M[q['k']]
                b, m = float(np.dot(bw, xs(q))), max(0.5, float(np.dot(mw, xs(q))))
                P.append((b, m)); tot[q['team']] += m
            preds[name] = [(b, 500 * m / tot[q['team']]) for q, (b, m) in zip(te, P)]
        trr = [q for q in tr if q['k'] in ('ret', 'tr')]
        idx = [i for i, q in enumerate(te) if q['k'] in ('ret', 'tr')]
        # the prior's projection for training rows (stack M4) needs out-of-sample values: use each training season's
        # own walk-forward prior (computed when that season was the test season)
        X1 = lambda q: q['x'] + [q['cur']]
        X2 = lambda q: q['x'] + [q['cur']] + q['e']
        c1 = ols([X1(q) for q in trr], [q['war'] for q in trr])
        c2 = ols([X2(q) for q in trr], [q['war'] for q in trr])
        stk = [q for q in trr if 'pp' in q]
        X4 = lambda q: [1.0, q['pp'][0], q['pp'][1], q['pp'][2], q['cur']] + q['e']
        c4 = ols([X4(q) for q in stk], [q['war'] for q in stk]) if len(stk) > 500 else None
        for i in idx:
            q = te[i]
            b, s = preds['prior'][i]
            pw = war(b, s)
            q['pp'] = (pw, b, s / 100)
            b3, s3 = preds['M3'][i]
            out = {'flat': q['cur'], 'prior': pw, 'M1': float(np.dot(c1, X1(q))), 'M2': float(np.dot(c2, X2(q))), 'M3': war(b3, s3)}
            if c4 is not None:
                out['M4'] = float(np.dot(c4, X4(q)))
            for m, v in out.items():
                res[m].append((y, v, q['war'], q['k'], q['pid']))
        coefs[y] = {'M2': [round(float(v), 4) for v in c2]}
        print(y, len(idx), {m: round(float(np.sqrt(np.mean([(v - a) ** 2 for yy, v, a, _, _ in L if yy == y]))), 4) for m, L in res.items()})

    # ---- scoring: every model on the seasons where all models have predictions (M4 needs a stacked history)
    def key(L): return {(yy, pid): (v, a, k) for yy, v, a, k, pid in L}
    base = key(res['prior'])
    ys4 = sorted({yy for yy, *_ in res['M4']})
    summ = {}
    for m in res:
        D = key(res[m])
        for scope, ys in (('all', range(FIRST, LAST + 1)), ('m4yrs', ys4)):
            ks = [k for k in base if k in D and k[0] in ys]
            e_m = np.array([(D[k][0] - D[k][1]) ** 2 for k in ks]); e_b = np.array([(base[k][0] - base[k][1]) ** 2 for k in ks])
            d = e_m - e_b
            t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if m != 'prior' else 0.0
            per = {}
            for yy in ys:
                kk = [k for k in ks if k[0] == yy]
                if kk:
                    per[yy] = (float(np.sqrt(np.mean([(D[k][0] - D[k][1]) ** 2 for k in kk]))), float(np.sqrt(np.mean([(base[k][0] - base[k][1]) ** 2 for k in kk]))))
            sd = np.array([a - b for a, b in per.values()])
            ct = float(sd.mean() / (sd.std(ddof=1) / math.sqrt(len(sd)))) if m != 'prior' and len(sd) > 2 else 0.0
            pr = np.array([D[k][0] for k in ks]); ac = np.array([D[k][1] for k in ks])
            slope = float(np.polyfit(pr, ac, 1)[0])
            summ.setdefault(m, {})[scope] = {'n': len(ks), 'rmse': round(float(np.sqrt(np.mean(e_m))), 4), 'rmse_prior': round(float(np.sqrt(np.mean(e_b))), 4),
                                            't_players': round(t, 2), 't_seasons': round(ct, 2), 'won': sum(1 for a, b in per.values() if a < b), 'of': len(per),
                                            'slope': round(slope, 3), 'mae': round(float(np.mean(np.abs(pr - ac))), 4),
                                            'by_season': {str(k): [round(a, 4), round(b, 4)] for k, (a, b) in per.items()}}
    for m, s in summ.items():
        a = s['all']
        print(f"{m:6s} n {a['n']} rmse {a['rmse']} (prior {a['rmse_prior']}) t {a['t_players']} season-t {a['t_seasons']} won {a['won']}/{a['of']} slope {a['slope']}"
              f" | M4 yrs rmse {s['m4yrs']['rmse']} t {s['m4yrs']['t_players']} won {s['m4yrs']['won']}/{s['m4yrs']['of']}")
    out = {}
    if '--logs' in sys.argv:
        out = partial(by, sys.argv[sys.argv.index('--logs') + 1])
    # live coefficients: M2 fit on every target season through LAST (offseason / last season's frozen view)
    trr = [q for yy in rows if yy <= LAST for q in rows[yy] if q['k'] in ('ret', 'tr')]
    cfull = ols([q['x'] + [q['cur']] + q['e'] for q in trr], [q['war'] for q in trr])
    nxt = live2027(by, ts, pm, cfull)
    json.dump({'built': 'scripts/cbb_next_research.py', 'season': LAST + 1, 'war': nxt}, open(NEXT, 'w'), separators=(',', ':'))
    print(NEXT, len(nxt), 'players')
    json.dump({'built': 'scripts/cbb_next_research.py', 'target': 'next-season WAR at 31 games, (BPM + 2) x min% / 100 x 31 x .68 x .01432',
               'units': 'returners + D-I transfers who play D-I next season', 'walk_forward': [FIRST, LAST], 'forms_tried': 4,
               'summary': summ, 'M2': [round(float(v), 5) for v in cfull], 'n_fit': len(trr),
               'posmean': {str(LAST): pm[LAST]}, 'inseason': out}, open(OUT, 'w'), indent=1)
    return res, rows


GRID = (0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0)
GL = {'min': 8, 'usg': 10, 'obpm': 30, 'gbpm': 44, 'team': 47, 'pid': 51, 'muid': 6, 'date': 0}


def todate(games, f):
    """pid -> to-date line at season share f: (minute-weighted game BPM, game OBPM, usage, min% of team minutes, minutes)"""
    tg = defaultdict(list)
    for g in games:
        tg[g[GL['team']]].append((g[GL['date']], g[GL['muid']]))
    cut = {}
    for t, L in tg.items():
        L = sorted(set(L))
        n = max(1, math.ceil(f * len(L)))
        cut[t] = (set(m for _, m in L[:n]), n)
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, None])
    for g in games:
        t = g[GL['team']]
        if g[GL['muid']] not in cut[t][0] or not g[GL['min']]:
            continue
        a = acc[str(g[GL['pid']])]; m = g[GL['min']]
        a[0] += m; a[1] += m * g[GL['gbpm']]; a[2] += m * g[GL['obpm']]; a[3] += m * g[GL['usg']]; a[4] = t
    return {p: line(a[1] / a[0], a[2] / a[0], a[3] / a[0], a[0], cut[a[4]][1]) for p, a in acc.items() if a[0] > 0}


def live2027(by, ts, pm, c):
    """2025-26 line -> 2026-27 WAR (M2) for every board career with a 2025-26 D-I line, at his 2026-27 school
    (scripts/cbb_prior.json.gz: the frozen preseason board)"""
    d = json.load(gzip.open(os.path.join(HERE, 'cbb_prior.json.gz')))
    out = {}
    for car in d['careers']:
        pid, bt = str(car.get('pid') or ''), car.get('bt')
        p = by[LAST].get(pid)
        if not bt or p is None or not f(p['min_per']):
            continue
        k = 'ret' if p['team'] == bt else 'tr'
        x = R.xrow(k, {'team': bt, 'rg_lrk': p.get('rg_lrk'), 'unranked': p.get('unranked')}, p, ts, LAST + 1)
        cur = war(f(p['bpm'], REPL), f(p['min_per'], 0))
        out[pid] = round(float(np.dot(c, x + [cur] + extra(p, pm[LAST]))), 2)
    return out


def partial(by, logdir):
    pm = posmeans(by)
    data = defaultdict(dict)           # f -> season -> [(x, next WAR, to-date WAR pace)]
    for s in range(FIRST - 1, LAST):
        p = os.path.join(logdir, f'{s}.json.gz')
        if not os.path.exists(p) or s + 1 not in by:
            continue
        games = [g for g in json.load(gzip.open(p)) if g[-1] == s]
        for fr in GRID:
            td = todate(games, fr) if fr > 0 else None
            L = []
            for pid, r in by[s].items():
                q = by[s + 1].get(pid)
                if q is None or not f(r['min_per']):
                    continue
                t = td.get(pid) if td is not None else None
                if fr > 0 and t is None:
                    continue
                L.append((pxrow(r, t, by[s - 1].get(pid) if s - 1 in by else None, pm[s - 1]), war(f(q['bpm'], REPL), f(q['min_per'], 0)),
                          war(t[0], t[3]) if t else None))
            data[fr][s] = L
        print('logs', s, {fr: len(data[fr][s]) for fr in GRID})
    grid, summ = [], {}
    seasons = sorted(data[1.0])
    for fr in GRID:
        e, e0, ef, P, A = defaultdict(list), defaultdict(list), defaultdict(list), [], []
        for s in seasons:
            tr = [q for ss in seasons if ss != s for q in data[fr][ss]]
            c = ols([q[0] for q in tr], [q[1] for q in tr])
            if fr > 0:
                tr0 = [q for ss in seasons if ss != s for q in data[0.0][ss]]
                c0 = ols([q[0][:NX] for q in tr0], [q[1] for q in tr0])
            for x, y, w in data[fr][s]:
                v = float(np.dot(c, x)); P.append(v); A.append(y)
                e[s].append((v - y) ** 2)
                if fr > 0:
                    e0[s].append((float(np.dot(c0, x[:NX])) - y) ** 2)
                    ef[s].append((w - y) ** 2)          # to-date WAR pace held flat (min% is a rate: WAR at 31 games)
        allc = ols([q[0] for s in seasons for q in data[fr][s]], [q[1] for s in seasons for q in data[fr][s]])
        grid.append({'f': fr, 'c': [round(float(v), 5) for v in allc]})
        row = {'n': len(P), 'rmse': round(float(np.sqrt(np.mean([v for s in e for v in e[s]]))), 4), 'slope': round(float(np.polyfit(P, A, 1)[0]), 3)}
        for nm, E in (('f0', e0), ('flat', ef)):
            if not E:
                continue
            d = np.array([a - b for s in seasons for a, b in zip(e[s], E[s])])
            row[nm] = {'rmse': round(float(np.sqrt(np.mean([v for s in E for v in E[s]]))), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
                       'won': sum(1 for s in seasons if np.mean(e[s]) < np.mean(E[s])), 'of': len(seasons)}
        summ[str(fr)] = row
        print('f', fr, row)
    return {'seasons': [seasons[0], seasons[-1]], 'grid': grid, 'summary': summ}


if __name__ == '__main__':
    main()
