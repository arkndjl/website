# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer award races added Nov 23 2026: each big-five league's player of the season (Premier League Player of the
Season, PFA Players' Player, LaLiga best player, Serie A Footballer of the Year, VDV Player of the Season, UNFP Player
of the Year), Golden Boy, Kopa Trophy, Yashin Trophy. Pools and features for scripts/research/awards_nov23/soccer/run.py
and scripts/awards.py. Pre-registration: scripts/research/awards_nov23/soccer/prereg.md.

History: winners (Kopa / Yashin: the top three) from each award's Wikipedia page; players and GAR from the big-five
season files (static/data/soccer-war/<S>.json); club honours from the club game archive, national titles from
martj42's international results (scripts/awards_soccer.py). Stdlib."""
import collections, gzip, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM
import awards_soccer as SO

FIRST, LAST = 2015, 2026
# pools by minutes (Nov 23: the pre-registered top-60 / top-40 GAR cuts left out Kante 2016-17 and the 2025 and 2026
# Yashin winners, whose GAR sat below the cut)
MIN_LG, MIN_YOUNG, MIN_GK = 1000, 600, 900
LEAGUE_COLS = ['gar', 'ga', 'lgw', 'tppg', 'prev']
YOUNG_COLS = ['gar', 'ga', 'ucl', 'lgw', 'age', 'prev']
KOPA_COLS = ['gar', 'ga', 'ucl', 'lgw', 'age']
YASHIN_COLS = ['gar', 'lgw', 'ucl', 'natw', 'prev']
NULL = ['gar']
# award: (label, Wikipedia page, league or None, last season with a winner on the page, depth)
AWARDS = {'pl_pots': ('PL Player of the Season', 'Premier_League_Player_of_the_Season', 'eng.1', 1),
          'pfa': ("PFA Players' Player", 'PFA_Players%27_Player_of_the_Year', 'eng.1', 1),
          'laliga': ('LaLiga Best Player', 'La_Liga_Awards', 'esp.1', 1),
          'seriea': ('Serie A MVP', 'Serie_A_Footballer_of_the_Year', 'ita.1', 1),
          'vdv': ('VDV Player of the Season', 'VDV_Player_of_the_Season', 'ger.1', 1),
          'ligue1': ('UNFP Player of the Year', 'Ligue_1_Player_of_the_Year', 'fra.1', 1),
          'goldenboy': ('Golden Boy', 'Golden_Boy_(award)', None, 1),
          'kopa': ('Kopa Trophy', 'Kopa_Trophy', None, 3),
          'yashin': ('Yashin Trophy', 'Yashin_Trophy', None, 3)}
LEAGUES = {'eng.1': 'Premier League', 'esp.1': 'LaLiga', 'ita.1': 'Serie A', 'ger.1': 'Bundesliga', 'fra.1': 'Ligue 1'}


def clean(n):
    n = re.sub(r'\[.*?\]', '', n)
    n = re.sub(r'\(\d+\)', '', n)
    return re.sub(r'[§‡†*^#]+', '', n).strip()


def winners(page):
    """{season end year: [names, best first]}: the first winners table with a season from 2015 on (one name a season),
    or the Year / Rank / Player tables (Kopa, Yashin: the top three)"""
    import awards_football as F
    h = F.wiki(page)
    for t in re.findall(r'<table class="[^"]*wikitable.*?</table>', h, re.S):
        rows = [F.cells(tr) for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)]
        if not rows: continue
        hd = rows[0]
        pc = next((i for i, c in enumerate(hd) if c in ('Player', 'Recipient', 'Winner')), None)
        if pc is None or not hd or hd[0] not in ('Season', 'Year'): continue
        out = {}
        if 'Rank' in hd:
            y = None
            for r in rows[1:]:
                if r and re.match(r'^\d{4}$', r[0]): y = int(r[0]); r = r[1:]
                if y is None or len(r) < 2 or not re.match(r'^\d', r[0]): continue
                out.setdefault(y, []).append(clean(r[1]))
        else:
            for r in rows[1:]:
                if not r: continue
                m = re.match(r'^(\d{4})(?:[–-](\d{2,4}))?', r[0])
                if not m or len(r) <= pc: continue
                y = int(m.group(1)) + (1 if m.group(2) else 0)
                nm = clean(r[pc])
                if nm and y not in out and not re.match(r'(?i)not awarded', nm): out[y] = [nm]
        if any(y >= FIRST for y in out): return out
    return {}


