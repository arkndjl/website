#!/usr/bin/env python3
"""Injuries in the soccer game model: Transfermarkt injury and absence (suspension, other) spells for big-five players
(tmapi-alpha /player/<id>/injury and /player/<id>/absence, start and end dates back to the 2000s), each player's
usual league minutes from Understat line-ups, and avz on each match row (soccer_games.add_inj).

    python3 scripts/soccer_tm_injuries.py [min_minutes]     # pull every linked player with min_minutes+ in a season

Players: Understat id -> Transfermarkt id from scripts/data/soccer_mv_link.json.gz (the dump, to Jul 2026), plus this
season's newcomers name-matched live against their club's Transfermarkt squad (scripts/names.py; cached in
scripts/.cache/soccer/tm_live_link.json). Spells cached per player in scripts/.cache/soccer/tminj (the full set for
--fit: /mnt/project-files/soccer/tminj_cache.tgz).

The term (Oct 28 2026, scripts/soccer_tminj_research.py): a player out on match day (a spell that began before it in
the last FRESH days and ends after it, or is open; a suspension only in its own competition) costs his prior-season
GAR a 90 (static/data/soccer-war/<S-1>.json, V0 when he has none) x his usual league minutes (mean over the club's
last 10 league matches he wasn't out for, 3+ of them) / 90. Older spells are left to the ratings: the market ratings
from earlier closes have priced them (every spell, any age: tune t -2.7, held out t -0.7; fresh: tune t -2.1, held
out t -0.9, big five t -1.7). The end date of a past spell is known only afterwards, so the history stands for pre-match
team news (the live run reads Transfermarkt's current list and expected return)."""
import bisect
import datetime as dt
import gzip
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM
import soccer_data as D

TMAPI = 'https://tmapi-alpha.transfermarkt.technology'
LINK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'soccer_mv_link.json.gz')
ROWS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'soccer_player_rows.json.gz')
CDIR = os.path.join(D.CACHE, 'tminj')
LIVE_LINK = os.path.join(D.CACHE, 'tm_live_link.json')
WARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'data', 'soccer-war')
FRESH, LAST_N, HEALTHY, STALE, V0 = 21, 10, 3, 30, 0.05
BUDGET = 480              # seconds of Understat and Transfermarkt calls a live run may spend (the rest wait for the next run)
TMC = {'eng.1': 'GB1', 'esp.1': 'ES1', 'ger.1': 'L1', 'ita.1': 'IT1', 'fra.1': 'FR1', 'uefa.champions': 'CL',
       'uefa.europa': 'EL', 'uefa.europa.conf': 'UCOL'}


def spells(tm, refetch=False, max_age=None):
    """[(start, end, kind, missed games)] for Transfermarkt player tm; kind 'inj' or 'abs' (end None = open),
    missed games, the injury or absence name, the competition a suspension applies to ('' = all)"""
    p = os.path.join(CDIR, f'{tm}.json.gz')
    if os.path.exists(p) and not refetch and (max_age is None or time.time() - os.path.getmtime(p) < max_age):
        return D.load(p)
    out = []
    for kind, path, key in (('inj', 'injury', 'injuries'), ('abs', 'absence', 'absences')):
        d = D.get(f'{TMAPI}/player/{tm}/{path}', tries=3, headers={'Accept': 'application/json'})
        if not d or not d.get('success'):
            if os.path.exists(p):
                return D.load(p)
            return None
        for x in (d.get('data') or {}).get(key) or []:
            if x.get('start'):
                out.append([x['start'], x.get('end'), kind, x.get('missedGamesCount'),
                            x.get('name') or x.get('absenceId'), x.get('competitionId') or ''])
    D.save(p, out)
    return out


def tm_json(path, cache=None, max_age=None):
    if cache and os.path.exists(cache) and (max_age is None or time.time() - os.path.getmtime(cache) < max_age):
        return json.load(open(cache))
    d = D.get(f'{TMAPI}/{path}', tries=2, headers={'Accept': 'application/json'})
    d = (d or {}).get('data') if (d or {}).get('success') else None
    if d is not None and cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump(d, open(cache, 'w'))
    return d


def live_link(clubs, link, deadline=None):
    """this season's Understat players at clubs {Transfermarkt club id: [(Understat id, name)]} that the dump link
    lacks, name-matched to the club's current Transfermarkt squad -> {Understat id: Transfermarkt id}"""
    try:
        got = json.load(open(LIVE_LINK))
    except (OSError, ValueError):
        got = {}
    taken = set(link.values())
    for tmc, ps in clubs.items():
        need = [(u, n) for u, n in ps if u not in link and u not in got]
        if not need or (deadline and time.time() > deadline):
            continue
        sq = tm_json(f'club/{tmc}/squad', os.path.join(D.CACHE, 'tm_club', f'{tmc}_squad.json'), 3 * 86400) or {}
        cands = []
        for x in sq.get('squad') or []:
            if deadline and time.time() > deadline:
                break
            i = str(x.get('playerId'))
            if int(i) in taken or i in taken:
                continue
            pl = tm_json(f'player/{i}', os.path.join(D.CACHE, 'tm_player', f'{i}.json'))
            if pl and pl.get('name'):
                cands.append({'id': int(i), 'name': pl['name']})
        M = NM.Matcher(cands, name='name', team=None, pos=None)
        for u, n in need:
            row, _ = M.find(n, cross_team='variant')
            if row is not None:
                got[u] = row['id']
    json.dump(got, open(LIVE_LINK, 'w'))
    return got


