#!/usr/bin/env python3
"""NHL box scores from ESPN (ESPN athlete ids, the ids its player props carry), for the NHL player props model
(scripts/nhl_props.py). Every final game from 2021-22 on, cached a game at a time in scripts/.cache/nhl_box/.

    python3 scripts/nhl_pbox.py            # pull what's missing -> scripts/.cache/nhl_box/<gid>.json

    {'k': start (UTC), 'S': season end year, 'po': playoffs, 'h': home, 'a': away, 'hs', 'as',
     'ou': ESPN's over/under, 'sp': home moneyline,
     'p': {team: [[id, name, pos, toi min, pp toi min, goals, assists, shots, blocks, hits], ...]},
     'gk': {team: [[id, name, toi min, shots against, saves], ...]}}
"""
import datetime
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache', 'nhl_box')
SITE = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl'
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'
FIRST = datetime.date(2021, 10, 1)
sys.path.insert(0, HERE)
import nhl_data as D  # noqa: E402


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


def mins(s):
    try:
        m, sec = str(s).split(':')
        return int(m) + int(sec) / 60
    except (ValueError, TypeError):
        return 0.0


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def season(d):
    return d.year + 1 if d.month >= 8 else d.year


def day(d):
    j = get(f'{SITE}/scoreboard?dates={d:%Y%m%d}&limit=50') or {}
    out = []
    for e in j.get('events', []):
        if not (e.get('status') or {}).get('type', {}).get('completed'):
            continue
        st = (e.get('season') or {}).get('type')
        if st not in (2, 3):
            continue
        out.append((e['id'], e['date'], st == 3))
    return out


def box(gid, k, po):
    fn = os.path.join(CACHE, f'{gid}.json')
    if os.path.exists(fn):
        return json.load(open(fn))
    j = get(f'{SITE}/summary?event={gid}')
    if not j or 'boxscore' not in j:
        return None
    try:
        comp = j['header']['competitions'][0]
        if not comp['status']['type']['completed']:
            return None
        side = {c['homeAway']: (D.team(c['team']['abbreviation']), int(c.get('score') or 0)) for c in comp['competitors']}
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    out = {'k': k, 'S': season(datetime.date.fromisoformat(k[:10])),
           'po': int(po), 'h': side['home'][0], 'a': side['away'][0], 'hs': side['home'][1], 'as': side['away'][1],
           'p': {}, 'gk': {}}
    pc = (j.get('pickcenter') or [{}])
    if pc:
        out['ou'] = pc[0].get('overUnder')
        out['ml'] = ((pc[0].get('homeTeamOdds') or {}).get('moneyLine'), (pc[0].get('awayTeamOdds') or {}).get('moneyLine'))
    for t in j['boxscore'].get('players', []):
        ab = D.team(t['team']['abbreviation'])
        sk, gk = [], []
        for st in t.get('statistics', []):
            keys = st.get('keys') or []
            for p in st.get('athletes', []):
                d = dict(zip(keys, p.get('stats', [])))
                a = p.get('athlete', {})
                toi = mins(d.get('timeOnIce'))
                if not toi:
                    continue
                pos = (a.get('position') or {}).get('abbreviation')
                if st.get('name') == 'goalies':
                    gk.append([a.get('id'), a.get('displayName'), round(toi, 2), num(d.get('shotsAgainst')), num(d.get('saves'))])
                else:
                    sk.append([a.get('id'), a.get('displayName'), 'D' if pos == 'D' else 'F', round(toi, 2),
                               round(mins(d.get('powerPlayTimeOnIce')), 2), num(d.get('goals')), num(d.get('assists')),
                               num(d.get('shotsTotal')), num(d.get('blockedShots')), num(d.get('hits'))])
        out['p'][ab], out['gk'][ab] = sk, gk
    if len(out['p']) != 2:
        return None
    with open(fn, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    return out


def pull(since=FIRST, until=None):
    os.makedirs(CACHE, exist_ok=True)
    until = until or datetime.date.today()
    days, d = [], since
    while d <= until:
        if d.month not in (7, 8, 9):
            days.append(d)
        d += datetime.timedelta(days=1)
    with ThreadPoolExecutor(8) as ex:
        evs = [x for xs in ex.map(day, days) for x in xs]
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda e: box(*e), evs))
    print(len(evs), 'games,', sum(1 for g in got if g), 'boxes', flush=True)
    return {e[0]: g for e, g in zip(evs, got) if g}


def load():
    out = {}
    for fn in os.listdir(CACHE):
        if fn.endswith('.json'):
            out[fn[:-5]] = json.load(open(os.path.join(CACHE, fn)))
    return out


if __name__ == '__main__':
    pull()
