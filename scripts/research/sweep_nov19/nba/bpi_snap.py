# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ESPN NBA predictor point-in-time check: snapshot the predictor for the games on the given dates.

    python3 bpi_snap.py OUT.json YYYYMMDD [YYYYMMDD ...]

Writes {event id: {date, state, lastModified, home/away stats, fetched}}. Run before tip and again after the final;
bpi_pit.py compares two snapshots. Reads forecasts and game state only, never a score."""
import datetime as dt, json, sys, time, urllib.request

UA = 'Mozilla/5.0'


def get(url):
    for k in range(3):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30))
        except Exception as e:
            err = e; time.sleep(3 * (k + 1))
    return {'error': str(err)}


def stats(side):
    return {s['name']: s.get('value') for s in (side or {}).get('statistics', [])}


def main():
    out, dates = sys.argv[1], sys.argv[2:]
    res = {}
    for d in dates:
        sb = get(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}')
        time.sleep(1.1)
        for ev in sb.get('events', []):
            eid = ev['id']
            p = get(f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{eid}/competitions/{eid}/predictor')
            time.sleep(1.1)
            res[eid] = {'date': ev['date'], 'state': ev['status']['type']['state'], 'lastModified': p.get('lastModified'),
                        'home': stats(p.get('homeTeam')), 'away': stats(p.get('awayTeam')), 'error': p.get('error'),
                        'fetched': dt.datetime.utcnow().isoformat(timespec='seconds') + 'Z'}
    json.dump(res, open(out, 'w'), indent=1)
    print(len(res), 'events ->', out)


if __name__ == '__main__':
    main()
