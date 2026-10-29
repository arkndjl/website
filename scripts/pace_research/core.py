"""shared pieces for the pace research: walk-forward pace ratings and the stack tests against the close"""
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import harness as H

# downloads and results (gitignored cache); run every script from this folder
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.cache', 'pace') + '/'
import os
os.makedirs(OUT, exist_ok=True)


class Pace:
    """opponent-adjusted pace: game events = lg + r[h] + r[a], each team's r an exponentially weighted mean of the
    game's events minus the league and the opponent, halved (both teams share the game). hl in games; carry: the
    fraction of r kept into a new season; recent: a second, fast copy for the trend"""

    def __init__(self, hl=10, carry=0.5, lg0=None, lg_hl=400):
        self.a = 0.5 ** (1 / hl)
        self.carry = carry
        self.r = defaultdict(float)
        self.n = defaultdict(float)
        self.lg = lg0
        self.lga = 0.5 ** (1 / lg_hl)
        self.S = None
        self.fast = defaultdict(float)
        self.v = defaultdict(lambda: [0.0, 0.0])  # each team's game-event variance (sum w x dev^2, sum w)

    def season(self, S):
        if S != self.S:
            if self.S is not None:
                for t in list(self.r):
                    self.r[t] *= self.carry
                    self.n[t] = min(self.n[t], 3.0)
                    self.fast[t] *= self.carry
            self.S = S

    def exp(self, h, a):
        return (self.lg or 0.0) + self.r[h] + self.r[a]

    def add(self, h, a, x):
        if x is None:
            return
        if self.lg is None:
            self.lg = x
        dev = x - self.exp(h, a)
        for t in (h, a):
            w = 1 - self.a
            self.r[t] += w * dev / 2 * 1.0
            self.fast[t] += 0.3 * (x - self.lg - self.fast[t] - (self.r[a if t == h else h]))
            vv = self.v[t]
            vv[0] = vv[0] * self.a + dev * dev
            vv[1] = vv[1] * self.a + 1
            self.n[t] += 1
        self.lg = self.lg * self.lga + x * (1 - self.lga)

    def sd(self, t):
        v = self.v[t]
        return math.sqrt(v[0] / v[1]) if v[1] > 3 else None


def walk_stack(X, y, S, first_pred, min_seasons=2):
    """OLS walk-forward by season: each season predicted from all seasons before it"""
    pred = np.full(len(y), np.nan)
    for s in sorted(set(S)):
        if s < first_pred:
            continue
        tr = (S < s) & ~np.isnan(X).any(1) & ~np.isnan(y)
        if len(set(S[tr])) < min_seasons:
            continue
        te = (S == s) & ~np.isnan(X).any(1)
        b, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        pred[te] = X[te] @ b
    return pred


def test(rows, base_cols, cand_cols, y, S, day, tune, held_from, first_pred, loss='ae'):
    """paired AE (or logloss for 0/1 y with a logit link) of the stack with the candidates vs without"""
    X0 = np.column_stack([np.ones(len(y))] + base_cols)
    X1 = np.column_stack([X0] + cand_cols)
    p0 = walk_stack(X0, y, S, first_pred)
    p1 = walk_stack(X1, y, S, first_pred)
    ok = ~np.isnan(p0) & ~np.isnan(p1) & ~np.isnan(y)
    l0, l1 = H.ae(p0, y), H.ae(p1, y)
    out = {}
    for nm, m in (('tune', ok & (S >= tune[0]) & (S <= tune[1])), ('held', ok & (S >= held_from))):
        r = H.paired(l1[m], l0[m], day[m])
        out[nm] = {'n': r['n'], 'd': round(r['d'], 4), 't': round(r['t'], 2), 'base': round(float(l0[m].mean()), 3)}
    # the full-sample coefficient for the record
    allok = ~np.isnan(X1).any(1) & ~np.isnan(y)
    b, *_ = np.linalg.lstsq(X1[allok], y[allok], rcond=None)
    out['coef'] = [round(float(v), 4) for v in b[X0.shape[1]:]]
    return out


def logit_fit(X, y, iters=25, ridge=1e-6):
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ b)))
        W = p * (1 - p)
        g = X.T @ (y - p) - ridge * b
        Hm = (X * W[:, None]).T @ X + ridge * np.eye(X.shape[1])
        b += np.linalg.solve(Hm, g)
    return b


def walk_logit(X, y, S, first_pred, min_seasons=2):
    pred = np.full(len(y), np.nan)
    for s in sorted(set(S)):
        if s < first_pred:
            continue
        tr = (S < s) & ~np.isnan(X).any(1) & ~np.isnan(y)
        if len(set(S[tr])) < min_seasons:
            continue
        te = (S == s) & ~np.isnan(X).any(1)
        b = logit_fit(X[tr], y[tr])
        pred[te] = 1 / (1 + np.exp(-(X[te] @ b)))
    return pred


def test_logit(base_cols, cand_cols, y, S, day, tune, held_from, first_pred):
    X0 = np.column_stack([np.ones(len(y))] + base_cols)
    X1 = np.column_stack([X0] + cand_cols)
    p0 = walk_logit(X0, y, S, first_pred)
    p1 = walk_logit(X1, y, S, first_pred)
    ok = ~np.isnan(p0) & ~np.isnan(p1) & ~np.isnan(y)
    l0, l1 = H.logloss(p0, y), H.logloss(p1, y)
    out = {}
    for nm, m in (('tune', ok & (S >= tune[0]) & (S <= tune[1])), ('held', ok & (S >= held_from))):
        r = H.paired(l1[m], l0[m], day[m])
        out[nm] = {'n': r['n'], 'd': round(r['d'], 5), 't': round(r['t'], 2), 'base': round(float(l0[m].mean()), 4)}
    allok = ~np.isnan(X1).any(1) & ~np.isnan(y)
    b = logit_fit(X1[allok], y[allok])
    out['coef'] = [round(float(v), 4) for v in b[X0.shape[1]:]]
    return out


def verdict(r):
    return 'PASS' if r['tune']['t'] <= -1.5 and r['held']['t'] <= 0 else 'fail'


def fmt(name, r):
    return '%-34s tune n%5d d%+.4f t%+6.2f | held n%5d d%+.4f t%+6.2f | coef %s  %s' % (
        name, r['tune']['n'], r['tune']['d'], r['tune']['t'], r['held']['n'], r['held']['d'], r['held']['t'],
        r['coef'], verdict(r))
