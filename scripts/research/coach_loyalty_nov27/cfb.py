#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Coach loyalty, College Football: pre-registered Transfer% and follow tests (prereg.md here) on top of
scripts/cfb_transfer_fit.py's live features.

    python3 scripts/cfb_transfer_fit.py                           # rows (scripts/.cache/transfer/rows.json)
    python3 scripts/research/coach_loyalty_nov27/cfb_staff.py     # staff by season (scripts/data/cfb_staff_hist.json)
    python3 scripts/research/coach_loyalty_nov27/cfb.py           # -> results_cfb.json here
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)
import cfb_transfer_fit as T  # noqa: E402
import harness as H  # noqa: E402
import recruits as RC  # noqa: E402

OUT = os.path.join(HERE, 'results_cfb.json')
OFF = {'QB', 'RB', 'WR', 'TE', 'OL'}
DEF = {'EDGE', 'DL', 'LB', 'CB', 'S'}


def rosters():
    """season -> athlete id -> teams on whose ESPN list he is, 2021-26"""
    on = {}
    for s in range(2021, 2027):
        tdiv = T.teams_of(s)
        ids = T.pmap(lambda t: T.roster_ids(s, t), list(tdiv), 12)
        on[s] = defaultdict(set)
        for t, a in zip(tdiv, ids):
            for x in a: on[s][x].add(t)
        print('rosters', s, len(on[s]), flush=True)
    return on


def ties(rows, on, st):
    first = {}
    for y in sorted(st):
        for t, v in st[y].items(): first.setdefault((v['hc'], t), y)
    lo = {t: min(y for y in st if t in st[y]) for t in {t for y in st for t in st[y]}}
    n = defaultdict(int)
    for r in rows:
        s, t, a = r['season'], r['tid'], r['id']
        cur = st.get(s, {}).get(t); nxt = st.get(s + 1, {}).get(t)
        r['hcKnown'] = int(bool(cur))
        r['hcChange'] = int(nxt['hc'] != cur['hc']) if cur and nxt else None
        z = {'came': 0.0, 'yrs': 0.25, 'inh': 0.0, 'ten': 0.0, 'tie': 1.0, 'coordNew': 0.0, 'cameStaff': 0.0}
        if cur:
            hc = cur['hc']
            arrive = s
            while arrive - 1 >= 2021 and t in on[arrive - 1].get(a, ()): arrive -= 1
            prev = [x for x in on.get(arrive - 1, {}).get(a, ()) if x != t] if arrive - 1 >= 2021 else []
            pst = [st.get(arrive - 1, {}).get(x) for x in prev]
            z['came'] = float(any(p and p['hc'] == hc for p in pst))
            z['cameStaff'] = float(any(p and (p['hc'] == hc or hc in p['co']) for p in pst))
            yrs = 0
            for y in range(2021, s + 1):
                for x in on[y].get(a, ()):
                    if (st.get(y, {}).get(x) or {}).get('hc') == hc: yrs += 1; break
            z['yrs'] = min(max(yrs, 1), 4) / 4
            h0 = first[(hc, t)]
            ten = s - h0 + 1
            z['ten'] = math.log1p(min(ten, 5)) - 1.2
            # at the school before the coach: needs the coach's first season there on file (not the first season we have)
            start = min(arrive, r['recYear']) if r.get('recYear') and arrive == 2021 else arrive
            z['inh'] = float(h0 > lo[t] and start < h0)
            z['tie'] = float(z['came'] or not z['inh'])
            side = 'oc' if r['g'] in OFF else 'dc' if r['g'] in DEF else None
            p = st.get(s - 1, {}).get(t)
            if side and p and cur.get(side) and p.get(side): z['coordNew'] = float(not (cur[side] & p[side]))
        r['_z'] = z
        for k, v in z.items(): n[k] += v > 0 if k != 'yrs' else 0
    print('ties', dict(n), 'hc known', sum(r['hcKnown'] for r in rows), 'of', len(rows), 'change labels', sum(r['hcChange'] is not None for r in rows))


def staff():
    f = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cfb_staff_hist.json')))
    raw = defaultdict(dict)
    for y, Tm in f.items():
        for t, v in Tm.items(): raw[int(y)][t] = v
    st = RC.clean(raw)
    for y, Tm in raw.items():
        for t, v in Tm.items():
            if t in st[y]:
                st[y][t]['oc'] = set(RC.keys(v.get('oc'))); st[y][t]['dc'] = set(RC.keys(v.get('dc')))
    return st


