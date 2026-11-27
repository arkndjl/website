#!/usr/bin/env python3
"""P4 check (prereg.md, round 2; not a test): the roster prior's history rows read pXPM (box form) through
cbb_xpm.pxpm_of, the frozen full-sample coefficients, where the live rows read a true projection. Size of the gap: the
frozen form against the walk-forward form (scripts/cbb_xpm_hist.py 'px') on next-season BPM, lines of 2012, 2015, 2018
(Barttorvik season files fetched to scripts/.cache).  -> r4.json"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cbb_xpm as XP, cbb_xpm_hist as XH
H = XH.load(); out = {}
for y in (2012, 2015, 2018):
    V = XP.values(y); a, b, t, w = [], [], [], []
    for pid, v in V.items():
        q = H.get((str(pid), y)); nx = H.get((str(pid), y + 1))
        if not q or not nx or not nx['e']: continue
        a.append(v[0]); b.append(q['px']); t.append(nx['bpm']); w.append(nx['e'])
    a, b, t, w = map(np.array, (a, b, t, w)); f = lambda p: float(np.sqrt((w * (p - t) ** 2).sum() / w.sum()))
    out[y] = {'n': len(t), 'rmse_frozen': round(f(a), 4), 'rmse_walk': round(f(b), 4), 'r': round(float(np.corrcoef(a, b)[0, 1]), 4), 'mean_abs_diff': round(float(np.abs(a - b).mean()), 3)}
    print(y, out[y])
json.dump(out, open(os.path.join(HERE, 'r4.json'), 'w'), indent=1)
