"""Library page data: research studies + glossary/methodology -> data/library.json.

  python3 scripts/library_build.py

Reads research/studies/<sport>/*.json (one study each, schema in research/studies/BRIEF.md; a study with
"publish": false is skipped) and research/library.json (glossary sections + FV conversion tables), draws each
study's chart as a pixel-grid SVG (integer coordinates, square markers, CI whiskers, colour by CSS class so the
site theme sets the palette) and writes data/library.json for layouts/shortcodes/libresearch.html and libglossary.html.
"""
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPORT_ORDER = ['NFL', 'CFB', 'NBA', 'CBB', 'NHL', 'MLB', 'soccer', 'tennis', 'CS2']
GROUP = {'NFL': 'football', 'CFB': 'football', 'NBA': 'basketball', 'CBB': 'basketball', 'NHL': 'hockey',
         'MLB': 'baseball', 'soccer': 'soccer', 'tennis': 'tennis', 'CS2': 'esports'}

W, H = 336, 200          # viewBox; every coordinate is an integer (crisp pixel edges)
L, R, T, B = 44, 10, 10, 34


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def fmt(v, kind):
    if kind == 'pct':
        return f'{v * 100:.0f}%'
    if kind == 'signed':
        return f'{v:+.2f}'.replace('+0.00', '0') if abs(v) < 10 else f'{v:+.0f}'
    if abs(v) >= 100:
        return f'{v:.0f}'
    if abs(v) >= 10 or v == int(v):
        return f'{v:.0f}' if v == int(v) else f'{v:.1f}'
    return f'{v:.2f}'.rstrip('0').rstrip('.') if abs(v) < 1 else f'{v:.1f}'


def nice_ticks(lo, hi, n=4):
    span = hi - lo or abs(hi) or 1
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=10 * mag)
    a = math.floor(lo / step) * step
    b = math.ceil(hi / step) * step
    ticks, v = [], a
    while v <= b + step * 1e-6:
        ticks.append(round(v, 10))
        v += step
    return ticks


