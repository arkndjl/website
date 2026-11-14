# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""MileSplit pull -> scripts/.cache/recruit/milesplit_hist.json from the cache only. The site began refusing requests
(403) part-way through the pull, so a recruit counts as looked up only if none of his requests was refused; the rest
are left out of the F4 sample rather than read as 'no track marks'."""
import hashlib
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import milesplit as M   # noqa: E402
import data as D        # noqa: E402

state = {'bad': False}


def get(url):
    f = os.path.join(M.CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if not os.path.exists(f): state['bad'] = True; return {'data': []}
    v = json.load(open(f))
    if v.get('status') in (401, 403): state['bad'] = True
    return v


M.get = get
out = {}; n = 0
rows = [r for r in D.load() if r['grade'] >= 75 and r['state']]
for r in rows:
    state['bad'] = False
    v = M.lookup(r['name'], r['state'], r['year'])
    if state['bad']: continue
    n += 1; out[r['rid']] = v or {'marks': None}
json.dump(out, open(os.path.join(M.ROOT, 'scripts', '.cache', 'recruit', 'milesplit_hist.json'), 'w'))
from collections import Counter
print('looked up cleanly', n, 'of', len(rows), 'with marks', sum(bool(v.get('marks')) for v in out.values()))
print(sorted(Counter(r['year'] for r in rows if r['rid'] in out).items()))
