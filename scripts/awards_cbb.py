# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB national player of the year race (the Wooden Award): candidate pools and features for
scripts/awards_research.py and scripts/awards.py.

History: Barttorvik player seasons (project files cbb/backtest/research_seasons.csv, the CBB board's research table)
and team results (barttorvik.com/<season>_team_results.json, scripts/.cache/awards/bt_<season>.json); winners from
Wikipedia's Wooden Award page."""
import csv, html, json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM
from awards_football import wiki, cells

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'awards')
SEASONS_CSV = '/mnt/project-files/cbb/backtest/research_seasons.csv'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
FIRST, LAST = 2008, 2026
WOODEN_COLS = ['bpm', 'ppg', 'wp', 'barthag', 'mpg', 'p5']


def team_results(season, fresh=False):
    fn = os.path.join(CACHE, f'bt_{season}.json')
    if not fresh and os.path.exists(fn): return json.load(open(fn))
    for a in range(3):
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(
                f'https://barttorvik.com/{season}_team_results.json', headers={'User-Agent': UA}), timeout=60).read())
            json.dump(d, open(fn, 'w'))
            time.sleep(1)
            return d
        except Exception as e:
            print('barttorvik', season, e); time.sleep(10)
    return []


def teams(season, fresh=False):
    out = {}
    for r in team_results(season, fresh):
        try:
            w, l = (int(x) for x in str(r[3]).split('-')[:2])
        except ValueError:
            continue
        out[r[1]] = {'wp': w / max(w + l, 1), 'barthag': float(r[8]), 'rk': int(r[0])}
    return out


def winners(page='John_R._Wooden_Award'):
    """{season: (player, school)} from the men's table of an award's Wikipedia page (the first listed of co-winners)"""
    out = {}
    for t in re.findall(r'<table class="wikitable.*?</table>', wiki(page), re.S)[1:2]:
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
            c = cells(tr)
            m = re.match(r"^(\d{4})[–-](\d{2,4})", c[0] if c else '')
            if m and len(c) > 2 and int(m.group(1)) + 1 not in out:
                out[int(m.group(1)) + 1] = (re.sub(r'\(\d+\)|\[.*?\]|[*†‡]', '', c[1]).strip(), c[2])
    return out


def row(r, tm):
    f = lambda k: float(r[k]) if r.get(k) not in (None, '') else 0.0
    mpg = f('min_per') / 100 * 40
    t = tm.get(r['team'], {'wp': .5, 'barthag': .5, 'rk': 200})
    return {'id': r['pid'], 'n': r['name'], 'tm': r['team'], 'conf': r['conf'], 'cls': r['yr'], 'gp': f('gp'),
            'min_per': f('min_per'), 'mpg': mpg, 'bpm': f('bpm'), 'ppg': f('pts40') * mpg / 40,
            'wp': t['wp'], 'barthag': t['barthag'], 'p5': f('p5'),
            'dbpm': f('dbpm'), 'blk': f('blk'), 'stl': f('stl'), 'drb': f('drb'),
            'role': r.get('role') or ('Combo G' if f('guard') or 0 < f('hti') <= 76 else 'PF/C' if f('big') or f('hti') >= 81 else 'Wing F')}


def seasons_data():
    W = winners()
    by = {}
    for r in csv.DictReader(open(SEASONS_CSV)):
        by.setdefault(int(r['year']), []).append(r)
    races = {'wooden': []}
    for s in range(FIRST, LAST + 1):
        tm = teams(s)
        pool = [row(r, tm) for r in by.get(s, []) if float(r['min_per'] or 0) >= 40 and float(r['gp'] or 0) >= 20]
        order = []
        if s in W:
            m = NM.Matcher(pool, name='n', team='tm', pos=None, sport='basketball')
            hit, _ = m.find(W[s][0], team=W[s][1])
            if hit is None: hit, _ = m.find(W[s][0])
            if hit is None: print('cbb', s, 'winner outside pool', W[s])
            else: order = [pool.index(hit)]
        races['wooden'].append((s, pool, order))
    return races


# ---------------------------------------------------------------- races added Nov 23 2026 (scripts/awards_bball.py)
DPOY_COLS = ['dbpm', 'blk', 'stl', 'drb', 'wp', 'barthag', 'mpg', 'p5']
G_ROLES = {'Pure PG', 'Scoring PG', 'Combo G'}
# Barttorvik's role is a playing style, not the listed position the awards go by: each pool takes the adjacent roles
# too (widened from the preregistered sets after the first pass left listed-position winners outside; prereg.md)
ROLE_POOL = {'cousy': G_ROLES, 'west': {'Combo G', 'Wing G', 'Scoring PG', 'Wing F'},
             'erving': {'Combo G', 'Wing G', 'Wing F', 'Stretch 4'},
             'malone': {'Wing F', 'Stretch 4', 'PF/C', 'C'}, 'kareem': {'PF/C', 'C'}}
# key: (Wikipedia page, voter model cols, null, first season, pool rule on a row)
MORE = {'naismith': ('Naismith_College_Player_of_the_Year', WOODEN_COLS, ['bpm'], FIRST, None),
        'ap': ('Associated_Press_College_Basketball_Player_of_the_Year', WOODEN_COLS, ['bpm'], FIRST, None),
        'dpoy': ('NABC_Defensive_Player_of_the_Year', DPOY_COLS, ['dbpm'], FIRST, None),
        'frosh': ('USBWA_National_Freshman_of_the_Year', WOODEN_COLS, ['bpm'], FIRST, lambda r: r['cls'] == 'Fr'),
        'cousy': ('Bob_Cousy_Award', WOODEN_COLS, ['bpm'], FIRST, lambda r: r['role'] in ROLE_POOL['cousy']),
        'west': ('Jerry_West_Award', WOODEN_COLS, ['bpm'], 2015, lambda r: r['role'] in ROLE_POOL['west']),
        'erving': ('Julius_Erving_Award', WOODEN_COLS, ['bpm'], 2015, lambda r: r['role'] in ROLE_POOL['erving']),
        'malone': ('Karl_Malone_Award', WOODEN_COLS, ['bpm'], 2015, lambda r: r['role'] in ROLE_POOL['malone']),
        'kareem': ('Kareem_Abdul-Jabbar_Award', WOODEN_COLS, ['bpm'], 2015, lambda r: r['role'] in ROLE_POOL['kareem'])}


def find(pool, w):
    m = NM.Matcher(pool, name='n', team='tm', pos=None, sport='basketball')
    hit, _ = m.find(w[0], team=w[1])
    if hit is None: hit, _ = m.find(w[0])
    return hit


def more_races(base=None):
    """{award: [(season, pool, [winner index])]} for the races in MORE, from the same season pools as the Wooden"""
    base = base or seasons_data()['wooden']
    out = {}
    for aw, (page, _, _, first, rule) in MORE.items():
        W = winners(page)
        out[aw] = []
        for s, pool, _ in base:
            if s < first: continue
            pl = [r for r in pool if rule is None or rule(r)]
            order = []
            if s in W:
                hit = find(pl, W[s])
                if hit is None:
                    print('cbb', aw, s, 'winner outside pool', W[s], 'role' if find(pool, W[s]) else '',
                          (find(pool, W[s]) or {}).get('role'), (find(pool, W[s]) or {}).get('cls'))
                else: order = [pl.index(hit)]
            out[aw].append((s, pl, order))
    return out
