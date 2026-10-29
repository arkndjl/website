#!/usr/bin/env python3
"""LEBRON (BBall Index) by NBA season, from nbarapm.com's public table.

    python3 scripts/nba_lebron.py --write      # -> scripts/nba_lebron.json.gz

LEBRON = box score + tracking + RAPM, points per 100 possessions (net = O + D). Seasons 2009-10 on. Each season's row
uses that season's games only, so a season S prior can take seasons S-1 and S-2 without seeing S.

File: {"src", "seasons": {end year: [[name, net, O, D, minutes, nba id], ...]}}
"""
import gzip
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'nba_lebron.json.gz')
URL = 'https://nbarapm.com/load/lebron'


def write(src=None):
    raw = json.load(open(src)) if src else \
        json.loads(urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'arkndjl.net'}), timeout=120).read())
    S = {}
    for r in raw:
        if r.get('LEBRON') is None or not r.get('Season'):
            continue
        y = int(r['Season'][:4]) + 1
        S.setdefault(y, []).append([r['player_name'], round(r['LEBRON'], 2), round(r['O-LEBRON'], 2), round(r['D-LEBRON'], 2),
                                    int(round(r.get('Minutes') or 0)), str(r.get('nba_id') or '')])
    if len(S) < 10:
        sys.exit(f'only {len(S)} seasons: kept the old file')
    with gzip.open(OUT, 'wt', encoding='utf-8') as fh:
        json.dump({'src': URL, 'seasons': S}, fh, separators=(',', ':'))
    print(OUT, {y: len(v) for y, v in sorted(S.items())})


_D = None


def seasons():
    """{end year: rows}; {} when the file isn't there"""
    global _D
    if _D is None:
        _D = {int(k): v for k, v in json.load(gzip.open(OUT, 'rt'))['seasons'].items()} if os.path.exists(OUT) else {}
    return _D


if __name__ == '__main__':
    if '--write' in sys.argv:
        write(sys.argv[sys.argv.index('--write') + 1] if len(sys.argv) > sys.argv.index('--write') + 1 else None)
