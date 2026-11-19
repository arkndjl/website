#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Build the price-history queue for the tennis tests: lower-level events that can reach a scored row's market
memory (T1a, by volume) interleaved with a fixed half of the tour main-draw events (T1b, even event ids)."""
import bisect
from tcommon import *
import pm, pm_join
from tennis_data import is_qual
J = pm_join.build()
rows, players, tn = load_rows()
tour_days = {}
for r in rows:
    if r[0] >= 20250901 and M.scored(r, 2025, 2026):
        for p in (r[7], r[8]): tour_days.setdefault(p, []).append(dord(r[0]))
for v in tour_days.values(): v.sort()
def reach(p, o):
    v = tour_days.get(p, []); i = bisect.bisect_left(v, o)
    return i < len(v) and v[i] - o <= 127
low, top = [], []
for j in J:
    r = rows[j['ri']]
    main = r[2] in M.TOUR_LV and not is_qual(r[4])
    if main:
        if int(j['ev']) % 2 == 0: top.append(j)
    elif r[14] is None:
        o = dord(r[0])
        if reach(r[7], o) or reach(r[8], o): low.append(j)
low.sort(key=lambda j: -j['vol'])
print('lower-level reachable', len(low), 'of', sum(1 for j in J if not (rows[j['ri']][2] in M.TOUR_LV and not is_qual(rows[j['ri']][4]))), 'tour sample', len(top))
q = []
for i in range(max(len(low), len(top))):
    for L in (low, top):
        if i < len(L):
            j = L[i]; q.append({'tok': j['tok'], 'a': j['t0'] - 26 * 3600, 'b': j['t0'], 'f': 10, 'k': 'ml'})
old = [json.loads(x) for x in open(os.path.join(pm.CACHE, 'queue.jsonl'))]
old = [x for x in old if x.get('k') != 'ml']
with open(os.path.join(pm.CACHE, 'queue.jsonl'), 'w') as f:
    for x in old + q: f.write(json.dumps(x) + '\n')
print('queue', len(old) + len(q), 'vol at 1000/2000/3000:', [round(low[i]['vol']) for i in (999, 1999, 2999) if i < len(low)])
