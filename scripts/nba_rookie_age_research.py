#!/usr/bin/env python3
"""Research (Nov 3 2026): an age-adjusted XPM for the NBA rookie board, built from data and kept only if it predicts
a rookie's later XPM better than his raw (shrunk) rookie XPM.

    python3 scripts/nba_rookie_age_research.py     # writes data/nba_rookie_age_research.json (numpy)

Rookies = the rookie board's rows (scripts/rookies.py: first season on the XPM board), classes 2010-11 .. 2022-23
(three later seasons on the board). Predictor x = the board's XPM (sxpm, shrunk by minutes, k 300); age = bbref
season age (Feb 1).
Targets, seasons +1..+3:
    fx    minutes-weighted XPM, shrunk toward -2 (the rookie prior) with 1,000 minutes, so washouts sit near -2
    fv    VORX summed (0 in a season off the board)
Forms (fit leave-one-class-out, scored on the held-out class):
    raw     T ~ a + b x
    lin     T ~ a + b x + c age          ->  aXPM = x + (c / b)(age - 21)
    quad    T ~ a + b x + c age + d age^2
    mp      T ~ a + b x + c age + e log(1 + MP)
    curve   x + the delta-method aging curve (nba_games.aging_curve, pairs before the class; 2014's before 2014) summed over 3 seasons
Score: RMSE and Spearman rho on the held-out class, minutes 0+ and 500+; paired squared-error t by player vs raw.
Kept (pre-registered): RMSE lower than raw on fx AND fv, paired t <= -2 on fx, Spearman higher in most classes.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import nba_games as N

XPM = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
OUT = os.path.join(ROOT, 'data', 'nba_rookie_age_research.json')
A0 = 21


def load():
    files = sorted(int(f[:-5]) for f in os.listdir(XPM) if f.endswith('.json'))
    D = {S: json.load(open(os.path.join(XPM, f'{S}.json'))) for S in files}
    F = {S: {p['id']: p for p in D[S]['players']} for S in files}
    draft = {}
    for yr, lst in json.load(open(os.path.join(HERE, 'nba_draft.json'))).items():
        for pk, bid, n, tm in lst:
            draft[bid] = (int(yr), pk)
    seen, rows = set(), []
    for S in files:
        for pid, p in F[S].items():
            first = pid not in seen
            seen.add(pid)
            if not first:
                continue
            dr = draft.get(pid)
            if S == files[0] and not (dr and dr[0] == S - 1):
                continue
            if not dr and (p.get('age') or 0) > 27:
                continue
            if dr and dr[0] > S - 1:
                continue
            if S + 3 > 2026 or not p.get('age') or p.get('sxpm') is None:
                continue
            fut = [F[S + k].get(pid) for k in (1, 2, 3)]
            mp = sum(f['mp'] for f in fut if f and f.get('xpm') is not None)
            num = sum(f['xpm'] * f['mp'] for f in fut if f and f.get('xpm') is not None)
            fx = (num - 2.0 * 1000) / (mp + 1000)
            fv = sum(f['vorx'] for f in fut if f and f.get('vorx') is not None)
            rows.append((S, p['sxpm'], p['age'], p['mp'], fx, fv, pid, p['xpm'], D[S]['games']))
    return rows


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def design(form, x, age, mp):
    a = age - A0
    cols = {'raw': [x], 'lin': [x, a], 'quad': [x, a, a * a], 'mp': [x, a, np.log1p(mp)]}[form]
    return np.column_stack([np.ones_like(x)] + cols)


def main():
    R = np.array([r[:6] for r in load()], float)
    S, x, age, mp, fx, fv = R.T
    classes = sorted(set(S.astype(int)))
    out = {'n': int(len(R)), 'classes': [int(c) for c in classes], 'ageMean': float(age.mean()), 'forms': {}}
    preds = {}
    for form in ('raw', 'lin', 'quad', 'mp', 'curve'):
        for tn, T in (('fx', fx), ('fv', fv)):
            p = np.zeros_like(T)
            for c in classes:
                tr, te = S != c, S == c
                if form == 'curve':
                    cv = N.aging_curve(c) or N.aging_curve(2014)     # the first classes have too few pairs before them
                    g = np.array([sum(cv(a + k) for k in (1, 2, 3)) for a in age[te]])
                    z = x[te] + g                                   # then calibrated like raw on the training classes
                    gtr = np.array([sum(cv(a + k) for k in (1, 2, 3)) for a in age[tr]])
                    X = np.column_stack([np.ones(tr.sum()), x[tr] + gtr])
                    b = np.linalg.lstsq(X, T[tr], rcond=None)[0]
                    p[te] = b[0] + b[1] * z
                else:
                    X = design(form, x[tr], age[tr], mp[tr])
                    b = np.linalg.lstsq(X, T[tr], rcond=None)[0]
                    p[te] = design(form, x[te], age[te], mp[te]) @ b
            preds[(form, tn)] = p
    for form in ('raw', 'lin', 'quad', 'mp', 'curve'):
        f = {}
        for tn, T in (('fx', fx), ('fv', fv)):
            p, p0 = preds[(form, tn)], preds[('raw', tn)]
            for lab, m in (('all', mp >= 0), ('500', mp >= 500)):
                e, e0 = (p - T) ** 2, (p0 - T) ** 2
                d = (e - e0)[m]
                t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if form != 'raw' else 0.0
                rho = [spearman(p[m & (S == c)], T[m & (S == c)]) for c in classes if (m & (S == c)).sum() > 5]
                rho0 = [spearman(p0[m & (S == c)], T[m & (S == c)]) for c in classes if (m & (S == c)).sum() > 5]
                f[f'{tn}_{lab}'] = {'rmse': round(float(np.sqrt(e[m].mean())), 4), 'rmseRaw': round(float(np.sqrt(e0[m].mean())), 4),
                                    't': round(t, 2), 'rho': round(float(np.mean(rho)), 4), 'rhoRaw': round(float(np.mean(rho0)), 4),
                                    'rhoClassesWon': int(sum(a > b + 1e-12 for a, b in zip(rho, rho0))), 'nClasses': len(rho)}
        out['forms'][form] = f
    # full-sample line for the board (fx target): aXPM = x + k (age - A0), k = c / b
    X = design('lin', x, age, mp)
    b = np.linalg.lstsq(X, fx, rcond=None)[0]
    kb = []
    for c in classes:                                   # stability of k across held-out fits
        tr = S != c
        bb = np.linalg.lstsq(design('lin', x[tr], age[tr], mp[tr]), fx[tr], rcond=None)[0]
        kb.append(bb[2] / bb[1])
    out['fit'] = {'a': round(float(b[0]), 4), 'b': round(float(b[1]), 4), 'c': round(float(b[2]), 4),
                  'k': round(float(b[2] / b[1]), 3), 'kLoco': [round(float(min(kb)), 3), round(float(max(kb)), 3)], 'A0': A0}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
