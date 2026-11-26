#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Understat deep completions (passes completed within ~20 m of goal, the football-docs metric cards' field-tilt
family) as a fifth side rating in the soccer game model, next to goals, xG and the two market ones.

    python3 scripts/research/soccer_fdocs_nov26/deep.py tune     # grid on 2015-22 (big five, the scored set)
    python3 scripts/research/soccer_fdocs_nov26/deep.py held kd wd   # one pass on 2023-26 at the chosen setting

A match's deep count goes on the goal scale by one fixed ratio (big-five goals per deep completion, 2015-22), then
walks like the xG rating (SUBS 'd': gain kd, weight wd in the blend). Scored like soccer_games.evaluate (1X2 log loss
on the 90-minute result, every scored competition), paired by match; t from season blocks and from match days.
"""
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_data as D
import soccer_games as G

PKL = os.path.join(D.CACHE, 'fdocs_rows.pkl')


def rows_with_deep():
    if os.path.exists(PKL):
        return pickle.load(open(PKL, 'rb'))
    rows = G.add_inj(G.add_mv(G.add_market(G.drop_alias_dups(D.load(G.HIST)))))
    look = {}
    for lg in D.US_LG:
        for S in range(2015, 2027):
            us = D.us_league(lg, S) or {}
            hist = {(tid, h['date'][:10]): h for tid, t in (us.get('teams') or {}).items() for h in t['history']}
            for m in us.get('matches') or []:
                h = hist.get((m['hid'], (m['t'] or '')[:10])); a = hist.get((m['aid'], (m['t'] or '')[:10]))
                if h and a and h['h_a'] == 'h':
                    look[m['id']] = (h['deep'], a['deep'])
    g = dsum = 0
    for r in rows:
        v = look.get(r.get('us'))
        if v:
            r['_dh'], r['_da'] = v
            if r['day'] < '2022-07-01':
                g += r['hs'] + r['as']; dsum += v[0] + v[1]
    c = g / dsum
    for r in rows:
        if '_dh' in r:
            r['hd'], r['ad'] = round(r['_dh'] * c, 4), round(r['_da'] * c, 4)
    print('deep on', sum('hd' in r for r in rows), 'rows, goals per deep', round(c, 4), flush=True)
    pickle.dump(rows, open(PKL, 'wb'))
    return rows


def per_match(rows, P, lo, hi):
    out = {}
    rho = P['rho']

    def score(r, S, lh, la, R):
        if lo <= S <= hi:
            pw, pd, pl = G.wdl(lh, la, rho)
            y = (pl, pd, pw)[G.res90(r) + 1]
            out[r['id']] = (-math.log(max(y, 1e-9)), S, r['day'], r['lg'] in D.BIG5)
    G.run(rows, P, score, et=True)
    return out


def compare(a, b, label):
    ks = [k for k in a if k in b]
    d = np.array([b[k][0] - a[k][0] for k in ks])
    seas = defaultdict(list); day = defaultdict(float)
    for k, x in zip(ks, d):
        seas[a[k][1]].append(x); day[a[k][2]] += x
    dd = np.array(list(day.values()))
    t_day = dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))
    big = np.array([b[k][0] - a[k][0] for k in ks if a[k][3]])
    sm = {S: round(float(np.mean(v)), 5) for S, v in sorted(seas.items())}
    print(f'{label}: n {len(ks)} base {np.mean([a[k][0] for k in ks]):.5f} new {np.mean([b[k][0] for k in ks]):.5f} '
          f'diff {d.mean():+.5f} t(day) {t_day:.2f} big5 {big.mean():+.5f} seasons better {sum(v < 0 for v in sm.values())}/{len(sm)} {sm}', flush=True)
    return d.mean(), t_day, sm


if __name__ == '__main__':
    G.SUBS['d'] = ('hd', 'ad')
    rows = rows_with_deep()
    P = dict(G.params(), kd=0.1, card=1.0, wd=0.0)
    if sys.argv[1] == 'tune':
        base = per_match(rows, P, 2015, 2022)
        for kd in (0.08, 0.15):
            for wd in (0.03, 0.06, 0.1):
                compare(base, per_match(rows, dict(P, kd=kd, wd=wd), 2015, 2022), f'kd {kd} wd {wd}')
        # deep in place of part of the xG weight
        compare(base, per_match(rows, dict(P, kd=0.15, wd=0.05, wx=P['wx'] - 0.05), 2015, 2022), 'kd .15 wd .05 wx-.05')
    else:
        kd, wd = float(sys.argv[2]), float(sys.argv[3])
        base = per_match(rows, P, 2023, 2026)
        compare(base, per_match(rows, dict(P, kd=kd, wd=wd), 2023, 2026), f'HELD kd {kd} wd {wd}')
