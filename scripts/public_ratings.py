#!/usr/bin/env python3
"""Public team ratings with dated snapshots, for stacking into the game models (team model idea 9, Oct 23 2026).
Only point-in-time sources: every snapshot carries the time it was published, and a game may read only a snapshot
published before it starts.

    python3 scripts/public_ratings.py --cfb [first last]    # ESPN FPI, preseason + every week + bowls, 2015 on
    python3 scripts/public_ratings.py --cfb-current         # this season's runs only (the cfb-board workflow)
    python3 scripts/public_ratings.py --cbb [first last]    # Barttorvik T-Rank time machine, one file a day, 2015 on
    python3 scripts/public_ratings.py --cbb-bpi             # ESPN BPI's own game forecast, every game in cbb_games_hist

Sources (free):
  ESPN core API powerindex by week (sports.core.api.espn.com .../seasons/S/types/T/weeks/W/powerindex). Type 1 week 1
  is the preseason run; type 2 week W is the run after week W's games (each item has lastUpdated). The week pages
  are sometimes a later run (2019 week 1 is the April 2020 final), so snapshots are keyed by their own lastUpdated
  and the reader takes the latest one before kickoff. College basketball BPI has no weekly history (season only).
  Barttorvik time machine (barttorvik.com/timemachine/team_results/YYYYMMDD_team_results.json.gz): T-Rank as of the
  end of that day (the 2023-11-06 file counts that day's openers), preseason files before the first game.
  ESPN's game predictor (core API .../events/E/competitions/E/predictor): BPI's forecast margin (teampredmov) and
  win chance for the home side, with lastModified; college basketball's carries the morning of the game from 2015 on
  (football's pre-2023 ones were rewritten in 2020, like the weekly runs).
  Massey's composite is behind a bot wall from here, so it is not used.

Writes scripts/data/public_ratings/cfb_fpi.json.gz ({season: [[lastUpdated, {espn team id: fpi}], ...]}); the T-Rank
days stay in scripts/.cache/cbb/trank/ (cbb reads them by date).
"""
import gzip
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'data', 'public_ratings')
CACHE = os.path.join(HERE, '.cache')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
FPI = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/{s}/types/{t}/weeks/{w}/powerindex?limit=200'
TRANK = 'https://barttorvik.com/timemachine/team_results/{d}_team_results.json.gz'
FPI_PATH = os.path.join(OUT, 'cfb_fpi.json.gz')
TRANK_DIR = os.path.join(CACHE, 'cbb', 'trank')


def get(url, tries=3):
    for i in range(tries):
        r = subprocess.run(['curl', '-s', '-m', '40', '-A', UA, url], capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        time.sleep(1 + 2 * i)
    return None


# ---------------------------------------------------------------- ESPN FPI (college football)
def fpi_page(s, t, w):
    b = get(FPI.format(s=s, t=t, w=w))
    try:
        d = json.loads(b)
    except Exception:
        return []
    out = []
    for it in d.get('items') or []:
        tid = it['team']['$ref'].split('/teams/')[1].split('?')[0]
        v = next((p.get('value') for p in it.get('predictives') or [] if p.get('name') == 'fpi'), None)
        if v is not None:
            out.append((it.get('lastUpdated'), tid, round(float(v), 3)))
    return out


def cfb(first, last):
    old = json.load(gzip.open(FPI_PATH, 'rt')) if os.path.exists(FPI_PATH) else {}
    jobs = [(s, t, w) for s in range(first, last + 1) for t, ws in ((1, [1]), (2, range(1, 18)), (3, [1])) for w in ws]
    with ThreadPoolExecutor(8) as ex:
        pages = list(ex.map(lambda j: (j[0], fpi_page(*j)), jobs))
    snaps = {}
    for s, rows in pages:
        for lu, tid, v in rows:
            snaps.setdefault(s, {}).setdefault(lu, {})[tid] = v
    for s, by in snaps.items():
        # a snapshot with few teams is a straggler row of a run (one team updated late): fold it into nothing
        old[str(s)] = sorted([[lu, r] for lu, r in by.items() if len(r) >= 60 and lu], key=lambda x: x[0])
        print(s, len(old[str(s)]), 'snapshots', [x[0][:10] for x in old[str(s)]], flush=True)
    os.makedirs(OUT, exist_ok=True)
    with gzip.open(FPI_PATH, 'wt') as f:
        json.dump(old, f, separators=(',', ':'))


def fpi_load():
    return {int(s): v for s, v in json.load(gzip.open(FPI_PATH, 'rt')).items()} if os.path.exists(FPI_PATH) else {}


def fpi_at(snaps, kickoff, lag_h=6):
    """the latest snapshot published at least lag_h hours before kickoff (ISO strings, UTC); None before the first"""
    from datetime import datetime
    k = datetime.fromisoformat(kickoff.replace('Z', '+00:00')).timestamp() - lag_h * 3600
    best = None
    for lu, r in snaps:
        if datetime.fromisoformat(lu.replace('Z', '+00:00')).timestamp() <= k:
            best = r
    return best


# ---------------------------------------------------------------- Barttorvik T-Rank (college basketball)
def trank_days(season):
    d, end = date(season - 1, 10, 25), date(season, 4, 10)
    while d <= end:
        yield d.strftime('%Y%m%d')
        d += timedelta(days=1)


def trank_one(d):
    p = os.path.join(TRANK_DIR, d + '.json')
    if os.path.exists(p):
        return
    b = get(TRANK.format(d=d))
    try:
        rows = json.loads(gzip.decompress(b))
    except Exception:
        return
    # name -> [adjoe, adjde, barthag, games, adj tempo]
    out = {r[1]: [round(r[4], 3), round(r[6], 3), round(r[8], 5), sum(int(x) for x in str(r[3]).split('-')[:2]), round(r[44], 2) if len(r) > 44 and isinstance(r[44], (int, float)) else None] for r in rows}
    with open(p, 'w') as f:
        json.dump(out, f, separators=(',', ':'))


def cbb(first, last):
    os.makedirs(TRANK_DIR, exist_ok=True)
    days = [d for s in range(first, last + 1) for d in trank_days(s)]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(trank_one, days))
    print(len(os.listdir(TRANK_DIR)), 'T-Rank days cached', flush=True)


