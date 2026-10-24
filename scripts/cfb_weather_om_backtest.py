#!/usr/bin/env python3
"""Does Open-Meteo kickoff weather improve the CFB totals model? (research only, round 2, Oct 24 2026)

    python3 scripts/cfb_weather_om_backtest.py     # needs numpy and scripts/data/cfb_weather_om.json (cfb_weather_om.py)

PRE-REGISTERED GATE (before the numbers): walk-forward rows of scripts/data/games_wf/cfb.json.gz with a model total
(tm), final total and closing total, non-neutral outdoor games (the home team's venue). Leave-one-season-out, OLS on
the other seasons: y = tot - tm on [wind past 10 mph, cold under 50F, rain 0.1in+ over the 3 hours]. Compared with
tm + the training-season mean. Pass = pooled held-out MAE improves with paired t <= -2 on |error| differences, most
seasons agree, and a forward check (fit on seasons before s, score s, 2022+) is not worse. Variants reported: wind only,
the same on the closing total (tot - T; an upper bound, observed weather), and the 2025-26 games with the old airport
(ASOS) proxy side by side.
"""
import gzip
import json
import math
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')
OM = os.path.join(HERE, 'data', 'cfb_weather_om.json')
OLD = os.path.join(HERE, 'data', 'cfb_weather.json')
OUT = os.path.join(HERE, 'data', 'cfb_weather_om_backtest.json')


def feats(w, which):
    f = {'wind': max(w['wind'] - 10, 0.0), 'cold': max(50 - (w['temp'] if w['temp'] is not None else 60.0), 0.0),
         'rain': 1.0 if (w.get('rain') or 0) >= 0.1 else 0.0, 'gust': max((w.get('gust') or w['wind']) - 15, 0.0)}
    return [f[k] for k in which]


def design(rows, which):
    return np.column_stack([np.ones(len(rows)), np.array([feats(r['w'], which) for r in rows])])


def run(rows, which, y_key, mode, min_seasons=2):
    b = None
    pairs = []
    for s in sorted({r['S'] for r in rows}):
        tr = [r for r in rows if (r['S'] != s if mode == 'loso' else r['S'] < s)]
        te = [r for r in rows if r['S'] == s]
        if len({r["S"] for r in tr}) < min_seasons or len(tr) < 300:
            continue
        ytr = np.array([r[y_key] for r in tr])
        mu = ytr.mean()
        b = np.linalg.lstsq(design(tr, which), ytr, rcond=None)[0]
        p1 = design(te, which) @ b
        for r, q in zip(te, p1):
            pairs.append((s, abs(r[y_key] - mu), abs(r[y_key] - q), (r[y_key] - mu) ** 2, (r[y_key] - q) ** 2))
    return pairs, b


def summ(pairs):
    d = np.array([p[2] - p[1] for p in pairs])
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    by = defaultdict(list)
    for p in pairs:
        by[p[0]].append(p[2] - p[1])
    seas = {int(s): round(float(np.mean(v)), 3) for s, v in sorted(by.items())}
    return {'n': len(d), 'mae0': round(float(np.mean([p[1] for p in pairs])), 3), 'mae1': round(float(np.mean([p[2] for p in pairs])), 3),
            'dMAE': round(float(d.mean()), 4), 't': round(t, 2), 'better': f"{sum(v < 0 for v in seas.values())}/{len(seas)}",
            'rmse0': round(math.sqrt(np.mean([p[3] for p in pairs])), 3), 'rmse1': round(math.sqrt(np.mean([p[4] for p in pairs])), 3),
            'seasons': seas}


def main():
    wf = json.load(gzip.open(WF))
    om = json.load(open(OM))
    old = json.load(open(OLD))
    rows = []
    for g in wf:
        w = om['games'].get(g['id'])
        if not w or g.get('tm') is None or g.get('T') is None or g.get('tot') is None:
            continue
        o = old['games'].get(g['id']) or {}
        a = old['venues'].get(o.get('venue')) if o.get('venue') else None
        asos = {'wind': o['wind'], 'temp': o.get('temp'), 'rain': o.get('rain') or 0.0, 'gust': o.get('gust')} \
            if o.get('wind') is not None and (o.get('km') or 0) <= 50 and not (a or {}).get('indoor') else None
        rows.append({**g, 'w': w, 'asos': asos, 'ytm': g['tot'] - g['tm'], 'yT': g['tot'] - g['T']})
    print(len(rows), 'outdoor games with weather;', sorted({(r['S']) for r in rows}))
    res = {'n': len(rows), 'meanWind': round(float(np.mean([r['w']['wind'] for r in rows])), 2),
           'windy15': sum(r['w']['wind'] >= 15 for r in rows), 'cold40': sum(r['w']['temp'] <= 40 for r in rows),
           'rainy': sum((r['w']['rain'] or 0) >= 0.1 for r in rows)}
    for nm, which in (('wind+cold+rain', ['wind', 'cold', 'rain']), ('wind', ['wind']), ('wind+gust+cold+rain', ['wind', 'gust', 'cold', 'rain'])):
        for yk, yn in (('ytm', 'tot-tm'), ('yT', 'tot-T')):
            for mode in ('loso', 'wf'):
                pairs, b = run(rows, which, yk, mode)
                if not pairs:
                    continue
                s = summ(pairs)
                s['coef(last fold)'] = [round(float(x), 3) for x in b]
                res[f'{nm}/{yn}/{mode}'] = s
                print(f"{nm:20s} {yn:7s} {mode:4s} n{s['n']} MAE {s['mae0']} -> {s['mae1']} d{s['dMAE']} t{s['t']} better {s['better']} rmse {s['rmse0']}->{s['rmse1']} coef {s['coef(last fold)']}")
    # in-sample slopes on the full set
    X = design(rows, ['wind', 'cold', 'rain'])
    for yk in ('ytm', 'yT'):
        y = np.array([r[yk] for r in rows])
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        e = y - X @ b
        V = np.linalg.inv(X.T @ X) @ (X.T * e ** 2) @ X @ np.linalg.inv(X.T @ X)
        res[f'full/{yk}'] = {k: [round(float(b[i]), 3), round(float(b[i] / math.sqrt(V[i, i])), 2)] for i, k in enumerate(['const', 'wind>10', 'cold<50', 'rain'])}
        print('full', yk, res[f'full/{yk}'])
    # same games, Open-Meteo vs the airport proxy (2025-26)
    sub = [r for r in rows if r['asos']]
    print(len(sub), 'games with both sources')
    res['bothN'] = len(sub)
    for src in ('w', 'asos'):
        s2 = [{**r, 'w': r[src]} for r in sub]
        pairs, _ = run(s2, ['wind', 'cold', 'rain'], 'ytm', 'loso', 1)
        if pairs:
            res[f'both/{src}/tot-tm/loso'] = summ(pairs)
            q = res[f'both/{src}/tot-tm/loso']
            print(f"both {src:5s} n{q['n']} MAE {q['mae0']} -> {q['mae1']} d{q['dMAE']} t{q['t']} better {q['better']}")
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
