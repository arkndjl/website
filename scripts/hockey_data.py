#!/usr/bin/env python3
"""Hockey prospects data (scripts/hockey_prospects.py reads it). Free sources only.

    python3 scripts/hockey_data.py [first last]     -> scripts/.cache/hockey/class_<year>.json (one file a draft class)

Each class: every pick from the NHL's draft API (api-web.nhle.com/v1/draft/picks/<year>/all) and every player in
Central Scouting's final rankings (/v1/draft/rankings/<year>/<1-4>: North American and international skaters and
goalies; rank within category, birth date, size, last amateur league). Picks are joined to NHL player ids through the
NHL's player search, confirmed on the player's landing page by draft year and overall pick (an exact join, no name
guessing); the landing page carries the birth date and every season line, junior and pro. Central Scouting rows join
the picks by the shared matcher (scripts/names.py) within the class, checked on birth date where both have one.
"""
import json
import os
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


if __name__ == '__main__':
    a = [int(x) for x in sys.argv[1:] if x.isdigit()]
    lo, hi = (a + [FIRST, 2026])[:2] if a else (FIRST, 2026)
    for y in range(lo, hi + 1):
        t = time.time()
        d = pull(y, fresh='--fresh' in sys.argv)
        n = sum(1 for p in d['picks'] if p.get('id'))
        print(y, len(d['picks']), 'picks', n, 'with NHL id', len(d['css']), 'css', sum(1 for p in d['picks'] if p.get('css')), 'joined',
              f'{time.time() - t:.0f}s', flush=True)
