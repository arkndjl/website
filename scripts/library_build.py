# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Library page data: research studies + glossary/methodology -> data/library.json.

  python3 scripts/library_build.py

Reads research/studies/<sport>/*.json (one study each, schema in research/studies/BRIEF.md; a study with
"publish": false is skipped) and research/library.json (glossary sections + FV conversion tables), draws each
study's chart as a pixel-grid SVG (integer coordinates, square markers, CI whiskers, colour by CSS class so the
site theme sets the palette) and writes data/library.json for layouts/shortcodes/libresearch.html and libglossary.html.

Also here, all read from files other scripts write (nothing typed in):
  the "testing" section    the gate and test entries, gathered from the sections they were written in (METHOD)
  entry charts             a term's held-out test, parts and distribution as pixel SVGs (data/glossary_gfx.json)
  overview / sports        the chain of tabs with counts, each sport's describe and predict pick, and a per-sport index
                           of terms, studies and log counts (data/arklog.json, scripts/arklog.py)
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
             'games': 'game models', 'drafts': 'drafts and mocks', 'method': 'testing', 'data': 'data and names',
             'abbr': 'abbreviations'}
# ARKLOG (was /arklog/, its own page until Nov 28 2026): the log, the monthly updates, the scoreboard and the site's own data
ARKLOG = {
    'log': '{{< arklog tab="log" >}}',
    'updates': '{{< arklogupdates tab="updates" >}}',
    # every sport's league dates and the site's season transitions (data/seasons, scripts/season_roll.py; Nov 28 2026)
    'calendar': '{{< arklogcal tab="calendar" >}}',
    'milestones': '{{< lazytab tab="milestones" >}}{{< arklogmiles tab="milestones" >}}{{< /lazytab >}}',   # scripts/milestones.py
    'scoreboard': '{{< lazytab tab="scoreboard" >}}{{< arklogboard tab="scoreboard" >}}{{< /lazytab >}}',
    'traffic': '{{< desk tab="traffic" >}}\n{{< sitestats part="views" class="desk__wide" >}}\n{{< sitestats part="trend" >}}\n'
               '{{< sitestats part="traffic" >}}\n{{< /desk >}}',
    'build': '{{< desk tab="build" >}}\n{{< sitestats part="build" class="desk__wide" >}}\n{{< /desk >}}',
    'data': '{{< desk tab="data" >}}\n{{< sitestats part="fresh" class="desk__wide" >}}\n{{< /desk >}}',
}
GROUP_ORDER = ['football', 'basketball', 'hockey', 'baseball', 'soccer', 'tennis', 'esports']
# the side strip: section -> the glossary sections under it (Process, Nov 27 2026). Tab names are the URL hash, so a
# section moves between groups without breaking a link.
SIDE = [('Metrics', ['fv', 'fv-scales', 'value', 'players']), ('Models', ['teams', 'games', 'drafts', 'method']),
        ('Data', ['data-sources', 'data', 'abbr'])]
# the testing tab: how a change is tested and kept, gathered from the sections the entries were written in
METHOD = ['Held out / LOSO / LOCO', 'Walk-forward test', 'Ship gate, placebo-calibrated', 'Model ledger', 'Driver gate (FV)',
          'FV scorecard', 'Held-out coverage (80% ranges)', 'Most predictive and most descriptive metric (by sport)',
          'Opponent adjustment (player and lineup rates)', 'Rule monitor (CUSUM)', 'Rule drift test (SPRT)']
SPORTS = ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer', 'Tennis', 'CS2', 'MLB']
SPORT_ALSO = {'NHL': ['Hockey']}           # glossary tags that belong to the same sheet
SPORT_STUDY = {'Soccer': 'soccer', 'Tennis': 'tennis'}


def gid(term):
    """the #g- anchor of a term (same rule as layouts/partials/glossid.html)"""
    import re
    return 'g-' + re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', term.lower()))


def regroup(sections):
    """Move the METHOD entries into one 'method' section, after drafts (order as listed)."""
    found = {}
    for sec in sections:
        keep = []
        for e in sec['entries']:
            (found.__setitem__(e['term'], e) if e['term'] in METHOD else keep.append(e))
        sec['entries'] = keep
    out = [x for x in sections if x['id'] != 'method']
    at = next((i + 1 for i, x in enumerate(out) if x['id'] == 'drafts'), len(out))
    out.insert(at, {'id': 'method', 'title': 'Testing and gates', 'entries': [found[t] for t in METHOD if t in found]})
    return out


def write_page(studies, sections, fv_tables):
    """content/arkboard-process.md (the Process page, /process/; was Reference, before that Library): hero, glossary search,
    then the side strip: Overview (overview, sports), Philosophy, ARKLOG, Metrics, Models, Research, Data."""
    page = ROOT / 'content/arkboard-process.md'
    head = page.read_text().split('{{< glossfind', 1)[0].split('{{< wintabs', 1)[0]
    groups = [g for g in GROUP_ORDER if any(s['group'] == g for s in studies)]
    rtabs = ['all studies'] + groups
    tab = {x['id']: x.get('tab') or GLOSS_TAB.get(x['id'], x['title']) for x in sections}
    tab.update({'fv-scales': 'FV scales', 'data-sources': 'data sources'})
    have = set(tab) if fv_tables else set(tab) - {'fv-scales'}
    side = [(lab, [sid for sid in ids if sid in have]) for lab, ids in SIDE]
    placed = {sid for _, ids in side for sid in ids}
    side[0][1].extend(x['id'] for x in sections if x['id'] not in placed)   # a section added later lands under Metrics
    phil = [t['tab'] for t in json.loads((ROOT / 'data/philosophy.json').read_text())['tabs']] \
        if (ROOT / 'data/philosophy.json').exists() else []        # scripts/philosophy_build.py
    strip = (['Overview:overview,sports'] + (['Philosophy:' + ','.join(phil)] if phil else []) + ['ARKLOG:' + ','.join(ARKLOG)] + [f'{lab}:' + ','.join(tab[i] for i in ids) for lab, ids in side[:2]]
             + ['Research:' + ','.join(rtabs)] + [f'{lab}:' + ','.join(tab[i] for i in ids) for lab, ids in side[2:]])
    gidx = '|'.join(f'{x["id"]}={tab[x["id"]]}' for x in sections)
    lines = ['{{< glossfind tabs="' + gidx + '" >}}', '',   # glossary search (layouts/shortcodes/glossfind.html)
             '{{< wintabs groups="' + '|'.join(strip) + '" side="true" class="libtabs" label="Process views" >}}',
             '{{< procover tab="overview" >}}']
    lazy = lambda t, sc: f'{{{{< lazytab tab="{t}" >}}}}{sc}{{{{< /lazytab >}}}}'   # later tabs load on first open
    lines += [lazy('sports', '{{< procsports tab="sports" >}}')]
    lines += [lazy(t, f'{{{{< procphil tab="{t}" >}}}}') for t in phil]
    lines += [ARKLOG[t] for t in ARKLOG]

    def gloss(sid):
        t = tab[sid]
        if sid == 'data-sources':
            return lazy(t, '{{< datasources tab="data sources" >}}')
        return lazy(t, f'{{{{< libglossary tab="{t}" fv="true" >}}}}' if sid == 'fv-scales' else f'{{{{< libglossary tab="{t}" section="{sid}" >}}}}')

    for _, ids in side[:2]:
        lines += [gloss(i) for i in ids]
    lines.append(lazy('all studies', '{{< libresearch tab="all studies" group="all" >}}'))
    lines += [lazy(g, f'{{{{< libresearch tab="{g}" group="{g}" >}}}}') for g in groups]
    lines += [gloss(i) for i in side[2][1]]
    lines.append('{{< /wintabs >}}')
    # #g-<term> links open the lazy glossary tab the term is in (layouts/shortcodes/libgidx.html, gfx.js rqFromHash)
    lines.append('{{< libgidx tabs="' + gidx + '" >}}')
    page.write_text(head + '\n'.join(lines) + '\n')


# ---- entry charts: what the term's GFX card draws (data/glossary_gfx.json), as pixel SVGs inside its window ----
def gnum(v, unit=''):
    if isinstance(v, str):
        return v
    s = f'{v:.1f}' if abs(v) >= 10 else f'{v:.3f}'.rstrip('0').rstrip('.')
    s = s.replace('0.', '.', 1) if s.startswith(('0.', '-0.')) else s
    return ('$' + s + 'M') if unit == '$M' else s + ('%' if unit == '%' else '')


def hbar_svg(rows, label, unit='', zoom=False):
    """Rows of [label, value, ours?]: one pixel bar each, the value at its end. zoom: bars start near the lowest value
    (close numbers on one scale, e.g. RMSE 2.93 against 2.97), marked by a broken axis."""
    rows = [r for r in rows if isinstance(r[1], (int, float))]
    if not rows:
        return ''
    Wd, Lb, Rv, T, rh = 336, 124, 52, 4, 18
    pw = Wd - Lb - Rv
    vals = [r[1] for r in rows]
    lo, hi = min(0, min(vals)), max(0, max(vals))
    if zoom and min(vals) > 0 and (max(vals) - min(vals)) < .35 * max(vals):
        lo = min(vals) - (max(vals) - min(vals)) * .6
    span = (hi - lo) or 1
    h = T + rh * len(rows) + 18
    out = [f'<svg class="libchart" viewBox="0 0 {Wd} {h}" shape-rendering="crispEdges" role="img" aria-label="{esc(label)}">']
    zx = Lb + round(pw * (0 - lo) / span) if lo <= 0 else Lb
    for i, r in enumerate(rows):
        y = T + i * rh
        ours = len(r) < 3 or r[2]
        out.append(f'<text class="lc-tick{" lc-own" if ours and len(r) > 2 else ""}" x="{Lb - 6}" y="{y + 12}" text-anchor="end">{esc(str(r[0])[:22])}</text>')
        x1 = Lb + round(pw * (r[1] - lo) / span)
        a, b = sorted((zx, x1))
        out.append(f'<rect class="lc-bar {"lc-s0" if ours else "lc-s3"}" x="{a}" y="{y + 3}" width="{max(2, b - a)}" height="11"/>')
        out.append(f'<text class="lc-tick{" lc-own" if ours and len(r) > 2 else ""}" x="{max(a, b) + 4}" y="{y + 12}">{esc(gnum(r[1], unit))}</text>')
    if lo > 0:   # broken axis: the bars do not start at zero
        for yy in range(T, T + rh * len(rows), 4):
            out.append(f'<rect class="lc-axis" x="{Lb - 2}" y="{yy}" width="2" height="2"/>')
    else:
        out.append(f'<rect class="lc-axis" x="{zx - 2}" y="{T}" width="2" height="{rh * len(rows)}"/>')
    out.append(f'<text class="lc-label" x="{Wd // 2}" y="{h - 4}" text-anchor="middle">{esc(label)}</text>')
    out.append('</svg>')
    return ''.join(out)


def dist_svg(bins, marks, label):
    """A distribution as pixel columns; marks [[x, word]] as dotted lines with the word over them."""
    if not bins:
        return ''
    Wd, Hd, L_, R_, T_, B_ = 336, 132, 8, 8, 16, 30
    pw, ph = Wd - L_ - R_, Hd - T_ - B_
    top = max(n for _, n in bins) or 1
    step = (bins[1][0] - bins[0][0]) if len(bins) > 1 else 1
    x0, x1 = bins[0][0], bins[-1][0] + step
    X = lambda v: L_ + round(pw * (v - x0) / ((x1 - x0) or 1))
    out = [f'<svg class="libchart" viewBox="0 0 {Wd} {Hd}" shape-rendering="crispEdges" role="img" aria-label="{esc(label)}">']
    for x, n in bins:
        a, b = X(x), X(x + step)
        hh = round(ph * n / top)
        if hh:
            out.append(f'<rect class="lc-bar lc-s0" x="{a}" y="{T_ + ph - hh}" width="{max(1, b - a - 1)}" height="{hh}"><title>{esc(gnum(x))}: {n}</title></rect>')
    out.append(f'<rect class="lc-axis" x="{L_}" y="{T_ + ph}" width="{pw}" height="2"/>')
    every = max(1, len(bins) // 8)
    for i, (x, _) in enumerate(bins):
        if i % every == 0:
            out.append(f'<text class="lc-tick" x="{X(x)}" y="{T_ + ph + 13}" text-anchor="middle">{esc(gnum(x))}</text>')
    last = -99
    for mx, word in (marks or []):
        x = X(mx)
        for yy in range(T_, T_ + ph, 4):
            out.append(f'<rect class="lc-mark" x="{x}" y="{yy}" width="1" height="2"/>')
        if x - last > 34:
            out.append(f'<text class="lc-marktext" x="{x + 3}" y="{T_ - 5}">{esc(word)}</text>')
            last = x
    out.append(f'<text class="lc-label" x="{Wd // 2}" y="{Hd - 4}" text-anchor="middle">{esc(label)}</text>')
    out.append('</svg>')
    return ''.join(out)


def entry_charts(g):
    """[{svg, note}] for one glossary_gfx entry: the held-out test, the blend's parts, bars, the distribution."""
    out = []
    t = g.get('test') or {}
    if t.get('rows'):
        out.append({'svg': hbar_svg(t['rows'], t.get('t', 'held-out test'), t.get('unit', ''), zoom=True), 'note': t.get('n', '')})
    elif t.get('tiles'):
        out.append({'tiles': [[str(x) for x in tl] for tl in t['tiles']], 'note': ' · '.join(x for x in (t.get('t', ''), t.get('n', '')) if x)})
    if g.get('parts'):
        out.append({'svg': hbar_svg([[p[0], p[1]] for p in g['parts']], 'weights'), 'note': ''})
    if g.get('bars'):
        out.append({'svg': hbar_svg(g['bars'], g.get('bl', ''), g.get('unit', ''), zoom=True), 'note': ''})
    v = g.get('viz') or {}
    if v.get('kind') == 'dist' and v.get('bins'):
        out.append({'svg': dist_svg(v['bins'], v.get('marks') or [], v.get('t', '')), 'note': ''})
    return [c for c in out if c.get('svg') or c.get('tiles')]


def lead_metrics(sections):
    """{sport: {describe, predict}} parsed from the 'Most predictive and most descriptive metric' entry (its numbers
    come from the metric audit files; this only splits its sentences by sport)."""
    import re
    e = next((x for sec in sections for x in sec['entries'] if x['term'].startswith('Most predictive and most descriptive')), None)
    if not e:
        return {}
    text = ' '.join(e.get('body') or [])
    names = '|'.join(SPORTS)
    out = {}
    for m in re.finditer(rf'\b({names}): describe (.+?), predict (.+?)\.(?=\s+(?:{names}|The)\b|\s*$)', text):
        cut = lambda t: re.match(r'^(.*?)(?:\s*\(([^)]*)\))?(?:,.*)?$', t.strip())
        d, p = cut(m.group(2)), cut(m.group(3))
        num = lambda t: (re.search(r'-?\.\d+', t or '') or [None])[0]
        out[m.group(1)] = {'describe': d.group(1), 'dn': num(m.group(2)), 'predict': p.group(1), 'pn': num(m.group(3)),
                           'dfull': m.group(2).strip(), 'pfull': m.group(3).strip()}
    return out


def overview(studies, sections, fv_tables):
    """data/library.json 'overview': the chain (tab, count), each sport's sheet, the gate entries' one-liners."""
    log = {}
    try:
        log = json.loads((ROOT / 'data/arklog.json').read_text())
    except (OSError, ValueError):
        pass
    try:
        nsrc = sum(len(g.get('sources', [])) for g in json.loads((ROOT / 'data/data_sources.json').read_text()).get('groups', []))
    except (OSError, ValueError, AttributeError):
        nsrc = 0
    sec = {x['id']: x for x in sections}
    n = lambda sid: len(sec[sid]['entries']) if sid in sec else 0
    chain = [{'k': 'data', 't': 'data sources', 'n': nsrc, 'u': 'sources'}, {'k': 'value', 't': 'player value', 'n': n('value'), 'u': 'terms'},
             {'k': 'players', 't': 'player odds', 'n': n('players'), 'u': 'terms'}, {'k': 'fv', 't': 'FV', 'n': n('fv'), 'u': 'terms'},
             {'k': 'teams', 't': 'team ratings', 'n': n('teams'), 'u': 'terms'}, {'k': 'games', 't': 'game models', 'n': n('games'), 'u': 'terms'},
             {'k': 'drafts', 't': 'drafts and mocks', 'n': n('drafts'), 'u': 'terms'}]
    lead = lead_metrics(sections)
    sheets = []
    for sp in SPORTS:
        tags = [sp] + SPORT_ALSO.get(sp, [])
        groups = []
        for x in sections:
            if x['id'] == 'abbr':
                continue
            terms = [{'t': e['term'], 'id': gid(e['term'])} for e in x['entries'] if any(t in (e.get('sports') or []) for t in tags)]
            if terms:
                groups.append({'tab': GLOSS_TAB.get(x['id'], x['title']), 'terms': terms})
        st = [{'id': s['id'], 'q': s['question']} for s in studies if s['sport'] == SPORT_STUDY.get(sp, sp)]
        if not groups and not st:
            continue
        sheets.append({'sport': sp, 'groups': groups, 'studies': st, 'log': (log.get('sports') or {}).get(sp, {}), 'lead': lead.get(sp),
                       'nterms': sum(len(g['terms']) for g in groups)})
    gate = [{'t': e['term'], 'id': gid(e['term']), 's': e['short']} for e in (sec.get('method') or {}).get('entries', [])]
    led = {}
    try:
        led = json.loads((ROOT / 'data/model_ledger.json').read_text()).get('counts', {})
    except (OSError, ValueError):
        pass
    return {'chain': chain, 'sheets': sheets, 'gate': gate, 'ledger': led,
            'terms': sum(len(x['entries']) for x in sections if x['id'] != 'abbr'), 'studies': len(studies), 'tables': len(fv_tables)}


def rq_card(s):
    """data-gfx-rq for the study's X card (assets/js/gfx.js buildRQ, same card as layouts/shortcodes/rq.html):
    question, answer, sample note, and up to 8 bars from the first chart series (evenly thinned)."""
    c = s.get('chart') or {}
    ser = (c.get('series') or [{}])[0].get('points') or []
    if len(ser) > 8:
        step = (len(ser) - 1) / 7
        ser = [ser[round(i * step)] for i in range(8)]
    pct = c.get('y_fmt') == 'pct'
    w0 = (c.get('x_label') or '').split(' ')[0].lower()
    unit_x = {'minutes': ' min', 'minute': "'", 'seconds': ' s', 'yards': ' yd', 'yds': ' yd'}.get(w0, '')
    bars = [[fmt(p['x'], 'num') + unit_x if not isinstance(p['x'], str) else p['x'], round(p['y'] * 100, 1) if pct else round(p['y'], 3)] for p in ser]
    name = (c.get('series') or [{}])[0].get('name', '')
    return {'id': s['id'], 'q': s['question'], 'a': s['answer'], 'sport': s['sport'], 'date': s.get('date', '2026-11-02'),
            'n': '', 'nl': '', 'bars': bars, 'unit': '%' if pct else '',
            'note': f"n = {s['n']:,}" + (f" · {c.get('y_label', '')} by {c.get('x_label', '')}" if bars else '') + (f" ({name})" if name and len(c.get('series') or []) > 1 else '')}


def main():
    studies = []
    for f in sorted((ROOT / 'research/studies').glob('*/*.json')):
        s = json.loads(f.read_text())
        if s.get('publish') is False:
            continue
        s['group'] = GROUP.get(s['sport'], 'other')
        s['svg'] = chart_svg(s.get('chart') or {})
        s['rq'] = rq_card(s)
        s['legend'] = [x['name'] for x in (s.get('chart') or {}).get('series', [])] if len((s.get('chart') or {}).get('series', [])) > 1 else []
        s.pop('chart', None)
        studies.append(s)
    studies.sort(key=lambda s: (SPORT_ORDER.index(s['sport']) if s['sport'] in SPORT_ORDER else 99, s.get('order', 9), -s.get('interest', 0), s['id']))
    lib = ROOT / 'research/library.json'
    glossary = json.loads(lib.read_text()) if lib.exists() else {'sections': [], 'fv_tables': []}
    sections = regroup(glossary.get('sections', []))
    try:   # the cards' pictures, written by scripts/glossary_gfx.py (which runs after this script; process-refresh.yml reruns this one)
        gfx = json.loads((ROOT / 'data/glossary_gfx.json').read_text())
    except (OSError, ValueError):
        gfx = {}
    for sec in sections:
        for e in sec['entries']:
            ch = entry_charts(gfx.get(e['term']) or {})
            if ch:
                e['charts'] = ch
            else:
                e.pop('charts', None)
    out = {'studies': studies, 'sections': sections, 'fv_tables': glossary.get('fv_tables', [])}
    out['overview'] = overview(studies, sections, out['fv_tables'])
    txt = json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    (ROOT / 'data/library.json').write_text(txt)
    write_page(studies, out['sections'], out['fv_tables'])
    print(f'library: {len(studies)} studies, {len(out["sections"])} glossary sections, {len(out["fv_tables"])} FV tables, {len(txt) // 1024} KB')


if __name__ == '__main__':
    main()