def chart_svg(c):
    series = c.get('series') or []
    kind = c.get('y_fmt', 'num')
    bar = c.get('type') == 'bar'
    ys = []
    for s in series:
        for p in s['points']:
            ys += [p['y']] + [p[k] for k in ('lo', 'hi') if p.get(k) is not None]
    ref = c.get('ref') or None
    if ref and ref.get('y') is not None:
        ys.append(ref['y'])
    if bar:
        ys.append(0)
    if not ys:
        return ''
    yt = nice_ticks(min(ys), max(ys))
    y0, y1 = yt[0], yt[-1]
    pw, ph = W - L - R, H - T - B

    def Y(v):
        return T + round(ph * (1 - (v - y0) / ((y1 - y0) or 1)))

    out = [f'<svg class="libchart" viewBox="0 0 {W} {H}" shape-rendering="crispEdges" role="img" '
           f'aria-label="{esc(c.get("title", "chart"))}">']
    for v in yt:   # grid + y labels
        y = Y(v)
        out.append(f'<rect class="lc-grid" x="{L}" y="{y}" width="{pw}" height="1"/>')
        out.append(f'<text class="lc-tick" x="{L - 4}" y="{y + 4}" text-anchor="end">{esc(fmt(v, kind))}</text>')
    out.append(f'<rect class="lc-axis" x="{L}" y="{T}" width="2" height="{ph + 1}"/>')
    out.append(f'<rect class="lc-axis" x="{L}" y="{T + ph}" width="{pw}" height="2"/>')

    if bar:
        cats = []
        for s in series:
            for p in s['points']:
                if p['x'] not in cats:
                    cats.append(p['x'])
        ns, slot = len(series), pw / max(1, len(cats))
        bw = max(4, int(slot * 0.7 / ns))
        for si, s in enumerate(series):
            for p in s['points']:
                ci = cats.index(p['x'])
                x = L + 2 + int(slot * ci + (slot - bw * ns) / 2) + si * bw
                ya, yb = sorted((Y(0), Y(p['y'])))
                out.append(f'<rect class="lc-bar lc-s{si}" x="{x}" y="{ya}" width="{bw - 2}" height="{max(1, yb - ya)}"/>')
                if p.get('lo') is not None and p.get('hi') is not None:
                    xm = x + (bw - 2) // 2
                    out.append(f'<rect class="lc-ci" x="{xm}" y="{Y(p["hi"])}" width="1" height="{max(1, Y(p["lo"]) - Y(p["hi"]))}"/>')
        for ci, cat in enumerate(cats):
            x = L + 2 + int(slot * ci + slot / 2)
            out.append(f'<text class="lc-tick" x="{x}" y="{T + ph + 14}" text-anchor="middle">{esc(cat)}</text>')
    else:
        xs = [p['x'] for s in series for p in s['points']]
        mark = c.get('mark') or None
        if mark and mark.get('x') is not None:
            xs.append(mark['x'])
        xt = nice_ticks(min(xs), max(xs), 5)
        xa, xb = min(xs), max(xs)   # data range; ticks outside it are not drawn
        rev = bool(c.get('x_reverse'))

        def X(v):
            f = (v - xa) / ((xb - xa) or 1)
            return L + 2 + round((pw - 6) * ((1 - f) if rev else f))

        for v in xt:
            if xa - 1e-9 <= v <= xb + 1e-9:
                out.append(f'<text class="lc-tick" x="{X(v)}" y="{T + ph + 14}" text-anchor="middle">{esc(fmt(v, "num"))}</text>')
        if mark and mark.get('x') is not None:
            x = X(mark['x'])
            for yy in range(T, T + ph, 4):
                out.append(f'<rect class="lc-mark" x="{x}" y="{yy}" width="1" height="2"/>')
            if mark.get('label'):
                anchor = 'start' if x < L + pw * 0.7 else 'end'
                out.append(f'<text class="lc-marktext" x="{x + (3 if anchor == "start" else -3)}" y="{T + 9}" text-anchor="{anchor}">{esc(mark["label"])}</text>')
        for si, s in enumerate(series):
            pts = sorted(s['points'], key=lambda p: p['x'])
            for p in pts:   # CI whiskers first
                if p.get('lo') is not None and p.get('hi') is not None:
                    x = X(p['x'])
                    out.append(f'<rect class="lc-ci lc-c{si}" x="{x}" y="{Y(p["hi"])}" width="1" height="{max(1, Y(p["lo"]) - Y(p["hi"]))}"/>')
            for a, b in zip(pts, pts[1:]):   # stair-step: across at a's height to the midpoint, up/down, across at b's
                xa_, xb_, ya_, yb_ = X(a['x']), X(b['x']), Y(a['y']), Y(b['y'])
                xm = (xa_ + xb_) // 2
                for x1, x2, y in ((xa_, xm, ya_), (xm, xb_, yb_)):
                    out.append(f'<rect class="lc-line lc-s{si}" x="{min(x1, x2)}" y="{y}" width="{abs(x2 - x1) + 2}" height="2"/>')
                out.append(f'<rect class="lc-line lc-s{si}" x="{xm}" y="{min(ya_, yb_)}" width="2" height="{abs(yb_ - ya_) + 2}"/>')
            for p in pts:
                out.append(f'<rect class="lc-pt lc-s{si}" x="{X(p["x"]) - 2}" y="{Y(p["y"]) - 2}" width="5" height="5"/>')
    if ref and ref.get('y') is not None:
        y = Y(ref['y'])
        for xx in range(L + 2, L + pw, 6):
            out.append(f'<rect class="lc-ref" x="{xx}" y="{y}" width="3" height="1"/>')
        if ref.get('label'):
            out.append(f'<text class="lc-reftext" x="{L + pw - 2}" y="{y - 3}" text-anchor="end">{esc(ref["label"])}</text>')
    out.append(f'<text class="lc-label" x="{L + pw // 2}" y="{H - 4}" text-anchor="middle">{esc(c.get("x_label", ""))}</text>')
    out.append(f'<text class="lc-label" x="10" y="{T + ph // 2}" text-anchor="middle" transform="rotate(-90 10 {T + ph // 2})">{esc(c.get("y_label", ""))}</text>')
    out.append('</svg>')
    return ''.join(out)


