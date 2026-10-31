#!/usr/bin/env python3
"""Age in the backup watch (Noah, Oct 31 2026: a backup younger than the starter he sits behind should rank above a
veteran backup). Fits how much the age gap (starter's age - backup's) adds to today's grade gap in predicting the gap
over the next two seasons, and writes the terms the backup watch ranks by: data/backup_age.json.

    python3 scripts/backup_age_fit.py [path to research_seasons.csv]

Backtest, per sport with past seasons on file. Each season, the starters are the most-used players at each spot
(the backup watch's shapes, from minutes: there are no past depth charts), the next as many the 2nd and 3rd string,
and a backup is a pair when his grade (the backup watch's: weighted seasons, shrunk) beats the lowest-graded starter
at his spot. Target: the pair's gap over the next two seasons (minutes-weighted rate, same shrink; a player who
leaves the league or the team's data counts at replacement). Model: target = a + b gap + c age gap. Walk-forward: each
season is predicted by pairs whose two-season target was complete before it; scored against gap alone (paired squared
errors, t). Coefficients shipped are the full-sample fit.

  nba     static/data/nba-xpm/ (XPM; age in years)
  nhl     static/data/nhl-war/ (HPM; age in years)
  soccer  static/data/soccer-war/ (GAR a 90; age from the Transfermarkt birth dates, scripts/data/soccer_mv_link)
  cbb     the CBB research seasons (BPM, which the history has; the age gap is the class gap, Fr 1 .. Sr 4, the
          only age the college boards carry for everyone). Departures dominate: a senior starter is gone next season.
  nfl     no past seasons on file: borrows the pro sports' fit in standard-deviation units of the gap
  cfb     no past seasons on file: borrows the CBB fit in standard-deviation units of the gap
The board's live grade for CBB is FV, not BPM, so CBB also ships the SD-unit fit.
"""
import gzip
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'backup_age.json')
RESEARCH = '/mnt/project-files/cbb/backtest/research_seasons.csv'
H = 2                                                        # target horizon, seasons


def seasons(sub):
    D = os.path.join(ROOT, 'static', 'data', sub)
    return {int(f[:4]): json.load(open(os.path.join(D, f))) for f in os.listdir(D) if f[:4].isdigit()}


def rate(by, pid, ys, w, val, use, k, r):
    num = den = 0.0
    for y, wt in zip(ys, w):
        p = by.get(y, {}).get(pid)
        if p and val(p) is not None and use(p):
            num += wt * use(p) * val(p); den += wt * use(p)
    return (num + k * r) / (den + k)


def pro_pairs(S, key, team, grp, shape, nxt, val, use, age, k, repl, w, mn):
    """[(season, gap, age gap, two-season future gap)] for one sport's seasons S"""
    by = {y: {key(p): p for p in d['players']} for y, d in S.items()}
    gof = {}
    for d in S.values():
        for p in d['players']:
            gof[key(p)] = grp(p)
    last = max(S)                                            # the season in progress: never a target
    out = []
    for y in sorted(S):
        if y - len(w) + 1 not in S or y + H >= last:
            continue
        g = lambda pid: rate(by, pid, [y - j for j in range(len(w))], w, val, use, k(gof[pid]), repl(y, gof[pid]))
        f = lambda pid: rate(by, pid, [y + j for j in range(1, H + 1)], [1] * H, val, use, k(gof[pid]), repl(y, gof[pid]))
        rooms = {}
        for p in S[y]['players']:
            if val(p) is None or not use(p) or age(p, y) is None or team(p) in ('TOT', '2TM', '3TM'):
                continue
            rooms.setdefault(team(p), {}).setdefault(grp(p), []).append(p)
        for R in rooms.values():
            st = {}
            for gp, L in R.items():
                L.sort(key=lambda p: -use(p))
                if len(L) >= shape[gp]:
                    st[gp] = L[:shape[gp]]
            for gp, L in R.items():
                n = shape[gp]
                sg = next((h for h in nxt.get(gp, [gp]) if h in st), None)
                if sg is None:
                    continue
                gs, s = min(((g(key(x)), x) for x in st[sg]), key=lambda t: t[0])
                for b in L[n:3 * n]:
                    gb = g(key(b))
                    if use(b) < mn or gb <= gs:
                        continue
                    out.append((y, gb - gs, age(s, y) - age(b, y), f(key(b)) - f(key(s))))
    return out


