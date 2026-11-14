#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Transfer + coaching watch, College Basketball: pre-registered destination and hot-seat tests
(/mnt/project-files/transfer-watch/prereg.md), on top of scripts/cbb_market_fit.py's live models.

    python3 scripts/research/xfer_watch_cbb.py    # -> data/xfer_watch_research.json ("cbb")

Destination (conditional logit over every D-I team, NIL-era moves): fold A fits 2022-24 and scores 2025->26, fold B
fits 2023-25 and scores 2022->23. Terms: D1 temperature, D2 ex-coach reunion, D4 positional open minutes,
D5 three-point style fit. Hot seat: H1 pay over the level median in the vacancy model (2016-21 fit, 2022-25 held).
Also reported: top-1 reliability (mean predicted p of the model's top school vs its hit rate).
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
sys.path.insert(0, os.path.dirname(HERE))
import cbb_market_fit as M  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'data', 'xfer_watch_research.json')


def extras():
    """(pid, year) -> position group (G guard / W wing / B big) and three-point attempt rate, from the research CSV"""
    out = {}
    if not os.path.exists(M.CSV):
        return out
    for r in csv.DictReader(open(M.CSV)):
        y = int(r['year'])
        if y < 2014:
            continue
        g = 'B' if r['big'] == '1.0' else 'G' if r['guard'] == '1.0' else 'W'
        out[(int(r['pid']), y)] = (g, M.fnum(r['tpar']))
    return out


def events(by, TS, raw, loc, X5, years):
    """M.land_events plus the pre-registered extras per row: reunion, open minutes at his group, style fit"""
    X, ev, ch, info = [], [], [], []
    e = 0
    # career: pid -> [(year, team)]
    car = defaultdict(list)
    for y, rs in by.items():
        for r in rs:
            car[r['pid']].append((y, r['team']))
    for y in years:
        if y + 1 not in by:
            continue
        nxt = {r['pid']: r for r in by[y + 1]}
        teams = sorted({r['team'] for r in by[y + 1]})
        conf = {r['team']: r['conf'] for r in by[y + 1]}
        T = defaultdict(list)
        for r in by[y]:
            T[r['team']].append(r)
        open_, openg, tpr = {}, {}, {}
        for t, ps in T.items():
            tot = sum((r['min_per'] or 0) for r in ps) or 1
            open_[t] = sum((r['min_per'] or 0) for r in ps if (nxt.get(r['pid']) or {}).get('team') != t) / tot
            g = defaultdict(lambda: [0.0, 0.0])
            a = b = 0.0
            for r in ps:
                x = X5.get((r['pid'], y)); m = r['min_per'] or 0
                if not x:
                    continue
                g[x[0]][1] += m
                if (nxt.get(r['pid']) or {}).get('team') != t:
                    g[x[0]][0] += m
                if x[1] is not None:
                    a += m * x[1]; b += m
            openg[t] = {k: v[0] / v[1] for k, v in g.items() if v[1] > 0}
            tpr[t] = a / b if b else None
        tv = np.array([v for v in tpr.values() if v is not None]); tmu, tsd = tv.mean(), tv.std()
        pv = np.array([X5[(r['pid'], y)][1] for r in by[y] if X5.get((r['pid'], y)) and X5[(r['pid'], y)][1] is not None and (r['min_per'] or 0) >= 20])
        pmu, psd = pv.mean(), pv.std()
        coach_y1 = {t: v['coach'] for t, v in raw.get(y + 1, {}).items()}
        coach_y = {t: v['coach'] for t, v in raw.get(y, {}).items()}
        for r in by[y]:
            n = nxt.get(r['pid'])
            if not n or n['team'] == r['team'] or (r['min_per'] or 0) <= 0:
                continue
            o = r['team']
            x5 = X5.get((r['pid'], y))
            grp = x5[0] if x5 else None
            ptz = (x5[1] - pmu) / psd if x5 and x5[1] is not None and (r['min_per'] or 0) >= 20 else 0.0
            past = {raw.get(yy, {}).get(tt, {}).get('coach') for yy, tt in car[r['pid']] if yy < y} - {None}
            for t in teams:
                if t == o:
                    continue
                follow = coach_y.get(o) is not None and coach_y1.get(t) == coach_y.get(o)
                base = M.feats_land(r, o, t, TS.get((y, t), {}).get('srs'), TS.get((y, o), {}).get('srs'), r['conf'], conf.get(t), loc.get(o), loc.get(t),
                                    follow, coach_y.get(t) is not None and coach_y1.get(t) is not None and coach_y.get(t) != coach_y1.get(t), open_.get(t, 0.5))
                reun = float(not follow and coach_y1.get(t) in past)
                og = openg.get(t, {}).get(grp, open_.get(t, 0.5)) if grp else open_.get(t, 0.5)
                sty = ((tpr[t] - tmu) / tsd if tpr.get(t) is not None else 0.0) * ptz
                X.append(base + [reun, og, sty])
                ev.append(e); ch.append(1 if t == n['team'] else 0)
            info.append((y, r['pid'], o, n['team']))
            e += 1
    return np.array(X, float), np.array(ev), np.array(ch), info


