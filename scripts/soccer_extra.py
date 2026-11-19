#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Display tables on the SOCCER ARKBOARD that come straight from a public source (no model of ours): data/soccer_extra.json,
one table spec per key, drawn by layouts/shortcodes/soccerextra.html.

    python3 scripts/soccer_extra.py mls                 # MLS players + keepers: American Soccer Analysis goals added (g+),
                                                        # xG, MLSPA pay (app.americansocceranalysis.com/api/v1/mls)
    python3 scripts/soccer_extra.py speed               # top speed and distance: UEFA competition stats (compstats.uefa.com)
    python3 scripts/soccer_extra.py scorers             # national-team scorers (martj42 goalscorers.csv)
    python3 scripts/soccer_extra.py managers <file>     # manager results above the game model's expectation, from
                                                        # scripts/research/sweep_nov19/soccer/club_tests.py l11 held table

One call a second to each host. A failed pull keeps the table already in the file.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_extra.json')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
ASA = 'https://app.americansocceranalysis.com/api/v1/mls'
UEFA = ('https://compstats.uefa.com/v1/player-ranking?competitionId={c}&seasonYear={y}&phase=TOURNAMENT'
        '&stats=top_speed,distance_covered,minutes_played_official&optionalFields=PLAYER,TEAM&limit=200&offset={o}&order=DESC')
GA = {'Dribbling': 'dri', 'Fouling': 'fou', 'Interrupting': 'int', 'Passing': 'pas', 'Receiving': 'rec', 'Shooting': 'sho'}


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    err = None
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            time.sleep(1.1)
            return d
        except Exception as e:
            err = e
            time.sleep(3 + 3 * i)
    print('soccer extra: failed', url, repr(err), file=sys.stderr)
    return None


def save(key, spec):
    try:
        J = json.load(open(OUT))
    except (OSError, ValueError):
        J = {}
    J[key] = spec
    json.dump(J, open(OUT, 'w'), separators=(',', ':'), allow_nan=False, ensure_ascii=False)
    print(key, len(spec['rows']), 'rows', flush=True)


def stamp():
    return dt.date.today().strftime('%b %-d').lower()


def one(v):
    return v if isinstance(v, str) else (v[-1] if v else None)


