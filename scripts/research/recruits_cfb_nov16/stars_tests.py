# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family STARS (prereg.md): S0 stars on the NFL index, S2 absolute 5-star+ line, S3 outcome-fit cuts, S1 the line."""
import json, math, os
import numpy as np
from common import R, T, rh, USE, hist, lock, p_one, holm, HERE

BANDS = [(1, 3), (4, 6), (7, 10), (11, 15), (16, 20), (21, 30), (31, 40)]


def shares():
    t = {x['stars']: x['share'] for x in json.load(open(T.BEFORE))['stars']['schemes']['band']['tiers']}
    return list(np.cumsum([t[1], t[2], t[3], t[4]]))


def tiers(s, cls, q, plus=6, thr=None):
    """stars within class at cumulative shares q; 5-star+ = top `plus` a class, or score >= thr"""
    st = np.zeros(len(s), int)
    for c in set(cls):
        i = np.where(cls == c)[0]; st[i] = R.cut(s[i], np.quantile(s[i], q))
        if thr is None: st[i[np.argsort(-s[i], kind='stable')[:plus]]] = 6
    if thr is not None: st[s >= thr] = 6
    return st


def tier_r2(st_fn, y, cls):
    """per held class: 1 - SSE(tier means of the other classes) / SST(the other classes' mean)"""
    out = {}
    for c in sorted(set(cls)):
        te = cls == c; st = st_fn(c); mu = {t: y[~te][st[~te] == t].mean() for t in set(st[~te])}; m0 = y[~te].mean()
        pred = np.array([mu.get(t, m0) for t in st[te]]); out[int(c)] = float(1 - ((y[te] - pred) ** 2).sum() / ((y[te] - m0) ** 2).sum())
    return out


def tclass(d):
    d = np.asarray(list(d), float); return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), int((d > 0).sum())


def rank_in_class(s, cls):
    rk = np.zeros(len(s), int)
    for c in set(cls):
        i = np.where(cls == c)[0]; rk[i[np.argsort(-s[i], kind='stable')]] = np.arange(1, len(i) + 1)
    return rk


