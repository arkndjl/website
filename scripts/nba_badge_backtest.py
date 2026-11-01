#!/usr/bin/env python3
"""Backtest: do NBA trait badges (scripts/nba_badges.py) predict next season's XPM beyond this season's XPM?

    python3 scripts/nba_xpm.py 2010 2026         # caches bbref's advanced + totals tables (scripts/.cache/nba)
    python3 scripts/nba_badge_backtest.py        # -> data/nba_badge_backtest.json (numpy)

Universe: player-seasons 2010-25 with 500+ MP (a badge's pool) and 250+ MP the next season, joined on the bbref id.
Outcome: next season's raw XPM, weighted by his minutes that season (as the XPM shrink fit, nba_xpm.SHRINK_K).
Control (held fixed): this season's shrunk XPM (the board's XPM, sxpm) by position group (dummies and sxpm x group),
ln MP, age, age^2. Badge value: the rate regressed by volume with its own k (year-to-year r, consecutive 500+ MP
seasons), z'd within position group and season. Tests, per badge:
  t         the badge's coefficient over its cluster-robust SE, clustered by player (CR1, weighted)
  oosGain   leave one season out (16 folds): out-of-sample weighted R^2 with the badge minus without (x100)
  pass      t >= 2 (positive), oosGain > 0, year-to-year r >= .15
  joint     the passers fit together; the weakest is dropped while its joint t < 2
Results (Nov 1 2026, 4,912 rows): four of 12 ship. Shot Creator (usage %, t +6.1), Playmaker (assist %, t +7.0), Foul
Drawer (FTA a shot, t +3.9), Disruptor (steal %, t +3.1); jointly t 3.7 / 4.1 / 2.9 / 3.3, OOS +.47 R^2 points.
Rebounder (DRB %) passed alone (t +2.4) and dropped in the joint fit (t < 2). Shooter (3P%, t -7.6), Efficient Scorer
(TS%, t -6.8) and Ball Security (t -6.3) are negative: XPM already pays for efficiency and it regresses. Rim Protector,
Touch, Offensive Rebounder flat. No hook into XPM (proj): its prior also feeds the game model (nba_games), so a change
there needs that model's own backtest; the badges are display only.
"""
import datetime
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_badges as B   # noqa: E402
import nba_xpm as X   # noqa: E402

SEASONS = list(range(2010, 2027))
BASE = SEASONS[:-1]


def load():
    stats, board = {}, {}
    for s in SEASONS:
        a = open(os.path.join(X.CACHE, f'adv_{s}.html'), encoding='utf-8').read()
        t = open(os.path.join(X.CACHE, f'tot_{s}.html'), encoding='utf-8').read()
        stats[s] = B.season_stats(a, t)
        board[s] = {p['id']: p for p in json.load(open(os.path.join(X.OUT, f'{s}.json')))['players']}
    return stats, board


def ols_cl(Xm, y, w, cl):
    sw = np.sqrt(w)
    Xw, yw = Xm * sw[:, None], y * sw
    XtX = np.linalg.pinv(Xw.T @ Xw)
    b = XtX @ Xw.T @ yw
    e = yw - Xw @ b
    G = defaultdict(lambda: np.zeros(Xm.shape[1]))
    for i, c in enumerate(cl):
        G[c] += Xw[i] * e[i]
    meat = sum(np.outer(g, g) for g in G.values())
    n, k, g = len(y), Xm.shape[1], len(G)
    V = XtX @ meat @ XtX * (g / (g - 1)) * ((n - 1) / (n - k))
    return b, np.sqrt(np.diag(V))


def design(R, zcols):
    out = []
    for r in R:
        a = (r['age'] if r['age'] is not None else 26) - 27
        g = r['grp']
        x = [1.0, a, a * a, math.log(r['mp']), float(g == 'F'), float(g == 'C')]
        x += [r['sx'] * (g == q) for q in ('G', 'F', 'C')]
        x += [r['z'].get(k, 0.0) for k in zcols]
        out.append(x)
    return np.array(out)


