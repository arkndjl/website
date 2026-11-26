#!/usr/bin/env python3
"""Transfer% and landing (scripts/cbb_market_fit.py: NIL era, fit 2022-24 offseasons, tested on 2025->26). The season's BPM in the
inputs -> rXPM (descriptive: what he did), and pXPM board (point in time: what he will be worth).
Score: per-row log loss on the held-out offseason (move: recalibrated multinomial; landing: log P(chosen school) per move),
paired t over rows / moves.  -> market.json"""
import json, math, os, sys
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import cbb_market_fit as MF
by = MF.player_rows()
for y, rs in by.items():
    for r in rs: MF.CONF[(y, r['team'])] = r['conf']
TS, bt = MF.team_seasons(); loc = MF.geo(bt); raw, miss = MF.coaches()
ORIG = {(y, r['pid']): r.get('bpm') for y, rs in by.items() for r in rs}


def setk(k):
    n = 0
    for y, rs in by.items():
        for r in rs:
            v = C.get(r['pid'], y, k) if k else None; n += v is None
            r['bpm'] = v if v is not None else ORIG[(y, r['pid'])]
    return n


def move_ll():
    rows = MF.move_rows(by, TS, raw)
    keep, _ = MF.select(rows, MF.MOVE_F, {2022, 2023}, {2024}, lam=2.0)
    tr = [x for x in rows if x[0] in (2022, 2023, 2024)]; te = [x for x in rows if x[0] == 2025]
    X = np.array([[x[1][k] for k in keep] for x in tr], float); y = np.array([x[2] for x in tr]); mu, sd = MF.std(X, None)
    B = MF.mnl((X - mu) / sd, y, 3, lam=2.0); lm = np.array([x[0] == 2024 for x in tr]); B = MF.recal(((X - mu) / sd)[lm], y[lm], B, 3)
    Xt = np.array([[x[1][k] for k in keep] for x in te], float); yt = np.array([x[2] for x in te]); P = MF.mnl_p((Xt - mu) / sd, B)
    return -np.log(P[np.arange(len(yt)), yt] + 1e-12), [(x[3], x[4]) for x in te], float(MF.auc((yt == 1).astype(int), P[:, 1]))


def land_ll():
    homes = MF.player_homes(by)
    Xa, eva, cha, _ = MF.land_events(by, TS, raw, loc, range(MF.NIL0, 2025), homes); Xt, evt, cht, it_ = MF.land_events(by, TS, raw, loc, [2025], homes)
    p = MF.clogit_p(Xt, evt, MF.clogit(Xa, eva, cha, lam=1.0)); st = np.r_[0, np.flatnonzero(np.diff(evt)) + 1, len(evt)]; L, R = [], []
    for a, b in zip(st, st[1:]):
        c = np.flatnonzero(cht[a:b])
        if len(c): L.append(-math.log(p[a:b][c[0]] + 1e-12)); R.append(int((p[a:b] > p[a:b][c[0]]).sum()) + 1)
    return np.array(L), np.array(R)


out = {}
setk(None); m0, k0, a0 = move_ll(); l0, r0 = land_ll()
out['base'] = {'move_n': len(m0), 'move_ll': round(float(m0.mean()), 4), 'move_auc': round(a0, 3), 'land_n': len(l0), 'land_ll': round(float(l0.mean()), 3), 'land_top10': round(float((r0 <= 10).mean()), 3)}
print(out['base'], flush=True)
for nm, k in (('rXPM for BPM', 'xpm'), ('pXPM board for BPM', 'px2')):
    miss_n = setk(k); m1, k1, a1 = move_ll(); l1, r1 = land_ll(); assert k1 == k0
    out[nm] = {'move_ll': round(float(m1.mean()), 4), 'move_t': round(C.tstat(m0 - m1), 2), 'move_auc': round(a1, 3),
               'land_ll': round(float(l1.mean()), 3), 'land_t': round(C.tstat(l0 - l1), 2), 'land_top10': round(float((r1 <= 10).mean()), 3), 'rows_without': miss_n}
    print(nm, out[nm], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'market.json'), 'w'), indent=1)
