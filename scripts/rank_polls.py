#!/usr/bin/env python3
"""Pull the AP and Coaches polls for college football and college basketball from ESPN's core API (free) into
scripts/data/polls/<sport>.json: every weekly release, its date and the ranked teams' ESPN ids, with each team's points
(receiving-votes teams under 'others') and ESPN's lastUpdated stamp, plus an id -> team name map in the game files' spelling. scripts/rank_odds.py --record scores ARK against them.

    python3 scripts/rank_polls.py cbb 2016 2026
    python3 scripts/rank_polls.py cfb 2025 2026     # a cross-check only; the CFB record is scripts/cfb_rank.mjs evidence.vsPolls
    python3 scripts/rank_polls.py cfb 2014 2025 cfp # the CFP committee's releases only (scripts/cfb_cfp.py fits on them)
Releases already cached are kept; the current season is always pulled again."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LG = {'cbb': 'basketball/leagues/mens-college-basketball', 'cfb': 'football/leagues/college-football'}
SITE = {'cbb': 'basketball/mens-college-basketball', 'cfb': 'football/college-football'}
POLLS = {'1': 'ap', '2': 'coaches', '21': 'cfp'}     # 21: the CFP committee (football only)


def get(url, tries=4):
    url = url.replace('http://', 'https://').replace('.espn.pvt', '.espn.com')
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if getattr(e, 'code', None) == 404 or i == tries - 1:     # no such poll that week: don't retry
                return None
            time.sleep(2 ** i)


def main(sport, y0, y1, only=None):
    polls = {k: v for k, v in POLLS.items() if (not only or v == only) and (v != 'cfp' or sport == 'cfb')}
    path = os.path.join(HERE, 'data', 'polls', f'{sport}.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = json.load(open(path)) if os.path.exists(path) else {'releases': [], 'names': {}}
    out['releases'] = [r for r in out['releases'] if r.get('date')]
    have = {(r['S'], r['poll'], r['type'], r['week']) for r in out['releases'] if 'others' in r}   # older pulls lack points: pull again
    out['releases'] = [r for r in out['releases'] if 'others' in r or r['poll'] not in polls.values()]
    core = f'https://sports.core.api.espn.com/v2/sports/{LG[sport]}'
    for S in range(y0, y1 + 1):
        out['releases'] = [r for r in out['releases'] if r['S'] != y1 or S != y1]
        for typ in (2, 3):
            wk = get(f'{core}/seasons/{S}/types/{typ}/weeks?limit=60') or {}
            for it in wk.get('items', []):
                w = it['$ref'].split('/weeks/')[1].split('?')[0]
                for pid, poll in polls.items():
                    if S != y1 and (S, poll, typ, w) in have:
                        continue
                    d = get(f'{core}/seasons/{S}/types/{typ}/weeks/{w}/rankings/{pid}')
                    if not d or not d.get('ranks'):
                        continue
                    tid = lambda x: x['team']['$ref'].split('/teams/')[1].split('?')[0]
                    ranks = [{'rk': x['current'], 'id': tid(x), 'pts': x.get('points')} for x in d['ranks']]
                    others = [{'id': tid(x), 'pts': x.get('points')} for x in d.get('others') or [] if x.get('points')]   # receiving votes
                    date = d.get('date')
                    if not date:                   # older releases (2016) carry no date: the poll week's start
                        date = (get(f'{core}/seasons/{S}/types/{typ}/weeks/{w}') or {}).get('startDate')
                    out['releases'].append({'S': S, 'poll': poll, 'type': typ, 'week': w, 'date': date, 'upd': d.get('lastUpdated'),
                                            'ranks': ranks, 'others': others})
            print(sport, S, typ, len([r for r in out['releases'] if r['S'] == S]), flush=True)
    teams = get(f'https://site.api.espn.com/apis/site/v2/sports/{SITE[sport]}/teams?limit=1000') or {}
    for lg in teams.get('sports', [{}])[0].get('leagues', []):
        for t in lg.get('teams', []):
            t = t['team']
            out['names'].setdefault(t['id'], t.get('location') or t.get('displayName'))
    out['releases'].sort(key=lambda r: (r['date'] or '', r['poll']))
    with open(path, 'w') as f:
        json.dump(out, f, separators=(',', ':'))


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else None)