def cbb_pairs(path):
    import pandas as pd
    d = pd.read_csv(path, usecols=['pid', 'team', 'year', 'cls', 'gp', 'min_per', 'bpm', 'guard', 'big'])
    d = d.dropna(subset=['bpm', 'min_per', 'cls', 'gp'])
    K, REP = 20.0, -6.0                                      # BPM shrunk to replacement with 20 games of 30 min shares
    d['m'] = d.min_per * d.gp / 30.0
    d['g'] = (d.bpm * d.m + K * REP) / (d.m + K)
    d['grp'] = np.where(d.guard > .5, 'G', np.where(d.big > .5, 'C', 'F'))
    by = {(r.pid, r.year): (r.bpm, r.m) for r in d.itertuples()}

    def fut(pid, y):
        num = den = 0.0
        for j in range(1, H + 1):
            x = by.get((pid, y + j))
            if x:
                num += x[0] * x[1]; den += x[1]
        return (num + K * REP) / (den + K)
    last = int(d.year.max())
    nxt = {'G': ['G', 'F'], 'F': ['F', 'C', 'G'], 'C': ['C', 'F']}
    out = []
    for (_, y), L in d.groupby(['team', 'year']):
        if y + H > last:
            continue
        L = L.sort_values('min_per', ascending=False)
        st = L.iloc[:5]
        for b in L.iloc[5:15].itertuples():
            sg = next((h for h in nxt[b.grp] if (st.grp == h).any()), None)
            if sg is None:
                continue
            s = st[st.grp == sg].sort_values('g').iloc[0]
            if b.g <= s.g:
                continue
            out.append((int(y), b.g - s.g, float(s.cls - b.cls), fut(b.pid, y) - fut(s.pid, y)))
    return out


def fit(P, start_after=4):
    """walk-forward test of gap + age gap vs gap alone, and the full-sample coefficients"""
    P = np.array(P, float)
    ys = sorted(set(P[:, 0].astype(int)))
    e0, e1 = [], []
    for y in ys[start_after:]:
        tr, te = P[P[:, 0] + H <= y], P[P[:, 0] == y]
        if len(tr) < 100 or not len(te):
            continue
        for cols, e in (([1], e0), ([1, 2], e1)):
            X = np.c_[np.ones(len(tr)), tr[:, cols]]
            b = np.linalg.lstsq(X, tr[:, 3], rcond=None)[0]
            e += list((np.c_[np.ones(len(te)), te[:, cols]] @ b - te[:, 3]) ** 2)
    d = np.array(e1) - np.array(e0)
    X = np.c_[np.ones(len(P)), P[:, 1:3]]
    b = np.linalg.lstsq(X, P[:, 3], rcond=None)[0]
    sd = float(P[:, 1].std())
    return {'n': len(P), 'held': len(d), 'seasons': [int(ys[0]), int(ys[-1])], 'mse_gap': round(float(np.mean(e0)), 6),
            'mse_age': round(float(np.mean(e1)), 6), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
            'a': float(b[0]), 'b': float(b[1]), 'c': float(b[2]), 'sd': sd,
            'z': {'a': float(b[0]) / sd, 'b': float(b[1]), 'c': float(b[2]) / sd}}


def live_sd(sport):
    rows = json.load(open(os.path.join(ROOT, 'data', f'backup_{sport}.json')))['rows']
    return float(np.std([r['gap'] for r in rows])) if len(rows) > 2 else None


