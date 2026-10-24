#!/usr/bin/env python3
"""Hockey prospects data (scripts/hockey_prospects.py reads it). Free sources only.

    python3 scripts/hockey_data.py [first last]     -> scripts/.cache/hockey/class_<year>.json (one file a draft class)
    python3 scripts/hockey_data.py --ahl            -> scripts/data/hockey_ahl.json.gz (AHL shots, completed seasons)
    python3 scripts/hockey_data.py --euro [season]  -> scripts/data/hockey_euro.json.gz (Liiga/SHL TOI and SOG, display only)

Each class: every pick from the NHL's draft API (api-web.nhle.com/v1/draft/picks/<year>/all) and every player in
Central Scouting's final rankings (/v1/draft/rankings/<year>/<1-4>: North American and international skaters and
goalies; rank within category, birth date, size, last amateur league). Picks are joined to NHL player ids through the
NHL's player search, confirmed on the player's landing page by draft year and overall pick (an exact join, no name
guessing); the landing page carries the birth date and every season line, junior and pro. Central Scouting rows join
the picks by the shared matcher (scripts/names.py) within the class, checked on birth date where both have one.
"""
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nhl_data as D
import names as NM

CACHE = os.path.join(HERE, '.cache', 'hockey')
WEB = 'https://api-web.nhle.com/v1'
SEARCH = 'https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=20&q='
FIRST = 2008
CATS = {1: ('NA', 'S'), 2: ('INT', 'S'), 3: ('NA', 'G'), 4: ('INT', 'G')}


def landing(pid):
    fn = os.path.join(CACHE, 'landing', f'{pid}.json')
    if os.path.exists(fn):
        try:
            return json.load(open(fn))
        except ValueError:
            pass
    j = D.get(f'{WEB}/player/{pid}/landing')
    if j:
        keep = {k: j.get(k) for k in ('playerId', 'birthDate', 'position', 'heightInInches', 'weightInPounds', 'shootsCatches',
                                       'draftDetails', 'birthCountry')}
        keep['name'] = f"{(j.get('firstName') or {}).get('default', '')} {(j.get('lastName') or {}).get('default', '')}".strip()
        keep['seasons'] = [{k: s.get(k) for k in ('season', 'gameTypeId', 'leagueAbbrev', 'gamesPlayed', 'goals', 'assists',
                                                   'points', 'savePctg', 'goalsAgainstAvg', 'wins', 'timeOnIce')}
                           | {'team': (s.get('teamName') or {}).get('default')}
                           for s in j.get('seasonTotals') or []]
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        json.dump(keep, open(fn, 'w'), separators=(',', ':'))
        return keep
    return None


def find_id(name, year, overall):
    """the NHL id of the player taken at <overall> in <year>, or None"""
    res = D.get(SEARCH + urllib.parse.quote(name)) or []
    for r in res[:10]:
        L = landing(r['playerId'])
        dd = (L or {}).get('draftDetails') or {}
        if dd.get('year') == year and dd.get('overallPick') == overall:
            return r['playerId']
    return None


def pull(year, fresh=False):
    fn = os.path.join(CACHE, f'class_{year}.json')
    if os.path.exists(fn) and not fresh:
        return json.load(open(fn))
    j = D.get(f'{WEB}/draft/picks/{year}/all') or {}
    picks = []
    for p in j.get('picks') or []:
        nm = f"{(p.get('firstName') or {}).get('default', '')} {(p.get('lastName') or {}).get('default', '')}".strip()
        picks.append({'name': nm, 'pick': p['overallPick'], 'round': p['round'], 'team': D.team(p.get('teamAbbrev')),
                      'pos': p.get('positionCode'), 'ht': p.get('height'), 'wt': p.get('weight'), 'country': p.get('countryCode'),
                      'league': p.get('amateurLeague'), 'club': p.get('amateurClubName')})
    with ThreadPoolExecutor(8) as ex:
        ids = list(ex.map(lambda p: find_id(p['name'], year, p['pick']), picks))
    for p, i in zip(picks, ids):
        p['id'] = i
        L = landing(i) if i else None
        if L:
            p['birth'] = L.get('birthDate'); p['ht'] = p['ht'] or L.get('heightInInches'); p['wt'] = p['wt'] or L.get('weightInPounds')
            p['shoots'] = L.get('shootsCatches')
    css = []
    for c, (reg, kind) in CATS.items():
        r = D.get(f'{WEB}/draft/rankings/{year}/{c}') or {}
        for x in r.get('rankings') or []:
            css.append({'name': f"{x.get('firstName', '')} {x.get('lastName', '')}".strip(), 'cat': c, 'reg': reg, 'kind': kind,
                        'final': x.get('finalRank'), 'mid': x.get('midtermRank'), 'pos': x.get('positionCode'),
                        'ht': x.get('heightInInches'), 'wt': x.get('weightInPounds'), 'birth': x.get('birthDate'),
                        'league': x.get('lastAmateurLeague'), 'club': x.get('lastAmateurClub'), 'country': x.get('birthCountry')})
    # Central Scouting -> picks: name within the class, birth date must agree where both sides have it
    M = NM.Matcher(picks, name='name', team=None, pos=None)
    for x in css:
        p, _ = M.find(x['name'])
        if p is not None and (not p.get('birth') or not x.get('birth') or p['birth'] == x['birth']):
            if 'css' not in p or (x['final'] or 999) < (p['css'].get('final') or 999):
                p['css'] = {k: x[k] for k in ('cat', 'reg', 'kind', 'final', 'mid')}
            x['pick'] = p['pick']
    out = {'year': year, 'picks': picks, 'css': css, 'pulled': time.strftime('%Y-%m-%d')}
    os.makedirs(CACHE, exist_ok=True)
    json.dump(out, open(fn, 'w'), separators=(',', ':'))
    return out


