#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Coach loyalty, College Basketball: pre-registered Transfer% and landing tests (prereg.md here), on top of
scripts/cbb_market_fit.py's live models.

    python3 scripts/research/coach_loyalty_nov27/cbb.py    # -> results_cbb.json here

Ties (all from seasons up to the one being predicted): came_with (transferred in, his coach now coached him at the
school he left), yrs_hc (seasons under this coach, any school), inherited (at the school before the coach), hc_ten
(the coach's seasons there), leave_x_tie (coach gone next season x a tie). Landing: follow x tie, recruiter.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import cbb_market_fit as M  # noqa: E402
import harness as H  # noqa: E402

OUT = os.path.join(HERE, 'results_cbb.json')
FOLDS = {'A': ({2022, 2023, 2024}, {2025}), 'B': ({2022, 2023}, {2024})}


def ties(by, raw):
    """(pid, y) -> dict of ties going into the y -> y+1 offseason"""
    car = defaultdict(dict)
    for y, rs in by.items():
        for r in rs:
            car[r['pid']][y] = r['team']
    coach = lambda y, t: (raw.get(y, {}).get(t) or {}).get('coach')
    first = {}                                   # (coach, team) -> first season there
    for y in sorted(raw):
        for t, v in raw[y].items():
            first.setdefault((v['coach'], t), y)
    out = {}
    for pid, c in car.items():
        ys = sorted(c)
        for y in ys:
            t = c[y]; hc = coach(y, t)
            if not hc:
                continue
            prior = [(z, c[z]) for z in ys if z <= y]
            yrs = sum(1 for z, tt in prior if coach(z, tt) == hc)
            arrive = min(z for z, tt in prior if tt == t)
            prev = [(z, tt) for z, tt in prior if z < arrive]
            came = bool(prev) and coach(prev[-1][0], prev[-1][1]) == hc
            hc0 = first.get((hc, t), y)
            inh = arrive < hc0
            f0 = coach(ys[0], c[ys[0]])
            out[(pid, y)] = {'came': float(came), 'yrs': min(yrs, 4) / 4, 'inh': float(inh), 'ten': math.log1p(min(raw[y][t].get('ten') or (y - hc0 + 1), 10)) - 1.5,
                             'tie': float(came or not inh), 'hc': hc, 'first_hc': f0, 'yrs_raw': yrs}
    return out


def move_test(by, TS, raw, T):
    rows = M.move_rows(by, TS, raw)
    live = json.load(open(M.OUT))['move']['feats']
    keep = [M.MOVE_F.index(f) for f in live]
    icc = M.MOVE_F.index('cc_next')
    zero = {'came': 0.0, 'yrs': 0.25, 'inh': 0.0, 'ten': 0.0, 'tie': 1.0}
    ext = {
        'T1 came_with': lambda r, t: [t['came']],
        'T2 yrs_hc': lambda r, t: [t['yrs']],
        'T3 inherited': lambda r, t: [t['inh']],
        'T4 hc_ten': lambda r, t: [t['ten']],
        'T5 leave_x_tie': lambda r, t: [r[1][icc] * t['tie']],
        'T5b leave_x_came': lambda r, t: [t['came'], r[1][icc] * t['came']],
        'all (T1-T5)': lambda r, t: [t['came'], t['yrs'], t['inh'], t['ten'], r[1][icc] * t['tie']],
    }
    res = {'live': live, 'n': {}, 'rates': {}}
    # descriptive: moved rate by tie, NIL era
    nil = [r for r in rows if 2022 <= r[0] <= 2025]
    def rate(sel):
        g = [r for r in nil if sel(r, T.get((r[3], r[0]), zero))]
        return {'n': len(g), 'moved': round(float(np.mean([r[2] == 1 for r in g])), 4) if g else None,
                'back': round(float(np.mean([r[2] == 0 for r in g])), 4) if g else None}
    tr = M.MOVE_F.index('trans')
    res['rates'] = {
        'all': rate(lambda r, t: True),
        'transfer in, came with coach': rate(lambda r, t: t['came'] == 1),
        'transfer in, did not': rate(lambda r, t: r[1][tr] == 1 and t['came'] == 0),
        'came with, coach stays': rate(lambda r, t: t['came'] == 1 and r[1][icc] == 0),
        'came with, coach leaves': rate(lambda r, t: t['came'] == 1 and r[1][icc] == 1),
        'other transfer in, coach stays': rate(lambda r, t: r[1][tr] == 1 and t['came'] == 0 and r[1][icc] == 0),
        'other transfer in, coach leaves': rate(lambda r, t: r[1][tr] == 1 and t['came'] == 0 and r[1][icc] == 1),
        'inherited': rate(lambda r, t: t['inh'] == 1),
        'recruited by coach': rate(lambda r, t: t['inh'] == 0),
        'coach leaves, tie': rate(lambda r, t: r[1][icc] == 1 and t['tie'] == 1),
        'coach leaves, no tie': rate(lambda r, t: r[1][icc] == 1 and t['tie'] == 0),
        'coach stays, tie': rate(lambda r, t: r[1][icc] == 0 and t['tie'] == 1),
        'coach stays, no tie': rate(lambda r, t: r[1][icc] == 0 and t['tie'] == 0),
    }
    res['terms'] = {}
    for name, fn in ext.items():
        res['terms'][name] = {}
        for fold, (fit, test) in FOLDS.items():
            a = [r for r in rows if r[0] in fit]; b = [r for r in rows if r[0] in test]
            def XY(rs, extra):
                X = [[r[1][k] for k in keep] + (fn(r, T.get((r[3], r[0]), zero)) if extra else []) for r in rs]
                return np.array(X, float), np.array([r[2] for r in rs])
            out = {}
            ll = {}
            for extra in (False, True):
                Xa, ya = XY(a, extra); Xb, yb = XY(b, extra)
                mu, sd = M.std(Xa, None)
                B = M.mnl((Xa - mu) / sd, ya, 3, lam=2.0)
                last = np.array([r[0] == max(fit) for r in a])
                B = M.recal(((Xa - mu) / sd)[last], ya[last], B, 3)
                P = M.mnl_p((Xb - mu) / sd, B)
                ll[extra] = -np.log(P[np.arange(len(yb)), yb] + 1e-12)
                if extra:
                    out['coef_moved'] = [round(float(v), 3) for v in (B[0, len(keep):] / sd[len(keep):])]
                    out['auc_moved'] = round(M.auc((yb == 1).astype(int), P[:, 1]) or 0, 4)
                else:
                    out['auc_moved_base'] = round(M.auc((yb == 1).astype(int), P[:, 1]) or 0, 4)
            pr = H.paired(ll[True], ll[False], np.array([r[4] for r in b]))
            out.update({'ll_base': round(float(ll[False].mean()), 5), 'll': round(float(ll[True].mean()), 5), 'd': round(float(pr['d']), 6),
                        't': round(-float(pr['t']), 2), 'n': int(pr['n']), 'G': int(pr['G'])})
            res['terms'][name][fold] = out
        print('move', name, {f: (v['d'], v['t'], v['coef_moved']) for f, v in res['terms'][name].items()}, flush=True)
    return res


def land_test(by, TS, raw, loc, T):
    homes = M.player_homes(by)
    fi = M.LAND_F.index('follow')
    coach = lambda y, t: (raw.get(y, {}).get(t) or {}).get('coach')
    res = {'terms': {}}
    cache = {}
    def events(years):
        k = tuple(years)
        if k in cache:
            return cache[k]
        X, ev, ch, info = M.land_events(by, TS, raw, loc, years, homes)
        # extras per row, in M.land_events' order
        E = np.zeros((len(X), 3)); i = 0
        for y in years:
            if y + 1 not in by:
                continue
            nxt = {r['pid']: r for r in by[y + 1]}
            teams = sorted({r['team'] for r in by[y + 1]})
            for r in by[y]:
                n = nxt.get(r['pid'])
                if not n or n['team'] == r['team'] or (r['min_per'] or 0) <= 0:
                    continue
                t_ = T.get((r['pid'], y), {})
                tie = float(t_.get('came', 0) == 1 or t_.get('yrs_raw', 0) >= 2)
                f0 = t_.get('first_hc'); hc = t_.get('hc')
                for t in teams:
                    if t == r['team']:
                        continue
                    c1 = coach(y + 1, t)
                    E[i, 0] = X[i, fi] * tie
                    E[i, 1] = X[i, fi] * t_.get('yrs', 0.25)
                    E[i, 2] = float(f0 is not None and c1 == f0 and f0 != hc)
                    i += 1
        assert i == len(X)
        cache[k] = (X, E, ev, ch, info)
        return cache[k]
    ext = {'L1 follow_tie': [0], 'L1b follow_x_yrs': [1], 'L2 recruiter': [2]}
    folds = {'A': (range(2022, 2025), [2025]), 'B': (range(2022, 2024), [2024])}
    for name, cols in ext.items():
        res['terms'][name] = {}
        for fold, (fit, test) in folds.items():
            Xa, Ea, eva, cha, _ = events(list(fit)); Xt, Et, evt, cht, info = events(list(test))
            lp = {}
            for extra in (False, True):
                A = np.c_[Xa, Ea[:, cols]] if extra else Xa
                Tt = np.c_[Xt, Et[:, cols]] if extra else Xt
                b = M.clogit(A, eva, cha, lam=1.0)
                p = M.clogit_p(Tt, evt, b)
                lp[extra] = np.log(p[cht == 1] + 1e-12)
                if extra:
                    coef = [round(float(v), 3) for v in b[-len(cols):]]
            exposed = int((Et[cht == 1][:, cols[0]] > 0).sum()); avail = len(set(evt[Et[:, cols[0]] > 0]))
            pr = H.paired(-lp[True], -lp[False], np.array([x[2] for x in info]))
            res['terms'][name][fold] = {'ll_base': round(float(lp[False].mean()), 4), 'll': round(float(lp[True].mean()), 4), 'd': round(float(pr['d']), 5),
                                        't': round(-float(pr['t']), 2), 'n': int(pr['n']), 'coef': coef, 'moversWithOption': avail, 'tookIt': exposed}
        print('land', name, res['terms'][name], flush=True)
    # descriptive: follow rate among movers whose coach took another D-I job, by tie
    X, E, ev, ch, info = events(list(range(2022, 2026)))
    has = defaultdict(lambda: [0, 0, 0]);
    for e in np.unique(ev[X[:, fi] > 0]):
        m = ev == e
        tie = E[m][:, 0].max() > 0
        took = bool(((X[m][:, fi] > 0) & (ch[m] == 1)).any())
        has[bool(tie)][0] += 1; has[bool(tie)][1] += took
    res['followShare'] = {('tie' if k else 'no tie'): {'n': v[0], 'followed': v[1], 'share': round(v[1] / max(1, v[0]), 3)} for k, v in has.items()}
    print('follow share', res['followShare'])
    return res


def main():
    by = M.player_rows(write=False)
    for y, rs in by.items():
        for r in rs:
            M.CONF[(y, r['team'])] = r['conf']
    TS, bt = M.team_seasons()
    loc = M.geo(bt)
    raw, _ = M.coaches()
    T = ties(by, raw)
    out = {'move': move_test(by, TS, raw, T), 'land': land_test(by, TS, raw, loc, T)}
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
