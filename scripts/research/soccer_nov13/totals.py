#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Market totals ratings: each club's lean on total goals, learned from the closing over/under 2.5 price of its
earlier league matches (never the match's own), as the 1X2 market ratings learn the gap between the sides. The
match's projected total = the league's market total x both clubs' leans; the game model's split between the sides is
kept. Scored on over 2.5 log loss against the live projection (model goals x the league's scoring level)."""
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine as E
import soccer_data as D
import soccer_games as G

TT = np.add.outer(np.arange(G.GMAX), np.arange(G.GMAX))
_C = {}


def o25(lh, la, rho):
    k = (round(lh, 3), round(la, 3))
    v = _C.get(k)
    if v is None:
        v = _C[k] = float(G.score_matrix(k[0], k[1], rho)[TT > 2.5].sum())
    return v


def ou_close(r):
    for k in ('ouc', 'oubc', 'ouac'):
        o = r.get(k)
        if o and o[0] > 1 and o[1] > 1:
            a, b = 1 / o[0], 1 / o[1]
            if 1.0 <= a + b <= 1.15:
                return a / (a + b)
    return None


_MU = None


def mu_of(p):
    """total goals whose Poisson chance of 3 or more is p"""
    global _MU
    if _MU is None:
        g = np.arange(0.8, 6.0, 0.005)
        _MU = (g, 1 - np.exp(-g) * (1 + g + g * g / 2))
    return float(np.interp(p, _MU[1], _MU[0]))


def collect(rows, P, kt=0.15, kb=0.02, car=1.0, lgs=None, rel=1.0):
    """walk forward: per scored match, the live projection's over chance, the totals-rating one, the close's"""
    lgs = lgs or D.BIG5
    tau = defaultdict(float)
    base = {}
    seen = {}
    lev_n = defaultdict(float); lev_d = defaultdict(float)     # the live scoring level, kept walk-forward here
    out = []
    pend = {}

    def score(r, S, lh, la, R):
        if r['lg'] not in lgs or r['st'] != 'FT':
            return
        lg = r['lg']
        for t in (r['h'], r['a']):
            if seen.get(t) != S:
                seen[t] = S
                tau[t] *= car
        # the live rule (soccer_games.level): big five only, 1 elsewhere
        f = lev_n[lg] / lev_d[lg] if lg in D.BIG5 and lev_d[lg] > 0 and lev_s.get(lg, S) < S else 1.0
        pc = ou_close(r)
        rec = {'S': S, 'day': r['day'], 'lg': lg, 'y': int(r['hs'] + r['as'] > 2), 'c': pc,
               'p0': o25(lh * f, la * f, P['rho']), 'lh': lh, 'la': la, 'f': f}
        own = rel * math.log((lh + la) * f)
        if lg in base:
            mu = math.exp(own + base[lg] + tau[r['h']] + tau[r['a']])
            k = mu / (lh + la)
            rec['p1'] = o25(lh * k, la * k, P['rho'])
            rec['mu'] = mu
        out.append(rec)
        if pc is not None:
            m = math.log(mu_of(min(0.95, max(0.05, pc))))
            if lg not in base:
                base[lg] = m - own
            e = m - (own + base[lg] + tau[r['h']] + tau[r['a']])
            pend[r['id']] = e
        cur[(lg, S)][0] += lh + la
        cur[(lg, S)][1] += r['hs'] + r['as']

    cur = defaultdict(lambda: [0.0, 0.0])
    lev_s = {}

    def keep(r, R):
        e = pend.pop(r['id'], None)
        if e is not None:
            tau[r['h']] += kt * e
            tau[r['a']] += kt * e
            base[r['lg']] += kb * e
    # the level: finished seasons only (as soccer_games.level)
    done = set()
    R = G.Ratings(P)
    R.set_membership(rows)
    for r in rows:
        if r.get('hs') is None:
            continue
        R.prep(r)
        if r['lg'] in G.SCORED and r['st'] == 'FT':
            S = D.season_of(r['day'], r['lg'])
            if S >= G.SCORE_FROM:
                lg = r['lg']
                for (l2, s2) in list(cur):
                    if l2 == lg and s2 < S and (l2, s2) not in done:
                        done.add((l2, s2))
                        lev_d[lg] += cur[(l2, s2)][0]; lev_n[lg] += cur[(l2, s2)][1]
                        lev_s[lg] = s2
                lh, la = R.lambdas(r)
                score(r, S, lh, la, R)
        R.update(r)
        keep(r, R)
    return out


def bll(p, y):
    p = min(1 - 1e-6, max(1e-6, p))
    return -math.log(p if y else 1 - p)


def report(out, lo, hi, tag=''):
    v = [o for o in out if lo <= o['S'] <= hi and 'p1' in o and o['c'] is not None]
    if not v:
        return None
    a = [bll(o['p1'], o['y']) for o in v]; b = [bll(o['p0'], o['y']) for o in v]; c = [bll(o['c'], o['y']) for o in v]
    d = [x - y for x, y in zip(a, b)]
    t = G.cl_t(d, [o['day'] for o in v])
    by = defaultdict(list)
    for o, x in zip(v, d):
        by[o['S']].append(x)
    res = {'n': len(v), 'live': round(sum(b) / len(v), 5), 'ratings': round(sum(a) / len(v), 5),
           'close': round(sum(c) / len(v), 5), 'd': round(sum(d) / len(v), 5), 't': t,
           'seasons': f"{sum(sum(x) < 0 for x in by.values())}/{len(by)}"}
    print(tag, lo, hi, res, flush=True)
    return res


OU_LGS = ('eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'eng.2', 'esp.2', 'ger.2', 'ita.2', 'fra.2', 'ned.1', 'por.1',
          'bel.1', 'tur.1', 'gre.1', 'sco.1')
PRE = {'rel': 0.77, 'kt': 0.03, 'kb': 0.06}


def draw_test(recs, lo, hi, th=0.06, w=0.15):
    rho = G.params()['rho']

    def pr(r, th):
        pw, pd, pl = G.wdl(r['lh'], r['la'], rho)
        pd2 = pd * math.exp(th * max(0.0, 1 - abs(pw - pl) / w))
        s = pw + pd2 + pl
        return pw / s, pd2 / s, pl / s
    v = [r for r in recs if lo <= r['S'] <= hi]
    d = [-math.log(pr(r, th)[1 - r['res']]) + math.log(pr(r, 0.0)[1 - r['res']]) for r in v]
    by = defaultdict(float)
    for r, x in zip(v, d):
        by[r['S']] += x
    return {'n': len(v), 'd': round(sum(d) / len(v), 6), 't': G.cl_t(d, [r['day'] for r in v]),
            'seasons': f"{sum(x < 0 for x in by.values())}/{len(by)}"}


if __name__ == '__main__':
    import json
    import pickle
    rows = E.load_rows()
    P = G.params()
    G.SCORED = set(G.SCORED) | set(OU_LGS)
    lo, hi = (2023, 2026) if '--held' in sys.argv else (2021, 2022)
    res = {'split': [lo, hi], 'pre': PRE}
    out = collect(rows, P, PRE['kt'], PRE['kb'], rel=PRE['rel'], lgs=set(OU_LGS))
    out0 = collect(rows, P, 0.0, PRE['kb'], rel=PRE['rel'], lgs=set(OU_LGS))
    res['T'] = report(out, lo, hi, 'all 16')
    res['T_big5'] = report([o for o in out if o['lg'] in D.BIG5], lo, hi, 'big five')
    res['T_other'] = report([o for o in out if o['lg'] not in D.BIG5], lo, hi, 'other 11')
    res['T_league_only'] = report(out0, lo, hi, 'league level only (kt 0)')
    v = [(a, b) for a, b in zip(out, out0) if lo <= a['S'] <= hi and 'p1' in a and a['c'] is not None]
    d = [bll(a['p1'], a['y']) - bll(b['p1'], b['y']) for a, b in v]
    res['T_club_vs_league'] = {'d': round(sum(d) / len(d), 6), 't': G.cl_t(d, [a['day'] for a, _ in v])}
    print('club leans vs league only', res['T_club_vs_league'])
    if os.environ.get('SHADOW_PKL'):
        res['D'] = draw_test(pickle.load(open(os.environ['SHADOW_PKL'], 'rb')), lo, hi)
        print('draw boost', res['D'])
    json.dump(res, open(os.path.join(HERE, 'held.json' if '--held' in sys.argv else 'tune.json'), 'w'), indent=1)
