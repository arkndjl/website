#!/usr/bin/env python3
"""History for the NCAA tournament model (scripts/cbb_tourney.py): each season's field with seeds and regions, and
every conference tournament game, written to scripts/data/cbb_tourney_hist.json (committed).

    python3 scripts/cbb_tourney_hist.py              # 2014-2026 (2020 had no tournament)
    python3 scripts/cbb_tourney_hist.py 2026         # one season

Source: ESPN scoreboard (groups=50, all of D-I) for Feb 20 - Apr 10, cached in scripts/.cache/cbb/tourney/. A game's
competition type 'TRNMNT' with tournamentId 22 is the NCAA tournament (curatedRank is the seed there); any other
tournamentId between two teams of one conference is that conference's tournament. Each team's conferenceId comes along.
"""
import json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import cbb_games_hist as H

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache', 'cbb', 'tourney')
OUT = os.path.join(HERE, 'data', 'cbb_tourney_hist.json')
NCAA = '22'
# games and seeds the ESPN feed lacks: 2017's Tuesday First Four, LIU Brooklyn's 2018 seed, VCU 2021
PATCH = {2017: {'games': [{'id': 'p2017a', 'date': '2017-03-14T23:40Z', 'home': '116', 'away': '2443', 'hs': 67, 'as': 66},
                          {'id': 'p2017b', 'date': '2017-03-15T02:10Z', 'home': '2306', 'away': '154', 'hs': 95, 'as': 88}],
                'field': {'116': (16, 'East'), '2443': (16, 'East'), '2306': (11, 'South'), '154': (11, 'South')}},
         2018: {'field': {'6446': (16, 'East')}},
         2021: {'field': {'2670': (10, 'West')}}}            # VCU, selected, out before its game (COVID)
REGION = re.compile(r'(East|West|South|Midwest|Southeast|Southwest)\s+Region', re.I)


def dates(season):
    d, end = date(season, 2, 20), date(season, 4, 10)
    while d <= end:
        yield d.strftime('%Y%m%d')
        d += timedelta(days=1)


def season(s):
    with ThreadPoolExecutor(8) as ex:
        days = list(ex.map(lambda d: H.cached(H.SB.format(d=d), os.path.join(CACHE, str(s), f'{d}.json')), list(dates(s))))
    conf, field, games, seen = {}, {}, [], set()
    for j in days:
        for e in (j or {}).get('events', []):
            if e['id'] in seen:
                continue
            seen.add(e['id'])
            c = e['competitions'][0]
            side = {x['homeAway']: x for x in c['competitors']}
            if 'home' not in side or 'away' not in side or not c['status']['type'].get('completed'):
                continue
            for x in side.values():
                if x['team'].get('conferenceId'):
                    conf[x['team']['id']] = x['team']['conferenceId']
            if (c.get('type') or {}).get('abbreviation') != 'TRNMNT':
                continue
            note = ' '.join(n.get('headline', '') for n in c.get('notes') or [])
            h, a = side['home'], side['away']
            g = {'id': e['id'], 'date': e['date'], 'tid': str(c.get('tournamentId') or ''), 'home': h['team']['id'], 'away': a['team']['id'],
                 'hs': int(h['score']), 'as': int(a['score']), 'neutral': bool(c.get('neutralSite')), 'note': note}
            if g['tid'] == NCAA:
                m = REGION.search(note)
                for x in (h, a):
                    sd = (x.get('curatedRank') or {}).get('current')
                    f = field.setdefault(x['team']['id'], {})
                    if sd and sd <= 16:
                        f['seed'] = sd
                    if m:
                        f['region'] = m[1].title()
            games.append(g)
    for g in PATCH.get(s, {}).get('games', []):
        games.append(dict(g, tid=NCAA, neutral=True, note="MEN'S BASKETBALL CHAMPIONSHIP - FIRST FOUR"))
    for t, (sd, rg) in PATCH.get(s, {}).get('field', {}).items():
        field.setdefault(t, {}).update(seed=sd, region=rg)
    games.sort(key=lambda g: (g['date'], g['id']))
    for g in games:
        g['ch'], g['ca'] = conf.get(g['home']), conf.get(g['away'])
    ncaa = [g for g in games if g['tid'] == NCAA]
    ct = [g for g in games if g['tid'] != NCAA and g['ch'] and g['ch'] == g['ca'] and g['date'] < (ncaa[0]['date'] if ncaa else '9')]
    return {'field': field, 'ncaa': ncaa, 'conftourn': ct, 'conf': conf}


def main():
    seasons = [int(a) for a in sys.argv[1:] if a.isdigit()] or [s for s in range(2014, 2027) if s != 2020]
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for s in seasons:
        r = season(s)
        out[str(s)] = r
        seeds = sorted(v.get('seed', 0) for v in r['field'].values())
        print(s, len(r['field']), 'teams', sum(1 for v in r['field'].values() if 'seed' in v), 'seeded', len(r['ncaa']), 'NCAA games',
              len(r['conftourn']), 'conf tourney games', 'seed sum', sum(seeds), flush=True)
    with open(OUT, 'w') as f:
        json.dump({k: out[k] for k in sorted(out)}, f, separators=(',', ':'))


if __name__ == '__main__':
    main()
