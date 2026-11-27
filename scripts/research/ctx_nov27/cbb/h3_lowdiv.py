#!/usr/bin/env python3
"""H3 (prereg.md): the low-division arrival value (FV above 20 from a first D-I season) on shrunk rXPM in place of shrunk
BPM. The kit's 2009-16 arrivals from below D-I, leave one first-season year out, shipped fit (arrive_map, shipped keep).
 -> h3.json"""
import csv, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, HERE)
import cbb_lowdiv as L
import cbb_xpm_hist as XH
from h1_builder import tstat
KEEP = json.load(open(L.FIT))['arrive']['keep']
num = L.num
first = {}
for r in csv.DictReader(open(L.KIT, newline='')):
    pid = r['pid'] or r['name'] + r['team']; y = int(num(r['year'], 0))
    if pid not in first or y < first[pid][0]: first[pid] = (y, r)
rows = []
for yr, r in first.values():
    if not (2009 <= yr <= 2016 and (r['yr'] or '') in ('So', 'Jr', 'Sr')) or r['on3rk'] or r['rk247'] or num(r['rec'], 0) > 0: continue
    mp = num(r['mp'], 0) * num(r['gp'], 0); b = num(r['bpm'], L.BS_0); x = XH.get(r['pid'], yr, 'xpm')
    x = b if x is None else x
    sh = lambda v: (v * mp + L.BS_0 * L.BS_K) / (mp + L.BS_K)
    rows.append((yr, sh(b), sh(x), {'So': 2, 'Jr': 3, 'Sr': 4}[r['yr']], num(r['hti'], 78), num(r['realized_fv'], 20) - 20, 1.0 if num(r['nba_games'], 0) > 0 else 0.0))
A = np.array(rows, float); yrs = A[:, 0].astype(int); y = A[:, 5]; nba = A[:, 6]


def X(col):
    bs = A[:, col]; v = {'bs': bs, 'bs2': np.maximum(0, bs - 2), 'bs4': np.maximum(0, bs - 4), 'ht': A[:, 4], 'cls': A[:, 3]}
    return np.column_stack([v[k] for k in KEEP])


def oof(col):
    Xa = X(col); p = np.zeros(len(y))
    for f in sorted(set(yrs)):
        te = yrs == f; M = L.arrive_map(Xa[~te], y[~te], nba[~te]); M['keep'] = KEEP
        p[te] = L.arrive_val(M, Xa[te])
    return p


p0, p1 = oof(1), oof(2)
d = (p0 - y) ** 2 - (p1 - y) ** 2; dv = L.pdev(y, p0) - L.pdev(y, p1)
byy = [float(d[yrs == f].mean()) for f in sorted(set(yrs))]
out = {'n': len(y), 'keep': KEEP, 'r_bpm_rxpm_shrunk': round(float(np.corrcoef(A[:, 1], A[:, 2])[0, 1]), 4),
       'mse_bpm': round(float(((p0 - y) ** 2).mean()), 4), 'mse_rxpm': round(float(((p1 - y) ** 2).mean()), 4), 't': round(tstat(d), 2),
       'dev_bpm': round(float(L.pdev(y, p0).mean()), 4), 'dev_rxpm': round(float(L.pdev(y, p1).mean()), 4), 't_dev': round(tstat(dv), 2),
       'k': int(sum(v > 0 for v in byy)), 'folds': len(byy)}
print(out)
json.dump(out, open(os.path.join(HERE, 'h3.json'), 'w'), indent=1)
