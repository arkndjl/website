# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L10: Premier League keepers' post-shot xG minus goals as the GAR `gk` rate, scored on Premier League team-seasons
in the GAR harness. Prereg: /mnt/project-files/research-sweep-nov19/impl/soccer/prereg.md.

    python3 scripts/research/sweep_nov19/soccer/l10_psxg.py <pl dir>
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
import names as N
import soccer_data as D
import soccer_players as SP

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')
LAST = 2026


def tstat(d, keys):
    m = sum(d) / len(d)
    gs = defaultdict(float)
    for x, k in zip(d, keys):
        gs[k] += x - m
    se = math.sqrt(sum(v * v for v in gs.values())) / len(d)
    return m, m / se


def main():
    F = json.load(open(SP.FIT))
    rows = [r for r in D.load(SP.ROWS) if r['S'] <= LAST]
    ts = SP.team_seasons(SP.FIRST, LAST)
    LS, TMV = SP.league_strength(), SP.tm_values()
    pri = dict(priors=SP.PRIORS, LS=LS, TMV=TMV)
    feats, lam = F['feats'], F['lambda']
    SP.prep(rows, F['shrink'])
    ks, X0, y = SP.design(rows, ts, feats, **pri)
    _, p0 = SP.loso(ks, X0, y, lam)
    live = {(r['lg'], r['S'], r['tid'], r['p']): r['_gk'] for r in rows}
    cand = [dict(r) for r in rows]
    joined = tot = 0
    pairs = []
    for S in range(SP.FIRST, LAST + 1):
        fn = os.path.join(sys.argv[1], f'pl_{S - 1}.json')
        if not os.path.exists(fn):
            continue
        gk = [x for x in json.load(open(fn)) if x['pos'] == 'Goalkeeper' and (x['st'].get('timePlayed') or 0) >= 90
              and x['st'].get('expectedGoalsOnTargetConceded') is not None]
        M = N.Matcher([{'name': x['n'], 'x': x} for x in gk])
        for r in cand:
            if r['lg'] != 'eng.1' or r['S'] != S or r['pos'] != 'GK':
                continue
            tot += 1
            hit, _ = M.find(r['n'])
            if not hit:
                continue
            st = hit['x']['st']
            rate = (st['expectedGoalsOnTargetConceded'] - (st.get('goalsConceded') or 0) + (st.get('ownGoalsConceded') or 0)) / st['timePlayed']
            pairs.append((r['gks'] / max(r['min'], 1) * 90, rate * 90, r['min'], r['p'], S))
            r['gks'] = rate * r['min']
            joined += 1
    SP.prep(cand, F['shrink'])
    k2, X1, y1 = SP.design(cand, ts, feats, **pri)
    assert k2 == ks
    _, p1 = SP.loso(ks, X1, y, lam)
    m = np.array([k[0] == 'eng.1' for k in ks])
    S = np.array([k[1] for k in ks])
    d = ((y - p1) ** 2 - (y - p0) ** 2)[m]
    mm, t = tstat(list(d), list(S[m]))
    by = {int(s): round(float(d[S[m] == s].mean()), 5) for s in np.unique(S[m])}
    # year-to-year r of each rate, 1500+ minutes both seasons
    by_p = defaultdict(dict)
    for a, b, mn, p, s in pairs:
        if mn >= 1500:
            by_p[p][s] = (a, b)
    yy = [(v[s], v[s + 1]) for v in by_p.values() for s in v if s + 1 in v]
    r_live = float(np.corrcoef([a[0] for a, _ in yy], [b[0] for _, b in yy])[0, 1]) if len(yy) > 5 else None
    r_ps = float(np.corrcoef([a[1] for a, _ in yy], [b[1] for _, b in yy])[0, 1]) if len(yy) > 5 else None
    res = {'keepersJoined': joined, 'keeperRows': tot, 'teamSeasons': int(m.sum()), 'baseMse': round(float(np.mean((y - p0)[m] ** 2)), 5),
           'candMse': round(float(np.mean((y - p1)[m] ** 2)), 5), 'd': round(mm, 6), 't': round(t, 2), 'bySeason': by,
           'seasonsBetter': sum(1 for v in by.values() if v < 0), 'seasons': len(by), 'yoyPairs': len(yy),
           'yoyLive': round(r_live, 3) if r_live is not None else None, 'yoyPsxg': round(r_ps, 3) if r_ps is not None else None,
           'rLivePsxg': round(float(np.corrcoef([a for a, b, mn, _, _ in pairs if mn >= 900], [b for a, b, mn, _, _ in pairs if mn >= 900])[0, 1]), 3)}
    json.dump(res, open(os.path.join(OUT, 'l10.json'), 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
