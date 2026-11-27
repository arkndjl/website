#!/usr/bin/env python3
"""T1 (prereg.md): the depth chart / backup watch grade, board WAR a snap this season (shrunk 300 snaps) against pXP/60.

    python3 scripts/research/ctx_nov27/nfl/t1_backup.py     # -> t1.json
"""
import json
import os
from collections import defaultdict

import common as C

K = 300


def rows_ros():
    """week-9 grades against weeks 10+"""
    out = []
    for y in C.YEARS:
        for pid, r9 in C.RATE9[y].items():
            p9, pf, rf = C.W9[y][pid], C.FULL[y].get(pid), C.RATE[y].get(pid)
            if not pf or not rf or r9['sn'] < 50 or rf['sub'] != r9['sub']:
                continue
            sn = rf['sn'] - r9['sn']
            if sn < 100:
                continue
            xv = None
            if pf.get('xv') is not None and p9.get('xv') is not None:
                xv = (pf['xv'] - p9['xv']) / sn * 1000
            out.append({'y': y, 'id': pid, 'sub': r9['sub'], 't': p9['t'], 'sn0': r9['sn'], 'w': sn,
                        'a': 1000 * (p9['war'] or 0.0) / (r9['sn'] + K), 'b': C.pxp(y, pid, r9),
                        'z': (rf['pts'] - r9['pts']) / sn * 60, 'xv': xv})
    return out


def rows_next():
    """whole-season grades against next season"""
    out = []
    for y in C.YEARS[:-1]:
        for pid, r in C.RATE[y].items():
            n = C.RATE[y + 1].get(pid)
            if r['sn'] < 50 or not n or n['sn'] < 100 or n['grp'] != r['grp']:
                continue
            p = C.FULL[y][pid]
            out.append({'y': y, 'id': pid, 'sub': r['sub'], 't': p['t'], 'sn0': r['sn'], 'w': n['sn'],
                        'a': 1000 * (p['war'] or 0.0) / (r['sn'] + K), 'b': C.pxp(y, pid, r),
                        'z': n['pts'] / n['sn'] * 60, 'xv': None})
    return out


def centre(rows, keys):
    """centre within season x sub-position (weights: target snaps)"""
    G = defaultdict(list)
    for r in rows:
        G[(r['y'], r['sub'])].append(r)
    for rs in G.values():
        w = [r['w'] for r in rs]
        for k in keys:
            m = C.wmean([r[k] for r in rs], w)
            for r in rs:
                r['c' + k] = r[k] - m


def score(rows, tk='z'):
    """leave one season out: slope of the centred target on the centred grade, weighted squared error held out"""
    rows = [r for r in rows if r.get(tk) is not None]
    centre(rows, ('a', 'b', tk))
    ys = sorted({r['y'] for r in rows})
    d, w, by = [], [], {}
    sse = {'a': 0.0, 'b': 0.0, '0': 0.0}
    for y in ys:
        tr = [r for r in rows if r['y'] != y]
        te = [r for r in rows if r['y'] == y]
        sl = {}
        for k in ('a', 'b'):
            sxx = sum(r['w'] * r['c' + k] ** 2 for r in tr)
            sl[k] = sum(r['w'] * r['c' + k] * r['c' + tk] for r in tr) / sxx
        ea = eb = 0.0
        for r in te:
            xa, xb = (r['c' + tk] - sl['a'] * r['ca']) ** 2, (r['c' + tk] - sl['b'] * r['cb']) ** 2
            d.append(xb - xa); w.append(r['w'])
            ea += r['w'] * xa; eb += r['w'] * xb
            sse['0'] += r['w'] * r['c' + tk] ** 2
        sse['a'] += ea; sse['b'] += eb
        by[y] = eb < ea
    sw = sum(w)
    return {'n': len(rows), 'mse_war': round(sse['a'] / sw, 4), 'mse_pxp': round(sse['b'] / sw, 4), 'mse_none': round(sse['0'] / sw, 4),
            'r2_war': round(1 - sse['a'] / sse['0'], 4), 'r2_pxp': round(1 - sse['b'] / sse['0'], 4),
            't': round(C.paired_t(d, w), 2), 'seasons': f'{sum(by.values())}/{len(by)}'}


def pairs(rows):
    """same team, same sub-position: does the grade name the player with the better weeks 10+ rate"""
    G = defaultdict(list)
    for r in rows:
        G[(r['y'], r['t'], r['sub'])].append(r)
    n = ha = hb = 0
    flips = fa = fb = 0
    for rs in G.values():
        rs.sort(key=lambda r: -r['sn0'])
        for i, s in enumerate(rs):
            for b in rs[i + 1:]:
                if s['z'] == b['z']:
                    continue
                n += 1
                up = b['z'] > s['z']
                ha += (b['a'] > s['a']) == up
                hb += (b['b'] > s['b']) == up
                if (b['a'] > s['a']) != (b['b'] > s['b']):
                    flips += 1
                    fa += (b['a'] > s['a']) == up
                    fb += (b['b'] > s['b']) == up
    return {'pairs': n, 'hit_war': round(ha / n, 4), 'hit_pxp': round(hb / n, 4), 'disagree': flips,
            'disagree_war_right': fa, 'disagree_pxp_right': fb}


if __name__ == '__main__':
    A, B = rows_ros(), rows_next()
    out = {'primary_ros': score(A), 'secondary_next': score(B), 'guard_pairs': pairs(A),
           'guard_xv_target': score([r for r in A if r['y'] >= 2018], 'xv')}
    json.dump(out, open(os.path.join(C.HERE, 't1.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))
