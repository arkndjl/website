#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research (Nov 28 2026): G League xVORX and xXPM run high against what happened. Does a recalibration fit on earlier
seasons fix them held out?

    python3 scripts/research/gleague_cal_nov28/test.py     -> research/gleague_cal.json, data/gleague_cal.json (live)

Rows: static/data/gleague-past.json, each past season's board as it read that season (xVORX and xXPM fit walk forward on
the seasons through s-3), with what happened: VORX per season over the next three (o3) and XPM over his NBA minutes in
them (ox). Pre-registered forms, each fit for test season s on the rows of seasons through s-3 only (their outcomes
were known when season s ended):
    offset   y = x + c
    linear   y = a + b x
Scores: xVORX squared error a row; xXPM squared error a row weighted by his NBA minutes the next season (o1, the
only minutes on the row; the live fit weights by three seasons' minutes), and unweighted as a check.
Gate: a form ships when it beats the raw value with paired t <= -2 (rows) and wins most test seasons; linear is taken
over offset only if it beats offset at t <= -2 too."""
import json
import math
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PAST = os.path.join(ROOT, 'static', 'data', 'gleague-past.json')
OUT = os.path.join(ROOT, 'research', 'gleague_cal.json')
LIVE = os.path.join(ROOT, 'data', 'gleague_cal.json')       # read by scripts/gleague_callup.py build()


def wfit(x, y, w, form):
    x, y, w = map(np.asarray, (x, y, w))
    if form == 'offset':
        return 1.0, float(np.sum(w * (y - x)) / np.sum(w))
    W = np.sum(w); mx, my = np.sum(w * x) / W, np.sum(w * y) / W
    b = float(np.sum(w * (x - mx) * (y - my)) / np.sum(w * (x - mx) ** 2))
    return b, float(my - b * mx)


def tstat(d, w):
    d, w = np.asarray(d), np.asarray(w)
    m = np.sum(w * d) / np.sum(w)
    n_eff = np.sum(w) ** 2 / np.sum(w ** 2)
    sd = math.sqrt(np.sum(w * (d - m) ** 2) / np.sum(w))
    return float(m / (sd / math.sqrt(n_eff))) if sd else 0.0


def run(rows, xk, yk, wk):
    seasons = sorted({r['s'] for r in rows})
    test = [s for s in seasons if len([t for t in seasons if t <= s - 3]) >= 3]
    err = {k: [] for k in ('raw', 'offset', 'linear')}; W = []; S = []; coef = {}
    for s in test:
        tr = [r for r in rows if r['s'] <= s - 3]; te = [r for r in rows if r['s'] == s]
        if not te: continue
        fits = {f: wfit([r[xk] for r in tr], [r[yk] for r in tr], [wk(r) for r in tr], f) for f in ('offset', 'linear')}
        coef[s] = {f: [round(b, 4), round(a, 4)] for f, (b, a) in fits.items()}
        for r in te:
            err['raw'].append((r[yk] - r[xk]) ** 2)
            for f, (b, a) in fits.items():
                err[f].append((r[yk] - (a + b * r[xk])) ** 2)
            W.append(wk(r)); S.append(s)
    W = np.asarray(W); S = np.asarray(S)
    res = {'n': len(W), 'seasons': [int(min(S)), int(max(S))], 'coef': coef}
    for k in err: err[k] = np.asarray(err[k]); res['mse_' + k] = round(float(np.sum(W * err[k]) / np.sum(W)), 5)
    for f, base in (('offset', 'raw'), ('linear', 'raw'), ('linear', 'offset')):
        won = sum(1 for s in set(S.tolist()) if np.sum((W * err[f])[S == s]) < np.sum((W * err[base])[S == s]))
        res[f'{f}_vs_{base}'] = {'t': round(tstat(err[f] - err[base], W), 2), 'won': f'{won}/{len(set(S.tolist()))}'}
    ok = lambda k: res[k]['t'] <= -2 and int(res[k]['won'].split('/')[0]) * 2 > int(res[k]['won'].split('/')[1])
    pick = 'linear' if ok('linear_vs_raw') and ok('linear_vs_offset') else 'offset' if ok('offset_vs_raw') else None
    res['ship'] = pick
    if pick:        # the live coefficients: every row whose outcome is known (seasons through the last with o3)
        b, a = wfit([r[xk] for r in rows], [r[yk] for r in rows], [wk(r) for r in rows], pick)
        res['live'] = {'form': pick, 'b': round(b, 4), 'a': round(a, 4), 'through': max(r['s'] for r in rows)}
    return res


def main():
    P = json.load(open(PAST))
    rv, rx = [], []
    for s in P['seasons']:
        for p in s['players']:
            if p.get('xv') is not None and p.get('o3') is not None:
                rv.append({'s': s['season'], 'x': p['xv'], 'y': p['o3']})
            if p.get('xx') is not None and p.get('ox') is not None:
                rx.append({'s': s['season'], 'x': p['xx'], 'y': p['ox'], 'w': p.get('o1') or 0})
    out = {'xvorx': run(rv, 'x', 'y', lambda r: 1.0),
           'xxpm': run([r for r in rx if r['w'] > 0], 'x', 'y', lambda r: r['w']),
           'xxpm_unweighted': run(rx, 'x', 'y', lambda r: 1.0)}
    for k, v in out.items():
        print(k, {a: b for a, b in v.items() if a != 'coef'})
    json.dump(out, open(OUT, 'w'), indent=1)
    cal = {k: dict(out[src]['live'], test={t: out[src][t] for t in ('n', 'seasons', 'mse_raw', 'mse_' + out[src]['ship'], out[src]['ship'] + '_vs_raw')})
           for k, src in (('xv', 'xvorx'), ('xx', 'xxpm')) if out[src].get('live')}
    json.dump(cal, open(LIVE, 'w'), indent=1)
    print('live', cal)


if __name__ == '__main__':
    main()
