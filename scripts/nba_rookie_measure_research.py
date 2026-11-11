#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research: which rookie-season number best orders NBA rookies by what they go on to produce.

    python3 scripts/nba_rookie_measure_research.py     # writes data/nba_rookie_measure_research.json (numpy)

Rookies, classes and targets as scripts/nba_rookie_age_research.py (1,222 rookies, 2010-11 .. 2022-23):
    fv    VORX summed over seasons +1..+3 (0 off the board): later value, wins
    fx    seasons +1..+3 minutes-weighted XPM, shrunk to -2 with 1,000 MP: later rate
Measures (rookie season):
    vorx  VORX (on raw XPM)                 rxpm  raw XPM                pxpm  the board's shrunk XPM (sxpm, k 600)
    axpm  role_sxpm + k (age - 21)          r3    a + b role_sxpm + c (age - 21) + d ln(1 + MP82)
    vage  a + b VORX + c (age - 21)
axpm, r3 and vage are fit leave one class out on the target being scored; the others need no fit.
Score: Spearman rho within each held-out class (the board sorts), mean over classes, all rookies and 500+ MP;
classes won vs VORX; held-out RMSE after a leave-one-class-out linear calibration; paired squared-error t vs VORX.
Pre-registered: the rookie board's default sort = the plain measure (vorx, rxpm, pxpm, axpm) with the highest mean
rho on fv at all minutes; a fitted measure replaces it only if it beats it in 10+ of 13 classes on fv AND fx.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_rookie_age_research as AR
import nba_xpm as XP

OUT = os.path.join(AR.ROOT, 'data', 'nba_rookie_measure_research.json')
A0 = 21


def rows():
    files = sorted(int(f[:-5]) for f in os.listdir(AR.XPM) if f.endswith('.json'))
    D = {S: json.load(open(os.path.join(AR.XPM, f'{S}.json'))) for S in files}
    F = {S: {p['id']: p for p in D[S]['players']} for S in files}
    out = []
    for S, sx, age, mp, fx, fv, pid, raw, gms in AR.load():
        p = F[S][pid]
        out.append((S, p['vorx'], raw, sx, XP.role_sxpm(p, gms), age, mp, mp * 82 / gms, fx, fv))
    return np.array(out, float)


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def loco(Xf, T, S, classes):
    p = np.zeros_like(T)
    for c in classes:
        tr, te = S != c, S == c
        b = np.linalg.lstsq(Xf[tr], T[tr], rcond=None)[0]
        p[te] = Xf[te] @ b
    return p


def main():
    R = rows()
    S, vorx, rx, px, rs, age, mp, mp82, fx, fv = R.T
    classes = sorted(set(S.astype(int)))
    one, a = np.ones_like(S), age - A0
    res = {'n': int(len(R)), 'classes': [int(c) for c in classes], 'targets': {}}
    for tn, T in (('fv', fv), ('fx', fx)):
        M = {'vorx': vorx, 'rxpm': rx, 'pxpm': px,
             'axpm': loco(np.column_stack([one, rs, a]), T, S, classes),
             'r3': loco(np.column_stack([one, rs, a, np.log1p(mp82)]), T, S, classes),
             'vage': loco(np.column_stack([one, vorx, a]), T, S, classes)}
        cal = {k: (v if k in ('axpm', 'r3', 'vage') else loco(np.column_stack([one, v]), T, S, classes)) for k, v in M.items()}
        out = {}
        for lab, m in (('all', mp >= 0), ('500', mp >= 500)):
            base = [spearman(M['vorx'][m & (S == c)], T[m & (S == c)]) for c in classes]
            e0 = (cal['vorx'] - T)[m] ** 2
            for k, v in M.items():
                rho = [spearman(v[m & (S == c)], T[m & (S == c)]) for c in classes]
                e = (cal[k] - T)[m] ** 2
                d = e - e0
                t = 0.0 if k == 'vorx' else float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
                out.setdefault(k, {})[lab] = {'rho': round(float(np.mean(rho)), 4), 'wonVsVorx': int(sum(x > y + 1e-12 for x, y in zip(rho, base))),
                                              'rmse': round(float(np.sqrt(e.mean())), 4), 'tVsVorx': round(t, 2), 'n': int(m.sum())}
        res['targets'][tn] = out
    json.dump(res, open(OUT, 'w'), indent=1)
    for tn, out in res['targets'].items():
        print(tn)
        for k, v in out.items():
            print(f"  {k:5s}  all rho {v['all']['rho']:.3f} won {v['all']['wonVsVorx']:2d}/13 rmse {v['all']['rmse']:.3f} t {v['all']['tVsVorx']:+.2f}"
                  f"  | 500+ rho {v['500']['rho']:.3f} won {v['500']['wonVsVorx']:2d}/13 rmse {v['500']['rmse']:.3f} t {v['500']['tVsVorx']:+.2f}")


if __name__ == '__main__':
    main()