def team_ppg():
    """{(league, S, ESPN team id): points a match / 3} from the club game archive"""
    H = json.load(gzip.open(os.path.join(SO.ROOT, 'scripts', 'soccer_games_hist.json.gz')))
    acc = collections.defaultdict(lambda: [0.0, 0])
    for g in H:
        if g.get('hs') is None or g.get('as') is None or not g['lg'].endswith('.1'): continue
        S = int(g['day'][:4]) + (1 if g['day'][5:7] >= '07' else 0)
        a, b = (3, 0) if g['hs'] > g['as'] else (0, 3) if g['as'] > g['hs'] else (1, 1)
        for t, p in ((g['h'], a), (g['a'], b)):
            x = acc[(g['lg'], S, t)]; x[0] += p; x[1] += 1
    return {k: v[0] / v[1] / 3 for k, v in acc.items() if v[1]}


def season_pool(S, champ, ucl, natw, nation, ppg):
    rows, _ = SO.season_rows(S)
    ages = {}
    d = json.load(open(os.path.join(SO.WAR, f'{S}.json')))
    for r in d['players']:
        if r.get('age') is not None: ages[r['p']] = r['age']
    w, l = ucl.get(S, (None, None))
    for r in rows:
        k = NM.key(r['n'])
        nat = nation.get(k)
        r.update(ga=r['g'] + r['a'], lgw=1.0 if champ.get((r['lg'], S)) == r['tid'] else 0.0,
                 ucl=1.0 if r['tid'] == w else .5 if r['tid'] == l else 0.0, natw=1.0 if nat in natw.get(S, ()) else 0.0,
                 tppg=ppg.get((r['lg'], S, r['tid']), .45), age=ages.get(r['id']), nat=nat)
    return rows


def young(r, S):
    """eligible for the Golden Boy / Kopa: under 21 at the end of the calendar year the season ends in (the file's
    age is on July 1 at the season's end, so under 20.5 then)"""
    return r.get('age') is not None and r['age'] < 20.5


def races(only=None):
    """{award: [(season, pool, order)]}, {award: prior wins by name key}"""
    champ, ucl = SO.club_honours()
    natw, nation = SO.nat_winners(), SO.scorer_nation()
    ppg = team_ppg()
    W = {a: winners(v[1]) for a, v in AWARDS.items() if not only or a in only}
    prev = {a: collections.Counter(NM.key(n[0]) for y, n in w.items() if y < FIRST) for a, w in W.items()}
    out = {a: [] for a in W}
    for S in range(FIRST, LAST + 1):
        rows = season_pool(S, champ, ucl, natw, nation, ppg)
        for a, w in W.items():
            lab, _, lg, depth = AWARDS[a]
            if S == 2020 and a in ('kopa', 'yashin'): continue
            if lg: P = [r for r in rows if r['lg'] == lg and r['min'] >= MIN_LG]
            elif a == 'yashin': P = [r for r in rows if r.get('pos') == 'GK' and r['min'] >= MIN_GK]
            else: P = [r for r in rows if young(r, S) and r['min'] >= MIN_YOUNG]
            P = [dict(r, prev=prev[a][NM.key(r['n'])]) for r in P]
            names = w.get(S)
            if not names:
                continue
            m = NM.Matcher(P, name='n', team=None, pos=None, sport='soccer')
            order = []
            for n in names[:depth]:
                hit, _ = m.find(n)
                order.append(P.index(hit) if hit is not None else None)
            if order[0] is None:
                print('soccer', S, a, 'winner outside pool', names[:1], flush=True)
                out[a].append((S, P, []))
            else:
                out[a].append((S, P, [i for i in order if i is not None]))
            prev[a][NM.key(names[0])] += 1
    return out, {a: dict(v) for a, v in prev.items()}
