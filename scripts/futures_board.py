#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Our season sims next to DraftKings' futures prices from ESPN (data/futures_board_<sport>.json). Display only: no
positions, no stakes. The win-total backtest (data/futures_fit.json) found no proven edge, so the page labels these
as not beating the line yet.

    python3 scripts/futures_board.py nba    # after scripts/nba_games.py (data/nba_games.json)
    python3 scripts/futures_board.py nfl    # after scripts/nfl_games.py

ESPN's core API lists DraftKings futures (title, conference, division winners; no win totals) for free, no key.
Each DraftKings market's prices are turned into chances and the vig removed by the power method (devig(): every
chance raised to the one power that makes them sum to 1). Scaling them all by one factor leaves the longshots too
high: a book loads its margin on them. Novig: the two-sided mids take up what the one-sided bounds leave.

    python3 scripts/futures_board.py --test
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


def devig(raw):
    """{team: implied chance with the vig in} -> {team: no-vig chance} by the power method: p ** k with the one k that
    makes them sum to 1 (k > 1 when the book holds a margin). Against scaling by 1 / sum it takes more out of the
    longshots, where a many-way book keeps most of its margin (the favourite-longshot bias). Under two prices, or with
    no margin to take out, they are scaled"""
    ps = {t: p for t, p in raw.items() if 0 < p < 1}
    tot = sum(ps.values())
    if len(ps) < 2 or tot <= 0:
        return {t: p / tot for t, p in ps.items()} if tot > 0 else {}
    lo, hi = (1.0, 50.0) if tot > 1 else (0.02, 1.0)
    for _ in range(80):
        k = (lo + hi) / 2
        lo, hi = (k, hi) if sum(p ** k for p in ps.values()) > 1 else (lo, k)
    k = (lo + hi) / 2
    out = {t: p ** k for t, p in ps.items()}
    z = sum(out.values())
    return {t: p / z for t, p in out.items()}


# Novig event names -> our sim's field (scripts/novig.py; public catalog, no key)
NOVIG = {'nba': {'Championship Winner': 'title', 'Eastern Conference Winner': 'conf', 'Western Conference Winner': 'conf'},
         'nfl': {'Super Bowl Winner': 'sb', 'AFC Conference Winner': 'conf', 'NFC Conference Winner': 'conf',
                 **{f'{c} {d} Winner': 'div' for c in ('AFC', 'NFC') for d in ('East', 'North', 'South', 'West')}}}


def event_size(sport, desc):
    """teams an event's winner comes from: the league, a conference or a division"""
    if 'Division' in desc or any(f' {d} Winner' in desc for d in ('East', 'North', 'South', 'West')) and 'Conference' not in desc:
        return 4
    if 'Conference' in desc:
        return 15 if sport == 'nba' else 16
    return 30 if sport == 'nba' else 32


def scale_event(raw):
    """{team: (p, two_sided)} -> {team: no-vig chance}. A two-sided quote's mid is a price; a one-sided quote (a Yes bid,
    or 1 - a No bid) is only a bound, so it is kept as given and the mids take up the rest of the event's 1 (all
    scaled together only when no team, or the bounds alone, leave nothing for the mids)"""
    mids = {t: p for t, (p, two) in raw.items() if two}
    bnds = {t: p for t, (p, two) in raw.items() if not two}
    sm, sb = sum(mids.values()), sum(bnds.values())
    if sm > 0 and sb < 1:
        k = (1 - sb) / sm
        return {**{t: round(p * k, 4) for t, p in mids.items()}, **{t: round(p, 4) for t, p in bnds.items()}}
    tot = sm + sb
    return {t: round(p / tot, 4) for t, (p, _) in raw.items()} if tot > 0 else {}


