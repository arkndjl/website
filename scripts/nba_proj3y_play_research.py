#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research + fit: the 1Y / 3Y XPM as XPM given he plays (the first half of a two-part projection).

The shipped targets (scripts/nba_proj3y_research.py) add 500 / 1,000 minutes of -2 to every player, so the column sits
below XPM for everyone who plays (XPM 6+ with 1,500 minutes: the next three seasons 6.68, the target 5.47). Here the
target is the minutes-weighted XPM over the window on rows with minutes in it, weighted by those minutes; the form is
the live one (H4, scripts/nba_proj3y_star_research.py), on the same season-share grid, the same simulated partial
seasons and draws, leave one season out with the same buffer (1 season for 1Y, 3 for 3Y).

    python3 scripts/nba_proj3y_play_research.py [--write]   # --write: coefficients into data/nba_proj3y_fit.json ('cp')

Test (stated before the run): actual = minutes-weighted XPM over S+1 (1Y, S 2012-2025) and S+1..S+3 (3Y, S 2012-2023),
players with 1,000+ minutes in the window, every score weighted by those minutes. At every season share f, both windows:
    bias    mean (prediction - actual) within +/-.25 in each bin (below 0, 0-2, 2-4, 4+), bins taken on the new
            prediction and again on XPM (proj)
    rmse    no worse than the shrunk-target H4 against the same actual: paired t <= 0 on weighted squared error,
            players as units
Ships only if both hold everywhere.

Refit order: nba_proj3y_research.py, nba_proj3y_star_research.py --write, then this with --write (the first rewrites
the fit file without 'cp' and nba_proj.py falls back to the shrunk coefficients).

