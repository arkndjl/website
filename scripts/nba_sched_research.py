#!/usr/bin/env python3
"""The schedule's side of the NBA game model: who sits or plays fewer minutes on the second night of a back-to-back,
minutes caps on return from a layoff, road trips, and tip time (local and body clock).

    python3 scripts/nba_sched_research.py        # writes data/nba_sched_research.json (numpy; ~6 min)

Same walk-forward and bar as the fit (scripts/nba_games_fit.py): each season 2015-26 is scored by weights fit on the
seasons before it, with the shipped settings and inputs; a change is kept only if it cuts 2015-21 error at paired
per-game t <= -1.5 and 2022-26 (held out) does not get worse. Availability factors are measured on 2015-21 player
games only, so 2022-26 never sees them.
    players   played share (minutes-weighted, rotation players) and minutes when played / role minutes, on night two
              vs other nights, by age (31+) and role (28+ minutes), with and without an injury report; by season
    caps      minutes when played / role minutes in the first game back, by games missed in a row
    margins   the lineup term with night-two and return factors; road trip length, km in the last 7 days, the first
              home game after a long trip; matinee home edge, body-clock early / late for the road team
    totals    matinee, late tips (10 PM ET+), the two teams' body-clock hours
Research only (late Oct 2026). Earlier failures not redone here: b2b flag, road b2b, last-leg km, time zones, altitude,
games in 4 nights (rest days absorb them; data/nba_games_fit.json 'select').
"""
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as Fit
import harness as H

OUT = os.path.join(N.ROOT, 'data', 'nba_sched_research.json')
ET = ZoneInfo('America/New_York')
TUNE_TO = N.HOLD_FROM - 1             # factors measured on 2015-21 only
STAR = N.B2B_STAR


def r4(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 4)


def et_hour(g):
    t = N.tipdt(g).astimezone(ET)
    return t.hour + t.minute / 60, bool(t.dst())


def tz_of(team, dst):
    off = N.ARENA[team][2]
    return off - 1 if team == 'PHX' and dst else off      # Arizona keeps standard time


class M(N.Model):
    """the live model plus the schedule candidates: road trips, km in the last 7 days, tip time and body clock"""
    def __init__(self, names, P, **k):
        super().__init__(names, P, **k)
        self.trip = defaultdict(int)                     # team -> road games in a row (0 = last game at home)
        self.hist = defaultdict(list)                    # team -> [(tip, arena)] in the last 8 days

    def new_season(self, S):
        super().new_season(S)
        self.trip.clear(); self.hist.clear()

    def km_since(self, t, tip, arena, days):
        pts = [a for x, a in self.hist[t] if (tip - x).total_seconds() < days * 86400] + [arena]
        return sum(N.hav(N.ARENA[a], N.ARENA[b]) for a, b in zip(pts, pts[1:]))

    def feats(self, g):
        x, tx = super().feats(g)
        h, a = g['h'], g['a']
        tip = N.tipdt(g)
        eh, dst = et_hour(g)
        loc = eh + tz_of(h, dst)
        bodyA = eh + tz_of(a, dst)
        home = 0.0 if g['n'] else 1.0
        tripA = self.trip[a] + 1                         # this game's place in the road trip
        x.update({
            'tripA': min(tripA, 6) - 1.0,
            'trip3': 1.0 if tripA >= 3 else 0.0,
            'km7': (self.km_since(a, tip, h, 7) - self.km_since(h, tip, h, 7)) / 1000,
            'homeBack': 1.0 if self.trip[h] >= 3 else 0.0,     # first home game after a 3+ game road trip
            'mat': home * (1.0 if loc < 16.5 else 0.0),
            'bodyE': (1.0 if bodyA < 17.5 else 0.0) - (1.0 if loc < 17.5 else 0.0),
            'bodyL': (1.0 if bodyA >= 21.5 else 0.0),
            'body': bodyA - loc,                         # road team's clock minus the home team's, hours
        })
        tx.update({'tmat': 1.0 if loc < 16.5 else 0.0, 'tlate': 1.0 if eh >= 21.9 else 0.0,
                   'tbodyE': (1.0 if bodyA < 17.5 else 0.0) + (1.0 if loc < 17.5 else 0.0),
                   'tbodyL': 1.0 if bodyA >= 21.5 else 0.0})
        return x, tx

    def update(self, g):
        h, a = g['h'], g['a']
        tip = N.tipdt(g)
        for t in (h, a):
            self.hist[t].append((tip, h))
            self.hist[t] = [z for z in self.hist[t] if (tip - z[0]).total_seconds() < 8 * 86400]
        self.trip[h] = 0
        self.trip[a] += 1
        super().update(g)


def walk(games, names, P, params, inj):
    m = M(names, P, inj=inj, **params)
    out = []
    for g in games:
        x, tx = m.feats(g)
        out.append((g, x, tx))
        m.update(g)
    return out


