# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""S2: a top-GAR hinge (and hinge x age) inside the xMV log fit, scored on the 60m+ band with a nested
leave-one-season-out (ridge and mean map both fit without the held season). Prereg:
/mnt/project-files/leads-nov14/soccer/prereg.md.

    python3 scripts/research/leads_nov14/s2_xmv.py
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_data as D
import soccer_mv as MV

OUT = os.environ.get('LEADS_OUT', '/home/user/scratch-soccer')
BAND = 60e6
PCT = 95


def tstat(d, keys):
    g = defaultdict(float)
    for x, k in zip(d, keys):
        g[k] += x
    m = float(np.mean(d))
    gs = defaultdict(float)
    for x, k in zip(d, keys):
        gs[k] += x - m
    se = math.sqrt(sum(v * v for v in gs.values())) / len(d)
    return round(m, 5), round(m / se, 2) if se else 0.0


def main():
    F = json.load(open(MV.FIT))
    rows = [r for r in D.load(os.path.join(OUT, 'mv_snaps_fringe.json.gz')) if r.get('dob')]
    for r in rows:
        r['age'] = MV.age_of(r['day'], r['dob'])
    MV.levels(rows)
    rows = [r for r in rows if r.get('mv') and 15 <= r['age'] <= 42]
    keep = F['feats']
    res = {'feats': keep, 'snap': {}}
    allrows = []
    for md in MV.SNAPS:
        rs = [r for r in rows if r['day'][5:] == MV.snapdate(2020, md).isoformat()[5:]]
        fs = [MV.feats(r) for r in rs]
        X0 = np.array([[1.0] + [f[k] for k in keep] for f in fs])
        y = np.log([r['mv'] for r in rs])
        S = np.array([r['S'] for r in rs])
        Gv = np.array([max(f['g0'] * min(1, max(r['tmp'], 1) / 19), f['g1']) for f, r in zip(fs, rs)])
        age = np.array([r['age'] - 26 for r in rs])

        def design(cand, tr):
            if not cand:
                return X0
            c = np.percentile(Gv[tr], PCT)
            h = np.maximum(Gv - c, 0.0)
            return np.c_[X0, h, h * age]

        def nested(cand):
            out = np.zeros(len(y))
            raw = np.zeros(len(y))
            seasons = np.unique(S)
            for s in seasons:
                tr = S != s
                X = design(cand, tr)
                p_s = X[~tr] @ MV.solve(X[tr], y[tr])
                pin = np.zeros(len(y))
                for t in seasons:
                    if t == s:
                        continue
                    tr2 = tr & (S != t)
                    X2 = design(cand, tr2)
                    pin[S == t] = X2[S == t] @ MV.solve(X2[tr2], y[tr2])
                knots = MV.calibration(pin[tr], y[tr]) + [MV.tail_slope(pin[tr], y[tr])]
                out[~tr] = MV.calibrate(p_s, knots)
                raw[~tr] = p_s
            return out, raw
        key = f'{md[0]:02d}-{md[1]:02d}'
        pb, rb = nested(False)
        pc, rc = nested(True)
        res['snap'][key] = {'n': len(y), 'band': int((np.exp(y) >= BAND).sum()),
                            'baseMse': round(float(np.mean((y - pb) ** 2)), 4), 'candMse': round(float(np.mean((y - pc) ** 2)), 4),
                            'baseRawMse': round(float(np.mean((y - rb) ** 2)), 4), 'candRawMse': round(float(np.mean((y - rc) ** 2)), 4)}
        for r, yy, a, b in zip(rs, y, pb, pc):
            allrows.append((key, r, yy, a, b))
        print(key, res['snap'][key], flush=True)
    y = np.array([x[2] for x in allrows]); pb = np.array([x[3] for x in allrows]); pc = np.array([x[4] for x in allrows])
    S = np.array([x[1]['S'] for x in allrows])
    d = (y - pc) ** 2 - (y - pb) ** 2
    top = np.exp(y) >= BAND - 1
    for lab, m in (('band', top), ('body', ~top)):
        mm, t = tstat(list(d[m]), list(S[m]))
        per = {int(s): round(float(d[m & (S == s)].mean()), 5) for s in np.unique(S[m])}
        res[lab] = {'n': int(m.sum()), 'baseMse': round(float(np.mean((y[m] - pb[m]) ** 2)), 4),
                    'candMse': round(float(np.mean((y[m] - pc[m]) ** 2)), 4), 'd': mm, 't': t, 'clusters': len(per),
                    'seasonsBetter': sum(1 for v in per.values() if v < 0), 'bySeason': per,
                    'baseBias': round(float(np.mean(pb[m] - y[m])), 4), 'candBias': round(float(np.mean(pc[m] - y[m])), 4)}
    res['maxXmv'] = {'base': round(float(np.exp(pb.max()) / 1e6), 1), 'cand': round(float(np.exp(pc.max()) / 1e6), 1)}
    # the gap forecast above 60m at Oct 24: held-out log(xMV / value) -> log(value at the season's end / value)
    end = {(x[1]['S'], x[1]['p']): x[1]['mv'] for x in allrows if x[0] == '07-01'}
    g = [(a - yy, b - yy, math.log(end[(r['S'], r['p'])] / r['mv'])) for k, r, yy, a, b in allrows
         if k == '10-24' and r['mv'] >= BAND and (r['S'], r['p']) in end]
    g = np.array(g)
    res['gap60'] = {'n': len(g), 'baseSlope': round(float(np.polyfit(g[:, 0], g[:, 2], 1)[0]), 3),
                    'candSlope': round(float(np.polyfit(g[:, 1], g[:, 2], 1)[0]), 3)}
    ex = sorted(((r['mv'], r['n'], r['S'], a, b) for k, r, yy, a, b in allrows if k == '07-01' and r['S'] == 2026), reverse=True)[:8]
    res['top2026'] = [[n, round(mv / 1e6), round(math.exp(a) / 1e6), round(math.exp(b) / 1e6)] for mv, n, s, a, b in ex]
    json.dump(res, open(os.path.join(OUT, 's2_xmv.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != 'snap'}, indent=1))


if __name__ == '__main__':
    main()
