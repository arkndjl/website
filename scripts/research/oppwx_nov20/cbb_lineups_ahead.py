# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball lineups: the look-ahead half of the gate with a schedule-fair target (Nov 20 2026).

The shared look-ahead scores the early rate against the RAW rate of the rest. In college the first half is
non-conference and the second is conference play, so the raw rest carries the schedule the adjustment removes. Here the
season is cut at the median game date, ratings are solved separately on each side (no game or rating shared), and the
early rate (raw, or adjusted with early-only ratings) predicts the late rate adjusted with late-only ratings; the raw
late target is printed beside it. Each variant gets its own best shrink. Paired t over units.
"""
import itertools, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_lineups as L

games = L.load(2026)
ok = {gid: g for gid, g in games.items() if 'stints' in g and None not in g['players'][g['home']] + g['players'][g['away']]}
cut = sorted(g['date'] for g in ok.values())[len(ok) // 2]
E = {k: g for k, g in ok.items() if g['date'] < cut}; T = {k: g for k, g in ok.items() if g['date'] >= cut}
RE, RL = L.team_ratings(E), L.team_ratings(T)
print(len(E), len(T), 'games, cut', cut)
out = {'cut': cut}
def unit_sums(G, R, size):
    acc = defaultdict(lambda: [0.0, 0.0, 0.0])                 # poss, raw net, adjusted net
    for gid, g in G.items():
        secs = g['secs'] or 1; poss = g.get('poss') or 68.0 * secs / 2400
        for side, opp, si in ((g['home'], g['away'], 1), (g['away'], g['home'], 2)):
            d = R.get((opp, gid)); o = (d[0] - d[1] + d[2]) if d else 0.0
            for s in g['stints']:
                ps = poss * s[0] / secs; n = (s[3] - s[4]) if si == 1 else (s[4] - s[3])
                for u in ([tuple(sorted(s[si]))] if size == 5 else itertools.combinations(sorted(s[si]), size)):
                    a = acc[(side, tuple(g['players'][side][i] for i in u))]
                    a[0] += ps; a[1] += n; a[2] += n - ps * o
    return acc
for size, MINH in ((5, 40), (2, 250), (1, 250)):
    a, b = unit_sums(E, RE, size), unit_sums(T, RL, size)
    ks = [k for k in a if k in b and a[k][0] >= MINH and b[k][0] >= MINH]
    e1 = np.array([a[k][0] for k in ks]); e2 = np.array([b[k][0] for k in ks])
    X = {'raw': np.array([a[k][1] for k in ks]) / e1, 'adjusted': np.array([a[k][2] for k in ks]) / e1}
    Y = {'late adjusted': np.array([b[k][2] for k in ks]) / e2, 'late raw': np.array([b[k][1] for k in ks]) / e2}
    res = {'n': len(ks)}
    for tn, y in Y.items():
        errs = {}
        for nm, x in X.items():
            mu = np.average(x, weights=e1); best = None
            for kk in (0, .25, .5, 1, 2, 4, 8):
                p = mu + (x - mu) * e1 / (e1 + kk * np.median(e1)) + (np.average(y, weights=e2) - mu)
                e = (p - y) ** 2 * e2; m = e.sum() / e2.sum()
                if best is None or m < best[0]: best = (m, kk, e)
            errs[nm] = best
        d = errs['adjusted'][2] - errs['raw'][2]
        res[tn] = {'mse raw': round(float(errs['raw'][0]), 5), 'mse adjusted': round(float(errs['adjusted'][0]), 5),
                   'r raw': round(float(np.corrcoef(X['raw'], y)[0, 1]), 4), 'r adjusted': round(float(np.corrcoef(X['adjusted'], y)[0, 1]), 4),
                   't': round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2)}
    print(size, res); out[str(size)] = res
json.dump(out, open(os.path.join(HERE, 'cbb_lineups_ahead.json'), 'w'), indent=1)