GLOSS_TAB = {'fv': 'FV', 'value': 'player value', 'players': 'player odds', 'teams': 'team ratings',
             'games': 'game models', 'drafts': 'drafts and mocks', 'data': 'data and names'}
GROUP_ORDER = ['football', 'basketball', 'hockey', 'baseball', 'soccer', 'tennis', 'esports']


def write_page(studies, sections, fv_tables):
    """content/arkboard-reference.md (the Reference page, was Library): hero + the research and glossary tab groups
    built from data/library.json, then the Data Sources tab (layouts/shortcodes/datasources.html)."""
    page = ROOT / 'content/arkboard-reference.md'
    head = page.read_text().split('{{< wintabs', 1)[0]
    groups = [g for g in GROUP_ORDER if any(s['group'] == g for s in studies)]
    rtabs = ['all studies'] + groups
    gtabs = [(x['id'], x.get('tab') or GLOSS_TAB.get(x['id'], x['title'])) for x in sections]
    if fv_tables:   # FV scales right after the FV section
        at = next((i + 1 for i, (sid, _) in enumerate(gtabs) if sid == 'fv'), 0)
        gtabs.insert(at, ('fv-scales', 'FV scales'))
    gl = ('|Glossary/Methodology:' + ','.join(t for _, t in gtabs)) if gtabs else ''
    lines = ['{{< wintabs groups="Research:' + ','.join(rtabs) + gl + '|Data Sources:data sources" side="true" class="libtabs" label="Reference views" >}}',
             '{{< libresearch tab="all studies" group="all" >}}']
    lazy = lambda tab, sc: f'{{{{< lazytab tab="{tab}" >}}}}{sc}{{{{< /lazytab >}}}}'   # later tabs load on first open
    lines += [lazy(g, f'{{{{< libresearch tab="{g}" group="{g}" >}}}}') for g in groups]
    for sid, tab in gtabs:
        lines.append(lazy(tab, f'{{{{< libglossary tab="{tab}" fv="true" >}}}}' if sid == 'fv-scales'
                          else f'{{{{< libglossary tab="{tab}" section="{sid}" >}}}}'))
    lines.append(lazy('data sources', '{{< datasources tab="data sources" >}}'))
    lines.append('{{< /wintabs >}}')
    page.write_text(head + '\n'.join(lines) + '\n')


def main():
    studies = []
    for f in sorted((ROOT / 'research/studies').glob('*/*.json')):
        s = json.loads(f.read_text())
        if s.get('publish') is False:
            continue
        s['group'] = GROUP.get(s['sport'], 'other')
        s['svg'] = chart_svg(s.get('chart') or {})
        s['legend'] = [x['name'] for x in (s.get('chart') or {}).get('series', [])] if len((s.get('chart') or {}).get('series', [])) > 1 else []
        s.pop('chart', None)
        studies.append(s)
    studies.sort(key=lambda s: (SPORT_ORDER.index(s['sport']) if s['sport'] in SPORT_ORDER else 99, s.get('order', 9), -s.get('interest', 0), s['id']))
    lib = ROOT / 'research/library.json'
    glossary = json.loads(lib.read_text()) if lib.exists() else {'sections': [], 'fv_tables': []}
    out = {'studies': studies, 'sections': glossary.get('sections', []), 'fv_tables': glossary.get('fv_tables', [])}
    txt = json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    (ROOT / 'data/library.json').write_text(txt)
    write_page(studies, out['sections'], out['fv_tables'])
    print(f'library: {len(studies)} studies, {len(out["sections"])} glossary sections, {len(out["fv_tables"])} FV tables, {len(txt) // 1024} KB')


if __name__ == '__main__':
    main()
