# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Football award races: the Heisman (CFB) and the AP NFL awards (MVP, OPOY, DPOY, OROY, DROY), candidate pools and
features for scripts/awards_research.py and scripts/awards.py.

History: ESPN season stats (the leaders by passing, rushing, receiving, touchdowns, sacks, tackles and interceptions,
each player's regular-season line and his team's record; scripts/.cache/awards/espn/), Heisman voting from each FBS
season's Wikipedia page, AP award winners from Wikipedia's award pages."""
import concurrent.futures as cf, html, json, os, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'awards', 'espn')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
LEAGUE = {'cfb': 'college-football', 'nfl': 'nfl'}
SORTS = [('offense', 'passing.passingYards', 60), ('offense', 'rushing.rushingYards', 50),
         ('offense', 'receiving.receivingYards', 50), ('offense', 'scoring.totalTouchdowns', 30),
         ('defense', 'defensive.sacks', 25), ('defense', 'defensive.totalTackles', 25),
         ('defense', 'defensiveInterceptions.interceptions', 15)]
STATS = {'passing': ['passingYards', 'passingTouchdowns', 'interceptions', 'passingAttempts', 'completions',
                     'QBRating', 'yardsPerPassAttempt', 'sacks'],
         'rushing': ['rushingYards', 'rushingTouchdowns', 'rushingAttempts'],
         'receiving': ['receivingYards', 'receivingTouchdowns', 'receptions'],
         'defensive': ['sacks', 'totalTackles', 'tacklesForLoss', 'passesDefended', 'stuffs'],
         'defensiveInterceptions': ['interceptions', 'interceptionTouchdowns'],
         'general': ['gamesPlayed', 'fumblesForced'], 'scoring': ['totalTouchdowns'],
         'returning': ['kickReturnTouchdowns', 'puntReturnTouchdowns']}


def get(url, fn=None, tries=4):
    if fn:
        p = os.path.join(CACHE, fn)
        if os.path.exists(p): return json.load(open(p))
    for a in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=40).read()
            d = json.loads(r)
            if fn:
                os.makedirs(os.path.dirname(os.path.join(CACHE, fn)), exist_ok=True)
                json.dump(d, open(os.path.join(CACHE, fn), 'w'))
            return d
        except urllib.error.HTTPError as e:
            if e.code == 404:
                if fn: json.dump({}, open(os.path.join(CACHE, fn), 'w'))
                return {}
            time.sleep(3 * (a + 1))
        except Exception:
            time.sleep(3 * (a + 1))
    return {}


def leaders(lg, season, stype=2):
    ids = {}
    for cat, sort, n in SORTS:
        u = ('https://site.web.api.espn.com/apis/common/v3/sports/football/%s/statistics/byathlete?region=us&lang=en'
             '&contentorigin=espn&isqualified=false&page=1&limit=%d&season=%d&seasontype=%d&category=%s&sort=%s:desc'
             % (LEAGUE[lg], n, season, stype, cat, sort))
        d = get(u, f'{lg}/lead_{season}_{sort}.json')
        for a in d.get('athletes', []):
            x = a['athlete']
            ids.setdefault(x['id'], {'id': x['id'], 'n': x['displayName'], 'tid': x.get('teamId'),
                                     'tm': x.get('teamShortName'), 'pos': (x.get('position') or {}).get('abbreviation', '')})
    return ids


def athlete_stats(lg, season, aid, stype=2):
    u = f'https://sports.core.api.espn.com/v2/sports/football/leagues/{LEAGUE[lg]}/seasons/{season}/types/{stype}/athletes/{aid}/statistics'
    d = get(u, f'{lg}/{season}/a{aid}.json')
    out = {}
    for c in (d.get('splits') or {}).get('categories', []):
        want = STATS.get(c['name'])
        if not want: continue
        for s in c['stats']:
            if s['name'] in want: out[c['name'][:4] + '.' + s['name']] = s.get('value') or 0.0
    return out


def team_record(lg, season, tid, stype=2):
    u = f'https://sports.core.api.espn.com/v2/sports/football/leagues/{LEAGUE[lg]}/seasons/{season}/types/{stype}/teams/{tid}/record'
    d = get(u, f'{lg}/{season}/t{tid}.json')
    for it in d.get('items', []):
        if it.get('type') == 'total' or it.get('name') == 'overall':
            st = {s['name']: s.get('value') for s in it.get('stats', [])}
            w, l = st.get('wins', 0) or 0, st.get('losses', 0) or 0
            return {'w': w, 'l': l, 'wp': w / max(w + l, 1)}
    return {}


def search_id(lg, name):
    u = ('https://site.web.api.espn.com/apis/common/v3/search?query=%s&limit=5&type=player&sport=football&league=%s'
         % (urllib.parse.quote(re.sub(r"[.'’]", '', name)), LEAGUE[lg]))
    d = get(u, f'{lg}/search/{NM.key(name).replace(" ", "_")}.json')
    out = []
    for it in d.get('items', []):
        if it.get('type') == 'player': out.append(it.get('id'))
    return [i for i in out if i]


def wiki(page):
    fn = os.path.join(CACHE, 'wiki', re.sub(r'[^A-Za-z0-9_]', '_', page) + '.html')
    if os.path.exists(fn): return open(fn, encoding='utf-8').read()
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    for a in range(3):
        try:
            h = urllib.request.urlopen(urllib.request.Request('https://en.wikipedia.org/wiki/' + page, headers={'User-Agent': UA}), timeout=40).read().decode('utf-8', 'replace')
            open(fn, 'w', encoding='utf-8').write(h)
            return h
        except Exception as e:
            print(page, e); time.sleep(5)
    return ''


def cells(tr):
    return [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', c))).strip()
            for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]


def heisman_votes(season):
    h = wiki(f'{season}_NCAA_Division_I_FBS_football_season')
    for t in re.findall(r'<table.*?</table>', h, re.S):
        rows = [cells(tr) for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)]
        if not rows or 'Player' not in rows[0] or not any('Total' in c or 'Points' in c for c in rows[0]): continue
        hd = rows[0]
        ti = next(i for i, c in enumerate(hd) if 'Total' in c or 'Points' in c)
        out = []
        for r in rows[1:]:
            if len(r) <= ti: continue
            try: pts = float(re.sub(r'[^\d.]', '', r[ti]) or 0)
            except ValueError: continue
            out.append((re.sub(r'\[.*?\]', '', r[hd.index('Player')]).strip(), r[1] if len(r) > 1 else '', r[2] if len(r) > 2 else '', pts))
        if out: return sorted(out, key=lambda t: -t[3])
    return []


NFL_PAGES = {'mvp': 'AP_NFL_Most_Valuable_Player', 'opoy': 'AP_NFL_Offensive_Player_of_the_Year',
             'dpoy': 'AP_NFL_Defensive_Player_of_the_Year', 'oroy': 'AP_NFL_Offensive_Rookie_of_the_Year',
             'droy': 'AP_NFL_Defensive_Rookie_of_the_Year'}


def nfl_winners(award):
    """{season: [winner names]} (co-winners share a season). The rookie awards share one page: offense's table first."""
    h = wiki(NFL_PAGES[award])
    tabs = [t for t in re.findall(r'<table class="wikitable.*?</table>', h, re.S)
            if (cells((re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S) or [''])[0]) or [''])[0].startswith('Season')]
    if award == 'droy': tabs = tabs[1:2]
    elif award == 'oroy': tabs = tabs[:1]
    out = {}
    for t in tabs:
        last = None
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)[1:]:
            c = cells(tr)
            if not c: continue
            if re.match(r'^(19|20)\d\d', c[0]):
                last = int(c[0][:4]); rest = c[1:]
            elif last is not None and len(c) >= 2:
                rest = c                                        # a co-winner row under a rowspan season
            else:
                continue
            n = re.sub(r'\[.*?\]|\(\d+\)|[*†‡^+§#]', '', rest[0]).strip()
            if n and not re.match(r'^\d', n): out.setdefault(last, []).append(n)
    return out


