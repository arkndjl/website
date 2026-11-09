#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB matchup, combo and size terms against the close ("head to head metrics, combo metrics, team
badges ... good rebounding teams vs high 3 pt shooting teams, tempo vs tempo"; "test team size in the game model").
Research only; results in data/cbb_matchup_research.json.

Harness, values and scoring are scripts/style_research.py's (Oct 29, 52 terms, none passed; its nine CBB terms are
not rerun): each team's season-to-date rate before the game, shrunk to half last season / half the league worth 6
games, z within season; margin terms antisymmetric A(h)B(a) - A(a)B(h), totals symmetric; outcome result - close,
tune 2016-21, held 2022-26, errors clustered by day.

Pre-registered before any outcome was seen (11 tests, one family):
  dreb_vs3   margin  defensive rebound % x the opponent's 3PA/FGA (long rebounds off a 3-heavy offense)     0
  orb_vs3    margin  offensive rebound % x the opponent's 3PA/FGA allowed (more misses off the glass)       0
  efg_x      margin  eFG% x the opponent's eFG% allowed (the shooting factor battle)                         +
  3p_x       margin  3P% x the opponent's 3P% allowed                                                       +
  ppp_x      margin  points a possession x the opponent's points a possession allowed (offense vs defense)  +
  topO_topD  margin  badge combo: Top Offense (top quarter of points a possession) against a Top Defense
                     (top quarter of points a possession allowed), 1/0 x 1/0                               0
  tempo_gap  margin  (the opponent's pace - own pace) x |pace gap|: the slower side imposing itself          0
  tempo_T    totals  pace x the opponent's pace (multiplicative tempo clash)                                0
  hgt        margin  minutes-weighted height (Barttorvik player heights x game minutes, season to date),
                     home minus away: size beyond the close                                                 0
  hgt_orb    margin  height x the opponent's offensive rebound % allowed                                    +
  hgt_3p     margin  height x the opponent's 3PA/FGA (size against a 3-heavy offense)                       0
Pass: style_research's split rule (tune t >= 1.5 in the expected direction, held b same sign, held-out squared error
of close + b x at paired t <= -1.5) AND Holm family-wise .05 on the two-sided Stouffer z of tune and held.
Joint check: all eleven in one ridge on tune (lambda by tune-season CV), held-out SE vs the close.

    python3 scripts/cbb_matchup_research.py
