# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ARK Ranking movement for every sport: rank and rating change over the last week.

Each builder passes its ranking rows and last run's output. The ranking is kept in the output's `mvHist`
({date: {id: [rk, rating]}}), stored only when it changes and pruned to the week window plus the snapshot just
before it. Each row gets `prev` (rank as of the sport's last weekly post day, POST; else 7 days ago) and `dR` (rating change since then); the output gets
`mvFrom` (the snapshot date the moves are against). CBB and CFB keep their own `prev` (rkHist / weekly board).

  python3 scripts/rank_moves.py --seed   seed mvHist from git history of the data files (one-off, local)
"""
import datetime as dt
import json
import os
import subprocess
import sys

DAYS = 7
# the weekly post day per sport (Noah, Nov 10 2026; Monday = 0): moves count from the last post day before today (on a
# post day, the one a week back), so each post shows the week since the last one. Not listed: a rolling 7 days.
POST = {'cbb': 0, 'nba': 1, 'cfb': 2, 'nfl': 3, 'soccer': 4, 'soccerp': 4, 'tennis': 5, 'tennisp': 5, 'cs2': 6}
ET = None
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo('America/New_York')
except Exception:
    pass


def today():
    """the day in New York (the posts' clock)"""
    return dt.datetime.now(ET or dt.timezone.utc).date()


def cutoff(day, sport=None, days=DAYS):
    """the date the moves count from: the last post day before `day`, else `days` back"""
    wd = POST.get(sport)
    if wd is None:
        return day - dt.timedelta(days=days)
    return day - dt.timedelta(days=(day.weekday() - wd) % 7 or 7)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _num(v):
    return None if v is None or v != v else round(float(v), 4)


def snap(rows, key, rating):
    return {str(key(r)): [int(r['rk']), _num(rating(r))] for r in rows if r.get('rk') is not None}


def apply(out, rows, old, key, rating, day=None, days=DAYS, sport=None):
    """Adds prev / dR to rows and mvHist / mvFrom to out. old = last run's output dict (or None)."""
    day = day or today()
    hist = dict(sorted(((old or {}).get('mvHist') or {}).items()))
    cur = snap(rows, key, rating)
    if not hist or hist[max(hist)] != cur:        # only on change, so a quiet day writes nothing new
        hist[day.isoformat()] = cur
    cut = cutoff(day, sport, days).isoformat()
    back = [k for k in hist if k <= cut]
    hist = {k: v for k, v in hist.items() if k > cut or (back and k == back[-1])}
    base = hist[back[-1]] if back else None
    for r in rows:
        r.pop('prev', None); r.pop('dR', None)
        b = base.get(str(key(r))) if base else None
        if b:
            r['prev'] = b[0]
            v = _num(rating(r))
            if v is not None and b[1] is not None:
                r['dR'] = round(v - b[1], 4)
    out['mvHist'] = hist
    out['mvFrom'] = back[-1] if back else None
    return out


# sport -> (data file, rows getter, key, rating)
SPORTS = {
    'nfl': ('data/nfl_games.json', lambda d: [d['power']], lambda r: r['t'], lambda r: r['rating']),
    'nba': ('data/nba_games.json', lambda d: [d['power']], lambda r: r['t'], lambda r: r['rating']),
    'nhl': ('data/nhl_games.json', lambda d: [d['power']], lambda r: r['t'], lambda r: r['rating']),
    'soccer': ('data/soccer_games.json', lambda d: [d['power']], lambda r: r['id'], lambda r: r['rating']),
    'cs2': ('data/cs2.json', lambda d: [d['teams']], lambda r: r['k'], lambda r: r['ark']),
}


def tennis_apply(out, old, day=None, sport='tennis'):
    """Tennis keeps one history per tour, under tours.<tour>.mvHist."""
    for t, td in out['tours'].items():
        o = ((old or {}).get('tours') or {}).get(t)
        apply(td, td['players'], o, lambda r: r['id'], lambda r: r['ark'], day, sport=sport)
    return out


def _git_versions(path, since):
    revs = subprocess.run(['git', 'log', '--format=%H %cI', f'--since={since}', '--', path], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.split('\n')
    for line in reversed([x for x in revs if x]):
        h, when = line.split()
        try:
            yield when[:10], json.loads(subprocess.run(['git', 'show', f'{h}:{path}'], cwd=ROOT, capture_output=True,
                                                       text=True, check=True).stdout)
        except (subprocess.CalledProcessError, ValueError):
            continue


def seed():
    today = dt.datetime.now(dt.timezone.utc).date()
    since = (today - dt.timedelta(days=DAYS + 3)).isoformat()
    jobs = dict(SPORTS)
    jobs['tennis'] = ('data/tennis.json', None, None, None)
    for sport, (path, get, key, rating) in jobs.items():
        fake = None
        for day, d in _git_versions(path, since):
            day = dt.date.fromisoformat(day)
            if sport == 'tennis':
                if 'tours' not in d:
                    continue
                fake = tennis_apply(d, fake, day)
            else:
                rows = get(d)[0]
                if not rows or 'rk' not in rows[0]:
                    continue
                fake = apply({}, rows, fake, key, rating, day, sport=sport)
        if fake is None:
            print(sport, 'no history'); continue
        p = os.path.join(ROOT, path)
        cur = json.load(open(p))
        if sport == 'tennis':
            tennis_apply(cur, fake, today)
        else:
            apply(cur, get(cur)[0], fake, key, rating, today, sport=sport)
        open(p, 'w').write(json.dumps(cur, separators=(',', ':'), allow_nan=False))
        n = cur['tours']['atp'] if sport == 'tennis' else cur
        print(sport, 'from', n.get('mvFrom'), 'snapshots', len(n['mvHist']))


if __name__ == '__main__':
    if '--seed' in sys.argv:
        seed()
