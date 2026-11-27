#!/usr/bin/env python3
"""H2 (prereg.md): Transfer% and landing are fit on pXPM board form after the season (px2) and served the board's xXPM,
which at portal time is mostly raw XPM to date. Models fit as shipped (2022-24 offseasons on px2); the held-out 2025->26
rows scored with input = px2 and with input = the season-end xXPM emulation.  -> h2.json"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, HERE)
import cbb_market_fit as MF
import cbb_xpm_hist as XH
from h1_builder import xx_end, tstat
H = XH.load()
by = MF.player_rows()
for y, rs in by.items():
    for r in rs: MF.CONF[(y, r['team'])] = r['conf']
TS, bt = MF.team_seasons(); loc = MF.geo(bt); raw, miss = MF.coaches()
PX = {(y, r['pid']): r.get('px') for y, rs in by.items() for r in rs}
a = b = 0.0
for (pid, y), q in H.items():
    if 2022 <= y <= 2024 and (pid, y - 1) not in H: a += q['e'] * q['xpm']; b += q['e']
NEW_MU = a / b


def serve(mode):
    n = 0
    for r in by[2025]:
        k = (str(r['pid']), 2025)
        if mode == 'xx' and k in H and H[k]['e']: r['px'] = xx_end(H, k[0], 2025, NEW_MU); n += 1
        else: r['px'] = PX[(2025, r['pid'])]
    return n


def move_fit():
    rows = MF.move_rows(by, TS, raw)
    keep, _ = MF.select(rows, MF.MOVE_F, {2022, 2023}, {2024}, lam=2.0)
    tr = [x for x in rows if x[0] in (2022, 2023, 2024)]
    X = np.array([[x[1][k] for k in keep] for x in tr], float); y = np.array([x[2] for x in tr]); mu, sd = MF.std(X, None)
    B = MF.mnl((X - mu) / sd, y, 3, lam=2.0); lm = np.array([x[0] == 2024 for x in tr]); B = MF.recal(((X - mu) / sd)[lm], y[lm], B, 3)
    return keep, mu, sd, B


def move_ll(M):
    keep, mu, sd, B = M
    te = [x for x in MF.move_rows(by, TS, raw) if x[0] == 2025]
    Xt = np.array([[x[1][k] for k in keep] for x in te], float); yt = np.array([x[2] for x in te]); P = MF.mnl_p((Xt - mu) / sd, B)
    return -np.log(P[np.arange(len(yt)), yt] + 1e-12), float(MF.auc((yt == 1).astype(int), P[:, 1])), float(P[:, 1].mean()), float((yt == 1).mean())


homes = MF.player_homes(by)


def land_fit():
    Xa, eva, cha, _ = MF.land_events(by, TS, raw, loc, range(MF.NIL0, 2025), homes)
    return MF.clogit(Xa, eva, cha, lam=1.0)


def land_ll(Bl):
    Xt, evt, cht, _ = MF.land_events(by, TS, raw, loc, [2025], homes)
    p = MF.clogit_p(Xt, evt, Bl); st = np.r_[0, np.flatnonzero(np.diff(evt)) + 1, len(evt)]; L, R = [], []
    for a, b in zip(st, st[1:]):
        c = np.flatnonzero(cht[a:b])
        if len(c): L.append(-math.log(p[a:b][c[0]] + 1e-12)); R.append(int((p[a:b] > p[a:b][c[0]]).sum()) + 1)
    return np.array(L), np.array(R)


serve('px'); M = move_fit(); Bl = land_fit()
m1, a1, pm1, ym = move_ll(M); l1, r1 = land_ll(Bl)
n = serve('xx'); m0, a0, pm0, _ = move_ll(M); l0, r0 = land_ll(Bl)
out = {'rows_emulated': n, 'new_mu': round(NEW_MU, 2),
       'move': {'n': len(m0), 'll_now': round(float(m0.mean()), 4), 'll_cand': round(float(m1.mean()), 4), 't': round(tstat(m0 - m1), 2), 'auc_now': round(a0, 3), 'auc_cand': round(a1, 3),
                'mean_p_move_now': round(pm0, 3), 'mean_p_move_cand': round(pm1, 3), 'moved': round(ym, 3)},
       'land': {'n': len(l0), 'll_now': round(float(l0.mean()), 3), 'll_cand': round(float(l1.mean()), 3), 't': round(tstat(l0 - l1), 2),
                'top10_now': round(float((r0 <= 10).mean()), 3), 'top10_cand': round(float((r1 <= 10).mean()), 3)}}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, 'h2.json'), 'w'), indent=1)