def design(data):
    D = [(g, x, tx) for g, x, tx in data if g.get('fin') and g['S'] >= N.FIRST + 1]
    X = {f: np.array([x[f] for _, x, _ in D], float) for f in D[0][1]}
    TX = {f: np.array([tx[f] for _, _, tx in D], float) for f in D[0][2]}
    y = np.array([g['hs'] - g['as'] for g, _, _ in D], float)
    ty = np.array([g['hs'] + g['as'] for g, _, _ in D], float)
    S = np.array([g['S'] for g, _, _ in D])
    line = np.array([g['L'] if g.get('L') is not None else np.nan for g, _, _ in D])
    tline = np.array([g['T'] if g.get('T') else np.nan for g, _, _ in D])
    return D, X, TX, y, ty, S, line, tline


CL = None                             # clusters for the harness's paired t: game day, home team-season


def compare(pr, base, y, k1, k2):
    a1, b1 = np.abs(pr[k1] - y[k1]), np.abs(base[k1] - y[k1])
    a2, b2 = np.abs(pr[k2] - y[k2]), np.abs(base[k2] - y[k2])
    c = {'mae2015_21': r4(a1.mean()), 'd2015_21': r4(a1.mean() - b1.mean()), 't2015_21': round(Fit.paired_t(a1, b1), 2),
         'mae2022_26': r4(a2.mean()), 'd2022_26': r4(a2.mean() - b2.mean()), 't2022_26': round(Fit.paired_t(a2, b2), 2)}
    if CL is not None:
        c['tc2015_21'] = round(H.paired(a1, b1, [CL[0][k1], CL[1][k1]])['t'], 2)
        c['tc2022_26'] = round(H.paired(a2, b2, [CL[0][k2], CL[1][k2]])['t'], 2)
    c['passes'] = bool(c['t2015_21'] <= -1.5 and c['d2022_26'] <= 0)
    return c


def coef(Xm, y, names):
    """full-sample OLS: each input's points and t (the plain effect size)"""
    ok = ~np.isnan(y)
    Xm, y = Xm[ok], y[ok]
    b = np.linalg.lstsq(Xm, y, rcond=None)[0]
    r = y - Xm @ b
    cov = (r @ r / (len(y) - len(b))) * np.linalg.pinv(Xm.T @ Xm)
    return {f: {'pts': round(float(v), 3), 't': round(float(v / math.sqrt(cov[i, i])), 2)} for i, (f, v) in enumerate(zip(names, b))}


def players(rows):
    """night-two availability and minutes, by group and era; factors from 2015-21"""
    A = np.array([(r[0], r[1], r[2], r[4], r[5], r[6], r[8], r[9]) for r in rows], float)
    S, n2, rep, stk, R, age, pl, mn = A.T
    st = np.array([r[3] for r in rows])
    grp = np.array([r[7] for r in rows])
    clean = (st == '') & (stk == 0)                      # not on the report (or no report) and played last game

    def share(k):
        return float((R[k] * pl[k]).sum() / R[k].sum()) if k.sum() else float('nan')

    def mratio(k):
        k = k & (pl > 0)
        return float(mn[k].sum() / R[k].sum()) if k.sum() else float('nan')

    out = {'byGroup': {}, 'bySeason': {}, 'factors': Fit.measure_b2b(rows, TUNE_TO)}
    tune = S <= TUNE_TO
    for era, ek in (('rep', rep == 1), ('norep', rep == 0)):
        for g_ in sorted(set(grp)):
            k = clean & ek & (grp == g_)
            row = {}
            for blk, bk in (('2015_21', tune), ('2022_26', ~tune)):
                a, b = k & bk & (n2 == 1), k & bk & (n2 == 0)
                row[blk] = {'n2': int(a.sum()), 'played2': r4(share(a)), 'playedOther': r4(share(b)),
                            'min2': r4(mratio(a)), 'minOther': r4(mratio(b))}
            out['byGroup'][era + g_] = row
    for s in sorted(set(S.astype(int))):
        k = clean & (S == s)
        stars = k & (R >= STAR)
        out['bySeason'][int(s)] = {'report': bool(rep[S == s].mean() > 0.5),
                              'played2': r4(share(k & (n2 == 1))), 'playedOther': r4(share(k & (n2 == 0))),
                              'starPlayed2': r4(share(stars & (n2 == 1))), 'starPlayedOther': r4(share(stars & (n2 == 0))),
                              'min2': r4(mratio(k & (n2 == 1))), 'minOther': r4(mratio(k & (n2 == 0)))}
    # minutes caps: first game back, by games missed in a row (played only)
    caps = {}
    fac = {}
    base_m = mratio((stk == 0) & tune)
    for b in (1, 2, 3, 4):
        bk = np.array([N.bucket(int(s)) for s in stk]) == b
        k = bk & (pl > 0)
        caps[str(b)] = {'n2015_21': int((k & tune).sum()), 'min2015_21': r4(mratio(bk & tune)),
                        'n2022_26': int((k & ~tune).sum()), 'min2022_26': r4(mratio(bk & ~tune))}
        fac[str(b)] = r4(mratio(bk & tune) / base_m)
    out['caps'] = {'baseMin2015_21': r4(base_m), 'baseMin2022_26': r4(mratio((stk == 0) & ~tune)), 'byStreak': caps, 'factors': fac}
    return out


