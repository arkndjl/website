#!/usr/bin/env python3
"""CS2 players, port round (prereg.md C-P1, C-D1..C-D4) -> cs2_port.json
Round-1 harness (scripts/research/metric_audit_nov24/cs2/common.py) on a copy of scripts/cs2_players.py with the
duplicate-map fix (cs2_maps_dedupe.patch); maps before 2026-11-11 only."""
import importlib.util, json, math, sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / 'scripts'))
spec = importlib.util.spec_from_file_location('cs2_players', HERE / '_cs2_players_dedup.py')
P = importlib.util.module_from_spec(spec); sys.modules['cs2_players'] = P; spec.loader.exec_module(P)
P.ROOT = HERE.parents[4]; P.FIT = P.ROOT / 'data' / 'cs2_players_fit.json'; P.OUT = P.ROOT / 'data' / 'cs2_players_scratch_unused.json'
sys.path.insert(0, str(HERE.parents[1] / 'cs2'))
import common as C  # noqa: E402
assert C.P is P

M = C.load(); p0 = dict(C.SHIP)
tm, hm = C.months('2024-07', '2025-06'), C.months('2025-07', C.LAST)
tune_g = M.gd < P.ordd(P.TUNE[1])
b0, ml0, _ = P.stat_weights(M, tune_g)
cb = P.contributions(M, b0, ml0, p0['pm']); c0 = P.contributions(M, b0, ml0, 0.0)


# ---------------------------------------------------------------- predictive: C-P1 tier weighting
def ratings_tw(c, T, p, lam):
    """cs2_players.ratings with B/C/D-tier map rows weighted lam"""
    m = M.d < T
    w = M.R * np.exp(-(T - M.d) * math.log(2) / p['h']) * m * np.where(M.tier >= 3, lam, 1.0)
    n = len(M.pids); theta = np.zeros(n); wsum = np.bincount(M.p, w, n)
    lift = p.get('ssg', 0.0) * P.sa_share(M, T) if p.get('ssg') else 0.0
    for _ in range(6):
        th_row = (theta + lift)[M.p]
        opp = th_row[M.five[M.g, 1 - M.side]].mean(1)
        adj = c + p['opp'] * opp
        pri = p.get('prior', 0.0)
        if p.get('tp'):
            mate = (theta[M.p][M.five[M.g, M.side]].sum(1) - theta[M.p]) / 4
            pri = pri + p['tp'] * np.bincount(M.p, w * mate, n) / np.maximum(wsum, 1e-9)
        theta = (np.bincount(M.p, w * adj, n) + p['k'] * pri) / (wsum + p['k'])
    return theta + lift


TH = {}


def month_x(mo, lam):
    if (mo, lam) not in TH:
        TH[(mo, lam)] = ratings_tw(cb, C.T0(mo), p0, lam)
    th = TH[(mo, lam)]; T, T2 = C.T0(mo), C.T1(mo)
    gi = np.where((M.gd >= T) & (M.gd < T2))[0]
    x = (th[M.p[M.five[gi, 0]]].sum(1) - th[M.p[M.five[gi, 1]]].sum(1)) / 200
    return x, M.y[M.five[gi, 0, 0]] - 0.5, th, T, T2


def scored(lam, mos, a=None):
    if a is None:
        num = den = 0.0
        for mo in tm[::2]:
            x, y, *_ = month_x(mo, lam); num += (x * y).sum(); den += (x * x).sum()
        a = num / den
    e, xs, ys, ws = {}, [], [], []
    for mo in mos:
        x, y, th, T, T2 = month_x(mo, lam); e[mo] = (y - a * x) ** 2
        m = (M.d >= T) & (M.d < T2); n = len(M.pids)
        R = np.bincount(M.p, M.R * m, n); raw = np.bincount(M.p, c0 * M.R * m, n) / np.maximum(R, 1)
        k = R >= 100; xs += list(th[k]); ys += list(raw[k]); ws += list(R[k])
    return e, a, C.wcorr(xs, ys, ws)


assert np.allclose(ratings_tw(cb, C.T0('2025-03'), p0, 1.0), P.ratings(M, cb, C.T0('2025-03'), p0)[0])
out = {'mapsUsed': len(M.games)}
eb, ab, rb = scored(1.0, hm); ebt, _, _ = scored(1.0, tm[1::2], a=ab)
grid = {}
for lam in (0.85, 0.7, 0.5):
    e, a, _ = scored(lam, tm[1::2]); grid[lam] = float(np.concatenate(list(e.values())).mean())
    print('lam', lam, grid[lam], flush=True)
grid[1.0] = float(np.concatenate(list(ebt.values())).mean())
lam = min((0.85, 0.7, 0.5), key=grid.get)
e, a, r = scored(lam, hm); et, _, _ = scored(lam, tm[1::2], a=a)
d = [e[m].mean() - eb[m].mean() for m in hm]; t = C.tby(d)
dt_ = [et[m].mean() - ebt[m].mean() for m in tm[1::2]]
out['P'] = [{'name': f'C-P1 tier weighting (B/C/D maps x{lam})', 'tuneGrid': grid, 'base': round(float(np.concatenate(list(eb.values())).mean()), 6),
             'cand': round(float(np.concatenate(list(e.values())).mean()), 6), 't': round(t, 2), 'p': float(C.tcdf(t, len(d) - 1)),
             'monthsBetter': f'{sum(x < 0 for x in d)}/{len(d)}', 'tTune': round(C.tby(dt_), 2), 'playerR': [round(rb, 4), round(r, 4)]}]
