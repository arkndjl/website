#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer GAR staple audit (Nov 3 2026) -> data/soccer_gar_research_nov03.json.

Harness = soccer_players.py's fit (last season's shrunk rates x this season's minutes -> team goal difference a match,
centred within league-season, ridge, leave-one-season-out). Understat is blocked from the container and no
scripts/.cache exists, so team-seasons are rebuilt from the cached player rows (on-pitch goals / 11, minutes / 990);
the Transfermarkt dump is absent, so the newcomer prior is the 'new' indicator only (no TM value). lgm kept.

Pre-registered (before results):
  A  leak : shrink, lambda and the rate set are picked on the same LOSO error that is reported as held out. Nested
            LOSO (pick shrink/lambda/rates on the other seasons only, score the left-out season) = honest R2.
  C1 per-rate shrink (on-off keeps 2x its own): coordinate descent over {100..1500} per rate, picked in inner LOSO.
  C2 two-season prior: S-1 and S-2 raw rates pooled (S-2 minutes x d, d picked inner from .25/.5/1), shrunk on the
     pooled minutes.
  C3 stint merge (bug check): a player with two clubs in a season gets one prior from both stints (minutes-weighted);
     shipped code keeps whichever stint is iterated last (and skips it under 300 minutes).
  C4 replacement (no fit): team prediction in GAR units (value - position replacement) vs value; thresholds 600 /
     900 / 1500 and one pooled replacement. Team GD is centred within league-season, so only position mix differs.
C2 follow-up (--transfer): two-season weights applied to one-season rates (what the board shows).
Gate: paired t over the 11 scored seasons (season mean squared-error change) <= -2 after Holm over C1-C3, a
majority of seasons better, 2022+ not worse. Each candidate vs the nested baseline (its own picks nested too).
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D  # noqa: E402
import soccer_players as SP  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_gar_research_nov03.json')
SHR = (100, 200, 300, 500, 800, 1500)
LAMS = (0.1, 1.0, 5.0)
PRI = ['lgm', 'new']
F = SP.FEATS


def team_seasons(rows):
    t = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        x = t[(r['lg'], r['S'], r['tid'])]
        x[0] += r['min']; x[1] += r['gf']; x[2] += r['ga']
    return {k: {'mp': max(1, round(v[0] / 990)), 'gd': (v[1] - v[2]) / 11} for k, v in t.items()}


def raw_and_mean(rows):
    """per row: league-season-centred raw rate (shrink 0) and its position mean (shrink -> inf)"""
    SP.prep(rows, 1e-9)
    raw = np.array([[r[f] for f in F] for r in rows])
    SP.prep(rows, 1e15)
    pm = np.array([[r[f] for f in F] for r in rows])
    return raw, pm


