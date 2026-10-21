#!/usr/bin/env python3
"""Where college basketball games were played, for the travel and tip-time research (scripts/cbb_sched_research.py).

    python3 scripts/cbb_venues.py      # writes scripts/data/cbb_venues.json (ESPN game summaries, cached; ~10 min cold)

Each team's home city is the most common venue of its home games (ESPN summary gameInfo.venue, two to four games a
team); every neutral-site game between D-I teams gets its own venue. Cities resolve to latitude and longitude through
scripts/geo/us_places.json (plus a short table for the island and foreign events). tz is hours behind Eastern
standard time by state, with the split states cut by longitude.
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HIST = os.path.join(HERE, 'data', 'cbb_games_hist.json.gz')
OUT = os.path.join(HERE, 'data', 'cbb_venues.json')
CACHE = os.path.join(HERE, '.cache', 'cbb', 'venues')
URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={}'
PLACES = json.load(open(os.path.join(HERE, 'geo', 'us_places.json')))
ABROAD = {'paradiseisland': (25.08, -77.32, 0), 'nassau': (25.05, -77.35, 0), 'cancun': (21.16, -86.85, -1),
          'stthomas': (18.34, -64.93, 1), 'charlotteamalie': (18.34, -64.93, 1), 'montegobay': (18.47, -77.92, 0),
          'freeport': (26.53, -78.70, 0), 'lahaina': (20.88, -156.68, -5), 'honolulu': (21.31, -157.86, -5),
          'riviera maya': (20.63, -87.07, -1), 'rivieramaya': (20.63, -87.07, -1), 'playadelcarmen': (20.63, -87.07, -1),
          'vancouver': (49.28, -123.12, -3), 'toronto': (43.65, -79.38, 0), 'montreal': (45.50, -73.57, 0),
          'victoria': (48.43, -123.37, -3), 'sanjuan': (18.47, -66.11, 1), 'cayman': (19.30, -81.38, 0),
          'georgetown': (19.29, -81.38, 0), 'maui': (20.88, -156.68, -5), 'bimini': (25.73, -79.25, 0),
          'laval': (45.57, -73.69, 0), 'moncton': (46.09, -64.78, 1), 'belfast': (54.60, -5.93, 5),
          'brooklyn': (40.68, -73.98, 0), 'bronx': (40.84, -73.87, 0), 'uncasville': (41.43, -72.11, 0),
          'dublin': (53.35, -6.26, 5), 'manila': (14.60, 120.98, 13), 'shanghai': (31.23, 121.47, 13),
          'ramstein': (49.44, 7.60, 6), 'frankfurt': (50.11, 8.68, 6)}
# US places missing from us_places.json (latitude, longitude)
EXTRA = {'fortworth': (32.75, -97.33), 'fortmyers': (26.64, -81.87), 'universitypark': (40.80, -77.86),
         'statenisland': (40.58, -74.15), 'fortwayne': (41.08, -85.14), 'chestnuthill': (42.33, -71.17),
         'northandover': (42.70, -71.13), 'mountpleasant': (43.60, -84.77), 'hamden': (41.40, -72.90),
         'fortcollins': (40.59, -105.08), 'northridge': (34.24, -118.53), 'southeaston': (42.03, -71.10),
         'piscataway': (40.52, -74.46), 'riverdale': (40.89, -73.91), 'smithfield': (41.92, -71.55),
         'moontownship': (40.52, -80.21), 'lorman': (31.87, -91.05), 'pearlharbor': (21.35, -157.95),
         'bayamon': (18.40, -66.16), 'fortlauderdale': (26.12, -80.14), 'fortmyersbeach': (26.45, -81.95)}
ABROAD.update({'london': (51.51, -0.13, 5), 'lethbridge': (49.69, -112.84, -2), 'puertovallarta': (20.65, -105.23, -1),
               'tortola': (18.43, -64.62, 1)})
STATES = {'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA', 'colorado': 'CO',
          'connecticut': 'CT', 'delaware': 'DE', 'district of columbia': 'DC', 'florida': 'FL', 'georgia': 'GA',
          'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS',
          'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD', 'massachusetts': 'MA',
          'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT',
          'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM',
          'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK',
          'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD',
          'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA',
          'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY', 'puerto rico': 'PR'}
TZ = {**{s: 0 for s in 'CT DE DC FL GA IN KY ME MD MA MI NH NJ NY NC OH PA RI SC VT VA WV'.split()},
      **{s: -1 for s in 'AL AR IL IA KS LA MN MS MO NE ND OK SD TN TX WI'.split()},
      **{s: -2 for s in 'AZ CO ID MT NM UT WY'.split()}, **{s: -3 for s in 'CA NV OR WA'.split()},
      'AK': -4, 'HI': -5, 'PR': 1}


def key(s):
    return re.sub(r'[^a-z]', '', (s or '').lower().replace('saint ', 'st ').replace('st. ', 'st '))


def tz_of(st, lat, lon):
    z = TZ.get(st, 0)
    if st == 'TN' and lon > -85.6: z = 0
    if st == 'KY' and lon < -86.0: z = -1
    if st == 'IN' and lon < -87.0: z = -1
    if st == 'FL' and lon < -85.0: z = -1
    if st == 'MI' and lon < -87.5: z = -1
    if st == 'TX' and lon < -104.5: z = -2
    if st == 'ID' and lat > 45.5: z = -3
    return z


def locate(addr):
    city, st = key(addr.get('city')), (addr.get('state') or '').strip()
    st = STATES.get(st.lower(), st.upper())
    if st in PLACES and st != '_src':
        p = PLACES[st].get(city) or PLACES[st].get(city.replace('st', 'saint', 1))
        if not p and len(city) >= 5:                    # consolidated cities: 'nashvilledavidson...', 'indianapoliscity...'
            c = sorted(k for k in PLACES[st] if k.startswith(city))
            p = PLACES[st][c[0]] if c else None
        p = p or EXTRA.get(city)
        if p:
            return [p[0], p[1], tz_of(st, p[0], p[1])]
    a = ABROAD.get(city)
    return list(a) if a else None


def venue(gid):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f'{gid}.json')
    if os.path.exists(fn):
        return json.load(open(fn))
    for i in range(4):
        try:
            req = urllib.request.Request(URL.format(gid), headers={'User-Agent': 'arkndjl.net arkboard'})
            d = json.load(urllib.request.urlopen(req, timeout=20))
            v = (d.get('gameInfo') or {}).get('venue') or {}
            r = {'name': v.get('fullName'), 'addr': v.get('address') or {}}
            json.dump(r, open(fn, 'w'))
            return r
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def main():
    G = json.load(gzip.open(HIST))
    home = defaultdict(list)
    for g in G:
        if not g['neutral']:
            home[g['home']].append(g['id'])
    big = {t for t, v in Counter([g['home'] for g in G] + [g['away'] for g in G]).items() if v >= 30}
    want = []
    for t in big:
        ids = home.get(t, [])
        want += [(t, i) for i in ids[-2:] + ids[len(ids) // 2:len(ids) // 2 + 2]]
    neutral = [g['id'] for g in G if g['neutral'] and g['home'] in big and g['away'] in big]
    with ThreadPoolExecutor(12) as ex:
        tv = list(ex.map(lambda z: (z[0], venue(z[1])), want))
        nv = dict(zip(neutral, ex.map(venue, neutral)))
    teams = {}
    for t in big:
        c = Counter(json.dumps(locate(v['addr'])) for tt, v in tv if tt == t and v and locate(v['addr']))
        if c:
            teams[t] = json.loads(c.most_common(1)[0][0])
    games = {gid: locate(v['addr']) for gid, v in nv.items() if v and locate(v['addr'])}
    miss = Counter((v['addr'].get('city'), v['addr'].get('state')) for v in nv.values() if v and not locate(v['addr']))
    print(len(big), 'teams', len(teams), 'located;', len(neutral), 'neutral games', len(games), 'located')
    print('unlocated neutral cities', miss.most_common(15))
    print('unlocated teams', [(t, [v['addr'] for tt, v in tv if tt == t and v][:1]) for t in big if t not in teams][:40])
    json.dump({'teams': teams, 'games': games}, open(OUT, 'w'), separators=(',', ':'))


if __name__ == '__main__':
    main()
