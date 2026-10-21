#!/usr/bin/env python3
"""Our season sims next to DraftKings' futures prices from ESPN (data/futures_board_<sport>.json). Display only: no
positions, no stakes. The win-total backtest (data/futures_fit.json) found no proven edge, so the page labels these
as not beating the line yet.

    python3 scripts/futures_board.py nba    # after scripts/nba_games.py (data/nba_games.json)
    python3 scripts/futures_board.py nfl    # after scripts/nfl_games.py

ESPN's core API lists DraftKings futures (title, conference, division winners; no win totals) for free, no key.
Each market's prices are turned into chances and the vig removed by scaling them to sum to 1 (to the number of
winners for a market with more than one).
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = 'https://sports.core.api.espn.com/v2/sports/{}/leagues/{}/seasons/{}/futures?limit=100'
TEAMS = 'https://site.api.espn.com/apis/site/v2/sports/{}/{}/teams?limit=100'
LG = {'nba': ('basketball', 'nba'), 'nfl': ('football', 'nfl')}
# market type -> our sim's field in data/<sport>_games.json power
OURS = {'nba': {'winLeague': 'title', 'winConference': 'conf'},
        'nfl': {'winLeague': 'sb', 'winConference': 'conf', 'winDivision': 'div'}}
NFL = {'WSH': 'WAS', 'LAR': 'LA'}          # ESPN -> nflverse codes (nfl_games.py)


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net futures'}), timeout=60) as r:
                return json.load(r)
        except Exception:
            if i == 3:
                raise
            time.sleep(2 * (i + 1))


def implied(american):
    a = float(american)
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def main():
    sport = sys.argv[1]
    sp, lg = LG[sport]
    d = json.load(open(os.path.join(ROOT, 'data', f'{sport}_games.json')))
    season = int(d['season'])
    ids = {}
    for t in get(TEAMS.format(sp, lg))['sports'][0]['leagues'][0]['teams']:
        ab = t['team']['abbreviation']
        ids[str(t['team']['id'])] = NFL.get(ab, ab) if sport == 'nfl' else ab
    mk = {}                                  # field -> team -> no-vig chance
    for it in get(CORE.format(sp, lg, season)).get('items', []):
        f = OURS[sport].get(it.get('type'))
        if not f:
            continue
        fut = get(it['$ref'])
        books = [b for x in fut.get('futures', []) if x['provider']['name'] == 'DraftKings' for b in x.get('books', [])]
        raw = {}
        for b in books:
            tid = b['team']['$ref'].split('/teams/')[1].split('?')[0]
            try:
                raw[ids.get(tid, tid)] = implied(b['value'])
            except (ValueError, KeyError):
                continue
        s = sum(raw.values())
        if s > 0:
            mk.setdefault(f, {}).update({t: p / s for t, p in raw.items()})   # one winner a market (a division or conference)
        time.sleep(0.3)
    rows = []
    for t in d['power']:
        r = {'t': t['t'], 'rec': t['rec'], 'xW': t['wins']}
        for f in OURS[sport].values():
            r[f] = t.get(f)
            r[f + 'Dk'] = round(mk[f][t['t']], 3) if f in mk and t['t'] in mk[f] else None
        rows.append(r)
    out = {'sport': sport, 'season': season, 'asof': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'modelAsof': d['asof'],
           'book': 'DraftKings via ESPN', 'markets': list(OURS[sport].values()), 'rows': rows}
    with open(os.path.join(ROOT, 'data', f'futures_board_{sport}.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print(sport, len(rows), 'teams', {f: len(v) for f, v in mk.items()})


if __name__ == '__main__':
    main()
