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
         ('defense', 'defensiveInterceptions.interceptions', 15), ('offense', 'receiving.receptions', 150),
         ('defense', 'defensive.totalTackles', 100), ('defense', 'defensive.passesDefended', 50),
         ('defense', 'defensive.tacklesForLoss', 50), ('specialTeams', 'kicking.fieldGoalsMade', 40),
         ('specialTeams', 'punting.punts', 40)]
# CFB only: every FBS punter and kicker, and deeper defensive and receiving lists (position award pools)
CFB_DEEP = [('specialTeams', 'punting.punts', 140), ('specialTeams', 'kicking.fieldGoalsMade', 140),
            ('defense', 'defensive.sacks', 100), ('defense', 'defensive.tacklesForLoss', 120),
            ('defense', 'defensive.passesDefended', 150), ('defense', 'defensiveInterceptions.interceptions', 100),
            ('defense', 'defensive.totalTackles', 200), ('offense', 'receiving.receivingYards', 200)]
STATS = {'passing': ['passingYards', 'passingTouchdowns', 'interceptions', 'passingAttempts', 'completions',
                     'QBRating', 'yardsPerPassAttempt', 'sacks'],
         'rushing': ['rushingYards', 'rushingTouchdowns', 'rushingAttempts'],
         'receiving': ['receivingYards', 'receivingTouchdowns', 'receptions'],
         'defensive': ['sacks', 'totalTackles', 'tacklesForLoss', 'passesDefended', 'stuffs'],
         'defensiveInterceptions': ['interceptions', 'interceptionTouchdowns'],
         'general': ['gamesPlayed', 'fumblesForced'], 'scoring': ['totalTouchdowns'],
         'returning': ['kickReturnTouchdowns', 'puntReturnTouchdowns'],
         'kicking': ['fieldGoalsMade', 'fieldGoalAttempts', 'fieldGoalPct', 'longFieldGoalMade', 'fieldGoalsMade50',
                     'fieldGoalAttempts50', 'extraPointsMade'],
         'punting': ['punts', 'grossAvgPuntYards', 'netAvgPuntYards', 'puntsInside20']}


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
    for cat, sort, n in SORTS + (CFB_DEEP if lg == 'cfb' else []):
        u = ('https://site.web.api.espn.com/apis/common/v3/sports/football/%s/statistics/byathlete?region=us&lang=en'
             '&contentorigin=espn&isqualified=false&page=1&limit=%d&season=%d&seasontype=%d&category=%s&sort=%s:desc'
             % (LEAGUE[lg], n, season, stype, cat, sort))
        d = get(u, f'{lg}/lead_{season}_{sort}_{n}.json')
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


POOL = os.path.join(ROOT, 'scripts', '.cache', 'awards', '%s_pool3.json')       # pull(): cfb with CFB_DEEP
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
            'qb': 1.0 if pos == 'QB' else 0.0, 'def': 1.0 if d else 0.0, 'debut': v.get('debut'),
            'ptd': ptd, 'rtd': rtd, 'ctd': ctd, 'rush_y': ry, 'rec_y': cy, 'rec': g('rece.receptions'),
            'ypa': py / g('pass.passingAttempts') if g('pass.passingAttempts') >= 50 else 0.0,
            'ypc': ry / g('rush.rushingAttempts') if g('rush.rushingAttempts') >= 50 else 0.0,
            'itd': g('defe.interceptionTouchdowns'), 'fgm': g('kick.fieldGoalsMade'), 'fga': g('kick.fieldGoalAttempts'),
            'fgpct': g('kick.fieldGoalsMade') / g('kick.fieldGoalAttempts') if g('kick.fieldGoalAttempts') else 0.0,
            'fg50': g('kick.fieldGoalsMade50'), 'long': g('kick.longFieldGoalMade'), 'punts': g('punt.punts'),
            'gross': g('punt.grossAvgPuntYards'), 'net': g('punt.netAvgPuntYards'), 'in20': g('punt.puntsInside20')}


def _order(pool, names):
    m = NM.Matcher(pool, name='n', team=None, pos=None)
    out = []
    for n in names:
        r, _ = m.find(n)
        if r is not None and pool.index(r) not in out: out.append(pool.index(r))
        elif r is None: out.append(None)
    return out


