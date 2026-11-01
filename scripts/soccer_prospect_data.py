#!/usr/bin/env python3
"""Soccer prospects data pull: match lineups, minutes and market values from Transfermarkt's public JSON API.

    python3 scripts/soccer_prospect_data.py games [comps] [--seasons 2012-2026]   # every finished game, compact, cached
    python3 scripts/soccer_prospect_data.py players <ids file>                     # player profiles (birth date, position)

The 2012-25 history of the 14 leagues in the Transfermarkt dump (dcaribou/transfermarkt-datasets, free on R2) comes
from that dump (scripts/soccer_prospects.py --dump); this pull adds the current season for those leagues and the feeder
leagues the dump lacks (second divisions, Brazil, Argentina, MLS, smaller European leagues, Premier League 2).
A game is kept as [id, comp, season, date, home, away, hg, ag, minutes, players, actions]; players are
[id, club, starter, position, age at the game, market value at the game]; actions [type, minute, added time, club,
active player, passive player, reason] (for a substitution the active player goes off).
"""
import concurrent.futures as cf
import gzip
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache', 'soccer_prospects', 'tm')
os.makedirs(CACHE, exist_ok=True)   # importers (soccer_prospects.py) write here without calling main()
API = 'https://tmapi-alpha.transfermarkt.technology'
DUMP = ['GB1', 'ES1', 'IT1', 'L1', 'FR1', 'NL1', 'PO1', 'BE1', 'TR1', 'RU1', 'SC1', 'GR1', 'DK1', 'UKR1']
EURO = ['CL', 'EL', 'UCOL']
FEED = ['GB2', 'L2', 'IT2', 'ES2', 'FR2', 'NL2', 'PO2', 'BRA1', 'AR1N', 'ARG1', 'MLS1', 'C1', 'A1', 'TS1', 'KR1', 'NO1',
        'SE1', 'SER1', 'PL1', 'GB21']
# academy and feeder leagues (Oct 31 2026, scripts/soccer_academy_research.py): youth (UEFA Youth League, U18 Premier
# League, Primavera, French U19 groups, Danish/Turkish/Dutch U19), U21/U23 (Liga Revelacao, Swiss U21; PL2 is GB21
# above), and the senior leagues where B teams and young players start (3. Liga and four Regionalligen, Serie C,
# Spain's Segunda B to 2020 and Primera Federacion after, Ligue 3/National, Austria 2. Liga, Challenger Pro League,
# Czech/Croatian/Danish/Norwegian/Swedish/Scottish second tiers, MLS NEXT Pro, USL Championship)
ACADEMY = ['19YL', 'GB18', 'IJ1', 'F19A', 'F19B', 'F19C', 'F19D', 'DKDL', 'T191', 'NLJV']
U23 = ['PT23', 'CHPR']
RESERVE = ['L3', 'RLB3', 'RLW3', 'RLSW', 'RLN3', 'RLN4', 'IT3A', 'IT3B', 'IT3C', 'ES3A', 'ES3B', 'ES3C', 'ES3D', 'E3G1',
           'E3G2', 'FR3', 'A2', 'BE2', 'TS2', 'KR2', 'DK2', 'NO2', 'SE2', 'SC2', 'MNP3', 'USL']
# youth internationals (Oct 31 2026, scripts/soccer_youth_intl_research.py): competition -> (age cap, finals tournament).
# U17/U20 World Cups, U17/U19/U21 Euros and the UEFA qualifiers, CONCACAF U17/U20 and U20 qualifying, South American
# U17/U20, Asian U17/U20, African U20/U17. Transfermarkt files a tournament under the season it starts in
YOUTH_INTL = {'17WC': (17, 1), '20WC': (20, 1), 'U17Q': (17, 0), 'U19Q': (19, 0), 'U21Q': (21, 0), '17EU': (17, 1),
              '19EU': (19, 1), '21EU': (21, 1), 'SAM7': (17, 1), '2SAM': (20, 1), '17AC': (17, 1), '20AC': (20, 1),
              'CO17': (17, 1), 'C220': (20, 1), 'C20Q': (20, 0), 'AU2C': (20, 1), 'AA17': (17, 1)}


def get(path, tries=5):
    for k in range(tries):
        try:
            req = urllib.request.Request(API + path, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** k)
        except Exception:
            time.sleep(2 ** k)
    return None


