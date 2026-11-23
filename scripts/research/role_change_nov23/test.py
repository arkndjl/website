#!/usr/bin/env python3
"""Tests on rows.pkl.gz (build.py). Target = the full-season grade (as cbb_live_backtest.py fits k), one season held out
at a time; realized NBA FV (2010-19) as the second check. Gate: paired t < -2 over players, better in 12+/17 held-out
seasons, the top 300 / role risers not worse."""
import gzip, os, pickle, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import harness as H
import cbb_live_backtest as B
R = pickle.load(gzip.open(os.path.join(HERE, 'rows.pkl.gz')))
I, J, N, MP = R['I'], R['J'], R['N'], R['MP']
M = {k: v[I] for k, v in R['meta'].items()}
NEW = M['new'] > 0.5; YR = M['y'].astype(int); PID = R['pid'][I]
T = R['e_full'][I]; P0 = R['e_pre'][I]; NOW = R['e_proj']; ROLE = R['e_role']; NR = R['NR']
KG = B.KGRID
SEAS = sorted(set(YR))
RET = ~NEW
rho = MP / np.maximum(M['prev_mp'], 1.0)
riser = RET & (MP >= 20) & (rho >= 1.5)
top = np.zeros(len(T), bool)
for y in SEAS:
    m = YR == y; top[m] = T[m] >= np.sort(np.unique(T[m]))[::-1][:300][-1]

def blend(k, now=NOW, n=N): w = n / (n + k); return (1 - w) * P0 + w * now
def se(k, now=NOW, n=N): return (blend(k, now, n) - T) ** 2
def bestk(mask, f): return min(KG, key=lambda k: f(k)[mask].mean())

def report(name, loss_new, loss_base, mask):
    t = H.paired(loss_new[mask], loss_base[mask], PID[mask])
    sb = sum(1 for y in SEAS if loss_new[mask & (YR == y)].mean() < loss_base[mask & (YR == y)].mean())
    out = {'mseBase': round(float(loss_base[mask].mean()), 4), 'mseNew': round(float(loss_new[mask].mean()), 4), 't': round(t['t'], 2), 'seasons': f'{sb}/{len(SEAS)}'}
    for nm, sub in (('top', top), ('riser', riser)):
        mm = mask & sub
        out[nm] = [round(float(loss_base[mm].mean()), 3), round(float(loss_new[mm].mean()), 3), round(H.paired(loss_new[mm], loss_base[mm], PID[mm])['t'], 2)]
    print(name, json.dumps(out)); return out

# baseline: one k for returners, LOSO
base = np.zeros(len(T))
for y in SEAS:
    k = bestk(RET & (YR != y), se); base[YR == y] = se(k)[YR == y]
print('baseline returner k all', bestk(RET, se))
bl = blend(156)
for nm, m in (('all returners', RET), ('risers', riser), ('risers top', riser & top), ('top', RET & top)):
    print(f'bias {nm:14s} n {m.sum():7d}  mean(blend - full) {np.mean(bl[m] - T[m]):+.3f}  pre-full {np.mean(P0[m] - T[m]):+.3f}  now-full {np.mean(NOW[m] - T[m]):+.3f}')
# bias by prior-season minutes band and by role ratio
BANDS = [0, 100, 250, 500, 800, 5000]
for a, b in zip(BANDS, BANDS[1:]):
    m = RET & (M['prev_n'] >= a) & (M['prev_n'] < b)
    print(f'prev min {a:4d}-{b:4d} n {m.sum():6d} best k {bestk(m, se):5d}  bias {np.mean(bl[m] - T[m]):+.3f}')
for a, b in ((0, .75), (.75, 1.25), (1.25, 1.75), (1.75, 3), (3, 99)):
    m = RET & (rho >= a) & (rho < b) & (M['prev_mp'] > 0)
    print(f'mpg ratio {a}-{b} n {m.sum():6d} best k {bestk(m, se):5d}  bias {np.mean(bl[m] - T[m]):+.3f}')

res = {}
# A: k by last season's minutes, k = kmax * (m + a) / (m + c)  (a < c: thin prior -> small k)
def kA(p): kmax, c = p; return kmax * (M['prev_n'] + 60) / (M['prev_n'] + c)
GA = [(km, c) for km in (120, 156, 200, 260, 340, 450) for c in (60, 100, 200, 400, 800)]
def seA(p): return se(kA(p))
lossA = np.zeros(len(T)); pick = []
for y in SEAS:
    tr = RET & (YR != y); p = min(GA, key=lambda p: seA(p)[tr].mean()); pick.append(p); lossA[YR == y] = seA(p)[YR == y]
print('A picks', sorted(set(pick)))
res['A_prev_minutes'] = report('A prev-min k', lossA, base, RET)
# B: k by role ratio: k = k0 / rho^g
def seB(p): k0, g = p; return se(k0 / np.clip(rho, 0.5, 4) ** g)
GB = [(k0, g) for k0 in (100, 130, 156, 190, 230) for g in (0, .25, .5, .75, 1.0, 1.5)]
lossB = np.zeros(len(T)); pick = []
for y in SEAS:
    tr = RET & (YR != y); p = min(GB, key=lambda p: seB(p)[tr].mean()); pick.append(p); lossB[YR == y] = seB(p)[YR == y]
print('B picks', sorted(set(pick)))
res['B_role_ratio'] = report('B role-ratio k', lossB, base, RET)
# C: role-run now grade (only where a role run exists; else as is), own k
has = ~np.isnan(NR)
print('role runs', int((has & RET).sum()), 'of', int(RET.sum()), 'returner checkpoints;', int((has & NEW).sum()), 'newcomer')
def seC(k): n2 = np.where(has, NR, N); now2 = np.where(has, ROLE, NOW); return se(k, now2, n2)
lossC = np.zeros(len(T))
for y in SEAS:
    k = bestk(RET & (YR != y), seC); lossC[YR == y] = seC(k)[YR == y]
res['C_role_run'] = report('C role run', lossC, base, RET)
res['C_role_run_rows'] = report('C role run (rows with a run)', lossC, base, RET & has)
# C2: role-run grade mixed with the full-to-date grade: now = (1-q) now + q role
def seC2(p):
    k, q = p; return se(k, np.where(has, (1 - q) * NOW + q * ROLE, NOW))
GC = [(k, q) for k in (130, 156, 190) for q in (0, .15, .3, .5)]
lossC2 = np.zeros(len(T)); pick = []
for y in SEAS:
    tr = RET & (YR != y); p = min(GC, key=lambda p: seC2(p)[tr].mean()); pick.append(p); lossC2[YR == y] = seC2(p)[YR == y]
print('C2 picks', sorted(set(pick)))
res['C2_role_mix'] = report('C2 role mix', lossC2, base, RET)
# newcomers too for C (a freshman who moved into the rotation)
baseN = np.zeros(len(T))
for y in SEAS:
    k = bestk(NEW & (YR != y), se); baseN[YR == y] = se(k)[YR == y]
lossCN = np.zeros(len(T))
for y in SEAS:
    k = bestk(NEW & (YR != y), seC); lossCN[YR == y] = seC(k)[YR == y]
res['C_role_run_newcomers'] = report('C role run newcomers', lossCN, baseN, NEW)
json.dump(res, open(os.path.join(HERE, 'results_self.json'), 'w'), indent=1)
np.savez_compressed(os.path.join(HERE, 'loss.npz'), base=base, A=lossA, B=lossB, C=lossC)