print(out['P'], flush=True)


# ---------------------------------------------------------------- descriptive: C-D1..C-D4
KG = (50, 100, 200, 400, 800)


def fill(v, R):
    low = (R > 0) & (R < 100)
    v = v.copy(); v[R == 0] = np.average(v[low], weights=R[low]) if low.any() else np.average(v[R > 0], weights=R[R > 0]); return v


def dvals(mo, h):
    Ta, Tb = C.T0(mo), C.T1(mo)
    gmo = (M.gd >= Ta) & (M.gd < Tb); rmo = (M.d >= Ta) & (M.d < Tb)
    eg, er = gmo & (M.half == h), rmo & (M.half[M.g] == h)
    beta, ml, _ = C.weights(M, Tb, eg)
    c5 = P.contributions(M, beta, ml, p0['pm'])
    th, _ = C.ratings_ex(M, c5, Tb, p0, er)
    lift = p0['ssg'] * C.sa_share_ex(M, Tb, er)
    opp = th[M.p][M.five[M.g, 1 - M.side]].mean(1)
    win = rmo & ~er; n = len(M.pids); w = M.R * win; adj = c5 + p0['opp'] * opp
    num, R = np.bincount(M.p, w * adj, n), np.bincount(M.p, w, n)
    V = {'base': fill(num / np.maximum(R, 1e-9), R) + lift}
    for k in KG: V[('D1', k)] = num / (R + k) + lift
    cnt = np.bincount(M.p, win * 1.0, n)
    V['D2'] = fill(np.bincount(M.p, win * adj, n) / np.maximum(cnt, 1e-9), R) + lift
    for nm, key in (('D3', 'K-D per round'), ('D4', 'ADR')):
        x = M.pub[key]; s = np.bincount(M.p, w * x, n); mu = s.sum() / R.sum()
        V[(nm, 'base')] = fill(s / np.maximum(R, 1e-9), R)
        for k in KG: V[(nm, k)] = (s + k * mu) / (R + k)
    return V, np.where(gmo & (M.half == h))[0]


DR = {}
for mo in tm + hm:
    xs = {}
    for h in (0, 1):
        V, gh = dvals(mo, h)
        for key, v in V.items():
            x, y = C.mapxy(M, v, gh); xs.setdefault(key, ([], [])); xs[key][0].append(x); xs[key][1].append(y)
    DR[mo] = {key: C.r2(np.concatenate(a), np.concatenate(b)) for key, (a, b) in xs.items()}
    print(mo, round(DR[mo]['base'], 4), round(DR[mo][('D1', 200)], 4), round(DR[mo]['D2'], 4), flush=True)


def drow(name, base, cand):
    d = [DR[m][cand] - DR[m][base] for m in hm]; dt2 = [DR[m][cand] - DR[m][base] for m in tm]; t = C.tby(d)
    return {'name': name, 'base': round(float(np.mean([DR[m][base] for m in hm])), 4), 'cand': round(float(np.mean([DR[m][cand] for m in hm])), 4),
            't': round(t, 2), 'p': float(1 - C.tcdf(t, len(d) - 1)), 'monthsBetter': f'{sum(x > 0 for x in d)}/{len(d)}', 'tTune': round(C.tby(dt2), 2)}


rows, tg = [], {}
for nm, base in (('D1', 'base'), ('D3', ('D3', 'base')), ('D4', ('D4', 'base'))):
    g = {k: float(np.mean([DR[m][(nm, k)] for m in tm])) for k in KG}; tg[nm] = g; k = max(g, key=g.get)
    label = {'D1': f'C-D1 season RWA shrunk toward 0 (k {k} rounds)', 'D3': f'C-D3 K-D per round shrunk to the mean (k {k})',
             'D4': f'C-D4 ADR shrunk to the mean (k {k})'}[nm]
    rows.append(drow(label, base, (nm, k)))
rows.insert(1, drow('C-D2 season RWA as per-map mean', 'base', 'D2'))
o = sorted(range(len(rows)), key=lambda i: rows[i]['p']); stop = False
for j, i in enumerate(o):
    r = rows[i]; r['pHolm'] = min(1.0, r['p'] * (len(rows) - j))
    r['pass'] = bool(not stop and r['pHolm'] < .05 and r['tTune'] > 0)
    if r['pHolm'] >= .05: stop = True
pr = out['P'][0]; pr['pHolm'] = pr['p']; pr['pass'] = bool(pr['p'] < .05 and pr['tTune'] < 0 and pr['playerR'][1] >= pr['playerR'][0] - .01)
out['D'] = rows; out['tuneGrids'] = tg
for r in rows: print(r)
(HERE / 'cs2_port.json').write_text(json.dumps(out, indent=1, default=str))
