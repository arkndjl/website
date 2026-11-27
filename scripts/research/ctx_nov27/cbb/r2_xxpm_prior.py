#!/usr/bin/env python3
"""R2 (prereg.md, round 2): last season's rXPM and VORX (season-only value) beside the model prior in a returner
projection of next-season rXPM. Reduced harness on scripts/data/cbb_xpm_hist.json.gz + the kit's teams and minute shares.
Downstream score: next-season team R2 of the returners' minutes-weighted projection.  -> r2.json"""
import csv, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, HERE)
import cbb_xpm_hist as XH
from h1_builder import tstat, KIT
H = XH.load(); INFO = {}
for r in csv.DictReader(open(KIT, newline='')):
    try: k = (str(int(float(r['pid']))), int(r['year'])); mp = float(r['min_per'] or 0)
    except ValueError: continue
    if k not in INFO or mp > INFO[k][1]: INFO[k] = (r['team'], mp)
P = defaultdict(list)       # pair start year -> rows
for (pid, y), q in H.items():
    nx = H.get((pid, y + 1)); a = INFO.get((pid, y)); b = INFO.get((pid, y + 1))
    if not nx or not nx['e'] or not q['e'] or not a or not b: continue
    base = [1.0, q['px2'], q['bpm'], q['bpm'] * a[1] / 100, math.log1p(q['e'] / 100)]
    P[y].append((base, [q['xpm'], (q['xpm'] + 1.4) * q['e'] / 40 * .68 * .01872], nx['xpm'], nx['e'], b[0]))


def run(cand):
    out = {}
    for n in range(2012, 2025):
        tr = [r for y in P if y < n for r in P[y]]; te = P[n]
        X = np.array([r[0] + (r[1] if cand else []) for r in tr]); y = np.array([r[2] for r in tr]); w = np.array([r[3] for r in tr])
        b = np.linalg.solve((X * w[:, None]).T @ X + 1e-6 * np.eye(X.shape[1]), (X * w[:, None]).T @ y)
        p = np.array([r[0] + (r[1] if cand else []) for r in te]) @ b; t = np.array([r[2] for r in te]); e = np.array([r[3] for r in te])
        T = defaultdict(lambda: [0.0, 0.0, 0.0])
        for (r, pi, ti, ei) in zip(te, p, t, e): q = T[r[4]]; q[0] += ei * pi; q[1] += ei * ti; q[2] += ei
        tp = np.array([q[0] / q[2] for q in T.values() if q[2] >= 1000]); ta = np.array([q[1] / q[2] for q in T.values() if q[2] >= 1000])
        out[n] = {'teamR2': float(1 - ((tp - ta) ** 2).sum() / ((ta - ta.mean()) ** 2).sum()), 'mse': float((e * (p - t) ** 2).sum() / e.sum()), 'teams': len(tp), 'n': len(te)}
    return out


a, b = run(False), run(True)
d = np.array([b[n]['teamR2'] - a[n]['teamR2'] for n in a]); dm = np.array([a[n]['mse'] - b[n]['mse'] for n in a])
out = {'pairs': {str(n): {'base': a[n], 'cand': b[n]} for n in a}, 'teamR2_base': round(float(np.mean([a[n]['teamR2'] for n in a])), 4), 'teamR2_cand': round(float(np.mean([b[n]['teamR2'] for n in a])), 4),
       't_team': round(tstat(d), 2), 'k_team': int((d > 0).sum()), 'rmse_base': round(float(np.mean([a[n]['mse'] for n in a]) ** .5), 4), 'rmse_cand': round(float(np.mean([b[n]['mse'] for n in a]) ** .5), 4),
       't_player': round(tstat(dm), 2), 'k_player': int((dm > 0).sum()), 'n': len(d)}
print({k: v for k, v in out.items() if k != 'pairs'})
json.dump(out, open(os.path.join(HERE, 'r2.json'), 'w'), indent=1)