def pull(lg, seasons, extra_names=None, workers=8):
    """every season's pool: leaders' ids + named vote-getters, their stats and team records"""
    out = {}
    for s in seasons:
        ids = leaders(lg, s)
        for n in (extra_names or {}).get(s, []):
            if not any(NM.same(n, v['n']) for v in ids.values()):
                for i in search_id(lg, n)[:3]:
                    a = get(f'https://sports.core.api.espn.com/v2/sports/football/leagues/{LEAGUE[lg]}/seasons/{s}/athletes/{i}', f'{lg}/{s}/info{i}.json')
                    if not a: continue
                    tm = re.search(r'/teams/(\d+)', json.dumps(a.get('team') or {}))
                    ids.setdefault(i, {'id': i, 'n': a.get('displayName', n), 'tid': tm.group(1) if tm else None,
                                       'tm': None, 'pos': (a.get('position') or {}).get('abbreviation', ''), 'searched': True})
        with cf.ThreadPoolExecutor(workers) as ex:
            st = dict(zip(ids, ex.map(lambda i: athlete_stats(lg, s, i), ids)))
        for i, v in ids.items(): v['st'] = st[i]
        tids = {v['tid'] for v in ids.values() if v['tid']}
        with cf.ThreadPoolExecutor(workers) as ex:
            rec = dict(zip(tids, ex.map(lambda t: team_record(lg, s, t), tids)))
        for v in ids.values(): v['rec'] = rec.get(v['tid'], {})
        out[s] = ids
        print(lg, s, len(ids), 'players', len(tids), 'teams', flush=True)
    return out


