#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Source build for the all-time head-coach rankings in the NBA and NHL (scripts/coach_alltime.py scores them with
the college method): scripts/data/coach_alltime_pro_src.json.gz.

    python3 scripts/coach_alltime_pro.py pull     # Basketball-Reference and Hockey-Reference pages, cached, 3.6 s apart
    python3 scripts/coach_alltime_pro.py build    # parse the cache, write the source file
    python3 scripts/coach_alltime.py              # scores every sport whose source file is present

Per team-season: the rating (Sports Reference SRS: points a game in the NBA, goals a game in the NHL), the record,
the conference (the division before conferences), the league title, the conference title (a place in the Finals /
the Stanley Cup Final), and each head coach with his share of the team's games.
  NBA  BAA 1947-49 and NBA 1950-2026: the season's coach register (games each coach was on the bench) and standings.
  NHL  1918-2026 (no 2005 season; seasons before Sports Reference has an SRS are dropped): every coach's own page
       (team, games, record by season) and the season standings.
A franchise keeps one id through its moves (FRANCH), so the expectation follows the club, not the city.
Hall of Fame: NBA = inducted to the Naismith Hall in the Coach category (Basketball-Reference's list, by coach id).
NHL = inducted to the Hockey Hall of Fame as a Builder (Hockey-Reference's list, joined by name): that Hall has no
coach category. Coaches inducted as players (Toe Blake, Dick Irvin, Jacques Lemaire) are left out of the fit
(`hofSkip`): their plaque says nothing either way about their coaching.
Cache: scripts/.cache/coach_alltime_pro (not committed).
"""
import gzip
import json
import os
import re
import sys
import time
from collections import defaultdict
from statistics import NormalDist

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as N

CACHE = os.path.join(HERE, '.cache', 'coach_alltime_pro')
SRC = os.path.join(HERE, 'data', 'coach_alltime_pro_src.json.gz')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
BB = 'https://www.basketball-reference.com'
HR = 'https://www.hockey-reference.com'
LAST = {'nba': 2026, 'nhl': 2026}
GAP = 3.6
# season codes that are one franchise: old code -> the current one
FRANCH = {
    'nba': {'NJN': 'BRK', 'NYN': 'BRK', 'NOH': 'NOP', 'NOK': 'NOP', 'SEA': 'OKC', 'VAN': 'MEM', 'CHH': 'CHO', 'CHA': 'CHO', 'WSB': 'WAS',
            'CAP': 'WAS', 'BAL': 'WAS', 'CHZ': 'WAS', 'CHP': 'WAS', 'KCK': 'SAC', 'KCO': 'SAC', 'CIN': 'SAC', 'ROC': 'SAC', 'SDC': 'LAC',
            'BUF': 'LAC', 'NOJ': 'UTA', 'SDR': 'HOU', 'SFW': 'GSW', 'PHW': 'GSW', 'SYR': 'PHI', 'STL': 'ATL', 'MLH': 'ATL', 'TRI': 'ATL',
            'MNL': 'LAL', 'FTW': 'DET'},
    'nhl': {'PHX': 'ARI', 'WIN': 'ARI', 'QUE': 'COL', 'HAR': 'CAR', 'MNS': 'DAL', 'ATF': 'CGY', 'KCS': 'NJD', 'CLR': 'NJD', 'ATL': 'WPG',
            'MDA': 'ANA', 'CBH': 'CHI', 'DTC': 'DET', 'DTF': 'DET', 'TRS': 'TOR', 'TRA': 'TOR', 'OAK': 'CLE', 'CGS': 'CLE'},
}
def fname(url):
    return os.path.join(CACHE, re.sub(r'[^A-Za-z0-9_.-]', '_', url.split('//')[1])[:150])


def get(url, fetch=True):
    """the page, from the cache or the site (one request every GAP seconds; a 429 waits two minutes and more)"""
    f = fname(url)
    if os.path.exists(f):
        return open(f, encoding='utf-8', errors='replace').read()
    if not fetch:
        return None
    import requests
    os.makedirs(CACHE, exist_ok=True)
    for i in range(4):
        try:
            r = requests.get(url, headers={'User-Agent': UA}, timeout=40)
        except requests.RequestException as e:
            print('error', url, str(e)[:80], flush=True); time.sleep(20); continue
        if r.status_code in (200, 404):
            txt = r.text if r.status_code == 200 else ''
            open(f, 'w', encoding='utf-8').write(txt); time.sleep(GAP)
            return txt
        print('status', r.status_code, url, flush=True)
        time.sleep(120 * (i + 1) if r.status_code == 429 else 15)
    return None


def nba_urls():
    out = [BB + '/coaches/', BB + '/playoffs/', BB + '/awards/hof.html']
    for y in range(LAST['nba'], 1946, -1):
        lg = 'BAA' if y <= 1949 else 'NBA'
        out += [f'{BB}/leagues/{lg}_{y}_coaches.html', f'{BB}/leagues/{lg}_{y}.html']
    return out


def nhl_urls(index=None):
    out = [HR + '/coaches/', HR + '/playoffs/', HR + '/awards/hhof.html'] + [f'{HR}/leagues/NHL_{y}.html' for y in range(LAST['nhl'], 1917, -1) if y != 2005]
    return out + [HR + l for l in sorted(set(re.findall(r'href="(/coaches/[a-z0-9]+\.html)"', index or '')))]


def pull():
    for u in nba_urls(): get(u)
    idx = get(HR + '/coaches/')
    for u in nhl_urls(idx): get(u)


# ---- parsing ---------------------------------------------------------------------------------------------------
def tables(html):
    """{table id: [row dicts by data-stat]} with commented-out tables included"""
    html = html.replace('<!--', '').replace('-->', '')
    out = {}
    for m in re.finditer(r'<table[^>]*id="([^"]+)".*?</table>', html, re.S):
        rows = []
        for r in re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(0), re.S):
            d = dict(re.findall(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', r, re.S))
            if d: rows.append(d)
        out[m.group(1)] = rows
    return out


def text(s):
    return re.sub(r'<[^>]+>', '', s or '').replace('&nbsp;', ' ').replace('&amp;', '&').strip()


def num(s):
    try:
        return float(text(s))
    except ValueError:
        return None


def code(s, kind='teams'):
    m = re.search(r'/%s/([A-Z0-9]+)/' % kind, s or '')
    return m.group(1) if m else None


def cid(s):
    m = re.search(r'/coaches/([a-z0-9]+)\.html', s or '')
    return m.group(1) if m else None


def finals(html, tid):
    """{season: (champion code, runner-up code)} from the playoff index"""
    out = {}
    for r in tables(html).get(tid, []):
        y = num(r.get('year_id') or r.get('season'))
        lg = text(r.get('lg_id') or 'NHL')
        ch, ru = code(r.get('champion')), code(r.get('runnerup') or r.get('finalist'))
        if y and ch and lg in ('NBA', 'BAA', 'NHL'): out[int(y)] = (ch, ru)
    return out


def build_nba():
    fin = finals(get(BB + '/playoffs/', False) or '', 'champions_index')
    rows, names, teams = [], {}, {}
    fr = FRANCH['nba']
    for y in range(1947, LAST['nba'] + 1):
        lg = 'BAA' if y <= 1949 else 'NBA'
        st = tables(get(f'{BB}/leagues/{lg}_{y}.html', False) or '')
        co = tables(get(f'{BB}/leagues/{lg}_{y}_coaches.html', False) or '').get(f'{lg}_coaches') or tables(get(f'{BB}/leagues/{lg}_{y}_coaches.html', False) or '').get('NBA_coaches', [])
        by = defaultdict(list)
        for r in co:
            c, t, g = cid(r.get('coach')), code(r.get('team')), num(r.get('cur_g'))
            if c and t and g:
                by[t].append((c, g)); names[c] = text(r['coach']).rstrip('*')
        seen = set()
        ids = [k for k in st if k.startswith('confs_standings')] or [k for k in st if k.startswith('divs_standings')]
        for k in ids:
            conf = k.rsplit('_', 1)[-1] if k.rsplit('_', 1)[-1] in ('E', 'W') else 'L'      # L: one table for the league
            for r in st[k]:
                t = code(r.get('team_name'))
                w, l, srs = num(r.get('wins')), num(r.get('losses')), num(r.get('srs'))
                if not t or t in seen or w is None or srs is None: continue
                seen.add(t)
                f = fr.get(t, t)
                if y == LAST['nba'] or f not in teams: teams[f] = re.sub(r'\*$', '', text(r['team_name'])).strip()
                tot = sum(g for _, g in by[t]) or 1
                ch, ru = fin.get(y, (None, None))
                rows.append(dict(t=f, y=y, r=srs, conf=conf, cs=[[c, round(g / tot, 4)] for c, g in by[t]], wl=[int(w), int(l), 0],
                                 nt=1.0 if t == ch else 0.0, ct=1.0 if t in (ch, ru) else 0.0))
    hof = set()
    for r in tables(get(BB + '/awards/hof.html', False) or '').get('hof', []):
        c = cid(r.get('name_full'))
        if c and text(r.get('category')) == 'Coach' and c in names: hof.add(names[c])
    return rows, names, teams, hof, set()


def build_nhl():
    fin = finals(get(HR + '/playoffs/', False) or '', 'playoffs')
    fr = FRANCH['nhl']
    idx = get(HR + '/coaches/', False) or ''
    names, by = {}, defaultdict(list)
    for r in tables(idx).get('coaches', []):
        c = cid(r.get('coach'))
        if c: names[c] = text(r['coach']).rstrip('*')
    hall = {'Builder': set(), 'Player': set()}
    for r in tables(get(HR + '/awards/hhof.html', False) or '').get('hhof', []):
        k = text(r.get('category'))
        if k in hall: hall[k].add(N.key(text(r.get('name_full'))))
    for c in names:
        pg = get(f'{HR}/coaches/{c}.html', False)
        if not pg: continue
        for r in tables(pg).get('coach', []) or tables(pg).get('coaches', []):
            y = re.match(r'(\d{4})-(\d{2})', text(r.get('season', '')))
            t, g = code(r.get('team_name') or r.get('team_id')), num(r.get('games'))
            if y and t and g and text(r.get('lg_id') or r.get('league_id') or 'NHL') == 'NHL':
                by[(int(y.group(1)) + 1, t)].append((c, g))
    rows, teams = [], {}
    for y in range(1918, LAST['nhl'] + 1):
        if y == 2005: continue
        st = tables(get(f'{HR}/leagues/NHL_{y}.html', False) or '')
        seen = set()
        for k in [k for k in st if k.startswith('standings')]:
            conf = k.split('_', 1)[1] if '_' in k else 'L'
            for r in st[k]:
                t = code(r.get('team_name'))
                w, l, srs = num(r.get('wins')), num(r.get('losses')), num(r.get('srs'))
                if not t or t in seen or w is None or srs is None: continue
                seen.add(t)
                tie = (num(r.get('ties')) or 0) + (num(r.get('losses_ot')) or 0)
                f = fr.get(t, t)
                if y == LAST['nhl'] or f not in teams: teams[f] = re.sub(r'\*$', '', text(r['team_name'])).strip()
                cs = by.get((y, t), []); tot = sum(g for _, g in cs) or 1
                ch, ru = fin.get(y, (None, None))
                rows.append(dict(t=f, y=y, r=srs, conf=conf, cs=[[c, round(g / tot, 4)] for c, g in cs], wl=[int(w), int(l), int(tie)],
                                 nt=1.0 if t == ch else 0.0, ct=1.0 if t in (ch, ru) else 0.0))
    used = {c for r in rows for c, _ in r['cs']}
    names = {c: n for c, n in names.items() if c in used}
    hof = {n for n in names.values() if N.key(n) in hall['Builder']}
    return rows, names, teams, hof, {n for n in names.values() if N.key(n) in hall['Player'] and n not in hof}


def scale(rows):
    """per decade, the rating-to-wins probit scale s: Phi(r / s) = points share, least squares on a grid"""
    PHI = NormalDist().cdf
    by = defaultdict(list)
    for r in rows:
        w, l, t = r['wl']
        if w + l + t: by[str(max(min(r['y'] // 10 * 10, 2020), 1900))].append((r['r'], (w + .5 * t) / (w + l + t)))
    out = {}
    for d, L in by.items():
        best = None
        for i in range(2, 400):
            s = i * 0.05
            e = sum((PHI(x / s) - p) ** 2 for x, p in L)
            if best is None or e < best[1]: best = (s, e)
        out[d] = round(best[0], 2)
    return out


def build():
    out = {}
    for sp, fn in (('nba', build_nba), ('nhl', build_nhl)):
        rows, names, teams, hof, skip = fn()
        if not rows:
            print(sp, 'no pages cached, skipped'); continue
        out[sp] = dict(rows=rows, names=names, teams=teams, sig=scale(rows), hof=sorted({N.key(n) for n in hof}), hofSkip=sorted({N.key(n) for n in skip}))
        nc = sum(1 for r in rows if r['cs'])
        print(sp, len(rows), 'team-seasons', nc, 'with a coach', len(names), 'coaches', 'titles', sum(r['nt'] for r in rows), 'scale', out[sp]['sig'],
              'hall of fame', len(hof), 'left out of the fit', len(skip))
    with gzip.GzipFile(SRC, 'wb', mtime=0) as g:
        g.write(json.dumps(out, separators=(',', ':')).encode())
    print('wrote', SRC, os.path.getsize(SRC) // 1024, 'KB')


if __name__ == '__main__':
    a = sys.argv[1:]
    if 'pull' in a: pull()
    if 'build' in a or not a: build()
