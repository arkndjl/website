# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family XFV (prereg.md): V1 P(on the board) on the recruit blocks directly (FV(on) keeps the NFL index), V2 position
by year, on the live board fit (classes 2023-26, school folds)."""
import json, math, os, pickle
import numpy as np
from common import R, T, rh, USE, hist, t_cluster, p_one, holm, HERE

FREE = ['grade', 'hinge', 'rank', 'pos', 'year', 'grade_year', 'pos_year1', 'size', 'level', 'elo', 'on3', 'svc']
_b0 = R.blocks0


def blocks0(r, sz):
    b = _b0(r, sz); b['pos_k'] = {f'pk_{p}': (1.0 if r['g'] == p else 0.0) * (r['k'] - 1) for p in R.GROUPS if p != 'WR'}; return b


R.blocks0 = blocks0


def main():
    season = int(json.load(open(R.ALL))['asof'][:4])
    f = os.path.join(R.CACHE, 'live_nov16.pkl')
    if os.path.exists(f): data = pickle.load(open(f, 'rb'))
    else:
        data, how, prog = R.dataset(season, range(season - R.KMAX + 1, season + 1)); data = [r for r in data if r['k'] <= R.KMAX]; pickle.dump(data, open(f, 'wb'))
    for r in data: r.pop('_bc', None)
    sz = R.size_norms(data); sch = np.array([r['tid'] for r in data]); y = np.array([r['on'] for r in data], float); m = y == 1
    fv = np.array([r['fv'] or 0 for r in data], float); print('rows', len(data), 'on', int(y.sum()))
    IDX = list(R.IDX_BLOCKS)
    llf = lambda p: -(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1)))
    def run(uo, uf):
        for r in data: r.pop('_bc', None)
        return R.cv(data, uo, uf, sz, R.LAM, R.LAM)
    p0, f0 = run(IDX, IDX); p1, f1 = run(FREE, IDX)
    out = {'base': {k: round(v, 4) for k, v in R.score(data, p0, f0).items()}, 'V1': {'score': {k: round(v, 4) for k, v in R.score(data, p1, f1).items()}}}
    d = llf(p0) - llf(p1); t = t_cluster(d, sch); out['V1'].update({'gain': float(d.mean()), 'tSchool': round(t, 2), 'p': p_one(t), 'tiers': R.tiers(data, p1, f1), 'tiersBase': R.tiers(data, p0, f0)})
    print('V1', out['V1']['gain'], t, flush=True)
    v1 = t > 0 and p_one(t) <= .05 / 3
    bo = FREE if v1 else IDX
    p2, _ = run(bo + ['pos_k'], IDX); _, f2 = run(bo, IDX + ['pos_k']); pb, fb = (p1, f1) if v1 else (p0, f0)
    d = llf(pb) - llf(p2); t = t_cluster(d, sch); out['V2 on'] = {'gain': float(d.mean()), 'tSchool': round(t, 2), 'p': p_one(t)}
    d = ((fv - fb) ** 2 - (fv - f2) ** 2)[m]; t = t_cluster(d, sch[m]); out['V2 fv'] = {'gain': float(d.mean()), 'tSchool': round(t, 2), 'p': p_one(t)}
    hp = holm({k: out[k]['p'] for k in ('V1', 'V2 on', 'V2 fv')})
    for k in hp: out[k]['holm'] = hp[k]; out[k]['pass'] = bool(hp[k] and out[k]['gain'] > 0)
    # guard: the year-3 xFV's Spearman with the NFL outcome on H, the index refit without each fold's schools
    H, cap = hist(); szh = R.size_norms(H); T.as_hurdle(H); live = json.load(open(R.OUT)); cls = np.array([r['year'] for r in H]); rfv = np.array([r['rfv'] for r in H])
    def model(uo, uf):
        for r in data: r.pop('_bc', None); r['_dev'] = 0.0
        return R.final(data, {'on': uo, 'fv': uf}, sz, 20)
    keepI = R.INDEX
    def stage(mod):
        fo = R.folds(H); s = np.zeros(len(H))
        for f_ in range(5):
            R.INDEX = T.index_fit(H, USE, szh, [r for r, x in zip(H, fo) if x != f_])
            for i in np.where(fo == f_)[0]: s[i] = R.predict(mod, {**{k: v for k, v in H[i].items() if k not in ('_bc', '_b0')}, 'k': 3, '_dev': 0.0}, live['sizeNorms'])[2]
        return s
    uo = (FREE if v1 else IDX) + (['pos_k'] if out['V2 on']['pass'] else []); uf = IDX + (['pos_k'] if out['V2 fv']['pass'] else [])
    R.INDEX = keepI; mb = model(IDX, IDX); mc = model(uo, uf)
    sb = stage(mb); sc = stage(mc); R.INDEX = keepI
    C = sorted(set(cls)); dd = np.array([T.spear(sc[cls == c], rfv[cls == c]) - T.spear(sb[cls == c], rfv[cls == c]) for c in C])
    out['guard'] = {'use': {'on': uo, 'fv': uf}, 'rho': [round(T.spear(sb, rfv), 4), round(T.spear(sc, rfv), 4)], 'tClass': round(float(dd.mean() / (dd.std(ddof=1) / 3)), 2), 'won': f'{int((dd > 0).sum())}/9',
                    'ok': bool(dd.mean() / (dd.std(ddof=1) / 3) > -2)}
    for r in data: r.pop('_bc', None)
    pc, fc = R.cv(data, uo, uf, sz, R.LAM, R.LAM); out['final'] = {'score': {k: round(v, 4) for k, v in R.score(data, pc, fc).items()}, 'tiers': R.tiers(data, pc, fc), 'byYear': R.per_year(data, pc, fc)}
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.path.join(HERE, 'xfv_tests.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
