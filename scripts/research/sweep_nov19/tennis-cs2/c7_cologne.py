#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""C7: Cologne Major 2026 stage advancement, our pre-stage chances (data/cs2_events_fit.json backtest, live sd) against
Polymarket's stage markets at the last hourly price before the stage's first day. Reported only. A market created
after its stage began is in play and is not scored."""
import datetime as dt, json, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pm, cs_maps  # noqa: E402
from cs2_data import key  # noqa: E402
fj = json.load(open(os.path.join(cs_maps.SCRIPTS, '..', 'data', 'cs2_events_fit.json')))
EV = {e['title']: e for e in json.load(open(os.path.join(pm.CACHE, 'cologne_events.json')))}
H = pm.load_hist()
STAGE = {'IEM Cologne Major 2026: Qualify to Stage 2': 'Intel Extreme Masters Cologne Major 2026 Stage 1',
         'IEM Cologne Major 2026: Qualify to Stage 3': 'Intel Extreme Masters Cologne Major 2026 Stage 2'}
out = {}
for title, stage in STAGE.items():
    s = next(x for x in fj['stages'] if x['event'] == stage and x['kind'] == 'swiss')
    e = EV[title]
    t0 = dt.datetime.fromisoformat(s['date'] + 'T00:00:00+00:00').timestamp()
    made = min(pm.ts(m['createdAt']).timestamp() for m in e['markets'])
    ours = s['m'][f"ARK {fj['sd']}"]['P']
    rows = []
    for m in e['markets']:
        k = next((t for t in ours if key(t) == key(m.get('groupItemTitle') or '')), None)
        h = H.get((json.loads(m['clobTokenIds'])[0], 'cologne2')) or []
        v = [p for t, p in h if t <= t0]
        if k and v: rows.append((k, ours[k], v[-1], 1.0 if k in s['adv'] else 0.0))
    o = {'stage_start': s['date'], 'market_created': dt.datetime.fromtimestamp(made, dt.timezone.utc).isoformat()[:16],
         'teams_priced': len(rows), 'teams_in_stage': len(ours)}
    if made >= t0 or not rows:
        o['scored'] = False; o['why'] = 'market opened after the stage began (in play)' if made >= t0 else 'no pre-stage price'
    else:
        b = lambda i: sum((r[i] - r[3]) ** 2 for r in rows) / len(rows)  # noqa: E731
        l = lambda i: -sum(math.log(max(min(r[i], .999), .001)) if r[3] else math.log(max(min(1 - r[i], .999), .001)) for r in rows) / len(rows)  # noqa: E731
        o.update(scored=True, brier_ours=round(b(1), 4), brier_price=round(b(2), 4), ll_ours=round(l(1), 4), ll_price=round(l(2), 4),
                 teams=[[r[0], r[1], round(r[2], 3), int(r[3])] for r in rows])
    out[title] = o
print(json.dumps(out, indent=1))
for q in (HERE, '/mnt/project-files/research-sweep-nov19/impl/tennis-cs2/'):
    json.dump(out, open(os.path.join(q, 'c7_results.json'), 'w'), indent=1)
