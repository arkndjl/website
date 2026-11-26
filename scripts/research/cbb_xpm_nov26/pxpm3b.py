#!/usr/bin/env python3
"""pxpm3.py found the fuller pXPM slightly worse in the game walk at the shipped params. Before calling it: does a retune
of the rating-memory knobs that set how much the preseason prior counts (lam = games the prior is worth, ecarry) change
the read?  python3 pxpm3b.py core|full  -> pxpm3b_<arm>.json (tune 2016-20 and held 2021-26 margin MAE at each setting)"""
import copy, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
os.environ.setdefault('OMP_NUM_THREADS', '1'); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cbb_roster as R
import cbb_xpm as XP
C = R.C
arm = sys.argv[1]; XP.CORE = arm == 'core'
games, btname, d1s, tprior, avs = C.load_all()
F = json.load(open(C.FIT)); P0 = F['params']; feats = F['feats']; C.NOFEAT = True
tp = copy.deepcopy(tprior); R.add_terms(tp, keys=('rost', 'rret', 'rtr', 'rfr', 'rnew', 'newmin', 'newc', 'newq', 'tenure'))
out = {}
for k, vals in (('lam', [2.0, 4.0, 6.0, 8.0]), ('ecarry', [0.4, 0.6, 0.8])):
    for v in vals:
        key = f'{k}={v}'
        if v == P0.get(k) and 'base' in out: out[key] = out['base']; continue
        P = dict(P0, **{k: v})
        W, rows = C.run_walk(P, games, tp, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        p = C.walk_pred(Xm, y, S, d1); ok = ~np.isnan(p) & d1; e = np.abs(p - y)
        r = {'tune': round(float(e[ok & (S <= C.TUNE_END)].mean()), 4), 'held': round(float(e[ok & (S > C.TUNE_END)].mean()), 4)}
        out[key] = r
        if v == P0.get(k): out['base'] = r
        print(arm, key, r, flush=True)
        json.dump(out, open(os.path.join(HERE, f'pxpm3b_{arm}.json'), 'w'), indent=1)
