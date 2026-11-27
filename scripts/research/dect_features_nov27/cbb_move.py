#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""DECT inputs in CBB Transfer% and landing (prereg.md T1-T4, L1), on top of scripts/cbb_market_fit.py's live models.

    python3 scripts/research/dect_features_nov27/cbb_move.py     # -> results_cbb_move.json here

Point in time: no NIL figure is on file by season, so each season's pay is rebuilt from that season's own lines with
today's formula (scripts/cbb_market.py): value = minutes share x (BPM + 3) + .3; yNIL = the level's budget split by the
value he brought into the season (last season's line; .2 with none), xNIL = the level's pool split by this season's
value. Levels by conference (high-major, mid-major, low-major) at today's budgets; the year's market size cancels in
every ratio tested.
  T1 zgap    ln((xNIL + 25K) / (yNIL + 25K)): the market's price over his school's pay (DECT's transfer side less college)
  T2 k       his school's ln(roster yNIL / roster xNIL): what the school pays per market dollar
  T3 up_pay  ln(his price one level up / his price at his level), 0 at a high-major
  T4 dect    the DECT certainty-equivalent staying edge (asinh, $M / .25) for board-ranked players, 0 otherwise, + a ranked flag
  L1 dest_k  landing: the destination's k (money per market dollar there)
Gate: fold A (fit 2022-24, score 2025->26) t >= 2 clustered by team, fold B (fit 2022-23, score 2024->25) t > -1.
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR); sys.path.insert(0, HERE)
import cbb_market_fit as M  # noqa: E402
import harness as H  # noqa: E402

OUT = os.path.join(HERE, 'results_cbb_move.json')
FOLDS = {'A': ({2022, 2023, 2024}, {2025}), 'B': ({2022, 2023}, {2024})}
BUD = {'HM': 13.7e6, 'MM': 2.3e6, 'LM': 0.25e6}
HMC = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}
MMC = {'A10', 'MWC', 'WCC', 'Amer', 'MVC'}
UP = {'LM': 'MM', 'MM': 'HM'}


def lvl(conf): return 'HM' if conf in HMC else 'MM' if conf in MMC else 'LM'


def pay(by):
    """(pid, y) -> {zgap, k, up_pay}; team (y, t) -> k"""
    out, tk = {}, {}
    for y, rs in by.items():
        prev = {r['pid']: r for r in by.get(y - 1, [])}
        val = lambda r: (r.get('min_per') or 0) / 100 * max(0.0, M.rate(r) + 3) + 0.3
        V = {r['pid']: val(r) for r in rs}
        P = {r['pid']: (val(prev[r['pid']]) if r['pid'] in prev else 0.2) for r in rs}
        T = defaultdict(list)
        for r in rs: T[r['team']].append(r)
        pool = defaultdict(float); vs = defaultdict(float)
        for t, ps in T.items():
            L = lvl(ps[0]['conf']); pool[L] += BUD[L]; vs[L] += sum(V[p['pid']] for p in ps)
        price = {L: pool[L] / vs[L] for L in pool}
        for t, ps in T.items():
            L = lvl(ps[0]['conf']); sp = sum(P[p['pid']] for p in ps)
            yn = {p['pid']: BUD[L] * P[p['pid']] / sp for p in ps}; xn = {p['pid']: price[L] * V[p['pid']] for p in ps}
            k = math.log(sum(yn.values()) / sum(xn.values())); tk[(y, t)] = k
            for p in ps:
                u = UP.get(L)
                out[(p['pid'], y)] = {'zgap': math.log((xn[p['pid']] + 25e3) / (yn[p['pid']] + 25e3)), 'k': k,
                                      'up_pay': math.log(price[u] / price[L]) * min(1.0, V[p['pid']] / 1.5) if u and u in price else 0.0}
    return out, tk


def dect_of():
    """(pid, y) -> staying edge from the DECT history rows (hist.py); pid there is the kit's, matched by name and year"""
    try:
        import hist
        h = hist.load()
    except Exception as e:
        print('no DECT rows', e); return {}
    return {(r.get('name'), r['year']): math.asinh(r['ce'] / 0.25) for r in h['cbb'] if r.get('ce') is not None and r.get('name')}


