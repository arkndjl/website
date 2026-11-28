#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Charts for posts (content/posts/*): pixel SVGs in the Process chart style (library_build.chart_svg), written to
data/post_charts.json {id: {svg, legend}} and placed with {{< postchart "<id>" >}}. Rerun after a source study changes.

    python3 scripts/post_charts.py

xpm-*: the XPM stabilization post, from data/nba_xpm_stability_research.json and the pXPM shrink fits
(old k 600 = nba_xpm.SHRINK_K; next-season RMSEs and the new pXPM from scripts/nba_pxpm_research.py).
cbb-*: the college XPM post, from data/cbb_xpm_research.json.
p1-*: Process #1, from the ARKLOG, site stats and LAURSEN_111 social files."""
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
    out['xpm-shrink'] = {'legend': ['one-dial shrink, k 600', f'{rho} x MP / (MP + {pad})', f'MP / (MP + {pad})', f'pXPM, k {k2} (one season)'], 'svg': LB.chart_svg({
        'title': 'Shrink weight on rXPM by minutes', 'x_label': 'minutes', 'y_label': 'weight on rXPM', 'y_fmt': 'pct',
        'series': [{'points': [{'x': m, 'y': round(f(m), 3)} for m in mps]} for f in
                   (lambda m: m / (m + k), lambda m: rho * m / (m + pad), lambda m: m / (m + pad), lambda m: m / (m + k2))]})}
    b = px['base']
    out['xpm-rmse'] = {'legend': ['next-season RMSE'], 'svg': LB.chart_svg({
        'title': 'Next-season XPM error', 'type': 'bar', 'x_label': '', 'y_label': 'RMSE',
        'series': [{'points': [{'x': 'BPM', 'y': b['BPM']['player']}, {'x': 'box XPM', 'y': b['rXPM']['player']},
                               {'x': 'DPM', 'y': b['DPM']['player']}, {'x': 'k 600', 'y': b['pXPM (live)']['player']},
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


def cbb_xpm_charts():
    """cbb-*: the college XPM post, from data/cbb_xpm_research.json (pxpm2, rxpm3: scripts/research/cbb_xpm_nov26)"""
    d = json.load(open(os.path.join(ROOT, 'data', 'cbb_xpm_research.json'))); P, H = d['pxpm2']['byPair'], d['rxpm3']
    out = {}
    out['cbb-pxpm-pairs'] = {'legend': ['pXPM', 'BPM'], 'svg': LB.chart_svg({
        'title': 'Next-season team strength R2 by season projected', 'y_fmt': 'num', 'x_label': 'season projected (spring year)', 'y_label': 'R2',
        'series': [{'points': [{'x': int(k) + 1, 'y': P[n][k]} for k in sorted(P[n])]} for n in ('pxpm', 'bpm')]})}
    W = H['team']['wab_g']['bySeason']
    out['cbb-rxpm-wab'] = {'legend': ['XPM', 'BPM'], 'svg': LB.chart_svg({
        'title': 'Team wins above bubble R2 by season', 'y_fmt': 'num', 'x_label': 'season (spring year)', 'y_label': 'R2',
        'series': [{'points': [{'x': int(k), 'y': W[n][k]} for k in sorted(W[n])]} for n in ('h', 'bpm')]})}
    return out


def process1_charts():
    """p1-*: Process #1 (November 2026), from data/arklog.json, data/site_stats.json and data/laursen_socials.json"""
    import datetime as dt
    out = {}
    a = json.load(open(os.path.join(ROOT, 'data', 'arklog.json')))
    wk = [w for w in a['weeks'] if '2026-10-26' <= w[0] <= '2026-11-23']
    lab = lambda d: dt.date.fromisoformat(d).strftime('%b %-d')
    out['p1-weeks'] = {'legend': ['shipped', 'part shipped', 'failed'], 'svg': LB.chart_svg({
        'title': 'Tests by week', 'type': 'bar', 'x_label': 'week of', 'y_label': 'tests',
        'series': [{'points': [{'x': lab(w[0]), 'y': w[1][k]} for w in wk]} for k in ('shipped', 'mixed', 'failed')]})}
    s = json.load(open(os.path.join(ROOT, 'data', 'site_stats.json')))['days']
    mo = {}
    for d, v in s.items():
        if d >= '2026-06':
            m = mo.setdefault(d[:7], [0, 0]); m[0] += v.get('pv', 0); m[1] += 1
    out['p1-traffic'] = {'legend': ['page views a day'], 'svg': LB.chart_svg({
        'title': 'Page views a day by month', 'type': 'bar', 'x_label': 'month', 'y_label': 'page views',
        'series': [{'points': [{'x': dt.date.fromisoformat(m + '-01').strftime('%b'), 'y': round(v[0] / v[1])} for m, v in sorted(mo.items())]}]})}
    rows = json.load(open(os.path.join(ROOT, 'static', 'data', 'arklog.json')))['rows']
    sec = {}
    for r in rows:
        if r['d'][:7] == '2026-11' and r.get('n'):
            sec[r['sec']] = sec.get(r['sec'], 0) + 1
    out['p1-sections'] = {'legend': ['merged changes'], 'svg': LB.chart_svg({
        'title': 'November changes by section', 'type': 'bar', 'x_label': '', 'y_label': 'changes',
        'series': [{'points': [{'x': {'ARKBOARD': 'ARKBOARD', 'LAURSEN_111': 'LAURSEN', 'ST. CLAIRE': 'ST. CLAIRE'}.get(k, k), 'y': v}
                               for k, v in sorted(sec.items(), key=lambda t: -t[1])]}]})}
    ls = json.load(open(os.path.join(ROOT, 'data', 'laursen_socials.json')))['series']
    day = {}
    for p in ls:
        day[dt.datetime.fromtimestamp(p['t'] / 1000, dt.timezone.utc).day] = p
    nets = [('twitch', 'Twitch'), ('tiktok', 'TikTok'), ('x', 'X'), ('youtube', 'YouTube')]
    out['p1-laursen'] = {'legend': [n for _, n in nets], 'svg': LB.chart_svg({
        'title': 'LAURSEN_111 followers by day', 'x_label': 'November', 'y_label': 'followers',
        'series': [{'points': [{'x': d, 'y': p[k]} for d, p in sorted(day.items()) if p.get(k) is not None]} for k, _ in nets]})}
    return out


if __name__ == '__main__':
    fn = os.path.join(ROOT, 'data', 'post_charts.json')
    try: allc = json.load(open(fn))
    except (OSError, ValueError): allc = {}
    allc.update(xpm_charts())
    allc.update(cbb_xpm_charts())
    allc.update(process1_charts())
    json.dump(allc, open(fn, 'w'), indent=1)
    print(sorted(allc))
