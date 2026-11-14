#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""An NBA rotation player's chance to play a game with an official injury report.

    python3 scripts/nba_play.py --fit      # data/nba_play_fit.json: 'full' (live) and 'walk' (each season on the seasons before)

Two ridge logistics (scripts/logit_ridge.py), rows weighted by role minutes:
  j3   every rotation player (8+ role minutes) in a reported game: status x games missed in a row, night two by age and
       role, role minutes, age, home, days since the club's last game, the club's play share at that status this
       season, his own share of the club's games, his status and outcome at the club's last game, season progress,
       club win share after game 55
  j4   listed players (Questionable, Doubtful, Probable) with a report the day before: j3's logit, tonight's status,
       and tonight's status x his status on the day-before report (new to the list, upgraded, downgraded, unchanged)
nba_games.Model builds each player's inputs (play_ctx) and reads prob()."""
import datetime as dt
import json
import math
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIT = os.path.join(os.path.dirname(HERE), 'data', 'nba_play_fit.json')
FIRST = 2020                  # the official reports start in 2019-20
LISTED = ('Questionable', 'Doubtful', 'Probable')
MIN_ROLE = 8.0
NUM = ['role minutes', 'age', 'age unknown', 'home', 'days since last', 'club share at status', 'own play share',
       'season progress', 'win share late', 'late']
LAM3, LAM4 = 30.0, 10.0       # picked by leave-one-season-out on 2020-22 (scripts/research/inj_nov14)


def _cats(c):
    return {'cell': f"{c['st']}|{c['bk']}", 'n2': c['grp'] if c['n2'] else 'no', 'last': f"{c['last'][0]}|{int(c['last'][1])}",
            'traj': f"{c['st']}|{c['prev']}"}


def _num(c, rate):
    r = rate.get(c['st'], 0.9)
    age = c['age']
    return [c['R'], age if age > 0 else 27.0, float(age <= 0), c['home'], c['days'],
            (c['club'][0] + 20 * r) / (c['club'][1] + 20) - r, (c['own'][0] + 8.5) / (c['own'][1] + 10),
            c['gnum'] / 82.0, c['wsh'], c['late']]


def _vec(c, names, rate, cats=None):
    k = cats or _cats(c)
    out = []
    for n in names:
        a, _, b = n.partition('=')
        if b:
            out.append(float(k.get(a) == b))
    return out + _num(c, rate)


def _sig(z):
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def prob(c, fit):
    """P(plays) for one player's inputs under a fit ({'j3': {...}, 'j4': {...}})"""
    j3 = fit['j3']
    x = _vec(c, j3['names'], j3['rate'])
    p = _sig(j3['b'][0] + sum(b * (v - m) / s for b, v, m, s in zip(j3['b'][1:], x, j3['mu'], j3['sd'])))
    j4 = fit.get('j4')
    if j4 and c['st'] in LISTED and c.get('prev') is not None:
        q = min(0.995, max(0.005, p))
        k = _cats(c)
        x = [math.log(q / (1 - q)), float(c['st'] == 'Doubtful'), float(c['st'] == 'Probable')] + [float(k['traj'] == n[5:]) for n in j4['names']]
        p = _sig(j4['b'][0] + sum(b * (v - m) / s for b, v, m, s in zip(j4['b'][1:], x, j4['mu'], j4['sd'])))
    return min(0.999, max(0.001, p))


_FIT = None


def load():
    global _FIT
    if _FIT is None:
        try:
            _FIT = json.load(open(FIT))
        except (OSError, ValueError):
            _FIT = {}
    return _FIT


def fit_for(S):
    """the fit season S reads: the seasons before it (None before two reported seasons exist)"""
    F = load()
    return (F.get('walk') or {}).get(str(S)) or (F.get('full') if F and S > F['seasons'][1] else None)


