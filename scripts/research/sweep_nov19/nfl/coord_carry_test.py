#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Does an NFL coordinator's team value carry into his head-coaching value (PREREG.md C1)?

    python3 coord_carry_test.py <out json>

x = mean team wins over expectation (the head coach's WAx that season) over his OC/DC seasons before his first
head-coaching season; y = his WAx a season as a head coach (seasons 1990-2025). One row a coach; slope and t overall,
and by decade of the first head-coaching season with the slope fit on the other decades."""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import coach_alltime as CA   # noqa: E402


def main():
    D = json.load(gzip.open(CA.SRC_NFL, 'rt'))['nfl']
    S = CA.Sport('nfl', D)
    V = S.values()
    team = defaultdict(float); hc = defaultdict(list)
    for v in V:
        team[(v['t'], v['y'])] += v['sh'] * v['v']
        hc[v['c']].append(v)
    co = defaultdict(list)
    for cid, y, t, side in D['coord']:
        if (t, y) in team:
            co[cid].append((y, team[(t, y)]))
    rows = []
    for cid, L in co.items():
        H = [v for v in hc.get(cid, []) if 1990 <= v['y'] <= 2025]
        if not H:
            continue
        first = min(v['y'] for v in hc[cid])
        pre = [x for y, x in L if y < first]
        n = sum(v['sh'] for v in H)
        if len(pre) >= 2 and n >= 2:
            rows.append((first // 10 * 10, float(np.mean(pre)), sum(v['sh'] * v['v'] for v in H) / n, n, len(pre)))
    R = np.array(rows)
    x, y, w = R[:, 1], R[:, 2], R[:, 3]

    def wls(k):
        xm = (w[k] * x[k]).sum() / w[k].sum(); ym = (w[k] * y[k]).sum() / w[k].sum()
        b = (w[k] * (x[k] - xm) * (y[k] - ym)).sum() / (w[k] * (x[k] - xm) ** 2).sum()
        e = y[k] - ym - b * (x[k] - xm)
        se = math.sqrt((w[k] ** 2 * (x[k] - xm) ** 2 * e ** 2).sum()) / (w[k] * (x[k] - xm) ** 2).sum()
        return b, b / se, xm, ym
    b, t, _, _ = wls(np.ones(len(R), bool))
    out = {'coaches': len(R), 'slope': round(b, 3), 't': round(t, 2), 'r': round(float(np.corrcoef(x, y)[0, 1]), 3), 'byDecade': {}}
    d = np.zeros(len(R))
    for dec in sorted(set(R[:, 0])):
        te = R[:, 0] == dec
        bb, _, xm, ym = wls(~te)
        d[te] = (y[te] - ym) ** 2 - (y[te] - ym - bb * (x[te] - xm)) ** 2
        out['byDecade'][int(dec)] = {'n': int(te.sum()), 'slopeOthers': round(bb, 3), 'gain': round(float((w[te] * d[te]).sum() / w[te].sum()), 4)}
    m = (w * d).sum() / w.sum()
    out['heldGain'] = round(float(m), 4)
    out['heldT'] = round(float(m / (math.sqrt((w ** 2 * (d - m) ** 2).sum()) / w.sum())), 2)
    print(json.dumps(out, indent=1))
    json.dump(out, open(sys.argv[1], 'w'), indent=1)


if __name__ == '__main__':
    main()