def mls():
    y = dt.date.today().year
    ga = None
    for S in (y, y - 1):
        ga = get(f'{ASA}/players/goals-added?season_name={S}&minimum_minutes=0')
        if ga:
            break
    xg = get(f'{ASA}/players/xgoals?season_name={S}')
    gk = get(f'{ASA}/goalkeepers/xgoals?season_name={S}')
    gkg = get(f'{ASA}/goalkeepers/goals-added?season_name={S}')
    sal = get(f'{ASA}/players/salaries?season_name={S}')
    pl, tm = get(f'{ASA}/players'), get(f'{ASA}/teams')
    if not (ga and xg and gk and pl and tm):
        return
    name = {p['player_id']: p.get('player_name') for p in pl}
    team = {t['team_id']: t.get('team_short_name') or t.get('team_name') for t in tm}
    pay = {}
    for s in sorted(sal or [], key=lambda s: s.get('mlspa_release') or ''):
        if s.get('guaranteed_compensation'):
            pay[s['player_id']] = round(s['guaranteed_compensation'] / 1e6, 2)
    X = {x['player_id']: x for x in xg}
    rows = []
    for x in ga:
        mn = x.get('minutes_played') or 0
        if mn < 450 or x.get('general_position') == 'GK' or not name.get(x['player_id']):
            continue
        a = {GA[d['action_type']]: d['goals_added_above_avg'] or 0.0 for d in x['data'] if d['action_type'] in GA}
        q = X.get(x['player_id']) or {}
        tot = sum(a.values())
        rows.append([name[x['player_id']], team.get(one(x['team_id'])), x.get('general_position'), mn, round(tot, 2),
                     round(tot / mn * 96, 3)] + [round(a.get(k, 0.0), 2) for k in ('pas', 'rec', 'dri', 'int', 'sho', 'fou')] +
                    [q.get('goals'), q.get('primary_assists'), round(q['xgoals'], 1) if q.get('xgoals') is not None else None,
                     round(q['xassists'], 1) if q.get('xassists') is not None else None, pay.get(x['player_id'])])
    rows.sort(key=lambda r: -r[4])
    cols = [['Player', 's', ''], ['Club', 's', ''], ['Pos', 's', "ASA's general position"], ['Min', 'd', 'minutes'],
            ['g+', '2', "goals added above the average player at his position, all actions (American Soccer Analysis)"],
            ['g+/96', '3', 'goals added above average per 96 minutes'], ['Pass', '2', 'g+ above average: passing'],
            ['Recv', '2', 'g+ above average: receiving'], ['Drib', '2', 'g+ above average: dribbling'],
            ['Int', '2', 'g+ above average: interrupting (tackles, interceptions, blocks, clearances)'],
            ['Shot', '2', 'g+ above average: shooting'], ['Foul', '2', 'g+ above average: fouls won and given'],
            ['G', 'd', 'goals'], ['A', 'd', 'primary assists'], ['xG', '1', 'expected goals'], ['xA', '1', 'expected assists'],
            ['Pay $m', '2', "guaranteed compensation, latest MLS Players Association release"]]
    save('mls', {'title': f'MLS players :: goals added {S}', 'cols': cols, 'rows': rows, 'filter': 'Club,Pos',
                 'note': f'American Soccer Analysis · MLSPA · {S} season · {stamp()}',
                 'about': "American Soccer Analysis's goals added (g+), outfield players with 450+ minutes. ASA's metric as published, not an ARKBOARD model."})
    G = {x['player_id']: x for x in gkg or []}
    rows = []
    for x in gk:
        mn = x.get('minutes_played') or 0
        if mn < 450 or not name.get(x['player_id']):
            continue
        g = {d['action_type']: d['goals_added_above_avg'] or 0.0 for d in (G.get(x['player_id']) or {}).get('data') or []}
        rows.append([name[x['player_id']], team.get(one(x['team_id'])), mn, x.get('shots_faced'), x.get('saves'), x.get('goals_conceded'),
                     round(x['xgoals_gk_faced'], 1) if x.get('xgoals_gk_faced') is not None else None,
                     round(-(x.get('goals_minus_xgoals_gk') or 0.0), 2), round(-(x.get('goals_minus_xgoals_gk') or 0.0) / mn * 96, 3),
                     round(sum(g.values()), 2) if g else None, round(g['Shotstopping'], 2) if 'Shotstopping' in g else None,
                     pay.get(x['player_id'])])
    rows.sort(key=lambda r: -r[7])
    cols = [['Keeper', 's', ''], ['Club', 's', ''], ['Min', 'd', 'minutes'], ['Shots', 'd', 'shots on target faced'], ['Saves', 'd', ''],
            ['GA', 'd', 'goals conceded'], ['PSxG', '1', 'post-shot expected goals faced (American Soccer Analysis)'],
            ['Saved', '+2', 'goals prevented: post-shot xG faced minus goals conceded'], ['/96', '+3', 'goals prevented per 96 minutes'],
            ['g+', '2', 'goals added above the average keeper, all actions'], ['Stop', '2', 'g+ above average: shot stopping'],
            ['Pay $m', '2', 'guaranteed compensation, latest MLS Players Association release']]
    save('mlsgk', {'title': f'MLS keepers :: goals prevented {S}', 'cols': cols, 'rows': rows, 'filter': 'Club',
                   'note': f'American Soccer Analysis · MLSPA · {S} season · {stamp()}',
                   'about': "Keepers with 450+ minutes. American Soccer Analysis's numbers as published, not an ARKBOARD model."})


def speed():
    t = dt.date.today()
    y = t.year + 1 if t.month >= 8 else t.year
    best = {}
    for c, lab in ((1, 'UCL'), (14, 'UEL')):
        o = 0
        while o < 3000:
            d = get(UEFA.format(c=c, y=y, o=o))
            if not d:
                break
            for x in d:
                p, tm = x.get('player') or {}, x.get('team') or {}
                st = {s.get('name'): s.get('value') for s in x.get('statistics') or []}
                try:
                    sp, mn = float(st['top_speed']), float(st['minutes_played_official'])
                    km = float(st.get('distance_covered') or 0)
                except (KeyError, TypeError, ValueError):
                    continue
                if mn < 90 or sp < 20 or not p.get('internationalName'):
                    continue
                k = p.get('id')
                if k not in best or sp > best[k][6]:
                    best[k] = [p['internationalName'], tm.get('internationalName'), p.get('countryCode'),
                               (p.get('fieldPosition') or '')[:3].title(), lab, int(mn), sp, round(km / mn * 90, 1) if km else None]
            if len(d) < 200:
                break
            o += 200
    rows = sorted(best.values(), key=lambda r: -r[6])[:400]
    if len(rows) < 50:
        return
    cols = [['Player', 's', ''], ['Club', 's', ''], ['Nat', 's', ''], ['Pos', 's', ''], ['Comp', 's', 'Champions League or Europa League'],
            ['Min', 'd', 'minutes in the competition'], ['Top km/h', '1', "the season's top speed in the competition (UEFA tracking)"],
            ['km/90', '1', 'distance covered per 90 minutes']]
    save('speed', {'title': f'top speed :: UEFA competitions {y - 1}-{str(y)[2:]}', 'cols': cols, 'rows': rows, 'filter': 'Pos,Comp,Nat',
                   'note': f'UEFA · {stamp()}', 'about': 'UEFA competition tracking stats as published, players with 90+ minutes, fastest 400. A season top speed rises with minutes played.'})


