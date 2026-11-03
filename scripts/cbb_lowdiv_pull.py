#!/usr/bin/env python3
"""NCAA Division II and III men's basketball box scores (ncaa.com, through the public ncaa-api.henrygd.me proxy), one
compact player line per game, for the CBB board's non-D-I players (scripts/cbb_lowdiv.py).

    python3 scripts/cbb_lowdiv_pull.py 2024 2025 2026 [d2|d3]   # seasons by end year (2024 = 2023-24)
    python3 scripts/cbb_lowdiv_pull.py --recent              # this season, the last 10 days (the daily job)

Player stats start with 2023-24 (earlier box scores carry team totals only). Writes scripts/data/cbb_lowdiv/
{div}-{season}.json.gz: {game id: [date, [team id, team, opp id, opp, pts, opp pts, home], [players...]]}.
The proxy allows 5 requests a second; this stays under 4.
"""
import concurrent.futures as cf
import datetime as dt
import gzip
import json
import os
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'scripts', 'data', 'cbb_lowdiv')
API = 'https://ncaa-api.henrygd.me'
UA = 'arkndjl-board/1.0'
DIVS = ('d2', 'd3')
STATS = ['minutesPlayed', 'fieldGoalsMade', 'fieldGoalsAttempted', 'threePointsMade', 'threePointsAttempted', 'freeThrowsMade',
         'freeThrowsAttempted', 'offensiveRebounds', 'totalRebounds', 'assists', 'turnovers', 'personalFouls', 'steals',
         'blockedShots', 'points']
os.makedirs(OUT, exist_ok=True)
_lock = threading.Lock(); _last = [0.0]


def get(path, tries=5):
    for i in range(tries):
        with _lock:                       # one request every 0.24 s across the threads
            w = _last[0] + 0.24 - time.time()
            if w > 0: time.sleep(w)
            _last[0] = time.time()
        try:
            req = urllib.request.Request(API + path, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            if e.code == 502 and i >= 2: return None      # no box score for this game
            time.sleep(2 + 3 * i)
        except Exception:
            time.sleep(2 + 3 * i)
    return None


def num(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0


def box(gid):
    d = get(f'/game/{gid}/boxscore')
    if not d or not d.get('teamBoxscore'): return None
    teams = {str(t['teamId']): t for t in d.get('teams', [])}
    tb = d['teamBoxscore']
    if len(tb) != 2 or not any(t['playerStats'] for t in tb): return None
    out = []
    for i, t in enumerate(tb):
        me, op = teams.get(str(t['teamId']), {}), teams.get(str(tb[1 - i]['teamId']), {})
        for p in t['playerStats']:
            nm = f"{(p.get('firstName') or '').strip()} {(p.get('lastName') or '').strip()}".strip()
            if not nm or nm.lower() in ('team', 'tm team'): continue
            out.append([str(t['teamId']), nm, p.get('position') or '', (p.get('year') or '')[:2], 1 if p.get('starter') else 0]
                       + [round(num(p.get(k)), 1) for k in STATS])
    tm = [[str(x['teamId']), teams.get(str(x['teamId']), {}).get('nameShort', ''), num(x['teamStats'].get('points')),
           1 if teams.get(str(x['teamId']), {}).get('isHome') else 0,
           {k: num(x['teamStats'].get(k)) for k in ('fieldGoalsAttempted', 'freeThrowsAttempted', 'offensiveRebounds', 'turnovers')}] for x in tb]
    return {'div': d.get('divisionName'), 'teams': tm, 'players': out}


def season_dates(s, until=None):
    a, b = dt.date(s - 1, 10, 25), min(dt.date(s, 3, 31), until or dt.date(s, 3, 31))
    while a <= b:
        yield a; a += dt.timedelta(days=1)


def pull(s, div, dates):
    path = os.path.join(OUT, f'{div}-{s}.json.gz')
    have = json.load(gzip.open(path, 'rt')) if os.path.exists(path) else {}
    ids = {}
    with cf.ThreadPoolExecutor(12) as ex:
        for d, sb in zip(dates, ex.map(lambda d: get(f'/scoreboard/basketball-men/{div}/{d:%Y/%m/%d}'), dates)):
            for g in (sb or {}).get('games', []):
                g = g['game']
                if g.get('gameState') == 'final' and g['gameID'] not in have: ids[g['gameID']] = d.isoformat()
    print(f'{div} {s}: {len(have)} cached, {len(ids)} new games', flush=True)
    todo = sorted(ids); n = 0
    with cf.ThreadPoolExecutor(12) as ex:
        for gid, b in zip(todo, ex.map(box, todo)):
            if b: have[gid] = [ids[gid], b['teams'], b['players']]
            n += 1
            if n % 300 == 0:
                print(f'  {div} {s}: {n}/{len(todo)}', flush=True)
                json.dump(have, gzip.open(path, 'wt'), separators=(',', ':'))
    json.dump(have, gzip.open(path, 'wt'), separators=(',', ':'))
    print(f'{div} {s}: {len(have)} games with box scores', flush=True)


if __name__ == '__main__':
    today = dt.date.today()
    if '--recent' in sys.argv:
        s = today.year + (1 if today.month >= 7 else 0)
        dates = [today - dt.timedelta(days=i) for i in range(10, -1, -1) if dt.date(s - 1, 10, 25) <= today - dt.timedelta(days=i) <= dt.date(s, 3, 31)]
        for div in DIVS:
            if dates: pull(s, div, dates)
    else:
        divs = [a for a in sys.argv[1:] if a in DIVS] or DIVS
        for div in divs:
            for s in [int(a) for a in sys.argv[1:] if a.isdigit()]:
                pull(s, div, list(season_dates(s, today)))
