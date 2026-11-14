# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Matchday squads (lineup + bench, with Transfermarkt's value at the game) of senior national-team matches from
Transfermarkt's JSON API. Walks national teams outward from a seed through their yearly fixture lists.

    python3 scripts/research/leads_nov14/intl_squads_pull.py [first year] [last year]

Cache: scripts/.cache/soccer/intl/tm/{fx,g,club}/. One compact file per game.
"""
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '..', '..', '.cache', 'soccer', 'intl', 'tm')
API = 'https://tmapi-alpha.transfermarkt.technology'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
SEED = ['3262', '3439', '3437', '3300', '3433', '3435', '3448', '3505']


def get(path, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(API + path, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 + 3 * i)
        except Exception:
            time.sleep(2 + 3 * i)
    return False


def cached(kind, key, path, shrink):
    p = os.path.join(CACHE, kind, key + '.json')
    if os.path.exists(p):
        return json.load(open(p))
    d = get(path)
    if d is False:
        return None
    out = shrink((d or {}).get('data') or {}) if d else {}
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.%d.tmp' % os.getpid()
    json.dump(out, open(tmp, 'w'), separators=(',', ':'))
    os.replace(tmp, p)
    return out


def fx_shrink(d):
    out = []
    for g in d.get('games') or []:
        b = g.get('baseDetails') or {}
        s = g.get('score') or {}
        out.append({'id': g.get('gameId'), 'c': b.get('competitionId'), 'd': ((b.get('date') or {}).get('dateTimeUTC') or '')[:10],
                    'h': (g.get('homeClub') or {}).get('clubId'), 'a': (g.get('awayClub') or {}).get('clubId'),
                    'hs': s.get('home'), 'as': s.get('away'), 'fin': g.get('isFinished'), 'add': s.get('additionType')})
    return out


def side(c):
    lu = c.get('lineup') or {}
    f = lambda xs: [[p.get('id'), ((p.get('marketValue') or {}).get('value')), p.get('ageAtGameDate'), p.get('positionId')] for p in xs or []]  # noqa: E731
    return {'id': c.get('clubId'), 'xi': f(lu.get('players')), 'sub': f(lu.get('substitutes')),
            'sq': (c.get('squadMarketValue') or {}).get('value')}


def g_shrink(d):
    b = d.get('baseDetails') or {}
    return {'id': d.get('id'), 'c': b.get('competitionId'), 'd': ((b.get('date') or {}).get('dateTimeUTC') or '')[:10],
            'h': side(d.get('homeClub') or {}), 'a': side(d.get('awayClub') or {})}


def club_shrink(d):
    b = d.get('baseDetails') or {}
    return {'id': d.get('id'), 'name': d.get('name'), 'nat': b.get('isNationalTeam'), 'main': b.get('mainClubId'),
            'type': b.get('clubTypeId'), 'country': b.get('countryId')}


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2004
    y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    years = list(range(y0, y1 + 1))
    teams, done = set(SEED), set()
    games = {}
    ex = ThreadPoolExecutor(8)
    while teams - done:
        new = sorted(teams - done)
        clubs = list(ex.map(lambda t: cached('club', t, f'/club/{t}', club_shrink), new))
        ok = [t for t, c in zip(new, clubs) if c and c.get('nat') and c.get('main') == t]
        done |= set(new)
        jobs = [(t, y) for t in ok for y in years]
        for (t, y), fx in zip(jobs, ex.map(lambda j: cached('fx', f'{j[0]}_{j[1]}', f'/club/{j[0]}/fixtures?season={j[1]}', fx_shrink), jobs)):
            for g in fx or []:
                if g.get('id') and g.get('fin'):
                    games[g['id']] = g
                    teams.add(g['h'])
                    teams.add(g['a'])
        print('teams', len(done), 'senior', len(ok), 'games', len(games), flush=True)
    ids = sorted(games)
    n = 0
    for i in range(0, len(ids), 400):
        res = list(ex.map(lambda g: cached('g', g, f'/game/{g}', g_shrink), ids[i:i + 400]))
        n += sum(1 for r in res if r)
        print('games', i + len(res), '/', len(ids), 'ok', n, flush=True)


if __name__ == '__main__':
    main()
