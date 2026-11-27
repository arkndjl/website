#!/usr/bin/env python3
"""T2 (prereg.md): xAAV's live form (M4/sqrt) with pXP/60 of the season before the signing added by position.

    PYTHONPATH=<dir with pyarrow> python3 scripts/research/ctx_nov27/nfl/t2_xaav.py     # -> t2.json
"""
import json
import os

import common as C
import xaav as X
import xaav_lib as L

X.nfl_boards = lambda: {str(y): list(C.FULL[y].values()) for y in C.YEARS}
G = X.NFL_POS

if __name__ == '__main__':
    rows = X.nfl_rows(first=2018)
    for r in rows:
        rt = C.RATE[r['y'] - 1].get(r['id'])
        r['pxp'] = C.pxp(r['y'] - 1, r['id'], rt) if rt else 0.0
        r['hasp'] = 1.0 if rt else 0.0
    F = X.nfl_forms()
    m4 = F['M4']

    def m5(r):
        x = m4(r)
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * r['pxp']]
        return x + [r['hasp']]
    lo, hi = 0.0015, X.NFL_MAX
    pa, pb = L.loyo(rows, m5, lo, hi, log='sqrt'), L.loyo(rows, m4, lo, hi, log='sqrt')
    out = {'rows': len(rows), 'years': sorted({r['y'] for r in rows}), 'loyo': L.compare(rows, pa, pb)}
    cb = L.compare(rows, pb, pb)
    out['m4'] = {k: cb[k] for k in ('maeA', 'topCal', 'r2A', 'slopeA')}
    fa, fb = L.forward(rows, m5, 2022, lo, hi, log='sqrt'), L.forward(rows, m4, 2022, lo, hi, log='sqrt')
    out['forward'] = L.compare(rows, fa, fb, sorted(fa))
    top = [i for i, r in enumerate(rows) if r['t'] >= 0.05]
    out['top5pct'] = L.compare(rows, pa, pb, top)
    json.dump(out, open(os.path.join(C.HERE, 't2.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))
