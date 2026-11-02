#!/usr/bin/env python3
"""NFL totals vs forecast wind at kickoff (research; Nov 2 2026 retest of the Oct 24 lead, scripts/nfl_weather_om_backtest.py).

    python3 scripts/nfl_wind_forecast_research.py           # numpy; pulls only games missing from the frozen file
    -> scripts/data/nfl_wind_forecast.json (frozen: game_id -> [wind mph, gust mph], kickoff .. +3 h mean)
    -> data/nfl_wind_forecast_research.json

Oct 24: realized (archive) weather vs the close was LOSO t -2.1 but walk-forward t -0.65. Here wind only, from the
Open-Meteo historical-forecast archive (historical-forecast-api.open-meteo.com: the forecast models' own stitched
hourly runs, what was forecast for the hour, 2021 on), at the home stadium (LL below), kickoff hour to +3 h.
Games: outdoor and open-roof (nflverse roof), not neutral sites, in scripts/data/games_wf/nfl.json.gz with a closing
total, 2021-26 (2026 to date). Target tot - T (result minus the closing total); also tot - tm (the model's total).
Feature: max(wind - 10, 0) with an intercept (the baseline is the intercept alone, same rows).
Gate (pre-registered): tune 2021-23 t(wind) <= -1.5 by week clusters, held 2024-26 squared error paired t <= -1.5 with
the tune coefficient, walk-forward 2022-26 paired t <= -1.5 and most seasons better.

RESULT (Nov 2 2026): FAIL, no model change. 1026 games (210 with forecast wind past 10 mph), 2021 199 / 2022 193 /
2023 194 / 2024 182 / 2025 187 / 2026 71.
    vs the close (tot - T): tune 2021-23 b -0.84 a mph past 10, t -3.43; held 2024-26 own b -0.13, squared error with
      the tune b worse (d +.94, t +0.56); walk-forward 2022-26 t -0.23, 2/5 seasons better (only 2023 clearly)
    vs the model total (tot - tm): tune b -1.17, t -4.42; held own b -0.48, t +0.11; walk-forward t -0.93, 3/5
The close priced forecast wind in 2021-23 only in part and has since (held b near 0); the model total misses some
of it (b -.5 held) but not past the gate. Retest wind in the total model if 2026 holds b <= -.5 against tm.
"""
import csv
import datetime
import gzip
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

ROOT = os.path.dirname(HERE)
WF = os.path.join(HERE, 'data', 'games_wf', 'nfl.json.gz')
FROZEN = os.path.join(HERE, 'data', 'nfl_wind_forecast.json')
OUT = os.path.join(ROOT, 'data', 'nfl_wind_forecast_research.json')
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
API = 'https://historical-forecast-api.open-meteo.com/v1/forecast?'
# home stadiums 2021-26 (scripts/nfl_weather_om_backtest.py's list; LA/LAC SoFi and LV are roofed and drop out by roof)
LL = {'ARI': (33.53, -112.26), 'ATL': (33.76, -84.40), 'BAL': (39.28, -76.62), 'BUF': (42.77, -78.79), 'CAR': (35.23, -80.85),
      'CHI': (41.86, -87.62), 'CIN': (39.10, -84.52), 'CLE': (41.51, -81.70), 'DAL': (32.75, -97.09), 'DEN': (39.74, -105.02),
      'DET': (42.34, -83.05), 'GB': (44.50, -88.06), 'HOU': (29.68, -95.41), 'IND': (39.76, -86.16), 'JAX': (30.32, -81.64),
      'KC': (39.05, -94.48), 'LA': (33.95, -118.34), 'LAC': (33.95, -118.34), 'LV': (36.09, -115.18),
      'MIA': (25.96, -80.24), 'MIN': (44.97, -93.26), 'NE': (42.09, -71.26), 'NO': (29.95, -90.08), 'NYG': (40.81, -74.07),
      'NYJ': (40.81, -74.07), 'PHI': (39.90, -75.17), 'PIT': (40.45, -80.02), 'SEA': (47.60, -122.33),
      'SF': (37.40, -121.97), 'TB': (27.98, -82.50), 'TEN': (36.17, -86.77), 'WAS': (38.91, -76.86)}
FIRST = 2021
TUNE, HELD = (2021, 2022, 2023), (2024, 2025, 2026)


def fetch(u):
    for i in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'arkndjl.net research'}), timeout=90).read())
        except Exception:  # noqa: BLE001 - flaky free source
            time.sleep(5 * (i + 1))
    return None


def kickoff(g):
    hh, mm = map(int, g['gametime'].split(':'))
    return datetime.datetime.fromisoformat(g['gameday']).replace(hour=hh, minute=mm, tzinfo=ZoneInfo('America/New_York')).astimezone(datetime.timezone.utc)


