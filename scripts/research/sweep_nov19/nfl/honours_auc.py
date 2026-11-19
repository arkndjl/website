#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Label agreement: how well each NFL value metric ranks the season's first-team AP All-Pros (and Pro Bowlers) at each
position group, 2018-25. Descriptive (PREREG.md lead 7): AUC among players with 400+ snaps, seasons pooled, 90%
interval from resampling seasons.

    python3 honours_auc.py <board_rows.json> <honours.json> <madden.json or -> <out json>"""
import json
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import names as NM      # noqa: E402
import nfl_games as N   # noqa: E402
from madden_rate_test import roster, zmap   # noqa: E402

GROUPS = ('QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB')
METRICS = ('war', 'xv', 'wav', 'rxp', 'madden')
MIN_SN = 400


def auc(pos, neg):
    if not pos or not neg:
        return None
    s = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return s / (len(pos) * len(neg))


def main():
    B = {int(y): v for y, v in json.load(open(sys.argv[1])).items()}
    H = json.load(open(sys.argv[2]))['honours']
    mad = json.load(open(sys.argv[3])) if sys.argv[3] != '-' else {}
    rows = []     # (season, group, metrics dict, ap1, pb)
    for y, L in sorted(B.items()):
        ros = roster(y)
        M = NM.Matcher([{'name': v[0], 'team': v[1], 'pos': v[2], 'id': k} for k, v in ros.items()])
        lab = {}
        for k in ('ap1', 'pb'):
            lab[k] = set()
            for _, name, team, pos in H.get(str(y), {}).get(k, []):
                r, _ = M.find(name, team=team, pos=pos)
                if r:
                    lab[k].add(r['id'])
        z = zmap(mad[str(y)], ros) if str(y) in mad else {}
        for p in L:
            if p['_g'] not in GROUPS or not p['sn'] or p['sn'] < MIN_SN:
                continue
            m = {'war': p['war'], 'xv': p['xv'], 'wav': p['wav'], 'rxp': (p['waa'] or 0) / p['sn'] if p['waa'] is not None else None,
                 'madden': z.get(p['id'])}
            rows.append((y, p['_g'], m, p['id'] in lab['ap1'], p['id'] in lab['pb']))
    out = {'seasons': sorted(B), 'minSnaps': MIN_SN, 'groups': {}}
    rng = random.Random(3)
    ys = sorted(B)
    for g in GROUPS:
        res = {}
        for li, lname in ((3, 'ap1'), (4, 'pb')):
            for mt in METRICS:
                def one(sel):
                    R = [r for y in sel for r in by[y]]
                    return auc([r[2][mt] for r in R if r[li]], [r[2][mt] for r in R if not r[li]])
                by = defaultdict(list)
                for r in rows:
                    if r[1] == g and r[2][mt] is not None:
                        by[r[0]].append(r)
                yy = [y for y in ys if by[y]]
                a = one(yy)
                bs = sorted(x for x in (one([rng.choice(yy) for _ in yy]) for _ in range(300)) if x is not None) if yy else []
                res[f'{lname}.{mt}'] = None if a is None else {'auc': round(a, 3), 'lo': round(bs[int(.05 * len(bs))], 3), 'hi': round(bs[int(.95 * len(bs)) - 1], 3),
                                                             'n': sum(len(by[y]) for y in yy), 'pos': sum(1 for y in yy for r in by[y] if r[li]), 'seasons': len(yy)}
        out['groups'][g] = res
        print(g, {k: (v or {}).get('auc') for k, v in res.items()}, {k: (v or {}).get('pos') for k, v in res.items() if k.endswith('war')})
    json.dump(out, open(sys.argv[4], 'w'), indent=1)


if __name__ == '__main__':
    main()
