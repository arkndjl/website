#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Basketball-Reference play-by-play position estimates (share of minutes at PG/SG/SF/PF/C) per NBA player season.
    python3 bbref_pos.py <dir with pbp<year>.html> <out.json>
Traded players: the TOT / 2TM row when the page has one, else team rows summed by minutes."""
import re, sys, json, glob, os
src, out = sys.argv[1], sys.argv[2]
rows = []
for p in sorted(glob.glob(os.path.join(src, 'pbp*.html'))):
    y = int(re.search(r'pbp(\d{4})', p).group(1))
    h = open(p, encoding='utf-8', errors='replace').read()
    h = h[h.find('<tbody'):]
    seen = {}
    for tr in re.findall(r'<tr\s*>(.*?)</tr>', h, re.S):
        m = re.search(r'data-append-csv="([a-z0-9]+)"', tr)
        if not m: continue
        cells = dict(re.findall(r'data-stat="(pct_\d)"[^>]*csk="([^"]*)"', tr))
        txt = dict(re.findall(r'data-stat="([a-z0-9_]+)"[^>]*>(?:<[^>]+>)*([^<]*)', tr))
        try:
            mp = float(re.sub(r'[^\d.]', '', txt.get('mp', '')) or 0)
            pct = [float(cells.get(f'pct_{k}') or 0) for k in range(1, 6)]
        except ValueError:
            continue
        team = txt.get('team_name_abbr', '')
        name = re.sub(r'<[^>]+>', '', txt.get('name_display', ''))
        seen.setdefault(m.group(1), []).append((team, mp, pct, name, txt.get('age')))
    for b, L in seen.items():
        tot = [x for x in L if re.match(r'(TOT|\dTM)$', x[0])]
        use = tot[:1] if tot else L
        mp = sum(x[1] for x in use)
        if mp <= 0: continue
        pct = [sum(x[1] * x[2][k] for x in use) / mp for k in range(5)]
        s = sum(pct) or 1
        rows.append({'bref': b, 'year': y, 'name': use[0][3], 'age': use[0][4], 'mp': mp, 'pct': [round(v / s, 4) for v in pct]})
json.dump(rows, open(out, 'w'))
print(len(rows), 'player seasons', min(r['year'] for r in rows), max(r['year'] for r in rows))