def rows(games=None, names=None, inj=None, prev=None):
    """every rotation player's reported game from FIRST on: (season, game day, inputs, played)"""
    import nba_games as N
    F = json.load(open(N.FIT))
    if games is None:
        games, names = N.load_hist()
    inj = N.load_inj() if inj is None else inj
    prev = N.load_prev() if prev is None else prev
    m = N.Model(names, F['P'], inj=inj, prev=prev, play=False, **F['params'])
    out = []
    for g in games:
        m.feats(g)
        if g.get('fin') and g.get('pl') and g['S'] >= FIRST and inj.get(g['id']) is not None:
            for t in (g['h'], g['a']):
                if t not in g['pl']:
                    continue
                mins = dict(g['pl'][t])
                st, _ = m.status_for(g, t)
                for p in m.roster(t):
                    w, n = m.role[p]
                    R = w / n if n else 0.0
                    if R >= MIN_ROLE:
                        out.append((g['S'], str(N.gday(N.tipdt(g))), m.play_ctx(p, t, st.get(p), R), float(mins.get(p, 0) > 0)))
        m.update(g)
    return out


def fit_rows(R, k):
    """the two logistics on the rows where k"""
    import numpy as np
    from logit_ridge import fit_ridge
    R = [r for r, kk in zip(R, k) if kk]
    y = np.array([r[3] for r in R]); w = np.array([r[2]['R'] for r in R])
    st = [r[2]['st'] for r in R]
    rate = {}
    for s in set(st):
        i = np.array([x == s for x in st])
        rate[s] = round(float((w[i] * y[i]).sum() / w[i].sum()), 4)
    cats = [_cats(r[2]) for r in R]
    names = []
    for key in ('cell', 'n2', 'last'):
        lv = [v for v, n in Counter(c[key] for c in cats).most_common() if n >= 30]
        names += [f'{key}={v}' for v in lv[1:]]          # the most common level is the reference
    X = np.array([_vec(r[2], names, rate, c) for r, c in zip(R, cats)])
    b, mu, sd = fit_ridge(X, y, LAM3, w)
    j3 = {'names': names, 'rate': rate, 'n': len(R), 'b': [round(float(v), 5) for v in b], 'mu': [round(float(v), 5) for v in mu],
          'sd': [round(float(v), 5) for v in sd]}
    p3 = np.array([prob(r[2], {'j3': j3}) for r in R])
    L = np.array([r[2]['st'] in LISTED and r[2]['prev'] is not None for r in R])
    lv = [v for v, n in Counter(c['traj'] for c, l in zip(cats, L) if l).most_common() if n >= 30]
    tn = ['traj=' + v for v in lv[1:]]
    q = np.clip(p3[L], 0.005, 0.995)
    X4 = np.column_stack([np.log(q / (1 - q)), [float(s == 'Doubtful') for s, l in zip(st, L) if l], [float(s == 'Probable') for s, l in zip(st, L) if l]]
                         + [[float(c['traj'] == v) for c, l in zip(cats, L) if l] for v in lv[1:]])
    b4, mu4, sd4 = fit_ridge(X4, y[L], LAM4, w[L])
    j4 = {'names': tn, 'ref': lv[0], 'n': int(L.sum()), 'b': [round(float(v), 5) for v in b4], 'mu': [round(float(v), 5) for v in mu4],
          'sd': [round(float(v), 5) for v in sd4]}
    return {'j3': j3, 'j4': j4}


def fit(last=None):
    import numpy as np
    R = rows()
    S = np.array([r[0] for r in R])
    last = last or int(S.max())
    out = {'asof': dt.date.today().isoformat(), 'seasons': [FIRST, last], 'full': fit_rows(R, S <= last),
           'walk': {str(s): fit_rows(R, S < s) for s in range(FIRST + 2, last + 1)}}
    with open(FIT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('nba play fit', len(R), 'rows', out['full']['j4']['n'], 'listed with a day-before report')
    return out, R


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