class H:
    def __init__(self):
        S1 = D.current_season()
        self.rows = rows = [r for r in D.load(SP.ROWS) if r['S'] < S1]
        self.ts = team_seasons(rows)
        self.LS = SP.league_strength()
        self.raw, self.pm = raw_and_mean(rows)
        self.mins = np.array([r['min'] for r in rows], float)
        self.ix = {}
        for i, r in enumerate(rows):
            self.ix.setdefault((r['p'], r['S']), []).append(i)
        self.lastrow = {}
        for i, r in sorted(enumerate(rows), key=lambda x: x[1]['S']):
            self.lastrow[(r['p'], r['S'])] = i               # shipped design(): the stint iterated last wins

    def shrunk(self, idx, sh, extra=None):
        """shrunk rates for stint(s) idx (pooled by minutes) at per-rate shrink sh (array len F; rel 2x)"""
        idx = list(idx)
        m = self.mins[idx]
        raw = (self.raw[idx] * m[:, None]).sum(0) / m.sum()
        pm = (self.pm[idx] * m[:, None]).sum(0) / m.sum()
        mt = m.sum()
        if extra is not None:                                # (raw2, minutes2 x d)
            r2, m2 = extra
            raw = (raw * mt + r2 * m2) / (mt + m2); mt = mt + m2
        k = np.array(sh, float) * np.array([2.0 if f == 'rel' else 1.0 for f in F])
        w = mt / (mt + k)
        return w * raw + (1 - w) * pm

    def design(self, sh, mode='base', d=0.5):
        rows, ts = self.rows, self.ts
        nx = len(F) + len(PRI)
        X, has = defaultdict(lambda: np.zeros(nx)), set()
        cache = {}
        for i, r in enumerate(rows):
            k = (r['lg'], r['S'], r['tid'])
            share = r['min'] / (90 * ts[k]['mp'])
            pr = None
            for S0 in (r['S'] - 1, r['S'] - 2):
                if mode == 'base':
                    j = self.lastrow.get((r['p'], S0))
                    if j is not None and rows[j]['min'] >= 300:
                        pr = [j]; break
                else:
                    js = self.ix.get((r['p'], S0))
                    if js and sum(rows[j]['min'] for j in js) >= 300:
                        pr = js; break
            e = np.zeros(len(PRI))
            if pr:
                key = (r['p'], S0)
                if key not in cache:
                    extra = None
                    if mode == 'two' and S0 == r['S'] - 1:
                        j2 = self.ix.get((r['p'], S0 - 1))
                        if j2:
                            m2 = self.mins[j2]
                            extra = ((self.raw[j2] * m2[:, None]).sum(0) / m2.sum(), m2.sum() * d)
                    cache[key] = self.shrunk(pr, sh, extra)
                v = cache[key]
                big = max(pr, key=lambda j: rows[j]['min'])
                if rows[big]['lg'] != r['lg']:
                    e[0] = self.LS.get((rows[big]['lg'], S0), 0) - self.LS.get((r['lg'], S0), 0)
                has.add(k)
            else:
                v = np.zeros(len(F)); e[1] = 1.0
            X[k] += share * np.concatenate([v, e])
        ks = sorted(k for k in X if k in has)
        Xm = np.array([X[k] for k in ks]); ym = np.array([ts[k]['gd'] / ts[k]['mp'] for k in ks])
        grp = defaultdict(list)
        for i, k in enumerate(ks):
            grp[(k[0], k[1])].append(i)
        for idx in grp.values():
            Xm[idx] -= Xm[idx].mean(0); ym[idx] -= ym[idx].mean()
        return ks, Xm, ym


def loso_pred(S_arr, X, y, lam, seasons):
    pred = np.full(len(y), np.nan)
    for S in seasons:
        te = S_arr == S; tr = np.isin(S_arr, seasons) & ~te
        if te.sum() == 0 or tr.sum() < 20:
            continue
        pred[te] = X[te] @ SP.ridge(X[tr], y[tr], lam)
    return pred


def mse_on(S_arr, X, y, lam, seasons):
    p = loso_pred(S_arr, X, y, lam, seasons)
    m = np.isin(S_arr, seasons) & ~np.isnan(p)
    return float(np.mean((y[m] - p[m]) ** 2))


def select_cols(S_arr, X, y, lam, seasons):
    """backward elimination as fit(): drop a rate while dropping it does not raise LOSO error by 1e-5"""
    npr = list(range(len(F), len(F) + len(PRI)))
    feats = list(range(len(F)))
    while True:
        e_full = mse_on(S_arr, X[:, feats + npr], y, lam, seasons)
        drops = sorted((mse_on(S_arr, X[:, [g for g in feats if g != f] + npr], y, lam, seasons) - e_full, f)
                       for f in feats)
        if drops[0][0] < 1e-5 and len(feats) > 1:
            feats.remove(drops[0][1])
        else:
            return feats + npr


