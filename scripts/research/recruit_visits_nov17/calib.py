# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Calibration of the kept CFB model (visits + expert picks): the shown lean's probability by bin, by class and by
whether he has expert picks, and a walk-forward temperature (each held class scaled by the T that maximises
held-out LL on the held classes before it). Follow-up to visit_tests.py, written after its calibration table showed
the top bins over-confident; reported, then gated like the tests (paired t >= 2, 2/3 classes)."""
import json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import visit_tests as V  # noqa: E402
C, J = V.C, V.J

KEPT = V.SPEC['cfb'][0] + V.FAM['V visits'] + V.FAM['E experts']


def ll_t(us, ys, T):
    s = 0.0
    for u, c in zip(us, ys):
        z = u * T; z = z - z.max(); s += z[c] - math.log(np.exp(z).sum())
    return s


def best_t(us, ys):
    grid = np.arange(0.5, 1.51, 0.02)
    return float(grid[np.argmax([ll_t(us, ys, t) for t in grid])])


def pav(p, h, nb=20):
    """isotonic fit of hit on p (pool adjacent violators over p-sorted blocks of nb); returns knots (x, y)"""
    o = np.argsort(p); p, h = p[o], h[o].astype(float)
    blocks = [[p[i:i + nb].mean(), h[i:i + nb].mean(), len(p[i:i + nb])] for i in range(0, len(p), nb)]
    st = []
    for b in blocks:
        st.append(b)
        while len(st) > 1 and st[-2][1] > st[-1][1]:
            a, c = st.pop(), st.pop(); n = a[2] + c[2]
            st.append([(a[0] * a[2] + c[0] * c[2]) / n, (a[1] * a[2] + c[1] * c[2]) / n, n])
    return np.array([b[0] for b in st]), np.array([b[1] for b in st])


def main():
    loc, cls = C.load('cfb'); J.attach('cfb', cls, 30)
    dec = V.SPEC['cfb'][1]; start = C.YEARS['cfb'][0] + 3
    rows = []
    for y in C.HELD['cfb']:
        Xt, yt, mt = C.build('cfb', loc, cls, range(start, y), 'list', True); Xh, yh, mh = C.build('cfb', loc, cls, [y], 'list', False)
        w = np.array([dec ** (y - 1 - m[0]) for m in mt]); m = V.fit_w(Xt, yt, KEPT, w / w.mean())
        idx = [C.COLS.index(c) for c in KEPT]; ex = {x['rid']: x.get('ex') for x in cls[y]}
        for F, c, mm in zip(Xh, yh, mh):
            e = ex.get(mm[1])
            rows.append((y, F[:, idx] @ np.array(m['b']), int(c), bool(e and e['hasP'])))
        print(y, len(yh), flush=True)
    out = {'bins': {}, 'temp': {}}
    def table(sel):
        p = np.array([np.exp(u - u.max()).max() / np.exp(u - u.max()).sum() for _, u, _, _ in sel])
        h = np.array([int(np.argmax(u) == c) for _, u, c, _ in sel]); q = np.minimum((p * 10).astype(int), 9)
        return [[round(float(p[q == i].mean()), 3), round(float(h[q == i].mean()), 3), int((q == i).sum())] for i in range(10) if (q == i).sum()]
    out['bins']['all'] = table(rows)
    out['bins']['picks'] = table([r for r in rows if r[3]])
    out['bins']['noPicks'] = table([r for r in rows if not r[3]])
    for y in sorted({r[0] for r in rows}): out['bins'][str(y)] = table([r for r in rows if r[0] == y])
    # walk-forward temperature from 2020 (two held classes before it)
    d, ts, yrs = [], {}, []
    for y in range(2020, 2027):
        prev = [r for r in rows if r[0] < y]; T = best_t([r[1] for r in prev], [r[2] for r in prev]); ts[y] = T
        for _, u, c, _ in (r for r in rows if r[0] == y):
            a = u - u.max(); z = u * T - (u * T).max()
            d.append((z[c] - math.log(np.exp(z).sum())) - (a[c] - math.log(np.exp(a).sum()))); yrs.append(y)
    d, yrs = np.array(d), np.array(yrs)
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    pos = np.mean([d[yrs == y].mean() > 0 for y in sorted(set(yrs))])
    out['temp'] = {'T': ts, 'gain': float(d.mean()), 't': float(t), 'classesPos': float(pos),
                   'byClass': {int(y): round(float(d[yrs == y].mean()), 4) for y in sorted(set(yrs))},
                   'pass': bool(d.mean() > 0 and t >= 2 and pos >= 2 / 3), 'Tall': best_t([r[1] for r in rows], [r[2] for r in rows])}
    # the scaled model's bins over the same classes
    T = out['temp']['T']
    sc = [(y, u * T[y], c, h) for y, u, c, h in rows if y >= 2020]
    out['bins']['scaled2020'] = table(sc); out['bins']['raw2020'] = table([r for r in rows if r[0] >= 2020])
    # walk-forward isotonic map of the shown lean's probability (binary: the top school is his pick), from 2020:
    # fit on the held classes before, scored by the Brier of the shown % against the plain model's
    def top(u):
        e = np.exp(u - u.max()); return float(e.max() / e.sum())
    P = np.array([top(u) for _, u, _, _ in rows]); Hh = np.array([int(np.argmax(u) == c) for _, u, c, _ in rows]); Y = np.array([r[0] for r in rows])
    dB, yb, iso = [], [], {}
    for y in range(2020, 2027):
        tr = Y < y; f = pav(P[tr], Hh[tr]); iso[y] = f
        q = np.interp(P[Y == y], f[0], f[1]); dB += list((P[Y == y] - Hh[Y == y]) ** 2 - (q - Hh[Y == y]) ** 2); yb += [y] * int((Y == y).sum())
    dB, yb = np.array(dB), np.array(yb); tb = dB.mean() / (dB.std(ddof=1) / math.sqrt(len(dB)))
    out['iso'] = {'brierGain': float(dB.mean()), 't': float(tb), 'classesPos': float(np.mean([dB[yb == y].mean() > 0 for y in range(2020, 2027)])),
                  'byClass': {y: round(float(dB[yb == y].mean()), 5) for y in range(2020, 2027)},
                  'top10pct': {y: round(float(dB[(yb == y) & (np.concatenate([P[Y == k] for k in range(2020, 2027)]) >= .8)].mean()), 4) for y in range(2020, 2027)},
                  'map': [[round(float(a), 3), round(float(b), 3)] for a, b in zip(*pav(P, Hh))]}
    out['iso']['pass'] = bool(out['iso']['brierGain'] > 0 and tb >= 2 and out['iso']['classesPos'] >= 2 / 3)
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.path.join(HERE, 'calib.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
