# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Process > Philosophy: Noah's text from research/philosophy.json with the charts and tables drawn from the site's own
fit and data files, written to data/philosophy.json for layouts/shortcodes/procphil.html.

    python3 scripts/philosophy_build.py

research/philosophy.json holds the text only: {"tabs": [{"tab", "title", "blocks": [...]}]}, each block one of
  {"h": "heading"}  {"p": "a paragraph"}  {"fig": "<figure id>"}  {"q": "a pull line"}
A number in the text is a {key} placeholder filled from VALUES below (read from the fit files), never typed in.
Figures (FIGS) are pixel SVGs in the Process chart style (library_build.chart_svg) or small tables. process-refresh.yml
reruns this after the fits move."""
import json
import math
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import library_build as LB   # noqa: E402

ROOT = HERE.parent
TEXT = ROOT / 'research/philosophy.json'
OUT = ROOT / 'data/philosophy.json'
AUDIT = ROOT / 'scripts/research/metric_audit_nov24'


def load(p):
    return json.loads((ROOT / p).read_text())


def scatter_svg(c):
    """Labelled points on two axes (x describe, y predict): the chart_svg frame with square markers and a name beside
    each one. c = {title, x_label, y_label, points: [{x, y, label, own}], diag}"""
    W, H, L, R, T, B = 336, 220, 44, 12, 10, 34
    pts = c['points']
    xs = [p['x'] for p in pts]
    ys = [p['y'] for p in pts]
    xt, yt = LB.nice_ticks(min(xs + [0]), max(xs)), LB.nice_ticks(min(ys + [0]), max(ys))
    x0, x1, y0, y1 = xt[0], xt[-1], yt[0], yt[-1]
    pw, ph = W - L - R, H - T - B

    def X(v):
        return L + 2 + round((pw - 6) * (v - x0) / ((x1 - x0) or 1))

    def Y(v):
        return T + round(ph * (1 - (v - y0) / ((y1 - y0) or 1)))

    out = [f'<svg class="libchart" viewBox="0 0 {W} {H}" shape-rendering="crispEdges" role="img" '
           f'aria-label="{LB.esc(c.get("title", "chart"))}">']
    for v in yt:
        out.append(f'<rect class="lc-grid" x="{L}" y="{Y(v)}" width="{pw}" height="1"/>')
        out.append(f'<text class="lc-tick" x="{L - 4}" y="{Y(v) + 4}" text-anchor="end">{LB.esc(LB.fmt(v, "num"))}</text>')
    for v in xt:
        out.append(f'<text class="lc-tick" x="{X(v)}" y="{T + ph + 14}" text-anchor="middle">{LB.esc(LB.fmt(v, "num"))}</text>')
    out.append(f'<rect class="lc-axis" x="{L}" y="{T}" width="2" height="{ph + 1}"/>')
    out.append(f'<rect class="lc-axis" x="{L}" y="{T + ph}" width="{pw}" height="2"/>')
    placed = []
    for p in sorted(pts, key=lambda p: -p['y']):
        x, y = X(p['x']), Y(p['y'])
        cls = 'lc-s1' if p.get('own') else 'lc-s3'
        out.append(f'<rect class="lc-pt {cls}" x="{x - 2}" y="{y - 2}" width="5" height="5"/>')
        if p.get('label'):
            right = x < L + pw * 0.62
            ty = y + 4
            while any(abs(ty - q) < 10 and abs(x - qx) < 90 for qx, q in placed):
                ty += 10
            placed.append((x, ty))
            out.append(f'<text class="lc-tick{" lc-own" if p.get("own") else ""}" x="{x + 5 if right else x - 5}" y="{ty}" '
                       f'text-anchor="{"start" if right else "end"}">{LB.esc(p["label"])}</text>')
    out.append(f'<text class="lc-label" x="{L + pw // 2}" y="{H - 4}" text-anchor="middle">{LB.esc(c.get("x_label", ""))}</text>')
    out.append(f'<text class="lc-label" x="10" y="{T + ph // 2}" text-anchor="middle" transform="rotate(-90 10 {T + ph // 2})">'
               f'{LB.esc(c.get("y_label", ""))}</text>')
    out.append('</svg>')
    return ''.join(out)


def context_figs(V):
    """describe against predict, one chart a sport, from the Nov 24 metric audit and the NBA XPM test"""
    figs = {}
    nba = load('data/nba_xpm_predictive_research.json')['all']
    own = {'rXPM', 'pXPM'}
    lab = {'on-court +/-': '+/-', 'RAPM (1-yr)': 'RAPM', 'HAPM (1-yr)': 'HAPM'}
    figs['ctx-nba'] = {'svg': scatter_svg({
        'title': 'NBA metrics: describe against predict', 'x_label': 'same-season team net rating R²',
        'y_label': 'next-season team net rating R²',
        'points': [{'x': v['describe'], 'y': v['predict'], 'label': lab.get(k, k), 'own': k in own} for k, v in nba.items()]}),
        'legend': ['site metric', 'other metric'], 'keys': [1, 3], 'note': f'{nba["rXPM"]["pairs"]} season pairs, held out'}
    V.update({'nba_rxpm_d': nba['rXPM']['describe'], 'nba_rxpm_p': nba['rXPM']['predict'], 'nba_pxpm_d': nba['pXPM']['describe'],
              'nba_pxpm_p': nba['pXPM']['predict'], 'nba_onoff_d': nba['on/off']['describe'], 'nba_onoff_p': nba['on/off']['predict'],
              'nba_pm_d': nba['on-court +/-']['describe'], 'nba_pm_p': nba['on-court +/-']['predict']})
    nhl = json.loads((AUDIT / 'nhl/results.json').read_text())['metrics']
    keep = {'WAR (descriptive)': 'WAR', 'pWAR / HPM (board weights)': 'pWAR', 'Marcel WAR (projections tab)': 'Marcel WAR',
            'points a 60': 'points/60', 'MoneyPuck game score a 60': 'game score/60'}
    figs['ctx-nhl'] = {'svg': scatter_svg({
        'title': 'NHL metrics: describe against predict', 'x_label': 'same-season team R², held out', 'y_label': 'next-season team R²',
        'points': [{'x': nhl[k]['describeHeld'], 'y': nhl[k]['predictTeam'], 'label': n, 'own': n in ('WAR', 'pWAR', 'Marcel WAR')}
                   for k, n in keep.items()]}), 'legend': ['site metric', 'other metric'], 'keys': [1, 3], 'note': '2009-26'}
    w, p = nhl['WAR (descriptive)'], nhl['pWAR / HPM (board weights)']
    V.update({'nhl_war_d': w['describeHeld'], 'nhl_war_p': w['predictTeam'], 'nhl_pwar_d': p['describeHeld'], 'nhl_pwar_p': p['predictTeam']})
    soc = json.loads((AUDIT / 'soccer/results.json').read_text())['metrics']
    keep = {'SV/SVAR': 'SVAR', 'GAR': 'GAR', 'p/90': 'p/90', 'xMV': 'xMV', 'TM value': 'TM value', 'G+A/90': 'G+A/90',
            'npxG+xA/90': 'npxG+xA/90', 'FotMob rating': 'FotMob'}
    figs['ctx-soccer'] = {'svg': scatter_svg({
        'title': 'Soccer metrics: describe against predict', 'x_label': 'same-season team R², held out', 'y_label': 'next-season team R²',
        'points': [{'x': soc[k]['describeHeld'], 'y': soc[k]['predictTeam'], 'label': n, 'own': n in ('SVAR', 'GAR', 'p/90', 'xMV')}
                   for k, n in keep.items()]}), 'legend': ['site metric', 'other metric'], 'keys': [1, 3], 'note': '2015-26'}
    V.update({'soc_svar_d': soc['SV/SVAR']['describeHeld'], 'soc_p90_p': soc['p/90']['predictTeam'],
              'soc_fm_d': soc['FotMob rating']['describeHeld']})
    return figs


def count_rate_figs(V):
    """VORX (count) and XPM (rate) on last season's NBA board, and how fast a rate settles"""
    figs = {}
    d = load('static/data/nba-xpm/2026.json')
    P = d['players']
    pts = [{'x': r['mp'], 'y': r['xpm']} for r in P if r.get('xpm') is not None]
    figs['cr-scatter'] = {'svg': LB.chart_svg({
        'title': f'{d["label"]} XPM by minutes', 'x_label': 'minutes', 'y_label': 'XPM',
        'series': [{'points': sorted(pts, key=lambda p: p['x'])}]}).replace('lc-line', 'lc-none'),
        'legend': [f'{len(pts)} players'], 'keys': [0], 'note': d['label']}
    top_r = sorted(P, key=lambda r: -r['xpm'])[:10]
    top_c = sorted(P, key=lambda r: -r['vorx'])[:10]
    rows = [[i + 1, a['n'], f'{a["xpm"]:+.1f}', f'{a["mp"]:,}', b['n'], f'{b["vorx"]:.1f}', f'{b["mp"]:,}']
            for i, (a, b) in enumerate(zip(top_r, top_c))]
    figs['cr-top'] = {'table': {'head': ['RK', 'by XPM', 'XPM', 'MP', 'by VORX', 'VORX', 'MP'], 'rows': rows,
                                'group': [[1, 3], [4, 6]]}, 'note': d['label']}
    small = [r for r in top_r if r['mp'] < 500]
    V.update({'cr_label': d['label'], 'cr_n': len(pts), 'cr_small': len(small),
              'cr_small_name': small[0]['n'] if small else '', 'cr_small_xpm': f'{small[0]["xpm"]:+.1f}' if small else '',
              'cr_small_mp': small[0]['mp'] if small else ''})
    st = load('data/nba_xpm_stability_research.json')['stab']
    short = {'3PA rate': '3PA', 'AST/48': 'AST', 'PTS/48': 'PTS', 'OREB/48': 'ORB', 'DREB/48': 'DRB', 'BLK/48': 'BLK',
             'TOV/48': 'TOV', 'PF/48': 'PF', 'box XPM': 'XPM', 'STL/48': 'STL', 'on-court +/-': '+/-', 'TS%': 'TS%'}
    rows = sorted(st.items(), key=lambda t: t[1]['g50x'])
    w0 = LB.W
    LB.W = 420
    figs['cr-stab'] = {'svg': LB.chart_svg({
        'title': 'Games to r = .50 by stat', 'type': 'bar', 'y_label': 'games', 'x_label': 'stat',
        'series': [{'points': [{'x': short.get(n, n), 'y': v['g50x'], 'lo': v['g50_90'][0], 'hi': v['g50_90'][1]} for n, v in rows]}]}),
        'legend': ['games to r = .50 (90% CI)'], 'keys': [0], 'note': 'split-half, 2010-26'}
    LB.W = w0
    V.update({'stab_xpm': st['box XPM']['g50'], 'stab_pm': st['on-court +/-']['g50'], 'stab_pts': st['PTS/48']['g50']})
    return figs


