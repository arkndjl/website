#!/usr/bin/env python3
"""CHL game summaries (HockeyTech's public gc feed, OHL/WHL/QMJHL) -> per-player scoring splits a season, for the
hockey FV driver search (Oct 26 2026): goals, primary and secondary assists, even-strength splits, and on-ice
even-strength goals for and against (the feed lists the skaters on the ice for every goal).
    python3 scripts/hockey_chl_games.py [first end-year] [last end-year]   # default 2008 2019
Summaries are slimmed to scripts/.cache/hockey/gs/<league>_<game>.json; the splits go to
scripts/.cache/hockey/chl_splits.json as {"<league>_<end year>": {player_id: {...}}}.
"""
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
C = os.path.join(HERE, '.cache', 'hockey')
GS = os.path.join(C, 'gs')
KEY = {'ohl': 'f1aa699db3d81487', 'whl': '41b145a848f4bd67', 'lhjmq': 'f322673b6bcae299'}
MK = 'https://lscluster.hockeytech.com/feed/?feed=modulekit&fmt=json&lang=en&key=%s&client_code=%s'
GC = 'https://lscluster.hockeytech.com/feed/?feed=gc&tab=gamesummary&game_id=%s&key=%s&client_code=%s&fmt=json&lang_code=en'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'


def get(u):
    for _ in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=60).read())
        except Exception:
            pass
    return None


def seasons(c, a, b):
    out = []
    for s in (get(MK % (KEY[c], c) + '&view=seasons') or {}).get('SiteKit', {}).get('Seasons') or []:
        m = re.match(r'(\d{4}) ?- ?(\d{2,4}) \|? ?Regular Season$', s['season_name'].strip())
        if m and a <= int(m.group(1)) + 1 <= b:
            out.append((s['season_id'], int(m.group(1)) + 1))
    return out


def slim(g):
    s = g['GC']['Gamesummary']
    pid = lambda p: (p or {}).get('player_id')
    goals = [{'t': x.get('team_id'), 'g': pid(x.get('goal_scorer')), 'a1': pid(x.get('assist1_player')), 'a2': pid(x.get('assist2_player')),
              'pp': x.get('power_play') == '1', 'sh': x.get('short_handed') == '1', 'en': x.get('empty_net') == '1',
              'on': [p.get('player_id') for p in x.get('plus') or []], 'off': [p.get('player_id') for p in x.get('minus') or []]}
             for x in s.get('goals') or []]
    return {'h': (s.get('home') or {}).get('id'), 'v': (s.get('visitor') or {}).get('id'), 'goals': goals}


def main():
    a, b = (int(x) for x in sys.argv[1:3]) if len(sys.argv) > 2 else (2008, 2019)
    os.makedirs(GS, exist_ok=True)
    jobs = []
    for c in KEY:
        for sid, yr in seasons(c, a, b):
            for g in (get(MK % (KEY[c], c) + f'&view=schedule&season_id={sid}') or {}).get('SiteKit', {}).get('Schedule') or []:
                jobs.append((c, yr, g.get('game_id') or g.get('id')))
    print(len(jobs), 'games', flush=True)

    def one(j):
        c, yr, gid = j
        fn = os.path.join(GS, f'{c}_{gid}.json')
        if not os.path.exists(fn):
            g = get(GC % (gid, KEY[c], c))
            if not g or 'GC' not in g:
                return None
            json.dump(slim(g), open(fn, 'w'), separators=(',', ':'))
        return j
    with ThreadPoolExecutor(16) as ex:
        done = [j for j in ex.map(one, jobs) if j]
    # splits: per league-season and player id
    S = {}
    for c, yr, gid in done:
        d = json.load(open(os.path.join(GS, f'{c}_{gid}.json')))
        T = S.setdefault(f'{c}_{yr}', {})
        team = S.setdefault(f'{c}_{yr}|team', {})
        for x in d['goals']:
            es = not x['pp'] and not x['sh'] and not x['en']
            tt = team.setdefault(x['t'], {'gf': 0, 'esgf': 0})
            tt['gf'] += 1; tt['esgf'] += es
            for k in ('g', 'a1', 'a2'):
                if x[k]:
                    p = T.setdefault(x[k], {})
                    p[k] = p.get(k, 0) + 1
                    if es:
                        p['es' + k] = p.get('es' + k, 0) + 1
            if es:
                for i in x['on']:
                    p = T.setdefault(i, {}); p['esgfOn'] = p.get('esgfOn', 0) + 1; p['team'] = x['t']
                for i in x['off']:
                    p = T.setdefault(i, {}); p['esgaOn'] = p.get('esgaOn', 0) + 1
    json.dump(S, open(os.path.join(C, 'chl_splits.json'), 'w'))
    print(len(done), 'summaries;', len(S), 'tables')


if __name__ == '__main__':
    main()