EXTRA = {'reunion': 12, 'open_pos': 13, 'style3': 14}


def per_event_ll(X, ev, ch, b):
    p = M.clogit_p(X, ev, b)
    starts = np.r_[0, np.flatnonzero(np.diff(ev)) + 1]
    return np.log(p[ch == 1] + 1e-12), p, starts


def paired(a, b):
    d = a - b
    return {'ll': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'n': len(d)}


def temp_fit(X, ev, ch, b):
    best = (None, -1e18)
    for tau in np.arange(0.5, 1.81, 0.02):
        ll = per_event_ll(X, ev, ch, b * tau)[0].sum()
        if ll > best[1]:
            best = (float(tau), ll)
    return best[0]


def reliability(p, ev, ch, starts):
    top, hit = [], []
    for i, s0 in enumerate(starts):
        s1 = starts[i + 1] if i + 1 < len(starts) else len(ev)
        pp = p[s0:s1]; j = int(np.argmax(pp))
        top.append(pp[j]); hit.append(ch[s0 + j])
    top, hit = np.array(top), np.array(hit)
    bins = [(0, .05), (.05, .1), (.1, .2), (.2, .35), (.35, 1.01)]
    return {'meanTop': round(float(top.mean()), 3), 'hitTop': round(float(hit.mean()), 3),
            'bins': [[a, b, round(float(top[(top >= a) & (top < b)].mean()), 3), round(float(hit[(top >= a) & (top < b)].mean()), 3), int(((top >= a) & (top < b)).sum())]
                     for a, b in bins if ((top >= a) & (top < b)).sum()]}


def fold(by, TS, raw, loc, X5, fit_years, test_years, cache):
    key = (tuple(fit_years), tuple(test_years))
    Xa, eva, cha, _ = cache.get(tuple(fit_years)) or events(by, TS, raw, loc, X5, fit_years)
    Xt, evt, cht, it_ = cache.get(tuple(test_years)) or events(by, TS, raw, loc, X5, test_years)
    cache[tuple(fit_years)] = (Xa, eva, cha, None); cache[tuple(test_years)] = (Xt, evt, cht, it_)
    nb = 12
    b0 = M.clogit(Xa[:, :nb], eva, cha, lam=1.0)
    ll0, p0, st = per_event_ll(Xt[:, :nb], evt, cht, b0)
    res = {'base': {'llPerMove': round(float(ll0.mean()), 4), 'n': len(ll0), 'top1': reliability(p0, evt, cht, st)}}
    tau = temp_fit(Xa[:, :nb], eva, cha, b0)
    llt, pt, _ = per_event_ll(Xt[:, :nb], evt, cht, b0 * tau)
    res['D1_temperature'] = {'tau': round(tau, 2), **paired(llt, ll0), 'top1': reliability(pt, evt, cht, st)}
    for name, k in EXTRA.items():
        cols = list(range(nb)) + [k]
        b = M.clogit(Xa[:, cols], eva, cha, lam=1.0)
        ll, _, _ = per_event_ll(Xt[:, cols], evt, cht, b)
        res[name] = {'coef': round(float(b[-1]), 3), **paired(ll, ll0), 'rate': round(float(Xt[cht == 1, k].mean()), 4), 'rateAll': round(float(Xt[:, k].mean()), 4)}
    return res, b0, (Xt, evt, cht, it_)


