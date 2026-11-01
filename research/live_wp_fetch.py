#!/usr/bin/env python3
"""Game states for the in-game win chance backtest (ticker live odds, Nov 1 2026).

    python3 research/live_wp_fetch.py [nfl nba nhl soccer]   # -> .cache/live_wp/<sport>.json.gz

ESPN public summaries: every play's score and clock (NFL also the ball and field position) and ESPN's own
win probability where it has one (NFL, NBA), plus the DraftKings pregame line from pickcenter. Soccer goals and
red cards come from the scoreboard; its pregame prices are the Pinnacle closes in scripts/soccer_games_hist.json.gz.
Seasons: NFL 2024-2026, NBA and NHL 2024-25 plus 2026-27 to date, LaLiga + Premier League 2024-25 and 2025-26.
"""
import concurrent.futures as cf
import datetime
import gzip
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, '.cache', 'live_wp')
API = 'https://site.api.espn.com/apis/site/v2/sports/'
PATH = {'nfl': 'football/nfl', 'nba': 'basketball/nba', 'nhl': 'hockey/nhl'}


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net research'})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(2 * (i + 1))


def clock_s(txt):
    try:
        if ':' in txt:
            m, s = txt.split(':')
            return int(m) * 60 + float(s)
        return float(txt)
    except (ValueError, AttributeError):
        return None


def dates(a, b, step):
    d = a
    while d <= b:
        yield d.strftime('%Y%m%d')
        d += datetime.timedelta(days=step)


def event_ids(sport):
    p = PATH[sport]
    ids = []
    if sport == 'nfl':
        for yr, weeks in ((2024, 18), (2025, 18), (2026, 8)):
            for w in range(1, weeks + 1):
                d = get(f'{API}{p}/scoreboard?dates={yr}&seasontype=2&week={w}') or {}
                ids += [e['id'] for e in d.get('events') or [] if e['competitions'][0]['status']['type'].get('completed')]
        return ids
    spans = [(datetime.date(2024, 10, 24), datetime.date(2025, 4, 13), 2),
             (datetime.date(2026, 10, 7), datetime.date.today() - datetime.timedelta(days=1), 1)]
    for a, b, step in spans:
        for ds in dates(a, b, step):
            d = get(f'{API}{p}/scoreboard?dates={ds}') or {}
            ids += [e['id'] for e in d.get('events') or [] if e['competitions'][0]['status']['type'].get('completed')]
    return ids


def pregame(d):
    pc = (d.get('pickcenter') or [{}])[0] or {}
    h, a = pc.get('homeTeamOdds') or {}, pc.get('awayTeamOdds') or {}
    return {'spread': pc.get('spread'), 'total': pc.get('overUnder'), 'mlH': h.get('moneyLine'), 'mlA': a.get('moneyLine')}


def summary(sport, eid):
    d = get(f'{API}{PATH[sport]}/summary?event={eid}')
    if not d:
        return None
    comp = d['header']['competitions'][0]
    cs = {c['homeAway']: c for c in comp['competitors']}
    if 'home' not in cs or 'away' not in cs:
        return None
    hid = cs['home']['id']
    try:
        fh, fa = int(cs['home']['score']), int(cs['away']['score'])
    except (KeyError, ValueError, TypeError):
        return None
    wp = {w['playId']: w['homeWinPercentage'] for w in d.get('winprobability') or []}
    plen = {'nfl': 900, 'nba': 720, 'nhl': 1200}[sport]
    nreg = {'nfl': 4, 'nba': 4, 'nhl': 3}[sport]
    if sport == 'nfl':
        plays = [p for dr in (d.get('drives') or {}).get('previous') or [] for p in dr.get('plays') or []]
    else:
        plays = d.get('plays') or []
    st = []
    for i, p in enumerate(plays):
        per = (p.get('period') or {}).get('number')
        c = clock_s((p.get('clock') or {}).get('displayValue'))
        if per is None or c is None or per > nreg:
            continue
        el = (per - 1) * plen + (c if sport == 'nhl' else plen - c)   # ESPN's NHL clock counts up, NFL/NBA down
        row = [round(el), p.get('homeScore'), p.get('awayScore'), wp.get(p.get('id'))]
        if sport == 'nfl':
            s = p.get('end') or {}
            tm = (s.get('team') or {}).get('id')
            row += [0 if not tm else (1 if tm == hid else -1), s.get('yardsToEndzone')]
        if row[1] is None or row[2] is None:
            continue
        st.append(row)
    ab = lambda x: (x.get('team') or {}).get('abbreviation')
    return {'id': eid, 'date': comp.get('date'), 'h': ab(cs['home']), 'a': ab(cs['away']), 'fh': fh, 'fa': fa, 'pre': pregame(d), 'st': st,
            'ot': len(cs['home'].get('linescores') or []) > nreg}


def soccer():
    hist = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))
    byid = {r['id']: r for r in hist if r.get('pc')}
    jobs = [(lg, ds) for lg in ('esp.1', 'eng.1')
            for a, b in ((datetime.date(2024, 8, 10), datetime.date(2025, 5, 31)), (datetime.date(2025, 8, 10), datetime.date(2026, 5, 31)))
            for ds in dates(a, b, 1)]

    def day(job):
        lg, ds = job
        d = get(f'{API}soccer/{lg}/scoreboard?dates={ds}', tries=2) or {}
        got = []
        for ev in d.get('events') or []:
            c = ev['competitions'][0]
            if not c['status']['type'].get('completed') or ev['id'] not in byid:
                continue
            cs = {x['homeAway']: x for x in c['competitors']}
            hid = cs['home']['team']['id']
            det = []
            for x in c.get('details') or []:
                if x.get('shootout'):
                    continue
                mn = round(((x.get('clock') or {}).get('value') or 0) / 60, 1)
                side = 1 if (x.get('team') or {}).get('id') == hid else -1
                if x.get('scoringPlay'):
                    det.append([mn, 'g', side])
                elif x.get('redCard'):
                    det.append([mn, 'r', side])
            r = byid[ev['id']]
            got.append({'id': ev['id'], 'lg': lg, 'date': ev['date'], 'fh': int(cs['home']['score']), 'fa': int(cs['away']['score']),
                        'pc': r['pc'], 'ouc': r.get('ouc'), 'ev': sorted(det)})
        return got

    with cf.ThreadPoolExecutor(8) as ex:
        out = [g for gs in ex.map(day, jobs) for g in gs]
    return out


def main():
    os.makedirs(CACHE, exist_ok=True)
    for sport in sys.argv[1:] or ['nfl', 'nba', 'nhl', 'soccer']:
        if sport == 'soccer':
            rows = soccer()
        else:
            ids = sorted(set(event_ids(sport)))
            print(sport, len(ids), 'games', flush=True)
            with cf.ThreadPoolExecutor(8) as ex:
                rows = [r for r in ex.map(lambda i: summary(sport, i), ids) if r and r['st']]
        with gzip.open(os.path.join(CACHE, f'{sport}.json.gz'), 'wt') as f:
            json.dump(rows, f)
        print(sport, len(rows), 'kept', flush=True)


if __name__ == '__main__':
    main()
