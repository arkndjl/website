#!/usr/bin/env python3
"""NFL totals vs Open-Meteo kickoff weather (research only, round 2, Oct 24 2026). Cheap retest of the Oct 15 failure.

    python3 scripts/nfl_weather_om_backtest.py      # needs numpy; ~400 archive calls (one per home city-season)

PRE-REGISTERED GATE: same as scripts/cfb_weather_om_backtest.py. Outdoor games (nflverse roof == outdoors) in
scripts/data/games_wf/nfl.json.gz 2015-25 with tm/T/tot, weather at the home team's city (city-level lat/lon is
enough for wind/temperature/rain) over kickoff .. +3 h; leave-one-season-out OLS of tot - tm on
[wind past 10 mph, cold under 40F, rain 0.1in+]; pass = pooled MAE improves, paired t <= -2, most seasons agree,
latest seasons not worse. Also nflverse's own temp/wind columns (observed, what the old test used) for comparison.
"""
import csv
import datetime
import gzip
import io
import json
import math
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, 'data', 'games_wf', 'nfl.json.gz')
CACHE = os.environ.get('NFL_OM_CACHE', '/tmp/nfl_weather_om_cache.json')
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
ARC = 'https://archive-api.open-meteo.com/v1/archive?'
LL = {'ARI': (33.53, -112.26), 'ATL': (33.76, -84.40), 'BAL': (39.28, -76.62), 'BUF': (42.77, -78.79), 'CAR': (35.23, -80.85),
      'CHI': (41.86, -87.62), 'CIN': (39.10, -84.52), 'CLE': (41.51, -81.70), 'DAL': (32.75, -97.09), 'DEN': (39.74, -105.02),
      'DET': (42.34, -83.05), 'GB': (44.50, -88.06), 'HOU': (29.68, -95.41), 'IND': (39.76, -86.16), 'JAX': (30.32, -81.64),
      'KC': (39.05, -94.48), 'LA': (33.95, -118.34), 'LAC': (33.95, -118.34), 'LV': (36.09, -115.18), 'OAK': (37.75, -122.20),
      'MIA': (25.96, -80.24), 'MIN': (44.97, -93.26), 'NE': (42.09, -71.26), 'NO': (29.95, -90.08), 'NYG': (40.81, -74.07),
      'NYJ': (40.81, -74.07), 'PHI': (39.90, -75.17), 'PIT': (40.45, -80.02), 'SD': (32.78, -117.12), 'SEA': (47.60, -122.33),
      'SF': (37.40, -121.97), 'STL': (38.63, -90.19), 'TB': (27.98, -82.50), 'TEN': (36.17, -86.77), 'WAS': (38.91, -76.86)}


def get(u):
    for i in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'arkndjl.net research'}), timeout=60).read())
        except Exception:  # noqa: BLE001 - flaky free source
            time.sleep(4 * (i + 1))


