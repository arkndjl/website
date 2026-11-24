#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Charts for posts (content/posts/*): pixel SVGs in the Process chart style (library_build.chart_svg), written to
data/post_charts.json {id: {svg, legend}} and placed with {{< postchart "<id>" >}}. Rerun after a source study changes.

    python3 scripts/post_charts.py

xpm-*: the XPM stabilization post, from data/nba_xpm_stability_research.json and the pXPM shrink fits
(old k 600 = nba_xpm.SHRINK_K; next-season RMSEs and the new pXPM from scripts/nba_pxpm_research.py)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import library_build as LB
ROOT = os.path.join(HERE, '..')


def xpm_charts():
    d = json.load(open(os.path.join(ROOT, 'data', 'nba_xpm_stability_research.json')))
    out = {}
    ks = sorted(d['byK'], key=int)
    out['xpm-splithalf'] = {'legend': ['box XPM', 'on-court +/-'], 'svg': LB.chart_svg({
        'title': 'Split-half r by games per half', 'y_fmt': 'num', 'x_label': 'games per half', 'y_label': 'split-half r',
        'ref': {'y': 0.5, 'label': 'r = .50'},
        'series': [{'points': [{'x': int(k), 'y': d['byK'][k][n]} for k in ks]} for n in ('box XPM', 'on-court +/-')]})}
    short = {'3PA rate': '3PA', 'AST/48': 'AST', 'PTS/48': 'PTS', 'OREB/48': 'ORB', 'DREB/48': 'DRB', 'BLK/48': 'BLK',
             'TOV/48': 'TOV', 'PF/48': 'PF', 'box XPM': 'XPM', 'STL/48': 'STL', 'on-court +/-': '+/-', 'TS%': 'TS%'}
    st = sorted(d['stab'].items(), key=lambda t: t[1]['g50x'])
    w0 = LB.W; LB.W = 420
    out['xpm-stats'] = {'legend': ['games to r = .50 (90% CI)'], 'svg': LB.chart_svg({
        'title': 'Games to r = .50 by stat', 'type': 'bar', 'y_label': 'games', 'x_label': 'stat',
        'series': [{'points': [{'x': short[n], 'y': v['g50x'], 'lo': v['g50_90'][0], 'hi': v['g50_90'][1]} for n, v in st]}]})}
    LB.W = w0
    rho, pad, k = 0.87, 230, 600
    mps = list(range(0, 3001, 250))
    px = json.load(open(os.path.join(ROOT, 'data', 'nba_pxpm_research.json')))    # scripts/nba_pxpm_research.py
    k2 = px['ship'][0]
    out['xpm-shrink'] = {'legend': ['old pXPM, k 600', f'{rho} x MP / (MP + {pad})', f'MP / (MP + {pad})', f'new pXPM, k {k2} (one season)'], 'svg': LB.chart_svg({
        'title': 'Shrink weight on rXPM by minutes', 'x_label': 'minutes', 'y_label': 'weight on rXPM', 'y_fmt': 'pct',
        'series': [{'points': [{'x': m, 'y': round(f(m), 3)} for m in mps]} for f in
                   (lambda m: m / (m + k), lambda m: rho * m / (m + pad), lambda m: m / (m + pad), lambda m: m / (m + k2))]})}
    b = px['base']
    out['xpm-rmse'] = {'legend': ['next-season RMSE'], 'svg': LB.chart_svg({
        'title': 'Next-season XPM error', 'type': 'bar', 'x_label': '', 'y_label': 'RMSE',
        'series': [{'points': [{'x': 'BPM', 'y': b['BPM']['player']}, {'x': 'rXPM', 'y': b['rXPM']['player']},
                               {'x': 'DPM', 'y': b['DPM']['player']}, {'x': 'old pXPM', 'y': b['pXPM (live)']['player']},
                               {'x': 'pXPM', 'y': px['loo']['player']}]}]})}
    pr = json.load(open(os.path.join(ROOT, 'data', 'nba_xpm_predictive_research.json')))['all']
    order = sorted(pr.items(), key=lambda t: -t[1]['predict'])
    lab = {'on-court +/-': '+/-', 'RAPM (1-yr)': 'RAPM', 'HAPM (1-yr)': 'HAPM', 'LEBRON': 'LEBR'}
    w0 = LB.W; LB.W = 420
    out['xpm-predict'] = {'legend': ['next-season team net R2 (90% CI)'], 'svg': LB.chart_svg({
        'title': 'Next-season team net rating R2 by metric', 'type': 'bar', 'x_label': 'metric', 'y_label': 'R2',
        'series': [{'points': [{'x': lab.get(m, m), 'y': v['predict'], 'lo': v['predict90'][0], 'hi': v['predict90'][1]} for m, v in order]}]})}
    LB.W = w0
    return out


if __name__ == '__main__':
    fn = os.path.join(ROOT, 'data', 'post_charts.json')
    try: allc = json.load(open(fn))
    except (OSError, ValueError): allc = {}
    allc.update(xpm_charts())
    json.dump(allc, open(fn, 'w'), indent=1)
    print(sorted(allc))
