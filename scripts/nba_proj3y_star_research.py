#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research (Nov 4 2026): the shipped 3Y / 1Y (form F4, scripts/nba_proj3y_research.py) runs low on stars (proj 4+:
3.80 held out vs 4.44 realized over three seasons). Pre-registered (/mnt/project-files/fv/sweep-nov04/nba/prereg.md)
forms, each F4 plus extra terms, on the same harness (leave one season out with a buffer, simulated partial seasons at
each season share f, same draws for every form):

    H1 hinge     + max(0, proj - 3)
    H2 Marcel    + d1 + d2, dj = (XPM in S-j + 2) x MP / (MP + 1000), 0 off the board
    H3 reliab.   + proj x (ln(1 + C3) - 8), C3 = minutes in S (to date), S-1, S-2
    H4 all       H1 + H2 + H3

Gate vs F4: t <= -2 on y1 and y3y at every f (form p = the largest of those 12 two-sided p), Holm across the 4 at .05;
wins most seasons on y3y at f 1; still beats aged and cal (t <= -2, every f); slope .8-1.2; proj-4+ |bias| smaller
than F4 at every f on both targets; top-25 by proj per season (y3y, f 1) MSE not worse.

    python3 scripts/nba_proj3y_star_research.py [--write]    # --write: the pick's coefficients into data/nba_proj3y_fit.json

Result (Nov 4 2026): H1, H3, H4 pass Holm vs F4 (worst-of-12 t -2.40 / -2.82 / -2.67); H3 fails the top-4 bias and
top-25 checks; H2 fails (t +1.23 on y1 at f 1). Pick H4 (lowest RMSE): y3y at season end .8325 vs F4 .8428 (t -3.53,
11/12 seasons), y1 .8517 vs .8564 (t -2.67); proj 4+ y3y 4.27 vs actual 4.44 (F4 3.80); top-25 MSE 2.01 vs 2.11.
Run after nba_proj3y_research.py (which rewrites the fit with F4).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_proj3y_research as R
import nba_proj as P

FS = R.FS
HC = 3.0                            # hinge knot, fixed before the run
FORMS = ('F4', 'H1', 'H2', 'H3', 'H4')
NEW = FORMS[1:]


def extra(form, proj, d1, d2, lc):
    h = np.maximum(0, proj - HC)
    rel = proj * (lc - 8)
    return {'F4': [], 'H1': [h], 'H2': [d1, d2], 'H3': [rel], 'H4': [h, d1, d2, rel]}[form]


def design(form, proj, prior, age, lm, d1, d2, lc):
    return np.column_stack([R.design('F4', proj, prior, age, lm)] + extra(form, proj, d1, d2, lc))


def add_history(rows):
    by = {}
    for s in range(2010, 2027):
        d = P.load(s)
        if d: by[s] = {p['id']: p for p in d['players'] if p.get('xpm') is not None and not p.get('pr')}
    for r in rows:
        for j in (1, 2):
            p = by.get(r['S'] - j, {}).get(r['id'])
            r[f'x{j}'], r[f'm{j}'] = (p['xpm'], p['mp']) if p else (0.0, 0.0)
    return rows


def norm_p(t):
    return math.erfc(abs(t) / math.sqrt(2))


