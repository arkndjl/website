#!/usr/bin/env python3
"""Every FotMob season stat list of the big five, 2016-17 on, as served (research dump: scripts/.cache/soccer/fmg_raw, gitignored)."""
import sys, os, json, time, gzip
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import soccer_data as D, soccer_more as M
OUTD = os.path.join(D.CACHE, 'fmg_raw'); os.makedirs(OUTD, exist_ok=True)
def one(a):
    lg, S, base = a
    p = os.path.join(OUTD, f'{lg}_{S}.json.gz')
    if os.path.exists(p) and S < 2027: return
    top = D.get(base + 'topstats.json') or {}
    names = [s.get('StatName') for s in top.get('TopLists') or []]
    out = {}
    for st in names:
        x = D.get(base + st + '.json', tries=2) or {}
        out[st] = [{'meta': {k: v for k, v in t.items() if k != 'StatList'}, 'rows': t.get('StatList') or []} for t in x.get('TopLists') or []]
        time.sleep(0.1)
    D.save(p, out)
    print(lg, S, len(names), flush=True)
jobs = [(lg, S, base) for lg in M.FMB5 for S, base in sorted(M.season_files(lg).items()) if 2017 <= S <= 2027]
with ThreadPoolExecutor(6) as ex: list(ex.map(one, jobs))
print('DONE')
