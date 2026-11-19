# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research pulls, one call a second: Premier League site player season stats (every player, 2014-15 on) and UEFA
competition player rankings (top speed, distance, minutes; Champions League and Europa League).

    python3 scripts/research/sweep_nov19/soccer/pl_uefa_pull.py pl <out dir>
    python3 scripts/research/sweep_nov19/soccer/pl_uefa_pull.py uefa <out dir> [first seasonYear] [last seasonYear]
"""
import json
import os
import sys
import time
import urllib.request

UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
PL = 'https://sdp-prem-prod.premier-league-prod.pulselive.com/api/v2/competitions/8/seasons/{S}/players/stats/leaderboard'
UEFA = ('https://compstats.uefa.com/v1/player-ranking?competitionId={c}&seasonYear={y}&phase=TOURNAMENT'
        '&stats=top_speed,distance_covered,minutes_played_official,matches_appearance&optionalFields=PLAYER,TEAM'
        '&limit=200&offset={o}&order=DESC')
PL_KEEP = ('timePlayed', 'appearances', 'goalsConceded', 'expectedGoalsOnTargetConceded', 'savesMade', 'penaltyGoalsConceded',
           'penaltiesFaced', 'expectedGoals', 'expectedAssists', 'goals', 'goalAssists', 'ownGoalsConceded')


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(3 + 3 * i)
    print('fail', url, repr(err), flush=True)
    return None


def pl(out):
    for S in range(2014, 2026):                     # season start years; 2025 = 2025-26
        fn = os.path.join(out, f'pl_{S}.json')
        if os.path.exists(fn):
            continue
        rows, nxt = [], None
        for _ in range(12):
            u = PL.format(S=S) + '?_sort=time_played:desc&_limit=100' + (f'&_next={nxt}' if nxt else '')
            d = get(u)
            time.sleep(1.1)
            if not d or not d.get('data'):
                break
            for x in d['data']:
                m = x.get('playerMetadata') or {}
                rows.append({'id': m.get('id'), 'n': m.get('name'), 'pos': m.get('position'),
                             'st': {k: v for k, v in (x.get('stats') or {}).items() if k in PL_KEEP}})
            nxt = (d.get('pagination') or {}).get('_next')
            if not nxt:
                break
        json.dump(rows, open(fn, 'w'))
        print('pl', S, len(rows), flush=True)


def uefa(out, y0, y1):
    for c in (1, 14):
        for y in range(y0, y1 + 1):
            fn = os.path.join(out, f'uefa_{c}_{y}.json')
            if os.path.exists(fn):
                continue
            rows, o = [], 0
            while o < 3000:
                d = get(UEFA.format(c=c, y=y, o=o))
                time.sleep(1.1)
                if not d:
                    break
                for x in d:
                    p, t = x.get('player') or {}, x.get('team') or {}
                    st = {s.get('name'): s.get('value') for s in x.get('statistics') or []}
                    rows.append({'id': p.get('id'), 'n': p.get('internationalName'), 'dob': p.get('birthDate'),
                                 'pos': p.get('fieldPosition'), 'club': (t.get('internationalName') or t.get('id')),
                                 'cc': p.get('countryCode'), 'st': st})
                if len(d) < 200:
                    break
                o += 200
            json.dump(rows, open(fn, 'w'))
            print('uefa', c, y, len(rows), flush=True)


if __name__ == '__main__':
    os.makedirs(sys.argv[2], exist_ok=True)
    if sys.argv[1] == 'pl':
        pl(sys.argv[2])
    else:
        uefa(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2016, int(sys.argv[4]) if len(sys.argv) > 4 else 2026)