def managers(fn):
    import gzip
    tb = json.load(open(fn))
    names = json.load(gzip.open(os.path.join(HERE, 'data', 'soccer_teams.json.gz'), 'rt'))
    sys.path.insert(0, HERE)
    import soccer_data as D
    rows = [[m['n'], (names.get(str(m['club'])) or ['?'])[0], D.NAME.get(m['lg'], m['lg']), m['last'][:4], m['mp'], m['clubs'], m['raw'], m['eff']]
            for m in sorted(tb, key=lambda m: -m['eff']) if m['mp'] >= 100]
    cols = [['Manager', 's', ''], ['Last club', 's', 'the club of his latest league match on record'], ['League', 's', ''],
            ['Last', 's', 'year of that match'], ['MP', 'd', 'league matches on record, 2012-13 to 2025-26'], ['Clubs', 'd', ''],
            ['GD +/-', '+2', "goal difference a match above the game model's pre-match expectation"],
            ['Shrunk', '+2', 'the same with 40 matches of an average manager added']]
    save('managers', {'title': 'managers :: results above expectation', 'cols': cols, 'rows': rows, 'filter': 'League',
                      'note': 'Transfermarkt · 2012-13 to 2025-26',
                      'about': "League matches with a manager on record (Transfermarkt), 100+ matches. Expectation = the game model's goals before each match, which already holds the club's rating at the time, so this is results against expectation, not a forecast: as a model term it failed its test."})


def scorers():
    import csv
    import io
    b = urllib.request.urlopen(urllib.request.Request(
        'https://raw.githubusercontent.com/martj42/international_results/master/goalscorers.csv', headers={'User-Agent': UA}), timeout=90).read()
    acc = {}
    for r in csv.DictReader(io.StringIO(b.decode('utf-8'))):
        if not r.get('scorer') or r.get('own_goal', '').upper() == 'TRUE':
            continue
        e = acc.setdefault((r['scorer'], r['team']), [0, 0, set(), r['date'][:4], r['date'][:4]])
        e[0] += 1
        e[1] += r.get('penalty', '').upper() == 'TRUE'
        e[2].add((r['date'], r['home_team'], r['away_team']))
        e[3], e[4] = min(e[3], r['date'][:4]), max(e[4], r['date'][:4])
    rows = [[n, t, v[0], v[0] - v[1], v[1], len(v[2]), f'{v[3]}-{v[4][2:]}'] for (n, t), v in acc.items() if v[0] >= 10]
    rows.sort(key=lambda r: (-r[2], r[0]))
    if len(rows) < 50:
        return
    cols = [['Player', 's', ''], ['Nation', 's', ''], ['Goals', 'd', 'goals in competitive internationals on record'],
            ['Non-pen', 'd', 'goals without penalties'], ['Pens', 'd', 'penalties scored'], ['Scored in', 'd', 'matches with a goal'],
            ['Years', 's', 'first and last year with a goal on record']]
    save('scorers', {'title': 'national-team scorers :: competitive matches', 'cols': cols, 'rows': rows[:500], 'filter': 'Nation',
                     'note': f'martj42 international results · {stamp()}',
                     'about': 'Goals in World Cups, continental finals and their qualifiers with a scorer on record (martj42 goalscorers.csv); friendlies and many older matches are not in the file. Own goals left out. 10+ goals.'})


if __name__ == '__main__':
    for a in sys.argv[1:]:
        if a == 'mls':
            mls()
        elif a == 'speed':
            speed()
        elif a == 'scorers':
            scorers()
        elif a == 'managers':
            managers(sys.argv[sys.argv.index(a) + 1])
