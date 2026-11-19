#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Madden launch overall as a prior input to pXP/60 for OL, LB and DB (PREREG.md M1-M3) and last season's honours
for OL (M4).

    python3 scripts/nfl_rate_research.py --prep
    python3 madden_rate_test.py <madden.json> <honours.json or -> <out json>"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import names as NM               # noqa: E402
import nfl_games as N            # noqa: E402
import nfl_rate_research as RR   # noqa: E402

GROUPS = ('OL', 'LB', 'DB')
TUNE, HELD = (2017, 2018, 2019, 2020), (2021, 2022, 2023, 2024)


def roster(y):
    """board id (pfr) -> (name, team, position) from the season's snap counts (the weekly rosters lack pfr ids for linemen)"""
    out = {}
    for r in N.rows(N.get(f'snap_counts_{y}.csv', f'{N.REL}/snap_counts/snap_counts_{y}.csv')):
        if r.get('pfr_player_id') and r['game_type'] == 'REG':
            out.setdefault(r['pfr_player_id'], (r['player'], N.team(r['team']), r['position']))
    return out


def zmap(rows, ros):
    """pfr id -> z of the launch overall within the Madden position, that edition"""
    by = defaultdict(list)
    for n, t, p, o in rows:
        by[p].append(o)
    st = {p: (np.mean(v), np.std(v) or 1.0) for p, v in by.items()}
    M = NM.Matcher([{'name': n, 'team': t, 'pos': p, 'o': o} for n, t, p, o in rows])
    out = {}
    for pid, (name, team, pos) in ros.items():
        r, how = M.find(name, team=team, pos=pos)
        if r:
            out[pid] = (r['o'] - st[r['pos']][0]) / st[r['pos']][1]
    return out


def tclus(d, w, cl):
    u = np.unique(cl)
    m = (d * w).sum() / w.sum()
    s = np.array([(w[cl == k] * (d[cl == k] - m)).sum() for k in u])
    return m / (math.sqrt((s ** 2).sum() * len(u) / (len(u) - 1)) / w.sum())


def trow(d, w):
    m = (d * w).sum() / w.sum()
    var = (w * (d - m) ** 2).sum() / w.sum()
    return m / math.sqrt(var / (w.sum() ** 2 / (w ** 2).sum()))


def main():
    mad = json.load(open(sys.argv[1]))
    hon = json.load(open(sys.argv[2])) if sys.argv[2] != '-' else None
    D = RR.load()
    targets = RR.YEARS[:-1]
    rows = []      # (target season, pid, grp, snaps next, resid, z or None, vet, honour)
    for ty in targets:
        tr = [y for y in targets if y != ty]
        m, b, xb = RR.means(D, tr)
        mq = RR.mslopes(D, tr, m)
        K = RR.fit_k(D, tr, 'marcelM', m, b, xb, mq=mq)
        T = ty + 1
        ros = roster(T)
        z = zmap(mad[str(T)], ros) if str(T) in mad else {}
        hs = set()
        if hon:
            MR = NM.Matcher([{'name': v[0], 'team': v[1], 'pos': v[2], 'id': k} for k, v in roster(ty).items()])
            for k in ('ap1', 'ap2', 'pb'):
                for _, name, team, pos in hon['honours'].get(str(ty), {}).get(k, []):
                    r, _ = MR.find(name, team=team, pos=pos)
                    if r:
                        hs.add(r['id'])
        for y, pid, t, sn in RR.pairs(D, [ty]):
            g = D[y][pid]['grp']
            if g not in GROUPS:
                continue
            e = t - RR.pred(D, y, pid, 'marcelM', K, m, b, xb, mq=mq)
            rows.append((T, pid, g, sn, e, z.get(pid), any(pid in D.get(q, {}) for q in range(2016, T - 2)), 1.0 if pid in hs else 0.0))
        print(T, len(z), len(hs), flush=True)
    out = {}
    tests = [('M1 OL', 'OL', 5), ('M2 LB', 'LB', 5), ('M3 DB', 'DB', 5)] + ([('M4 OL honours', 'OL', 7)] if hon else [])
    for name, g, xi in tests:
        R = [r for r in rows if r[2] == g and (xi == 7 or str(r[0]) in mad)]
        S = np.array([r[0] for r in R]); w = np.array([r[3] for r in R], float); e = np.array([r[4] for r in R])
        x = np.array([0.0 if r[xi] is None else r[xi] for r in R]); has = np.array([r[xi] is not None for r in R]); vet = np.array([r[6] for r in R])
        d = np.zeros(len(R)); bs = {}
        for s in sorted(set(S)):
            k = S != s
            bb = (w[k] * x[k] * e[k]).sum() / max((w[k] * x[k] * x[k]).sum(), 1e-9)
            bs[int(s)] = round(float(bb), 4)
            te = S == s
            d[te] = (e[te] - bb * x[te]) ** 2 - e[te] ** 2
        res = {'rows': len(R), 'matched': round(float(has.mean()), 3), 'b': bs}
        for lab, ys in (('tune', TUNE), ('held', HELD)):
            k = np.isin(S, ys)
            if k.sum() < 10:
                continue
            res[lab] = {'n': int(k.sum()), 'seasons': sorted({int(s) for s in S[k]}), 'mseBase': round(float((w[k] * e[k] ** 2).sum() / w[k].sum()), 4),
                        'd': round(float((w[k] * d[k]).sum() / w[k].sum()), 5), 'tSeason': round(float(tclus(d[k], w[k], S[k])), 2),
                        'tRows': round(float(trow(d[k], w[k])), 2),
                        'bySeason': {int(s): round(float((w[S == s] * d[S == s]).sum() / w[S == s].sum()), 5) for s in sorted(set(S[k]))},
                        'vetsD': round(float((w[k & vet] * d[k & vet]).sum() / w[k & vet].sum()), 5), 'vetsTRows': round(float(trow(d[k & vet], w[k & vet])), 2)}
        out[name] = res
    print(json.dumps(out, indent=1))
    json.dump(out, open(sys.argv[3], 'w'), indent=1)


if __name__ == '__main__':
    main()
