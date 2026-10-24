#!/usr/bin/env python3
"""Open-Meteo historical weather for CFB home games (research only, round 2, Oct 24 2026).

    python3 scripts/cfb_weather_om.py            # fills scripts/data/cfb_weather_om.json (resumable)

Venue = the home team's modal venue in scripts/data/cfb_weather.json (ESPN venue records, 2025-26), applied to every
non-neutral game 2017-26 in the walk-forward file. Venue lat/lon from Open-Meteo's geocoder (city + state checked), not
Nominatim (which put Beaver Stadium in Alabama). One archive call per venue-season (Aug 15 - Jan 20), hourly wind 10 m,
gusts, temperature and precipitation at the stadium; per game the mean/max over kickoff .. kickoff + 3 h (UTC hours).
Indoor venues (ESPN record) are skipped. Free, no key; stops cleanly on the daily-limit error and resumes next run.
"""
import datetime
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')
OLD = os.path.join(HERE, 'data', 'cfb_weather.json')
OUT = os.path.join(HERE, 'data', 'cfb_weather_om.json')
UA = {'User-Agent': 'arkndjl.net research (github.com/arkndjl/website)'}
GEO = 'https://geocoding-api.open-meteo.com/v1/search?'
ARC = 'https://archive-api.open-meteo.com/v1/archive?'
STATES = {'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California', 'CO': 'Colorado',
          'CT': 'Connecticut', 'DE': 'Delaware', 'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia',
          'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
          'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland', 'MA': 'Massachusetts',
          'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana',
          'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico',
          'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
          'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota',
          'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington',
          'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming'}
FIX = {'USAF Academy': 'Colorado Springs', 'Dekalb': 'DeKalb', 'University Park': 'State College'}


class Limit(Exception):
    pass


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            if 'limit' in body.lower() and 'concurrent' not in body.lower():
                raise Limit(body)
            time.sleep(5 * (i + 1))
        except Exception:  # noqa: BLE001 - flaky free source
            time.sleep(3 * (i + 1))
    return None


def geocode(v):
    city = FIX.get(v.get('city'), v.get('city'))
    j = get(GEO + urllib.parse.urlencode({'name': city, 'count': 10, 'countryCode': 'US', 'format': 'json'})) or {}
    for p in j.get('results') or []:
        if p.get('admin1') == STATES.get(v.get('st')):
            return round(p['latitude'], 3), round(p['longitude'], 3)
    return None


def main():
    rows = json.load(gzip.open(WF))
    old = json.load(open(OLD))
    byid = {r['id']: r for r in rows}
    cnt = {}
    for gid, g in old['games'].items():
        r = byid.get(gid)
        if r and not r['neutral'] and g.get('venue'):
            cnt.setdefault(r['home'], {}).setdefault(g['venue'], 0)
            cnt[r['home']][g['venue']] += 1
    home_v = {h: max(c, key=c.get) for h, c in cnt.items()}
    have = json.load(open(OUT)) if os.path.exists(OUT) else {'venues': {}, 'games': {}, 'done': []}
    import concurrent.futures
    todo = [vid for vid in set(home_v.values()) if vid not in have['venues'] and not (old['venues'].get(vid) or {}).get('indoor')]
    print(len(todo), 'venues to geocode', flush=True)

    def one(vid):
        ov = old['venues'].get(vid) or {}
        ll = geocode(ov)
        have['venues'][vid] = {'name': ov.get('name'), 'city': ov.get('city'), 'st': ov.get('st'),
                               'lat': ll[0] if ll else None, 'lon': ll[1] if ll else None}
    with concurrent.futures.ThreadPoolExecutor(3) as ex:
        list(ex.map(one, todo))
    json.dump(have, open(OUT, 'w'))
    have['home'] = home_v
    today = datetime.date.today()
    jobs = {}
    for r in rows:
        if r['neutral'] or r['home'] not in home_v or home_v[r['home']] not in have['venues'] or r['id'] in have['games']:
            continue
        vid = home_v[r['home']]
        if have['venues'][vid]['lat'] is None:
            continue
        d = datetime.datetime.fromisoformat(r['date'].replace('Z', '+00:00'))
        if d.date() > today - datetime.timedelta(days=6):
            continue
        jobs.setdefault((vid, r['S']), []).append((r, d))
    print(len(jobs), 'venue-seasons to fetch')
    items = sorted(jobs.items())

    def fetch(item):
        (vid, s), lst = item
        v = have['venues'][vid]
        d0 = min(d for _, d in lst).date() - datetime.timedelta(days=1)
        d1 = max(d for _, d in lst).date() + datetime.timedelta(days=1)
        q = {'latitude': v['lat'], 'longitude': v['lon'], 'start_date': d0.isoformat(), 'end_date': d1.isoformat(),
             'hourly': 'temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation', 'timezone': 'UTC',
             'wind_speed_unit': 'mph', 'temperature_unit': 'fahrenheit', 'precipitation_unit': 'inch'}
        return item, get(ARC + urllib.parse.urlencode(q))

    try:
        with concurrent.futures.ThreadPoolExecutor(3) as ex:
            for n, (item, j) in enumerate(ex.map(fetch, items)):
                (vid, s), lst = item
                if not j or 'hourly' not in j:
                    print('  fail', vid, s)
                    continue
                H = j['hourly']
                idx = {t: i for i, t in enumerate(H['time'])}
                for r, d in lst:
                    k0 = d.replace(minute=0, second=0, microsecond=0)
                    ix = [idx[t] for t in ((k0 + datetime.timedelta(hours=h)).strftime('%Y-%m-%dT%H:00') for h in range(4)) if t in idx]
                    if len(ix) < 4:
                        continue

                    def col(nm):
                        return [H[nm][i] for i in ix if H[nm][i] is not None]
                    w, g, t, p = col('wind_speed_10m'), col('wind_gusts_10m'), col('temperature_2m'), col('precipitation')
                    if not w or not t:
                        continue
                    have['games'][r['id']] = {'v': vid, 'wind': round(sum(w) / len(w), 1), 'gust': round(max(g), 1) if g else None,
                                              'temp': round(sum(t) / len(t), 1), 'rain': round(sum(p), 3) if p else 0.0}
                if n % 40 == 0:
                    print(n, len(have['games']), time.strftime('%H:%M:%S'), flush=True)
                    json.dump(have, open(OUT, 'w'))
    except Limit as e:
        print('daily limit hit; resume later', str(e)[:120])
    json.dump(have, open(OUT, 'w'))
    print('games with weather', len(have['games']))


if __name__ == '__main__':
    sys.exit(main())
