#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""All-time head-coach history for CFB and CBB: pulls the free sources into scripts/.cache/coach_alltime and builds
the compact team-season file scripts/coach_alltime.py fits (scripts/data/coach_alltime_src.json.gz).

    python3 scripts/coach_alltime_pull.py pull     # every source below (about 2 hours, mostly polite delays)
    python3 scripts/coach_alltime_pull.py build    # caches -> scripts/data/coach_alltime_src.json.gz

Sources (all free; data/data_sources.json):
  CFB games     James Howell's historical scores, every game of every team that was major-college (FBS, I-A, pre-split
                major) in that season, 1869-2025: score, site, conference game flag, bowl / title-game notes.
  CFB coaches   Wikipedia: each program's "List of ... head football coaches" table (or the program article's head
                coaches section), else the program's season list (CFB Yearly Record Entry templates). Seasons with two
                coaches are split evenly.
  CFB OC / DC   Wikipedia season-article infoboxes (off_coach / def_coach), 1990-2025.
  CFB titles    Wikipedia's yearly table of NCAA-designated major selectors (team, coach, selectors).
  CBB           Sports Reference school index pages: every Division I season's SRS, record, conference record, NCAA
                result and head coach(es) with each one's record (mid-season changes split by games).
  Hall of Fame  Wikipedia lists: College Football Hall of Fame coaches; Naismith and National Collegiate Basketball
                Halls of Fame coaches.
