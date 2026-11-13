#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research engine for the soccer game model sweep: soccer_games.Ratings with optional pieces switched on by params.

    kq > 0     market side ratings ('m', 'n') from a Kalman filter on log market goals instead of the fixed-gain walk
    stk        late-season stakes: clubs with a table boundary still in reach, home minus away
    mve        squad market value weight raised in a season's first matches
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

PKL = os.environ.get('SOCCER_ROWS_PKL', '')


def load_rows():
    if PKL and os.path.exists(PKL):
        return pickle.load(open(PKL, 'rb'))
    rows = G.add_inj(G.add_mv(G.add_market(D.load(G.HIST))))
    if PKL:
        pickle.dump(rows, open(PKL, 'wb'))
    return rows


class KF:
    """one league's market ratings: state = [env, hfa, a_1, d_1, a_2, d_2, ...] (log goals), a random walk in time,
    observed through each match's two market-implied goal means"""

    def __init__(self, P):
        self.P = P
        self.ix = {}
        self.x = np.zeros(2)
        self.x[1] = 0.25
        self.C = np.diag([0.02, 0.02])
        self.last = {}
        self.day0 = None

    def add(self, t, a, d, v):
        if t in self.ix:
            i = self.ix[t]
            self.C[i:i + 2, :] = 0.0
            self.C[:, i:i + 2] = 0.0
        else:
            i = len(self.x)
            self.ix[t] = i
            self.x = np.concatenate([self.x, [0.0, 0.0]])
            C = np.zeros((i + 2, i + 2))
            C[:i, :i] = self.C
            self.C = C
        self.x[i], self.x[i + 1] = a, d
        self.C[i, i] = self.C[i + 1, i + 1] = v

    def age(self, t, ord_):
        i = self.ix[t]
        l = self.last.get(t)
        if l is not None and ord_ > l:
            dq = self.P['kq'] * min(ord_ - l, 60)
            self.C[i, i] += dq
            self.C[i + 1, i + 1] += dq
        self.last[t] = ord_

    def summer(self, teams):
        qs = self.P['kqs']
        for t in teams:
            i = self.ix.get(t)
            if i is not None:
                self.C[i, i] += qs
                self.C[i + 1, i + 1] += qs

    def update(self, h, a, zh, za, ord_):
        self.age(h, ord_)
        self.age(a, ord_)
        if self.day0 is not None and ord_ > self.day0:
            self.C[0, 0] += self.P['kqe'] * (ord_ - self.day0)
            self.C[1, 1] += self.P['kqe'] * (ord_ - self.day0)
        self.day0 = ord_
        ih, ia = self.ix[h], self.ix[a]
        n = len(self.x)
        H = np.zeros((2, n))
        H[0, 0] = 1; H[0, 1] = 1; H[0, ih] = 1; H[0, ia + 1] = -1
        H[1, 0] = 1; H[1, ia] = 1; H[1, ih + 1] = -1
        y = np.array([zh, za]) - H @ self.x
        CH = self.C @ H.T
        S = H @ CH + np.eye(2) * self.P['kr']
        K = CH @ np.linalg.inv(S)
        self.x = self.x + K @ y
        C = self.C - K @ CH.T
        self.C = (C + C.T) / 2


