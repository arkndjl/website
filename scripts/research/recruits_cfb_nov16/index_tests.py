# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family INDEX (prereg.md): I1 ordinal fit, I2 top-end curve, I3 service dispersion, each against the shipped index on
school-held-out folds of the 2011-19 history, with the 2020-21 lockbox."""
import json, math, os
import numpy as np
from scipy.optimize import minimize
from common import R, T, rh, USE, hist, lock, t_cluster, p_one, holm, by_class, HERE

rh.EXTRA['on3top'] = lambda r: {'lind': (math.log(400) - math.log(r['indRank'])) if r.get('indRank') and r['indRank'] <= 400 else 0.0,
                                'ind95': max(0.0, (r['ind'] - 95) / 5) if r.get('ind') else 0.0}
rh.EXTRA['disp'] = lambda r: {'a247': abs(r.get('g247') or 0.0), 'aEspn': abs(r.get('gEspn') or 0.0)}
BANDS = lambda r: 0 if not r['drafted'] else 1 if r['pick'] > 100 else 2 if r['pick'] > 32 else 3


def ordinal(X, k, lam):
    """proportional-odds logit, ridge on standardized columns: P(band >= j) = sig(a_j + x.b); returns (a_1, b) raw"""
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1; Z = (X - mu) / sd; n, p = Z.shape; J = int(k.max())
    def unpack(w):
        a = np.concatenate([[w[0]], w[0] - np.cumsum(np.exp(w[1:J]))]); return a, w[J:]
    def nll(w):
        a, b = unpack(w); eta = Z @ b
        cum = 1 / (1 + np.exp(-np.clip(a[None, :] + eta[:, None], -30, 30)))      # P(band >= j), j = 1..J
        up = np.c_[np.ones(n), cum]; lo = np.c_[cum, np.zeros(n)]
        pr = np.clip(up[np.arange(n), k] - lo[np.arange(n), k], 1e-12, 1)
        return -np.log(pr).sum() + 0.5 * lam * b @ b
    w0 = np.zeros(J + p); w0[0] = math.log(max(1e-6, (k >= 1).mean()) / (1 - (k >= 1).mean())); w0[1:J] = 0.0
    w = minimize(nll, w0, method='L-BFGS-B', options={'maxiter': 500}).x
    a, b = unpack(w)
    return a[0] - (b * mu / sd).sum(), b / sd


def main():
    H, cap = hist(); L = lock(cap); sz = T.size_norms(H) if hasattr(T, 'size_norms') else R.size_norms(H)
    cls = np.array([r['year'] for r in H]); sch = np.array([r['tid'] for r in H]); y = np.array([r['on'] for r in H], float)
    rfv = np.array([r['rfv'] for r in H]); fo = R.folds(H); out = {}
    p0, f0 = rh.cv(H, USE['on'], USE['fv'], sz); ll0, _, _ = rh.losses(H, p0, f0)
    e0 = p0 * np.maximum(f0, R.FLOOR) + (1 - p0) * R.FLOOR
    print('base ll', ll0.mean(), 'rho', T.spear(e0, rfv))
    # lockbox: fit on all of H
    Xh = rh.X_of(H, USE['on'], sz); a, b = R.logit(Xh, y, R.LAM); yl = np.array([r['on'] for r in L], float); lc = np.array([r['year'] for r in L])
    capl = np.array([r['capps'] for r in L]); pl0 = R.sig(a + rh.X_of(L, USE['on'], sz) @ b)
    llf = lambda p, yy: -(yy * np.log(np.clip(p, 1e-6, 1)) + (1 - yy) * np.log(np.clip(1 - p, 1e-6, 1)))
    for nm in ('on3top', 'disp'):
        u = USE['on'] + [nm]; p1, _ = rh.cv(H, u, USE['fv'], sz, parts=('on',)); d = ll0 - llf(p1, y)
        a1, b1 = R.logit(rh.X_of(H, u, sz), y, R.LAM); pl1 = R.sig(a1 + rh.X_of(L, u, sz) @ b1); dl = llf(pl0, yl) - llf(pl1, yl)
        bc = by_class(d, cls); t = t_cluster(d, sch)
        out[nm] = {'gain': float(d.mean()), 'tSchool': round(t, 2), 'p': p_one(t), 'won': f'{sum(v > 0 for v in bc.values())}/9', 'byClass': {c: round(v, 6) for c, v in bc.items()},
                   'lock2020': float(dl[lc == 2020].mean()), 'lock2021': float(dl[lc == 2021].mean()), 'coef': dict(zip(list(rh.EXTRA[nm](H[0])), [round(float(x), 4) for x in b1[-2:]]))}
        print(nm, out[nm], flush=True)
    # I1: ordinal coefficients for the P part
    k = np.array([BANDS(r) for r in H]); p1 = np.zeros(len(H))
    for f in range(5):
        tr = fo != f; a1, b1 = ordinal(Xh[tr], k[tr], R.LAM); p1[~tr] = R.sig(a1 + Xh[~tr] @ b1)
    e1 = p1 * np.maximum(f0, R.FLOOR) + (1 - p1) * R.FLOOR
    d = (rfv - e0) ** 2 - (rfv - e1) ** 2; t = t_cluster(d, sch); bc = by_class(d, cls); dll = ll0 - llf(p1, y)
    rc = [T.spear(e1[cls == c], rfv[cls == c]) - T.spear(e0[cls == c], rfv[cls == c]) for c in sorted(set(cls))]
    ao, bo = ordinal(Xh, k, R.LAM); pl1 = R.sig(ao + rh.X_of(L, USE['on'], sz) @ bo)
    lk = {int(c): [round(T.spear(pl0[lc == c], capl[lc == c]), 4), round(T.spear(pl1[lc == c], capl[lc == c]), 4)] for c in (2020, 2021)}
    out['ordinal'] = {'gain': float(d.mean()), 'tSchool': round(t, 2), 'p': p_one(t), 'won': f'{sum(v > 0 for v in bc.values())}/9', 'llGain': float(dll.mean()), 'llT': round(t_cluster(dll, sch), 2),
                      'rho': [round(T.spear(e0, rfv), 4), round(T.spear(e1, rfv), 4)], 'rhoWon': f'{sum(x > 0 for x in rc)}/9', 'lockRhoCapital': lk,
                      'lock2020': lk[2020][1] - lk[2020][0]}
    print('ordinal', out['ordinal'])
    hp = holm({n: out[n]['p'] for n in out})
    for n in out: out[n]['holm'] = hp[n]; out[n]['pass'] = bool(hp[n] and int(out[n]['won'].split('/')[0]) >= 6 and out[n]['lock2020'] >= 0)
    # descriptive: the shipped index against the services alone on the lockbox
    desc = {}
    for c in (2020, 2021):
        i = lc == c; rows = [r for r, m in zip(L, i) if m]
        sc = {'index': pl0[i], 'espn': np.array([r['grade'] if r['grade'] >= 60 else 50 for r in rows], float), 'industry': np.array([r.get('ind') or 0 for r in rows], float),
              'comp247': np.array([r.get('comp') or 0 for r in rows], float)}
        desc[c] = {'n': int(i.sum()), 'drafted': int(yl[i].sum()), **{nm: {'rhoCapital': round(T.spear(s, capl[i]), 4), 'auc': round(R.auc(s + 1e-9 * np.arange(len(s)), yl[i]), 4),
                   'top3draft': round(float(yl[i][s >= np.quantile(s, .97)].mean()), 3)} for nm, s in sc.items()}}
    out['lockDescriptive'] = desc; print(json.dumps(desc, indent=1))
    json.dump(out, open(os.path.join(HERE, 'index_tests.json'), 'w'), indent=1)
    print({n: (out[n].get('pass'), out[n].get('tSchool')) for n in ('ordinal', 'on3top', 'disp')})


if __name__ == '__main__':
    main()