def value_table():
    gv = {}

    def v(S, p):
        if S not in gv:
            try:
                gv[S] = {x['p']: x['gar90'] for x in json.load(open(os.path.join(WARD, f'{S}.json')))['players']}
            except (OSError, KeyError, ValueError):
                gv[S] = {}
        return gv[S].get(p, V0)
    return v


def out_on(sp, day, comp=None):
    """spells covering day; a suspension counts only in its own competition (comp: the match's Transfermarkt id)"""
    return [s for s in sp if s[0] < day and (s[1] is None or s[1] > day)
            and (s[2] == 'inj' or not s[5] or comp is None or s[5] == comp)]


def add_avz(rows, live=False, until=None, e2t=None):
    """avz on each scored row (lg in TMC): half the away-minus-home goals of value out injured or suspended (fresh
    spells). live: fetch this season's line-ups, link newcomers, refresh the spells of players who count for clubs
    playing by until (yyyy-mm-dd; later fixtures get 0)"""
    link = dict(D.load(LINK)['p'])
    seq = defaultdict(list)                          # club -> [(day, {Understat id: minutes}, comp)]
    nm = {}
    deadline = time.time() + BUDGET
    played = [r for r in rows if r.get('us') and r.get('hs') is not None]
    if live:
        # only the line-ups the next matches need (the last LAST_N of each club), fetched within the budget
        since = (dt.date.today() - dt.timedelta(days=150)).isoformat()
        played = [r for r in played if r['day'] >= since]

        def fetch(r):
            if time.time() < deadline:
                D.us_match(r['us'])
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(fetch, played))
    for r in sorted(played, key=lambda r: r['day']):
        p = os.path.join(D.CACHE, 'usm', str(r['us'])[-2:], f"{r['us']}.json.gz")
        m = D.us_match(r['us']) if os.path.exists(p) else None
        if not m:
            continue
        for s, t in (('h', r['h']), ('a', r['a'])):
            seq[t].append((r['day'], {str(x['player_id']): int(x['time'] or 0) for x in m['ro'][s]}, TMC[r['lg']]))
            for x in m['ro'][s]:
                nm[str(x['player_id'])] = x.get('player') or ''
    days = {t: [x[0] for x in L] for t, L in seq.items()}
    todo = [r for r in rows if r['lg'] in TMC and (not until or r['day'] <= until) and (not live or r.get('hs') is None)]

    def window(t, day):
        L = seq.get(t)
        if not L:
            return None
        i = bisect.bisect_left(days[t], day) - 1
        if i < HEALTHY or (dt.date.fromisoformat(day) - dt.date.fromisoformat(L[i][0])).days > STALE:
            return None
        return L[max(0, i - LAST_N + 1):i + 1]
    if live:
        clubs = defaultdict(set)
        for r in todo:
            for t in (r['h'], r['a']):
                w = window(t, r['day'])
                if w and (e2t or {}).get(t):
                    clubs[e2t[t]] |= {(p, nm.get(p, '')) for x in w for p in x[1]}
        link.update(live_link({k: sorted(v) for k, v in clubs.items()}, link, deadline))
        need = sorted({link[p] for ps in clubs.values() for p, _ in ps if p in link})

        def one(i):
            if time.time() < deadline:
                spells(i, max_age=18 * 3600)
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(one, need))
        print('injuries: refreshed', len(need), 'players at', len(clubs), 'clubs', flush=True)
    sp = {}

    def spl(p):
        if p not in sp:
            f = os.path.join(CDIR, f'{link[p]}.json.gz') if p in link else None
            sp[p] = (D.load(f) or []) if f and os.path.exists(f) else []
        return sp[p]
    v = value_table()

    def deficit(t, day, comp):
        w = window(t, day)
        if not w:
            return 0.0
        S = D.season_of(day)
        cut = (dt.date.fromisoformat(day) - dt.timedelta(days=FRESH)).isoformat()
        tot = 0.0
        for p in set().union(*[x[1] for x in w]):
            o = out_on(spl(p), day, comp)
            if not o or not any(s[0] >= cut for s in o):
                continue
            ms = [x[1].get(p, 0) for x in w if not out_on(spl(p), x[0], x[2])]
            if len(ms) >= HEALTHY:
                tot += v(S - 1, p) * (sum(ms) / len(ms)) / 90
        return tot
    for r in todo:
        c = TMC[r['lg']]
        r['avz'] = round((deficit(r['a'], r['day'], c) - deficit(r['h'], r['day'], c)) / 2, 4)
    return rows


def linked(min_min=300):
    link = D.load(LINK)['p']
    rows = D.load(ROWS)
    return sorted({link[r['p']] for r in rows if r['min'] >= min_min and r['p'] in link})


if __name__ == '__main__':
    ids = linked(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
    todo = [i for i in ids if not os.path.exists(os.path.join(CDIR, f'{i}.json.gz'))]
    print(len(ids), 'players,', len(todo), 'to fetch', flush=True)
    n = [0, 0]

    def one(i):
        s = spells(i)
        n[0] += 1
        n[1] += s is None
        if n[0] % 250 == 0:
            print(n[0], 'done,', n[1], 'failed', flush=True)
        time.sleep(0.2)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, todo))
    print('done', n, flush=True)
