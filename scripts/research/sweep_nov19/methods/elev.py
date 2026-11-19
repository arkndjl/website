# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Venue elevation table (PREREG.md M8): srtm90m elevations from api.opentopodata.org for the repo's CFB venues, CBB
team home cities and the cities of full internationals since 1990. -> scripts/data/venue_elev.json

    python3 scripts/research/sweep_nov19/methods/elev.py <cities.json> <results.csv>

cities.json: a public city list (name, lat, lng, ISO country; github.com/lutangar/cities.json), read for the
internationals' city coordinates. Polite: one call a second, 100 points a call.
"""
import csv
import json
import os
import subprocess
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
OUTF = os.path.join(ROOT, 'scripts', 'data', 'venue_elev.json')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'


def nk(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return ''.join(c for c in s if c.isalnum())


def elevations(pts):
    out = []
    for i in range(0, len(pts), 100):
        loc = '|'.join(f'{a},{b}' for a, b in pts[i:i + 100])
        for attempt in range(3):
            r = subprocess.run(['curl', '-sS', '-m', '60', '-A', UA, f'https://api.opentopodata.org/v1/srtm90m?locations={loc}'], capture_output=True, text=True)
            try:
                d = json.loads(r.stdout)
                if d.get('status') == 'OK':
                    out += [x['elevation'] for x in d['results']]
                    break
            except ValueError:
                pass
            time.sleep(3)
        else:
            out += [None] * len(pts[i:i + 100])
        time.sleep(1.1)
    return out


def main(cities_f, results_f):
    import soccer_intl as I
    out = {'source': 'api.opentopodata.org srtm90m', 'cfb': {}, 'cbb': {}, 'intl': {}}
    V = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cfb_weather_om.json')))['venues']
    T = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cbb_venues.json')))['teams']
    cities = {}
    for c in json.load(open(cities_f)):
        cities.setdefault((c['country'].lower(), nk(c['name'])), (float(c['lat']), float(c['lng'])))
    need, miss = {}, 0
    for r in csv.DictReader(open(results_f, encoding='utf-8')):
        if r['date'] < '1990-01-01':
            continue
        k = f"{r['city']}|{r['country']}"
        if k in need:
            continue
        iso = (I.iso_of(r['country']) or '').lower()
        if iso.startswith('gb-'):
            iso = 'gb'
        need[k] = cities.get((iso, nk(r['city'])))
        miss += need[k] is None
    jobs = [('cfb', k, (v['lat'], v['lon'])) for k, v in V.items()] + [('cbb', k, (v[0], v[1])) for k, v in T.items()] + \
           [('intl', k, v) for k, v in need.items() if v]
    el = elevations([j[2] for j in jobs])
    for (grp, k, pt), e in zip(jobs, el):
        if e is not None:
            out[grp][k] = round(e)
    out['intlCities'] = {'asked': len(need), 'noCoordinates': miss, 'resolved': len(out['intl'])}
    json.dump(out, open(OUTF, 'w'), separators=(',', ':'), sort_keys=True)
    print({k: len(v) for k, v in out.items() if isinstance(v, dict)}, out['intlCities'])


if __name__ == '__main__':
    main(*sys.argv[1:3])