def compact(d):
    b, sc = d['baseDetails'], d.get('score') or {}
    pl = []
    for side in ('homeClub', 'awayClub'):
        c = d.get(side) or {}
        lu = c.get('lineup') or {}
        for st, key in ((1, 'players'), (0, 'substitutes')):
            for p in lu.get(key) or []:
                pl.append([p['id'], c.get('clubId'), st, (p.get('position') or {}).get('shortName'), p.get('ageAtGameDate'),
                           (p.get('marketValue') or {}).get('value')])
    acts = [[a.get('type'), a.get('minute'), a.get('addedTime'), a.get('clubId'), a.get('activePlayerId'),
             a.get('passivePlayerId'), a.get('actionReasonId')] for a in d.get('actions') or [] if a.get('type') != 'PLACEHOLDER']
    return [d['id'], b.get('competitionId'), b.get('seasonId'), (b.get('date') or {}).get('dateTimeUTC'),
            (d.get('homeClub') or {}).get('clubId'), (d.get('awayClub') or {}).get('clubId'), sc.get('home'), sc.get('away'),
            (d.get('extendedDetails') or {}).get('duration'), pl, acts]


def pull_comp(comp, season, current):
    fn = os.path.join(CACHE, f'{comp}_{season}.json.gz')
    have = {}
    if os.path.exists(fn):
        have = {g[0]: g for g in json.load(gzip.open(fn, 'rt'))}
        if not current:
            return len(have), 0
    fx = get(f'/competition/{comp}/fixtures?season={season}')
    if not fx or not fx.get('data'):
        return len(have), 0
    ids = []
    for f in fx['data'].get('fixtures') or []:
        for g in f.get('games') or []:
            if g.get('isFinished') and (g.get('baseDetails') or {}).get('seasonId') == season and g['gameId'] not in have:
                ids.append(g['gameId'])
    new = 0
    with cf.ThreadPoolExecutor(10) as ex:
        for r in ex.map(lambda i: get(f'/game/{i}'), ids):
            if r and r.get('data'):
                g = compact(r['data'])
                have[g[0]] = g
                new += 1
    tmp = f'{fn}.{os.getpid()}.tmp'
    with gzip.open(tmp, 'wt') as f:
        json.dump(list(have.values()), f)
    os.replace(tmp, fn)
    return len(have), new


PARENTS = os.path.join(HERE, 'data', 'soccer_club_parents.json')


def club_parents(ids):
    """club id -> its first team (Transfermarkt mainClubId; a first team maps to itself): the committed map, plus any
    club new to it fetched once into the cache"""
    have = json.load(open(PARENTS)) if os.path.exists(PARENTS) else {}
    fn = os.path.join(CACHE, 'club_parents.json')
    extra = json.load(open(fn)) if os.path.exists(fn) else {}
    todo = [str(int(i)) for i in ids if str(int(i)) not in have and str(int(i)) not in extra]
    if todo:
        with cf.ThreadPoolExecutor(10) as ex:
            for i, r in zip(todo, ex.map(lambda i: get(f'/club/{i}', tries=3), todo)):
                m = (((r or {}).get('data') or {}).get('baseDetails') or {}).get('mainClubId')
                extra[i] = int(m) if m else int(i)
        json.dump(extra, open(fn, 'w'))
    return {int(k): int(v) for k, v in {**have, **extra}.items()}


def main_pull(comps, season):
    for c in comps:
        n, new = pull_comp(c, season, True)
        print(c, season, n, new, flush=True)


def main():
    os.makedirs(CACHE, exist_ok=True)
    a = sys.argv[1:]
    if a and a[0] == 'players':
        ids = [l.strip() for l in open(a[1]) if l.strip()]
        fn = os.path.join(CACHE, 'players.json.gz')
        have = json.load(gzip.open(fn, 'rt')) if os.path.exists(fn) else {}
        todo = [i for i in ids if i not in have]
        with cf.ThreadPoolExecutor(10) as ex:
            for i, r in zip(todo, ex.map(lambda i: get(f'/player/{i}'), todo)):
                if r and r.get('data'):
                    have[i] = r['data']
        with gzip.open(fn, 'wt') as f:
            json.dump(have, f)
        print(len(have), 'profiles')
        return
    lo, hi = 2012, 2026
    if '--seasons' in a:
        lo, hi = map(int, a[a.index('--seasons') + 1].split('-'))
        a = [x for i, x in enumerate(a) if x != '--seasons' and (i == 0 or a[i - 1] != '--seasons')]
    comps = [c for c in (a[1:] if len(a) > 1 else [])] or None
    plan = []
    for s in range(hi, lo - 1, -1):
        for c in comps or (DUMP + EURO + FEED):
            if c in DUMP + EURO and s < 2026 and not comps:
                continue            # history from the dump
            plan.append((c, s))
    for c, s in plan:
        t = time.time()
        n, new = pull_comp(c, s, s >= hi and hi >= 2026)
        print(c, s, n, new, round(time.time() - t), flush=True)


if __name__ == '__main__':
    main()
