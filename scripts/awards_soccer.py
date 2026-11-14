# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Ballon d'Or race: candidate pools and features for scripts/awards_more.py and scripts/awards.py.

History: each year's vote from its Wikipedia page (ranking table), tied to the club season ending that year; players
and GAR from the board's big-five files (static/data/soccer-war/<S>.json), league champions and Champions League
finalists from the club game archive (scripts/soccer_games_hist.json.gz), World Cup / Euro / Copa America winners
and each scorer's national side from martj42's international results. Stdlib only."""
import collections, csv, gzip, io, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
WAR = os.path.join(ROOT, 'static', 'data', 'soccer-war')
FIRST, LAST = 2015, 2026
SKIP = {2020}
POOL_N = 150
COLS = ['gar', 'ga', 'lgw', 'ucl', 'natw', 'prev']
NULL = ['gar']
PRE = ['Cristiano Ronaldo', 'Lionel Messi', 'Lionel Messi', 'Lionel Messi', 'Lionel Messi', 'Cristiano Ronaldo',
       'Cristiano Ronaldo']                                    # 2008-14
MAJOR = ('FIFA World Cup', 'UEFA Euro', 'Copa América')
MJ = 'https://raw.githubusercontent.com/martj42/international_results/master/'


def votes(year):
    """[(player, nation or None)] in voting order from the year's Wikipedia page (the men's ranking tables)"""
    import awards_football as F
    h = F.wiki(f"{year}_FIFA_Ballon_d%27Or" if year == 2015 else f"{year}_Ballon_d%27Or")
    out = []
    for t in re.findall(r'<table class="wikitable.*?</table>', h, re.S):
        rows = [F.cells(tr) for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)]
        if not rows or 'Player' not in rows[0] or rows[0][0] != 'Rank': continue
        if out and (len(rows) < 6 or rows[1][0].lstrip('=') in ('1', '1st')): break      # the next award's table
        hd = rows[0]
        ni = next((i for i, c in enumerate(hd) if c in ('Nationality', 'National team')), None)
        for r in rows[1:]:
            if len(r) < len(hd) - 1: continue
            n = re.sub(r'\[.*?\]', '', r[hd.index('Player')]).strip()
            if n: out.append((n, r[ni] if ni is not None and len(r) > ni else None))
        if len(out) >= 10: break
    return out


def mj(name):
    import awards_football as F
    fn = os.path.join(F.CACHE, 'wiki', 'mj_' + name)
    if not os.path.exists(fn):
        import urllib.request
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        d = urllib.request.urlopen(urllib.request.Request(MJ + name, headers={'User-Agent': 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'}), timeout=120).read()
        open(fn, 'wb').write(d)
    return list(csv.DictReader(open(fn, encoding='utf-8')))


def nat_winners():
    """{season end year: {nations that won a major tournament in that season, August to July}}: the December 2022
    World Cup belongs to 2022-23"""
    sh = {(r['date'], r['home_team'], r['away_team']): r['winner'] for r in mj('shootouts.csv')}
    last = {}
    for r in mj('results.csv'):
        if r['tournament'] not in MAJOR or not r['home_score'].isdigit(): continue
        k = (r['tournament'], r['date'][:4])
        if k not in last or r['date'] >= last[k]['date']: last[k] = r
    out = collections.defaultdict(set)
    for (t, y), r in last.items():
        hs, as_ = int(r['home_score']), int(r['away_score'])
        w = r['home_team'] if hs > as_ else r['away_team'] if as_ > hs else sh.get((r['date'], r['home_team'], r['away_team']))
        if w: out[int(r['date'][:4]) + (1 if r['date'][5:7] >= '08' else 0)].add(w)
    return out


def scorer_nation():
    """{name key: the national side he scored most for}"""
    c = collections.defaultdict(collections.Counter)
    for r in mj('goalscorers.csv'):
        if r.get('scorer') and r.get('own_goal') != 'TRUE' and r['date'] >= '2005': c[NM.key(r['scorer'])][r['team']] += 1
    return {k: v.most_common(1)[0][0] for k, v in c.items()}


def club_honours():
    """({(league, S): champion team id}, {S: (Champions League winner, loser of the final)})"""
    H = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))
    pts, fin = collections.defaultdict(collections.Counter), {}
    for g in H:
        if g.get('hs') is None or g.get('as') is None: continue
        S = int(g['day'][:4]) + (1 if g['day'][5:7] >= '07' else 0)
        if g['lg'].endswith('.1'):
            a, b = (3, 0) if g['hs'] > g['as'] else (0, 3) if g['as'] > g['hs'] else (1, 1)
            pts[(g['lg'], S)][g['h']] += a + (g['hs'] - g['as']) / 1000; pts[(g['lg'], S)][g['a']] += b + (g['as'] - g['hs']) / 1000
        elif g['lg'] == 'uefa.champions' and f'{S}-05-01' <= g['day'] <= f'{S}-06-15':
            if S not in fin or g['day'] > fin[S]['day']: fin[S] = g
    champ = {k: v.most_common(1)[0][0] for k, v in pts.items()}
    ucl = {S: ((g['h'], g['a']) if g.get('hw') else (g['a'], g['h'])) for S, g in fin.items()}
    return champ, ucl


def season_rows(S):
    """one line a player: clubs summed, club = most minutes"""
    d = json.load(open(os.path.join(WAR, f'{S}.json')))
    esp = json.load(open(os.path.join(ROOT, 'data', 'soccer_logos.json'))).get('espn', {})    # Understat name -> ESPN id
    out = {}
    for r in d['players']:
        x = out.setdefault(r['p'], {'id': r['p'], 'n': r['n'], 'gar': 0.0, 'g': 0, 'a': 0, 'min': 0, '_m': -1})
        x['gar'] += r.get('gar') or 0; x['g'] += r.get('g') or 0; x['a'] += r.get('a') or 0; x['min'] += r.get('min') or 0
        if (r.get('min') or 0) > x['_m']:
            x['_m'] = r.get('min') or 0
            x.update(team=r['team'], lg=r['lg'], tid=esp.get(r['team']), pos=r.get('pos'))
    return list(out.values()), d


def races():
    champ, ucl = club_honours()
    natw, nation = nat_winners(), scorer_nation()
    prev = collections.Counter(NM.key(n) for n in PRE)
    out = []
    for S in range(FIRST, LAST + 1):
        if S in SKIP: continue
        V = votes(S)
        vn = {NM.key(n): c for n, c in V if c}
        rows, _ = season_rows(S)
        pool = sorted(rows, key=lambda r: -r['gar'])[:POOL_N]
        for r in pool:
            k = NM.key(r['n'])
            nat = vn.get(k) or nation.get(k)
            w, l = ucl.get(S, (None, None))
            r.update(ga=r['g'] + r['a'], lgw=1.0 if champ.get((r['lg'], S)) == r['tid'] else 0.0,
                     ucl=1.0 if r['tid'] == w else .5 if r['tid'] == l else 0.0,
                     natw=1.0 if nat in natw.get(S, ()) else 0.0, prev=prev.get(k, 0), nat=nat)
        m = NM.Matcher(pool, name='n', team=None, pos=None, sport='soccer')
        order = []
        for n, _ in V[:3]:
            hit, _ = m.find(n)
            order.append(pool.index(hit) if hit is not None else None)
        if not V or order[0] is None:
            print('soccer', S, 'winner outside pool', V[:1]); out.append((S, pool, []))
        else:
            out.append((S, pool, [i for i in order if i is not None]))
        if V: prev[NM.key(V[0][0])] += 1
    return out, dict(prev)
