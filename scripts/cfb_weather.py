#!/usr/bin/env python3
"""Game-time weather for college football games with opening and closing totals (research only, Oct 21 2026).

    python3 scripts/cfb_weather.py        # fills scripts/data/cfb_weather.json, skipping games already in it

For each game in the walk-forward file (scripts/data/games_wf/cfb.json.gz): the venue and kickoff from ESPN's summary,
whether the venue is indoors from ESPN's venue record, the venue's place from OpenStreetMap's geocoder (Nominatim, 1
request a second), and the weather at the nearest airport (ASOS) station from the Iowa Environmental Mesonet archive:
mean wind, highest gust, mean temperature and rain over kickoff to 3.5 hours after. All free, no key. Open-Meteo was
the plan's source; its free archive was over its daily limit from this machine, so the airport stations stand in.

Observed weather, not the forecast a bettor had: the totals test in scripts/close_model.py (--weather) is an upper bound
on what a forecast could have told the market.
"""
import concurrent.futures
import datetime
import gzip
import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')
OUT = os.path.join(HERE, 'data', 'cfb_weather.json')
UA = {'User-Agent': 'arkndjl.net research (github.com/arkndjl/website)'}
SUM = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={}'
VEN = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/venues/{}'
GEO = 'https://nominatim.openstreetmap.org/search?{}'
NET = 'https://mesonet.agron.iastate.edu/geojson/network/{}_ASOS.geojson'
ASOS = 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?{}'


def get(url, tries=4, raw=False):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                b = r.read().decode('utf-8', 'replace')
                return b if raw else json.loads(b)
        except Exception as e:  # noqa: BLE001 - a flaky free source; retry, then give up on this one
            if i == tries - 1:
                print('  fail', url[:100], e)
                return None
            time.sleep(2 ** i)


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def main():
    rows = json.load(gzip.open(WF))
    have = json.load(open(OUT)) if os.path.exists(OUT) else {'games': {}, 'venues': {}}
    G, V = have['games'], have['venues']
    nets = {}

    def stations(st):
        if st not in nets:
            j = get(NET.format(st)) or {'features': []}
            nets[st] = [(f['id'], f['geometry']['coordinates'][1], f['geometry']['coordinates'][0], f['properties'].get('archive_end'))
                        for f in j['features'] if f.get('geometry')]
        return nets[st]

    todo = [r for r in rows if r.get('To') is not None and r['id'] not in G]
    print(len(todo), 'games to fetch')
    geo_lock, net_lock = threading.Lock(), threading.Lock()

    def venue(v):
        vid = v.get('id')
        with geo_lock:          # Nominatim asks for one request a second
            if vid in V:
                return V[vid]
            a = v.get('address') or {}
            core = get(VEN.format(vid)) or {}
            q = urllib.parse.urlencode({'city': a.get('city', ''), 'state': a.get('state', ''), 'country': 'USA', 'format': 'json', 'limit': 1})
            g = get(GEO.format(q)) or []
            time.sleep(1.1)
            V[vid] = {'name': v.get('fullName'), 'city': a.get('city'), 'st': a.get('state'), 'indoor': core.get('indoor'),
                      'grass': core.get('grass'), 'lat': float(g[0]['lat']) if g else None, 'lon': float(g[0]['lon']) if g else None}
            return V[vid]

    def one(r):
        s = get(SUM.format(r['id']))
        if not s:
            return
        v = (s.get('gameInfo') or {}).get('venue') or {}
        kick = s['header']['competitions'][0]['date']
        ve = venue(v) if v.get('id') else {}
        e = {'venue': v.get('id'), 'kick': kick}
        if ve.get('lat') is not None and ve.get('st'):
            k0 = datetime.datetime.fromisoformat(kick.replace('Z', '+00:00'))
            day = k0.date().isoformat()
            with net_lock:
                st = stations(ve['st'])
            near = sorted(((km((ve['lat'], ve['lon']), (la, lo)), sid) for sid, la, lo, end in st
                           if not end or end >= day), key=lambda x: x[0])[:3]
            for d, sid in near:
                a0, a1 = k0 - datetime.timedelta(hours=1), k0 + datetime.timedelta(hours=4)
                q = [('station', sid), ('data', 'sknt'), ('data', 'gust'), ('data', 'tmpf'), ('data', 'p01i'),
                     ('year1', a0.year), ('month1', a0.month), ('day1', a0.day), ('hour1', a0.hour),
                     ('year2', a1.year), ('month2', a1.month), ('day2', a1.day), ('hour2', a1.hour),
                     ('tz', 'Etc/UTC'), ('format', 'onlycomma'), ('missing', 'M'), ('report_type', '3'), ('report_type', '4')]
                txt = get(ASOS.format(urllib.parse.urlencode(q)), raw=True) or ''
                obs = []
                for line in txt.splitlines()[1:]:
                    p = line.split(',')
                    if len(p) < 6:
                        continue
                    t = datetime.datetime.fromisoformat(p[1]).replace(tzinfo=datetime.timezone.utc)
                    if k0 <= t <= k0 + datetime.timedelta(hours=3.5):
                        obs.append([None if x in ('M', '') else (0.0 if x == 'T' else float(x)) for x in p[2:6]])
                wind = [o[0] for o in obs if o[0] is not None]
                if not wind:
                    continue
                gust = [o[1] for o in obs if o[1] is not None]
                temp = [o[2] for o in obs if o[2] is not None]
                rain = [o[3] for o in obs if o[3] is not None]
                e.update({'station': sid, 'km': round(d, 1), 'wind': round(sum(wind) / len(wind) * 1.15078, 1),
                          'gust': round(max(gust) * 1.15078, 1) if gust else None,
                          'temp': round(sum(temp) / len(temp), 1) if temp else None, 'rain': round(sum(rain), 2) if rain else 0.0})
                break
        G[r['id']] = e

    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        for n, _ in enumerate(ex.map(one, todo)):
            if n % 100 == 0:
                print(n, flush=True)
                with geo_lock:
                    json.dump({'games': dict(G), 'venues': dict(V)}, open(OUT, 'w'), indent=0)
    json.dump(have, open(OUT, 'w'), indent=0)
    print('done', len(G), 'games,', len(V), 'venues')


if __name__ == '__main__':
    main()