def testing_figs(V):
    """the record: every reviewed test's t and its verdict, from ARKLOG"""
    figs = {}
    rows = load('static/data/arklog.json')['rows']
    tests = [r for r in rows if r.get('v') in ('s', 'm', 'f')]
    a = load('data/arklog.json')
    ts = [abs(r['tt']) for r in tests if isinstance(r.get('tt'), (int, float))]
    bins = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 99)]
    lab = ['0-1', '1-2', '2-3', '3-5', '5-10', '10+']
    figs['t-hist'] = {'svg': LB.chart_svg({
        'title': 'Tests by |t|', 'type': 'bar', 'x_label': '|t| of the deciding number', 'y_label': 'tests',
        'ref': None, 'series': [{'points': [{'x': lab[i], 'y': sum(lo <= t < hi for t in ts)} for i, (lo, hi) in enumerate(bins)]}]}),
        'legend': [f'{len(ts)} tests with a stated t'], 'keys': [0], 'note': 'ARKLOG'}
    mo = [m for m in a['months'] if (m['s'] + m['m'] + m['f'])]
    figs['verdicts'] = {'svg': LB.chart_svg({
        'title': 'Verdicts by month', 'type': 'bar', 'x_label': 'month', 'y_label': 'tests',
        'series': [{'points': [{'x': m['mo'][5:], 'y': m[k]} for m in mo]} for k in ('s', 'm', 'f')]}),
        'legend': ['shipped', 'part shipped', 'failed'], 'keys': [0, 1, 2], 'note': 'ARKLOG'}
    V.update({'tests': a['tests'], 'shipped': a['shipped'], 'mixed': a['mixed'], 'failed': a['failed'],
              'failed_pct': round(100 * a['failed'] / max(1, a['tests'])), 'changes': f'{a["changes"]:,}',
              'ship_pct': round(100 * a['shipped'] / max(1, a['tests']))})
    return figs