def novig_futures(sport, ids):
    """[(field, event, teams in the event, {team: no-vig chance})] from Novig's Yes/No team markets: the mid where both
    sides are quoted, else the one bound a side gives (Yes bid or 1 - No bid); each event scaled to sum to 1
    (scale_event)"""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import names
    import novig
    lg = {'nba': 'NBA', 'nfl': 'NFL'}[sport]
    full = {}
    for t in get(TEAMS.format(*LG[sport]))['sports'][0]['leagues'][0]['teams']:
        ab = t['team']['abbreviation']
        full[names.team_key(t['team']['displayName'])] = NFL.get(ab, ab) if sport == 'nfl' else ab
    out = []
    for e in novig.pages('events', league=lg):
        desc = e.get('description') or ''
        f = NOVIG[sport].get(desc)
        if not f:
            continue
        raw = {}
        for m in novig.pages('markets', event=e['eventId']):
            oc = {(o.get('name') or '').lower(): novig.bid(o) for o in m.get('outcomes') or []}
            yes, no = oc.get('yes'), oc.get('no')
            p = (yes + 1 - no) / 2 if yes is not None and no is not None else yes if yes is not None else 1 - no if no is not None else None
            t = full.get(names.team_key((m.get('description') or '').rsplit(' ', 1)[0]))   # 'Phoenix Suns CHAMPIONSHIP_WINNER'
            if p is not None and t:
                raw[t] = (max(p, 1e-4), yes is not None and no is not None)
        v = scale_event(raw)
        if v:
            out.append((f, desc, event_size(sport, desc), v))
        time.sleep(0.25)
    return out


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
        mk.setdefault(f, {}).update(devig(raw))      # one winner a market (a division or conference)
        time.sleep(0.3)
    # Novig's futures first; each event (a conference, a division, the
    # title) stays on DraftKings unless Novig prices 80%+ of that event's own teams (its futures books are thin)
    src = {f: {} for f in mk}                # field -> team -> book
    for f, v in mk.items():
        for t in v: src[f][t] = 'DraftKings'
    try:
        nv = novig_futures(sport, ids)
    except Exception as e:
        print('novig futures failed:', e); nv = []
    for f, desc, n, v in nv:
        if len(v) >= 0.8 * n:
            mk.setdefault(f, {}).update(v); src.setdefault(f, {}).update(dict.fromkeys(v, 'Novig'))
    book = {f: ' / '.join(sorted(set(v.values()))) for f, v in src.items() if v}
    rows = []
    for t in d['power']:
        r = {'t': t['t'], 'rec': t['rec'], 'xW': t['wins']}
        for f in OURS[sport].values():
            r[f] = t.get(f)
            r[f + 'Dk'] = round(mk[f][t['t']], 3) if f in mk and t['t'] in mk[f] else None
        rows.append(r)
    out = {'sport': sport, 'season': season, 'asof': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'modelAsof': d['asof'],
           'book': ' / '.join(sorted({b for v in book.values() for b in v.split(' / ')})) or 'DraftKings via ESPN', 'books': book, 'markets': list(OURS[sport].values()), 'rows': rows}
    with open(os.path.join(ROOT, 'data', f'futures_board_{sport}.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print(sport, len(rows), 'teams', {f: len(v) for f, v in mk.items()})


def test():
    raw = {'a': implied(-150), 'b': implied(250), 'c': implied(600), 'd': implied(2000)}
    v, tot = devig(raw), sum(raw.values())
    assert abs(sum(v.values()) - 1) < 1e-9 and tot > 1
    # the favourite gives up less of its price than scaling takes, the longshot more; the order is kept
    assert v['a'] > raw['a'] / tot and v['d'] < raw['d'] / tot and v['a'] > v['b'] > v['c'] > v['d'] > 0
    fair = {'a': 0.5, 'b': 0.3, 'c': 0.2}
    assert all(abs(devig(fair)[t] - p) < 1e-9 for t, p in fair.items())           # no margin: unchanged
    assert devig({'a': 0.6}) == {'a': 1.0} and devig({}) == {}
    print('futures_board: ok')


if __name__ == '__main__':
    test() if sys.argv[1:] == ['--test'] else main()
