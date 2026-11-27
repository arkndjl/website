#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer context audit, round 2 (prereg.md "Round 2"): P1 backup xGap on the p/90 gap, P2 awards games-left rate.

    python3 scripts/research/ctx_nov27/soccer/run2.py     # -> results2.json here
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCR)
LOCK = 2027


def tstat(d):
    d = np.asarray(d, float)
    return round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)


def p1():
    import backup_age_fit as BA
    S = {y: d for y, d in BA.seasons('soccer-war').items() if y < LOCK}
    link = json.load(gzip.open(os.path.join(SCR, 'data', 'soccer_mv_link.json.gz'), 'rt'))
    dob = {u: link['dob'].get(str(t)) for u, t in link['p'].items()}
    age = lambda p, y: (y - 1 + 8 / 12 - (int(dob[p['p']][:4]) + (int(dob[p['p']][5:7]) - 1) / 12)) if dob.get(p['p']) else None
    by = {y: {p['p']: p for p in d['players']} for y, d in S.items()}
    shape, K, W, MN, H = {'GK': 1, 'D': 4, 'M': 4, 'F': 2}, 900, (1, .5), 270, BA.H
    use = lambda p: p['min']
    last = max(S)
    rows = []
    for y in sorted(S):
        if y - 1 not in S or y + H > last:
            continue
        g = lambda pid: BA.rate(by, pid, [y, y - 1], W, lambda p: p.get('gar90'), use, K, 0.0)
        fut = lambda pid: BA.rate(by, pid, [y + 1, y + 2], [1, 1], lambda p: p.get('gar90'), use, K, 0.0)
        rooms = {}
        for p in S[y]['players']:
            if p.get('gar90') is None or not use(p) or age(p, y) is None:
                continue
            rooms.setdefault(p['team'], {}).setdefault(p['pos'], []).append(p)
        for R in rooms.values():
            for gp, L in R.items():
                L.sort(key=lambda p: -use(p))
                n = shape[gp]
                if len(L) < n:
                    continue
                gs, s = min(((g(x['p']), x) for x in L[:n]), key=lambda t: t[0])
                for b in L[n:3 * n]:
                    gb = g(b['p'])
                    if use(b) < MN or gb <= gs or b.get('pg90') is None or s.get('pg90') is None:
                        continue
                    rows.append((y, gb - gs, b['pg90'] - s['pg90'], age(s, y) - age(b, y), fut(b['p']) - fut(s['p'])))
    P = np.array(rows, float)
    ys = sorted(set(P[:, 0].astype(int)))
    forms = {'A': [1, 3], 'P1b': [2, 3], 'P1c': [1, 2, 3]}
    e = {k: [] for k in forms}
    ss = []
    for y in ys:
        tr, te = P[P[:, 0] + H <= y], P[P[:, 0] == y]
        if len(tr) < 100 or not len(te):
            continue
        for k, cols in forms.items():
            b = np.linalg.lstsq(np.c_[np.ones(len(tr)), tr[:, cols]], tr[:, 4], rcond=None)[0]
            e[k] += list((np.c_[np.ones(len(te)), te[:, cols]] @ b - te[:, 4]) ** 2)
        ss += [int(y)] * len(te)
    ss = np.array(ss)
    e = {k: np.array(v) for k, v in e.items()}
    out = {'pairs': len(P), 'held': len(ss), 'seasons': [int(ys[0]), int(ys[-1])], 'mse': {k: round(float(v.mean()), 6) for k, v in e.items()}}
    for k in ('P1b', 'P1c'):
        won = int(sum(e[k][ss == y].mean() < e['A'][ss == y].mean() for y in sorted(set(ss))))
        n = len(set(ss))
        out[k] = {'t': tstat(e[k] - e['A']), 'seasons_better': f'{won}/{n}', 'pass': bool(tstat(e[k] - e['A']) <= -2 and won * 2 > n),
                  'b': [round(float(v), 5) for v in np.linalg.lstsq(np.c_[np.ones(len(P)), P[:, forms[k]]], P[:, 4], rcond=None)[0]]}
    return out


def p2():
    import soccer_data as D
    import soccer_proj_research as R
    SF = R.season_files()
    snap = D.load(R.SNAPS)
    out = {}
    for f in (0.25, 0.5, 0.75):
        eA, eB, ss, pid = [], [], [], []
        for S in range(2017, 2027):
            sn = snap.get(f'{S}_{f}')
            if not sn or S not in SF:
                continue
            top = sorted(sn['p'].items(), key=lambda t: -t[1][1])[:150]
            for p, (mn, g, pos, lg) in top:
                fx = sn['f'].get(lg)
                if not fx or p not in SF[S]:
                    continue
                rem = mn / fx * (1 - fx)
                x1, x2 = SF.get(S - 1, {}).get(p, [0, 0.0]), SF.get(S - 2, {}).get(p, [0, 0.0])
                rate = (g + .5 * x1[1] + .25 * x2[1]) / (mn + .5 * x1[0] + .25 * x2[0] + 900)
                y = SF[S][p][1] - g
                eA.append((g / max(mn, 1) * rem - y) ** 2); eB.append((rate * rem - y) ** 2); ss.append(S); pid.append(p)
        eA, eB, ss = np.array(eA), np.array(eB), np.array(ss)
        d = defaultdict(list)
        for p, x in zip(pid, eB - eA):
            d[p].append(x)
        won = int(sum(eB[ss == s].mean() < eA[ss == s].mean() for s in sorted(set(ss))))
        out[str(f)] = {'n': len(ss), 'rmse_pace': round(float(np.sqrt(eA.mean())), 4), 'rmse_pred': round(float(np.sqrt(eB.mean())), 4),
                       't': tstat([np.mean(v) for v in d.values()]), 'seasons_better': f'{won}/{len(set(ss))}'}
    out['pass'] = bool(all(v['t'] <= -2 and int(v['seasons_better'].split('/')[0]) * 2 > int(v['seasons_better'].split('/')[1])
                           for v in out.values()))
    return out


if __name__ == '__main__':
    res = {'P1': p1(), 'P2': p2()}
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(HERE, 'results2.json'), 'w'), indent=1, allow_nan=False)