# -- AHL shots (HockeyTech's public AHL feed): shots on goal per game, a post-draft stage driver (scripts/hockey_prospects.py)
AHL_FILE = os.path.join(HERE, 'data', 'hockey_ahl.json.gz')     # frozen, small: completed seasons, skaters with 20+ GP
AHL_FEED = 'https://lscluster.hockeytech.com/feed/index.php?feed=modulekit&fmt=json&key=ccb91f29d6744675&client_code=ahl'


def ahl_compact(players):
    """one AHL season from the topscorers feed -> {'norm': {F, D: league shots/GP}, 'p': [[name, birth, gp, shots, goals, pos]]}"""
    out, pool = [], {'F': [], 'D': []}
    for p in players or []:
        gp, sh = int(p.get('games_played') or 0), int(p.get('shots') or 0)
        if p.get('position') == 'G' or gp < 20:
            continue
        pos = 'D' if p.get('position') == 'D' else 'F'
        try:
            b = dt.datetime.strptime(p.get('birthdate') or '', '%b %d, %Y').date().isoformat()
        except ValueError:
            b = None
        nm = p.get('name') or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        out.append([nm, b, gp, sh, int(p.get('goals') or 0), pos])
        if sh > 0:
            pool[pos].append(sh / gp)
    if len(pool['F']) + len(pool['D']) < 100:
        return None                                     # a season without shots in the feed
    return {'norm': {k: round(sum(v) / len(v), 4) for k, v in pool.items()}, 'p': out}


def ahl_pull():
    """add any completed AHL season missing from the frozen file (2008-09 on)"""
    have = json.load(gzip.open(AHL_FILE, 'rt')) if os.path.exists(AHL_FILE) else {}
    cur = D.current_season()
    new = 0
    for s in (D.get(AHL_FEED + '&view=seasons') or {}).get('SiteKit', {}).get('Seasons') or []:
        m = re.match(r'(\d{4})-(\d{2,4}) (AHL )?Regular Season$', s['season_name'].strip())
        if not m or s.get('playoff') != '0':
            continue
        y = int(m.group(1)) + 1
        if y < 2009 or y >= cur or str(y) in have:
            continue
        d = D.get(AHL_FEED + f"&view=statviewtype&type=topscorers&season_id={s['season_id']}&first=0&limit=3000&stat=all&order_direction=")
        c = ahl_compact(((d or {}).get('SiteKit') or {}).get('Statviewtype'))
        if c:
            have[str(y)] = c; new += 1
    if new:
        with gzip.open(AHL_FILE, 'wt') as f:
            json.dump(have, f, separators=(',', ':'))
    print('AHL seasons', len(have), 'new', new)


# -- Liiga and SHL ice time and shots on goal (display only on the prospects pipeline: too few gradable Euro-pro picks to fit)
EURO_FILE = os.path.join(HERE, 'data', 'hockey_euro.json.gz')   # frozen, small: {season: {liiga, shl: [[name, birth, pos, gp, gp with TOI, TOI s, SOG]]}}
LIIGA = 'https://liiga.fi/api/v2'
SHL = 'https://www.shl.se/api'
# SHL's API has no season list: each season's uuid (and the regular-season series/game-type ids) comes from shl.se's schedule page
SHL_SEASONS = {2026: 'xs4m9qupsi'}
SHL_SERIES, SHL_GTYPE = 'qQ9-bb0bzEWUk', 'qQ9-af37Ti40B'


def _mmss(s):
    try:
        m, x = str(s).split(':')
        return int(m) * 60 + int(x)
    except ValueError:
        return 0