def season_team(lg, season, aid):
    """the athlete's team that season (the leaders feed carries his latest team) and his experience"""
    a = get(f'https://sports.core.api.espn.com/v2/sports/football/leagues/{LEAGUE[lg]}/seasons/{season}/athletes/{aid}',
            f'{lg}/{season}/info{aid}.json')
    tm = re.search(r'/teams/(\d+)', json.dumps(a.get('team') or {}))
    exp = (a.get('experience') or {}).get('years')
    return {'tid': tm.group(1) if tm else None, 'exp': exp, 'pos': (a.get('position') or {}).get('abbreviation', ''),
            'debut': a.get('debutYear') or (a.get('draft') or {}).get('year')}


def fix_teams(lg, pool, workers=8):
    """re-point every pooled player at his team that season and refetch records"""
    for s, ids in pool.items():
        s = int(s)
        with cf.ThreadPoolExecutor(workers) as ex:
            info = dict(zip(ids, ex.map(lambda i: season_team(lg, s, i), ids)))
        for i, v in ids.items():
            if info[i]['tid']: v['tid'] = info[i]['tid']
            v['exp'], v['debut'] = info[i]['exp'], info[i]['debut']
            if info[i]['pos']: v['pos'] = info[i]['pos']
        tids = {v['tid'] for v in ids.values() if v['tid']}
        with cf.ThreadPoolExecutor(workers) as ex:
            rec = dict(zip(tids, ex.map(lambda t: team_record(lg, s, t), tids)))
        for v in ids.values(): v['rec'] = rec.get(v['tid'], {})
        print(lg, s, 'teams fixed', len(tids), flush=True)
    return pool


POOL = os.path.join(ROOT, 'scripts', '.cache', 'awards', '%s_pool2.json')
DEF_POS = {'DE', 'DT', 'NT', 'LB', 'ILB', 'OLB', 'MLB', 'CB', 'S', 'FS', 'SS', 'DB', 'DL', 'EDGE'}
HEIS_COLS = ['yds', 'td', 'int', 'wp', 'qb', 'def', 'prev_top5']
NULL_COLS = ['yds', 'td']
NFL_LABEL = {'mvp': 'MVP', 'opoy': 'OPOY', 'dpoy': 'DPOY', 'oroy': 'OROY', 'droy': 'DROY'}
NFL_COLS = {'mvp': ['yds', 'td', 'int', 'wp', 'qb', 'prev_mvp'],
            'opoy': ['pass_y', 'scrim', 'td', 'wp', 'qb'],
            'dpoy': ['sacks', 'dint', 'tfl', 'pd', 'ff', 'wp'],
            'oroy': ['yds', 'td', 'wp', 'qb']}
# DROY not modelled: the leaders feed holds 3-5 rookie defenders a season, too few for a pool
NFL_NULL = {'mvp': ['yds', 'td'], 'opoy': ['yds', 'td'], 'dpoy': ['sacks', 'dint'], 'oroy': ['yds', 'td']}


