#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research: college basketball on/off, pairs, trios and lineups (Noah, Nov 3 2026: "test on/off as an FV driver for
college basketball and test incorporating it into XPM/VORX"; "test lineup/pair/trio FV drivers as well for CBB").

Data: scripts/cbb_lineups.py stints (NCAA play-by-play substitutions, cache scripts/.cache/cbb/lineups; 2025 = 2024-25
about half the games, 2026 = 2025-26 nearly all; nothing older), Barttorvik game logs (game BPM, minutes), the CBB kit
(/mnt/project-files/cbb/kit/college_seasons_nba.csv: Barttorvik pid -> draft, Basketball-Reference id) and the NBA
XPM pages (static/data/nba-xpm/<season>.json).

  OMP_NUM_THREADS=1 python3 scripts/cbb_onoff_research.py        # data/cbb_onoff_research.json

A. College XPM (a rating per player in points per 100 possessions, team-net units):
   box   = a x Barttorvik BPM (minutes-weighted game BPM over the training games, shrunk to b0 by m0 minutes) + HCA,
           a and HCA fit on the training stints (weighted least squares, weight = possessions)
   rapm  = box + delta, delta a ridge fit of the stint residuals (lambda in possessions): RAPM with the box prior
   oo    = box + c x shrunk raw on-off (k 600 possessions) from the training games, c .25 / .5 / 1 (fixed, not fit)
   pair / trio = rapm + ridge interaction terms for teammate pairs / trios with 100+ training possessions together
   Scored on games the fit never saw: the game margin each model gives from the stints actually played (who played,
   how long), against the real margin; MSE, paired t clustered by date. Splits: 5 random game folds inside a season,
   forward by date (train before Jan 10 -> test Jan 10 - Feb 9; before Feb 10 -> Feb 10 on), and next season
   (2025 ratings -> 2026 games; a and the newcomer level fit on half the 2026 games, scored on the other half).
   Lambda is picked on 2025 and judged on 2026. VORX (wins over replacement) is a linear map of the rating x minutes,
   so it passes or fails with the rating.
B. FV drivers (full-season values per player-season, 200+ minutes):
   oo      shrunk on-off (k 600 poss)
   rapm    delta above the box prior (lambda from A)
   pair    possession-weighted mean of his pair interaction terms; pairmax his best pair (100+ poss)
   trio    the same for trios; triomax
   unit    possession-weighted net of the 5-man units he played in, each shrunk to the team net by 150 poss, minus the
           team net; unitbest the shrunk net of his most-used unit minus the team net
   Outcomes the data reach: (1) drafted that June (2025, 2026 drafts) and the pick (-ln pick) given a box baseline
   (BPM, PRPG, age, recruit rank, height, steals, usage, power conference), fit on one season and scored on the other;
   (2) the 2025 class's NBA rookie season (2025-26 XPM shrunk to -2 by 500 MP) given -ln pick and college BPM,
   leave-one-out. The board's gate is NBA FV, so (1) alone is a lead, not a driver.

Result (Nov 3 2026; D-I vs D-I games: 2025 3,130 games / 106k stints, 2026 5,653 / 199k): nothing passes, nothing shipped.
  XPM   game-margin MSE vs box (122.6 2025, 132.0 2026, 5-fold): RAPM lambda 250 -> 64000 is worse at every lambda in
        both seasons, k-fold and forward (2026 lambda 2000 +4.0 t 7.3, 8000 +1.2 t 4.9, 64000 +.13 t 2.9; forward
        8000 +2.2 t 6.0): the error falls toward the box as lambda grows, so the best weight on on-off is zero.
        Raw on-off at c .25 / .5 / 1: +2.4 to +35 (t 5-12). Pair / trio interactions on top: worse again (pair 8000
        +3.0, trio 8000 +2.3 over box, 2026 k-fold). Next season (2025 ratings -> 2026 games): RAPM -0.18 t -0.8,
        on-off -0.04 t -0.3: flat. With all games (CBB_DI_ONLY=0, data/cbb_onoff_research_alld.json) 2026 RAPM looked
        better (-15, t -6.6) only because non-D-I opponents have no Barttorvik box prior; D-I only, the gain is gone.
        VORX is a linear map of the rating x minutes, so it fails with it.
  FV    corr with BPM: oo .25, rapm .01, pair .04, trio .02, unit .15. Drafted that June (fit one season, score the
        other): no driver lowers log loss both ways (oo +.0003 / +.0010, rapm -.0001 / +.0004). -ln pick: unitbest
        lower MSE both ways (-.038 t -2.1, -.039 t -1.1) with a negative sign (a better top unit, a later pick); the
        rest worse. NBA rookie season 2025-26 (73 players of the 2025 college season): every driver raises
        leave-one-out MSE (oo +.036 t 3.8, rapm +.035, pair +.030, trio +.028, unit +.036, unitbest +.024).
  Retest when the 2025 and 2026 classes have three NBA seasons (summer 2028), or if older NCAA play-by-play turns up.
