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


def winners():
    out = {}
    for t in re.findall(r'<table class="wikitable.*?</table>', wiki('John_R._Wooden_Award'), re.S)[1:2]:
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
            c = cells(tr)
            m = re.match(r"^(\d{4})[–-](\d{2,4})", c[0] if c else '')
            if m and len(c) > 2:
                out[int(m.group(1)) + 1] = (re.sub(r'\(\d+\)|\[.*?\]', '', c[1]).strip(), c[2])
    return out


def row(r, tm):
    f = lambda k: float(r[k]) if r.get(k) not in (None, '') else 0.0
    mpg = f('min_per') / 100 * 40
    t = tm.get(r['team'], {'wp': .5, 'barthag': .5, 'rk': 200})
    return {'id': r['pid'], 'n': r['name'], 'tm': r['team'], 'conf': r['conf'], 'cls': r['yr'], 'gp': f('gp'),
            'min_per': f('min_per'), 'mpg': mpg, 'bpm': f('bpm'), 'ppg': f('pts40') * mpg / 40,
            'wp': t['wp'], 'barthag': t['barthag'], 'p5': f('p5')}


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
