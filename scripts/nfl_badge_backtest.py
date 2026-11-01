#!/usr/bin/env python3
"""Backtest: do NFL trait badges (scripts/nfl_badges.py) predict next season's board WAR beyond this season's WAR?

    python3 scripts/nfl_xv.py --prep      # the player-season cache 2018-25 (scripts/.cache/nfl/xv_<y>.json), if missing
    python3 scripts/nfl_badge_backtest.py # -> data/nfl_badge_backtest.json (numpy)

Universe: every player-season 2018-24 in a badge's position pool (snaps on his side >= 300), one row per player (teams
summed). Board WAR as the board builds it: .4 XV (data/nfl_xv.json weights) + .6 AV WAR (nfl_xv's per-row WAR).
Outcome: next season's board WAR (0 when he plays no snaps: out of the league is no value).
Control (held fixed): this season's WAR, by position (position dummies and WAR x position), and age, age^2.
Badge value: the rate regressed by volume with its own k (from the year-to-year r, consecutive seasons both in the pool),
z'd within position and season. Tests, per badge:
  t         the badge's coefficient over its cluster-robust SE, clustered by player (CR1)
  oosGain   leave one season out (7 folds): out-of-sample R^2 with the badge minus without (x100: 1.0 = one point)
  pass      t >= 2 (positive: a badge is a good thing), oosGain > 0, and year-to-year r >= .15
  joint     the passers fit together (z 0 at positions a badge doesn't cover); the weakest is dropped while its joint
            t < 2, so two badges measuring one thing don't both ship
Results (Nov 1 2026): one of 21 ships, WR/TE Target Magnet (targets a snap; r .77, t +4.2, OOS +.80, +.029 WAR a
season per SD). Chain Mover (WR/TE first downs a snap) passed alone (t +3.1, OOS +.43) but is the same trait and drops
in the joint fit. Every QB, RB and defensive badge failed: none reaches t 2 positive. Efficiency rates (rushing EPA a
carry t -3.6, receiving EPA a target t -6.1) come out negative: XV already prices them and they regress. No FV hook:
the WAR board has no projection to add a badge to.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_war as W   # noqa: E402
import nfl_xv as X   # noqa: E402
import nfl_badges as B   # noqa: E402

YEARS = list(range(2018, 2026))
BASE = YEARS[:-1]
OUT = B.BT


def data():
    S = X.load()
    assert all(y in S for y in YEARS), 'run python3 scripts/nfl_xv.py --prep first'
    X.zscore(S)
    M = json.load(open(X.OUT))['model']
    _, value, _ = W.sub_lines()
    rows, war = {}, defaultdict(float)
    for y in YEARS:
        for p, xv in zip(S[y]['players'], X.xv_of(S, y, M['weights'], value, M['qMean'])):
            war[(p['pfr'], y)] += M['alpha'] * xv + (1 - M['alpha']) * p['war']
        ros, _ = W.rosters(y)
        R = B.seasons_of(S[y]['players'], B.pbp_extras(y))
        for pid, a in R.items():
            a['age'] = W.age(ros.get(pid, {}).get('birth_date'), y)
            a['war'] = war[(pid, y)]
        rows[y] = R
    return rows, war


def ols_cl(Xm, y, cl):
    """coefficients and CR1 cluster-robust SEs"""
    XtX = np.linalg.pinv(Xm.T @ Xm)
    b = XtX @ Xm.T @ y
    e = y - Xm @ b
    G = defaultdict(lambda: np.zeros(Xm.shape[1]))
    for i, c in enumerate(cl):
        G[c] += Xm[i] * e[i]
    meat = sum(np.outer(g, g) for g in G.values())
    n, k, g = len(y), Xm.shape[1], len(G)
    V = XtX @ meat @ XtX * (g / (g - 1)) * ((n - 1) / (n - k))
    return b, np.sqrt(np.diag(V))


def design(R, zcols):
    pos = sorted({r['pos'] for r in R})
    am = np.mean([r['age'] for r in R if r['age'] is not None])
    cols = []
    for r in R:
        a = (r['age'] if r['age'] is not None else am) - 27
        x = [1.0, a, a * a]
        for p in pos[1:]:
            x.append(float(r['pos'] == p))
        for p in pos:
            x.append(r['war'] * (r['pos'] == p))
        x += [r['z'].get(k, 0.0) for k in zcols]
        cols.append(x)
    return np.array(cols)


def loso(R, zcols):
    """out-of-sample R^2 x100 with zcols minus without"""
    y = np.array([r['next'] for r in R])
    X0, X1 = design(R, []), design(R, zcols)
    yrs = np.array([r['y'] for r in R])
    sse0 = sse1 = sst = 0.0
    for s in sorted(set(yrs)):
        tr, te = yrs != s, yrs == s
        for Xm, acc in ((X0, 0), (X1, 1)):
            b = np.linalg.lstsq(Xm[tr], y[tr], rcond=None)[0]
            e = float(((y[te] - Xm[te] @ b) ** 2).sum())
            if acc == 0:
                sse0 += e
            else:
                sse1 += e
        sst += float(((y[te] - y[tr].mean()) ** 2).sum())
    return 100 * (sse0 - sse1) / sst


def main():
    rows, war = data()
    res = {}
    zs = {}   # (pfr, y) -> {key: z}
    for key, name, poss, fn, label in B.BADGES:
        # year-to-year r of the raw rate, consecutive seasons both in the pool at the same position
        a_, b_, n_ = [], [], []
        for y in BASE:
            for pid, r in rows[y].items():
                r2 = rows[y + 1].get(pid)
                if not r2 or r['pos'] not in poss or r2['pos'] != r['pos'] or r['snaps'] < B.MIN_SNAPS or r2['snaps'] < B.MIN_SNAPS:
                    continue
                v1, n1 = fn(r['c'], r['snaps']); v2, n2 = fn(r2['c'], r2['snaps'])
                if v1 is None or v2 is None:
                    continue
                a_.append(v1); b_.append(v2); n_.append((n1 + n2) / 2)
        r_ = float(np.corrcoef(a_, b_)[0, 1]) if len(a_) > 20 else 0.0
        n = float(np.mean(n_)) if n_ else 0.0
        k = n * (1 - r_) / r_ if r_ > 0 else None
        out = {'name': name, 'pos': list(poss), 'stat': label, 'pairs': len(a_), 'r': round(r_, 3), 'nVol': round(n, 1),
               'k': None if k is None else round(k, 1)}
        res[key] = out
        if r_ < 0.15:
            out.update(pass_=False, note='year-to-year r < .15: noise'); continue
        for y in YEARS:
            for pid, (_, z, _) in B.regress(list(rows[y].values()), key, k).items():
                zs.setdefault((pid, y), {})[key] = z
        R = []
        for y in BASE:
            for pid, r in rows[y].items():
                z = zs.get((pid, y), {}).get(key)
                if z is None:
                    continue
                R.append({'y': y, 'pid': pid, 'pos': r['pos'], 'age': r['age'], 'war': r['war'], 'next': war.get((pid, y + 1), 0.0), 'z': {key: z}})
        Xm = design(R, [key]); yv = np.array([r['next'] for r in R])
        b, se = ols_cl(Xm, yv, [r['pid'] for r in R])
        t = float(b[-1] / se[-1])
        g = loso(R, [key])
        out.update(n=len(R), players=len({r['pid'] for r in R}), coef=round(float(b[-1]), 3), t=round(t, 2), oosGain=round(g, 3),
                   pass_=bool(t >= 2 and g > 0))
        print(f"{key:9s} {name:17s} n{len(R):5d} r{r_:.2f} k{k:7.1f} coef{b[-1]:+.3f} t{t:+.2f} oos{g:+.3f}{' PASS' if out['pass_'] else ''}", flush=True)
    # joint: passers together, weakest dropped while joint t < 2
    keep = [k for k, v in res.items() if v.get('pass_')]
    joint = None
    while keep:
        R = []
        for y in BASE:
            for pid, r in rows[y].items():
                z = zs.get((pid, y), {})
                if r['snaps'] < B.MIN_SNAPS or not any(k in z for k in keep):
                    continue
                R.append({'y': y, 'pid': pid, 'pos': r['pos'], 'age': r['age'], 'war': r['war'], 'next': war.get((pid, y + 1), 0.0), 'z': z})
        Xm = design(R, keep); yv = np.array([r['next'] for r in R])
        b, se = ols_cl(Xm, yv, [r['pid'] for r in R])
        ts = dict(zip(keep, (b[-len(keep):] / se[-len(keep):]).tolist()))
        joint = {'n': len(R), 'oosGain': round(loso(R, keep), 3), 't': {k: round(v, 2) for k, v in ts.items()},
                 'coef': {k: round(float(c), 3) for k, c in zip(keep, b[-len(keep):])}}
        worst = min(keep, key=lambda k: ts[k])
        if ts[worst] >= 2:
            break
        res[worst]['pass_'] = False; res[worst]['note'] = f'dropped in the joint fit (t {ts[worst]:.2f})'
        keep.remove(worst)
    for v in res.values():
        v['pass'] = v.pop('pass_')
    import datetime
    d = {'asof': datetime.date.today().isoformat(), 'method': 'see scripts/nfl_badge_backtest.py', 'years': [BASE[0], BASE[-1]],
         'outcome': "next season's board WAR", 'control': "this season's WAR by position, age, age^2", 'badges': res, 'joint': joint}
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1)
        f.write('\n')
    print('joint', json.dumps(joint))


if __name__ == '__main__':
    main()
