#!/usr/bin/env python3
"""Kickoff time in college football: night, noon (local), late (10 PM ET+) and weekday games, on margins and totals.

    python3 scripts/cfb_espn_hist.py 2015 2025    # first: ESPN scores and closes (free, cached)
    python3 scripts/cfb_sched_research.py         # writes data/cfb_sched_research.json (numpy; ~1 min)

The live game model (scripts/cfb_model.mjs) can only be walked on the CFBD research dump, so margins are tested on
the ESPN-history Elo model (scripts/cfb_elo_research.py, its best variant): Elo gap, home, FBS side, plus the
candidate, each season fit on the seasons before; 2016-20 tunes, 2021-25 is held out, keep at paired t <= -1.5 and
not worse held out. Every input is also put against the closing line (result minus close, by block), which is the
test that matters for picks and for a model that already trails the close. Totals are tested against the closing
total only (the history has no totals model). Body clock, bye and short week failed earlier (cfb-game-model-audit).
"""
import datetime as dt
import json
import math
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cfb_elo_research as E
from cbb_venues import tz_of

OUT = os.path.join(E.ROOT, 'data', 'cfb_sched_research.json')
LOC = json.load(open(os.path.join(HERE, 'geo', 'team_loc.json')))
ET = ZoneInfo('America/New_York')
r4 = lambda x: round(float(x), 4)


def close_total(lines):
    v = [l['ou'] for l in lines if 'Live' not in (l.get('prov') or '') and l.get('prov') != 'consensus' and l.get('ou')]
    return float(np.median(v)) if v else None


def coef(Xm, y, names):
    b = np.linalg.lstsq(Xm, y, rcond=None)[0]
    r = y - Xm @ b
    cov = (r @ r / (len(y) - len(b))) * np.linalg.pinv(Xm.T @ Xm)
    return {f: {'pts': round(float(v), 3), 't': round(float(v / math.sqrt(cov[i, i])), 2)} for i, (f, v) in enumerate(zip(names, b))}


def main():
    G = E.load()
    raw = {}
    for S in E.SEASONS:
        for g in json.load(open(os.path.join(E.DIR, f'games{S}.json'))):
            raw[g['id']] = g
    vs = json.load(open(os.path.join(E.ROOT, 'data', 'cfb_elo_research.json')))['variants']
    P = (vs.get('linear') or vs['early'])['params']
    F, _ = E.run_seasons(G, P)
    rows, X, Y, C, T, Sx = [], [], [], [], [], []
    for S in E.SEASONS:
        gs = [g for g in G[S]['rows'] if g['fbsGame']]
        for g, f in zip(gs, F[S]):
            t = dt.datetime.fromisoformat(g['date'].replace('Z', '+00:00')).astimezone(ET)
            eh = t.hour + t.minute / 60
            if eh < 6:                                    # past midnight ET: the previous evening
                eh += 24
            H = LOC.get(g['h'])
            loc = eh + (tz_of(H[2], H[0], H[1]) if H and not g['n'] else 0)
            if H and H[2] == 'AZ':
                loc -= 1                                  # no daylight time: Pacific clock in the fall
            home = 0.0 if g['n'] else 1.0
            sat = t.weekday() == 5 or (t.weekday() == 6 and t.hour < 6)
            x = {'night': home * (1.0 if loc >= 18 else 0.0), 'noon': home * (1.0 if loc < 13 else 0.0),
                 'late': home * (1.0 if eh >= 22 else 0.0), 'wkday': home * (0.0 if sat else 1.0)}
            tx = {'tnight': 1.0 if loc >= 18 else 0.0, 'tnoon': 1.0 if loc < 13 else 0.0,
                  'tlate': 1.0 if eh >= 22 else 0.0, 'twkday': 0.0 if sat else 1.0}
            rows.append((x, tx))
            X.append(f); Y.append(g['m']); C.append(g['close'] if g['close'] is not None else np.nan)
            ct = close_total(raw[g['id']].get('lines') or [])
            r = raw[g['id']]
            T.append((r['hp'] + r['ap'], ct if ct else np.nan)); Sx.append(S)
    X, y, C, S = np.array(X, float), np.array(Y, float), np.array(C, float), np.array(Sx)
    ty, tl = np.array([a for a, _ in T], float), np.array([b for _, b in T], float)
    tune, hold = (S >= 2016) & (S <= 2020), S >= 2021

    def wf(Xm):
        pred = np.full(len(y), np.nan)
        for s in range(2016, 2026):
            tr, te = S < s, S == s
            pred[te] = Xm[te] @ np.linalg.lstsq(Xm[tr], np.clip(y[tr], -45, 45), rcond=None)[0]
        return pred

    def cmp(p1, p0):
        e1, e0 = np.abs(p1 - y), np.abs(p0 - y)
        c = {}
        for lab, k in (('2016_20', tune), ('2021_25', hold)):
            d = e1[k] - e0[k]
            c['mae' + lab] = r4(e1[k].mean()); c['d' + lab] = r4(d.mean())
            c['t' + lab] = round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)
        c['passes'] = bool(c['t2016_20'] <= -1.5 and c['d2021_25'] <= 0)
        return c

    base = wf(X)
    ok = ~np.isnan(C)
    res = {'model': 'ESPN-history Elo (cfb_elo_research best variant) + home + FBS side', 'params': P,
           'base': {'games': int((tune | hold).sum()), 'mae2016_20': r4(np.abs(base - y)[tune].mean()),
                    'mae2021_25': r4(np.abs(base - y)[hold].mean()),
                    'close2016_20': r4(np.abs(C - y)[tune & ok].mean()), 'close2021_25': r4(np.abs(C - y)[hold & ok].mean())}}
    names = ['night', 'noon', 'late', 'wkday']
    M = {}
    for c in names:
        v = np.array([x[c] for x, _ in rows])
        X1 = np.column_stack([X, v])
        M[c] = cmp(wf(X1), base)
        M[c]['games'] = int((v != 0).sum())
        M[c]['effect'] = coef(X1[S >= 2016], y[S >= 2016], ['elo', 'home', 'fbs', c])[c]
        for lab, k in (('2016_20', tune), ('2021_25', hold)):
            kk = k & ok
            Z = np.column_stack([np.ones(kk.sum()), v[kk]])
            M[c]['vsClose' + lab] = coef(Z, (y - C)[kk], ['one', c])[c]
        print(c, M[c], flush=True)
    res['margin'] = M
    T_ = {}
    okt = ~np.isnan(tl)
    for c in ('tnight', 'tnoon', 'tlate', 'twkday'):
        v = np.array([tx[c] for _, tx in rows])
        T_[c] = {'games': int((v != 0).sum())}
        for lab, k in (('2016_20', tune), ('2021_25', hold)):
            kk = k & okt
            Z = np.column_stack([np.ones(kk.sum()), v[kk]])
            T_[c]['vsClose' + lab] = coef(Z, (ty - tl)[kk], ['one', c])[c]
        print(c, T_[c], flush=True)
    res['totals'] = T_
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
