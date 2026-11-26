#!/usr/bin/env python3
"""Downstream test 2 (prereg): the CBB game model's walk (cbb_games.run_walk, shipped params and PRIOR_F) with the roster
prior's returner projection on pXPM (roster.py 'swap') against the shipped roster prior. Margin MAE, tune 2016-20 and
held out 2021-26, paired t (cbb_roster.main's cmp). Needs scripts/.cache/cbb/bpi (public_ratings.py --cbb-bpi).
-> game.json"""
import copy, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.environ.setdefault('OMP_NUM_THREADS', '1'); os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import roster as RS
R = RS.R; C = R.C
games, btname, d1s, tprior, avs = C.load_all()
F = json.load(open(C.FIT)); P = F['params']; feats = F['feats']
C.NOFEAT = True


def walk(tp):
    W, rows = C.run_walk(P, games, tp, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    return C.walk_pred(Xm, y, S, d1), y, S, d1, D


t0 = copy.deepcopy(tprior); R.xrow = RS.ORIG; R.add_terms(t0, keys=('rost', 'rret', 'rtr', 'rfr', 'rnew', 'newmin', 'newc', 'newq', 'tenure'))
t1 = copy.deepcopy(tprior); R.xrow = RS.make('swap'); R.add_terms(t1, keys=('rost', 'rret', 'rtr', 'rfr', 'rnew', 'newmin', 'newc', 'newq', 'tenure')); R.xrow = RS.ORIG
b, y, S, d1, D = walk(t0); p, *_ = walk(t1)
ok = ~np.isnan(b) & ~np.isnan(p) & d1
tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
lined = np.array([g.get('spread') is not None for g, _, _ in D])
e0, e1 = np.abs(b - y), np.abs(p - y)
out = {'tuneMae': [round(float(e0[tune].mean()), 4), round(float(e1[tune].mean()), 4)], 'tuneT': round(C.paired_t(e1[tune], e0[tune]), 2),
       'heldMae': [round(float(e0[held].mean()), 4), round(float(e1[held].mean()), 4)], 'heldT': round(C.paired_t(e1[held], e0[held]), 2),
       'linedHeldMae': [round(float(e0[held & lined].mean()), 4), round(float(e1[held & lined].mean()), 4)],
       'linedHeldT': round(C.paired_t(e1[held & lined], e0[held & lined]), 2),
       'bySeason': {int(s): round(float(e1[ok & (S == s)].mean() - e0[ok & (S == s)].mean()), 4) for s in sorted(set(S[ok].tolist()))}}
print(out); json.dump(out, open(os.path.join(HERE, 'game.json'), 'w'), indent=1)