def move_test(by, TS, raw, X, D):
    rows = M.move_rows(by, TS, raw)
    live = json.load(open(M.OUT))['move']['feats']
    keep = [M.MOVE_F.index(f) for f in live]
    nm = {(r['pid'], y): r.get('player') or r.get('name') for y, rs in by.items() for r in rs}
    z0 = {'zgap': 0.0, 'k': 0.0, 'up_pay': 0.0}
    def dd(r):
        v = D.get((nm.get((r[3], r[0])), r[0])) or D.get((nm.get((r[3], r[0])), r[0] + 1))
        return [v or 0.0, float(v is not None)]
    ext = {'T1 zgap': lambda r, x: [x['zgap']], 'T2 k': lambda r, x: [x['k']], 'T3 up_pay': lambda r, x: [x['up_pay']], 'T4 dect': lambda r, x: dd(r)}
    res = {'live': live, 'terms': {}, 'dectMatched': int(sum(1 for r in rows if dd(r)[1]))}
    for name, fn in ext.items():
        res['terms'][name] = {}
        for fold, (fit, test) in FOLDS.items():
            a = [r for r in rows if r[0] in fit]; b = [r for r in rows if r[0] in test]
            def XY(rs, extra):
                Z = [[r[1][k] for k in keep] + (fn(r, X.get((r[3], r[0]), z0)) if extra else []) for r in rs]
                return np.array(Z, float), np.array([r[2] for r in rs])
            lls, o = {}, {}
            for extra in (False, True):
                Xa, ya = XY(a, extra); Xb, yb = XY(b, extra)
                mu, sd = M.std(Xa, None)
                B = M.mnl((Xa - mu) / sd, ya, 3, lam=2.0)
                last = np.array([r[0] == max(fit) for r in a])
                B = M.recal(((Xa - mu) / sd)[last], ya[last], B, 3)
                P = M.mnl_p((Xb - mu) / sd, B)
                lls[extra] = -np.log(P[np.arange(len(yb)), yb] + 1e-12)
                o['auc' if extra else 'aucBase'] = round(M.auc((yb == 1).astype(int), P[:, 1]) or 0, 4)
                if extra: o['coefMoved'] = [round(float(v), 3) for v in B[0, len(keep):] / sd[len(keep):]]
            pr = H.paired(lls[True], lls[False], np.array([r[4] for r in b]))
            o.update({'llBase': round(float(lls[False].mean()), 5), 'll': round(float(lls[True].mean()), 5), 't': round(-float(pr['t']), 2), 'n': int(pr['n'])})
            res['terms'][name][fold] = o
        v = res['terms'][name]; v['pass'] = bool(v['A']['t'] >= 2 and v['B']['t'] > -1)
        print('move', name, v, flush=True)
    return res


def land_test(by, TS, raw, loc, tk):
    homes = M.player_homes(by)
    res = {}
    cache = {}
    def events(years):
        k = tuple(years)
        if k in cache: return cache[k]
        Xl, ev, ch, info = M.land_events(by, TS, raw, loc, years, homes)
        E = np.zeros((len(Xl), 1)); i = 0
        for y in years:
            if y + 1 not in by: continue
            nxt = {r['pid']: r for r in by[y + 1]}
            teams = sorted({r['team'] for r in by[y + 1]})
            for r in by[y]:
                n = nxt.get(r['pid'])
                if not n or n['team'] == r['team'] or (r['min_per'] or 0) <= 0: continue
                for t in teams:
                    if t == r['team']: continue
                    E[i, 0] = tk.get((y, t), 0.0); i += 1
        assert i == len(Xl)
        cache[k] = (Xl, E, ev, ch, info); return cache[k]
    folds = {'A': (range(2022, 2025), [2025]), 'B': (range(2022, 2024), [2024])}
    for fold, (fit, test) in folds.items():
        Xa, Ea, eva, cha, _ = events(list(fit)); Xt, Et, evt, cht, info = events(list(test))
        lp = {}
        for extra in (False, True):
            b = M.clogit(np.c_[Xa, Ea] if extra else Xa, eva, cha, lam=1.0)
            p = M.clogit_p(np.c_[Xt, Et] if extra else Xt, evt, b)
            lp[extra] = np.log(p[cht == 1] + 1e-12)
            if extra: coef = round(float(b[-1]), 3)
        pr = H.paired(-lp[True], -lp[False], np.array([x[2] for x in info]))
        res[fold] = {'llBase': round(float(lp[False].mean()), 4), 'll': round(float(lp[True].mean()), 4), 't': round(-float(pr['t']), 2), 'n': int(pr['n']), 'coef': coef}
    res['pass'] = bool(res['A']['t'] >= 2 and res['B']['t'] > -1)
    print('land L1 dest_k', res, flush=True)
    return res


def main():
    by = M.player_rows(write=False)
    for y, rs in by.items():
        for r in rs: M.CONF[(y, r['team'])] = r['conf']
    TS, bt = M.team_seasons()
    loc = M.geo(bt)
    raw, _ = M.coaches()
    X, tk = pay(by)
    out = {'move': move_test(by, TS, raw, X, dect_of()), 'land': {'L1 dest_k': land_test(by, TS, raw, loc, tk)}}
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
