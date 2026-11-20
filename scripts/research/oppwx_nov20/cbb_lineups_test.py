# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball lineups / on-off: opponent adjustment of Net (Nov 20 2026).
    python3 scripts/cbb_lineups.py --pull 2026 && python3 scripts/research/oppwx_nov20/cbb_lineups_test.py

Two opponent forms: 'one step' (what the opponent allowed and scored per possession in its other games, shrunk: the
NBA form) and 'ratings' (cbb_lineups.team_ratings: offence and defence solved together over the season's games with a
home term, so an opponent's own schedule counts; the game itself is taken back out). Fives, pairs, on-court net and
on-off, odd vs even games of 2025-26 (the test is out of sample by construction: one half never sees the other).
"""
import itertools, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import oppadj as OA
import cbb_lineups as L

games = L.load(2026)
ok = {gid: g for gid, g in games.items() if 'stints' in g and None not in g['players'][g['home']] + g['players'][g['away']]}
print(len(ok), 'games')
R = L.team_ratings(ok)
out = {}
def rows_for(size):
    rows, adj, off = [], [], []
    for gid, g in ok.items():
        secs = g['secs'] or 1; poss = g.get('poss') or 68.0 * secs / 2400
        for side, opp, si in ((g['home'], g['away'], 1), (g['away'], g['home'], 2)):
            acc = defaultdict(lambda: [0.0, 0.0]); T = [0.0, 0.0]
            for s in g['stints']:
                ps = poss * s[0] / secs
                pf, pa = (s[3], s[4]) if si == 1 else (s[4], s[3])
                T[0] += ps; T[1] += pf - pa
                for u in ([tuple(sorted(s[si]))] if size == 5 else itertools.combinations(sorted(s[si]), size)):
                    a = acc[u]; a[0] += ps; a[1] += pf - pa
            d = R.get((opp, gid))
            for u, (p, n) in acc.items():
                if p <= 0: continue
                rows.append((2026, gid, g['date'], (side, tuple(g['players'][side][i] for i in u)), opp, p, n, si == 1))
                adj.append(n - p * (d[0] - d[1] + d[2]) if d else n)  # defence allowed minus offence scored, and the home edge
                if size == 1: off.append((T[0] - p, T[1] - n, d))
    return rows, np.array(adj), off
for size, MIN, MINH in ((5, 100, 30), (2, 600, 200), (1, 600, 200)):
    rows, adj, off = rows_for(size)
    V = {'raw': np.array([r[6] for r in rows]), 'ratings': adj}
    for K in (0, 350, 700):
        V[f'one step K{K}'] = OA.adjust(rows, K, 1.0)
    res = {'split': OA.split(rows, V, MIN, MINH), 'ahead50': OA.ahead(rows, V, MIN, MINH, 0.5)}
    for k, v in res.items():
        print(size, k, 'n', v['n'])
        for a, o in v.items():
            if a != 'n': print('   ', a, o)
    out[str(size)] = res
    if size == 1:
        raw = V['raw']
        offraw = np.array([o[1] for o in off]); offp = np.array([o[0] for o in off])
        offadj = np.array([o[1] - o[0] * (o[2][0] - o[2][1] + o[2][2]) if o[2] else o[1] for o in off])
        keys, A, B = OA._halves(rows, raw, 600, 200)
        oo = {}
        for nm, von, voff in (('raw', raw, offraw), ('ratings', adj, offadj)):
            xa, xb = [], []
            for (a, ea), (b, eb) in zip(A, B):
                a = np.array(a); b = np.array(b)
                fa = offp[a].sum(); fb = offp[b].sum()
                if fa < 150 or fb < 150: xa.append(np.nan); xb.append(np.nan); continue
                xa.append(von[a].sum() / ea - voff[a].sum() / fa); xb.append(von[b].sum() / eb - voff[b].sum() / fb)
            oo[nm] = (np.array(xa), np.array(xb))
        keep = ~np.isnan(oo['raw'][0])
        rng = np.random.default_rng(3); n = int(keep.sum()); idx = rng.integers(0, n, (2000, n))
        r0 = np.array([np.corrcoef(oo['raw'][0][keep][i], oo['raw'][1][keep][i])[0, 1] for i in idx])
        for nm, (a, b) in oo.items():
            a = a[keep]; b = b[keep]
            d = np.array([np.corrcoef(a[i], b[i])[0, 1] for i in idx]) - r0
            out.setdefault('onoff', {})[nm] = {'n': n, 'r': round(float(np.corrcoef(a, b)[0, 1]), 4), 'P': round(float((d > 0).mean()), 3)}
            print('onoff', nm, out['onoff'][nm])
json.dump(out, open(os.path.join(HERE, 'cbb_lineups_results.json'), 'w'), indent=1)
