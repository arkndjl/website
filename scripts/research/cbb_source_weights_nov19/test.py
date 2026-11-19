#!/usr/bin/env python3
"""CBB recruit consensus: per-source accuracy weights vs equal weight, walk-forward by class (see README.md)."""
import gzip, itertools, json, math, os
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')
H = json.load(gzip.open(os.path.join(ROOT, 'scripts/data/cbb_recruit_hist.json.gz')))['recruits']
SRC = ['247', 'espn', 'on3']
K, STEP, CAP = 4, 0.05, 400
ERA = lambda c: 0 if c <= 2020 else 1


def rankdata(a):
    a = np.asarray(a, float); o = np.argsort(a, kind='mergesort'); r = np.empty(len(a)); s = a[o]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and s[j + 1] == s[i]: j += 1
        r[o[i:j + 1]] = (i + j) / 2 + 1; i = j + 1
    return r


def spear(x, y): return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def colval(r):
    v = []
    for y in (r['cls'] + 1, r['cls'] + 2):
        s = (r.get('col') or {}).get(str(y))
        v.append(s[1] / 100 * max(0.0, s[2] + 3) if s else 0.0)
    return max(v)


cls_rows = {}
for c in range(2009, 2026):
    rs = [r for r in H if r['cls'] == c]
    depth = {s: max((r['svc'][s] for r in rs if s in r['svc']), default=0) for s in SRC}
    srcs = [s for s in SRC if depth[s] >= 50]
    L = np.array([[-math.log(min(r['svc'][s], CAP)) if s in r['svc'] else -math.log(min(1.25 * depth[s], CAP))
                   for s in srcs] for r in rs])
    cls_rows[c] = {'srcs': srcs, 'L': L, 'rk': np.array([-math.log(min(r['rk'] or CAP, CAP)) for r in rs]),
                   'nba': np.array([r.get('rfv') or 20 for r in rs], float), 'col': np.array([colval(r) for r in rs])}


def simplex(k):
    n = round(1 / STEP)
    for p in itertools.product(range(n + 1), repeat=k - 1):
        if sum(p) <= n: yield np.array(list(p) + [n - sum(p)]) / n


def fit(train, tgt):
    k = len(cls_rows[train[0]]['srcs'])
    best = max(simplex(k), key=lambda w: np.mean([spear(cls_rows[c]['L'] @ w, cls_rows[c][tgt]) for c in train]))
    return best


def run(tgt, tests, k_shr=K):
    out = []
    for c in tests:
        train = [t for t in cls_rows if t < c and ERA(t) == ERA(c)]
        d = cls_rows[c]; k = len(d['srcs']); eq = np.ones(k) / k
        wf = fit(train, tgt); w = eq + len(train) / (len(train) + k_shr) * (wf - eq) if k_shr is not None else eq
        out.append({'cls': c, 'srcs': d['srcs'], 'w_fit': wf.round(2).tolist(), 'w': w.round(3).tolist(),
                    'eq': spear(d['L'] @ eq, d[tgt]), 'wt': spear(d['L'] @ w, d[tgt]), 'raw': spear(d['L'] @ wf, d[tgt]),
                    'on3ind': spear(d['rk'], d[tgt])})
    return out


def summ(name, res, key='wt'):
    dlt = np.array([r[key] - r['eq'] for r in res]); n = len(dlt)
    t = dlt.mean() / (dlt.std(ddof=1) / math.sqrt(n)) if n > 1 and dlt.std() > 0 else float('nan')
    return {'test': name, 'n': n, 'eq': round(float(np.mean([r['eq'] for r in res])), 4),
            key: round(float(np.mean([r[key] for r in res])), 4), 'delta': round(float(dlt.mean()), 4),
            't': round(float(t), 2), 'wins': int((dlt > 0).sum())}


if __name__ == '__main__':
    R = {}
    R['nba'] = run('nba', range(2011, 2019))
    R['col_e1'] = run('col', range(2011, 2021))
    R['col_e2'] = run('col', range(2023, 2026))
    S = []
    for nm, res in R.items():
        S.append(summ(nm + ' shrunk k4', res)); S.append(summ(nm + ' unshrunk', res, 'raw'))
        S.append(summ(nm + ' On3 industry rk', res, 'on3ind'))
    # does a class's own best weight repeat? each class's in-sample best ESPN share, era 1, lag-1 correlation
    own = {t: {c: fit([c], t)[1] for c in range(2009, 2021 if t == 'col' else 2019)} for t in ('nba', 'col')}
    rep = {t: round(float(np.corrcoef([v[c] for c in sorted(v)][:-1], [v[c] for c in sorted(v)][1:])[0, 1]), 3)
           for t, v in own.items()}
    own3 = {c: fit([c], 'col').round(2).tolist() for c in range(2021, 2026)}
    res = {'summary': S, 'by_class': R, 'own_best_espn_share_e1': own, 'lag1_r': rep, 'own_best_e2_247_espn_on3': own3}
    json.dump(res, open(os.path.join(os.path.dirname(__file__), 'results.json'), 'w'), indent=1)
    for s in S: print(s)
    print('lag-1 r of own best ESPN weight:', rep)
    print('own best ESPN share', own)
    print('own best e2', own3)
    for nm in R: print(nm, [(r['cls'], r['w']) for r in R[nm]])