def fit_cuts(s, y, cls, q0):
    """cumulative shares maximising in-sample tier R2 (5 tiers + the top 6), coordinate search"""
    grid = np.r_[np.linspace(.05, .9, 35), np.linspace(.91, .995, 35)]
    def val(q):
        st = tiers(s, cls, q); mu = {t: y[st == t].mean() for t in set(st)}
        return 1 - ((y - np.array([mu[t] for t in st])) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    q = list(q0); best = val(q)
    for _ in range(3):
        for i in range(4):
            lo = q[i - 1] if i else 0; hi = q[i + 1] if i < 3 else 1
            for g in grid:
                if not lo + .005 < g < hi - .005: continue
                t = q[:i] + [float(g)] + q[i + 1:]; v = val(t)
                if v > best + 1e-9: best, q = v, t
    return q


def line_table(s, cls, data, st5):
    rk = rank_in_class(s, cls); d = np.array([r['drafted'] for r in data]); pk = np.array([r['pick'] or 999 for r in data])
    av = np.array([r.get('avps', 0.0) for r in data]); y = np.array([r.get('rfv', 20.0) for r in data])
    row = lambda i: {'n': int(i.sum()), 'drafted': round(float(d[i].mean()), 3), 'top32': round(float((pk[i] <= 32).mean()), 3), 'top64': round(float((pk[i] <= 64).mean()), 3),
                     'starter': round(float((av[i] >= 3).mean()), 3), 'rfv': round(float(y[i].mean()), 1)}
    out = {'bands': {f'{a}-{b}': row((rk >= a) & (rk <= b)) for a, b in BANDS}, 'top': {n: row(rk <= n) for n in (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40)},
           'plain5': row((st5 >= 5) & (rk > 6)), 'star4': row(st5 == 4)}
    return out, rk, pk


def n_star(rk, pk, st5, idx=None, rng=None, sch=None):
    """largest N whose every band up to it has top-64 >= 50% and beats the plain 5-star tier (rest of it) one-sided .05"""
    if idx is None: idx = np.arange(len(rk))
    rk, pk, st5 = rk[idx], pk[idx], st5[idx]; hit = pk <= 64; n = 0
    for a, b in BANDS:
        i = (rk >= a) & (rk <= b); j = (st5 >= 5) & (rk > 6) & ~i
        if not i.any() or not j.any(): break
        p1, p2 = hit[i].mean(), hit[j].mean(); se = math.sqrt(p1 * (1 - p1) / i.sum() + p2 * (1 - p2) / j.sum()) or 1e-9
        if p1 >= .5 and p_one((p1 - p2) / se) <= .05: n = b
        else: break
    return n


def main():
    H, cap = hist(); L = lock(cap); sz = R.size_norms(H); q = shares()
    cls = np.array([r['year'] for r in H]); y = np.array([r['rfv'] for r in H]); sch = np.array([r['tid'] for r in H])
    p0, f0 = rh.cv(H, USE['on'], USE['fv'], sz); s_idx = p0 * np.maximum(f0, R.FLOOR) + (1 - p0) * R.FLOOR
    live = json.load(open(R.OUT)); T.as_hurdle(H); s_ship = T.stage_b(H, USE, sz, live)
    for r in H: r.pop('_bc', None)
    out = {'shares': [round(x, 4) for x in q]}
    C = sorted(set(cls))
    # S0
    st = {'shipped': tiers(s_ship, cls, q), 'index': tiers(s_idx, cls, q)}
    rho = {k: {int(c): T.spear(v[cls == c], y[cls == c]) for c in C} for k, v in st.items()}
    t, won = tclass(rho['index'][c] - rho['shipped'][c] for c in C)
    # lockbox: index fit on all of H; shipped = live model at year 3
    ix = T.index_fit(H, USE, sz); lc = np.array([r['year'] for r in L]); yl = np.array([r['drafted'] for r in L], float)
    Xl = rh.X_of(L, USE['on'], sz); pl = R.sig(ix['on']['b0'] + Xl @ np.array(ix['on']['coef'])); fl = ix['fv']['b0'] + rh.X_of(L, USE['fv'], sz) @ np.array(ix['fv']['coef'])
    l_idx = pl * np.maximum(fl, R.FLOOR) + (1 - pl) * R.FLOOR
    keep = R.INDEX; R.INDEX = ix
    l_ship = np.array([R.predict(live['model'], {**{k: v for k, v in r.items() if k not in ('_bc', '_b0')}, 'k': 3, '_dev': 0.0}, live['sizeNorms'])[2] for r in L]); R.INDEX = keep
    top3 = lambda s, i: float(yl[i][s[i] >= np.quantile(s[i], .97)].mean())
    lk = {int(c): {'index': round(top3(l_idx, lc == c), 3), 'shipped': round(top3(l_ship, lc == c), 3)} for c in (2020, 2021)}
    capl = np.array([r['capps'] for r in L])
    lkr = {int(c): {'index': round(T.spear(tiers(l_idx[lc == c], lc[lc == c], q), capl[lc == c]), 4), 'shipped': round(T.spear(tiers(l_ship[lc == c], lc[lc == c], q), capl[lc == c]), 4)} for c in (2020, 2021)}
    out['S0'] = {'rhoByClass': {k: {c: round(v, 4) for c, v in d.items()} for k, d in rho.items()}, 'mean': [round(float(np.mean(list(rho[k].values()))), 4) for k in ('shipped', 'index')],
                 't': round(t, 2), 'p': p_one(t), 'won': f'{won}/9', 'lockTop3Draft': lk, 'lockStarRhoCapital': lkr,
                 'lockOk': bool(lk[2020]['index'] >= lk[2020]['shipped'])}
    print('S0', json.dumps(out['S0']), flush=True)
    sc_name = 'index' if (out['S0']['p'] <= .05 / 3 and won >= 7 and out['S0']['lockOk']) else 'shipped'
    s = s_idx if sc_name == 'index' else s_ship; ls = l_idx if sc_name == 'index' else l_ship
    out['scoreUsed'] = sc_name
    # S2: threshold from the other classes at the same average count vs top 6
    def thr_fn(c):
        o = cls != c; th = np.sort(s[o])[::-1][6 * len(set(cls[o])) - 1]; return tiers(s, cls, q, thr=th)
    a = tier_r2(lambda c: tiers(s, cls, q), y, cls); b = tier_r2(thr_fn, y, cls); t, won = tclass(b[c] - a[c] for c in C)
    nthr = {int(c): int((thr_fn(c)[cls == c] == 6).sum()) for c in C}
    out['S2'] = {'r2Count': round(float(np.mean(list(a.values()))), 5), 'r2Thr': round(float(np.mean(list(b.values()))), 5), 't': round(t, 2), 'p': p_one(t), 'won': f'{won}/9', 'nByClass': nthr}
    print('S2', out['S2'], flush=True)
    # S3: outcome-fit shares from the other eight classes
    fitq = {c: fit_cuts(s[cls != c], y[cls != c], cls[cls != c], q) for c in C}
    b = tier_r2(lambda c: tiers(s, cls, fitq[c]), y, cls); t, won = tclass(b[c] - a[c] for c in C)
    qall = fit_cuts(s, y, cls, q)
    out['S3'] = {'r2Live': round(float(np.mean(list(a.values()))), 5), 'r2Fit': round(float(np.mean(list(b.values()))), 5), 't': round(t, 2), 'p': p_one(t), 'won': f'{won}/9',
                 'sharesFit': [round(x, 4) for x in qall], 'byClass': {int(c): [round(a[c], 4), round(b[c], 4)] for c in C}}
    print('S3', out['S3'], flush=True)
    hp = holm({k: out[k]['p'] for k in ('S0', 'S2', 'S3')})
    for k in hp: out[k]['holm'] = hp[k]; out[k]['pass'] = bool(hp[k] and int(out[k]['won'].split('/')[0]) >= 7 and out[k].get('lockOk', True))
    # S1
    st5 = tiers(s, cls, q); tab, rk, pk = line_table(s, cls, H, st5)
    ns = n_star(rk, pk, st5); rng = np.random.default_rng(11); bs = []
    ci = {int(c): np.where(cls == c)[0] for c in C}
    for _ in range(2000):
        idx = np.concatenate([ci[c] for c in rng.choice(C, len(C))]); bs.append(n_star(rk, pk, st5, idx))
    r2n = {}
    for n in (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40):
        r2n[n] = round(float(np.mean(list(tier_r2(lambda c, n=n: tiers(s, cls, q, plus=n), y, cls).values()))), 5)
    lt5 = tiers(ls, lc, q); ltab, _, _ = line_table(ls, lc, [{**r, 'avps': 0.0, 'rfv': 20.0} for r in L], lt5)
    for part in ('bands', 'top'):
        for v in ltab[part].values(): v.pop('starter'); v.pop('rfv')
    out['S1'] = {'table': tab, 'tierR2ByN': r2n, 'nStar': ns, 'boot90': [int(np.quantile(bs, .05)), int(np.quantile(bs, .95))], 'bootDist': {int(k): int(v) for k, v in zip(*np.unique(bs, return_counts=True))},
                 'moves': bool(not (np.quantile(bs, .05) <= 6 <= np.quantile(bs, .95))), 'lockbox': ltab}
    print(json.dumps(out['S1'], indent=0))
    json.dump(out, open(os.path.join(HERE, 'stars_tests.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
