# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB top tier (prereg.md): B3 position at the top, and the 5-star+ line by the even-odds rule.

    python3 scripts/research/arkstars_nov26/cbb_top.py
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'cbb_recruits_nov16'))
from common import C, CP, CV, load, tstat, place   # noqa: E402
from top import loco, line_report                    # noqa: E402

POOL = 50
SHIP = 41.43
FWD = [2017, 2018, 2019, 2020]


def main():
    H, rows, F, cls, ts = load(list(range(2009, 2021)))
    fv = ts + 20; rk = np.array([r['rk'] or 999 for r in rows]); tr = np.isin(cls, C.TRAIN)
    E = np.zeros(len(rows))
    for c in C.TRAIN:
        te = cls == c; trn = tr & ~te
        E[te] = 20 + C.Hurdle(CP, CV).fit([F[i] for i in np.where(trn)[0]], ts[trn]).ets([F[i] for i in np.where(te)[0]])
    M = C.Hurdle(CP, CV).fit([F[i] for i in np.where(tr)[0]], ts[tr]); E[~tr] = 20 + M.ets([F[i] for i in np.where(~tr)[0]])
    r = place(E, cls, rk); pool = r <= POOL
    hit = (fv >= 45).astype(float); hit55 = (fv >= 55).astype(float)
    big = np.array([1.0 if x['pos'] in ('PF', 'C') else 0.0 for x in rows]); pg = np.array([1.0 if x['pos'] == 'PG' else 0.0 for x in rows])
    X0 = E[:, None]; X3 = np.c_[E, big, pg]
    out = {'n': int((pool & tr).sum()), 'hits': int(hit[pool & tr].sum()), 'pos': {'big': float(big[pool & tr].mean()), 'pg': float(pg[pool & tr].mean())}}
    p0, l0 = loco(X0, hit, cls, pool, C.TRAIN, FWD); p3, l3 = loco(X3, hit, cls, pool, C.TRAIN, FWD)
    d = (l0 - l3)
    m = pool & tr; by = [float(d[m & (cls == c)].mean()) for c in C.TRAIN]; mf = pool & ~tr
    t = tstat(d[m]); p = 0.5 * math.erfc(t / math.sqrt(2))
    out['B3'] = {'ll0': round(float(l0[m].mean()), 5), 'll1': round(float(l3[m].mean()), 5), 'gain': round(float(d[m].mean()), 5), 't': round(t, 2), 'p': round(p, 4),
                 'won': f'{sum(x > 0 for x in by)}/{len(by)}', 'forward': round(float(d[mf].mean()), 5), 'forwardT': round(tstat(d[mf]), 2),
                 'rateBig': round(float(hit[m & (big == 1)].mean()), 3), 'ratePG': round(float(hit[m & (pg == 1)].mean()), 3), 'rateWing': round(float(hit[m & (big == 0) & (pg == 0)].mean()), 3)}
    out['B3']['pass'] = bool(p <= .05 and sum(x > 0 for x in by) >= 6 and d[mf].mean() >= 0)
    print('B3', out['B3'], flush=True)
    # the line: baseline score unless B3 passes (it then needs the position terms; reported on the baseline either way)
    plain5 = float(json.load(open(os.path.join(C.ROOT, 'data', 'cbb_recruits.json')))['model']['stars']['cuts'][3])
    out['line'] = line_report(E, p0, hit, cls, pool, C.TRAIN, FWD, E >= SHIP, E >= plain5, extra={'fv55': hit55}, X=X0)
    # not in the prereg (added after the line result): held-out R2 of realized FV on the six-tier star under each line
    cuts = json.load(open(os.path.join(C.ROOT, 'data', 'cbb_recruits.json')))['model']['stars']['cuts'][:4]
    def r2(line):
        st = C.cut(E, cuts + [line]); sse = sst = 0.0
        for c in C.TRAIN:
            a = cls == c; o = tr & ~a; mu = {t: fv[o][st[o] == t].mean() for t in set(st[o])}
            sse += float(((fv[a] - np.array([mu.get(t, fv[o].mean()) for t in st[a]])) ** 2).sum()); sst += float(((fv[a] - fv[a].mean()) ** 2).sum())
        return round(1 - sse / sst, 4)
    out['tierR2'] = {'shipped': r2(SHIP), 'rule': r2(out['line']['lineScore'])}
    new = p0 >= .5; drop = tr & (E >= SHIP) & ~new; dropf = ~tr & (E >= SHIP) & ~new
    out['between'] = {'n': int(drop.sum()), 'hit': round(float(hit[drop].mean()), 3), 'forwardN': int(dropf.sum()), 'forwardHit': round(float(hit[dropf].mean()), 3)}
    print(out['tierR2'], out['between'])
    by_place = {}
    for a, b in ((1, 1), (2, 3), (4, 5), (6, 8), (9, 12), (13, 20), (21, 35)):
        i = tr & (r >= a) & (r <= b); by_place[f'{a}-{b}'] = {'n': int(i.sum()), 'fv45': round(float(hit[i].mean()), 3), 'fv55': round(float(hit55[i].mean()), 3)}
    out['byPlace'] = by_place
    print(json.dumps(out['line'], indent=0)); print(by_place)
    json.dump(out, open(os.path.join(HERE, 'cbb_top.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
