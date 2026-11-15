# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""M3: the 247 composite (CFBD copy) added to the live recruit index, the Nov 14 gate plus the batch's clustered t.
    python3 m3_test.py <repo root>  -> m3.json beside this file"""
import json, math, os, sys
import numpy as np

ROOT = sys.argv[1]; HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'recruits_nov14'))
import data as D
import rh as H
R, T = H.R, H.T


def clustered(d, g):
    """mean / se with se clustered by g"""
    m = d.mean(); u = {}
    for x, k in zip(d - m, g): u[k] = u.get(k, 0.0) + x
    se = math.sqrt(sum(v * v for v in u.values())) / len(d) * math.sqrt(len(u) / (len(u) - 1))
    return float(m / se), len(u)


def main():
    data = H.prep(H.dedupe(D.load()))
    tms = [t for t in (R.commit_timing(r) for r in data) if t]
    R.TM_MEAN = [round(float(np.mean([t[0] for t in tms])), 3), round(float(np.mean([t[1] for t in tms])), 3)]
    sz = R.size_norms(data)
    base = json.load(open(os.path.join(ROOT, 'data', 'cfb_recruit_retarget.json')))['use']
    cls = np.array([r['year'] for r in data]); sch = np.array([r['tid'] for r in data])
    out = {'n': len(data), 'drafted': int(sum(r['on'] for r in data)), 'base': base,
           'compPresent': round(float(np.mean([bool(r.get('comp')) for r in data])), 4),
           'compPresentDrafted': round(float(np.mean([bool(r.get('comp')) for r in data if r['on']])), 4)}
    p0, f0 = H.cv(data, base['on'], base['fv'], sz); l0, s0, m = H.losses(data, p0, f0)
    p1, _ = H.cv(data, base['on'] + ['comp'], base['fv'], sz, parts=('on',)); l1, _, _ = H.losses(data, p1, f0)
    _, f1 = H.cv(data, base['on'], base['fv'] + ['comp'], sz, parts=('fv',)); _, s1, _ = H.losses(data, p0, f1)
    d = l0 - l1
    out['on'] = H.paired(d, cls); tc, k = clustered(d, sch); out['on']['tSchool'] = round(tc, 2); out['on']['schools'] = k
    out['on']['byClass'] = {int(c): round(float(d[cls == c].mean()), 6) for c in sorted(set(cls))}
    for nm, i in (('tune 2011-15', cls <= 2015), ('held 2016-19', cls >= 2016)):
        out['on'][nm] = {'n': int(i.sum()), 'gain': round(float(d[i].mean()), 6), 't': round(float(d[i].mean() / (d[i].std() / math.sqrt(i.sum()))), 2), 'tSchool': round(clustered(d[i], sch[i])[0], 2)}
    out['on']['ll'] = {'base': round(float(l0.mean()), 5), 'cand': round(float(l1.mean()), 5)}
    df = (s0 - s1)[m]; out['fv (descriptive)'] = H.paired(df, cls[m]); out['fv (descriptive)']['tSchool'] = round(clustered(df, sch[m])[0], 2)
    e0 = p0 * np.maximum(f0, R.FLOOR) + (1 - p0) * R.FLOOR; e1 = p1 * np.maximum(f0, R.FLOOR) + (1 - p1) * R.FLOOR
    yo = np.array([r['out'] for r in data])
    dr = np.array([T.spear(e1[cls == c], yo[cls == c]) - T.spear(e0[cls == c], yo[cls == c]) for c in sorted(set(cls))])
    out['rho (comp in P only)'] = {'base': round(T.spear(e0, yo), 4), 'new': round(T.spear(e1, yo), 4), 'won': f'{int((dr > 0).sum())}/{len(dr)}',
                                   't': round(float(dr.mean() / (dr.std(ddof=1) / math.sqrt(len(dr)))), 2), 'byClass': [round(float(x), 4) for x in dr]}
    # the fitted coefficients on all rows, for the record
    X, names = R.design(data, base['on'] + ['comp'], sz); a, b = R.logit(X, np.array([r['on'] for r in data], float), R.LAM)
    out['coef'] = {n: round(float(v), 4) for n, v in zip(names, b) if n in ('compz', 'noComp', 'indz', 'noInd', 'g247', 'gEspn')}
    print(json.dumps(out, indent=1)); json.dump(out, open(os.path.join(HERE, 'm3.json'), 'w'), indent=1)


main()