def design_figs(V):
    """the palette and the one font, read from static/style.css"""
    css = (ROOT / 'static/style.css').read_text()
    root = css[css.index(':root'):css.index('}', css.index(':root'))]
    tok = dict(re.findall(r'--([a-z-]+):\s*(#[0-9a-fA-F]{3,8})', root))
    sw = [(k, v) for k, v in tok.items()][:8]
    V.update({'palette_n': len(sw)})
    return {'palette': {'swatches': [{'name': k, 'hex': v} for k, v in sw]}}


def fill(s, V):
    def rep(m):
        k = m.group(1)
        if k not in V:
            raise KeyError(f'philosophy: no value for {{{k}}}')
        v = V[k]
        if isinstance(v, float):
            return (f'{v:.3f}'.lstrip('0') if abs(v) < 1 else f'{v:g}')
        return str(v)
    return re.sub(r'\{([a-z0-9_]+)\}', rep, s)


def main():
    V = {}
    figs = {}
    for f in (context_figs, count_rate_figs, testing_figs, design_figs):
        figs.update(f(V))
    text = json.loads(TEXT.read_text()) if TEXT.exists() else {'tabs': []}
    tabs = []
    for t in text['tabs']:
        blocks = []
        for b in t['blocks']:
            if 'fig' in b:
                if b['fig'] not in figs:
                    raise KeyError(f'philosophy: no figure {b["fig"]}')
                blocks.append({'fig': b['fig'], **figs[b['fig']], **({'cap': fill(b['cap'], V)} if b.get('cap') else {})})
            else:
                blocks.append({k: fill(v, V) for k, v in b.items()})
        tabs.append({**{k: v for k, v in t.items() if k != 'blocks'}, 'blocks': blocks})
    OUT.write_text(json.dumps({'tabs': tabs, 'values': V}, ensure_ascii=False, indent=1, allow_nan=False))
    print(f'philosophy: {len(tabs)} tabs, {len(figs)} figures, {len(V)} values')


if __name__ == '__main__':
    main()