class R2(G.Ratings):
    def __init__(self, P):
        super().__init__(P)
        self.kf = {k: {} for k in ('m', 'n')}
        self.old = {}                      # club -> (league, absolute market attack, defence) when it left a league
        self.tab = {}                      # (league, season) -> club -> [points, played]
        self.eu = defaultdict(float)       # club -> its own lean in cross-league (UEFA) matches, log goals each way
        self.lsp = defaultdict(float)      # league -> stretch of its clubs' ratings in cross-league matches
        self.size = {}

    # ---- stakes
    def set_membership(self, rows):
        super().set_membership(rows)
        c = defaultdict(lambda: defaultdict(int))
        for r in rows:
            if r['lg'] in D.BIG5:
                S = D.season_of(r['day'], r['lg'])
                c[(r['lg'], S)][r['h']] += 1
                c[(r['lg'], S)][r['a']] += 1
        self.sched = {k: dict(v) for k, v in c.items()}

    def stake(self, r):
        """(home, away) 1 if the club can still cross a table boundary (title, top four, top six, the drop) or be
        caught across one, else 0; None outside the big five or before every club has played half its matches"""
        lg = r['lg']
        if lg not in D.BIG5:
            return None
        S = D.season_of(r['day'], lg)
        T = self.tab.get((lg, S))
        sch = self.sched.get((lg, S))
        if not T or not sch or len(T) < len(sch):
            return None
        N = len(sch)
        order = sorted(T, key=lambda t: -T[t][0])
        pts = [T[t][0] for t in order]
        left = {t: sch[t] - T[t][1] for t in T}
        bounds = (1, 4, 6, N - 3)
        out = []
        for t in (r['h'], r['a']):
            if t not in T:
                return None
            p, g = T[t][0], left[t]
            rk = order.index(t) + 1
            live = 0
            for b in bounds:
                if rk <= b:
                    # can the first club below the line catch it?
                    ch = order[b]
                    if pts[b] + 3 * left[ch] >= p:
                        live = 1
                else:
                    if p + 3 * g >= pts[b - 1]:
                        live = 1
            out.append(live)
        return out

    def note_table(self, r):
        if r['lg'] in D.BIG5:
            S = D.season_of(r['day'], r['lg'])
            T = self.tab.setdefault((r['lg'], S), {})
            hp = 3 if r['hs'] > r['as'] else 1 if r['hs'] == r['as'] else 0
            ap = 3 if r['as'] > r['hs'] else 1 if r['hs'] == r['as'] else 0
            for t, p in ((r['h'], hp), (r['a'], ap)):
                e = T.setdefault(t, [0, 0])
                e[0] += p; e[1] += 1

    # ---- Kalman market ratings
    def move(self, t, L):
        old = self.lg.get(t)
        if old is not None and old != L and self.P.get('kq'):
            for k in ('m', 'n'):
                e = self.sub[k]
                if t in e['has']:
                    self.old[(k, t)] = (old, self.s[old] + e['a'][t] + self.env[old] / 2,
                                        self.s[old] + e['d'][t] - self.env[old] / 2)
        super().move(t, L)

    def rollover(self, L, S):
        first = (L, S) not in self.rolled
        super().rollover(L, S)
        if first and self.P.get('kq'):
            for k in ('m', 'n'):
                f = self.kf[k].get(L)
                if f:
                    f.summer([t for t, l in self.lg.items() if l == L])
                    # the base class recentred and scaled e['a'], e['d']: write them back into the filter
                    e = self.sub[k]
                    for t, i in f.ix.items():
                        if t in e['has']:
                            f.x[i], f.x[i + 1] = e['a'][t], e['d'][t]

    def lambdas(self, r):
        P = self.P
        add = 0.0
        if P.get('mve'):
            nb = P.get('mvn', P['nb'])
            e = max(0.0, 1 - min(self.n[r['h']], self.n[r['a']]) / nb)
            add += P['mve'] * e * r.get('mvz', 0.0)
        if P.get('stk'):
            s = self.stake(r)
            if s:
                add += P['stk'] * (s[0] - s[1])
        if P.get('keu') and r['lg'] in D.EURO:
            add += self.eu[r['h']] - self.eu[r['a']]
        if not add:
            return super().lambdas(r)
        lh, la = super().lambdas(r)
        sp = P.get('sp', 1.0)
        return lh * math.exp(add * sp), la * math.exp(-add * sp)

    def update(self, r):
        P = self.P
        if P.get('keu') and r['lg'] in D.EURO and r.get('hs') is not None:
            lh, la = self.lambdas(r)
            span = 4 / 3 if r['st'] in ('AET', 'PEN') else 1.0
            e = (min(r['hs'], 6) - span * lh) - (min(r['as'], 6) - span * la)
            self.eu[r['h']] += P['keu'] * e
            self.eu[r['a']] -= P['keu'] * e
        if not P.get('kq'):
            super().update(r)
            self.note_table(r)
            return
        h, a = r['h'], r['a']
        Lh, La = self.lg.get(h, 'x'), self.lg.get(a, 'x')
        # the base update with the market side ratings held out, then the filter's own
        hold = {}
        for k in ('m', 'n'):
            oh, oa = G.SUBS[k]
            if r.get(oh) is not None:
                hold[k] = (r[oh], r[oa])
                r[oh] = None
        super().update(r)
        for k, v in hold.items():
            oh, oa = G.SUBS[k]
            r[oh], r[oa] = v
        if Lh == La:
            ord_ = D_ord(r['day'])
            for k, (mh, ma) in hold.items():
                e = self.sub[k]
                f = self.kf[k].get(Lh)
                if f is None:
                    f = self.kf[k][Lh] = KF(P)
                for t in (h, a):
                    if t not in e['has']:
                        e['has'].add(t)
                        A, Dd, v = self.a[t], self.d[t], P['kv0']
                        o = self.old.pop((k, t), None)
                        if o and P.get('kcar'):
                            A = o[1] - self.s[Lh] - self.env[Lh] / 2
                            Dd = o[2] - self.s[Lh] + self.env[Lh] / 2
                            v = P['kv1']
                        f.add(t, A, Dd, v)
                        f.last[t] = ord_
                    elif t not in f.ix:
                        f.add(t, e['a'][t], e['d'][t], P['kv0'])
                        f.last[t] = ord_
                f.update(h, a, math.log(max(mh, 0.05)) - G.M0, math.log(max(ma, 0.05)) - G.M0, ord_)
                for t in (h, a):
                    i = f.ix[t]
                    e['a'][t], e['d'][t] = float(f.x[i]), float(f.x[i + 1])
                e['env'][Lh], e['hfa'][Lh] = float(f.x[0]), float(f.x[1])
        self.note_table(r)


_ORD = {}


def D_ord(day):
    v = _ORD.get(day)
    if v is None:
        import datetime as dt
        v = _ORD[day] = dt.date.fromisoformat(day).toordinal()
    return v


G.Ratings = R2
KP = {'kq': 0.0, 'kqs': 0.01, 'kqe': 1e-6, 'kr': 0.001, 'kv0': 0.09, 'kv1': 0.03, 'kcar': 0}
