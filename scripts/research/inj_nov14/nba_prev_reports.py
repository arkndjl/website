#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""J4's input: each game's statuses on the last report of the day before (11 PM, else 8 PM, else 5 PM ET).
Writes scripts/.cache/nba/prev_reports.json = {game id: {name: status} or {} (listed, nobody on it) or null (no report)}."""
import datetime as dt, json, os, sys
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import nba_espn as E
import nba_games as N
import nba_inj_hist as I

OUT = os.path.join(E.ROOT, 'scripts', '.cache', 'nba', 'prev_reports.json')
HOURS = (23, 20, 17)
ET = ZoneInfo('America/New_York')

if __name__ == '__main__':
    games, _ = N.load_hist()
    gs = [g for g in games if 2020 <= g['S'] <= 2026]
    byday = {}
    for g in gs:
        tip = dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00')).astimezone(ET)
        byday.setdefault(tip.date(), []).append(g)
    jobs = [((d - dt.timedelta(days=1)).isoformat(), h) for d in byday for h in HOURS]
    with ThreadPoolExecutor(8) as ex:
        texts = dict(zip(jobs, ex.map(lambda j: I.fetch(*j), jobs)))
    out, n = {}, 0
    for d, lst in byday.items():
        p = (d - dt.timedelta(days=1)).isoformat()
        rep, sub = None, False
        for h in HOURS:
            txt = texts.get((p, h), '')
            if txt:
                rep = I.parse(txt, d); sub = True
                break
        for g in lst:
            if not sub:
                out[g['id']] = None
                continue
            found = None
            for (a, h), v in rep.items():
                if (E.team(I.ABBR.get(a, a)), E.team(I.ABBR.get(h, h))) == (g['a'], g['h']) or (E.team(a), E.team(h)) == (g['a'], g['h']):
                    found = v
            out[g['id']] = found if found is not None else {}
            n += found is not None
    json.dump(out, open(OUT, 'w'))
    print(len(out), 'games', n, 'with a prior-day listing', sum(v is None for v in out.values()), 'no report')
