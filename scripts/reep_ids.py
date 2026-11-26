#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Understat player id -> Transfermarkt player id candidates from Reep, the football identity register
(reep.football, CC0 1.0), for scripts/soccer_mv.py's link.

    python3 scripts/reep_ids.py      # download the current release's bridges, write scripts/data/reep_soccer.json.gz
    python3 scripts/reep_ids.py bridges.parquet 2026-11-23.1   # from a file already downloaded

The register maps one player to his ids at many providers (Understat `player`, Transfermarkt `spieler`). It is used
only as a candidate list: soccer_mv.py keeps its own name match first and takes a Reep pair only when the
Transfermarkt player has league minutes for the matched club in that league-season. On release 2026-11-23.1 Reep and
the name link disagreed on 77 of 4,469 shared players and the name link was right on every one checked (Reep had
joined namesakes: Karim / Omar Rekik, Gareth / Thierno Barry), so a Reep pair is never taken unchecked. What it adds
is players whose two names share no word (Franck Zambo = Frank Anguissa, Sávio = Savinho).

Needs duckdb (pip install duckdb). The parquet file is ~260 MB; it is read once and deleted.
"""
import gzip
import json
import os
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'data', 'reep_soccer.json.gz')
URL = 'https://reep.football/downloads/parquet/bridges'
UA = {'User-Agent': 'Mozilla/5.0 (compatible; arkndjl-data/1.0)'}


def build(path=None, release=None):
    import duckdb
    tmp = None
    if path is None:
        fd, tmp = tempfile.mkstemp(suffix='.parquet')
        os.close(fd)
        with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=600) as r, open(tmp, 'wb') as f:
            release = r.geturl().split('/releases/')[1].split('/')[0] if '/releases/' in r.geturl() else None
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        path = tmp
    try:
        c = duckdb.connect()
        rows = c.execute(
            "with b as (select reep_id, provider, external_id from read_parquet(?) where "
            "(provider = 'understat' and namespace = 'player') or (provider = 'transfermarkt' and namespace = 'spieler')) "
            "select u.external_id, string_agg(t.external_id, ',' order by t.external_id) from b u join b t "
            "on u.reep_id = t.reep_id and t.provider = 'transfermarkt' where u.provider = 'understat' group by 1",
            [path]).fetchall()
    finally:
        if tmp:
            os.remove(tmp)
    out = {u: [int(x) for x in t.split(',') if x.isdigit()] for u, t in rows}
    with gzip.open(OUT, 'wt') as f:
        json.dump({'note': 'Understat player id -> Transfermarkt player ids, Reep register (reep.football, CC0 1.0); '
                           'candidates only, checked by scripts/soccer_mv.py --link', 'release': release,
                   'us_tm': out}, f, separators=(',', ':'), sort_keys=True)
    print(len(out), 'Understat players with a Transfermarkt id, release', release)


if __name__ == '__main__':
    build(*(sys.argv[1:3]))