def loso(R, zcols):
    y = np.array([r['next'] for r in R]); w = np.array([r['w'] for r in R]); yrs = np.array([r['y'] for r in R])
    X0, X1 = design(R, []), design(R, zcols)
    sse = [0.0, 0.0]; sst = 0.0
    for s in sorted(set(yrs)):
        tr, te = yrs != s, yrs == s
        sw = np.sqrt(w[tr])
        for i, Xm in enumerate((X0, X1)):
            b = np.linalg.lstsq(Xm[tr] * sw[:, None], y[tr] * sw, rcond=None)[0]
            sse[i] += float((w[te] * (y[te] - Xm[te] @ b) ** 2).sum())
        sst += float((w[te] * (y[te] - np.average(y[tr], weights=w[tr])) ** 2).sum())
    return 100 * (sse[0] - sse[1]) / sst


def rows_for(stats, board, zs, keys):
    R = []
    for s in BASE:
        for pid, st in stats[s].items():
            z = zs.get((pid, s), {})
            p, q = board[s].get(pid), board[s + 1].get(pid)
            if not any(k in z for k in keys) or not p or not q or p.get('sxpm') is None or q.get('xpm') is None or q['mp'] < 250 or q.get('pr'):
                continue
            R.append({'y': s, 'pid': pid, 'grp': st['grp'], 'age': p.get('age'), 'mp': max(p['mp'], 1), 'sx': p['sxpm'],
                      'next': q['xpm'], 'w': q['mp'], 'z': z})
    return R


def main():
    stats, board = load()
    res, zs = {}, {}
    for key, name, grps, fn, label in B.BADGES:
        a_, b_, n_ = [], [], []
        for s in BASE:
            for pid, st in stats[s].items():
                s2 = stats[s + 1].get(pid)
                if not s2 or st.get('grp') not in grps or s2.get('grp') != st['grp'] or (st['mp'] or 0) < B.MIN_MP or (s2['mp'] or 0) < B.MIN_MP:
                    continue
                v1, n1 = fn(st); v2, n2 = fn(s2)
                if v1 is None or v2 is None:
                    continue
                a_.append(v1); b_.append(v2); n_.append((n1 + n2) / 2)
        r_ = float(np.corrcoef(a_, b_)[0, 1]); n = float(np.mean(n_))
        k = n * (1 - r_) / r_ if r_ > 0 else None
        out = res[key] = {'name': name, 'stat': label, 'pairs': len(a_), 'r': round(r_, 3), 'nVol': round(n, 1), 'k': None if k is None else round(k, 1)}
        if r_ < 0.15:
            out.update(pass_=False, note='year-to-year r < .15: noise'); continue
        for s in SEASONS:
            for pid, (_, z, _) in B.regress(stats[s], key, k).items():
                zs.setdefault((pid, s), {})[key] = z
        R = rows_for(stats, board, zs, [key])
        for r in R:
            r['z'] = {key: r['z'][key]}
        b, se = ols_cl(design(R, [key]), np.array([r['next'] for r in R]), np.array([r['w'] for r in R]), [r['pid'] for r in R])
        t = float(b[-1] / se[-1]); g = loso(R, [key])
        out.update(n=len(R), players=len({r['pid'] for r in R}), coef=round(float(b[-1]), 3), t=round(t, 2), oosGain=round(g, 3),
                   pass_=bool(t >= 2 and g > 0))
        print(f"{key:9s} {name:20s} n{len(R):5d} r{r_:.2f} k{k:8.1f} coef{b[-1]:+.3f} t{t:+.2f} oos{g:+.3f}{' PASS' if out['pass_'] else ''}", flush=True)
    keep = [k for k, v in res.items() if v.get('pass_')]
    joint = None
    while keep:
        R = rows_for(stats, board, zs, keep)
        b, se = ols_cl(design(R, keep), np.array([r['next'] for r in R]), np.array([r['w'] for r in R]), [r['pid'] for r in R])
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
    d = {'asof': datetime.date.today().isoformat(), 'method': 'see scripts/nba_badge_backtest.py', 'years': [BASE[0], BASE[-1]],
         'outcome': "next season's XPM (raw, minutes-weighted, 250+ MP)", 'control': "this season's shrunk XPM by position group, ln MP, age, age^2",
         'badges': res, 'joint': joint}
    with open(B.BT, 'w') as f:
        json.dump(d, f, indent=1)
        f.write('\n')
    print('joint', json.dumps(joint))


if __name__ == '__main__':
    main()
