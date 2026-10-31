#!/usr/bin/env python3
"""Archived NBA and NHL player prop opens from ESPN's core API (propBets), for the props paper tests
(scripts/nba_props_research.py, scripts/nhl_props_research.py). ESPN BET (odds provider 58) is served from Jan 2024
(NBA) / Apr 2024 (NHL) until it left ESPN, DraftKings (provider 100) after that; both for finished games (Oct 31 2026).

    python3 scripts/props_archive.py nba      # -> scripts/data/props/nba_opens.json.gz
    python3 scripts/props_archive.py nhl      # -> scripts/data/props/nhl_opens.json.gz

Each over/under prop is two items at one target (over first, as in props_snap.py); a ladder rung ("X+") is one item, so
the main line is the target that appears twice with prices. Where ESPN marks the sides (`open.over` / `open.under`,
ESPN BET's NHL props from 2024-25 on, where the list order is not over first) the marks decide; else over first. Kept: the open line and the open American prices of both
sides, and the last ones (`current` / `value`, which for a finished game can be in-play).

    {gid: {'k': tip, 'b': '58' | '100', 'props': [[espn athlete id, stat, open L, open oO, open oU, L, oO, oU,
                                                   1 if the sides were marked], ...]}}
"""
import datetime
import gzip
import json
import os
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'
SP = {
    'nba': ('basketball', 'nba', datetime.date(2024, 1, 1),
            {'Total Points': 'pts', 'Total Rebounds': 'reb', 'Total Assists': 'ast',
             'Total Points, Rebounds, and Assists': 'pra', 'Total Points and Rebounds': 'pr',
             'Total Points and Assists': 'pa', 'Total Assists and Rebounds': 'ar', 'Total 3-Point Field Goals': 'fg3',
             'Total Steals': 'stl', 'Total Blocks': 'blk', 'Total Turnovers': 'tov', 'Total Steals and Blocks': 'sb'}),
    'nhl': ('hockey', 'nhl', datetime.date(2024, 3, 1),
            {'Total Shots on Goal': 'sog', 'Total Points': 'pts', 'Total Assists': 'ast', 'Total Goals': 'g',
             'Total Saves': 'sv', 'Total Blocked Shots': 'blk', 'Total Power Play Points': 'ppp', 'Total Hits': 'hit',
             'Total Goals Against': 'ga'}),
}


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


def am(o, k):
    try:
        s = str(((o or {}).get('american') or {}).get(k, '')).strip().lower()
        return 100.0 if s in ('even', 'ev') else float(s)
    except (TypeError, ValueError):
        return None


def main_lines(items, types):
    by = defaultdict(list)
    for it in items:
        s = types.get((it.get('type') or {}).get('name'))
        ref = (it.get('athlete') or {}).get('$ref', '')
        if not s or '/athletes/' not in ref:
            continue
        try:
            op = float(it['open']['target']['value'])
            cur = float(it['current']['target']['value'])
        except (KeyError, TypeError, ValueError):
            continue
        side = next((k for k in ('over', 'under') if k in (it.get('open') or {}) or k in (it.get('current') or {})), None)
        by[(ref.split('/athletes/')[1].split('?')[0], s)].append(
            (op, am(it.get('odds'), 'open'), cur, am(it.get('odds'), 'value'), side))
    out = []
    for (a, s), v in by.items():
        ops = [x[0] for x in v]
        twice = [L for L in set(ops) if ops.count(L) == 2]
        if len(twice) != 1:
            continue
        o, u = [x for x in v if x[0] == twice[0]]
        if (o[4], u[4]) == ('under', 'over'):
            o, u = u, o
        elif (o[4], u[4]) != ('over', 'under') and (o[4] or u[4]):
            continue
        if o[1] is None or u[1] is None:
            continue
        out.append([a, s, o[0], o[1], u[1], o[2], o[3], u[3], 1 if o[4] else 0])
    return out


def game(sport, gid):
    sp, lg, _, types = SP[sport]
    fn = os.path.join(HERE, '.cache', f'{sport}_props', f'{gid}.json')
    if os.path.exists(fn):
        return json.load(open(fn))
    core = f'https://sports.core.api.espn.com/v2/sports/{sp}/leagues/{lg}/events/{gid}/competitions/{gid}/odds'
    res = None
    for b in ('58', '100'):
        items, page = [], 1
        while True:
            j = get(f'{core}/{b}/propBets?limit=1000&page={page}')
            if not j:
                break
            items += j.get('items', [])
            if page >= j.get('pageCount', 1):
                break
            page += 1
        r = main_lines(items, types)
        if r:
            res = {'b': b, 'props': r}
            break
    res = res or {'b': None, 'props': []}
    with open(fn, 'w') as f:
        json.dump(res, f)
    return res


def schedule(sport):
    sp, lg, d0, _ = SP[sport]
    days, d = [], d0
    while d < datetime.date.today():
        if d.month not in (7, 8, 9):
            days.append(d)
        d += datetime.timedelta(days=1)

    def day(d):
        j = get(f'https://site.api.espn.com/apis/site/v2/sports/{sp}/{lg}/scoreboard?dates={d:%Y%m%d}&limit=50') or {}
        return [(e['id'], e['date']) for e in j.get('events', [])
                if (e.get('status') or {}).get('type', {}).get('completed')]
    with ThreadPoolExecutor(8) as ex:
        return dict(x for xs in ex.map(day, days) for x in xs)


def main(sport):
    os.makedirs(os.path.join(HERE, '.cache', f'{sport}_props'), exist_ok=True)
    sched = schedule(sport)
    print(sport, len(sched), 'games', flush=True)
    with ThreadPoolExecutor(8) as ex:
        got = dict(zip(sched, ex.map(lambda g: game(sport, g), sched)))
    res = {g: {'k': sched[g], **v} for g, v in got.items() if v['props']}
    out = os.path.join(HERE, 'data', 'props', f'{sport}_opens.json.gz')
    with gzip.open(out, 'wt') as f:
        json.dump(res, f, separators=(',', ':'))
    print(sport, len(res), 'games with props,', sum(len(v['props']) for v in res.values()), 'main lines')


if __name__ == '__main__':
    for s in sys.argv[1:] or ('nba', 'nhl'):
        main(s)