Result: passes at every f. Season end, 3Y: RMSE 1.125 vs 1.344 for the shrunk target (t -7.8, 12/12 seasons), bias by
prediction bin -.07 / +.05 / -.22 / .00 (shrunk -.49 / -.70 / -1.21 / -1.09); 1Y 1.138 vs 1.474 (t -9.9, 14/14),
bias -.14 / -.04 / -.08 / -.08 (shrunk -.51 / -.93 / -1.37 / -1.85). Every f and bin in data/nba_proj3y_fit.json 'play'.
"""
import json
import sys

import numpy as np

import nba_proj3y_research as R
import nba_proj3y_star_research as SR

FS = R.FS
FORM = 'H4'
MINW = 1000.0
BINS = ((-99, 0), (0, 2), (2, 4), (4, 99))
TOL = 0.25


def wfit(X, y, w):
    s = np.sqrt(w)
    return np.linalg.lstsq(X * s[:, None], y * s, rcond=None)[0]


def evaluate(rows, f, rng):
    n, proj, prior, age, lm, M = R.inputs(rows, f, rng)
    rep = lambda k: np.repeat(np.array([r[k] for r in rows], float), n)
    S, ids = rep('S'), np.repeat([r['id'] for r in rows], n)
    d1 = (rep('x1') + 2) * rep('m1') / (rep('m1') + 1000)
    d2 = (rep('x2') + 2) * rep('m2') / (rep('m2') + 1000)
    lc = np.log1p(SR.MPF[0] + rep('m1') + rep('m2'))
    X = SR.design(FORM, proj, prior, age, lm, d1, d2, lc)
    FM = np.repeat(np.array([r['fmp'] for r in rows], float), n, axis=0)
    FX = np.repeat(np.array([r['fx'] for r in rows], float), n, axis=0)
    Y = np.repeat(np.array([r['y'] for r in rows], float), n, axis=0)
    y3y = np.repeat(np.array([np.nan if r['y3y'] is None else r['y3y'] for r in rows]), n)
    w3 = FM.sum(1)
    a3 = np.where(w3 > 0, (FX * FM).sum(1) / np.maximum(w3, 1e-9), np.nan)
    tg = {'y1': (Y[:, 0], np.where(FM[:, 0] > 0, FX[:, 0], np.nan), FM[:, 0], 1, 2025),
          'y3y': (y3y, a3, w3, 3, 2023)}
    res, coefs = {}, {}
    for tn, (Told, act, w, buf, last) in tg.items():
        ok = S <= last
        seasons = sorted(set(S[ok].astype(int)))
        po, pn = np.zeros_like(act), np.zeros_like(act)
        for c in seasons:
            tr = ok & (np.abs(S - c) > buf); te = ok & (S == c)
            po[te] = X[te] @ np.linalg.lstsq(X[tr], Told[tr], rcond=None)[0]
            tw = tr & (w > 0)
            pn[te] = X[te] @ wfit(X[tw], act[tw], w[tw])
        full = ok & (w > 0)
        coefs[tn] = wfit(X[full], act[full], w[full])
        sc = ok & (w >= MINW)
        ws = w[sc]
        eo, en = (po - act)[sc], (pn - act)[sc]
        out = {'n': int(sc.sum() // n) if f < 1 else int(sc.sum()), 'seasons': [int(seasons[0]), int(seasons[-1])],
               'rmse': {'shrunk': round(float(np.sqrt(np.average(eo ** 2, weights=ws))), 4),
                        'play': round(float(np.sqrt(np.average(en ** 2, weights=ws))), 4)},
               't': round(R.tstat(ws * (en ** 2 - eo ** 2), ids[sc]), 2),
               'won': int(sum(np.average((pn - act)[sc & (S == c)] ** 2, weights=w[sc & (S == c)]) <
                              np.average((po - act)[sc & (S == c)] ** 2, weights=w[sc & (S == c)]) for c in seasons)),
               'of': len(seasons),
               'slope': round(float(np.polyfit(pn[sc], act[sc], 1, w=np.sqrt(ws))[0]), 3)}
        for name, key in (('byPred', pn), ('byProj', proj)):
            b = []
            for lo, hi in BINS:
                m = (key[sc] >= lo) & (key[sc] < hi)
                b.append({'bin': [lo, hi], 'n': int(m.sum() // n) if f < 1 else int(m.sum()),
                          'actual': round(float(np.average(act[sc][m], weights=ws[m])), 3) if m.any() else None,
                          'play': round(float(np.average(en[m], weights=ws[m])), 3) if m.any() else None,
                          'shrunk': round(float(np.average(eo[m], weights=ws[m])), 3) if m.any() else None})
            out[name] = b
        out['pass'] = bool(out['t'] <= 0 and all(b['play'] is None or abs(b['play']) <= TOL for k in ('byPred', 'byProj') for b in out[k]))
        res[tn] = out
    return res, coefs


def main():
    rows = SR.add_history(R.load())
    rng = np.random.default_rng(20261103)
    grid = []
    for f in FS:
        SR.inputs_with_mp(rows, f, rng)
        res, coefs = evaluate(rows, f, rng)
        grid.append({'f': f, 'res': res, 'c': {tn: [round(float(v), 4) for v in coefs[tn]] for tn in ('y1', 'y3y')}})
        print(f, json.dumps(res), flush=True)
    kept = all(g['res'][tn]['pass'] for g in grid for tn in ('y1', 'y3y'))
    print('kept', kept)
    if '--write' in sys.argv:
        fit = json.load(open(R.OUT))
        assert fit.get('form') == FORM, 'run nba_proj3y_star_research.py --write first'
        fit['play'] = {'kept': kept, 'form': FORM, 'minW': MINW, 'tol': TOL,
                       'note': 'cp: the same form fit to the minutes-weighted XPM over the window on rows with minutes, weighted by '
                               'them (XPM given he plays); scored on 1,000+ minutes in the window against the shrunk-target fit',
                       'bins': [list(b) for b in BINS],
                       'res': {str(g['f']): {tn: {k: v for k, v in o.items() if k not in ('byPred', 'byProj')} |
                                             {k: [b['play'] for b in o[k]] for k in ('byPred', 'byProj')}
                                             for tn, o in g['res'].items()} for g in grid}}
        for g, gg in zip(fit['grid'], grid):
            assert g['f'] == gg['f']
            if kept: g['cp'] = gg['c']
            else: g.pop('cp', None)
        json.dump(fit, open(R.OUT, 'w'), indent=1)
        print('wrote', R.OUT)


if __name__ == '__main__':
    main()