def main():
    h = H()
    res = {'note': 'team-seasons rebuilt from cached rows; newcomer prior = indicator only (TM dump absent)'}
    # designs per (mode, shrink); each column depends only on its own shrink, so per-rate shrink = column picks
    designs = {}
    for mode in ('base', 'merge'):
        for s in SHR:
            designs[(mode, s)] = h.design([s] * len(F), mode)
            print(mode, s, flush=True, file=sys.stderr)
    for d in (0.25, 0.5, 1.0):
        for s in SHR:
            designs[('two', d, s)] = h.design([s] * len(F), 'two', d)
        print('two', d, flush=True, file=sys.stderr)
    ks = designs[('base', 300)][0]
    for key, (k2, _, _) in designs.items():
        assert k2 == ks, key
    S_arr = np.array([k[1] for k in ks]); seasons = sorted(set(S_arr.tolist()))
    y = designs[('base', 300)][2]
    var = float(np.mean(y ** 2))
    # reproduction at the shipped settings (shrink 300, lambda 1, shipped rate set)
    shipped = [F.index(f) for f in json.load(open(SP.FIT))['feats']] + [len(F), len(F) + 1]
    Xb = designs[('base', 300)][1]
    res['reproduce'] = {'r2HeldShipped': round(1 - mse_on(S_arr, Xb[:, shipped], y, 1.0, seasons) / var, 4),
                        'r2HeldNoPriors': round(1 - mse_on(S_arr, Xb[:, shipped[:-2]], y, 1.0, seasons) / var, 4),
                        'teamSeasons': len(ks), 'seasons': seasons}
    print(res['reproduce'], file=sys.stderr, flush=True)

    def colmix(prefix, sh):
        return np.column_stack([designs[prefix + (sh[j],)][1][:, j] for j in range(len(F))] +
                               [designs[prefix + (300,)][1][:, len(F):]])

    def pick(inner, variant):
        """choose settings on inner seasons -> (X, lam, cols)"""
        best = None
        prefixes = [('base',)] if variant == 'base' else [('merge',)] if variant == 'merge' else \
            [('two', d) for d in (0.25, 0.5, 1.0)] if variant == 'two' else [('base',)]
        for pf in prefixes:
            for s in SHR:
                X = designs[pf + (s,)][1]
                for lam in LAMS:
                    e = mse_on(S_arr, X, y, lam, inner)
                    if best is None or e < best[0]:
                        best = (e, pf, [s] * len(F), lam)
        _, pf, sh, lam = best
        if variant == 'rate':                                    # coordinate descent per rate, 2 passes
            cur = mse_on(S_arr, colmix(pf, sh), y, lam, inner)
            for _ in range(2):
                for j in range(len(F)):
                    for s in SHR:
                        t = list(sh); t[j] = s
                        e = mse_on(S_arr, colmix(pf, t), y, lam, inner)
                        if e < cur - 1e-7:
                            cur, sh = e, t
        X = colmix(pf, sh)
        cols = select_cols(S_arr, X, y, lam, inner)
        return X, lam, cols, {'pf': list(pf), 'sh': sh, 'lam': lam, 'cols': [(F + PRI)[c] for c in cols]}

    nested = {}
    for variant in ('base', 'rate', 'two', 'merge'):
        e_by, picks = {}, {}
        for S in seasons[1:] if False else seasons:
            inner = [s for s in seasons if s != S]
            X, lam, cols, info = pick(inner, variant)
            te = S_arr == S
            b = SP.ridge(X[~te][:, cols], y[~te], lam)
            e_by[S] = ((y[te] - X[te][:, cols] @ b) ** 2)
            picks[S] = info
        nested[variant] = (e_by, picks)
        allE = np.concatenate([e_by[S] for S in seasons])
        print(variant, round(1 - allE.mean() / var, 4), file=sys.stderr, flush=True)
    base_e = nested['base'][0]
    res['A_nested'] = {'r2NestedBase': round(1 - np.concatenate([base_e[S] for S in seasons]).mean() / var, 4),
                       'picks': {str(S): nested['base'][1][S] for S in seasons}}
    tests = {}
    for v, nm in (('rate', 'C1_perRateShrink'), ('two', 'C2_twoSeason'), ('merge', 'C3_stintMerge')):
        e_by = nested[v][0]
        dS = np.array([e_by[S].mean() - base_e[S].mean() for S in seasons])
        t = float(dS.mean() / (dS.std(ddof=1) / math.sqrt(len(dS)))) if dS.std() > 0 else 0.0
        late = float(np.mean([e_by[S].mean() - base_e[S].mean() for S in seasons if S >= 2022]))
        tests[nm] = {'r2': round(1 - np.concatenate([e_by[S] for S in seasons]).mean() / var, 4),
                     't': round(t, 2), 'seasonsBetter': int((dS < 0).sum()), 'seasons': len(seasons),
                     'late2022Change': round(late, 6),
                     'picks': {str(S): nested[v][1][S] for S in seasons[-2:]}}
    # Holm over C1-C3 (one-sided, normal approx on t over seasons -> use t cut 2 at the first rank scaled)
    from math import erf
    pv = {k: 0.5 * (1 + erf(v['t'] / math.sqrt(2))) for k, v in tests.items()}   # P(improvement by chance)
    order = sorted(pv, key=pv.get)
    alive = True
    for i, k in enumerate(order):
        cut = 0.05 / (len(order) - i)
        ok = alive and pv[k] <= cut and tests[k]['seasonsBetter'] > len(seasons) / 2 and tests[k]['late2022Change'] <= 0
        tests[k]['pOneSided'] = round(pv[k], 4); tests[k]['holmCut'] = round(cut, 4); tests[k]['pass'] = bool(ok)
        alive = alive and pv[k] <= cut
    res.update(tests)
    # C4: replacement, no fit. GAR-unit team prediction = shipped LOSO prediction - sum(share x repl[pos]) (centred)
    Fj = json.load(open(SP.FIT))
    pred = loso_pred(S_arr, Xb[:, shipped], y, 1.0, seasons)
    base_sq = (y - pred) ** 2
    rows, ts = h.rows, h.ts
    SP.prep(rows, 300)
    vals = np.array([SP.value(r, Fj) + SP.lg_adj(r, Fj, h.LS) for r in rows])
    c4 = {}
    for thr in (600, 900, 1500, 'pooled900'):
        repl = {}
        for pos in ('GK', 'D', 'M', 'F'):
            t_ = 900 if thr == 'pooled900' else thr
            sel = [i for i, r in enumerate(rows) if (thr == 'pooled900' or r['pos'] == pos) and 90 <= r['min'] < t_]
            repl[pos] = float((vals[sel] * h.mins[sel]).sum() / h.mins[sel].sum())
        adj = defaultdict(float)
        for r in rows:
            k = (r['lg'], r['S'], r['tid'])
            adj[k] += r['min'] / (90 * ts[k]['mp']) * repl[r['pos']]
        a = np.array([adj[k] for k in ks])
        grp = defaultdict(list)
        for i, k in enumerate(ks):
            grp[(k[0], k[1])].append(i)
        for idx in grp.values():
            a[idx] -= a[idx].mean()
        sq = (y - (pred - a)) ** 2
        dS = np.array([sq[S_arr == S].mean() - base_sq[S_arr == S].mean() for S in seasons])
        c4[str(thr)] = {'repl': {k: round(v, 4) for k, v in repl.items()}, 'dMse': round(float(dS.mean()), 6),
                        't': round(float(dS.mean() / (dS.std(ddof=1) / math.sqrt(len(dS)) + 1e-12)), 2),
                        'seasonsBetter': int((dS < 0).sum())}
    res['C4_replacement'] = c4
    print(json.dumps(res, indent=1)[:3000], file=sys.stderr)
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False)


