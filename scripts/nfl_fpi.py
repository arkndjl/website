#!/usr/bin/env python3
"""ESPN's NFL game predictor (FPI) for every game, home side: forecast margin (teamPredPtDiff), win chance
(gameProjection) and the record's lastModified, from the core API .../events/E/competitions/E/predictor.
    python3 scripts/nfl_fpi.py [first season]     # -> scripts/data/public_ratings/nfl_fpi.json.gz (game_id -> row)
A game already pulled is never pulled again; this season's unplayed games are refreshed every run.
"""
import csv
import gzip
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'data', 'public_ratings', 'nfl_fpi.json.gz')
URL = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{i}/competitions/{i}/predictor'


def get(u, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={'user-agent': 'Mozilla/5.0 (arkndjl.net arkboard)'}), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return {}
            time.sleep(1.5 * (k + 1))
        except Exception:
            time.sleep(1.5 * (k + 1))
    return None


def row(eid):
    d = get(URL.format(i=eid))
    if d is None:
        return None
    st = {s['name']: s['value'] for s in (d.get('homeTeam') or {}).get('statistics', [])}
    return {'mod': d.get('lastModified'), 'pd': st.get('teamPredPtDiff'), 'wp': st.get('gameProjection')}


def main():
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 2015
    import nfl_games as N
    games = list(csv.DictReader(open(N.get('games.csv', f'{N.REL}/schedules/games.csv'))))
    have = json.load(gzip.open(OUT)) if os.path.exists(OUT) else {}
    todo = [g for g in games if int(g['season']) >= first and g['espn'] not in ('', 'NA')
            and (g['game_id'] not in have or g['result'] in ('', 'NA'))]
    print('pulling', len(todo), flush=True)
    with ThreadPoolExecutor(8) as ex:
        for g, r in zip(todo, ex.map(lambda g: row(g['espn']), todo)):
            if r is not None:
                have[g['game_id']] = r
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, 'wt') as f:
        json.dump(have, f, separators=(',', ':'))
    print('games', len(have), 'with margin', sum(1 for r in have.values() if r.get('pd') is not None))


if __name__ == '__main__':
    sys.path.insert(0, HERE)
    main()