"""
import collections
import datetime
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H        # noqa: E402
import style_research as SR  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'cbb_matchup_research.json')
SIGN = {'dreb_vs3': 0, 'orb_vs3': 0, 'efg_x': 1, '3p_x': 1, 'ppp_x': 1, 'topO_topD': 0, 'tempo_gap': 0, 'tempo_T': 0,
        'hgt': 0, 'hgt_orb': 1, 'hgt_3p': 0}
EXTRA = ['efg', 'efg_al', '3p_al', 'ppp', 'ppp_al', 'hgt']


def heights():
    """(season, Barttorvik team, date) -> (sum minutes x inches, sum minutes) from the game logs and research heights"""
    import cbb_games as C
    by = C.research_seasons()
    out = {}
    for y in range(2015, 2027):
        hti = {}
        for yy in (y, y - 1):
            for pid, r in by.get(yy, {}).items():
                try:
                    h = float(r.get('hti') or 'nan')
                except ValueError:
                    continue
                if 66 <= h <= 90:
                    hti.setdefault(pid, h)
        for t, gl in C.bt_logs(y).items():
            for d, pl in gl:
                num = den = 0.0
                for pid, (m, _) in pl.items():
                    pid = str(pid)
                    if pid in hti and m > 0:
                        num += m * hti[pid]; den += m
                if den > 100:
                    out[(y, t, d)] = (num, den)
    return out


def patch_sides(HT):
    """style_research.bb_sides plus eFG, 3P% allowed, points a possession and height; the CBB event loop passes no
    team or date, so heights ride in through the box dicts (key '_h')"""
    base = SR.bb_sides

    def sides(fh, fa):
        out = base(fh, fa)
        for o, me, op in ((out[0], fh, fa), (out[1], fa, fh)):
            P = o['tov'][1]
            o['efg'] = (me['fgm'] + 0.5 * me['fg3m'], me['fga'])
            o['efg_al'] = (op['fgm'] + 0.5 * op['fg3m'], op['fga'])
            o['3p_al'] = (op['fg3m'], op['fg3a'])
            o['ppp'] = (me['pts'], P)
            o['ppp_al'] = (op['pts'], P)
            if me.get('_h'):
                o['hgt'] = me['_h']
        return out
    SR.bb_sides = sides
    SR.BB_STATS = SR.BB_STATS + EXTRA


def cbb_rows(HT):
    """style_research.cbb with the extra stats; heights joined by (season, team, date)"""
    import ast
    import csv
    orig_eval = ast.literal_eval
    patch_sides(HT)
    # style_research.cbb builds box dicts inside; wrap bb_sides once more to attach heights from the current row
    cur = {}
    inner = SR.bb_sides

    def sides(f1, f2):
        if cur:
            f1 = dict(f1, _h=HT.get((cur['y'], cur['n1'], cur['d'])))
            f2 = dict(f2, _h=HT.get((cur['y'], cur['n2'], cur['d'])))
            f1['_h'] = (f1['_h'][0] / f1['_h'][1], 1.0) if f1['_h'] else None
            f2['_h'] = (f2['_h'][0] / f2['_h'][1], 1.0) if f2['_h'] else None
        return inner(f1, f2)
    SR.bb_sides = sides
    real_reader = csv.reader

    def reader(fh, *a, **k):
        y = int(os.path.basename(fh.name)[6:10])
        for r in real_reader(fh, *a, **k):
            if len(r) >= 30:
                try:
                    b = orig_eval(r[29])
                    mo, dd, yy = b[0].split('/')
                    d = datetime.date(int(yy) + (2000 if len(yy) == 2 else 0), int(mo), int(dd))
                    cur.update(y=y, n1=b[2], n2=b[3], d=d.isoformat())
                except Exception:
                    cur.clear()
            yield r
    SR.csv.reader = reader
    try:
        rows = SR.cbb()
    finally:
        SR.csv.reader = real_reader
    return rows


def terms(rows):
    SR.zs(rows, SR.BB_STATS)
    Z, NEG, term = SR.Z, SR.NEG, SR.term
    # quarter cuts within season for the badge combo (raw values, both sides)
    cut = collections.defaultdict(dict)
    for k, hi in (('ppp', True), ('ppp_al', False)):
        by = collections.defaultdict(list)
        for r in rows:
            for s in ('h', 'a'):
                v = r['st'][s].get(k)
                if v is not None:
                    by[r['S']].append(v)
        for S, v in by.items():
            cut[S][k] = np.percentile(v, 75 if hi else 25)
    for r in rows:
        for s in ('h', 'a'):
            st, z = r['st'][s], r['z'][s]
            z['topO'] = None if st.get('ppp') is None else float(st['ppp'] >= cut[r['S']]['ppp'])
            z['topD'] = None if st.get('ppp_al') is None else float(st['ppp_al'] <= cut[r['S']]['ppp_al'])
            z['one'] = 1.0
    gap = []
    for r in rows:
        try:
            d = r['z']['a']['pace'] - r['z']['h']['pace']        # + when home is the slower side
            gap.append(d * abs(d))
        except TypeError:
            gap.append(np.nan)
    hg = []
    for r in rows:
        a, b = r['z']['h'].get('hgt'), r['z']['a'].get('hgt')
        hg.append(a - b if a is not None and b is not None else np.nan)
    return {
        'dreb_vs3': (term(rows, NEG('orb_al'), Z('3pa'), False), False),
        'orb_vs3': (term(rows, Z('orb'), Z('3pa_al'), False), False),
        'efg_x': (term(rows, Z('efg'), Z('efg_al'), False), False),
        '3p_x': (term(rows, Z('3p'), Z('3p_al'), False), False),
        'ppp_x': (term(rows, Z('ppp'), Z('ppp_al'), False), False),
        'topO_topD': (term(rows, Z('topO'), Z('topD'), False), False),
        'tempo_gap': (np.array(gap, float), False),
        'tempo_T': (term(rows, Z('pace'), Z('pace'), True), True),
        'hgt': (np.array(hg, float), False),
        'hgt_orb': (term(rows, Z('hgt'), Z('orb_al'), False), False),
        'hgt_3p': (term(rows, Z('hgt'), Z('3pa'), False), False),
    }


def holm(z, alpha=0.05):
    p = {k: 2 * (1 - 0.5 * (1 + math.erf(abs(v) / math.sqrt(2)))) for k, v in z.items()}
    order = sorted(p, key=p.get)
    ok = {}
    for j, k in enumerate(order):
        if p[k] > alpha / (len(order) - j):
            break
        ok[k] = True
    return p, ok


def joint(rows, T, tune_yrs):
    """all margin terms in one ridge on result - close (lambda by leave-one-tune-season-out), held-out SE vs the close"""
    ks = [k for k, (_, tot) in T.items() if not tot]
    X = np.c_[[T[k][0] for k in ks]].T
    y = np.array([r['ym'] - r['cm'] if r['ym'] is not None and r['cm'] is not None else np.nan for r in rows])
    ok = ~np.isnan(X).any(1) & ~np.isnan(y)
    X, y = X[ok], y[ok]
    S = np.array([r['S'] for r, o in zip(rows, ok) if o]); day = np.array([r['day'] for r, o in zip(rows, ok) if o])
    tune = np.isin(S, list(tune_yrs))
    mu, sd = X[tune].mean(0), X[tune].std(0)
    Zx = (X - mu) / sd

    def fit(m, lam):
        A = np.c_[np.ones(m.sum()), Zx[m]]
        P = np.eye(A.shape[1]) * lam; P[0, 0] = 0
        return np.linalg.solve(A.T @ A + P, A.T @ y[m])
    best = None
    for lam in (1e2, 1e3, 1e4, 1e5, 1e6):
        e = 0.0
        for s in sorted(set(S[tune])):
            tr, te = tune & (S != s), tune & (S == s)
            b = fit(tr, lam)
            e += float(((y[te] - b[0] - Zx[te] @ b[1:]) ** 2).sum() - ((y[te] - y[tr].mean()) ** 2).sum())
        if best is None or e < best[0]:
            best = (e, lam)
    b = fit(tune, best[1])
    held = ~tune
    new = b[0] + Zx[held] @ b[1:]
    pr = H.paired((y[held] - new) ** 2, (y[held] - y[tune].mean()) ** 2, cluster=day[held])
    return {'terms': ks, 'lambda': best[1], 'tuneCvGain': round(best[0], 1), 'coef': dict(zip(ks, [round(float(v), 4) for v in b[1:]])),
            'seHeld': [round(float(pr['d']), 6), round(pr['t'], 2)]}


def main():
    HT = heights()
    print('heights', len(HT), flush=True)
    rows = cbb_rows(HT)
    T = terms(rows)
    cover = round(float(np.mean(~np.isnan(T['hgt'][0]))), 3)
    print('height coverage', cover, flush=True)
    res = {}
    for k, (x, tot) in T.items():
        res[k] = SR.score(rows, x, tot, SR.TUNE['cbb'], SIGN[k])
        o = res[k]
        print(f"{k:10} n {o['n']}  tune {o['tune']} held {o['held']} held SE {o['seHeld']}  z {o['z']}  model {o.get('model')}", flush=True)
    p, ok = holm({k: o['z'] for k, o in res.items()})
    for k, o in res.items():
        o['p'], o['holm'] = round(p[k], 5), bool(ok.get(k))
        o['pass'] = bool(o['pass_split'] and o['holm'])
    J = joint(rows, T, SR.TUNE['cbb'])
    print('joint', J, flush=True)
    json.dump({'asof': datetime.date.today().isoformat(), 'tests': len(res), 'heightCoverage': cover, 'terms': res, 'joint': J},
              open(OUT, 'w'), indent=1)
    for k, o in res.items():
        print(f"{k:10} z {o['z']:6} p {o['p']}  split {o['pass_split']}  holm {o['holm']}  {'PASS' if o['pass'] else ''}")


if __name__ == '__main__':
    main()
