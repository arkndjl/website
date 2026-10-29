#!/usr/bin/env python3
"""Archived NFL player prop opens from ESPN's core API (propBets), for the props paper test
(scripts/nfl_props_research.py): ESPN BET (odds provider 58) 2024 through Nov 2025, when ESPN BET left ESPN, and
DraftKings (provider 100) for 2026's finished games, which ESPN still serves for NFL (Oct 29 2026; its NBA props go a day
after the game). Nothing older: 2025's December games have neither provider.

    python3 scripts/nfl_props_archive.py        # -> scripts/data/props/nfl_espnbet_opens.json.gz

Each over/under prop is two items (over, under) at the same target; a milestone rung ("X+ yards") is one item, so the
main line is the target that appears twice. Only `open` is used: `current` was last updated during or after the game
(in-play). Prices are not archived, only lines.

    {gid: {'k': kickoff, 'b': 'espnbet' | 'dk', 'props': [[espn athlete id, stat, open line], ...]}}
"""
import datetime
import gzip
import json
import os
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'data', 'props', 'nfl_espnbet_opens.json.gz')
CACHE = os.path.join(HERE, '.cache', 'nfl_props58')
SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl'
TYPES = {'Total Passing Yards (incl. overtime)': 'py', 'Total Passing Touchdowns (incl. overtime)': 'ptd',
         'Total Pass Completions (incl. overtime)': 'pc', 'Total Passing Attempts (incl. overtime)': 'pa',
         'Total Passing Interceptions (incl. overtime)': 'pint', 'Total Rushing Yards (incl. overtime)': 'ry',
         'Total Carries (incl. overtime)': 'ca', 'Total Receiving Yards (incl. overtime)': 'wy',
         'Total Receptions (incl. overtime)': 'rc', 'Total Rushing Plus Receiving Yards (incl. overtime)': 'rwy',
         'Total Passing Plus Rushing Yards (incl. overtime)': 'pry'}
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'


def get(url):
    for _ in range(3):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
        except Exception:
            pass
    return None


def main_lines(items):
    """[[athlete, stat, open line]] for every over/under whose two items share one target"""
    by = defaultdict(list)
    for it in items:
        s = TYPES.get((it.get('type') or {}).get('name'))
        ref = (it.get('athlete') or {}).get('$ref', '')
        if not s or '/athletes/' not in ref:
            continue
        try:
            cur, op = float(it['current']['target']['value']), float(it['open']['target']['value'])
        except (KeyError, TypeError, ValueError):
            continue
        by[(ref.split('/athletes/')[1].split('?')[0], s)].append((cur, op))
    out = []
    for (a, s), v in by.items():
        twice = [x for x in set(v) if v.count(x) == 2]
        if len(twice) == 1:
            out.append([a, s, twice[0][1]])
    return out


def book(k):
    return '58' if k < '2025-12-01' else '100'


def game(gid, k):
    fn = os.path.join(CACHE, f'{gid}.json')
    if os.path.exists(fn):
        return json.load(open(fn))
    items, page = [], 1
    while True:
        j = get(f'{CORE}/events/{gid}/competitions/{gid}/odds/{book(k)}/propBets?limit=1000&page={page}')
        if not j:
            break
        items += j.get('items', [])
        if page >= j.get('pageCount', 1):
            break
        page += 1
    r = main_lines(items)
    with open(fn, 'w') as f:
        json.dump(r, f)
    return r


def schedule():
    out = {}
    for y in (2024, 2025, 2026):
        for w in range(1, 19):
            j = get(f'{SITE}/scoreboard?dates={y}&seasontype=2&week={w}&limit=100') or {}
            for e in j.get('events', []):
                k = e['date']
                if (e.get('status') or {}).get('type', {}).get('completed') and not '2025-12-01' <= k < '2026-08-01':
                    out[e['id']] = k
    return out


def main():
    os.makedirs(CACHE, exist_ok=True)
    sched = schedule()
    print(len(sched), 'games')
    with ThreadPoolExecutor(6) as ex:
        got = dict(zip(sched, ex.map(game, sched, sched.values())))
    res = {g: {'k': sched[g], 'b': 'espnbet' if book(sched[g]) == '58' else 'dk', 'props': v} for g, v in got.items() if v}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, 'wt') as f:
        json.dump(res, f, separators=(',', ':'))
    print(len(res), 'games with props,', sum(len(v['props']) for v in res.values()), 'main lines')


if __name__ == '__main__':
    main()
