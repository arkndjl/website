#!/usr/bin/env python3
"""Research (Oct 30 2026): more of an age curve in the tennis match chances, after the NHL age line (PR #583).

    python3 scripts/tennis_aging_research.py [matches.csv.gz]   # numpy; writes data/tennis_aging_research.json

The ratings (Elo + the serve/return filter) have no age, and the match chance already carries one linear context term,
CA = (age - 26) / 5, A minus B (Elo lags a young player's rise and an old player's fall; Oct 28, weight about -.10).
An over-30 hinge on top of it added nothing (Oct 28). This tests the rest of the curve, each beside the live terms:
    young    max(0, 22 - age) / 5: the teenage rise steeper than the line
    quad     ((age - 26) / 5) ** 2
    wta      CA x WTA (a line per tour: the WTA peaks younger)
    exp      log(1 + career matches) / 3: career stage in place of the calendar (Elo's K already fades with matches)
    youngN   young x 20 / (matches + 20): the rise where the rating has few matches behind it
Walk-forward like the fit (blend weights on the 3 seasons before each match's season, rating parameters as fit), log loss
on tour-level main draws, 2012-22 (tuning) and 2023+ (held out), paired t by tournament; seasons better in each.
Kept: tuning t <= -1.5 and held out no worse.
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tennis_model as T  # noqa: E402

OUT = os.path.join(T.ROOT, 'data', 'tennis_aging_research.json')
SRC = sys.argv[1] if len(sys.argv) > 1 else '/mnt/project-files/tennis/matches.csv.gz'


def load_rows(path):
    """the history rows (tennis_data COLS order) from tennis_data.py --export's CSV"""
    rows = []
    with gzip.open(path, 'rt', newline='') as fh:
        rd = csv.reader(fh)
        next(rd)
        for r in rd:
            st = lambda a: [int(float(v)) for v in a] if all(v != '' for v in a) else None
            f = lambda v: float(v) if v != '' else None
            rows.append([int(r[0]), r[1], r[2], r[3], r[4], int(r[5]), r[6], r[7], r[8], r[9],
                         st(r[11:20]), st(r[20:29]), f(r[29]), f(r[30]), f(r[31]), f(r[32])])
    return rows


EXTRA = ('young', 'quad', 'wta', 'exp', 'youngN')


def install():
    """context terms + the candidates; the blend reads only the ones a variant uses (others weight 0)"""
    base_ctx = T.Model.ctx

    def ctx(self, a, b, day):
        cx = base_ctx(self, a, b, day)
        out = []
        for p in (a, b):
            age = (day - self.born[p]) / 365.25 if p in self.born else 26.0
            n = self.nm.get(p, 0)
            y = max(0.0, 22 - age) / 5
            out.append((y, ((age - 26) / 5) ** 2, math.log1p(n) / 3, y * 20 / (n + 20)))
        fa, fb = out
        wta = cx[1] if a.startswith('w') else 0.0
        return cx + [fa[0] - fb[0], fa[1] - fb[1], wta, fa[2] - fb[2], fa[3] - fb[3]]
    T.Model.ctx = ctx
    T.CTX = T.CTX + EXTRA
    T.NAMES = ('A', 'B', 'G') + T.CTX
    T.ALL = tuple(range(len(T.NAMES)))


def main():
    rows = load_rows(SRC)
    with gzip.open(os.path.join(os.path.dirname(SRC), 'players.json.gz'), 'rt') as fh:
        bios = json.load(fh)
    T.bios = lambda: bios
    print('rows', len(rows), flush=True)
    install()
    P = dict(T.DEFAULT, **json.load(open(T.FIT))['params'])
    for k in EXTRA:
        P[k] = 0.0
    _, rec = T.run(rows, P, score=lambda r: T.scored(r, 2012 - T.WIN, 2100))
    print('recorded', len(rec), flush=True)
    base = tuple(range(3 + 5))

    def probs(use):
        W, out = {}, []
        for x in rec:
            y = x[0][0] // 10000
            if y not in W:
                win = T.window(rec, y * 10000)
                W[y] = dict(P, **T.fit_blend(win, use)) if len(win) > 1000 else P
            out.append(T.blend_p(W[y], x))
        return np.array(out), W
    keep = np.array([x[0][0] // 10000 >= 2012 for x in rec])
    yr = np.array([x[0][0] // 10000 for x in rec])
    tid = np.array([x[0][6] for x in rec])
    tour = np.array([x[0][1] for x in rec])
    p0, W0 = probs(base)
    l0 = -np.log(np.clip(p0, 1e-9, 1))

    def tby(l, k):
        d = defaultdict(float)
        for t, v in zip(tid[k], l[k]):
            d[t] += v
        return np.array(list(d.values()))

    def pt(a, b):
        d = a - b
        return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    res = {'live': {nm: round(float(l0[keep & (yr >= lo) & (yr <= hi)].mean()), 5) for nm, lo, hi in (('tune', 2012, 2022), ('held', 2023, 2100))},
           'liveCA2026': round(W0[2026]['CA'], 4), 'variants': []}
    print(res, flush=True)
    for i, nm in enumerate(EXTRA):
        use = base + (8 + i,)
        p, W = probs(use)
        l = -np.log(np.clip(p, 1e-9, 1))
        r = {'label': nm, 'w2026': round(W[2026][nm], 4), 'w2018': round(W[2018][nm], 4)}
        for lab, lo, hi in (('tune', 2012, 2022), ('held', 2023, 2100)):
            k = keep & (yr >= lo) & (yr <= hi)
            r[lab] = {'n': int(k.sum()), 'dLL1e4': round(float((l[k] - l0[k]).mean()) * 1e4, 2), 't': round(pt(tby(l, k), tby(l0, k)), 2),
                      'seasons': f"{sum((l[k & (yr == s)] - l0[k & (yr == s)]).mean() < 0 for s in range(lo, min(hi, 2026) + 1))}/{min(hi, 2026) - lo + 1}"}
            for tr in ('atp', 'wta'):
                kk = k & (tour == tr)
                r[lab][tr] = round(float((l[kk] - l0[kk]).mean()) * 1e4, 2)
        r['kept'] = r['tune']['t'] <= -1.5 and r['held']['dLL1e4'] <= 0
        print(json.dumps(r), flush=True)
        res['variants'].append(r)
    with open(OUT, 'w') as fh:
        json.dump(res, fh, indent=1)


if __name__ == '__main__':
    main()
