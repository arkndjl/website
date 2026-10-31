#!/usr/bin/env python3
"""The current AP Top 25 and Coaches Poll for college basketball from ESPN (free site API) -> data/cbb_polls.json, shown
beside the ARK Ranking (layouts/shortcodes/cbbpower.html) and in its Top 25 graphic. Runs daily in the cbb-board
workflow, so each Monday's release is up the next run. Display only: the game model doesn't read polls (poll terms
failed the backtest, scripts/poll_research.py).

    python3 scripts/cbb_polls_live.py"""
import datetime as dt
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_polls.json')
URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/rankings'


def team(x):
    t = x.get('team') or {}
    return {'tid': str(t.get('id', '')), 'team': t.get('location') or t.get('nickname') or '', 'logo': t.get('logo') or None,
            'rec': x.get('recordSummary') or None, 'pts': x.get('points'), 'fpv': x.get('firstPlaceVotes') or None}


def main():
    with urllib.request.urlopen(URL, timeout=30) as r:
        d = json.load(r)
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'polls': {}}
    for r in d.get('rankings') or []:
        key = 'ap' if r.get('type') == 'ap' else 'coaches' if r.get('type') == 'usa' or 'Coaches' in (r.get('name') or '') else None
        if not key or key in out['polls'] or not r.get('ranks'):
            continue
        occ = r.get('occurrence') or {}
        out['polls'][key] = {'name': r.get('name'), 'date': (r.get('date') or '')[:10], 'week': occ.get('displayValue') or occ.get('value'),
                             'season': (r.get('season') or {}).get('year'),
                             'ranks': [{'rk': x['current'], 'prev': x.get('previous') or None, **team(x)} for x in r['ranks']],
                             'others': [team(x) for x in r.get('others') or [] if x.get('points')]}
    if not out['polls']:
        raise SystemExit('no polls in the ESPN feed; keeping the last file')
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('cbb polls:', ', '.join(f"{k} {v['week']} ({v['date']}) #1 {v['ranks'][0]['team']}" for k, v in out['polls'].items()))


if __name__ == '__main__':
    main()
