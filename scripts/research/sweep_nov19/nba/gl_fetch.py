# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""G League bio rows and game logs (stats.gleague.nba.com, the board's own source) for the sweep tests.

    python3 gl_fetch.py OUTDIR      # bio_<season>.json 2009-2025, log_<season>.json 2018-2025 (one call each, 2 s apart)"""
import json, os, sys, time
import common as C
import gleague_callup as GC

BIO = 'https://stats.gleague.nba.com/stats/leaguedashplayerbiostats?LeagueID=20&Season={s}&SeasonType=Regular%20Season&PerMode=Totals'
LOG = 'https://stats.gleague.nba.com/stats/leaguegamelog?LeagueID=20&PlayerOrTeam=P&Season={s}&SeasonType={t}&Sorter=DATE&Direction=ASC&Counter=0'

out = sys.argv[1]; os.makedirs(out, exist_ok=True)
jobs = [(f'bio_{y}.json', BIO.format(s=GC.sname(y))) for y in range(2009, 2026)]
for y in range(2018, 2026):
    jobs.append((f'log_{y}.json', LOG.format(s=GC.sname(y), t='Regular%20Season')))
    if y >= 2022: jobs.append((f'logsc_{y}.json', LOG.format(s=GC.sname(y), t='Showcase')))
for fn, url in jobs:
    fn = os.path.join(out, fn)
    if os.path.exists(fn): continue
    try:
        d = GC.gl_get(url)
        json.dump(d, open(fn, 'w'))
        print(os.path.basename(fn), len(d['resultSets'][0]['rowSet']), flush=True)
    except Exception as e:
        print(os.path.basename(fn), 'failed', e, flush=True)
    time.sleep(2)