def main():
    old = json.load(open(OUT)) if os.path.exists(OUT) else {'sports': {}}
    F = {}
    nba = seasons('nba-xpm')
    F['nba'] = fit(pro_pairs(nba, key=lambda p: p['id'], team=lambda p: p['tm'],
                             grp=lambda p: {'PG': 'G', 'SG': 'G', 'SF': 'F', 'PF': 'F', 'C': 'C'}.get(p['pos'].split('-')[0], 'F'),
                             shape={'G': 2, 'F': 2, 'C': 1}, nxt={'G': ['G', 'F'], 'F': ['F', 'C', 'G'], 'C': ['C', 'F']},
                             val=lambda p: p.get('xpm'), use=lambda p: p['mp'], age=lambda p, y: p.get('age'),
                             k=lambda g: 500, repl=lambda y, g: -2.0, w=(1, .5, .25), mn=50))
    nhl = seasons('nhl-war')
    F['nhl'] = fit(pro_pairs(nhl, key=lambda p: p['id'], team=lambda p: p['tm'], grp=lambda p: p['pos'],
                             shape={'C': 1, 'L': 1, 'R': 1, 'D': 2, 'G': 1}, nxt={},
                             val=lambda p: p.get('hpm'), use=lambda p: p.get('toi') or 0, age=lambda p, y: p.get('age'),
                             k=lambda g: 1500 if g == 'G' else 600,
                             repl=lambda y, g: nhl[y].get('repl', {}).get('G' if g == 'G' else 'D' if g == 'D' else 'F', 0.0),
                             w=(1, .5, .25), mn=100))
    link = json.load(gzip.open(os.path.join(HERE, 'data', 'soccer_mv_link.json.gz'), 'rt'))
    dob = {u: link['dob'].get(str(t)) for u, t in link['p'].items()}
    sage = lambda p, y: (y - 1 + 8 / 12 - (int(dob[p['p']][:4]) + (int(dob[p['p']][5:7]) - 1) / 12)) if dob.get(p['p']) else None
    F['soccer'] = fit(pro_pairs(seasons('soccer-war'), key=lambda p: p['p'], team=lambda p: p['team'], grp=lambda p: p['pos'],
                                shape={'GK': 1, 'D': 4, 'M': 4, 'F': 2}, nxt={},
                                val=lambda p: p.get('gar90'), use=lambda p: p['min'], age=sage,
                                k=lambda g: 900, repl=lambda y, g: 0.0, w=(1, .5), mn=270))
    path = sys.argv[1] if len(sys.argv) > 1 else RESEARCH
    if os.path.exists(path):
        F['cbb'] = fit(cbb_pairs(path))
    elif 'cbb' in old['sports']:
        F['cbb'] = old['sports']['cbb']; print('cbb: research seasons missing, kept the last fit')
    pros = [F[s]['z'] for s in ('nba', 'nhl', 'soccer')]
    zp = {k: float(np.mean([z[k] for z in pros])) for k in ('a', 'b', 'c')}
    out = {}
    for s in ('nba', 'nhl', 'soccer'):          # own fit, in the grade's units
        f = F[s]
        out[s] = {'a': round(f['a'], 5), 'b': round(f['b'], 4), 'c': round(f['c'], 5), 'unit': 'year', 'src': 'fit',
                  **{k: f[k] for k in ('n', 'held', 'seasons', 't')}}
    for s, z, src, unit in (('nfl', zp, 'pros', 'year'), ('cbb', F['cbb']['z'], 'fit-sd', 'class'),
                            ('cfb', F['cbb']['z'], 'cbb', 'class')):
        sd = live_sd(s) or (old['sports'].get(s) or {}).get('sd') or 1.0
        out[s] = {'a': round(z['a'] * sd, 5), 'b': round(z['b'], 4), 'c': round(z['c'] * sd, 5), 'unit': unit, 'src': src,
                  'sd': round(sd, 4)}
        if s == 'cbb':
            out[s].update({k: F['cbb'][k] for k in ('n', 'held', 'seasons', 't')})
    for s, f in F.items():
        print(f"{s:7s} pairs {f['n']:5d} held {f['held']:5d} mse {f['mse_gap']:.5g} -> {f['mse_age']:.5g} t {f['t']:+.2f}  "
              f"a {f['a']:+.4f} b {f['b']:.3f} c {f['c']:+.5f} / yr")
    txt = json.dumps({'asof': time.strftime('%Y-%m-%d'), 'horizon': H, 'sports': out}, indent=1, allow_nan=False)
    open(OUT + '.tmp', 'w').write(txt); os.replace(OUT + '.tmp', OUT)        # a failed run never leaves a broken data file
    print('wrote', OUT)


if __name__ == '__main__':
    main()