def main():
    games, names = N.load_hist()
    inj = Fit.load_inj()
    F = json.load(open(N.FIT))
    P, feats, params = F['P'], F['feats'], F['params']
    res = {'base': {'feats': feats, 'params': params}}

    rows = Fit.b2b_rows(games, names, inj, params, P)
    pp = players(rows)
    data = walk(games, names, P, params, inj)
    res['players'] = pp
    print(json.dumps(pp['factors']), json.dumps(pp['caps']['factors']), flush=True)

    D, X, TX, y, ty, S, line, tline = design(data)
    global CL
    CL = (np.array([g['tip'][:10] for g, _, _ in D]), np.array([f"{g['h']}{g['S']}" for g, _, _ in D]))
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM)
    k2 = S >= N.HOLD_FROM
    base = Fit.wf(Fit.mat(X, feats), y, S)
    res['base']['mae'] = compare(base, base, y, k1, k2)

    # lineup variants: night-two factors, return caps, both
    M_ = {}
    for tag, kw in (('b2b', {'b2b': pp['factors']}), ('caps', {'cap': pp['caps']['factors']}),
                    ('both', {'b2b': pp['factors'], 'cap': pp['caps']['factors']})):
        d2 = walk(games, names, P, {**params, **kw}, inj)
        Dv, Xv = design(d2)[:2]
        pr = Fit.wf(Fit.mat(Xv, feats), y, S)
        M_[tag] = compare(pr, base, y, k1, k2)
        dl = Xv['lin'] - X['lin']
        M_[tag]['linShift'] = {'games': int((np.abs(dl) > 1e-9).sum()), 'meanAbs': r4(np.abs(dl[np.abs(dl) > 1e-9]).mean()) if (np.abs(dl) > 1e-9).any() else 0}
        # the same games' residual vs the close: does the line already know?
        n2 = np.abs(dl) > 0.05
        ok = n2 & ~np.isnan(line)
        if ok.sum() > 30:
            M_[tag]['vsClose'] = {'games': int(ok.sum()), 'resultMinusClose': r4(np.mean(y[ok] - line[ok])),
                                  'shiftPts': r4(np.mean(dl[ok] * F['coef']['lin'])),
                                  'slope': r4(np.polyfit(dl[ok] * F['coef']['lin'], y[ok] - line[ok], 1)[0])}
        print(tag, M_[tag], flush=True)
    res['lineup'] = M_

    # schedule and tip-time candidates on the margin
    C = {}
    for c in ('tripA', 'trip3', 'km7', 'homeBack', 'mat', 'bodyE', 'bodyL', 'body'):
        pr = Fit.wf(Fit.mat(X, feats + [c]), y, S)
        C[c] = compare(pr, base, y, k1, k2)
        C[c]['effect'] = coef(Fit.mat(X, feats + [c]), y, feats + [c])[c]
        nz = X[c] != 0
        okl = nz & ~np.isnan(line)
        C[c]['games'] = int(nz.sum())
        # vs the close: result minus close regressed on the input (does the market leave it?)
        if okl.sum() > 30:
            Z = np.column_stack([np.ones(len(y)), X[c]])[~np.isnan(line)]
            C[c]['vsClose'] = coef(Z, (y - line)[~np.isnan(line)], ['one', c])[c]
        print(c, C[c], flush=True)
    res['margin'] = C

    # totals
    TF = N.TFEATS
    tb = Fit.wf(Fit.mat(TX, TF), ty, S)
    T = {'base': compare(tb, tb, ty, k1, k2)}
    for c in ('tmat', 'tlate', 'tbodyE', 'tbodyL'):
        pr = Fit.wf(Fit.mat(TX, TF + [c]), ty, S)
        T[c] = compare(pr, tb, ty, k1, k2)
        T[c]['effect'] = coef(Fit.mat(TX, TF + [c]), ty, TF + [c])[c]
        T[c]['games'] = int((TX[c] != 0).sum())
        okt = ~np.isnan(tline)
        Z = np.column_stack([np.ones(okt.sum()), TX[c][okt]])
        T[c]['vsClose'] = coef(Z, (ty - tline)[okt], ['one', c])[c]
        print(c, T[c], flush=True)
    res['totals'] = T
    with open(OUT, 'w') as f:
        # Hugo's JSON loader rejects NaN (it broke the site build); undefined stats are null.
        f.write(json.dumps(res, indent=1).replace(': NaN', ': null'))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
