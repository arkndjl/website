# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Point-in-time log of DRatings' pregame win chances (NBA, NHL): the upcoming-games table as posted at fetch time.

    python3 scripts/dratings_log.py            # append today's upcoming rows to scripts/data/dratings_log/<lg>.jsonl
    python3 scripts/dratings_log.py --check    # logged rows vs the same games on the completed pages (do they move?)

The stack test on the completed pages cannot tell whether a posted number was rewritten after the game. This log
holds what was posted before tip; --check compares it with the completed row. One row a game a fetch:
{f: fetch time, t: listed start, a, h, pa, ph}. Predictions only: no scores are stored."""
import datetime as dt, html, json, os, re, subprocess, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DIR = os.path.join(ROOT, 'scripts', 'data', 'dratings_log')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
LEAGUES = {'nba': 'nba-basketball', 'nhl': 'nhl-hockey'}


def page(lg, path=''):
    u = f'https://www.dratings.com/predictor/{LEAGUES[lg]}-predictions/{path}'
    r = subprocess.run(['curl', '-sL', '--compressed', '--max-time', '60', '-A', UA, u], capture_output=True, timeout=90)
    time.sleep(1.1)
    return r.stdout.decode('utf-8', 'replace')


def table(h, head):
    i = h.find(head)
    b = re.search(r'<tbody.*?</tbody>', h[i:], re.S) if i >= 0 else None
    out = []
    for tr in re.findall(r'<tr>(.*?)</tr>', b.group(0) if b else '', re.S):
        d = re.search(r'datetime="([^"]+)"', tr)
        tm = [html.unescape(x) for x in re.findall(r'<a href="/teams/[^"]+">([^<]+)</a>', tr)]
        td = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        pc = next((re.findall(r'([\d.]+)%', c) for c in td if len(re.findall(r'([\d.]+)%', c)) == 2), None)
        if d and len(tm) >= 2 and pc:
            out.append({'t': d.group(1), 'a': tm[0], 'h': tm[1], 'pa': round(float(pc[0]) / 100, 4), 'ph': round(float(pc[1]) / 100, 4)})
    return out


def log():
    os.makedirs(DIR, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    for lg in LEAGUES:
        rows = table(page(lg), 'Upcoming Games')
        with open(os.path.join(DIR, lg + '.jsonl'), 'a') as f:
            for r in rows: f.write(json.dumps(dict(r, f=now), separators=(',', ':')) + '\n')
        print(lg, len(rows), 'upcoming rows logged')


def check():
    for lg in LEAGUES:
        fn = os.path.join(DIR, lg + '.jsonl')
        if not os.path.exists(fn): continue
        last = {}
        for l in open(fn):
            r = json.loads(l); last[(r['t'], r['a'], r['h'])] = r            # the last fetch before the start
        done = {}
        for n in range(1, 6):
            for r in table(page(lg, f'completed/{n}'), 'Completed Games'): done[(r['t'], r['a'], r['h'])] = r
        d = [abs(last[k]['ph'] - done[k]['ph']) for k in last if k in done]
        if d: print(lg, 'games', len(d), 'mean |change|', round(sum(d) / len(d), 4), 'moved 1+ pt', sum(x >= .01 for x in d), 'max', round(max(d), 3))
        else: print(lg, 'no logged game is on the completed pages yet')


if __name__ == '__main__':
    check() if '--check' in sys.argv else log()
