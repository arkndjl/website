# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""feeder profiles: ids on a TM lineup aged <= 23 and not in the dump with dob + height -> players.json.gz"""
import concurrent.futures as cf
import glob
import gzip
import json
import os
import sys

W = "/home/user/website/.claude/worktrees/agent-aa5a875ff47df8680/scripts"
sys.path.insert(0, W)
import soccer_prospect_data as SD  # noqa
import pandas as pd  # noqa

ids = set()
for fn in glob.glob(os.path.join(SD.CACHE, '*_20*.json.gz')):
    for g in json.load(gzip.open(fn, 'rt')):
        for p in g[9]:
            if p[4] is not None and p[4] <= 23:
                ids.add(int(p[0]))
p = pd.read_csv(os.path.join(SD.CACHE, '..', 'dump', 'players.csv.gz'), usecols=['player_id', 'date_of_birth', 'height_in_cm'])
ok = set(p[p.date_of_birth.notna() & p.height_in_cm.notna()].player_id.astype(int))
fn = os.path.join(SD.CACHE, 'players.json.gz')
have = json.load(gzip.open(fn, 'rt')) if os.path.exists(fn) else {}
todo = [str(i) for i in sorted(ids - ok) if str(i) not in have]
print('ids', len(ids), 'todo', len(todo), flush=True)
n = 0
with cf.ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 32) as ex:
    for i, r in zip(todo, ex.map(lambda i: SD.get(f'/player/{i}'), todo)):
        if r and r.get('data'):
            d = r['data']
            have[i] = {k: d.get(k) for k in ('name', 'lifeDates', 'attributes', 'marketValueDetails', 'clubAssignments')}
        n += 1
        if n % 5000 == 0:
            print(n, flush=True)
tmp = fn + '.tmp'
with gzip.open(tmp, 'wt') as f:
    json.dump(have, f)
os.replace(tmp, fn)
print('profiles', len(have), flush=True)
