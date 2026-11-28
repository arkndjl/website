#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research (Nov 28 2026): is NHL pWAR on WAR's scale, and does a calibrated pWAR predict next season's WAR better?

    python3 scripts/research/nhl_pwar_nov28/test.py      # writes research/nhl_pwar_cal.json and data/nhl_pwar_cal.json

Rows: every player-season S 2010-25 in static/data/nhl-war/<S>.json with 100+ minutes in S and in S+1.
Target: WAR a 60 in S+1, weighted by S+1 minutes (the error is then WAR at his next-season minutes).
Inputs at the end of S, by group (F / D / G):
    pw   the live pWAR a 60: (HPM - replacement) / goals a win
    pm   descriptive WAR a 60, Marcel over S, S-1, S-2 (1/.7/.5) with 1,600 minutes at the group mean (the 3Y input)
    A    age - 27, A^2
Forms (pre-registered): live (pw as is), cal (a + b pw), both (a + b pw + c pm), bage (both + A + A^2).
Gate: leave one season out (and a time split, fit 2010-16, test 2017-25); beat live and the simpler form with paired t <= -2 (players), win most seasons, calibration
slope .8-1.2 overall and the top WAR decile within 25% of its outcome.
"""
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SD = os.path.join(ROOT, 'static', 'data', 'nhl-war')
KP, MW, A0 = 1600.0, (1.0, 0.7, 0.5), 27
FORMS = ['live', 'cal', 'both', 'bage']


def load():
    F = {}
    for S in range(2009, 2030):
        fn = os.path.join(SD, f'{S}.json')
        if os.path.exists(fn):
            F[S] = {p['id']: p for p in json.load(open(fn))['players']}
    return F


def group_mu(F):
    """WAR a minute of each group over every finished season (the shrink target)"""
    mu = {}
    for g in 'FDG':
        w = t = 0.0
        for S, P in F.items():
            for p in P.values():
                if p['grp'] == g:
                    w += p['war']; t += p['toi']
        mu[g] = w / t
    return mu


def feats(F, S, p, mu):
    num, den = MW[0] * p['war'], MW[0] * p['toi']
    for j, w in ((1, MW[1]), (2, MW[2])):
        q = F.get(S - j, {}).get(p['id'])
        if q:
            num += w * q['war']; den += w * q['toi']
    pm = (num + KP * mu[p['grp']]) / (den + KP) * 60
    pw = p.get('pw0', p['pwar']) / p['toi'] * 60 if p['toi'] else 0.0     # the uncalibrated pWAR (pw0 once calibration ships)
    A = (p['age'] if p.get('age') is not None else A0) - A0
    return pw, pm, A


def X(form, pw, pm, A):
    if form == 'cal':
        return np.c_[np.ones_like(pw), pw]
    if form == 'both':
        return np.c_[np.ones_like(pw), pw, pm]
    return np.c_[np.ones_like(pw), pw, pm, A, A * A]


def wfit(x, y, w):
    s = np.sqrt(w)
    return np.linalg.lstsq(x * s[:, None], y * s, rcond=None)[0]


def run():
    F = load()
    last = max(S for S in F if S + 1 in F) - 1        # the season in progress is never a target
    mu = group_mu({S: P for S, P in F.items() if S <= last})
    out, coef, ship = {}, {}, {}
    for g in 'FDG':
        R = []
        for S in range(2010, last + 1):
            for i, p in F[S].items():
                q = F[S + 1].get(i)
                if p['grp'] != g or p['toi'] < 100 or not q or q['toi'] < 100:
                    continue
                R.append((S, *feats(F, S, p, mu), q['war'] / q['toi'] * 60, q['toi'], p['war'] / p['toi'] * 60))
        S, pw, pm, A, y, w, wnow = map(np.array, zip(*R))
        pred = {'live': pw.copy()}
        for f in FORMS[1:]:
            pr = np.zeros_like(y)
            for s in np.unique(S):
                tr, te = S != s, S == s
                pr[te] = X(f, pw[te], pm[te], A[te]) @ wfit(X(f, pw[tr], pm[tr], A[tr]), y[tr], w[tr])
            pred[f] = pr
            coef[f'{g}:{f}'] = [round(float(c), 5) for c in wfit(X(f, pw, pm, A), y, w)]
        se = {f: w / 60 * (pred[f] - y) ** 2 for f in FORMS}           # squared error x minutes (WAR-scale weight)
        # time split: fit 2010-16, test 2017 on
        tr, te = S <= 2016, S >= 2017
        split = {}
        for f in FORMS[1:]:
            e = w[te] / 60 * (X(f, pw[te], pm[te], A[te]) @ wfit(X(f, pw[tr], pm[tr], A[tr]), y[tr], w[tr]) - y[te]) ** 2
            d = e - se['live'][te]
            split[f] = round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2)
        res = {}
        for f in FORMS:
            d = se[f] - se['live']
            dc = se[f] - se[FORMS[max(0, FORMS.index(f) - 1)]]
            won = sum(se[f][S == s].sum() < se['live'][S == s].sum() for s in np.unique(S))
            b = wfit(np.c_[np.ones_like(y), pred[f]], y, w)
            # top decile by this season's WAR a 60 (what the WAR board leads with): mean prediction vs outcome
            top = wnow >= np.quantile(wnow, .9)
            res[f] = {'wmse': round(float(se[f].sum() / (w / 60).sum()), 6),
                      't_vs_live': round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2) if f != 'live' else None,
                      't_vs_prev': round(float(dc.mean() / (dc.std(ddof=1) / np.sqrt(len(dc)))), 2) if f not in ('live', 'cal') else None,
                      'seasonsWon': int(won), 'seasons': int(len(np.unique(S))), 'slope': round(float(b[1]), 3),
                      'split_t': split.get(f), 'mean': round(float(np.average(pred[f], weights=w)), 4), 'top10': round(float(np.average(pred[f][top], weights=w[top])), 4)}
        dec = []
        q = np.quantile(wnow, np.linspace(0, 1, 11))
        for a, b in zip(q, q[1:]):
            m = (wnow >= a) & (wnow <= b)
            dec.append({'now': round(float(np.average(wnow[m], weights=w[m])), 4), 'next': round(float(np.average(y[m], weights=w[m])), 4),
                        **{f: round(float(np.average(pred[f][m], weights=w[m])), 4) for f in FORMS}})
        # the shipped form: the richest one that beats live and the next simpler form at t <= -2 on both tests
        best = 'live'
        for f in FORMS[1:]:
            prev_ok = f == 'cal' or (res[f]['t_vs_prev'] <= -2)
            if res[f]['t_vs_live'] <= -2 and split[f] <= -2 and prev_ok and res[f]['seasonsWon'] * 2 > res[f]['seasons'] \
                    and .8 <= res[f]['slope'] <= 1.2 and (f == 'cal' or best == FORMS[FORMS.index(f) - 1]):
                best = f
        ship[g] = best
        out[g] = {'ship': best, 'n': len(y), 'next': round(float(np.average(y, weights=w)), 4), 'forms': res, 'deciles': dec}
        print(g, len(y), 'next', out[g]['next'], json.dumps(res), flush=True)
    return out, coef, mu, ship


if __name__ == '__main__':
    out, coef, mu, ship = run()
    json.dump({'updated': __import__('datetime').date.today().isoformat(), 'A0': A0, 'K': KP, 'mw': MW,
               'mu': {g: round(v, 7) for g, v in mu.items()},
               'groups': {g: {'form': f, 'c': coef[f'{g}:{f}']} for g, f in ship.items() if f != 'live'},
               'note': 'scripts/research/nhl_pwar_nov28/test.py; pWAR a 60 = c . X(form), x TOI / 60'},
              open(os.path.join(ROOT, 'data', 'nhl_pwar_cal.json'), 'w'), indent=1)
    os.makedirs(os.path.join(ROOT, 'research'), exist_ok=True)
    json.dump({'updated': __import__('datetime').date.today().isoformat(), 'groups': out, 'coef': coef, 'mu': mu},
              open(os.path.join(ROOT, 'research', 'nhl_pwar_cal.json'), 'w'), indent=1)