def main():
    T.OFFLINE = False
    rows = json.load(open(os.path.join(T.CACHE, 'rows.json')))
    on = rosters()
    st = staff()
    ties(rows, on, st)
    T.talent(rows)
    yT = lambda rs: np.array([r['y'] == 'transfer' for r in rs], float)
    ll = lambda p, y: -(y * np.log(p) + (1 - y) * np.log(1 - p))
    res = {'n': len(rows), 'rates': {}, 'terms': {}}

    def rate(sel):
        g = [r for r in rows if r['hcKnown'] and sel(r, r['_z'])]
        return {'n': len(g), 'transfer': round(float(np.mean([r['y'] == 'transfer' for r in g])), 4) if g else None}
    res['rates'] = {
        'all (coach on file)': rate(lambda r, z: True),
        'transfer in, came with head coach': rate(lambda r, z: z['came'] == 1),
        'transfer in, came with a coach (HC or coordinator there)': rate(lambda r, z: z['cameStaff'] == 1),
        'transfer in, did not': rate(lambda r, z: r['newcomer'] and r['exp'] >= 2 and z['came'] == 0),
        'came with, coach stays': rate(lambda r, z: z['came'] == 1 and r['hcChange'] == 0),
        'came with, coach leaves': rate(lambda r, z: z['came'] == 1 and r['hcChange'] == 1),
        'inherited': rate(lambda r, z: z['inh'] == 1),
        'not inherited': rate(lambda r, z: z['inh'] == 0),
        'coach leaves, tie': rate(lambda r, z: r['hcChange'] == 1 and z['tie'] == 1),
        'coach leaves, no tie': rate(lambda r, z: r['hcChange'] == 1 and z['tie'] == 0),
        'coach stays, tie': rate(lambda r, z: r['hcChange'] == 0 and z['tie'] == 1),
        'coach stays, no tie': rate(lambda r, z: r['hcChange'] == 0 and z['tie'] == 0),
        'new coordinator on his side': rate(lambda r, z: z['coordNew'] == 1),
    }
    for k, v in res['rates'].items(): print(k, v)
    ext = {
        'T1 came_with': lambda r, z: [z['came']],
        'T1s came_with_staff': lambda r, z: [z['cameStaff']],
        'T2 yrs_hc': lambda r, z: [z['yrs']],
        'T3 inherited': lambda r, z: [z['inh']],
        'T4 hc_ten': lambda r, z: [z['ten']],
        'T5 leave_x_tie': lambda r, z: [(r['hcChange'] or 0) * z['tie']],
        'T6 coord_new': lambda r, z: [z['coordNew']],
    }
    folds = {'2024->25 fit, 2025->26 scored': (2024, 2025), 'back': (2025, 2024)}
    for name, fn in ext.items():
        res['terms'][name] = {}
        for fold, (a, b) in folds.items():
            A = [r for r in rows if r['season'] == a]; B = [r for r in rows if r['season'] == b]
            Xa, names = T.design(A); Xb, _ = T.design(B)
            Ea = np.array([fn(r, r['_z']) for r in A], float); Eb = np.array([fn(r, r['_z']) for r in B], float)
            b0, _ = T.logit_fit(Xa, yT(A), T.LAM); b1, _ = T.logit_fit(np.c_[Xa, Ea], yT(A), T.LAM)
            p0 = T.sig(Xb @ b0); p1 = T.sig(np.c_[Xb, Eb] @ b1)
            # the level differs by cycle (portal volume): both models get the scored cycle's base rate through one intercept shift
            def shift(p, y):
                c = 0.0
                for _ in range(30): c += math.log(y.mean() / (1 - y.mean())) - math.log(T.sig(np.log(p / (1 - p)) + c).mean() / (1 - T.sig(np.log(p / (1 - p)) + c).mean()))
                return T.sig(np.log(p / (1 - p)) + c)
            yb = yT(B)
            pr = H.paired(ll(p1, yb), ll(p0, yb), np.array([r['tid'] for r in B]))
            prs = H.paired(ll(shift(p1, yb), yb), ll(shift(p0, yb), yb), np.array([r['tid'] for r in B]))
            res['terms'][name][fold] = {'d': round(float(pr['d']), 6), 't': round(-float(pr['t']), 2), 'tLevelAdj': round(-float(prs['t']), 2), 'n': int(pr['n']), 'G': int(pr['G']),
                                        'coef': [round(float(v), 3) for v in b1[Xa.shape[1]:]], 'auc_base': round(T.auc(p0, yb), 4), 'auc': round(T.auc(p1, yb), 4)}
        print(name, res['terms'][name], flush=True)
    # L1: movers whose head coach took another FBS/FCS head job: did he go there, by tie
    newjob = {}
    for y in st:
        for t, v in st[y].items():
            p = st.get(y - 1, {})
            for o, pv in p.items():
                if o != t and pv['hc'] == v['hc'] and (st[y].get(o) or {}).get('hc') != v['hc']: newjob[(y - 1, o)] = t
    fol = defaultdict(lambda: [0, 0])
    for r in rows:
        j = newjob.get((r['season'], r['tid']))
        if r['y'] != 'transfer' or not j: continue
        z = r['_z']; k = 'came with him before' if z['came'] else '2+ seasons under him' if z['yrs'] >= .5 else 'first season under him'
        fol[k][0] += 1; fol[k][1] += r['to'] == j
        fol[('all', r['season'])][0] += 1; fol[('all', r['season'])][1] += r['to'] == j
    res['follow'] = {str(k): {'n': v[0], 'followed': v[1], 'share': round(v[1] / max(1, v[0]), 3)} for k, v in fol.items()}
    print('follow', res['follow'])
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
