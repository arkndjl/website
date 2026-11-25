#!/usr/bin/env python3
"""CS2 metric audit (Nov 24 2026): pre-registered candidates (prereg.md). -> candidates.json
Predictive P1-P3: shipped walk-forward procedure (cs2_players.fit: weights on tune maps, scale a on tune months [::2],
grid choices on tune months [1::2]); held months Jul 2025 - Oct 2026 scored once, t by month on map squared error.
Descriptive D1-D4: held-out-half describe R2 a month (harness.py), t by month, held months; tune months for grid/sign."""
import json, math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
from common import P

M = C.load(); p0 = dict(C.SHIP)
last = '2026-10'
tm, hm = C.months('2024-07', '2025-06'), C.months('2025-07', last)
X0 = M.X.copy()
XR = np.column_stack([X0, M.rt])
tune_g = M.gd < P.ordd(P.TUNE[1])
MAPS = {k: i for i, k in enumerate(sorted(set(M.mapname)))}; mcode = np.array([MAPS[x] for x in M.mapname])


def setX(X): M.X = X


# ---------- predictive ----------
def offsets(c, th, T, p, kmap):
    """player x map residual, decayed like the rating, shrunk kmap rounds toward 0"""
    m = M.d < T
    w = M.R * np.exp(-(T - M.d) * math.log(2) / p['h']) * m
    opp = th[M.p][M.five[M.g, 1 - M.side]].mean(1)
    res = c + p['opp'] * opp - th[M.p]
    key = M.p * len(MAPS) + mcode[M.g]; nk = len(M.pids) * len(MAPS)
    return np.bincount(key, w * res, nk) / (np.bincount(key, w, nk) + kmap)


def month_x(c, p, mo, kmap=None):
    T, T2 = C.T0(mo), C.T1(mo)
    th, _ = P.ratings(M, c, T, p)
    gi = np.where((M.gd >= T) & (M.gd < T2))[0]
    va, vb = th[M.p[M.five[gi, 0]]], th[M.p[M.five[gi, 1]]]
    if kmap is not None:
        off = offsets(c, th, T, p, kmap); mk = mcode[gi][:, None]
        va = va + off[M.p[M.five[gi, 0]] * len(MAPS) + mk]; vb = vb + off[M.p[M.five[gi, 1]] * len(MAPS) + mk]
    return (va.sum(1) - vb.sum(1)) / 200, M.y[M.five[gi, 0, 0]] - 0.5, th, T, T2


def scored(c, p, mos, kmap=None, a=None):
    if a is None:
        num = den = 0.0
        for mo in tm[::2]:
            x, y, *_ = month_x(c, p, mo, kmap); num += (x * y).sum(); den += (x * x).sum()
        a = num / den
    e, xs, ys, ws = {}, [], [], []
    c0 = P.contributions(M, *BASEW, 0.0)
    for mo in mos:
        x, y, th, T, T2 = month_x(c, p, mo, kmap); e[mo] = (y - a * x) ** 2
        m = (M.d >= T) & (M.d < T2); n = len(M.pids)
        R = np.bincount(M.p, M.R * m, n); raw = np.bincount(M.p, c0 * M.R * m, n) / np.maximum(R, 1)
        k = R >= 100; xs += list(th[k]); ys += list(raw[k]); ws += list(R[k])
    return e, a, C.wcorr(xs, ys, ws)


def ttest(eb, ec, mos):
    d = [ec[m].mean() - eb[m].mean() for m in mos]; t = C.tby(d)
    return t, float(C.tcdf(t, len(d) - 1)), int(sum(x < 0 for x in d))


out = {'predictive': {}, 'descriptive': {}}
b, ml, _ = P.stat_weights(M, tune_g); BASEW = (b, ml)
cb = P.contributions(M, b, ml, p0['pm'])
eb, ab, rb = scored(cb, p0, hm); ebt, _, _ = scored(cb, p0, tm[1::2], a=ab)
base_mse = float(np.concatenate(list(eb.values())).mean())
cands = {}
# P1 bo3.gg rating as a stat
setX(XR); b1, m1, _ = P.stat_weights(M, tune_g); c1 = P.contributions(M, b1, m1, p0['pm']); setX(X0)
cands['P1 bo3.gg rating as a 14th stat'] = (c1, p0, None)
# P2 player x map offsets, kmap on tune months [1::2]
g2 = []
for km in (100, 300, 1000, 3000):
    e, a, _ = scored(cb, p0, tm[1::2], kmap=km); g2.append((float(np.concatenate(list(e.values())).mean()), km))
    print('kmap', km, g2[-1][0], flush=True)
km = min(g2)[1]
cands[f'P2 player x map offsets (kmap {km})'] = (cb, p0, km)
# P3 ridge l2 on tune months [1::2]
g3 = []
for l2 in (1e-3, 1e-2, 3e-2):
    b3, m3, _ = P.stat_weights(M, tune_g, l2); c3 = P.contributions(M, b3, m3, p0['pm'])
    e, a, _ = scored(c3, p0, tm[1::2]); g3.append((float(np.concatenate(list(e.values())).mean()), l2, c3))
    print('l2', l2, g3[-1][0], flush=True)
