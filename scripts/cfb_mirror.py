#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CFBD's play feed from the sportsdataverse release mirror, with no CFBD call.

    python3 scripts/cfb_mirror.py [season]          # refresh scripts/.cache/cfb/mirror/ when the release changed
    python3 scripts/cfb_mirror.py 2026 --file X     # read a parquet already on disk (research, tests)
    python3 scripts/cfb_mirror.py 2026 --max-week 10

The cfbfastR release file (sportsdataverse-data, tag cfbfastR_cfb_pbp, play_by_play_<season>.parquet) is CFBD's
/plays feed for every game with play-by-play, CFBD's own ppa on each play, rebuilt Saturday to Monday in season.
This writes one file a week in CFBD's /plays shape, FBS games only (either team FBS, as classification=fbs):
    scripts/.cache/cfb/mirror/plays<season>-<regular|postseason>-<week>.json
plus index.json (the release's Last-Modified and ETag, weeks and games per week). scripts/cfb_mirror.mjs reads them for
fetch_cfb.mjs, which takes a week from here before it spends a CFBD call and falls back to ESPN's play-by-play for a
week the release does not have yet. The download (about 100 MB) is skipped when the ETag is the one on file, and the
parquet is deleted after it is read. Needs pyarrow.
"""
import json
import math
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'mirror')
URL = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/cfbfastR_cfb_pbp/play_by_play_{}.parquet'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
COLS = ['week', 'season_type', 'game_id', 'id_play', 'game_play_number', 'orig_play_type', 'offense_play', 'defense_play', 'home', 'away',
        'period', 'yards_to_goal', 'down', 'distance', 'yards_gained', 'play_type', 'play_text', 'ppa', 'scoring',
        'offense_score', 'defense_score', 'home_team_division', 'away_team_division', 'drive_number']
# release column -> CFBD /plays field
MAP = [('game_id', 'gameId'), ('offense_play', 'offense'), ('defense_play', 'defense'), ('home', 'home'), ('period', 'period'),
       ('yards_to_goal', 'yardsToGoal'), ('down', 'down'), ('distance', 'distance'), ('yards_gained', 'yardsGained'),
       ('play_type', 'playType'), ('play_text', 'playText'), ('ppa', 'ppa'), ('scoring', 'scoring'),
       ('offense_score', 'offenseScore'), ('defense_score', 'defenseScore'), ('drive_number', 'driveNumber')]
INT = {'gameId', 'period', 'yardsToGoal', 'down', 'distance', 'yardsGained', 'offenseScore', 'defenseScore', 'driveNumber'}


def head(season):
    r = urllib.request.urlopen(urllib.request.Request(URL.format(season), method='HEAD', headers={'User-Agent': UA}), timeout=60)
    return {'etag': r.headers.get('ETag'), 'modified': r.headers.get('Last-Modified'), 'bytes': int(r.headers.get('Content-Length') or 0)}


def download(season, dest):
    r = urllib.request.urlopen(urllib.request.Request(URL.format(season), headers={'User-Agent': UA}), timeout=600)
    with open(dest, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)


def val(v, as_int):
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return int(v) if as_int else round(v, 6)
    if isinstance(v, bool):
        return v
    if as_int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return v


def convert(parquet, season, max_week=None):
    import pyarrow.parquet as pq
    have = set(pq.ParquetFile(parquet).schema_arrow.names)
    t = pq.read_table(parquet, columns=[c for c in COLS if c in have]).to_pydict()
    n = len(t['game_id'])
    order = sorted(range(n), key=lambda i: (t['game_id'][i], t['game_play_number'][i] if t.get('game_play_number') and t['game_play_number'][i] is not None else 0))
    weeks = {}
    for i in order:
        w = t['week'][i]
        if w is None or (max_week and int(w) > max_week):
            continue
        if 'fbs' not in (t['home_team_division'][i], t['away_team_division'][i]):
            continue
        st = (t.get('season_type') or [None] * n)[i] or 'regular'
        row = {dst: val(t[src][i], dst in INT) for src, dst in MAP if src in t}
        # the release's play_type is cfbfastR's cleaned label; CFBD's own is kept beside it
        if t.get('orig_play_type') and t['orig_play_type'][i]:
            row['playType'] = t['orig_play_type'][i]
        row['scoring'] = bool(row.get('scoring'))
        weeks.setdefault((st, int(w)), []).append(row)
    os.makedirs(OUT, exist_ok=True)
    idx = {}
    for (st, w), rows in sorted(weeks.items()):
        with open(os.path.join(OUT, f'plays{season}-{st}-{w}.json'), 'w') as f:
            json.dump(rows, f, separators=(',', ':'))
        idx[f'{st}|{w}'] = {'plays': len(rows), 'games': sorted({r['gameId'] for r in rows})}
    return idx


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    today = __import__('datetime').date.today()
    season = int(args[0]) if args else (today.year if today.month >= 8 else today.year - 1)
    opt = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else None
    local, max_week = opt('--file'), opt('--max-week')
    ix_path = os.path.join(OUT, 'index.json')
    try:
        index = json.load(open(ix_path))
    except Exception:
        index = {}
    stamp = {}
    if not local:
        try:
            stamp = head(season)
        except Exception as e:
            print(f'cfb mirror: release not reachable ({e}); the files on disk stay')
            return 0
        if index.get(str(season), {}).get('etag') == stamp['etag'] and stamp['etag']:
            print(f"cfb mirror: {season} unchanged since {stamp['modified']}")
            return 0
    src = local or os.path.join(OUT, f'_pbp{season}.parquet')
    os.makedirs(OUT, exist_ok=True)
    try:
        if not local:
            download(season, src)
        weeks = convert(src, season, int(max_week) if max_week else None)
    except Exception as e:
        print(f'cfb mirror: {season} failed ({e}); the files on disk stay')
        return 0
    finally:
        if not local and os.path.exists(src):
            os.remove(src)
    index[str(season)] = {**stamp, 'weeks': weeks}
    with open(ix_path, 'w') as f:
        json.dump(index, f)
    print(f"cfb mirror: {season} {sum(v['plays'] for v in weeks.values())} plays, {len(weeks)} weeks, "
          f"{sum(len(v['games']) for v in weeks.values())} FBS games (release of {stamp.get('modified') or 'local file'})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
