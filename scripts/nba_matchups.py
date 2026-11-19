#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Defensive matchups for the NBA ARKBOARD (data/nba_matchups.json): who each defender guarded and what they scored.

    python3 scripts/nba_matchups.py [SEASON]      # end year, default the latest file in shufinskiy/nba_data

Source: github.com/shufinskiy/nba_data (Apache-2.0) matchups_<Y>.tar.xz, one row per game x offensive player x
defender (partial possessions, points), mirrored from NBA.com's box score matchups; history only, about once a year.
Per defender (1,000+ partial possessions):
    MD     matchup difficulty: the points per 100 matchup possessions his assignments scored against everyone that
           season, weighted by the possessions he guarded them (who he was asked to guard)
    Allowed  points per 100 partial possessions his assignments scored against him
    PAOE   Allowed - MD (points allowed over expected), shrunk toward 0 by poss / (poss + 300)
Display only: as a team-defence input PAOE failed (scripts/research/sweep_nov19/nba/def_test.py, prior season,
held t +0.13). Stdlib only."""
import csv, io, json, lzma, os, sys, tarfile, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'nba_matchups.json')
URL = 'https://raw.githubusercontent.com/shufinskiy/nba_data/main/datasets/matchups_{y}.tar.xz'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
MIN_POSS, K = 1000.0, 300.0
# NBA.com tricode -> the board's logo file (static/img/nba/<code>.png)
TEAM = {'GSW': 'gs', 'NOP': 'no', 'NYK': 'ny', 'SAS': 'sa', 'UTA': 'utah', 'WAS': 'wsh', 'PHX': 'phx', 'BKN': 'bkn', 'CHA': 'cha'}


def rows(y):
    """the season's CSV rows (file year y = season y-1..y, end year y + 1)"""
    raw = urllib.request.urlopen(urllib.request.Request(URL.format(y=y), headers={'User-Agent': UA}), timeout=300).read()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as t:
        m = next(x for x in t.getmembers() if x.name.endswith('.csv'))
        yield from csv.DictReader(io.TextIOWrapper(t.extractfile(m), encoding='utf-8'))


def build(season):
    tri, games = {}, {}
    off = defaultdict(lambda: [0.0, 0.0])                       # offensive player -> [points, poss]
    raw = []
    for r in rows(season - 1):
        n = float(r['partial_possessions'] or 0)
        if n <= 0: continue
        tri[r['team_id']] = r['team_tricode']
        games[r['game_id']] = (r['home_team_id'], r['away_team_id'])
        pts = float(r['player_points'] or 0)
        o = off[r['person_id']]; o[0] += pts; o[1] += n
        dteam = r['home_team_id'] if r['team_id'] == r['away_team_id'] else r['away_team_id']
        raw.append((r['matchups_person_id'], f"{r['matchups_first_name']} {r['matchups_family_name']}".strip(), dteam, r['person_id'], n, pts))
    lg = sum(v[0] for v in off.values()) / sum(v[1] for v in off.values())
    rate = {p: (v[0] + lg * 100) / (v[1] + 100) for p, v in off.items()}
    d = defaultdict(lambda: {'n': None, 'tm': defaultdict(float), 'poss': 0.0, 'pts': 0.0, 'exp': 0.0})
    for pid, nm, tm, op, n, pts in raw:
        x = d[pid]; x['n'] = nm; x['tm'][tm] += n; x['poss'] += n; x['pts'] += pts; x['exp'] += n * rate[op]
    out = []
    for pid, x in d.items():
        if x['poss'] < MIN_POSS: continue
        t = tri.get(max(x['tm'], key=x['tm'].get), '')
        md, al = 100 * x['exp'] / x['poss'], 100 * x['pts'] / x['poss']
        out.append({'id': pid, 'n': x['n'], 'tm': TEAM.get(t, t.lower()), 'ab': t, 'poss': round(x['poss']), 'md': round(md, 1), 'al': round(al, 1),
                    'paoe': round((al - md) * x['poss'] / (x['poss'] + K), 1)})
    out.sort(key=lambda r: -r['md'])
    return {'season': f'{season - 1}-{str(season)[2:]}', 'lg': round(100 * lg, 1), 'minPoss': int(MIN_POSS), 'k': int(K), 'players': out}


def main():
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    res = build(season)
    with open(OUT, 'w') as f:
        json.dump(res, f, separators=(',', ':'))
    print('nba matchups', res['season'], len(res['players']), 'defenders')


if __name__ == '__main__':
    main()
