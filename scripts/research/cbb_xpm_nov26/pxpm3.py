#!/usr/bin/env python3
"""The fuller pXPM (box form + team context + recruit rating; cbb_xpm.CORE = False) against the box form (CORE = True)
where the fitted models read it: the roster-prior harness (audit.roster_prior, walk-forward) and the game walk with the
shipped params (prod_check.py's protocol). Pre-registered in prereg.md "pXPM round 3".  -> pxpm3.json"""
import copy, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb')); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import audit as A
import cbb_roster as R
import cbb_xpm as XP
C = R.C
out = {}; sc = {}
for core in (True, False):
    XP.CORE = core; RP = A.roster_prior()
    vn = {n: {p: v for p, (v, k) in RP[n].items() if k in ('ret', 'tr', 'back')} for n in A.PAIRS}
    sc[core] = A.predict(lambda n: vn[n])[2]
d = [sc[False]['byPair'][n] - sc[True]['byPair'][n] for n in A.PAIRS]; t, p = A.paired_t(d)
out['roster'] = {'teamR2': [sc[True]['teamR2'], sc[False]['teamR2']], 'playerR_vsBPM': [sc[True]['playerR_vsBPM'], sc[False]['playerR_vsBPM']], 'pairsBetter': int(sum(x > 0 for x in d)), 't': t}
print(out, flush=True)
games, btname, d1s, tprior, avs = C.load_all()
F = json.load(open(C.FIT)); P = F['params']; feats = F['feats']; C.NOFEAT = True
res = {}
for core in (True, False):
    XP.CORE = core; tp = copy.deepcopy(tprior); R.add_terms(tp, keys=('rost', 'rret', 'rtr', 'rfr', 'rnew', 'newmin', 'newc', 'newq', 'tenure'))
    W, rows = C.run_walk(P, games, tp, btname, d1s, avs)
    Dm, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    res[core] = (C.walk_pred(Xm, y, S, d1), y, S, d1, Dm)
XP.CORE = False
b, y, S, d1, Dm = res[True]; p = res[False][0]
ok = ~np.isnan(b) & ~np.isnan(p) & d1; tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
lined = np.array([g.get('spread') is not None for g, _, _ in Dm]); e0, e1 = np.abs(b - y), np.abs(p - y)
out['game'] = {'tuneMae': [round(float(e0[tune].mean()), 4), round(float(e1[tune].mean()), 4)], 'tuneT': round(C.paired_t(e1[tune], e0[tune]), 2),
               'heldMae': [round(float(e0[held].mean()), 4), round(float(e1[held].mean()), 4)], 'heldT': round(C.paired_t(e1[held], e0[held]), 2),
               'linedHeldMae': [round(float(e0[held & lined].mean()), 4), round(float(e1[held & lined].mean()), 4)],
               'linedHeldT': round(C.paired_t(e1[held & lined], e0[held & lined]), 2),
               'bySeason': {int(s): round(float(e1[ok & (S == s)].mean() - e0[ok & (S == s)].mean()), 4) for s in sorted(set(S[ok].tolist()))}}
print(out); json.dump(out, open(os.path.join(HERE, 'pxpm3.json'), 'w'), indent=1)
