#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pack On3's industry football recruiting tables (scripts/cfb_on3.mjs -> scripts/.cache/cfb/on3/<class>.json) into the
two files the recruit fit and the recruit tabs read:

    python3 scripts/cfb_on3_pack.py --live 2027 2028 2029   # scripts/data/cfb_on3_live.json (the classes being recruited)
    python3 scripts/cfb_on3_pack.py --hist 2011 2026        # scripts/data/cfb_on3_hist.json.gz (signed classes, the fits)

A row: [name, home state, industry rating, industry rank, 247's own national rank, 247 vs industry, ESPN vs industry,
commit date, Rivals rank (the Rivals300: On3's own service, 'On3' in its ratings), Rivals stars, and in the live file
On3's photo path (on on3static.com, for the recruit tabs' row frames and GFX cards; null when On3 has none)]. The two gaps are the service's rating less the industry rating, each as a z-score within the class among
the recruits it rated. The live file also carries the line from the industry rating to 247's composite scale (fit on
the classes both cover in scripts/cfb_recruit_247.json), for the recruit tabs' composite-to-grade map.
"""
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'on3')
HIST = os.path.join(ROOT, 'scripts', 'data', 'cfb_on3_hist.json.gz')
LIVE = os.path.join(ROOT, 'scripts', 'data', 'cfb_on3_live.json')
SNAP = os.path.join(ROOT, 'scripts', 'cfb_recruit_247.json')


def msd(v):
    m = sum(v) / len(v); return m, (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5 or 1.0


def rows(y, img=False):
    f = os.path.join(CACHE, f'{y}.json')
    if not os.path.exists(f): return None
    o3 = [o for o in json.load(open(f)) if o.get('cons')]
    if not o3: return None
    z = {}
    for s in ('247', 'espn'):
        v = [o['svc'][s][0] for o in o3 if s in (o.get('svc') or {})]
        z[s] = msd(v) if len(v) >= 20 else None
    mc, sc = msd([o['cons'] for o in o3])
    out = []
    for o in o3:
        zc = (o['cons'] - mc) / sc; sv = o.get('svc') or {}
        gap = lambda s: round((sv[s][0] - z[s][0]) / z[s][1] - zc, 3) if s in sv and z[s] else None
        out.append([o['name'], o.get('state'), round(o['cons'], 2), o.get('consRank'), sv.get('247', [None, None])[1], gap('247'), gap('espn'),
                    (o.get('commitDate') or '')[:10] or None, o.get('on3Rank'), sv.get('on3', [None, None, None])[2]]
                   + ([re.sub(r'^https?://on3static\.com/', '', o['img']) if o.get('img') else None] if img else []))
    return out


def comp_map():
    """247 composite = a + b x industry rating, on the snapshot's classes that On3 covers too"""
    snap = json.load(open(SNAP))['composite']; pts = []
    for y, c in snap.items():
        r = rows(y)
        if not r: continue
        by = {(N.key(x[0]), x[1]): x[2] for x in r}
        pts += [(by[(N.key(n), st)], cp) for n, st, cp, *_ in c if (N.key(n), st) in by and cp]
    if len(pts) < 500: return None
    mx = sum(p[0] for p in pts) / len(pts); my = sum(p[1] for p in pts) / len(pts)
    b = sum((p[0] - mx) * (p[1] - my) for p in pts) / sum((p[0] - mx) ** 2 for p in pts)
    return [round(my - b * mx, 5), round(b, 6), len(pts)]


def main():
    ys = [int(a) for a in sys.argv[1:] if a.isdigit()]
    if '--hist' in sys.argv:
        out = {str(y): r for y in range(ys[0], ys[1] + 1) if (r := rows(y))}
        with gzip.open(HIST, 'wt') as f: json.dump(out, f, separators=(',', ':'))
        print('history', {y: len(r) for y, r in out.items()})
    if '--live' in sys.argv:
        prev = json.load(open(LIVE)) if os.path.exists(LIVE) else {'classes': {}}
        got = {str(y): r for y in ys if (r := rows(y, img=True))}
        if not got: raise SystemExit('no On3 classes in the cache: the live file is left as it was')
        m = comp_map() or prev.get('map')
        out = {'asof': __import__('datetime').date.today().isoformat(), 'map': m, 'classes': {**prev.get('classes', {}), **got}}
        json.dump(out, open(LIVE, 'w'), separators=(',', ':'))
        print('live', {y: len(r) for y, r in got.items()}, 'map', m)


if __name__ == '__main__':
    main()
