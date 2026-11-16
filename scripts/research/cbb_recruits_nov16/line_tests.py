# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family LINE: is there a step in elite outcomes by class place (L1), forward confirmation on early NBA value (L2),
and the information rule (held-out R2 of realized FV on the six-tier star by 5-star+ count a class)."""
import json
import math
import os

import numpy as np

from common import C, CP, CV, OUT, load, tstat, place

KS = [2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20]
TOP = 50


def smooth(r): lr = np.log(r); return np.c_[lr, lr ** 2]


def logit_ll(X, y, Xe, ye):
    m, s = C.std_fit(X); b = C.logit_fit((X - m) / s, y, lam=1e-3)
    def p(A): return np.clip(1 / (1 + np.exp(-(b[0] + ((A - m) / s) @ b[1:]))), 1e-6, 1 - 1e-6)
    q = p(X); pe = p(Xe)
    return float((y * np.log(q) + (1 - y) * np.log(1 - q)).sum()), -(ye * np.log(pe) + (1 - ye) * np.log(1 - pe)), b


def ols(X, y, Xe, ye):
    A = np.c_[np.ones(len(X)), X]; b = np.linalg.lstsq(A, y, rcond=None)[0]
    return -float(((y - A @ b) ** 2).sum()), (ye - np.c_[np.ones(len(Xe)), Xe] @ b) ** 2, b


def step_test(r, y, cls, folds, fit):
    d, ks, by = [], [], []
    for c in folds:
        tr = (cls != c) & np.isin(cls, folds) & (r <= TOP); te = (cls == c) & (r <= TOP)
        _, l0, _ = fit(smooth(r[tr]), y[tr], smooth(r[te]), y[te])
        best = max(KS, key=lambda k: fit(np.c_[smooth(r[tr]), r[tr] <= k], y[tr], np.c_[smooth(r[te]), r[te] <= k], y[te])[0])
        _, l1, _ = fit(np.c_[smooth(r[tr]), r[tr] <= best], y[tr], np.c_[smooth(r[te]), r[te] <= best], y[te])
        d.append(l0 - l1); ks.append(best); by.append(float((l0 - l1).mean()))
    d = np.concatenate(d); mode = max(set(ks), key=ks.count)
    near = sum(abs(KS.index(k) - KS.index(mode)) <= 1 for k in ks)
    return {'gain': round(float(d.mean()), 5), 't': round(tstat(d), 2), 'won': f'{sum(x > 0 for x in by)}/{len(by)}', 'k': ks, 'mode': mode, 'near': near,
            'byClass': [round(x, 4) for x in by]}


def main():
    H, rows, F, cls, ts = load(list(range(2009, 2021)))
    fv = ts + 20; rk = np.array([r['rk'] or 999 for r in rows]); tr = np.isin(cls, C.TRAIN)
    E = np.zeros(len(rows))
    for c in C.TRAIN:
        te = cls == c; trn = tr & ~te
        E[te] = 20 + C.Hurdle(CP, CV).fit([F[i] for i in np.where(trn)[0]], ts[trn]).ets([F[i] for i in np.where(te)[0]])
    M = C.Hurdle(CP, CV).fit([F[i] for i in np.where(tr)[0]], ts[tr]); E[~tr] = 20 + M.ets([F[i] for i in np.where(~tr)[0]])
    r = place(E, cls, rk)
    elite = (fv >= 55).astype(float); start = (fv >= 45).astype(float)
    out = {'elite': int(elite[tr].sum()), 'n': int(tr.sum())}
    out['L1'] = step_test(r, elite, cls, C.TRAIN, logit_ll)
    out['L1_fv'] = step_test(r, fv, cls, C.TRAIN, ols)
    # L2: early NBA value through class + 6 on the 2017-20 classes, step at L1's modal k
    Y = np.array([sum(max(0.0, s[2]) for s in (x.get('nba') or []) if s[0] <= x['cls'] + 6) for x in rows])
    ev = np.zeros(len(rows))
    for c in set(cls):
        i = np.where(cls == c)[0]; o = [j for j in sorted(i, key=lambda j: -Y[j]) if Y[j] > 0][:5]; ev[o] = 1
    k = out['L1']['mode']; fw = np.isin(cls, [2017, 2018, 2019, 2020]) & (r <= TOP)
    X = np.c_[smooth(r[fw]), r[fw] <= k]; m, s = C.std_fit(X); Zs = (X - m) / s; b = C.logit_fit(Zs, ev[fw], lam=1e-3)
    A = np.c_[np.ones(len(Zs)), Zs]; p = 1 / (1 + np.exp(-A @ b)); cov = np.linalg.inv(A.T @ (A * (p * (1 - p))[:, None]) + 1e-3 * np.eye(4))
    out['L2'] = {'k': k, 'n': int(fw.sum()), 'events': int(ev[fw].sum()), 'step': round(float(b[3] / s[2]), 3), 'z': round(float(b[3] / math.sqrt(cov[3, 3])), 2)}
    # the same on the training classes (descriptive)
    for nm, m_ in (('L2_2009_16', tr & (r <= TOP)),):
        X = np.c_[smooth(r[m_]), r[m_] <= k]; mm, s = C.std_fit(X); Zs = (X - mm) / s; b = C.logit_fit(Zs, ev[m_], lam=1e-3)
        A = np.c_[np.ones(len(Zs)), Zs]; p = 1 / (1 + np.exp(-A @ b)); cov = np.linalg.inv(A.T @ (A * (p * (1 - p))[:, None]) + 1e-3 * np.eye(4))
        out[nm] = {'k': k, 'n': int(m_.sum()), 'step': round(float(b[3] / s[2]), 3), 'z': round(float(b[3] / math.sqrt(cov[3, 3])), 2)}
    # ---- the information rule: held-out R2 of realized FV on the six-tier star by 5-star+ count a class
    st = json.load(open(os.path.join(C.ROOT, 'data', 'cbb_recruits.json')))['model']['stars']
    i8 = np.where(tr)[0]; s8, real, c8, r8 = E[i8], fv[i8], cls[i8], r[i8]
    band6 = np.array([C.band_of(rows[i]) for i in i8]); band = np.minimum(band6, 5)
    per_cls = len(i8) / len(C.TRAIN)
    C5 = {c: C.fit_band(s8[c8 != c], band[c8 != c]) for c in C.TRAIN}
    TC = {}
    def tiers(k_):
        if k_ in TC: return TC[k_]
        t = np.zeros(len(i8), int); TC[k_] = t
        for c in C.TRAIN:
            te = c8 == c; trn = ~te; c5 = C5[c]
            t[te] = C.cut(s8[te], c5 + [max(float(np.quantile(s8[trn], 1 - k_ / per_cls)), c5[-1] + 1e-6)])
        return t
    def sse_by_class(t):
        o = []
        for c in C.TRAIN:
            a = c8 == c; mu = {v: real[~a][t[~a] == v].mean() for v in set(t[~a])}
            pred = np.array([mu.get(v, real[~a].mean()) for v in t[a]]); o.append((float(((real[a] - pred) ** 2).sum()), float(((real[a] - real[a].mean()) ** 2).sum())))
        return np.array(o)
    S = {k_: sse_by_class(tiers(k_)) for k_ in range(1, 16)}
    S[0] = sse_by_class(np.minimum(tiers(1), 5))   # no 5-star+ tier at all
    r2 = {k_: 1 - v[:, 0].sum() / v[:, 1].sum() for k_, v in S.items()}
    best = max(range(1, 16), key=lambda k_: r2[k_])
    def gap_se(a, b):
        """class jackknife SE of R2(a) - R2(b)"""
        n = len(C.TRAIN); g = []
        for j in range(n):
            m_ = np.arange(n) != j
            g.append((1 - S[a][m_, 0].sum() / S[a][m_, 1].sum()) - (1 - S[b][m_, 0].sum() / S[b][m_, 1].sum()))
        g = np.array(g); return float(math.sqrt((n - 1) / n * ((g - g.mean()) ** 2).sum()))
    info = []
    for k_ in range(1, 16):
        t = tiers(k_); six = t == 6; five = t == 5; slot = r8 == k_
        info.append({'k': k_, 'r2': round(r2[k_], 4), 'gapToBest': round(r2[best] - r2[k_], 4), 'se': round(gap_se(best, k_), 4) if k_ != best else 0.0,
                     'n6': int(six.sum()), 'fv55_6': round(float((real[six] >= 55).mean()), 3), 'fv45_6': round(float((real[six] >= 45).mean()), 3), 'fv_6': round(float(real[six].mean()), 1),
                     'fv55_5': round(float((real[five] >= 55).mean()), 3), 'fv45_5': round(float((real[five] >= 45).mean()), 3), 'fv_5': round(float(real[five].mean()), 1), 'n5': int(five.sum()),
                     'slot55': round(float((real[slot] >= 55).mean()), 3), 'slot45': round(float((real[slot] >= 45).mean()), 3), 'slotFv': round(float(real[slot].mean()), 1),
                     'slotY': round(float(Y[i8][slot].mean()), 3)})
    out['info'] = {'best': best, 'r2None': round(r2[0], 4), 'shipped': 5, 'gap5': round(r2[best] - r2[5], 4), 'se5': round(gap_se(best, 5), 4) if best != 5 else 0.0, 'rows': info}
    # outcome by slot on the forward classes (early value only; careers still running)
    f4 = np.isin(cls, [2017, 2018, 2019, 2020])
    out['forwardSlots'] = [{'slot': f'{lo}-{hi}', 'n': int((f4 & (r >= lo) & (r <= hi)).sum()), 'Y': round(float(Y[f4 & (r >= lo) & (r <= hi)].mean()), 3),
                            'top5': round(float(ev[f4 & (r >= lo) & (r <= hi)].mean()), 3), 'fv55': round(float((fv[f4 & (r >= lo) & (r <= hi)] >= 55).mean()), 3)}
                           for lo, hi in ((1, 1), (2, 3), (4, 5), (6, 8), (9, 12), (13, 20), (21, 35), (36, 50))]
    out['trainSlots'] = [{'slot': f'{lo}-{hi}', 'n': int((tr & (r >= lo) & (r <= hi)).sum()), 'Y': round(float(Y[tr & (r >= lo) & (r <= hi)].mean()), 3),
                          'top5': round(float(ev[tr & (r >= lo) & (r <= hi)].mean()), 3), 'fv55': round(float((fv[tr & (r >= lo) & (r <= hi)] >= 55).mean()), 3),
                          'fv45': round(float((fv[tr & (r >= lo) & (r <= hi)] >= 45).mean()), 3), 'fv': round(float(fv[tr & (r >= lo) & (r <= hi)].mean()), 1)}
                         for lo, hi in ((1, 1), (2, 3), (4, 5), (6, 8), (9, 12), (13, 20), (21, 35), (36, 50))]
    print(json.dumps(out, indent=None)[:200])
    json.dump(out, open(os.path.join(OUT, 'line_tests.json'), 'w'), indent=1)
    for k_ in ('L1', 'L1_fv', 'L2', 'L2_2009_16'): print(k_, out[k_])
    print({k_: v for k_, v in out['info'].items() if k_ != 'rows'})
    for x in info: print(x)
    for x in out['trainSlots']: print(x)
    for x in out['forwardSlots']: print(x)


if __name__ == '__main__':
    main()
