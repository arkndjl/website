#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""N1 parser check: Tennis Abstract rows for Jan-May 2026 against the archive rows of the same matches."""
import sys, os, json, gzip
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import tennis_ta as TA, tennis_data as T
TA.CUT = 20260101
TA.PAGES = os.path.join(TA.CACHE, 'ta_validate')
TA.PAUSE = 1.5
rows, players, tn = T.load()
bios = T.sack_players()
ranks = T.ta_ranks()
have = {}
for r in rows:
    if 20260101 <= r[0] <= 20260520 and r[2] in ('C', 'S', 'Q'):
        have[(frozenset((r[7], r[8])), r[4], r[0])] = r
res = dict(pages=0, ta=0, matched=0, winner=0, level=0, score=0, stats=0, stats_eq=0, missing_in_archive=0, newid=0)
miss = []
for tour, n in (('wta', 40), ('atp', 20)):
    pool = TA._pool(bios, ranks[tour], tour)
    pick = [p for p in pool if 80 <= p[0] <= 300][::max(1, len([p for p in pool if 80 <= p[0] <= 300]) // n)][:n]
    new = {}
    find = TA.finder(bios, tour, new)
    for rk, name, pid in pick:
        pg, _ = TA.page(name, tour)
        if pg is None: continue
        res['pages'] += 1
        for r in TA.derive(pid, tour, pg, find):
            if not (20260101 <= r[0] <= 20260520): continue
            res['ta'] += 1
            if 'ta' in r[7][:3] or 'ta' in r[8][:3]: res['newid'] += 1
            h = have.get((frozenset((r[7], r[8])), r[4], r[0]))
            if h is None:
                # same pair and round within two weeks
                c = [v for (pr, rd, d), v in have.items() if pr == frozenset((r[7], r[8])) and rd == r[4] and abs(d - r[0]) < 100]
                h = c[0] if c else None
            if h is None:
                res['missing_in_archive'] += 1; miss.append(r[:10]); continue
            res['matched'] += 1
            res['winner'] += h[7] == r[7]
            res['level'] += h[2] == r[2]
            res['score'] += h[9].split() == r[9].split()
            if h[10] and r[10]:
                res['stats'] += 1; res['stats_eq'] += (h[10] == r[10] and h[11] == r[11])
print(json.dumps(res))
for m in miss[:15]: print(m)
from collections import Counter
c = Counter()
for tour in ('wta', 'atp'):
    pool = TA._pool(bios, ranks[tour], tour)
    find = TA.finder(bios, tour, {})
    for rk, name, pid in pool:
        f = os.path.join(TA.PAGES, f'{tour}_{TA.param(name)}.json')
        if not os.path.exists(f): continue
        for raw in json.load(open(f)):
            for r in TA.derive(pid, tour, [raw], find):
                h = have.get((frozenset((r[7], r[8])), r[4], r[0]))
                if h and h[2] != r[2]: c[(tour, raw[3], raw[8][:1] == 'Q', 'ta ' + r[2], 'arch ' + h[2])] += 1
print(c.most_common(20))
dd = Counter()
for tour in ('wta', 'atp'):
    pool = TA._pool(bios, ranks[tour], tour)
    find = TA.finder(bios, tour, {})
    for rk, name, pid in pool:
        f = os.path.join(TA.PAGES, f'{tour}_{TA.param(name)}.json')
        if not os.path.exists(f): continue
        for r in TA.derive(pid, tour, json.load(open(f)), find):
            for (pr, rd, d), v in have.items():
                pass
            c = [d for (pr, rd, d) in [(k[0], k[1], k[2]) for k in ()]]
idx = {}
for (pr, rd, d), v in have.items(): idx.setdefault((pr, rd), []).append(d)
import datetime as dt
def dn(d): return dt.date(d // 10000, d // 100 % 100, d % 100).toordinal()
for tour in ('wta', 'atp'):
    pool = TA._pool(bios, ranks[tour], tour)
    find = TA.finder(bios, tour, {})
    for rk, name, pid in pool:
        f = os.path.join(TA.PAGES, f'{tour}_{TA.param(name)}.json')
        if not os.path.exists(f): continue
        for r in TA.derive(pid, tour, json.load(open(f)), find):
            for d in idx.get((frozenset((r[7], r[8])), r[4]), []):
                if abs(dn(d) - dn(r[0])) < 30: dd[(r[2], dn(r[0]) - dn(d))] += 1
print(sorted(dd.items()))
