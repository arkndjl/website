#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Source build for the all-time NFL head-coach rankings (scripts/coach_alltime.py scores them with the college
method): scripts/data/coach_alltime_nfl_src.json.gz.

    python3 scripts/coach_alltime_nfl.py pull     # pro-football-history.com coach pages, cached, 1.3 s apart
    python3 scripts/coach_alltime_nfl.py build    # parse the cache, write the source file
    python3 scripts/coach_alltime.py              # scores every sport whose source file is present

Per team-season (NFL, AFL and AAFC, 1920 on): the rating and record from the all-time teams' source
(scripts/data/alltime_src.json.gz: ridge points a game vs an average team), the league or conference, the league title,
the conference title (a place in the title game), and each head coach with his share of the team's games.
Coaches come from each head coach's page on pro-football-history.com: year, team, role and his own record that season
(a row whose role names Head Coach, so an interim's games count as his share), with the page's marks for a championship
or a conference championship season. Coordinator seasons on the same pages are kept for the carry test ('coord').
Hall of Fame: inducted to the Pro Football Hall of Fame as a coach (Wikipedia's list, position starting "Coach");
coaches inducted as players or owners are left out of the fit (`hofSkip`).
Cache: scripts/.cache/coach_alltime_nfl (not committed).
"""
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as N
from coach_alltime_pro import scale

CACHE = os.path.join(HERE, '.cache', 'coach_alltime_nfl')
SRC = os.path.join(HERE, 'data', 'coach_alltime_nfl_src.json.gz')
TEAMS = os.path.join(HERE, 'data', 'alltime_src.json.gz')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
BASE = 'https://pro-football-history.com'
HOF = 'https://en.wikipedia.org/w/index.php?title=List_of_Pro_Football_Hall_of_Fame_inductees&action=raw'
GAP = 1.3
AFC = {'BUF', 'MIA', 'NE', 'NYJ', 'BAL', 'CIN', 'CLE', 'PIT', 'HOU', 'IND', 'JAX', 'TEN', 'DEN', 'KC', 'LV', 'LAC'}
# one code a franchise through its moves, so the expectation follows the club
FRANCH = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA', 'WSH': 'WAS'}


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=40) as r:
        return r.read()


def pull():
    os.makedirs(CACHE, exist_ok=True)
    idx = os.path.join(CACHE, 'coaches.html')
    if not os.path.exists(idx):
        open(idx, 'wb').write(fetch(BASE + '/coaches')); time.sleep(GAP)
    hof = os.path.join(CACHE, 'hof.txt')
    if not os.path.exists(hof):
        open(hof, 'wb').write(fetch(HOF))
    links = sorted(set(re.findall(r'href="(/coach/\d+/[^"]+-bio)"', open(idx, encoding='utf-8', errors='replace').read())))
    for l in links:
        fn = os.path.join(CACHE, l.strip('/').replace('/', '_') + '.html')
        if os.path.exists(fn) and os.path.getsize(fn) > 5000:
            continue
        try:
            open(fn, 'wb').write(fetch(BASE + l))
        except Exception as e:      # noqa: BLE001
            print(l, repr(e), flush=True)
        time.sleep(GAP)
    print(len(links), 'coach pages')


def text(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s))).strip()


def page(path):
    """(name, [(year, team name, franchise slug, role, w, l, t, title, conference title)])"""
    s = open(path, encoding='utf-8', errors='replace').read()
    m = re.search(r'<h1[^>]*>(.*?)</h1>', s, re.S)
    name = text(m.group(1)) if m else ''
    m = re.search(r'<table id="coach-history".*?</table>', s, re.S)
    rows = []
    for cls, body in re.findall(r'<tr([^>]*)>(.*?)</tr>', m.group(0) if m else '', re.S):
        td = re.findall(r'<td[^>]*>(.*?)</td>', body, re.S)
        if len(td) < 3:
            continue
        a = re.findall(r'<a href="([^"]*)"[^>]*>(.*?)</a>', td[0], re.S)
        rec = re.match(r'(\d+)-(\d+)(?:-(\d+))?', text(td[2]))
        if len(a) < 2 or not rec or not text(a[0][1]).isdigit():
            continue
        fr = re.search(r'/franchise/\d+/(.*?)-coaches', a[1][0])
        rows.append((int(text(a[0][1])), text(a[1][1]), fr.group(1) if fr else '', text(td[1]), int(rec.group(1)), int(rec.group(2)),
                     int(rec.group(3) or 0), 'bg-yellow' in cls, 'bg-yellow' in cls or 'bg-purple' in cls))
    return name, rows


def is_hc(role):
    r = re.sub(r'assistant head coach|associate head coach', '', role.lower())
    return 'head coach' in r


def coord_side(role):
    r = role.lower()
    return 'o' if 'offensive coordinator' in r else 'd' if 'defensive coordinator' in r else None


def hall():
    s = open(os.path.join(CACHE, 'hof.txt'), encoding='utf-8', errors='replace').read()
    coach, other = set(), set()
    for m in re.finditer(r'\{\{sortname\|([^|}]+)\|([^|}]+)[^}]*\}\}', s):
        p = re.search(r'data-sort-value="([^"]*?) \d{4}"', s[m.end():m.end() + 500])
        if not p:
            continue
        (coach if p.group(1).strip().lower().startswith('coach') else other).add(N.key(f'{m.group(1).strip()} {m.group(2).strip()}'))
    return coach, other - coach


def build():
    with gzip.open(TEAMS, 'rt') as f:
        A = json.load(f)
    for r in A['nfl']:
        r['c'] = FRANCH.get(r['c'], r['c'])
    T = {}
    for r in A['nfl']:
        T[(N.key(r['t']), r['y'])] = r
    by_code = defaultdict(dict)
    for r in A['nfl']:
        by_code[r['c']][r['y']] = r
    names, cs, flags, coord = {}, defaultdict(list), {}, []
    slug_code = {}       # franchise slug -> code, learned from the seasons whose names agree
    pages = {}
    for f in sorted(os.listdir(CACHE)):
        if f.startswith('coach_'):
            cid = 'pfh' + f.split('_')[1]
            pages[cid] = page(os.path.join(CACHE, f))
    find = lambda team, y: T.get((N.key(team), y))
    for cid, (name, rows) in pages.items():
        for y, team, slug, role, w, l, t, nt, ct in rows:
            r = find(team, y)
            if r:
                slug_code.setdefault(slug, r['c'])
    miss = 0
    for cid, (name, rows) in pages.items():
        for y, team, slug, role, w, l, t, nt, ct in rows:
            r = find(team, y) or by_code.get(slug_code.get(slug), {}).get(y)
            if not r:
                miss += is_hc(role)
                continue
            k = (r['c'], y)
            if is_hc(role):
                names[cid] = name
                cs[k].append((cid, w + l + t))
                flags[k] = (max(flags.get(k, (0, 0))[0], int(nt)), max(flags.get(k, (0, 0))[1], int(ct)))
            elif coord_side(role):
                coord.append([cid, y, r['c'], coord_side(role)])
    rows = []
    for r in A['nfl']:
        k = (r['c'], r['y'])
        g = sum(r['wl']) or 1
        L = [(c, n) for c, n in cs.get(k, []) if n > 0] or [(c, g) for c, n in cs.get(k, [])][:1]
        tot = sum(n for _, n in L) or 1
        conf = r.get('lg') or ('NFL' if r['y'] < 1970 else 'AFC' if r['c'] in AFC else 'NFC')
        nt, ct = flags.get(k, (0, 0))
        rows.append(dict(t=r['c'], y=r['y'], r=r['r'], conf=conf, cs=[[c, round(n / tot, 4)] for c, n in L], wl=r['wl'],
                         nt=float(nt), ct=float(ct)))
    teams = {}
    for r in sorted(A['nfl'], key=lambda r: r['y']):
        teams[r['c']] = r['t']
    hc, other = hall()
    hof = sorted(k for k in {N.key(n) for n in names.values()} if k in hc)
    skip = sorted(k for k in {N.key(n) for n in names.values()} if k in other)
    ch = {int(y): t for y, t in A.get('nflch', {}).items()}
    bad = [(r['y'], r['t']) for r in rows if r['nt'] and r['y'] in ch and N.key(teams.get(r['t'], '')) != N.key(ch[r['y']]) and r['y'] >= 1970]
    out = {'nfl': dict(rows=rows, names=names, teams=teams, sig=scale(rows), hof=hof, hofSkip=skip, coord=[c for c in coord if c[0] in names])}
    with gzip.GzipFile(SRC, 'wb', mtime=0) as g:
        g.write(json.dumps(out, separators=(',', ':')).encode())
    print('nfl', len(rows), 'team-seasons', sum(1 for r in rows if r['cs']), 'with a coach', len(names), 'coaches; head-coach rows with no team-season',
          miss, '; titles', sum(r['nt'] for r in rows), 'title-game seasons', sum(r['ct'] for r in rows), 'scale', out['nfl']['sig'],
          'hall of fame', len(hof), 'left out of the fit', len(skip), 'coordinator seasons', len(out['nfl']['coord']), 'title mismatches', bad[:8])


if __name__ == '__main__':
    a = sys.argv[1:]
    if 'pull' in a:
        pull()
    if 'build' in a or not a:
        build()