def vac_pay(TS, raw, miss):
    """H1: vacancy model + log(pay / level median) (public schools with USA Today pay that season, else 0 + a flag)"""
    src = json.load(gzip.open(M.SRC))['pay']
    names = {t for (_, t) in TS}
    pay = {}
    for r in src['list']:
        t = M.match_team(r['school'], names)
        if t:
            for y, cid, nm, v in src['schools'].get(r['sid'], []):
                if v:
                    pay[(y, t)] = v
    rows = M.vac_rows(TS, raw, miss)
    med = {}
    for (y, t), v in pay.items():
        med.setdefault((y, M.conf_of(y, t) in M.P6), []).append(v)
    med = {k: float(np.median(v)) for k, v in med.items()}
    F = M.VAC_F
    live = json.load(open(M.OUT))['vacancy']['feats']
    keep = [F.index(f) for f in live]

    def design(rs, extra):
        out = []
        for (y, f, lab, t, c) in rs:
            # pay for the season just played (y), known before the hire decision that follows it
            v = pay.get((y, t)) or pay.get((y + 1, t))
            m = med.get((y, M.conf_of(y, t) in M.P6))
            pr = math.log(v / m) if v and m else 0.0
            out.append([f[k] for k in keep] + ([pr, float(not (v and m))] if extra else []))
        return np.array(out, float)
    tr = [x for x in rows if 2016 <= x[0] <= 2021]
    te = [x for x in rows if 2022 <= x[0] <= 2025]
    res = {'nPaid': sum(1 for x in te if pay.get((x[0], x[3])) or pay.get((x[0] + 1, x[3])))}
    yt = np.array([x[2] for x in tr]); ye = np.array([x[2] for x in te])
    lls = {}
    for extra in (False, True):
        Xa, Xe = design(tr, extra), design(te, extra)
        cols = [i for i in range(Xa.shape[1]) if Xa[:, i].std() > 0]
        Xa, Xe = Xa[:, cols], Xe[:, cols]
        mu, sd = Xa.mean(0), Xa.std(0)
        B = M.mnl((Xa - mu) / sd, yt, 3, lam=1.0)
        P = M.mnl_p((Xe - mu) / sd, B)
        lls[extra] = np.log(P[np.arange(len(ye)), ye] + 1e-12)
        if extra:
            res['coefOut'] = round(float(B[1][-2]), 3); res['coefMoved'] = round(float(B[0][-2]), 3)
    res.update(paired(lls[True], lls[False]))
    return res


def main():
    by = M.player_rows()
    for y, rs in by.items():
        for r in rs:
            M.CONF[(y, r['team'])] = r['conf']
    TS, bt = M.team_seasons()
    loc = M.geo(bt)
    raw, miss = M.coaches()
    X5 = extras()
    print('extras', len(X5), flush=True)
    cache = {}
    A, bA, held = fold(by, TS, raw, loc, X5, range(2022, 2025), [2025], cache)
    print('fold A', json.dumps(A), flush=True)
    Bf, _, _ = fold(by, TS, raw, loc, X5, range(2023, 2026), [2022], cache)
    print('fold B', json.dumps(Bf), flush=True)
    H1 = vac_pay(TS, raw, miss)
    print('H1', H1, flush=True)
    gate = {}
    for k in ['D1_temperature'] + list(EXTRA):
        a, b = A[k], Bf[k]
        gate[k] = {'pass': a['ll'] > 0 and a['t'] >= 2 and not (b['ll'] < 0 and b['t'] <= -1), 'A': [a['ll'], a['t']], 'B': [b['ll'], b['t']]}
    gate['H1_pay'] = {'pass': H1['ll'] > 0 and H1['t'] >= 2, 'held': [H1['ll'], H1['t']]}
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    res['cbb'] = {'foldA': A, 'foldB': Bf, 'H1': H1, 'gate': gate}
    json.dump(res, open(OUT, 'w'), indent=1)
    print('gate', json.dumps(gate))


if __name__ == '__main__':
    main()