def transfer():
    """C2 follow-up: do weights fit on the two-season design help the one-season rates the board shows?"""
    h = H()
    d = {k: h.design([k[1]] * len(F), *(('two', 1.0) if k[0] == 't' else ('base',))) for k in (('b', 300), ('t', 100))}
    ks, _, y = d[('b', 300)]
    S_arr = np.array([k[1] for k in ks]); seasons = sorted(set(S_arr.tolist()))
    ship = [F.index(f) for f in json.load(open(SP.FIT))['feats']] + [len(F), len(F) + 1]

    def run(trn, tst):
        e = {}
        for s in seasons:
            te = S_arr == s
            b = SP.ridge(trn[~te][:, ship], y[~te], 1.0)
            e[s] = float(np.mean((y[te] - tst[te][:, ship] @ b) ** 2))
        return e
    base = run(d[('b', 300)][1], d[('b', 300)][1])
    e = run(d[('t', 100)][1], d[('b', 300)][1])
    dS = np.array([e[s] - base[s] for s in seasons])
    res = json.load(open(OUT))
    res['C2_weightsOnOneSeason'] = {'t': round(float(dS.mean() / (dS.std(ddof=1) / math.sqrt(len(dS)))), 2),
                                    'seasonsBetter': int((dS < 0).sum()), 'seasons': len(seasons)}
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False)
    print(res['C2_weightsOnOneSeason'])


if __name__ == '__main__':
    transfer() if '--transfer' in sys.argv else main()
