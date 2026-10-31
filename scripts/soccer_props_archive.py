#!/usr/bin/env python3
"""Archived DraftKings soccer player props from ESPN's core API (odds provider 100, propBets) with each match's ESPN
box score, for the soccer props test (scripts/soccer_props_research.py). ESPN still serves DraftKings' prices for
finished matches from about April 2026 (none in Feb/Mar 2026, checked Oct 31 2026), one item per player and market:
a price for yes at the open and now, and for the milestone ladders the rung (target) each was taken at.

    python3 scripts/soccer_props_archive.py        # -> scripts/data/props/soccer_dk_opens.json.gz

Each match: {id, lg, day, h, a (team names), p: [[athlete, market, open target, open decimal, target, decimal]],
ro: {athlete: [name, team name, starter, appeared, goals, shots on target, shots, assists, saves, position]}}.
markets: ags (anytime goalscorer, target 1), g2 (2+ goals), sot, sh, ast, sav (milestones, target = the rung)."""
import datetime as dt
import gzip
import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'soccer', 'props')
OUT = os.path.join(ROOT, 'scripts', 'data', 'props', 'soccer_dk_opens.json.gz')
CORE = 'https://sports.core.api.espn.com/v2/sports/soccer/leagues'
SITE = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
UA = 'arkndjl.net arkboard (odds research)'
LEAGUES = ('eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'usa.1')
START = dt.date(2026, 3, 1)
TYPES = {'Anytime Goalscorer': 'ags', 'To Score 2+ Goals': 'g2', 'Shots on Target Milestones': 'sot',
         'Shots Milestones': 'sh', 'Assists Milestones': 'ast', 'Goalkeeper Saves Milestones': 'sav'}
STATS = ('totalGoals', 'shotsOnTarget', 'totalShots', 'goalAssists', 'saves')


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


def props(lg, gid):
    items, page = [], 1
    while True:
        j = get(f'{CORE}/{lg}/events/{gid}/competitions/{gid}/odds/100/propBets?limit=1000&page={page}')
        if not j:
            break
        items += j.get('items', [])
        if page >= j.get('pageCount', 1):
            break
        page += 1
    out = []
    for it in items:
        m = TYPES.get((it.get('type') or {}).get('name'))
        ref = (it.get('athlete') or {}).get('$ref', '')
        if not m or '/athletes/' not in ref:
            continue
        a = ref.split('/athletes/')[1].split('?')[0]
        row = [a, m]
        for side in ('open', 'current'):
            s = it.get(side) or {}
            tg = (s.get('target') or {}).get('value')
            dec = (s.get('over') or {}).get('decimal')
            row += [float(tg) if tg is not None else 1.0, float(dec) if dec else None]
        out.append(row)
    return out


def box(lg, gid):
    j = get(f'{SITE}/{lg}/summary?event={gid}')
    if not j:
        return None
    ro = {}
    for side in j.get('rosters') or []:
        tn = (side.get('team') or {}).get('displayName')
        for p in side.get('roster') or []:
            st = {s.get('name'): s.get('value') for s in p.get('stats') or []}
            ro[str(p['athlete']['id'])] = [p['athlete'].get('displayName'), tn, bool(p.get('starter')),
                                           bool(st.get('appearances'))] + [st.get(k) for k in STATS] + \
                                          [(p.get('position') or {}).get('abbreviation')]
    return ro


def game(lg, e):
    gid = e['id']
    fn = os.path.join(CACHE, f'{gid}.json')
    if os.path.exists(fn):
        return json.load(open(fn))
    p = props(lg, gid)
    ro = box(lg, gid) if p else None
    c = (e.get('competitions') or [{}])[0]
    tm = {x.get('homeAway'): (x.get('team') or {}).get('displayName') for x in c.get('competitors', [])}
    r = {'id': gid, 'lg': lg, 'day': e['date'][:10], 'k': e['date'], 'h': tm.get('home'), 'a': tm.get('away'),
         'p': p, 'ro': ro}
    if ro is not None or not p:
        with open(fn, 'w') as f:
            json.dump(r, f)
    return r


def schedule():
    days = [START + dt.timedelta(days=i) for i in range((dt.date.today() - START).days)]

    def one(x):
        lg, d = x
        j = get(f'{SITE}/{lg}/scoreboard?dates={d:%Y%m%d}') or {}
        return [(lg, ev) for ev in j.get('events', []) if (ev.get('status') or {}).get('type', {}).get('completed')]
    with ThreadPoolExecutor(8) as ex:
        out = [g for r in ex.map(one, [(lg, d) for lg in LEAGUES for d in days]) for g in r]
    return list({ev['id']: (lg, ev) for lg, ev in out}.values())


def main():
    os.makedirs(CACHE, exist_ok=True)
    sc = schedule()
    print(len(sc), 'finished matches since', START, flush=True)
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(lambda x: game(*x), sc) if r['p'] and r['ro']]
    rows.sort(key=lambda r: r['k'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, 'wt') as f:
        json.dump(rows, f, separators=(',', ':'))
    by = {}
    for r in rows:
        by.setdefault(r['lg'], [0, 0, r['day']])
        by[r['lg']][0] += 1
        by[r['lg']][1] += len(r['p'])
    print(len(rows), 'matches with props', by)


if __name__ == '__main__':
    main()
