#!/usr/bin/env python3
"""Research (Oct 30 2026): an age term on the NFL QB value, in the form that passed for the NHL lineup value (PR #583).

    python3 scripts/nfl_aging_research.py     # numpy; writes data/nfl_aging_research.json

The QB term prices the starter at his career EPA a play (seasons carried at .7 each summer, shrunk toward a backup's
level with qb_n0 plays) against the team's recent QB play. Nothing ages him: a second-year QB and a 39-year-old open
the season at last season's line. Non-QBs already age (nfl_roster.py's projection has a pooled curve; the kept roster's
aging failed as a game input, Oct 21), so this tests the QB.

Age line: each season s, every QB with 50+ carried plays and 100+ plays in s: his EPA a play in s minus his qbval at
the start of s, weighted by plays, on his age on Sep 1 (clipped 21-40, centred 28), seasons before the one being
priced only, net of the overall mean so the average QB keeps his value. Variants:
    shift     the line moves each QB's carried career mean at the summer (so it fades as he throws), through the
              live qb term and its fitted weight
    shiftQ    the same with a quadratic
    qage      the starter's age line (home minus away, x38 like qb) as its own input, all season
    qageF     the same faded by 0.5 ** (team games / 8)
Scored like the fit (nfl_games.fit): walk-forward least squares, MAE and log loss (normal, model sd) on 2015-20
(tuning) and 2021-25 (held out); kept at paired MAE t <= -1.5 on 2015-20 and 2021-25 no worse.
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nfl_games as N  # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'nfl_aging_research.json')
LAST = 2025
A0, ALO, AHI = 28.0, 21.0, 40.0


def births():
    out = {}
    for r in N.rows(os.path.join(N.CACHE, 'players.csv')):
        if r['birth_date'] and r['gsis_id']:
            out[r['gsis_id']] = r['birth_date']
    return out


BIRTH = births()


def age(g, s):
    b = BIRTH.get(g)
    if not b:
        return None
    y, m, d = int(b[:4]), int(b[5:7]), int(b[8:10])
    return s - y - ((m - 9) * 30.4 + d) / 365.25


class AgedModel(N.Model):
    def __init__(self, form='none', **kw):
        super().__init__(**kw)
        self.form = form
        self.pairs = []            # (season, age, actual - prior, plays)
        self.start = {}            # gsis -> (prior qbval, carried plays) at this season's start
        self.seas = defaultdict(lambda: [0.0, 0.0])
        self.line = None
        self.tg = defaultdict(int)

    def fit_line(self, s):
        P = [p for p in self.pairs if p[0] < s]
        if len(P) < 150:
            return None
        x = np.array([min(max(p[1], ALO), AHI) - A0 for p in P]); y = np.array([p[2] for p in P]); w = np.array([p[3] for p in P])
        cols = [np.ones(len(x)), x] + ([x * x] if self.form == 'shiftQ' else [])
        A = np.column_stack(cols)
        b = np.linalg.solve(A.T @ (A * w[:, None]) + 1e-6 * np.eye(A.shape[1]), A.T @ (w * y))
        mu = np.average(y, weights=w)
        return lambda a: float(b[0] - mu + sum(b[i] * (min(max(a, ALO), AHI) - A0) ** i for i in range(1, len(b))))

    def new_season(self, s):
        # close last season's pairs
        if self.season is not None:
            for gq, (pr, n) in self.start.items():
                e, k = self.seas.get(gq, (0.0, 0.0))
                a = age(gq, self.season)
                if n >= 50 and k >= 100 and a is not None:
                    self.pairs.append((self.season, a, e / k - pr, k))
        super().new_season(s)
        self.line = self.fit_line(s)
        self.seas = defaultdict(lambda: [0.0, 0.0])
        self.tg = defaultdict(int)
        self.start = {gq: (self.qbval(gq), q[1]) for gq, q in self.qb.items()}
        if self.line and self.form in ('shift', 'shiftQ'):
            for gq, q in self.qb.items():
                a = age(gq, s)
                if a is not None and q[1] > 0:
                    q[0] += self.line(a) * q[1]

    def qdelta(self, gq, s):
        if not gq or not self.line:
            return 0.0
        a = age(gq, s)
        return self.line(a) if a is not None and self.qb[gq][1] > 0 else 0.0

    def feats(self, g):
        x, tx = super().feats(g)
        s = int(g['season']); h, a = N.team(g['home_team']), N.team(g['away_team'])
        d = (self.qdelta(g['home_qb_id'], s) - self.qdelta(g['away_qb_id'], s)) * 38
        x['qage'] = d
        x['qageF'] = (self.qdelta(g['home_qb_id'], s) * 0.5 ** (self.tg[h] / 8) - self.qdelta(g['away_qb_id'], s) * 0.5 ** (self.tg[a] / 8)) * 38
        return x, tx

    def update(self, g, box, qbs):
        if g['home_score'] not in ('', 'NA'):
            h, a = N.team(g['home_team']), N.team(g['away_team'])
            for t in (h, a):
                for k, q in N.qbs_for(qbs, g['game_id'], t):
                    self.seas[k][0] += q['epa']; self.seas[k][1] += q['plays']
                self.tg[t] += 1
        super().update(g, box, qbs)


def main():
    F = json.load(open(N.FIT)); params = F['params']
    games, box, qbs = N.load(LAST)
    N.index_qbs(qbs, games); N.load_qb_teams(LAST)
    inj = N.injury_history(games, range(N.INJ_FIRST, LAST + 1))
    played = lambda g: g['home_score'] not in ('', 'NA')

    def run(form):
        m = AgedModel(form=form, **params)
        data = []
        for g in games:
            x, tx = m.feats(g)
            data.append((g, x))
            m.update(g, box, qbs)
        for g, x in data:
            r = inj.get(g['game_id'])
            if r:
                x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D = [(g, x) for g, x in data if played(g) and int(g['season']) >= 2012]
        return D, m

    def wf(D, feats):
        X = np.array([[x[f] for f in feats] for _, x in D]); y = np.array([N.num(g['result']) for g, _ in D])
        S = np.array([int(g['season']) for g, _ in D])
        pred = np.full(len(y), np.nan)
        for s in range(2015, LAST + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        return pred, y, S

    D0, m0 = run('none')
    ref, y, S = wf(D0, N.FEATS)
    k = ~np.isnan(ref)
    sd = float(np.std((ref - y)[k]))
    win = (y > 0).astype(float); dec = y != 0
    from math import erf

    def ll(pr):
        p = np.clip(0.5 * (1 + np.vectorize(erf)(pr / sd / math.sqrt(2))), 1e-6, 1 - 1e-6)
        return -(win * np.log(p) + (1 - win) * np.log(1 - p))

    def pt(a, b):
        d = a - b
        return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    l0 = ll(ref)
    out = {'line': {}, 'variants': []}
    # the line as it stood before each season (fit through the season before)
    for s in (2015, 2021, 2026):
        m0.form = 'shift'
        f = m0.fit_line(s)
        out['line'][str(s)] = {str(a): round(f(a), 3) for a in (22, 24, 26, 28, 30, 32, 34, 36, 38, 40)} if f else None
    m0.form = 'shiftQ'
    fq = m0.fit_line(2026)
    out['lineQ2026'] = {str(a): round(fq(a), 3) for a in (22, 24, 26, 28, 30, 32, 34, 36, 38, 40)}
    out['pairs'] = len(m0.pairs)
    print(json.dumps(out), flush=True)

    def score(pr, lab):
        r = {'label': lab}
        e, e0, l = np.abs(pr - y), np.abs(ref - y), ll(pr)
        for nm, kk in (('2015_20', (S >= 2015) & (S <= 2020)), ('2021_25', S >= 2021)):
            r[nm] = {'n': int(kk.sum()), 'mae': round(float(e[kk].mean()), 4), 'd': round(float(e[kk].mean() - e0[kk].mean()), 4),
                     't': round(pt(e[kk], e0[kk]), 2), 'llD': round(float(l[kk & dec].mean() - l0[kk & dec].mean()), 5),
                     'llT': round(pt(l[kk & dec], l0[kk & dec]), 2)}
        wk = np.array([N.num(g['week']) for g, _ in D]) if False else None
        r['seasons'] = f"{sum(e[S == s].mean() < e0[S == s].mean() for s in range(2015, LAST + 1))}/{LAST - 2014}"
        r['kept'] = r['2015_20']['t'] <= -1.5 and r['2021_25']['d'] <= 0
        print(json.dumps(r), flush=True)
        out['variants'].append(r)
    for form in ('shift', 'shiftQ'):
        D, _ = run(form)
        score(wf(D, N.FEATS)[0], form)
    score(wf(D0, N.FEATS + ['qage'])[0], 'qage')
    score(wf(D0, N.FEATS + ['qageF'])[0], 'qageF')
    with open(OUT, 'w') as fh:
        json.dump(out, fh, indent=1)


if __name__ == '__main__':
    main()
