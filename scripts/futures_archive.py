#!/usr/bin/env python3
"""Daily archive of DraftKings' team futures from ESPN (free), so a market preseason prior can be backtested later.

    python3 scripts/futures_archive.py nba 2027     # appends today's snapshot to scripts/data/futures/archive/nba-2027.jsonl
    python3 scripts/futures_archive.py cbb 2027

One line a day per sport and season: {"d": date, "m": {market name: {ESPN team id: american price}}}. Raw prices, vig
in, every team market (title, conference, division, in-season groups, conference regular-season winners); player
awards left out. Only the first line of each day is kept. No free history of these exists (scripts/futures_hist.py),
so the NBA prior's title-odds map (scripts/nba_market_prior.py) and any college basketball market prior need this.
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, 'data', 'futures', 'archive')
LG = {'nba': ('basketball', 'nba'), 'cbb': ('basketball', 'mens-college-basketball'), 'nfl': ('football', 'nfl'),
      'cfb': ('football', 'college-football')}
CORE = 'https://sports.core.api.espn.com/v2/sports/{}/leagues/{}/seasons/{}/futures?limit=100'


def get(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net futures'}), timeout=60) as r:
                return json.load(r)
        except Exception:            # noqa: BLE001
            time.sleep(2 * (i + 1))
    return {}


def main(sport, season):
    sp, lg = LG[sport]
    fn = os.path.join(DIR, f'{sport}-{season}.jsonl')
    day = time.strftime('%Y-%m-%d', time.gmtime())
    if os.path.exists(fn) and any(json.loads(l).get('d') == day for l in open(fn) if l.strip()):
        return print(sport, season, 'already archived', day)
    m = {}
    for it in get(CORE.format(sp, lg, season)).get('items', []):
        fut = get(it['$ref'])
        px = {}
        for x in fut.get('futures', []):
            if x.get('provider', {}).get('name') != 'DraftKings':
                continue
            for b in x.get('books', []):
                ref = (b.get('team') or {}).get('$ref')
                if not ref or b.get('value') is None:
                    continue                     # player markets (MVP, Wooden) name athletes, not teams
                px[ref.split('/teams/')[1].split('?')[0]] = b['value']
        if px:
            m[it.get('name') or it.get('type') or str(len(m))] = px
        time.sleep(0.3)
    if not m:
        return print(sport, season, 'no team futures')
    os.makedirs(DIR, exist_ok=True)
    with open(fn, 'a') as f:
        f.write(json.dumps({'d': day, 'm': m}, separators=(',', ':')) + '\n')
    print(sport, season, day, {k: len(v) for k, v in m.items()})


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]))
