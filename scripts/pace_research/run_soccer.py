import json, gzip, math
import numpy as np
import os
SC = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/'
from core import Pace, test_logit, OUT
B = json.load(gzip.open(OUT + 'soccer_big5.json.gz'))
wf = {r['id']: r for r in json.load(gzip.open(SC + 'data/games_wf/soccer.json.gz'))}
def season(d): y, m = int(d[:4]), int(d[5:7]); return y + 1 if m >= 7 else y
def lg(p): p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p / (1 - p))
B.sort(key=lambda r: r['day'])
out = {}
for nm, fx in (('shots', lambda r: (r['hsh'] + r['ash']) if r.get('hsh') is not None else None),
               ('shots on target', lambda r: (r['hst'] + r['ast']) if r.get('hst') is not None else None),
               ('xG', lambda r: (r['hx'] + r['ax']) if r.get('hx') is not None else None)):
    Ps = {}
    F = {}
    for r in B:
        L = r['lg']; P = Ps.setdefault(L, Pace(hl=10, carry=0.5)); P.season(season(r['day']))
        h, a = r['h'], r['a']
        if P.n[h] >= 4 and P.n[a] >= 4:
            F[r['id']] = (P.r[h] + P.r[a], abs(P.r[h] - P.r[a]), (P.fast[h] - P.r[h]) + (P.fast[a] - P.r[a]), P.lg)
        P.add(h, a, fx(r))
    rows = []
    for r in B:
        w = wf.get(r['id']); f = F.get(r['id'])
        ou = r.get('ouc') or r.get('ouac')
        if not w or not f or not ou or w.get('o25') is None or r['hs'] is None:
            continue
        po = (1 / ou[0]) / (1 / ou[0] + 1 / ou[1])
        rows.append((season(r['day']), r['day'], lg(po), lg(w['o25']), f, int(r['hs'] + r['as'] > 2.5)))
    S = np.array([x[0] for x in rows]); day = np.array([x[1] for x in rows]); c = np.array([x[2] for x in rows]); m = np.array([x[3] for x in rows])
    y = np.array([x[5] for x in rows], float)
    ep = np.array([x[4][0] / x[4][3] for x in rows]); cl = np.array([x[4][1] / x[4][3] for x in rows]); tr = np.array([x[4][2] / x[4][3] for x in rows])
    print('##', nm, len(rows), sorted(set(S)))
    for cn, cc in (('expected pace', [ep]), ('clash', [cl]), ('trend', [tr]), ('all three', [ep, cl, tr])):
        r1 = test_logit([c, m - c], cc, y, S, day, (2014, 2021), 2022, 2014)
        r2 = test_logit([m], cc, y, S, day, (2014, 2021), 2022, 2014)
        out[nm + ': ' + cn] = {'close': r1, 'model': r2}
        for k, r in (('model', r2), ('close', r1)):
            print('%-6s %-14s tune n%5d d%+.5f t%+.2f | held n%5d d%+.5f t%+.2f coef %s' % (k, cn, r['tune']['n'], r['tune']['d'], r['tune']['t'], r['held']['n'], r['held']['d'], r['held']['t'], r['coef']))
json.dump(out, open(OUT + 'soccer.json', 'w'), indent=1)
