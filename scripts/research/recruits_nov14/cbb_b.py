# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""B1 / B2 (pre-registered, /mnt/project-files/recruits/arkstars-nov14/prereg.md): the training window of the CBB
recruit model's P(reached the NBA). Each class 2009-21 held out in turn; log loss of the shipped window (2009-16)
against 2009-21, and against either with the RSCI 1998-2008 classes (basketball-reference) added."""
import glob
import json
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.argv.append('--offline')
import cbb_recruit_fit as C   # noqa: E402

WIDE = list(range(2009, 2022))


def rsci():
    rows = []
    for f in sorted(glob.glob(os.path.join(C.ROOT, 'scripts', '.cache', 'cbb', 'rsci', '*.html'))):
        y = int(os.path.basename(f)[:4]); h = open(f, encoding='utf-8', errors='ignore').read()
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', h[h.find('<tbody'):], re.S):
            rk = re.search(r'data-stat="rank"[^>]*>(?:<[^>]+>)*T?(\d+)', tr); ym = re.search(r'data-stat="year_min"[^>]*>(\d{4})?', tr)
            if not rk: continue
            rows.append({'cls': y, 'rk': int(rk.group(1)), 'nba': 1.0 if ym and ym.group(1) else 0.0})
    return rows


def ll(p, y): return -(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1)))


def fit_p(X, y):
    m, s = C.std_fit(X); b = C.logit_fit(np.clip((X - m) / s, -4, 4), y)
    return lambda Z: 1 / (1 + np.exp(-(b[0] + np.clip((Z - m) / s, -4, 4) @ b[1:])))


def main():
    H = C.history(); smap = C.slug_map(H)
    rows = [r for r in H['recruits'] if r['cls'] in WIDE]
    F, ref = C.frame(rows, smap, H['teams'])
    cls = np.array([r['cls'] for r in rows]); y = np.array([1.0 if r['rfv'] > 20 else 0.0 for r in rows])
    X = np.array([[f['lrk'], f['old']] for f in F])
    R = rsci(); Xr = np.array([[C.lr(r['rk']), ref['old']] for r in R]); yr = np.array([r['nba'] for r in R])
    print('rows', len(rows), 'NBA by class', {c: (int((cls == c).sum()), round(float(y[cls == c].mean()), 3)) for c in WIDE})
    print('RSCI', len(R), 'classes', sorted({r['cls'] for r in R}), 'NBA', round(float(yr.mean()), 3))
    L = {k: {} for k in ('ship', 'wide', 'ship+rsci', 'wide+rsci')}
    for c in WIDE:
        te = cls == c
        tr_s = np.isin(cls, C.TRAIN) & ~te; tr_w = ~te
        for k, (tr, extra) in {'ship': (tr_s, False), 'wide': (tr_w, False), 'ship+rsci': (tr_s, True), 'wide+rsci': (tr_w, True)}.items():
            Xa = np.r_[X[tr], Xr] if extra else X[tr]; ya = np.r_[y[tr], yr] if extra else y[tr]
            L[k][c] = float(ll(fit_p(Xa, ya)(X[te]), y[te]).mean())
    out = {'ll': {k: round(float(np.mean(list(v.values()))), 5) for k, v in L.items()}}
    for a, b in (('ship', 'wide'), ('ship', 'ship+rsci'), ('wide', 'wide+rsci'), ('ship', 'wide+rsci')):
        for nm, cs in (('all', WIDE), ('2009-16', C.TRAIN), ('2017-21', [c for c in WIDE if c not in C.TRAIN])):
            d = np.array([L[a][c] - L[b][c] for c in cs])
            out[f'{a} -> {b} [{nm}]'] = {'gain': round(float(d.mean()), 5), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'won': f'{int((d > 0).sum())}/{len(d)}'}
    out['byClass'] = {k: {c: round(v, 4) for c, v in L[k].items()} for k in L}
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.path.join(HERE, 'cbb_b.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