def liiga_season(y):
    """Liiga regular season y (end year): TOI and shot attempts from the game stats, shots on goal (saved or scored) from the
    shot map, birth dates from game rosters (fetched only until every player has one)"""
    games = [g['id'] for g in D.get(f'{LIIGA}/games?tournament=runkosarja&season={y}') or [] if g.get('ended')]
    with ThreadPoolExecutor(4) as ex:
        stats = list(ex.map(lambda g: D.get(f'{LIIGA}/games/stats/{y}/{g}'), games))
        shots = list(ex.map(lambda g: D.get(f'{LIIGA}/shotmap/{y}/{g}'), games))
    P, bio = {}, {}
    for gid, st, sm in zip(games, stats, shots):
        if not st or sm is None:
            continue
        toi = {}                                        # this game's TOI a player, summed over the period blocks
        for side in ('homeTeam', 'awayTeam'):
            for blk in st.get(side) or []:
                for p in blk.get('periodPlayerStats') or []:
                    toi[p['playerId']] = toi.get(p['playerId'], 0) + ((p.get('period') or {}).get('timeofice') or 0)
        for pid, t in toi.items():
            a = P.setdefault(pid, [0, 0, 0, 0])
            a[0] += 1; a[1] += t > 0; a[2] += t
        for s in sm:
            if s.get('eventType') in ('GOAL', 'GOALIE_BLOCKED') and s.get('shooterId') in toi:
                P[s['shooterId']][3] += 1
        if any(pid not in bio for pid in toi):
            det = D.get(f'{LIIGA}/games/{y}/{gid}') or {}
            for side in ('homeTeamPlayers', 'awayTeamPlayers'):
                for p in det.get(side) or []:
                    bio[p['id']] = (f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(), p.get('dateOfBirth'), p.get('roleCode'))
    out = []
    for pid, (gp, gpt, toi, sog) in P.items():
        nm, b, role = bio.get(pid, (None, None, None))
        if nm and role != 'MV':                         # MV = maalivahti (goalie)
            out.append([nm, b, 'D' if (role or '').endswith('P') else 'F', gp, gpt, toi, sog])   # VP/OP/7. P = defence
    return out if len(games) > 100 else None


def shl_season(y):
    """SHL regular season y (end year) from the per-game player stats: TOI and shots on goal, no birth dates"""
    su = SHL_SEASONS.get(y)
    if not su:
        return None
    sch = D.get(f'{SHL}/sports-v2/game-schedule?seasonUuid={su}&seriesUuid={SHL_SERIES}&gameTypeUuid={SHL_GTYPE}&gamePlace=all&played=all')
    gs = [g['uuid'] for g in (sch or {}).get('gameInfo') or [] if g.get('state') == 'post-game']
    with ThreadPoolExecutor(4) as ex:
        box = list(ex.map(lambda u: D.get(f'{SHL}/gameday/player-stats/{u}'), gs))
    P = {}
    for d in box:
        for side in ('homeTeamValue', 'awayTeamValue'):
            names = ((d or {}).get('players') or {}).get(side) or {}
            for v in ((d or {}).get('stats') or {}).get(side) or []:
                if (v.get('info') or {}).get('period') != 0 or v.get('POS') == 'GK':
                    continue
                pid = str(v['info']['playerId'])
                a = P.setdefault(pid, [(names.get(pid) or {}).get('fullName'), None, 'D' if 'D' in (v.get('POS') or '') else 'F', 0, 0, 0, 0])
                t = _mmss(v.get('TOI'))
                a[3] += 1; a[4] += t > 0; a[5] += t; a[6] += int(v.get('SOG') or 0)
    return [p for p in P.values() if p[0]] if len(gs) > 100 else None


def euro_pull(seasons=None):
    """add completed Liiga / SHL seasons missing from the frozen file (default: the last completed season, the one the
    pipeline's lines show)"""
    have = json.load(gzip.open(EURO_FILE, 'rt')) if os.path.exists(EURO_FILE) else {}
    cur = D.current_season()
    new = 0
    for y in seasons or [cur - 1]:                    # Liiga TOI is 0 before 2021-22
        e = have.setdefault(str(y), {})
        for lg, fn in (('liiga', liiga_season), ('shl', shl_season)):
            if lg not in e and y < cur:
                r = fn(y)
                if r:
                    e[lg] = r; new += 1
        if not e:
            del have[str(y)]
    if new:
        with gzip.open(EURO_FILE, 'wt') as f:
            json.dump(have, f, separators=(',', ':'))
    print('Liiga/SHL seasons', {k: sorted(v) for k, v in have.items()}, 'new', new)


if __name__ == '__main__':
    if '--ahl' in sys.argv:
        ahl_pull(); sys.exit()
    if '--euro' in sys.argv:
        euro_pull([int(x) for x in sys.argv[1:] if x.isdigit()] or None); sys.exit()
    a = [int(x) for x in sys.argv[1:] if x.isdigit()]
    lo, hi = (a + [FIRST, 2026])[:2] if a else (FIRST, 2026)
    for y in range(lo, hi + 1):
        t = time.time()
        d = pull(y, fresh='--fresh' in sys.argv)
        n = sum(1 for p in d['picks'] if p.get('id'))
        print(y, len(d['picks']), 'picks', n, 'with NHL id', len(d['css']), 'css', sum(1 for p in d['picks'] if p.get('css')), 'joined',
              f'{time.time() - t:.0f}s', flush=True)
    ahl_pull()
    euro_pull()
