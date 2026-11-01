#!/usr/bin/env python3
"""Data pulls for scripts/team_badges.py (cached in scripts/.cache/style/, not committed).
  cbb   Barttorvik getgamestats.php?year=Y&csv=1 -> cbb_gs{Y}.csv (2015 on)
  nfl   nflverse stats_team_week_Y.csv -> nfl_team{Y}.csv (2014 on)
  cfb   ESPN summary team boxes for every games_wf CFB id, plus team sacks/TFL from the defensive player lines and
        kicking/punting -> cfb_box.json {id: {home: {stat: displayValue}, away: {...}}}
    python3 scripts/team_badges_pull.py cbb nfl cfb [--current]   (--current: only this season's files / new ids)
"""
import concurrent.futures as cf
import datetime
import gzip
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
C = os.path.join(HERE, '.cache', 'style')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            time.sleep(2 ** i)
    return None


def season_now():
    t = datetime.date.today()
    return t.year + (1 if t.month >= 8 else 0)


def cbb(current):
    S = season_now()
    for y in ([S] if current else range(2015, S + 1)):
        p = os.path.join(C, f'cbb_gs{y}.csv')
        if os.path.exists(p) and y < S - 1:
            continue
        b = get(f'https://barttorvik.com/getgamestats.php?year={y}&csv=1')
        if b and len(b) > 1000:
            open(p, 'wb').write(b)
        print('cbb', y, len(b or b''), flush=True)


def nfl(current):
    y0 = datetime.date.today().year - (1 if datetime.date.today().month < 3 else 0)
    for y in ([y0] if current else range(2014, y0 + 1)):
        p = os.path.join(C, f'nfl_team{y}.csv')
        if os.path.exists(p) and y < y0:
            continue
        b = get(f'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{y}.csv')
        if b:
            open(p, 'wb').write(b)
        print('nfl', y, len(b or b''), flush=True)


def cfb_one(gid, ids=False):
    b = get(f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={gid}')
    if not b:
        return gid, None
    try:
        d = json.loads(b)
    except ValueError:
        return gid, None
    out = {}
    side = {}
    for t in (d.get('boxscore') or {}).get('teams') or []:
        ha = t.get('homeAway')
        if ha not in ('home', 'away'):
            continue
        out[ha] = {s['name']: s.get('displayValue') for s in t.get('statistics') or []}
        side[str(t['team']['id'])] = ha
        if ids:
            out[ha[0] + 'id'] = str(t['team']['id'])
    for t in (d.get('boxscore') or {}).get('players') or []:
        ha = side.get(str(t['team']['id']))
        if not ha:
            continue
        for s in t.get('statistics') or []:
            tot = s.get('totals') or []
            lab = s.get('labels') or []
            for k, v in zip(lab, tot):
                out[ha][f"{s['name']}.{k}"] = v
    return gid, out if 'home' in out and 'away' in out else None


def cfb(current):
    p = os.path.join(C, 'cfb_box.json')
    box = json.load(open(p)) if os.path.exists(p) else {}
    wf = json.load(gzip.open(os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')))
    ids = [str(r['id']) for r in wf if r.get('res') is not None and str(r['id']) not in box]
    print('cfb to pull', len(ids), flush=True)
    n = 0
    with cf.ThreadPoolExecutor(8) as ex:
        for gid, o in ex.map(cfb_one, ids):
            if o:
                box[gid] = o
            n += 1
            if n % 500 == 0:
                json.dump(box, open(p, 'w'))
                print('cfb', n, len(box), flush=True)
    json.dump(box, open(p, 'w'))
    print('cfb done', len(box), flush=True)


if __name__ == '__main__':
    os.makedirs(C, exist_ok=True)
    cur = '--current' in sys.argv
    for a in [x for x in sys.argv[1:] if not x.startswith('--')]:
        {'cbb': cbb, 'nfl': nfl, 'cfb': cfb}[a](cur)
