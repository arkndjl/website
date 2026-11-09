#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research + fit: the rookie 3Y as XPM given he plays, the same change as scripts/nba_proj3y_play_research.py.

The rookie 3Y (scripts/nba_rookie_proj_research.py) is fit to seasons +1..+3 minutes-weighted XPM with 1,000 minutes
of -2 added to every rookie. Here the target is the minutes-weighted XPM over those seasons for rookies with minutes
in them, weighted by those minutes; same form (XPM, age, ln(1 + MP82)), same season-share grid, simulated partial
seasons and draws, leave one class out.

    python3 scripts/nba_rookie_proj_play_research.py [--write]   # --write: 'cp' per grid point in data/nba_rookie_proj_fit.json

Test (stated before the run): actual = minutes-weighted XPM over seasons +1..+3, rookies with 1,000+ minutes there,
scores weighted by those minutes, classes 2010-2023. At every season share f:
    bias    mean (prediction - actual) within +/-.25 in each bin (below 0, 0-2, 2-4, 4+) of the new prediction and of
            the board XPM; a bin with fewer than 30 rookies is reported and does not bind
    rmse    no worse than the shrunk-target fit against the same actual (paired t <= 0, rookies as units)
Result: passes at every f (season end RMSE 1.304 vs 1.509, t -5.7; bias -.09 below 0, +.06 at 0-2). The 2-4 bin
holds 0-16 rookies and still runs .5 to 1.2 low (the shrunk fit 1.9 to 2.8 low).
Run after nba_rookie_proj_research.py (it rewrites the fit file without 'cp'; scripts/rookies.py then reads 'c').
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_rookie_age_research as AR
import nba_rookie_proj_research as RP

MINW, TOL, MINN = 1000.0, 0.25, 30
BINS = ((-99, 0), (0, 2), (2, 4), (4, 99))


def future(rows):
    """(minutes, minutes-weighted XPM) over seasons +1..+3 for each row, as AR.load counts them"""
    F = {}
    for f in os.listdir(AR.XPM):
        if f.endswith('.json'):
            F[int(f[:-5])] = {p['id']: p for p in json.load(open(os.path.join(AR.XPM, f)))['players']}
    w, a = [], []
    for r in rows:
        fut = [F[r[0] + k].get(r[6]) for k in (1, 2, 3)]
        fut = [f for f in fut if f and f.get('xpm') is not None]
        mp = sum(f['mp'] for f in fut)
        w.append(mp); a.append(sum(f['xpm'] * f['mp'] for f in fut) / mp if mp else np.nan)
    return np.array(w, float), np.array(a, float)


def main():
    rows = AR.load()
    S, sx, age, mp, fx = (np.array([r[i] for r in rows], float) for i in (0, 1, 2, 3, 4))
    raw = np.array([r[7] for r in rows], float); gm = np.array([r[8] for r in rows], float)
    w0, a0 = future(rows)
    assert np.allclose((a0 * w0 - 2000)[w0 > 0] / (w0 + 1000)[w0 > 0], fx[w0 > 0])
    mp82 = mp * 82 / gm
    rng = np.random.default_rng(20261103)
    classes = sorted(set(S.astype(int)))
    n0, grid = len(rows), []
    for f in RP.FS:
        n = RP.DRAWS if f < 1 else 1
        if f < 1:                                        # the same draws as nba_rookie_proj_research.py
            Sd, ad, fd = (np.repeat(v, n) for v in (S, age, fx))
            mpf = np.maximum(np.repeat(mp, n) * f, 1.0)
            rawf = np.repeat(raw, n) + rng.normal(0, 1, len(mpf)) * np.sqrt(RP.S2 * np.maximum(1 / mpf - 1 / np.maximum(np.repeat(mp, n), 1), 0))
            lm = np.log1p(np.repeat(mp82, n)) + rng.normal(0, 0.25 * math.sqrt((1 - f) / f), len(mpf))
            m82 = np.expm1(np.maximum(lm, 0))
            xd = RP.board_x(rawf, mpf, m82); lm = np.log1p(m82)
        else:
            # the board's old shrink (nba_xpm.role_sxpm, what scripts/rookies.py feeds the fit), not the file's sxpm
            Sd, ad, fd, xd, lm = S, age, fx, RP.board_x(raw, mp, mp82), np.log1p(mp82)
        w, act = np.repeat(w0, n), np.repeat(a0, n)
        A = RP.X('proj', xd, ad, lm)
        po, pn = np.zeros_like(fd), np.zeros_like(fd)
        for c in classes:
            tr, te = Sd != c, Sd == c
            po[te] = A[te] @ np.linalg.lstsq(A[tr], fd[tr], rcond=None)[0]
            tw = tr & (w > 0); s = np.sqrt(w[tw])
            pn[te] = A[te] @ np.linalg.lstsq(A[tw] * s[:, None], act[tw] * s, rcond=None)[0]
        full = w > 0; s = np.sqrt(w[full])
        coef = np.linalg.lstsq(A[full] * s[:, None], act[full] * s, rcond=None)[0]
        sc = w >= MINW; ws = w[sc]
        eo, en = (po - act)[sc], (pn - act)[sc]
        d = np.where(sc, w * ((pn - act) ** 2 - (po - act) ** 2), 0.0).reshape(n0, -1).mean(1)[(w0 >= MINW)]
        o = {'f': f, 'n': int(sc.sum() // n), 'c': [round(float(v), 4) for v in coef],
             'rmse': {'shrunk': round(float(np.sqrt(np.average(eo ** 2, weights=ws))), 4), 'play': round(float(np.sqrt(np.average(en ** 2, weights=ws))), 4)},
             't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
             'slope': round(float(np.polyfit(pn[sc], act[sc], 1, w=np.sqrt(ws))[0]), 3)}
        ok = o['t'] <= 0
        for name, key in (('byPred', pn), ('byXpm', xd)):
            b = []
            for lo, hi in BINS:
                m = (key[sc] >= lo) & (key[sc] < hi)
                cnt = int(m.sum() // n)
                b.append({'n': cnt, 'play': round(float(np.average(en[m], weights=ws[m])), 3) if m.any() else None,
                          'shrunk': round(float(np.average(eo[m], weights=ws[m])), 3) if m.any() else None})
                if cnt >= MINN and abs(b[-1]['play']) > TOL: ok = False
            o[name] = b
        o['pass'] = bool(ok)
        grid.append(o)
        print(json.dumps(o), flush=True)
    kept = all(g['pass'] for g in grid)
    print('kept', kept)
    if '--write' in sys.argv:
        fit = json.load(open(RP.OUT))
        fit['play'] = {'kept': kept, 'minW': MINW, 'tol': TOL, 'minN': MINN, 'bins': [list(b) for b in BINS],
                       'res': {str(g['f']): {k: v for k, v in g.items() if k not in ('f', 'c')} for g in grid}}
        for g, gg in zip(fit['grid'], grid):
            assert g['f'] == gg['f']
            if kept: g['cp'] = gg['c']
            else: g.pop('cp', None)
        json.dump(fit, open(RP.OUT, 'w'), indent=1)
        print('wrote', RP.OUT)


if __name__ == '__main__':
    main()