"""
import os
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import hashlib
import json
import math
import sys
from collections import defaultdict

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve, cg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cbb_lineups as L  # noqa: E402
import cbb_lineups_research as R  # noqa: E402
import names as N  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'cbb_onoff_research.json')
if os.environ.get('CBB_DI_ONLY', '1') != '1':
    OUT = OUT.replace('.json', '_alld.json')
KIT = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit/college_seasons_nba.csv')
M0, B0 = 150.0, -1.0           # box prior: game BPM shrunk to -1 by 150 minutes (as cbb_games avail)
K_OO = 600.0
LAMS = [250, 500, 1000, 2000, 4000, 8000]
LAM_INT = [500, 2000, 8000]    # pair / trio interaction ridge
MIN_INT = 100.0                # possessions together for a pair / trio column
DI_ONLY = os.environ.get('CBB_DI_ONLY', '1') == '1'   # games between two Barttorvik (D-I) teams only


def h01(s):
    return int(hashlib.md5(str(s).encode()).hexdigest(), 16)


# ---------------------------------------------------------------- data
class Season:
    def __init__(self, S):
        self.S = S
        games = L.load(S)
        raw = R.bt_raw(S)
        roster = defaultdict(dict)
        self.box = {}                                # (bt team, date, pid) -> (min, gbpm)
        for r in raw:
            try:
                d = str(r[0]); d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
                roster[r[47]][r[51]] = dict(name=r[48], team=r[47], pid=r[51])
                mn = float(r[8] or 0)
                if mn > 0:
                    self.box[(r[47], d, r[51])] = (mn, float(r[44] or 0))
            except (IndexError, TypeError, ValueError):
                continue
        roster = {t: list(v.values()) for t, v in roster.items()}
        self.tm, self.pm = R.ncaa_to_bt(games, roster)
        G = [g for g in games.values() if 'stints' in g and g['secs'] > 1800 and None not in g['players'][g['home']] + g['players'][g['away']]
             and (not DI_ONLY or (g['home'] in self.tm and g['away'] in self.tm))]
        G.sort(key=lambda g: (g['date'], g['id']))
        self.games = G
        self.pidx = {}                               # (tid, name) -> column
        self.pkey = []
        rows = []                                    # stint rows: game index, poss, home margin, home cols, away cols
        for gi, g in enumerate(G):
            P = R.poss_of(g); secs = g['secs']
            for s in g['stints']:
                if s[0] <= 0:
                    continue
                hc = [self.col(g['home'], g['players'][g['home']][j]) for j in s[1]]
                ac = [self.col(g['away'], g['players'][g['away']][j]) for j in s[2]]
                rows.append((gi, P * s[0] / secs, s[3] - s[4], hc, ac))
        self.rows = rows
        self.sg = np.array([r[0] for r in rows])
        self.w = np.array([r[1] for r in rows])
        self.m = np.array([r[2] for r in rows], float)
        self.y = 100 * self.m / self.w
        ii, jj, vv = [], [], []
        for k, r in enumerate(rows):
            for c in r[3]:
                ii.append(k); jj.append(c); vv.append(1.0)
            for c in r[4]:
                ii.append(k); jj.append(c); vv.append(-1.0)
        self.X = sparse.csr_matrix((vv, (ii, jj)), shape=(len(rows), len(self.pkey)))
        self.gdate = np.array([g['date'] for g in G])
        self.np = len(self.pkey)
        self.pid = np.array([self.pm.get(k, -1) for k in self.pkey])
        print(f'{S}: {len(G)} games, {len(rows)} stints, {self.np} players, {int((self.pid >= 0).sum())} matched', flush=True)

    def col(self, t, n):
        k = (t, n)
        if k not in self.pidx:
            self.pidx[k] = len(self.pkey); self.pkey.append(k)
        return self.pidx[k]

    def bpm(self, gmask, m0=M0, b0=B0):
        """per column: (shrunk BPM over the games in gmask, minutes) from the Barttorvik logs"""
        num = np.zeros(self.np); den = np.zeros(self.np)
        for gi in np.where(gmask)[0]:
            g = self.games[gi]
            for t in (g['home'], g['away']):
                b = self.tm.get(t)
                if b is None:
                    continue
                for n in g['players'][t]:
                    pid = self.pm.get((t, n))
                    if pid is None:
                        continue
                    x = self.box.get((b, g['date'], pid))
                    if x:
                        c = self.pidx[(t, n)]
                        num[c] += x[0] * x[1]; den[c] += x[0]
        return (num + m0 * b0) / (den + m0), den

    def oo(self, smask, k=K_OO):
        """shrunk raw on-off per column from the stints in smask (team-net points per 100)"""
        on_p = np.zeros(self.np); on_m = np.zeros(self.np)
        team = defaultdict(lambda: [0.0, 0.0])
        cols_of = defaultdict(set)
        for idx in np.where(smask)[0]:
            gi, p, m, hc, ac = self.rows[idx]
            g = self.games[gi]
            for t, cs, sg in ((g['home'], hc, 1), (g['away'], ac, -1)):
                team[t][0] += p; team[t][1] += sg * m
                for c in cs:
                    on_p[c] += p; on_m[c] += sg * m
                    cols_of[t].add(c)
        out = np.zeros(self.np)
        for t, cs in cols_of.items():
            T = team[t]
            for c in cs:
                offp = T[0] - on_p[c]
                if on_p[c] > 0 and offp > 20:
                    diff = 100 * on_m[c] / on_p[c] - 100 * (T[1] - on_m[c]) / offp
                    hm = 1 / (1 / on_p[c] + 1 / offp)
                    out[c] = diff * hm / (hm + k)
        return out


def team_of_col(Sd):
    return np.array([hash(k[0]) for k in Sd.pkey])


# ---------------------------------------------------------------- interaction columns
def combos(Sd, smask, size, minp=MIN_INT):
    """teammate pairs / trios with minp+ possessions together in smask: list of column tuples, and a sparse design"""
    tog = defaultdict(float)
    idxs = np.where(smask)[0]
    from itertools import combinations
    for idx in idxs:
        _, p, _, hc, ac = Sd.rows[idx]
        for cs in (hc, ac):
            for cb in combinations(sorted(cs), size):
                tog[cb] += p
    keep = [cb for cb, p in tog.items() if p >= minp]
    ix = {cb: i for i, cb in enumerate(keep)}
    return keep, ix, tog


def combo_design(Sd, ix, size):
    from itertools import combinations
    ii, jj, vv = [], [], []
    for k, (_, _, _, hc, ac) in enumerate(Sd.rows):
        for cs, sg in ((hc, 1.0), (ac, -1.0)):
            for cb in combinations(sorted(cs), size):
                j = ix.get(cb)
                if j is not None:
                    ii.append(k); jj.append(j); vv.append(sg)
    return sparse.csr_matrix((vv, (ii, jj)), shape=(len(Sd.rows), len(ix)))


# ---------------------------------------------------------------- fits
def wls(cols, y, w):
    A = np.column_stack(cols)
    Aw = A * w[:, None]
    return np.linalg.solve(A.T @ Aw + 1e-9 * np.eye(A.shape[1]), Aw.T @ y)


def ridge(X, r, w, lam):
    """argmin sum w (r - X d)^2 + lam |d|^2"""
    W = sparse.diags(w)
    A = (X.T @ W @ X).tocsc() + lam * sparse.identity(X.shape[1], format='csc')
    b = X.T @ (w * r)
    if X.shape[1] <= 12000:
        return spsolve(A, b)
    d, _ = cg(A, b, maxiter=2000)
    return d


class Fit:
    """box prior + optional RAPM delta + optional on-off term + optional pair / trio interactions, on training stints"""

    def __init__(self, Sd, smask, gmask, lam=None, oo=False, inter=None, lam_int=None, unm_extra=True):
        self.Sd = Sd
        bpm, mins = Sd.bpm(gmask)
        known = (Sd.pid >= 0).astype(float)
        self.bpm = bpm * known
        X = Sd.X[smask]; y = Sd.y[smask]; w = Sd.w[smask]
        cols = [np.ones(len(y)), X @ self.bpm, X @ (1 - known)]
        c = wls(cols, y, w)
        self.hca, self.a, self.u = c[0], c[1], c[2]
        # on-off at a fixed weight (a weight fit on the same stints that made the on-off would chase its own noise)
        self.c = float(oo or 0.0)
        self.oov = Sd.oo(smask) if oo else 0.0
        self.base = self.a * self.bpm + self.u * (1 - known) + self.c * self.oov
        r = y - self.hca - X @ self.base
        self.delta = ridge(X, r, w, lam) if lam else np.zeros(Sd.np)
        self.rating = self.base + self.delta
        self.inter = None
        if inter:
            size = inter
            keep, ix, _ = combos(Sd, smask, size)
            self.keep, self.ix = keep, ix
            Z = combo_design(Sd, ix, size)
            self.Z = Z
            r2 = r - X @ self.delta
            self.inter = ridge(Z[smask], r2, w, lam_int) if len(keep) else np.zeros(0)

    def pred(self, smask):
        p = self.hca + self.Sd.X[smask] @ self.rating
        if self.inter is not None and len(self.inter):
            p = p + self.Z[smask] @ self.inter
        return p


def game_err(Sd, smask, pred):
    """per test game: (date, squared error, abs error) of the margin the stints give"""
    idx = np.where(smask)[0]
    pm = defaultdict(float); am = defaultdict(float)
    for k, i in enumerate(idx):
        gi = Sd.sg[i]
        pm[gi] += Sd.w[i] * pred[k] / 100
        am[gi] += Sd.m[i]
    gs = sorted(pm)
    e = np.array([pm[g] - am[g] for g in gs])
    return gs, e


def tstat(d, cl):
    by = defaultdict(float)
    for a, c in zip(d, cl):
        by[c] += a
    v = np.array(list(by.values()))
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))) if len(v) > 2 else 0.0


def splits(Sd):
    G = len(Sd.games)
    out = []
    fid = np.array([h01(g['id']) % 5 for g in Sd.games])
    for f in range(5):
        out.append(('kfold', fid != f, fid == f))
    for lo, hi in ((f'{Sd.S}-01-10', f'{Sd.S}-02-10'), (f'{Sd.S}-02-10', f'{Sd.S}-05-01')):
        tr = Sd.gdate < lo
        te = (Sd.gdate >= lo) & (Sd.gdate < hi)
        if tr.sum() > 300 and te.sum() > 100:
            out.append(('forward', tr, te))
    return out


def eval_models(Sd, specs):
    """specs: name -> kwargs for Fit. Returns per split kind: name -> (games, sq err list, date list)"""
    res = defaultdict(lambda: defaultdict(lambda: [[], []]))
    for kind, gtr, gte in splits(Sd):
        str_ = gtr[Sd.sg]; ste = gte[Sd.sg]
        for name, kw in specs.items():
            F = Fit(Sd, str_, gtr, **kw)
            gs, e = game_err(Sd, ste, F.pred(ste))
            res[kind][name][0].extend(e.tolist())
            res[kind][name][1].extend(Sd.gdate[gs].tolist())
        print(f'  {Sd.S} {kind} split done', flush=True)
    return res


def summarize(res, base='box'):
    out = {}
    for kind, d in res.items():
        e0 = np.array(d[base][0]); dates = d[base][1]
        o = {'games': len(e0), base: round(float(np.mean(e0 ** 2)), 3)}
        for name, (e, _) in d.items():
            if name == base:
                continue
            e = np.array(e)
            dd = e ** 2 - e0 ** 2
            o[name] = dict(mse=round(float(np.mean(e ** 2)), 3), d=round(float(dd.mean()), 3), t=round(tstat(dd, dates), 2))
        out[kind] = o
    return out


# ---------------------------------------------------------------- next season
def next_season(S0, S1, lam):
    """2025 ratings -> 2026 games. Ratings by Barttorvik pid. Models share the newcomer handling (an indicator)."""
    F0 = Fit(S0, np.ones(len(S0.rows), bool), np.ones(len(S0.games), bool), lam=lam)
    oo0 = S0.oo(np.ones(len(S0.rows), bool))
    full = {}
    for c, pid in enumerate(S0.pid):
        if pid >= 0:
            full[pid] = (F0.bpm[c], F0.delta[c], oo0[c], F0.rating[c])
    # S1 columns
    v = np.zeros((S1.np, 4)); known = np.zeros(S1.np)
    for c, pid in enumerate(S1.pid):
        if pid in full:
            v[c] = full[pid]; known[c] = 1
    X = S1.X
    feats = {'box': [X @ v[:, 0], X @ (1 - known)],
             'rapm': [X @ v[:, 0], X @ v[:, 1], X @ (1 - known)],
             'oo': [X @ v[:, 0], X @ v[:, 2], X @ (1 - known)]}
    half = np.array([h01(g['id']) % 2 for g in S1.games])[S1.sg]
    errs = defaultdict(list); dates = []
    coefs = defaultdict(list)
    for hh in (0, 1):
        tr, te = half != hh, half == hh
        first = True
        for name, cols in feats.items():
            C = [np.ones(len(S1.y))] + cols
            b = wls([c[tr] for c in C], S1.y[tr], S1.w[tr])
            coefs[name].append([round(float(x), 3) for x in b])
            p = np.column_stack([c[te] for c in C]) @ b
            gs, e = game_err(S1, te, p)
            errs[name].extend(e.tolist())
            if first:
                dates.extend(S1.gdate[gs].tolist()); first = False
    e0 = np.array(errs['box'])
    out = {'games': len(e0), 'box': round(float(np.mean(e0 ** 2)), 3), 'returnerShare': round(float((known * 1).sum() / S1.np), 3), 'coefs': coefs}
    for name in ('rapm', 'oo'):
        e = np.array(errs[name]); dd = e ** 2 - e0 ** 2
        out[name] = dict(mse=round(float(np.mean(e ** 2)), 3), d=round(float(dd.mean()), 3), t=round(tstat(dd, dates), 2))
    return out


# ---------------------------------------------------------------- FV drivers
def drivers(Sd, lam, lam_int):
    """per Barttorvik pid: oo, rapm, pair, pairmax, trio, triomax, unit, unitbest, min (full season)"""
    allS = np.ones(len(Sd.rows), bool); allG = np.ones(len(Sd.games), bool)
    F = Fit(Sd, allS, allG, lam=lam)
    oo = Sd.oo(allS)
    _, mins = Sd.bpm(allG)
    feat = {c: {} for c in range(Sd.np)}
    for c in range(Sd.np):
        feat[c].update(oo=oo[c], rapm=F.delta[c], min=mins[c])
    for size, nm in ((2, 'pair'), (3, 'trio')):
        Fi = Fit(Sd, allS, allG, lam=lam, inter=size, lam_int=lam_int)
        _, _, tog = combos(Sd, allS, size, minp=0)
        acc = defaultdict(lambda: [0.0, 0.0, -99.0])
        for cb, j in Fi.ix.items():
            p = tog[cb]; v = Fi.inter[j]
            for c in cb:
                a = acc[c]; a[0] += p * v; a[1] += p; a[2] = max(a[2], v)
        for c in range(Sd.np):
            a = acc.get(c)
            feat[c][nm] = a[0] / a[1] if a and a[1] else 0.0
            feat[c][nm + 'max'] = a[2] if a and a[1] else 0.0
    # 5-man units
    unit = defaultdict(lambda: [0.0, 0.0])            # (team, cols) -> poss, team margin
    team = defaultdict(lambda: [0.0, 0.0])
    for gi, p, m, hc, ac in Sd.rows:
        g = Sd.games[gi]
        for t, cs, sg in ((g['home'], hc, 1), (g['away'], ac, -1)):
            if len(cs) != 5:
                continue
            u = unit[(t, tuple(sorted(cs)))]; u[0] += p; u[1] += sg * m
            team[t][0] += p; team[t][1] += sg * m
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, None])
    for (t, cs), (p, m) in unit.items():
        tn = 100 * team[t][1] / team[t][0]
        sh = (100 * m + tn * 150.0) / (p + 150.0) - tn
        for c in cs:
            a = acc[c]; a[0] += p * sh; a[1] += p
            if p > a[2]:
                a[2] = p; a[3] = sh
    for c in range(Sd.np):
        a = acc.get(c)
        feat[c]['unit'] = a[0] / a[1] if a and a[1] else 0.0
        feat[c]['unitbest'] = a[3] if a and a[3] is not None else 0.0
    out = {}
    for c, f in feat.items():
        pid = Sd.pid[c]
        if pid >= 0 and f['min'] >= 200:
            if pid not in out or f['min'] > out[pid]['min']:
                out[int(pid)] = f
    return out


DRV = ['oo', 'rapm', 'pair', 'pairmax', 'trio', 'triomax', 'unit', 'unitbest']


def kit_rows(seasons):
    import csv
    rows = {}
    with open(KIT) as fh:
        for r in csv.DictReader(fh):
            try:
                y = int(r['year'])
            except ValueError:
                continue
            if y in seasons:
                rows[(y, int(r['pid']))] = r
    return rows


def fnum(x, d=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except (TypeError, ValueError):
        return d


POWER = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}


def base_feats(r, S):
    mpt = (fnum(r['mp'], 0) or 0) * (fnum(r['gp'], 0) or 0)
    sh = lambda x, prior, k: ((fnum(x, prior)) * mpt + prior * k) / (mpt + k)
    bpm = sh(r['bpm'], -4.0, 300)
    prpg = sh(r['porpag'], 0, 300) * (fnum(r['min_per'], 0) or 0) / 100
    dob = r.get('dob') or ''
    try:
        age = S + 0.5 - int(dob[:4]) - (int(dob[5:7]) - 1) / 12
    except ValueError:
        age = 21.0
    rk = [fnum(r.get('on3rk')), fnum(r.get('rk247'))]
    rk = [x for x in rk if x]
    lrk = -math.log(min(min(rk), 500)) if rk else -math.log(600)
    return [bpm, prpg, age, (age - 21) ** 2, lrk, fnum(r['hti'], 77) or 77, sh(r['stl'], 1.4, 400), sh(r['usg'], 16, 300),
            1.0 if r['conf'] in POWER else 0.0]


def logit(X, y, lam=1.0, it=50):
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        g = X.T @ (p - y) + lam * np.r_[0, b[1:]]
        H = (X * (p * (1 - p))[:, None]).T @ X + lam * np.diag(np.r_[0, np.ones(len(b) - 1)])
        b -= np.linalg.solve(H, g)
    return b


def std(A, ref):
    mu, sd = ref.mean(0), ref.std(0) + 1e-9
    return (A - mu) / sd


def auc(s, y):
    o = np.argsort(s); r = np.empty(len(s)); r[o] = np.arange(1, len(s) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def fv_tests(DR, seasons):
    kit = kit_rows(set(seasons))
    data = {}
    for S in seasons:
        rows = []
        for pid, f in DR[S].items():
            r = kit.get((S, pid))
            if r is None:
                continue
            drafted = fnum(r['nba_draft']) == S
            pick = fnum(r['nba_pick']) if drafted else None
            rows.append(dict(pid=pid, name=r['name'], base=base_feats(r, S), d=[f[k] for k in DRV], drafted=drafted, pick=pick,
                             bref=r['nba_bref'] or None))
        data[S] = rows
        print(f'FV rows {S}: {len(rows)}, drafted {sum(r["drafted"] for r in rows)}', flush=True)
    res = {'n': {S: len(v) for S, v in data.items()}, 'drafted': {S: sum(r['drafted'] for r in v) for S, v in data.items()},
           'corrWithBpm': {}, 'draft': {}, 'pick': {}, 'rookie': {}}
    # driver correlations with BPM (how much is new information)
    allr = [r for S in seasons for r in data[S]]
    if len(allr) < 50:
        return res
    Bm = np.array([r['base'][0] for r in allr]); Dm = np.array([r['d'] for r in allr])
    for j, k in enumerate(DRV):
        res['corrWithBpm'][k] = round(float(np.corrcoef(Bm, Dm[:, j])[0, 1]), 3)
    # (1) drafted that June: fit on one season, score the other (both ways); 5-fold within each season too
    for j, k in enumerate(DRV):
        o = {}
        for a, b in ((seasons[0], seasons[-1]), (seasons[-1], seasons[0])):
            if a == b:
                continue
            tr, te = data[a], data[b]
            Xtr0 = np.array([r['base'] for r in tr]); Xte0 = np.array([r['base'] for r in te])
            ytr = np.array([r['drafted'] for r in tr], float); yte = np.array([r['drafted'] for r in te], float)
            Z0 = std(Xtr0, Xtr0); Zt0 = std(Xte0, Xtr0)
            dtr = np.array([r['d'][j] for r in tr])[:, None]; dte = np.array([r['d'][j] for r in te])[:, None]
            Z1 = np.c_[Z0, std(dtr, dtr)]; Zt1 = np.c_[Zt0, std(dte, dtr)]
            b0 = logit(np.c_[np.ones(len(Z0)), Z0], ytr); b1 = logit(np.c_[np.ones(len(Z1)), Z1], ytr)
            p0 = 1 / (1 + np.exp(-(np.c_[np.ones(len(Zt0)), Zt0] @ b0))); p1 = 1 / (1 + np.exp(-(np.c_[np.ones(len(Zt1)), Zt1] @ b1)))
            ll = lambda p: -float(np.mean(yte * np.log(np.clip(p, 1e-9, 1)) + (1 - yte) * np.log(np.clip(1 - p, 1e-9, 1))))
            # bootstrap over test players for the log-loss change
            rng = np.random.default_rng(3)
            l0 = -(yte * np.log(np.clip(p0, 1e-9, 1)) + (1 - yte) * np.log(np.clip(1 - p0, 1e-9, 1)))
            l1 = -(yte * np.log(np.clip(p1, 1e-9, 1)) + (1 - yte) * np.log(np.clip(1 - p1, 1e-9, 1)))
            dd = l1 - l0
            bs = [dd[rng.integers(0, len(dd), len(dd))].mean() for _ in range(400)]
            o[f'{a}->{b}'] = dict(coef=round(float(b1[-1]), 3), llBase=round(ll(p0), 5), llD=round(float(dd.mean()), 5),
                                  pBetter=round(float(np.mean(np.array(bs) < 0)), 3), aucBase=round(auc(p0, yte), 4),
                                  auc=round(auc(p1, yte), 4))
        res['draft'][k] = o
    # (2) -ln pick among the drafted, the other season
    for j, k in enumerate(DRV):
        o = {}
        for a, b in ((seasons[0], seasons[-1]), (seasons[-1], seasons[0])):
            if a == b:
                continue
            tr = [r for r in data[a] if r['drafted'] and r['pick']]; te = [r for r in data[b] if r['drafted'] and r['pick']]
            if len(tr) < 15 or len(te) < 15:
                continue
            Xtr0 = np.array([r['base'] for r in tr]); Xte0 = np.array([r['base'] for r in te])
            ytr = -np.log([r['pick'] for r in tr]); yte = -np.log([r['pick'] for r in te])
            Z0 = std(Xtr0, Xtr0); Zt0 = std(Xte0, Xtr0)
            dtr = np.array([r['d'][j] for r in tr])[:, None]; dte = np.array([r['d'][j] for r in te])[:, None]
            Z1 = np.c_[Z0, std(dtr, dtr)]; Zt1 = np.c_[Zt0, std(dte, dtr)]
            rf = lambda Z, y: np.linalg.solve(np.c_[np.ones(len(Z)), Z].T @ np.c_[np.ones(len(Z)), Z] + 3 * np.diag(np.r_[0, np.ones(Z.shape[1])]), np.c_[np.ones(len(Z)), Z].T @ y)
            b0 = rf(Z0, ytr); b1 = rf(Z1, ytr)
            e0 = (np.c_[np.ones(len(Zt0)), Zt0] @ b0 - yte) ** 2; e1 = (np.c_[np.ones(len(Zt1)), Zt1] @ b1 - yte) ** 2
            dd = e1 - e0
            o[f'{a}->{b}'] = dict(n=len(te), coef=round(float(b1[-1]), 3), mseBase=round(float(e0.mean()), 4), d=round(float(dd.mean()), 4),
                                  t=round(float(dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))), 2))
        res['pick'][k] = o
    # (3) the 2025 class's NBA rookie season (2025-26)
    S = seasons[0]
    try:
        nba = json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{S + 1}.json')))['players']
    except Exception:
        nba = []
    by = {p['id']: p for p in nba}
    rk = []
    for r in data.get(S, []):
        p = by.get(r['bref']) if r['bref'] else None
        if p and p.get('mp'):
            x = (p['xpm'] * p['mp'] - 2.0 * 500) / (p['mp'] + 500)
            rk.append((r, x, p['mp']))
    res['rookie']['n'] = len(rk)
    if len(rk) >= 20:
        yv = np.array([x for _, x, _ in rk])
        B = np.c_[np.ones(len(rk)), -np.log([r['pick'] or 75 for r, _, _ in rk]), [r['base'][0] for r, _, _ in rk]]
        def loo(A):
            e = []
            for i in range(len(yv)):
                m = np.arange(len(yv)) != i
                b = np.linalg.lstsq(A[m], yv[m], rcond=None)[0]
                e.append((A[i] @ b - yv[i]) ** 2)
            return np.array(e)
        e0 = loo(B)
        res['rookie']['mseBase'] = round(float(e0.mean()), 4)
        for j, k in enumerate(DRV):
            A = np.c_[B, [r['d'][j] for r, _, _ in rk]]
            e1 = loo(A); dd = e1 - e0
            b = np.linalg.lstsq(A, yv, rcond=None)[0]
            res_ = yv - A @ b
            se = math.sqrt(res_.var() * np.linalg.inv(A.T @ A)[-1, -1] * len(yv) / (len(yv) - A.shape[1]))
            res['rookie'][k] = dict(coef=round(float(b[-1]), 3), coefT=round(float(b[-1] / se), 2), looD=round(float(dd.mean()), 4),
                                    t=round(float(dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))), 2))
    return res


# ---------------------------------------------------------------- main
def main():
    seasons = [int(a) for a in sys.argv[1:] if a.isdigit()] or [2025, 2026]
    SD = {S: Season(S) for S in seasons}
    res = {'seasons': {S: dict(games=len(SD[S].games), stints=len(SD[S].rows), players=SD[S].np) for S in seasons}}
    # A1: lambda grid + on-off blend, both seasons, in-season splits
    specs = {'box': {}}
    for c in (0.25, 0.5, 1.0):
        specs[f'oo{c}'] = dict(oo=c)
    for lam in LAMS:
        specs[f'rapm{lam}'] = dict(lam=lam)
    res['xpm'] = {}
    for S in seasons:
        res['xpm'][S] = summarize(eval_models(SD[S], specs))
        print('xpm', S, json.dumps(res['xpm'][S]), flush=True)
    tuneS, heldS = seasons[0], seasons[-1]
    kf = res['xpm'][tuneS]['kfold']
    lam = min(LAMS, key=lambda l: kf[f'rapm{l}']['mse'])
    res['lam'] = lam
    # A2: interactions on top of the picked lambda
    specs2 = {'box': {}, f'rapm{lam}': dict(lam=lam)}
    for li in LAM_INT:
        specs2[f'pair{li}'] = dict(lam=lam, inter=2, lam_int=li)
        specs2[f'trio{li}'] = dict(lam=lam, inter=3, lam_int=li)
    res['inter'] = {}
    for S in seasons:
        res['inter'][S] = summarize(eval_models(SD[S], specs2))
        print('inter', S, json.dumps(res['inter'][S]), flush=True)
    kfi = res['inter'][tuneS]['kfold']
    lam_int = min(LAM_INT, key=lambda l: min(kfi[f'pair{l}']['mse'], kfi[f'trio{l}']['mse']))
    res['lamInt'] = lam_int
    # A3: next season
    if len(seasons) >= 2:
        res['nextSeason'] = next_season(SD[seasons[0]], SD[seasons[1]], lam)
        print('next', json.dumps(res['nextSeason']), flush=True)
    # B: FV drivers
    DR = {S: drivers(SD[S], lam, lam_int) for S in seasons}
    res['fv'] = fv_tests(DR, seasons)
    print('fv', json.dumps(res['fv'])[:4000], flush=True)
    json.dump(res, open(OUT, 'w'), indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
