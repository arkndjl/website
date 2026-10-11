"""Where transfers land: a destination-choice model for the team builder's landing odds.

For every 2024 and 2025 transfer with a known hometown (scripts/cfb_transfer_fit.py's build, cached in
scripts/.cache/transfer/rows.json), the school he picked is set against every other FBS and FCS school
that season (a conditional logit). A school's pull on him:
  - the level step: where he comes from (P4, G5, FCS) x where it is (P4, G5; FCS the base)
  - program talent (its roster's mean recruiting grade, as a z-score) and the prestige gap: talent x his
    current school's talent (players move between like programs), x his recruiting grade, x his production
  - winning (its record that season)
  - playing time on offer: the share of its players at his position who left that season
  - home: miles from his hometown (log) and a home-state school
Tested out of time (fit on 2024 moves, scored on 2025's), then refit on both. Writes `landing` into
data/cfb_transfer_fit.json, with each school's level, state and talent for scoring the live season.
Run after scripts/cfb_transfer_fit.py: python3 scripts/cfb_landing_fit.py
"""
import json
import math
import os
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROWS = os.path.join(ROOT, 'scripts', '.cache', 'transfer', 'rows.json')
LOC = os.path.join(ROOT, 'scripts', 'geo', 'team_loc.json')
FIT = os.path.join(ROOT, 'data', 'cfb_transfer_fit.json')
LAM = 2.0
NAMES = ['dP4_oP4', 'dP4_oG5', 'dP4_oFCS', 'dG5_oP4', 'dG5_oG5', 'dG5_oFCS', 'tal', 'tal_from', 'tal_rec', 'tal_prod', 'winp', 'open', 'logdist', 'inState']


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def schools(rows):
    """per season: each school's level, talent z, record, and share leaving at each position"""
    by = defaultdict(list)
    for r in rows: by[(r['season'], r['tid'])].append(r)
    out = defaultdict(dict)
    for (s, tid), rs in by.items():
        g = [x['rec'] for x in rs if x['rec']]
        pos = defaultdict(lambda: [0, 0])
        for x in rs:
            if x['played']: pos[x['g']][0] += x['y'] != 'stay'; pos[x['g']][1] += 1
        out[s][tid] = {'level': rs[0]['level'], 'rec': float(np.mean(g)) if len(g) >= 5 else None,
                       'winp': rs[0]['winp'] if rs[0]['winp'] is not None else 0.5,
                       'open': {k: v[0] / v[1] for k, v in pos.items() if v[1]}}
    for s, d in out.items():   # talent z within the season; schools with few graded recruits get the level's low end
        v = np.array([x['rec'] for x in d.values() if x['rec'] is not None]); mu, sd = v.mean(), v.std()
        lo = {lv: np.percentile([x['rec'] for x in d.values() if x['rec'] is not None and x['level'] == lv] or [mu], 10) for lv in ('P4', 'G5', 'FCS')}
        for x in d.values(): x['tal'] = ((x['rec'] if x['rec'] is not None else lo[x['level']]) - mu) / sd
        opens = defaultdict(list)
        for x in d.values():
            for k, v in x['open'].items(): opens[k].append(v)
        for x in d.values(): x['openMean'] = {k: float(np.mean(v)) for k, v in opens.items()}
    return out


def feats(m, j, sch, loc, tfrom=0.0):
    """one mover m against one school j (tfrom: his current school's talent z)"""
    lv, o = sch['level'], m['level']
    rz = (m['rec'] - 80) / 5 if m['rec'] else -1.0
    prod = (m['pct'] - 0.5) if m['pct'] is not None else 0.0
    st = loc[j][2] if j in loc else None
    d = miles(m['home'], loc[j]) if j in loc else 600
    op = sch['open'].get(m['g'], sch['openMean'].get(m['g'], 0.3))
    return [lv == 'P4' and o == 'P4', lv == 'P4' and o == 'G5', lv == 'P4' and o == 'FCS', lv == 'G5' and o == 'P4', lv == 'G5' and o == 'G5', lv == 'G5' and o == 'FCS',
            sch['tal'], sch['tal'] * tfrom, sch['tal'] * rz, sch['tal'] * prod, sch['winp'] - 0.5, op, math.log1p(d / 100), float(st is not None and st == m['homeState'])]


def design(movers, S, loc):
    Xs, idx = [], []
    for m in movers:
        cand = [j for j in S[m['season']] if j != m['tid'] and j in loc]
        if m['to'] not in cand: continue
        cand.remove(m['to']); cand.insert(0, m['to'])
        tf = S[m['season']].get(m['tid'], {}).get('tal', 0.0)
        Xs.append(np.array([feats(m, j, S[m['season']][j], loc, tf) for j in cand], float)); idx.append(m)
    return Xs, idx


def clogit(Xs, lam=LAM, iters=50):
    k = Xs[0].shape[1]; b = np.zeros(k)
    for _ in range(iters):
        g = -lam * b; H = -lam * np.eye(k)
        for X in Xs:
            u = X @ b; u -= u.max(); p = np.exp(u); p /= p.sum()
            xb = p @ X
            g += X[0] - xb
            H -= (X * p[:, None]).T @ X - np.outer(xb, xb)
        step = np.linalg.solve(H, g); b -= step
        if np.abs(step).max() < 1e-7: break
    return b, np.sqrt(np.diag(np.linalg.inv(-H)))


def evaluate(Xs, b):
    ll, ranks, top10 = 0.0, [], 0
    for X in Xs:
        u = X @ b; u -= u.max(); p = np.exp(u); p /= p.sum()
        ll += math.log(p[0]); r = int((p > p[0]).sum()) + 1; ranks.append(r); top10 += r <= 10
    n = len(Xs); base = -sum(math.log(X.shape[0]) for X in Xs)
    return {'n': n, 'logLik': round(ll / n, 3), 'logLikUniform': round(base / n, 3), 'skill': round(1 - ll / base, 3),
            'medianRank': int(np.median(ranks)), 'top10': round(top10 / n, 3), 'schools': int(np.median([X.shape[0] for X in Xs]))}


def main():
    rows = json.load(open(ROWS)); loc = json.load(open(LOC))
    S = schools(rows)
    movers = [r for r in rows if r['y'] == 'transfer' and r['home'] and r['to'] and not r['abroad']]
    old = [m for m in movers if m['season'] == 2024]; new = [m for m in movers if m['season'] == 2025]
    Xo, _ = design(old, S, loc); Xn, _ = design(new, S, loc)
    bo, _ = clogit(Xo)
    test = evaluate(Xn, bo)
    # a home-and-level-only model, to show what the rest adds
    keep = [NAMES.index(n) for n in NAMES[:6] + ['logdist', 'inState']]
    bh, _ = clogit([X[:, keep] for X in Xo])
    test['homeLevelOnly'] = evaluate([X[:, keep] for X in Xn], bh)
    print('landing, out of time', test)
    b, se = clogit(Xo + Xn)
    print({n: (round(float(x), 3), round(float(s), 3)) for n, x, s in zip(NAMES, b, se)})
    latest = max(S)
    fit = json.load(open(FIT))
    fit['landing'] = {'names': NAMES, 'coef': [round(float(x), 4) for x in b], 'se': [round(float(x), 4) for x in se], 'test': test,
                      'n': len(Xo) + len(Xn), 'season': latest,
                      'schools': {j: [x['level'], round(x['tal'], 3)] for j, x in S[latest].items() if j in loc}}
    json.dump(fit, open(FIT, 'w'), indent=1)
    print('wrote landing into', FIT)


if __name__ == '__main__':
    main()