def features(v):
    st = v.get('st') or {}
    g = lambda k: float(st.get(k) or 0)
    pos = (v.get('pos') or '').upper()
    py, ry, cy = g('pass.passingYards'), g('rush.rushingYards'), g('rece.receivingYards')
    ptd, rtd, ctd = g('pass.passingTouchdowns'), g('rush.rushingTouchdowns'), g('rece.receivingTouchdowns')
    rec = v.get('rec') or {}
    d = pos in DEF_POS or (py + ry + cy < 50 and g('defe.totalTackles') > 20)
    return {'id': v['id'], 'n': v['n'], 'tid': v.get('tid'), 'pos': pos, 'pass_y': py, 'scrim': ry + cy,
            'yds': py + ry + cy, 'td': ptd + rtd + ctd + g('retu.kickReturnTouchdowns') + g('retu.puntReturnTouchdowns'),
            'int': g('pass.interceptions'), 'sacks': g('defe.sacks'), 'dint': g('defe.interceptions'),
            'tackles': g('defe.totalTackles'), 'tfl': g('defe.tacklesForLoss'), 'pd': g('defe.passesDefended'),
            'ff': g('gene.fumblesForced'), 'wp': rec.get('wp', .5), 'w': rec.get('w', 0), 'l': rec.get('l', 0),
            'qb': 1.0 if pos == 'QB' else 0.0, 'def': 1.0 if d else 0.0, 'debut': v.get('debut')}


def _order(pool, names):
    m = NM.Matcher(pool, name='n', team=None, pos=None)
    out = []
    for n in names:
        r, _ = m.find(n)
        if r is not None and pool.index(r) not in out: out.append(pool.index(r))
        elif r is None: out.append(None)
    return out


def cfb_races():
    P = json.load(open(POOL % 'cfb'))
    races, prev = {'heisman': []}, set()
    for s in sorted(P, key=int):
        S = int(s)
        pool = [features(v) for v in P[s].values()]
        pool = [r for r in pool if r['yds'] >= 500 or r['tackles'] >= 40 or r['sacks'] >= 6 or r['dint'] >= 4]
        for r in pool: r['prev_top5'] = 1.0 if NM.key(r['n']) in prev else 0.0
        vt = heisman_votes(S)
        o = _order(pool, [n for n, _, _, _ in vt])
        miss = [vt[i][0] for i, x in enumerate(o[:5]) if x is None]
        if miss: print('cfb', S, 'vote-getters outside pool', miss)
        order = [x for x in o if x is not None]
        if o and o[0] is None: order = []                     # the winner must be in the pool
        races['heisman'].append((S, pool, order))
        prev = {NM.key(n) for n, _, _, _ in vt[:5]}
    return races


PRE_MVP = {}
for _n in ['Peyton Manning'] * 3 + ['Kurt Warner', 'Kurt Warner', 'Rich Gannon', 'Marshall Faulk', 'Steve McNair',
           'Brett Favre', 'Brett Favre', 'Brett Favre']:                     # 1995-2004 (2003 shared)
    PRE_MVP[NM.key(_n)] = PRE_MVP.get(NM.key(_n), 0) + 1


def nfl_races():
    P = json.load(open(POOL % 'nfl'))
    W = {a: nfl_winners(a) for a in NFL_COLS}
    races = {a: [] for a in NFL_COLS}
    mvps = dict(PRE_MVP)
    for s in sorted(P, key=int):
        S = int(s)
        rows = [features(v) for v in P[s].values()]
        for r in rows:
            r['prev_mvp'] = mvps.get(NM.key(r['n']), 0)
            r['rookie'] = r['debut'] == S
        off = [r for r in rows if not r['def'] and r['yds'] >= 400]
        dfn = [r for r in rows if r['def'] and (r['tackles'] >= 30 or r['sacks'] >= 4 or r['dint'] >= 3)]
        pools = {'mvp': off, 'opoy': off, 'dpoy': dfn, 'oroy': [r for r in off if r['rookie']]}
        for a, pool in pools.items():
            win = W[a].get(S, [])[:1]
            o = _order(pool, win)
            if not o or o[0] is None:
                print('nfl', S, a, 'winner outside pool', win); races[a].append((S, pool, [])); continue
            races[a].append((S, pool, o[:1]))
        for n in W['mvp'].get(S, [])[:1]: mvps[NM.key(n)] = mvps.get(NM.key(n), 0) + 1
    return races
