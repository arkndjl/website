#!/usr/bin/env python3
"""T1b (prereg.md): the backup watch's two-season xGap from the live grade's gap or the pXP/60 gap.

    python3 scripts/research/ctx_nov27/nfl/t1b_xgap.py     # -> t1b.json
"""
import json
import os
from collections import defaultdict

import numpy as np

import common as C

K, H = 300, 2


def grade(y, pid):
    p = C.FULL[y][pid]
    return 1000 * (p['war'] or 0.0) / (p['sn'] + K)


def fut(y, pid):
    w = s = 0.0
    for j in range(1, H + 1):
        p = C.FULL[y + j].get(pid)
        if p and p['sn'] > 0:
            w += p['war'] or 0.0
            s += p['sn']
    return 1000 * w / (s + K)


def pairs():
    out = []
    for y in range(2016, 2024):
        rooms = defaultdict(list)
        for pid, r in C.RATE[y].items():
            p = C.FULL[y][pid]
            if (p.get('ax') or p.get('age')) is None:
                continue
            rooms[(p['t'], r['sub'])].append(pid)
        for L in rooms.values():
            L.sort(key=lambda i: -C.RATE[y][i]['sn'])
            s = L[0]
            age = lambda i: C.FULL[y][i].get('ax') or C.FULL[y][i]['age']
            for b in L[1:]:
                if C.RATE[y][b]['sn'] < 50:
                    continue
                ga = grade(y, b) - grade(y, s)
                gb = C.pxp(y, b, C.RATE[y][b]) - C.pxp(y, s, C.RATE[y][s])
                out.append((y, ga, gb, age(s) - age(b), fut(y, b) - fut(y, s)))
    return out


def run(P, only=None):
    d, by = [], {}
    sse = [0.0, 0.0, 0.0]
    for y in range(2019, 2024):
        tr = [p for p in P if p[0] <= y - 3]
        te = [p for p in P if p[0] == y and (only is None or only(p))]
        if only is not None:
            tr = [p for p in tr if only(p)]
        Y = np.array([p[4] for p in tr])
        e = []
        for k in (1, 2):
            X = np.array([[1.0, p[k], p[3]] for p in tr])
            b = np.linalg.lstsq(X, Y, rcond=None)[0]
            e.append(np.array([(p[4] - b @ np.array([1.0, p[k], p[3]])) ** 2 for p in te]))
        sse[0] += e[0].sum(); sse[1] += e[1].sum(); sse[2] += len(te)
        d += list(e[1] - e[0])
        by[y] = bool(e[1].sum() < e[0].sum())
    return {'pairs': int(sse[2]), 'mse_live': round(sse[0] / sse[2], 5), 'mse_pxp': round(sse[1] / sse[2], 5),
            't': round(C.paired_t(d), 2), 'seasons': f'{sum(by.values())}/{len(by)}'}


def full_fit(P, k):
    X = np.array([[1.0, p[k], p[3]] for p in P])
    b = np.linalg.lstsq(X, np.array([p[4] for p in P]), rcond=None)[0]
    return [round(float(v), 5) for v in b]


if __name__ == '__main__':
    P = pairs()
    L = [p for p in P if p[1] > 0]
    out = {'all': run(P), 'listed': run(P, lambda p: p[1] > 0), 'n_pairs': len(P),
           'fit_live': full_fit(P, 1), 'fit_pxp': full_fit(P, 2), 'fit_live_listed': full_fit(L, 1), 'fit_pxp_listed': full_fit(L, 2)}
    json.dump(out, open(os.path.join(C.HERE, 't1b.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))