Polite: Sports Reference at most 20 requests a minute (one every ~3.3 s); Wikipedia raw pages one a second, backing
off on 429.
"""
import glob
import gzip
import html
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import defaultdict
from statistics import NormalDist

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as N

CACHE = os.path.join(HERE, '.cache', 'coach_alltime')
SRC = os.path.join(HERE, 'data', 'coach_alltime_src.json.gz')
WIKI_UA = 'arkndjl.net ARKBOARD (https://arkndjl.net; site maintenance)'
JH = 'https://www.jhowell.net/cf/scores/'
SR = 'https://www.sports-reference.com/cbb/schools/'
LAST_CFB = 2025          # last finished FBS season in the scores archive
LAST_CBB = 2026          # last finished CBB season (2025-26)
CAP = 35                 # CFB rating: scoring margin capped at 35


def cdir(*p):
    d = os.path.join(CACHE, *p); os.makedirs(d, exist_ok=True); return d


def curl(url, out=None, ua=None, timeout=40):
    args = ['curl', '-s', '-m', str(timeout), '-w', '\n%{http_code}']
    if ua: args += ['-A', ua]
    r = subprocess.run(args + [url], capture_output=True, text=True, errors='replace')
    body, _, code = r.stdout.rpartition('\n')
    if out and code == '200': open(out, 'w').write(body)
    return code, body


def wiki_raw(title):
    """raw wikitext, following redirects (up to 3); '' if missing"""
    for hop in range(4):
        u = 'https://en.wikipedia.org/w/index.php?action=raw&title=' + urllib.parse.quote(title.replace(' ', '_'))
        for k in range(8):
            code, b = curl(u, ua=WIKI_UA)
            if code != '429': break
            time.sleep(30 * (k + 1))
        time.sleep(1.0)
        m = re.match(r'#REDIRECT\s*\[\[([^\]#|]+)', b, re.I)
        if code == '200' and m: title = m.group(1); continue
        return title, (b if code == '200' else '')
    return title, ''


# ---------------------------------------------------------------- pull
def pull_jh():
    d = cdir('jh'); _, idx = curl(JH + 'byname.htm')
    open(os.path.join(CACHE, 'jh_byname.htm'), 'w').write(idx)
    for p in sorted(set(re.findall(r'href="([^"/]+)\.htm"', idx)) - {'ScoresIndex'}):
        f = os.path.join(d, p + '.htm')
        if not os.path.exists(f): curl(JH + p + '.htm', f); time.sleep(1)


def pull_sr():
    d = cdir('sr'); f0 = os.path.join(CACHE, 'sr_schools.html')
    if not os.path.exists(f0): curl(SR, f0)
    for s in sorted(set(re.findall(r'href="/cbb/schools/([^/]+)/men/"', open(f0).read()))):
        f = os.path.join(d, s + '.html')
        if os.path.exists(f) and os.path.getsize(f) > 20000: continue
        for a in range(3):
            code, _ = curl(f'{SR}{s}/men/', f)
            if code == '200': break
            time.sleep(60 if code == '429' else 5)
        time.sleep(3.3)


# jhowell page -> Wikipedia program name (ESPN display names, then hand fixes)
WIKI_FIX = {'Massachusetts Minutemen': 'UMass Minutemen', "Hawai'i Rainbow Warriors": 'Hawaii Rainbow Warriors',
            'Pitt Panthers': 'Pittsburgh Panthers', 'UL Monroe Warhawks': 'Louisiana–Monroe Warhawks',
            'Miami (OH) RedHawks': 'Miami RedHawks', 'App State Mountaineers': 'Appalachian State Mountaineers',
            'San José State Spartans': 'San Jose State Spartans'}
WIKI_PAGE = {'Miami(Florida)': 'Miami Hurricanes', 'Miami(Ohio)': 'Miami RedHawks', 'AppalachianState': 'Appalachian State Mountaineers',
             'MiddleTennesseeState': 'Middle Tennessee Blue Raiders', 'SamHoustonState': 'Sam Houston Bearkats', 'Pacific': 'Pacific Tigers',
             'WichitaState': 'Wichita State Shockers', 'LongBeachState': 'Long Beach State 49ers', 'Carlisle': 'Carlisle Indians',
             'SantaClara': 'Santa Clara Broncos', 'DetroitMercy': 'Detroit Titans', 'Marquette': 'Marquette Golden Avalanche',
             'NewYorkUniversity': 'NYU Violets', 'CarnegieTech': 'Carnegie Tech Tartans', 'Centenary': 'Centenary Gentlemen',
             'Denver': 'Denver Pioneers', 'GeorgeWashington': 'George Washington Colonials', 'Gonzaga': 'Gonzaga Bulldogs',
             'StMarys': "Saint Mary's Gaels", 'SanFrancisco': 'San Francisco Dons', 'BostonUniversity': 'Boston University Terriers',
             'WashingtonLee': 'Washington and Lee Generals', 'Texas-Arlington': 'UT Arlington Mavericks',
             'FullertonState': 'Cal State Fullerton Titans', 'Creighton': 'Creighton Bluejays', 'Xavier': 'Xavier Musketeers',
             'Tampa': 'Tampa Spartans', 'StLouis': 'Saint Louis Billikens', 'LoyolaMarymount': 'Loyola Lions', 'McNeeseState': 'McNeese Cowboys',
             'Manhattan': 'Manhattan Jaspers', 'Bradley': 'Bradley Braves', 'Wesleyan': 'Wesleyan Cardinals', 'Stevens': 'Stevens Ducks',
             'Swarthmore': 'Swarthmore Garnet Tide', 'Birmingham-Southern': 'Birmingham–Southern Panthers',
             'Oglethorpe': 'Oglethorpe Stormy Petrels', 'Haverford': 'Haverford Fords', 'Vermont': 'Vermont Catamounts',
             'Whitman': 'Whitman Fighting Missionaries', 'Regis': 'Regis Rangers', 'Portland': 'Portland Pilots',
             'MississippiCollege': 'Mississippi College Choctaws', 'ColoradoCollege': 'Colorado College Tigers',
             'WesternState': 'Western Colorado Mountaineers', 'GramblingState': 'Grambling State Tigers', 'WorcesterTech': 'WPI Engineers',
             'SantaBarbara': 'UC Santa Barbara Gauchos', 'LosAngelesState': 'Cal State Los Angeles Golden Eagles'}
JH_ALIAS = {'Southern California': 'USC', 'Brigham Young': 'BYU', 'Louisiana State': 'LSU', 'Southern Methodist': 'SMU',
            'Texas Christian': 'TCU', 'Central Florida': 'UCF', 'Nevada-Las Vegas': 'UNLV', 'Texas-El Paso': 'UTEP',
            'Texas-San Antonio': 'UTSA', 'Alabama-Birmingham': 'UAB', 'Southern Mississippi': 'Southern Miss', 'Mississippi': 'Ole Miss',
            'Florida International': 'FIU', 'Florida Atlantic': 'FAU', 'Hawaii': "Hawai'i", 'Louisiana-Monroe': 'UL Monroe',
            'Massachusetts': 'UMass', 'Connecticut': 'UConn', 'Tennessee-Chattanooga': 'Chattanooga', 'Citadel': 'The Citadel',
            'Virginia Military Institute': 'VMI', 'Pennsylvania': 'Penn'}


def wiki_names():
    f = os.path.join(CACHE, 'wiki_names.json')
    if os.path.exists(f): return json.load(open(f))
    idx = open(os.path.join(CACHE, 'jh_byname.htm'), encoding='latin-1').read()
    pairs = [(p, re.sub(r'\s*\(\d.*', '', html.unescape(re.sub('<[^>]+>', '', n)), flags=re.S).strip())
             for p, n in re.findall(r'href="([^"/]+)\.htm"[^>]*>(.*?)</a>', idx, re.S) if p != 'ScoresIndex']
    _, js = curl('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000')
    ts = [t['team'] for t in json.loads(js)['sports'][0]['leagues'][0]['teams']]
    ix = {}
    for t in ts:
        for k in (t.get('location'), t.get('shortDisplayName')):
            if k: ix.setdefault(N.team_key(k), t)
    out = {}
    for p, n in pairs:
        if p in WIKI_PAGE: out[p] = WIKI_PAGE[p]; continue
        t = ix.get(N.team_key(JH_ALIAS.get(n, n))) or ix.get(N.team_key(n))
        if t: out[p] = WIKI_FIX.get(t['displayName'], t['displayName'])
    json.dump(out, open(f, 'w'), indent=0)
    return out


def pull_wiki():
    names = wiki_names(); dl, ds = cdir('wp_lists'), cdir('wp_seasonlists')
    for p, full in sorted(names.items()):
        f = os.path.join(dl, p + '.txt')
        if not os.path.exists(f):
            t, b = wiki_raw(f'List of {full} head football coaches')
            if not b: t, b = wiki_raw(f'{full} football')
            open(f, 'w').write(t + '\n' + b)
    hc = parse_lists()
    for p, full in sorted(names.items()):
        f = os.path.join(ds, p + '.txt')
        if len(hc.get(p, {}).get('rows', [])) >= 3 or os.path.exists(f): continue
        t, b = wiki_raw(f'List of {full} football seasons'); open(f, 'w').write(t + '\n' + b)
    for t in ('College_football_national_championships_in_NCAA_Division_I_FBS', 'List_of_College_Football_Hall_of_Fame_inductees_(coaches)',
              'List_of_members_of_the_Naismith_Memorial_Basketball_Hall_of_Fame', 'National_Collegiate_Basketball_Hall_of_Fame'):
        f = os.path.join(cdir('wp'), t + '.txt')
        if not os.path.exists(f): open(f, 'w').write(wiki_raw(t)[1])


def pull_coord(first=1990):
    names = wiki_names(); jh = parse_jh(); d = cdir('wp_seasons')
    jobs = sorted(((p, y) for p in names if p in jh for y in jh[p]['s'] if first <= int(y) <= LAST_CFB), key=lambda j: (-int(j[1]), j[0]))

    def work(js):
        for p, y in js:
            f = os.path.join(d, f'{p}_{y}.txt')
            if os.path.exists(f): continue
            _, body = wiki_raw(f'{y} {names[p]} football team')
            i = body.lower().find('{{infobox')
            open(f, 'w').write(body[i:i + 6000] if i >= 0 else '')
    th = [threading.Thread(target=work, args=(jobs[i::2],)) for i in range(2)]
    [t.start() for t in th]; [t.join() for t in th]


# ---------------------------------------------------------------- parse: CFB
def parse_jh():
    out = {}
    for f in sorted(glob.glob(os.path.join(CACHE, 'jh', '*.htm'))):
        p = os.path.basename(f)[:-4]; h = open(f, encoding='latin-1').read()
        m = re.search(r'<title>\s*(.*?)\s+Historical Scores', h, re.S | re.I)
        seasons = {}
        for tb in re.split(r'<table border="1">', h)[1:]:
            hm = re.search(r'<a name=(\d{4})>\d{4}-(.*?)(?:\s*\(([^)]*)\))?</a>', tb)
            if not hm: continue
            gs = []
            for row in re.findall(r'<tr>(.*?)</tr>', tb, re.S):
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
                if len(cells) < 6 or cells[3] not in ('W', 'L', 'T'): continue
                link = re.search(r'href="([^"#]+)\.htm', cells[2])
                otxt = html.unescape(re.sub('<[^>]+>', '', cells[2])).strip()
                try: pf, pa = int(cells[4]), int(cells[5])
                except ValueError: continue
                extra = [html.unescape(re.sub('<[^>]+>', '', c)).strip() for c in cells[6:]]
                site = next((e for e in extra if e.startswith('@')), '')
                note = next((e for e in extra if not e.startswith('@')), '')
                loc = cells[1].strip()
                gs.append(dict(d=cells[0].strip(), opp=link.group(1) if link else 'nonIA', cg=otxt.startswith('*'),
                               h=0 if (loc == 'vs.' and site) else (1 if loc == 'vs.' else -1), pf=pf, pa=pa, note=note))
            seasons[hm.group(1)] = dict(conf=(hm.group(3) or '').strip(), g=gs)
        out[p] = dict(name=html.unescape(m.group(1)).strip() if m else p, s=seasons)
    return out


def cfb_ratings(jh):
    """per season: ridge SRS on capped margin with a home edge; offense / defense on capped points (FCS pooled)"""
    games = defaultdict(dict)
    for p, v in jh.items():
        for y, s in v['s'].items():
            for g in s['g']:
                o = g['opp']; a, b = sorted([p, o]); k = (a, b, g['d'], g['pf'] + g['pa'])
                if k in games[int(y)]: continue
                sg = 1 if p == a else -1
                games[int(y)][k] = dict(a=a, b=b, m=(g['pf'] - g['pa']) * sg, h=g['h'] * sg,
                                        pa=g['pf'] if p == a else g['pa'], pb=g['pa'] if p == a else g['pf'])
    out = {}
    for y in sorted(games):
        G = list(games[y].values()); teams = sorted({g['a'] for g in G} | {g['b'] for g in G}); ix = {t: i for i, t in enumerate(teams)}
        n = len(teams); X = np.zeros((len(G), n + 1)); Xo = np.zeros((2 * len(G), 2 * n + 1)); yo = np.zeros(2 * len(G))
        ym = np.zeros(len(G))
        for r, g in enumerate(G):
            X[r, ix[g['a']]] = 1; X[r, ix[g['b']]] = -1; X[r, n] = g['h']; ym[r] = max(-CAP, min(CAP, g['m']))
            for q, (t, u, pts, hh) in enumerate([(g['a'], g['b'], g['pa'], g['h']), (g['b'], g['a'], g['pb'], -g['h'])]):
                Xo[2 * r + q, ix[t]] = 1; Xo[2 * r + q, n + ix[u]] = -1; Xo[2 * r + q, 2 * n] = hh / 2; yo[2 * r + q] = pts
        lam = np.full(n + 1, 2.0); lam[n] = .01
        if 'nonIA' in ix: lam[ix['nonIA']] = .5
        beta = np.linalg.solve(X.T @ X + np.diag(lam), X.T @ ym)
        yo2 = np.minimum(yo, yo.mean() + CAP); l2 = np.full(2 * n + 1, 2.0); l2[2 * n] = .01
        bo = np.linalg.solve(Xo.T @ Xo + np.diag(l2), Xo.T @ (yo2 - yo2.mean()))
        cnt = defaultdict(int)
        for g in G: cnt[g['a']] += 1; cnt[g['b']] += 1
        out[y] = dict(hfa=float(beta[n]), r={t: (float(beta[ix[t]]), float(bo[ix[t]]), float(bo[n + ix[t]]), cnt[t]) for t in teams if t != 'nonIA'})
    # points -> wins: probit scale per decade from the games themselves
    sig = {}
    from math import erf, sqrt
    byd = defaultdict(list)
    for p, v in jh.items():
        for y, s in v['s'].items():
            R = out.get(int(y), {}).get('r', {})
            for g in s['g']:
                o = g['opp']
                if o in R and p in R and g['pf'] != g['pa'] and p < o:
                    byd[int(y) // 10 * 10].append((R[p][0] - R[o][0] + g['h'] * out[int(y)]['hfa'], 1 if g['pf'] > g['pa'] else 0))
    for d, L in byd.items():
        a = np.array(L); best = None
        for s in np.arange(6, 30, .25):
            pr = np.clip(.5 * (1 + np.vectorize(erf)(a[:, 0] / s / sqrt(2))), 1e-6, 1 - 1e-6)
            ll = (a[:, 1] * np.log(pr) + (1 - a[:, 1]) * np.log(1 - pr)).sum()
            if best is None or ll > best[1]: best = (float(s), ll)
        sig[str(d)] = best[0]
    return out, sig


# programs whose Wikipedia pages have no coach table
MANUAL_HC = {'Carlisle': ('Pop Warner', list(range(1899, 1904)) + list(range(1907, 1915))),
             'Fordham': ('Jim Crowley', list(range(1933, 1942))), 'SantaClara': ('Buck Shaw', list(range(1936, 1943)))}
POST = re.compile(r'(?i)bowl|playoff|classic|semifinal|quarterfinal')


def cfb_conf_champs(jh):
    tab = defaultdict(lambda: defaultdict(lambda: [0, 0, 0])); ccg = {}
    for p, v in jh.items():
        for y, s in v['s'].items():
            c = s['conf']
            if not c or re.fullmatch(r'(?i)ind\.?|independent', c): continue
            for g in s['g']:
                if not g['cg'] or g['opp'] == 'nonIA' or POST.search(g['note'] or ''): continue
                if re.search(r'(?i)championship', g['note'] or ''):
                    ccg[(int(y), c)] = p if g['pf'] > g['pa'] else g['opp']; continue
                r = tab[(int(y), c)][p]; r[0 if g['pf'] > g['pa'] else 1 if g['pf'] < g['pa'] else 2] += 1
    champ = {}
    for k, T in tab.items():
        if k in ccg: champ[k] = {ccg[k]: 1.0}; continue
        pct = {t: (r[0] + .5 * r[2]) / sum(r) for t, r in T.items() if sum(r) >= 2}
        if not pct: continue
        b = max(pct.values()); win = [t for t, x in pct.items() if abs(x - b) < 1e-9]
        champ[k] = {t: 1 / len(win) for t in win}
    return champ


def _clean(s):
    s = re.sub(r'<ref[^>]*/>', '', s); s = re.sub(r'<ref.*?</ref>', '', s, flags=re.S)
    s = re.sub(r'\{\{#tag:ref.*?\}\}', '', s, flags=re.S)
    return re.sub(r'\{\{\s*(?:ndash|snd|spaced ndash|–)\s*\}\}', '–', s, flags=re.I)


def _years(c):
    c = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', c)
    c = re.sub(r'\{\{(?:nts|ntsh|sort)\|[^|}]*\|?([^}]*)\}\}', r'\1', c)
    c = re.sub(r'\(.*?\)', '', re.sub(r'<[^>]+>', '', c).replace('&ndash;', '–').replace('—', '–'))
    if not re.fullmatch(r'[\s\d–\-,;/present]+', c.strip()) or not re.search(r'\d{4}', c): return None
    out, prev = [], None
    for part in re.split(r'[,;/]', c):
        mm = re.findall(r'\d{4}|\d{2}|present', part)
        if not mm: continue
        if len(mm[0]) == 2:
            if prev is None: continue
            mm[0] = str(prev)[:2] + mm[0]
        a = int(mm[0]); b = mm[-1]; prev = a
        if re.search(r'[–\-]\s*$', part) and len(mm) == 1: b = 'present'
        b = LAST_CFB if b == 'present' else (int(b) if len(b) == 4 else int(str(a)[:2] + b))
        out += list(range(a, max(a, b) + 1))
    return out


def _name(c):
    m = re.search(r'\{\{\s*sortname\s*\|([^|}]+)\|([^|}]+)(?:\|([^|}]+))?', c, re.I)
    if m:
        nm = m.group(1).strip() + ' ' + m.group(2).strip(); link = (m.group(3) or '').strip()
        return nm, (link if link and '=' not in link else nm)
    m = re.search(r'\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]', c)
    if m and not re.match(r'\d{4}', m.group(1)) and 'File:' not in m.group(1):
        return (m.group(2) or m.group(1)).strip(), m.group(1).strip()
    t = re.sub(r"\{\{[^}]*\}\}|<[^>]+>|''+", '', c).strip()
    return (t, t) if re.fullmatch(r"[A-Z][A-Za-z.'\- ]{3,40}", t) else None


def _coach_table(txt):
    rows = []
    for tb in re.findall(r'\{\|.*?\n\|\}', _clean(txt), re.S):
        if not re.search(r'(?i)year|season|tenure|term', tb[:3000]): continue
        for r in re.split(r'\n\|-[^\n]*', tb)[1:]:
            cells = []
            for line in r.split('\n'):
                line = line.strip()
                if not line or line[0] not in '|!': continue
                for c in re.split(r'\|\||!!', line[1:]):
                    head = c.split('|')[0]
                    if '|' in c and not re.search(r'\[\[|\{\{', head) and re.search(r'(?i)scope|style|rowspan|align|class|data-sort', head):
                        c = c.split('|', 1)[1]
                    cells.append(c.strip())
            nm = ys = None
            for c in cells:
                if ys is None:
                    y = _years(c)
                    if y: ys = y; continue
                if nm is None and not re.fullmatch(r'[\d.*]*', c.strip()):
                    n = _name(c)
                    if n and not re.search(r'(?i)interim|vacant|no coach|none|unknown|^no\b', n[0]): nm = n
            if nm and ys: rows.append((nm[0], nm[1], ys))
    return rows


def parse_lists():
    out = {}
    for f in sorted(glob.glob(os.path.join(CACHE, 'wp_lists', '*.txt'))):
        title, body = open(f).read().split('\n', 1)
        if not title.startswith('List of'):
            m = None
            for pat in (r'Head coach(?:es|ing history|ing records)?', r'All-time head coaches|Coaching history|Coaches'):
                m = re.search(r'\n(==+)\s*(?:' + pat + r')\s*\1\s*\n', body, re.I)
                if m: break
            if not m: out[os.path.basename(f)[:-4]] = dict(title=title, rows=[]); continue
            rest = body[m.end():]; n = re.search(r'\n==[^=]', rest); body = rest[:n.start()] if n else rest
        out[os.path.basename(f)[:-4]] = dict(title=title, rows=_coach_table(body))
    return out


def parse_seasonlists():
    out = {}
    for f in sorted(glob.glob(os.path.join(CACHE, 'wp_seasonlists', '*.txt'))):
        title, body = (open(f).read().split('\n', 1) + [''])[:2]; rows = []
        for blk in re.findall(r'\{\{\s*CFB Yearly Record Entry(.*?)\n\s*\}\}', body, re.S | re.I):
            y = re.search(r'\|\s*year\s*=\s*(?:\[\[[^\]|]*\|)?(\d{4})', blk); n = re.search(r'\|\s*name\s*=\s*(.*?)\s*(?=\n\s*\|)', blk, re.S)
            if not y or not n: continue
            nm = n.group(1).strip(); m = re.search(r'\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]', nm)
            if m: rows.append(((m.group(2) or m.group(1)).strip(), m.group(1).strip(), [int(y.group(1))])); continue
            disp = re.sub(r"<.*?>|\{\{.*?\}\}|''+", '', nm).strip()
            for part in re.split(r'\s*(?:/|,|&| and )\s*', disp):
                if part and not re.search(r'(?i)no coach|none|unknown|interim', part): rows.append((part, None, [int(y.group(1))]))
        out[os.path.basename(f)[:-4]] = rows
    return out


def parse_coord():
    def people(v):
        v = re.sub(r'<ref.*?(</ref>|/>)', '', v, flags=re.S)
        v = re.sub(r'\{\{(?:sortname|nowrap)\|([^}|]+)\|([^}|]+)\|?([^}|]*)[^}]*\}\}',
                   lambda m: '[[' + (m.group(3) or m.group(1) + ' ' + m.group(2)) + '|' + m.group(1) + ' ' + m.group(2) + ']]', v, flags=re.I)
        out = [(a.strip(), (b or a).strip()) for a, b in re.findall(r'\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]', v)
               if not re.search(r'(?i)season|football|offensive|defensive|coordinator|interim|^\d', a)]
        if not out:
            for x in re.split(r'<br\s*/?>|,|;|\band\b|/', re.sub(r'\(.*?\)|\{\{.*?\}\}', '', v)):
                x = re.sub(r"[\[\]']", '', x).strip()
                if re.fullmatch(r"[A-Z][A-Za-z.'\- ]{3,40}", x) and not re.search(r'(?i)interim|season', x): out.append((None, x))
        return out[:2]
    res = {}
    for f in glob.glob(os.path.join(CACHE, 'wp_seasons', '*.txt')):
        p, y = os.path.basename(f)[:-4].rsplit('_', 1); t = open(f).read(); d = {}
        for fld, key in (('off_coach', 'oc'), ('def_coach', 'dc')):
            m = re.search(r'\|\s*' + fld + r'\s*=(.*?)(?=\n\s*\||\n\}\})', t, re.S)
            if m: d[key] = people(m.group(1))
        if d: res[f'{p}|{y}'] = d
    return res


def parse_champs(jpage):
    t = open(os.path.join(CACHE, 'wp', 'College_football_national_championships_in_NCAA_Division_I_FBS.txt')).read()
    a = t.find('===Yearly national championship selections from major selectors==='); b = t.find('===Total championship selections', a)
    tb = re.sub(r'<ref[^>]*/>', '', t[a:b]); tb = re.sub(r'<ref.*?</ref>', '', tb, flags=re.S)
    year = None; L = defaultdict(list)
    for r in re.split(r'\n\|-[^\n]*', tb):
        r = r.strip().split('\n')[0]
        if not r.startswith('|'): continue
        cells = [c.strip() for c in re.split(r'\|\|', r.lstrip('|'))]
        m = re.search(r'\[\[(\d{4}) [^\]|]*season\|', cells[0])
        if m: year = int(m.group(1)); cells = cells[1:]
        if len(cells) < 4 or year is None: continue
        tm = re.search(r'\[\[(\d{4}) ([^\]|]+?) football team\|([^\]]+)\]\]', cells[0])
        if not tm: continue
        sels = [s for s in re.findall(r"([A-Za-z&/()]+)", re.sub(r'<sup>.*?</sup>', '', cells[3])) if s]
        L[year].append((jpage(tm.group(3).strip("'")), sels))
    nat = defaultdict(float); COACH = re.compile(r'^(UP|UPI|USA.*|USAT.*)$')
    for y, X in L.items():
        if y >= 1936:   # AP from 1936, AP + Coaches Poll halves from 1950
            for p, s in X:
                nat[(p, y)] += (1.0 if y < 1950 else .5) * ('AP' in s) + (.5 * any(COACH.match(x) for x in s) if y >= 1950 else 0)
        else:           # before polls: share of major-selector picks
            cnt = [(p, len([x for x in s if re.fullmatch(r'[A-Z][A-Za-z&()/]*', x)])) for p, s in X]; tot = sum(c for _, c in cnt)
            for p, c in cnt: nat[(p, y)] += c / tot if tot else 0
    return {k: v for k, v in nat.items() if v}


def hof_keys(sport):
    files = {'cfb': ['List_of_College_Football_Hall_of_Fame_inductees_(coaches)'],
             'cbb': ['List_of_members_of_the_Naismith_Memorial_Basketball_Hall_of_Fame', 'National_Collegiate_Basketball_Hall_of_Fame']}[sport]
    ks = set()
    for fn in files:
        t = open(os.path.join(CACHE, 'wp', fn + '.txt')).read()
        if 'Naismith' in fn: t = t[t.find('===Coaches==='):t.find('===Contributors===')]
        for a, b in re.findall(r'\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]', t):
            for x in (a, b):
                if x: ks.add(N.key(re.sub(r'\s*\(.*?\)', '', x)))
    return sorted(ks)


def build_cfb():
    jh = parse_jh(); R, sig = cfb_ratings(jh); champ = cfb_conf_champs(jh)
    jk = {N.team_key(v['name']): p for p, v in jh.items()}
    EX = {'USC': 'SouthernCalifornia', 'BYU': 'BrighamYoung', 'LSU': 'LouisianaState', 'SMU': 'SouthernMethodist', 'TCU': 'TexasChristian',
          'Ole Miss': 'Mississippi', 'Miami (FL)': 'Miami(Florida)', 'Miami': 'Miami(Florida)', 'Penn': 'Pennsylvania', 'Pitt': 'Pittsburgh',
          'UCF': 'CentralFlorida', 'Cal': 'California'}
    nat = parse_champs(lambda n: EX.get(n) or jk.get(N.team_key(n)))
    hc = parse_lists(); sl = parse_seasonlists()
    # one id per coach: the Wikipedia article title; season-list names without a link map to a list-page id by name key
    bykey = defaultdict(set)
    for v in hc.values():
        for nm, link, ys in v['rows']: bykey[N.key(nm)].add(link)
    cs = defaultdict(list); names = {}
    for p, v in hc.items():
        if len(v['rows']) < 3: continue
        for nm, link, ys in v['rows']:
            names.setdefault(link, nm)
            for y in ys: cs[(p, y)].append(link)
    for p, rows in sl.items():
        if len(hc.get(p, {}).get('rows', [])) >= 3: continue
        for nm, link, ys in rows:
            k = bykey.get(N.key(nm)); cid = link or (next(iter(k)) if k and len(k) == 1 else nm)
            names.setdefault(cid, nm)
            for y in ys:
                if cid not in cs[(p, y)]: cs[(p, y)].append(cid)
    for p, (nm, yrs) in MANUAL_HC.items():
        for y in yrs:
            if not cs.get((p, y)): cs[(p, y)] = [nm]; names.setdefault(nm, nm)
    co = parse_coord(); coord = {}
    for k, d in co.items():
        p, y = k.split('|')
        for role in ('oc', 'dc'):
            L = [(link or N.key(nm), nm) for link, nm in d.get(role, [])]
            for cid, nm in L: names.setdefault(cid, nm)
            if L: coord.setdefault(k, {})[role] = [c for c, _ in L]
    rows = []
    for p, v in jh.items():
        for ys, s in v['s'].items():
            y = int(ys)
            if y < 1900 or y > LAST_CFB or y not in R or p not in R[y]['r']: continue
            r = R[y]['r'][p]; L = cs.get((p, y), [])
            cf = s['conf'] if s['conf'] and not re.fullmatch(r'(?i)ind\.?|independent', s['conf']) else None
            w = sum(g['pf'] > g['pa'] for g in s['g']); l = sum(g['pf'] < g['pa'] for g in s['g'])
            rows.append(dict(t=p, y=y, r=round(r[0], 3), o=round(r[1], 3), d=round(r[2], 3), conf=cf,
                             cs=[(c, 1 / len(L)) for c in L], nt=round(nat.get((p, y), 0.0), 4),
                             ct=round(champ.get((y, s['conf']), {}).get(p, 0.0), 4) if cf else 0.0, wl=[w, l, len(s['g']) - w - l],
                             oc=coord.get(f'{p}|{y}', {}).get('oc', []), dc=coord.get(f'{p}|{y}', {}).get('dc', [])))
    teams = {p: v['name'] for p, v in jh.items()}
    return dict(rows=rows, names=names, sig=sig, teams=teams, hof=hof_keys('cfb'))


def build_cbb():
    nd = NormalDist(); R = []
    for f in sorted(glob.glob(os.path.join(CACHE, 'sr', '*.html'))):
        s = os.path.basename(f)[:-5]; h = open(f, encoding='utf-8', errors='ignore').read()
        title = re.search(r'<h1>\s*<span>[^<]*</span>\s*<span>([^<]+)</span>', h)
        for r in re.findall(r'<tr[^>]*>(.*?)</tr>', h, re.S):
            if 'data-stat="season"' not in r or '/men/' not in r: continue
            d = dict(re.findall(r'data-stat="([a-z_]+)"[^>]*>(.*?)</t[dh]>', r, re.S))
            m = re.search(r'/men/(\d{4})\.html', d.get('season', ''))
            if not m: continue
            num = lambda k: float(d[k]) if re.fullmatch(r'-?[\d.]+', d.get(k, '').strip()) else None
            cm = re.search(r'/conferences/([^/]+)/', d.get('conf_abbr', ''))
            co = [(a, html.unescape(b), int(w), int(l)) for a, b, w, l in re.findall(r'/cbb/coaches/([^.]+)\.html">([^<]+)</a>\s*\((\d+)-(\d+)\)', d.get('coaches', ''))]
            R.append(dict(t=s, y=int(m.group(1)), conf=cm.group(1) if cm else None, w=num('wins'), l=num('losses'), cw=num('wins_conf'),
                          cl=num('losses_conf'), srs=num('srs'), ps=num('pts_per_g'), pa=num('opp_pts_per_g'),
                          rnd=html.unescape(re.sub('<[^>]+>', '', d.get('round_max', ''))).strip(), co=co))
    R = [r for r in R if r['y'] <= LAST_CBB and r['w'] is not None and r['l'] is not None and r['w'] + r['l'] >= 5]
    pb = lambda w, g: nd.inv_cdf((w + 1) / (g + 2))
    cm = defaultdict(list)
    for r in R: cm[(r['y'], r['conf'])].append(r)
    for r in R:
        o = [x for x in cm[(r['y'], r['conf'])] if x is not r]
        r['pb'] = pb(r['w'], r['w'] + r['l']); r['cpb'] = float(np.mean([pb(x['w'], x['w'] + x['l']) for x in o])) if o and r['conf'] else 0.0
    # before 1950 (no SRS): rating from win% and the conference's win% (fit on 1950-65)
    fit = [r for r in R if 1950 <= r['y'] <= 1965 and r['srs'] is not None]
    beta = np.linalg.lstsq(np.array([[1, r['pb'], r['cpb']] for r in fit]), np.array([r['srs'] for r in fit]), rcond=None)[0]
    for r in R:
        r['est'] = r['srs'] is None
        if r['est']: r['srs'] = float(beta[0] + beta[1] * r['pb'] + beta[2] * r['cpb'])
    R = [r for r in R if r['y'] >= 1939]
    sig = {}
    for dec in range(1950, 2030, 10):
        L = [r for r in R if r['y'] // 10 * 10 == dec and r['ps'] is not None and r['pa'] is not None]
        best = min(((sum((nd.cdf((r['ps'] - r['pa']) / s) - r['w'] / (r['w'] + r['l'])) ** 2 * (r['w'] + r['l']) for r in L), float(s))
                    for s in np.arange(5, 25, .25)))
        sig[str(dec)] = best[1]
    sig['1930'] = sig['1940'] = sig['1950']
    ct = {}
    for (y, c), L in cm.items():
        if not c or c == 'independent': continue
        pct = {x['t']: x['cw'] / (x['cw'] + x['cl']) for x in L if x['cw'] is not None and x['cl'] is not None and x['cw'] + x['cl'] >= 4}
        if len(pct) < 3: continue
        b = max(pct.values()); win = [t for t, v in pct.items() if abs(v - b) < 1e-9]
        for t in win: ct[(t, y)] = 1 / len(win)
    rows, names = [], {}
    for r in R:
        co = [c for c in r['co'] if c[2] + c[3] > 0]; tot = sum(c[2] + c[3] for c in co)
        for c in co: names[c[0]] = c[1]
        rnd = r['rnd']
        rows.append(dict(t=r['t'], y=r['y'], r=round(r['srs'], 3), est=r['est'], conf=r['conf'] if r['conf'] != 'independent' else None,
                         cs=[(c[0], round((c[2] + c[3]) / tot, 4)) for c in co] if tot else [],
                         nt=1.0 if rnd.startswith('Won NCAA') else 0.0, ff=1.0 if ('National' in rnd or 'Final Four' in rnd) else 0.0,
                         ct=round(ct.get((r['t'], r['y']), 0.0), 4), wl=[int(r['w']), int(r['l']), 0]))
    f0 = open(os.path.join(CACHE, 'sr_schools.html')).read()
    teams = {s: html.unescape(n) for s, n in re.findall(r'href="/cbb/schools/([^/]+)/men/">([^<]+)</a>', f0)}
    return dict(rows=rows, names=names, sig=sig, teams=teams, hof=hof_keys('cbb'), pseudo=[round(float(b), 3) for b in beta])


def main():
    if 'pull' in sys.argv:
        th = [threading.Thread(target=f) for f in (pull_jh, pull_sr)]
        [t.start() for t in th]
        pull_wiki(); pull_coord(); [t.join() for t in th]
    if 'build' in sys.argv:
        out = dict(cfb=build_cfb(), cbb=build_cbb())
        with gzip.open(SRC, 'wt') as f: json.dump(out, f, separators=(',', ':'))
        print('cfb rows', len(out['cfb']['rows']), 'cbb rows', len(out['cbb']['rows']), SRC)


if __name__ == '__main__':
    main()