def trank_at(day):
    """T-Rank as of the end of the day before `day` (YYYY-MM-DD); walks back up to 10 days for gaps"""
    d = date.fromisoformat(day) - timedelta(days=1)
    for _ in range(10):
        p = os.path.join(TRANK_DIR, d.strftime('%Y%m%d') + '.json')
        if os.path.exists(p):
            return json.load(open(p))
        d -= timedelta(days=1)
    return None


# ---------------------------------------------------------------- ESPN BPI game forecasts (college basketball)
BPI = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/events/{i}/competitions/{i}/predictor'
BPI_DIR = os.path.join(CACHE, 'cbb', 'bpi')


def bpi_one(gid):
    import urllib.request
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(BPI.format(i=gid), headers={'User-Agent': UA}), timeout=30)
            d = json.loads(r.read())
            st = {s['name']: s.get('value') for s in (d.get('homeTeam') or {}).get('statistics') or []}
            return gid, [d.get('lastModified'), st.get('teampredmov'), st.get('teampredwinpct')]
        except Exception as e:
            if '404' in str(e):
                return gid, None
            time.sleep(1 + 2 * i)
    return gid, None


def cbb_bpi():
    """one forecast a game, cached by season (home side's view)"""
    import cbb_games as C
    os.makedirs(BPI_DIR, exist_ok=True)
    by = {}
    for g in C.load_hist():
        by.setdefault(g['season'], []).append(str(g['id']))
    for s in sorted(by):
        p = os.path.join(BPI_DIR, f'{s}.json')
        have = json.load(open(p)) if os.path.exists(p) else {}
        todo = [i for i in by[s] if i not in have]
        with ThreadPoolExecutor(24) as ex:
            for gid, v in ex.map(bpi_one, todo):
                have[gid] = v
        with open(p, 'w') as f:
            json.dump(have, f, separators=(',', ':'))
        print(s, len(have), 'games,', sum(1 for v in have.values() if v and v[1] is not None), 'with a BPI margin', flush=True)


def bpi_load():
    out = {}
    if os.path.isdir(BPI_DIR):
        for f in os.listdir(BPI_DIR):
            out.update(json.load(open(os.path.join(BPI_DIR, f))))
    return out


if __name__ == '__main__':
    a = sys.argv[1:]
    rng = [int(x) for x in a[1:3]] if len(a) >= 3 else None
    if a and a[0] == '--cfb-current':
        t = date.today()
        cfb(*(2 * [t.year if t.month >= 7 else t.year - 1]))
    elif a and a[0] == '--cfb':
        cfb(*(rng or (2015, 2026)))
    elif a and a[0] == '--cbb-bpi':
        cbb_bpi()
    elif a and a[0] == '--cbb':
        cbb(*(rng or (2015, 2027)))
    else:
        print(__doc__)