def pull(wf, G):
    frozen = json.load(open(FROZEN)) if os.path.exists(FROZEN) else {}
    jobs = defaultdict(list)
    for r in wf:
        g = G.get(r['id'])
        if (not g or r['id'] in frozen or g['roof'] not in ('outdoors', 'open') or g['location'] == 'Neutral'
                or r['home'] not in LL or not g['gametime']):
            continue
        jobs[(r['home'], r['S'])].append((r['id'], kickoff(g)))
    print(len(jobs), 'team-seasons to pull', flush=True)
    for (h, s), lst in sorted(jobs.items()):
        d0 = min(d for _, d in lst).date()
        d1 = max(d for _, d in lst).date() + datetime.timedelta(days=1)
        j = fetch(API + urllib.parse.urlencode({'latitude': LL[h][0], 'longitude': LL[h][1], 'start_date': d0.isoformat(),
                                                'end_date': d1.isoformat(), 'hourly': 'wind_speed_10m,wind_gusts_10m',
                                                'timezone': 'UTC', 'wind_speed_unit': 'mph'}))
        if not j or 'hourly' not in j:
            print('fail', h, s, flush=True)
            continue
        Hh = j['hourly']
        idx = {t: i for i, t in enumerate(Hh['time'])}
        for gid, d in lst:
            k0 = d.replace(minute=0, second=0, microsecond=0)
            ix = [idx.get((k0 + datetime.timedelta(hours=q)).strftime('%Y-%m-%dT%H:00')) for q in range(4)]
            w = [Hh['wind_speed_10m'][i] for i in ix if i is not None]
            gu = [Hh['wind_gusts_10m'][i] for i in ix if i is not None]
            if len(w) == 4 and None not in w:
                frozen[gid] = [round(float(np.mean(w)), 1), round(float(np.mean([x for x in gu if x is not None] or [0])), 1)]
        save(frozen)
        print('pulled', h, s, flush=True)
        time.sleep(0.4)
    save(frozen)
    return frozen


def save(frozen):
    with open(FROZEN, 'w') as f:
        json.dump(dict(sorted(frozen.items())), f, separators=(',', ':'))


def main():
    rows = list(csv.DictReader(io.StringIO(urllib.request.urlopen(urllib.request.Request(GAMES, headers={'User-Agent': 'x'}), timeout=90).read().decode())))
    G = {g['game_id']: g for g in rows}
    wf = [r for r in json.load(gzip.open(WF)) if r['S'] >= FIRST and r.get('tm') is not None and r.get('T') is not None
          and r.get('tot') is not None]
    W = pull(wf, G)
    D = [r for r in wf if r['id'] in W]
    S = np.array([r['S'] for r in D])
    wk = np.array([f"{r['S']}-{r['wk']}" for r in D])
    x = np.array([max(W[r['id']][0] - 10, 0.0) for r in D])
    res = {'n': len(D), 'windy': int((x > 0).sum()), 'bySeason': {str(s): {'n': int((S == s).sum()), 'windy': int(((S == s) & (x > 0)).sum())}
                                                                 for s in sorted(set(S.tolist()))}}
    for yk, yn in (('T', 'tot-T'), ('tm', 'tot-tm')):
        y = np.array([r['tot'] - r[yk] for r in D])
        out = {}
        tr = np.isin(S, TUNE)
        X = np.c_[np.ones(len(D)), x]
        b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        e = y[tr] - X[tr] @ b
        XtXi = np.linalg.inv(X[tr].T @ X[tr])
        meat = np.zeros((2, 2))
        cl = wk[tr]
        for k in set(cl.tolist()):
            m = cl == k
            s_ = X[tr][m].T @ e[m]
            meat += np.outer(s_, s_)
        se = np.sqrt(np.diag(XtXi @ meat @ XtXi))
        out['tune'] = {'n': int(tr.sum()), 'b': round(float(b[1]), 3), 't': round(float(b[1] / se[1]), 2)}
        he = np.isin(S, HELD)
        b0 = y[tr].mean()
        r = H.paired((y[he] - X[he] @ b) ** 2, (y[he] - b0) ** 2, cluster=wk[he])
        bh = np.linalg.lstsq(X[he], y[he], rcond=None)[0]
        out['held'] = {'n': int(he.sum()), 'bHeldOwn': round(float(bh[1]), 3), 'd': round(r['d'], 4), 't': round(r['t'], 2)}
        ds, ws, per = [], [], {}
        for s in sorted(set(S.tolist())):
            if s == FIRST:
                continue
            a, te = S < s, S == s
            b_ = np.linalg.lstsq(X[a], y[a], rcond=None)[0]
            d = (y[te] - X[te] @ b_) ** 2 - (y[te] - y[a].mean()) ** 2
            ds.append(d)
            ws.append(wk[te])
            per[str(s)] = {'n': int(te.sum()), 'b': round(float(b_[1]), 3), 'dSE': round(float(d.mean()), 4)}
        r = H.paired(np.concatenate(ds), np.zeros(sum(len(d) for d in ds)), cluster=np.concatenate(ws))
        out['walk'] = {'seasons': per, 'dSE': round(r['d'], 4), 't': round(r['t'], 2),
                       'better': f"{sum(v['dSE'] < 0 for v in per.values())}/{len(per)}"}
        out['passes'] = bool(out['tune']['t'] <= -1.5 and out['held']['t'] <= -1.5 and out['walk']['t'] <= -1.5)
        res[yn] = out
        print(yn, json.dumps(out), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
