# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family F (prereg-F.md): team unit context as a CFB FV term, class held out, on the all-time rows.
  python3 scripts/research/cfb_nov13/fv_unit_test.py /tmp/cfb_units.json [fm|fvx]"""
import gzip, json, sys, os, collections, math
import numpy as np
sys.path.insert(0, 'scripts'); import fv_alltime as FA, names as N, cfb_horizon
U = json.load(open(sys.argv[1])); KEY = sys.argv[2] if len(sys.argv) > 2 else 'fm'
hz = cfb_horizon.saved()
Z = {}
for S, d in U.items():
    o = np.array([v['o'] for v in d.values()]); dd = np.array([v['d'] for v in d.values()])
    Z[int(S)] = {N.team_key(t): ((v['o'] - o.mean()) / o.std(), (v['d'] - dd.mean()) / dd.std()) for t, v in d.items()}
src = json.load(gzip.open(FA.CFB_ROWS))
OFF = {'QB', 'RB', 'WR', 'TE'}
R = []
for r in src:
    if not r['final'] or not (2015 <= r['last'] <= 2022) or r['s'] != r['last']: continue
    cls = r['draft'] or r['last'] + 1
    if not (2016 <= cls <= 2023): continue
    z = Z.get(r['last'], {}).get(N.team_key(r['team']))
    if z is None or r.get(KEY) is None: continue
    av = (r['av'] or 0) / hz(r['draft']) if r['draft'] and r['av'] and not r.get('hz') else (r['av'] or 0)
    own = z[0] if r['g'] in OFF else z[1]
    R.append(dict(cls=cls, g=r['g'], x=float(r[KEY]), out=float(FA.fv_from_av(av)), own=own, team=(z[0] + z[1]) / math.sqrt(2), box=r['last'] < 2019))
print(KEY, len(R), 'rows;', sum(1 for r in R if r['x'] > 20.001), 'above the floor;', collections.Counter(r['cls'] for r in R))
cls = np.array([r['cls'] for r in R]); x0 = np.array([r['x'] for r in R]); out = np.array([r['out'] for r in R]); box = np.array([r['box'] for r in R])
GRID = [0, .5, 1, 1.5, 2, 3]
def design(x):   # the draft-day line, one for each grading era
    return np.column_stack([(x - 20) * box, np.maximum(0, x - 40) * box, (x - 20) * ~box, np.maximum(0, x - 40) * ~box])
def run(feat):
    f = np.array([r[feat] for r in R]); above = x0 > 20.001
    e0 = np.zeros(len(R)); e1 = np.zeros(len(R)); picks = {}
    for c in sorted(set(cls)):
        tr = cls != c; te = ~tr; best = None
        for w in GRID:
            x = np.clip(x0 + w * f * above, 20, 80); A = design(x); b = np.linalg.lstsq(A[tr], out[tr] - 20, rcond=None)[0]
            mse = ((out[tr] - 20 - A[tr] @ b) ** 2).mean()
            if w == 0: e0[te] = (out[te] - 20 - A[te] @ b) ** 2
            if best is None or mse < best[0] - 1e-12: best = (mse, w, (out[te] - 20 - A[te] @ b) ** 2)
        picks[int(c)] = best[1]; e1[te] = best[2]
    d = e1 - e0
    by = np.array([d[cls == c].sum() for c in sorted(set(cls))]); G = len(by)
    se = math.sqrt(G / (G - 1) * (by ** 2).sum()) / len(d)
    won = sum(1 for c in sorted(set(cls)) if d[cls == c].mean() < 0)
    hi = x0 >= 30
    return dict(feat=feat, mse0=round(e0.mean(), 3), mse1=round(e1.mean(), 3), d=round(d.mean(), 4), t=round(d.mean() / se, 2), won=f'{won}/{G}', picks=picks,
                d30=round(d[hi].mean(), 3), n30=int(hi.sum()), byClass={int(c): round(d[cls == c].mean(), 3) for c in sorted(set(cls))}), e1
res = {}
for feat in ('own', 'team'):
    res[feat], e = run(feat); res[feat + '_e'] = e
    print(json.dumps(res[feat]))
d = res['own_e'] - res['team_e']
by = np.array([d[cls == c].sum() for c in sorted(set(cls))]); G = len(by)
print('own vs team held-out error: d %.4f t %.2f' % (d.mean(), d.mean() / (math.sqrt(G / (G - 1) * (by ** 2).sum()) / len(d))))