bt = float(np.concatenate(list(ebt.values())).mean()); best3 = min(g3, key=lambda z: z[0])
cands[f'P3 stat-weight ridge l2 {best3[1]:g}'] = (best3[2], p0, None)
out['predictive']['grids'] = {'kmap': g2, 'l2': [(z[0], z[1]) for z in g3], 'tuneBase': bt}
rows = []
for nm, (c, p, km) in cands.items():
    e, a, r = scored(c, p, hm, kmap=km)
    et, _, _ = scored(c, p, tm[1::2], kmap=km, a=a)
    t, pv, nb = ttest(eb, e, hm); tt, _, _ = ttest(ebt, et, tm[1::2])
    rows.append({'name': nm, 'base': round(base_mse, 6), 'cand': round(float(np.concatenate(list(e.values())).mean()), 6),
                 't': round(t, 2), 'p': pv, 'monthsBetter': f'{nb}/{len(hm)}', 'tTune': round(tt, 2),
                 'playerR': [round(rb, 4), round(r, 4)], 'a': round(a, 3)})
    print(rows[-1], flush=True)

# ---------- descriptive ----------


def dvals(mo, h, pm=0.5, X=None, kpri=0):
    """season RWA from the month's maps outside hash half h (as harness.values), variants"""
    Ta, Tb = C.T0(mo), C.T1(mo)
    gmo = (M.gd >= Ta) & (M.gd < Tb); rmo = (M.d >= Ta) & (M.d < Tb)
    eg, er = gmo & (M.half == h), rmo & (M.half[M.g] == h)
    if X is not None: setX(X)
    beta, ml, _ = C.weights(M, Tb, eg)
    c = P.contributions(M, beta, ml, pm); c5 = P.contributions(M, beta, ml, p0['pm'])
    setX(X0)
    th, _ = C.ratings_ex(M, c5, Tb, p0, er)
    lift = p0['ssg'] * C.sa_share_ex(M, Tb, er)
    opp = th[M.p][M.five[M.g, 1 - M.side]].mean(1)
    win = rmo & ~er; n = len(M.pids); w = M.R * win
    num, R = np.bincount(M.p, w * (c + p0['opp'] * opp), n), np.bincount(M.p, w, n)
    if kpri:
        th0, _ = C.ratings_ex(M, c5, Ta, p0); th0 = th0 - p0['ssg'] * C.sa_share_ex(M, Ta)
        v = (num + kpri * th0) / (R + kpri)
    else:
        v = num / np.maximum(R, 1e-9)
        low = (R > 0) & (R < 100); v[R == 0] = np.average(v[low], weights=R[low])
    return v + lift, np.where(gmo & (M.half == h))[0]


def dr2(mo, **kw):
    xs, ys = [], []
    for h in (0, 1):
        v, gh = dvals(mo, h, **kw); x, y = C.mapxy(M, v, gh); xs.append(x); ys.append(y)
    return C.r2(np.concatenate(xs), np.concatenate(ys))


allm = tm + hm
base_d = {mo: dr2(mo) for mo in allm}
g4 = {}
for k in (50, 100, 200, 400):
    g4[k] = float(np.mean([dr2(mo, kpri=k) for mo in tm])); print('kpri', k, g4[k], flush=True)
k4 = max(g4, key=g4.get)
dc = {'D1 season RWA pm 1.0': dict(pm=1.0), 'D2 season RWA pm 0 (box only)': dict(pm=0.0),
      'D3 bo3.gg rating as a 14th stat': dict(X=XR), f'D4 shrink toward rating at month start (k {k4})': dict(kpri=k4)}
drows = []
for nm, kw in dc.items():
    cd = {mo: dr2(mo, **kw) for mo in allm}
    d = [cd[m] - base_d[m] for m in hm]; dt_ = [cd[m] - base_d[m] for m in tm]
    t = C.tby(d)
    drows.append({'name': nm, 'base': round(float(np.mean([base_d[m] for m in hm])), 4), 'cand': round(float(np.mean([cd[m] for m in hm])), 4),
                  't': round(t, 2), 'p': float(1 - C.tcdf(t, len(d) - 1)), 'monthsBetter': f'{sum(x > 0 for x in d)}/{len(d)}',
                  'tTune': round(C.tby(dt_), 2)})
    print(drows[-1], flush=True)
out['descriptive']['grids'] = {'kpri': g4}


def holm(rows, tune_sign):
    o = sorted(range(len(rows)), key=lambda i: rows[i]['p']); stop = False
    for j, i in enumerate(o):
        r = rows[i]; r['pHolm'] = min(1.0, r['p'] * (len(rows) - j))
        ok = not stop and r['pHolm'] < .05 and tune_sign(r)
        if r['pHolm'] >= .05: stop = True
        r['pass'] = bool(ok)
    return rows


out['predictive']['rows'] = holm(rows, lambda r: r['tTune'] < 0 and r['playerR'][1] >= r['playerR'][0] - .01)
out['descriptive']['rows'] = holm(drows, lambda r: r['tTune'] > 0)
print(json.dumps(out, indent=1, default=float))
Path(__file__).with_name('candidates.json').write_text(json.dumps(out, indent=1, default=float))