LB_POS, DB_POS = {'LB', 'ILB', 'OLB', 'MLB'}, {'CB', 'S', 'FS', 'SS', 'DB'}
# the other major CFB awards: (Wikipedia page, label, pool, pre-registered voter features, null)
CFB_AWARDS = {
    'maxwell': ('Maxwell_Award', 'Maxwell', lambda r: True, HEIS_COLS, NULL_COLS),
    'camp': ('Walter_Camp_Award', 'Walter Camp', lambda r: True, HEIS_COLS, NULL_COLS),
    'obrien': ("Davey_O%27Brien_Award", "O'Brien", lambda r: r['pos'] == 'QB' and r['pass_y'] >= 1000,
               ['pass_y', 'ptd', 'int', 'ypa', 'rush_y', 'wp'], ['pass_y', 'ptd']),
    'doak': ('Doak_Walker_Award', 'Doak Walker', lambda r: r['pos'] in ('RB', 'FB') and r['rush_y'] >= 300,
             ['rush_y', 'rtd', 'ypc', 'scrim', 'wp'], ['rush_y', 'rtd']),
    'bilet': ('Fred_Biletnikoff_Award', 'Biletnikoff', lambda r: r['pos'] not in ('QB', 'RB', 'FB') and r['rec_y'] >= 300,
              ['rec_y', 'ctd', 'rec', 'wp'], ['rec_y', 'ctd']),
    'mackey': ('John_Mackey_Award', 'Mackey', lambda r: r['pos'] == 'TE' and r['rec_y'] >= 100,
               ['rec_y', 'ctd', 'rec', 'wp'], ['rec_y', 'ctd']),
    'bednarik': ('Chuck_Bednarik_Award', 'Bednarik', lambda r: r['def'] > 0,
                 ['sacks', 'dint', 'tfl', 'pd', 'tackles', 'ff', 'wp'], ['sacks', 'dint']),
    'nagurski': ('Bronko_Nagurski_Trophy', 'Nagurski', lambda r: r['def'] > 0,
                 ['sacks', 'dint', 'tfl', 'pd', 'tackles', 'ff', 'wp'], ['sacks', 'dint']),
    'butkus': ('Butkus_Award', 'Butkus', lambda r: r['pos'] in LB_POS,
               ['tackles', 'tfl', 'sacks', 'dint', 'pd', 'wp'], ['tackles', 'sacks']),
    'thorpe': ('Jim_Thorpe_Award', 'Thorpe', lambda r: r['pos'] in DB_POS,
               ['dint', 'pd', 'tackles', 'itd', 'wp'], ['dint', 'pd']),
    'groza': ('Lou_Groza_Award', 'Groza', lambda r: r['fga'] >= 8, ['fgm', 'fgpct', 'fg50', 'long', 'wp'], ['fgm', 'fgpct']),
    'guy': ('Ray_Guy_Award', 'Ray Guy', lambda r: r['punts'] >= 20, ['gross', 'net', 'in20', 'punts'], ['gross']),
}


def award_winners(page):
    """{season: winner} from an award's Wikipedia page: the table with the most seasons since 2005 (the college award;
    some pages also list a high-school or older award)"""
    best = {}
    for t in re.findall(r'<table class="wikitable.*?</table>', wiki(page), re.S):
        out = {}
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
            c = cells(tr)
            if c and re.match(r'^(19|20)\d\d$', c[0]) and len(c) > 1 and int(c[0]) not in out:
                n = re.sub(r'\[.*?\]|\(\d+\)|[*†‡^+§#]', '', c[1]).strip()
                if n and not re.match(r'^\d', n): out[int(c[0])] = n
        if sum(y >= 2005 for y in out) > sum(y >= 2005 for y in best): best = out
    return best


def cfb_award_races():
    P = json.load(open(POOL % 'cfb'))
    W = {a: award_winners(v[0]) for a, v in CFB_AWARDS.items()}
    races = {a: [] for a in CFB_AWARDS}
    for s in sorted(P, key=int):
        S = int(s)
        rows = [features(v) for v in P[s].values()]
        for a, (_, _, f, _, _) in CFB_AWARDS.items():
            pool = [r for r in rows if f(r)]
            if a in ('maxwell', 'camp'):
                pool = [r for r in pool if r['yds'] >= 500 or r['tackles'] >= 40 or r['sacks'] >= 6 or r['dint'] >= 4]
            for r in pool: r.setdefault('prev_top5', 0.0)
            w = W[a].get(S)
            o = _order(pool, [w]) if w else []
            if not o or o[0] is None:
                if w: print('cfb', S, a, 'winner outside pool', w)
                races[a].append((S, pool, [])); continue
            races[a].append((S, pool, o[:1]))
    return races


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