def evaluate(rows, f, rng):
    n, proj, prior, age, lm, M = R.inputs(rows, f, rng)
    rep = lambda k: np.repeat(np.array([r[k] for r in rows], float), n)
    S, ids = rep('S'), np.repeat([r['id'] for r in rows], n)
    d1 = (rep('x1') + 2) * rep('m1') / (rep('m1') + 1000)
    d2 = (rep('x2') + 2) * rep('m2') / (rep('m2') + 1000)
    # this season's minutes to date: the same draws as R.inputs (inputs_with_mp)
    lc = np.log1p(MPF[0] + rep('m1') + rep('m2'))
    AG = np.repeat(np.array([r['ag'] for r in rows], float), n, axis=0)
    Y = np.repeat(np.array([r['y'] for r in rows], float), n, axis=0)
    y3y = np.repeat(np.array([np.nan if r['y3y'] is None else r['y3y'] for r in rows]), n)
    tg = {'y1': (Y[:, 0], proj + AG[:, 0], 1), 'y3y': (y3y, proj + AG.mean(1), 3)}
    res, coefs = {}, {}
    for tn, (T, aged, buf) in tg.items():
        ok = ~np.isnan(T)
        if tn == 'y3y': ok &= S <= 2023
        seasons = sorted(set(S[ok].astype(int)))
        P_ = {'aged': aged.copy()}
        p = np.zeros_like(T)
        for c in seasons:
            tr = ok & (np.abs(S - c) > buf); te = ok & (S == c)
            b = np.linalg.lstsq(R.design('cal', aged[tr], aged[tr], aged[tr], aged[tr]), T[tr], rcond=None)[0]
            p[te] = R.design('cal', aged[te], aged[te], aged[te], aged[te]) @ b
        P_['cal'] = p
        for form in FORMS:
            p = np.zeros_like(T)
            X = design(form, proj, prior, age, lm, d1, d2, lc)
            for c in seasons:
                tr = ok & (np.abs(S - c) > buf); te = ok & (S == c)
                b = np.linalg.lstsq(X[tr], T[tr], rcond=None)[0]
                p[te] = X[te] @ b
            P_[form] = p
            coefs[(tn, form)] = np.linalg.lstsq(X[ok], T[ok], rcond=None)[0]
        E = {k: (v - T) ** 2 for k, v in P_.items()}
        out = {'n': int(ok.sum() // n), 'rmse': {k: round(float(np.sqrt(e[ok].mean())), 4) for k, e in E.items()}}
        top = ok & (proj >= 4)
        out['top4'] = {k: round(float(v[top].mean()), 3) for k, v in P_.items()} | {'actual': round(float(T[top].mean()), 3)}
        # top 25 by proj in each held-out season (f = 1 only meaningful; reported at every f)
        t25 = np.zeros_like(ok)
        for c in seasons:
            idx = np.where(ok & (S == c))[0]
            t25[idx[np.argsort(-proj[idx])[:25 * n]]] = True
        out['top25mse'] = {k: round(float(E[k][t25].mean()), 4) for k in FORMS}
        for form in FORMS:
            o = {'slope': round(float(np.polyfit(P_[form][ok], T[ok], 1)[0]), 3)}
            for base in ('aged', 'cal') + (('F4',) if form != 'F4' else ()):
                d = (E[form] - E[base])[ok]
                won = sum(np.sqrt(E[form][ok & (S == c)].mean()) < np.sqrt(E[base][ok & (S == c)].mean()) for c in seasons)
                o[base] = {'t': round(R.tstat(d, ids[ok]), 2), 'won': int(won), 'of': len(seasons)}
            out[form] = o
        res[tn] = out
    return res, coefs


MPF = [None]


def inputs_with_mp(rows, f, rng):
    """R.inputs plus this season's simulated minutes (for C3), from the same draws"""
    state = rng.bit_generator.state
    n = R.DRAWS if f < 1 else 1
    mps = []
    for r in rows:
        for _ in range(n):
            if f < 1:
                cg = max(1, round(r['gp'] * f))
                mp = max(1.0, r['mp'] * cg / r['gp'] * math.exp(rng.normal(0, 0.25 * math.sqrt((1 - f) / f))))
                rng.normal()
            else:
                mp = r['mp']
            mps.append(mp)
    rng.bit_generator.state = state
    MPF[0] = np.array(mps)


def main():
    rows = add_history(R.load())
    rng = np.random.default_rng(20261103)
    grid = []
    for f in FS:
        inputs_with_mp(rows, f, rng)
        res, coefs = evaluate(rows, f, rng)
        grid.append({'f': f, 'res': res, 'coefs': {f'{tn}|{a}': [round(float(v), 4) for v in coefs[(tn, a)]] for tn in ('y1', 'y3y') for a in FORMS}})
        print(f, json.dumps({tn: {k: res[tn][k] for k in ('rmse', 'top4', 'top25mse')} | {a: res[tn][a] for a in NEW} for tn in res}), flush=True)
    # gate
    verdict = {}
    for a in NEW:
        ts = [g['res'][tn][a]['F4']['t'] for g in grid for tn in ('y1', 'y3y')]
        pmax = max(norm_p(t) if t < 0 else 1.0 for t in ts)
        g1 = grid[-1]['res']['y3y']
        v = {'tmax': max(ts), 'p': pmax,
             'won': g1[a]['F4']['won'] * 2 > g1[a]['F4']['of'],
             'base': all(g['res'][tn][a][b]['t'] <= -2 for g in grid for tn in ('y1', 'y3y') for b in ('aged', 'cal')),
             'slope': all(0.8 <= g['res'][tn][a]['slope'] <= 1.2 for g in grid for tn in ('y1', 'y3y')),
             'top4': all(abs(g['res'][tn]['top4'][a] - g['res'][tn]['top4']['actual']) < abs(g['res'][tn]['top4']['F4'] - g['res'][tn]['top4']['actual']) for g in grid for tn in ('y1', 'y3y')),
             'top25': g1['top25mse'][a] <= g1['top25mse']['F4']}
        verdict[a] = v
    order = sorted(NEW, key=lambda a: verdict[a]['p'])
    for i, a in enumerate(order):                       # Holm step-down
        verdict[a]['holm'] = verdict[a]['p'] <= 0.05 / (len(NEW) - i) and all(verdict[b]['holm'] for b in order[:i])
    passed = [a for a in NEW if all(verdict[a][k] for k in ('holm', 'won', 'base', 'slope', 'top4', 'top25'))]
    score = lambda a: sum(g['res'][tn]['rmse'][a] for g in grid for tn in ('y1', 'y3y'))
    pick = min(passed, key=score) if passed else None
    print(json.dumps(verdict, indent=1)); print('pick', pick)
    out = os.path.join('/mnt/project-files/fv/sweep-nov04/nba/', 'star_research.json')
    try:
        json.dump({'grid': grid, 'verdict': verdict, 'pick': pick, 'HC': HC}, open(out, 'w'), indent=1)
    except OSError as e:
        print('not saved', e)
    if pick and '--write' in sys.argv:
        fit = json.load(open(R.OUT))
        fit['form'] = pick; fit['HC'] = HC
        fit['starResearch'] = {'verdict': verdict, 'pick': pick,
                               'rmse': {str(g['f']): {tn: g['res'][tn]['rmse'] for tn in ('y1', 'y3y')} for g in grid},
                               'top4': {str(g['f']): {tn: g['res'][tn]['top4'] for tn in ('y1', 'y3y')} for g in grid}}
        for g, gg in zip(fit['grid'], grid):
            assert g['f'] == gg['f']
            g['c'] = {tn: gg['coefs'][f'{tn}|{pick}'] for tn in ('y1', 'y3y')}
        json.dump(fit, open(R.OUT, 'w'), indent=1)
        print('wrote', R.OUT)


if __name__ == '__main__':
    main()