def main():
    rows = list(csv.DictReader(io.StringIO(urllib.request.urlopen(urllib.request.Request(GAMES, headers={'User-Agent': 'x'}), timeout=90).read().decode())))
    G = {g['game_id']: g for g in rows}
    wf = [r for r in json.load(gzip.open(WF)) if r.get('tm') is not None and r.get('T') is not None and r.get('tot') is not None]
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    jobs = defaultdict(list)
    for r in wf:
        g = G.get(r['id'])
        if not g or g['roof'] != 'outdoors' or r['home'] not in LL or not g['gametime']:
            continue
        hh, mm = map(int, g['gametime'].split(':'))
        d = datetime.datetime.fromisoformat(g['gameday']).replace(hour=hh, minute=mm, tzinfo=ZoneInfo('America/New_York')).astimezone(datetime.timezone.utc)
        jobs[(r['home'], r['S'])].append((r, d, g))
    print(len(jobs), 'city-seasons')
    data = []
    for (h, s), lst in sorted(jobs.items()):
        key = f'{h}/{s}'
        if key not in cache:
            d0 = min(d for _, d, _ in lst).date() - datetime.timedelta(days=1)
            d1 = max(d for _, d, _ in lst).date() + datetime.timedelta(days=1)
            j = get(ARC + urllib.parse.urlencode({'latitude': LL[h][0], 'longitude': LL[h][1], 'start_date': d0.isoformat(), 'end_date': d1.isoformat(),
                                                  'hourly': 'temperature_2m,wind_speed_10m,precipitation', 'timezone': 'UTC', 'wind_speed_unit': 'mph',
                                                  'temperature_unit': 'fahrenheit', 'precipitation_unit': 'inch'}))
            if not j or 'hourly' not in j:
                print('fail', key)
                continue
            cache[key] = j['hourly']
            time.sleep(0.5)
            json.dump(cache, open(CACHE, 'w'))
        H = cache[key]
        idx = {t: i for i, t in enumerate(H['time'])}
        for r, d, g in lst:
            k0 = d.replace(minute=0, second=0, microsecond=0)
            ix = [idx[t] for t in ((k0 + datetime.timedelta(hours=q)).strftime('%Y-%m-%dT%H:00') for q in range(4)) if t in idx]
            if len(ix) < 4:
                continue
            w = [H['wind_speed_10m'][i] for i in ix]
            t = [H['temperature_2m'][i] for i in ix]
            p = [H['precipitation'][i] or 0 for i in ix]
            if None in w or None in t:
                continue
            nv = (float(g['wind']) if g['wind'] else None, float(g['temp']) if g['temp'] else None)
            data.append({'S': r['S'], 'ytm': r['tot'] - r['tm'], 'yT': r['tot'] - r['T'], 'wind': float(np.mean(w)), 'temp': float(np.mean(t)),
                         'rain': float(sum(p)), 'nwind': nv[0], 'ntemp': nv[1]})
    print(len(data), 'outdoor games with weather')
    res = {'n': len(data)}

    def X(rows, src):
        if src == 'om':
            return np.array([[1, max(r['wind'] - 10, 0), max(40 - r['temp'], 0), 1.0 if r['rain'] >= 0.1 else 0.0] for r in rows])
        return np.array([[1, max((r['nwind'] if r['nwind'] is not None else 8) - 10, 0), max(40 - (r['ntemp'] if r['ntemp'] is not None else 60), 0), 0.0] for r in rows])

    for src in ('om', 'nflverse'):
        for yk, yn in (('ytm', 'tot-tm'), ('yT', 'tot-T')):
            for mode in ('loso', 'wf'):
                pairs = []
                for s in sorted({r['S'] for r in data}):
                    tr = [r for r in data if (r['S'] != s if mode == 'loso' else r['S'] < s)]
                    te = [r for r in data if r['S'] == s]
                    if len({r['S'] for r in tr}) < 3:
                        continue
                    y = np.array([r[yk] for r in tr])
                    A = X(tr, src)[:, :3 if src == 'nflverse' else 4]
                    b = np.linalg.lstsq(A, y, rcond=None)[0]
                    p1 = X(te, src)[:, :A.shape[1]] @ b
                    for r, q in zip(te, p1):
                        pairs.append((s, abs(r[yk] - y.mean()), abs(r[yk] - q)))
                d = np.array([p[2] - p[1] for p in pairs])
                t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
                by = defaultdict(list)
                for p in pairs:
                    by[p[0]].append(p[2] - p[1])
                seas = {int(s): round(float(np.mean(v)), 3) for s, v in sorted(by.items())}
                res[f'{src}/{yn}/{mode}'] = {'n': len(d), 'mae0': round(float(np.mean([p[1] for p in pairs])), 3), 'dMAE': round(float(d.mean()), 4),
                                             't': round(t, 2), 'better': f"{sum(v < 0 for v in seas.values())}/{len(seas)}", 'seasons': seas}
                print(src, yn, mode, res[f'{src}/{yn}/{mode}'])
    json.dump(res, open(os.path.join(HERE, 'data', 'nfl_weather_om_backtest.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
