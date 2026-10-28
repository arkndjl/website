#!/usr/bin/env python3
"""LUMA ARC season boards (LUMA Basketball Research / CourtShare, https://court-share.com/luma, CC BY 4.0).

    python3 scripts/nba_arc.py --write      # download ARC v3.1 season boards -> scripts/nba_arc.json.gz

ARC = Bayesian RAPM with a box-score expected-value prior, points per 100 possessions vs the average possession
(net = O + D). Only the one-season windows are kept: each season's board uses that season's games, so a season S
prior can take seasons S-1 and S-2 without seeing S. Released boards are frozen (hash in MANIFEST.txt); the model's
settings were chosen on data through 2025-26, which no season-level window can avoid.

File: {"src", "version", "seasons": {end year: [[name, team, net, O, D, poss, gp, nba id], ...]}}
"""
import csv
import gzip
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'nba_arc.json.gz')
VERSION = 'v3.1'
URL = f'https://lumahoops.org/luma/data/releases/arc/{VERSION}/arc_season_boards.csv'


def write(src=None):
    raw = open(src, encoding='utf-8').read() if src else \
        urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'arkndjl.net'}), timeout=120).read().decode()
    S = {}
    for r in csv.DictReader(io.StringIO(raw)):
        if r['window_years'] != '1' or not r['net']:
            continue
        y = int(r['season'][:4]) + 1
        f = lambda k: round(float(r[k]), 2) if r.get(k) not in (None, '') else None
        S.setdefault(y, []).append([r['name'], r['team'], f('net'), f('O'), f('D'), int(float(r['poss'] or 0)),
                                    int(float(r['gp'] or 0)), r['pid']])
    with gzip.open(OUT, 'wt', encoding='utf-8') as fh:
        json.dump({'src': URL, 'version': VERSION, 'seasons': S}, fh, separators=(',', ':'))
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
