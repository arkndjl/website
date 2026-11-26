# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Round 3: the four classes on a roster against that season's rating (prereg.md). python3 stock.py -> stock.json"""
import json, math, os
import numpy as np
import tests as T

CFG = {'cfb': {'seasons': range(2013, 2026), 'cls': (0, -1, -2, -3), 'pre': (-4, -5), 'base': (-6, -7, -8)},
       'cbb': {'seasons': range(2016, 2027), 'cls': (-1, -2, -3, -4), 'pre': (-4, -5), 'base': (-6, -7, -8)}}


def rows_of(sp, S, C, key='z'):
    cfg = CFG[sp]; rows = []
    for s in cfg['seasons']:
        for t, v in S.get(s, {}).items():
            y = v.get(key); pre = [(S.get(s + k) or {}).get(t, {}).get('z') for k in cfg['pre']]
            b = [x for x in ((S.get(s + k) or {}).get(t, {}).get('z') for k in cfg['base']) if x is not None]
            if y is None or any(x is None for x in pre) or not b: continue
            cl = [sorted((p[2] for p in C.get(s + k, {}).get(t, [])), reverse=True) for k in cfg['cls']]
            if sp == 'cbb' and not any(cl): continue
            pre = pre + [float(np.mean(b))] + ([float(bool(((S.get(s + cfg['pre'][0]) or {}).get(t) or {}).get('p4')))] if sp == 'cfb' else [])
            rows.append({'t': t, 'c': s, 'y': float(y), 'pre': pre, 'prev': [], 'cl': cl, 'pts': None})
    return rows


def lift(f):
    """a one-class form -> the roster's: applied to each class, summed"""
    def g(r):
        return list(np.sum([f({'pts': c}) for c in r['cl']], axis=0))
    return g


def family(sp):
    cfg = T.CFG[sp]
    return {'split': ([lift(T.f_split(k)) for k in cfg['k']], cfg['k']), 'decay': ([lift(T.f_decay(d)) for d in T.DEC], T.DEC),
            'cap': ([lift(T.f_cap(n)) for n in cfg['cap']], cfg['cap']), 'star premium': ([lift(T.f_pow(p)) for p in T.POW], T.POW),
            'power x decay': ([lift(T.f_pd(p, d)) for p, d in T.PD], [f'{p}/{d}' for p, d in T.PD])}


def weights(rows, k):
    y = np.array([r['y'] for r in rows]); X = T.X_of(rows, lift(T.f_split(k))); b = T.ols(X, y); e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X); u = {}
    for x, ei, r in zip(X, e, rows): u[r['t']] = u.get(r['t'], 0) + x * ei
    V = XtXi @ sum(np.outer(v, v) for v in u.values()) @ XtXi; i, j = X.shape[1] - 2, X.shape[1] - 1
    top, dep = X[:, i], X[:, j]
    Z = T.X_of(rows, lambda r: []); res = lambda v: v - Z @ T.ols(Z, v)
    return {'k': k, 'top': [round(float(b[i]), 5), round(float(math.sqrt(V[i, i])), 5)], 'depth': [round(float(b[j]), 5), round(float(math.sqrt(V[j, j])), 5)],
            'ratio': round(float(b[i] / b[j]), 2) if b[j] > 0 and b[i] > 0 else None, 't_diff': round(float((b[i] - b[j]) / math.sqrt(V[i, i] + V[j, j] - 2 * V[i, j])), 2),
            'sd': [round(float(top.std()), 2), round(float(dep.std()), 2)], 'per_sd': [round(float(b[i] * top.std()), 4), round(float(b[j] * dep.std()), 4)],
            'r': [round(float(np.corrcoef(top, y)[0, 1]), 3), round(float(np.corrcoef(dep, y)[0, 1]), 3)], 'r_top_depth': round(float(np.corrcoef(top, dep)[0, 1]), 3),
            'partial': [round(float(np.corrcoef(res(top), res(y))[0, 1]), 3), round(float(np.corrcoef(res(dep), res(y))[0, 1]), 3)],
            'share_top': round(float(top.sum() / (top.sum() + dep.sum())), 3)}


def main():
    out = {}
    for sp in ('cfb', 'cbb'):
        P, S, C = T.load(sp); rows = rows_of(sp, S, C); fam = family(sp); plain = lift(T.f_plain)
        res = T.compare(rows, fam, base=plain)
        none = T.compare(rows, {'plain': ([plain], ['-'])}, base=lambda r: [])
        fw = {}
        tr = [r for r in rows if r['c'] <= 2019]; te = [r for r in rows if r['c'] > 2019]
        ytr = np.array([r['y'] for r in tr]); yte = np.array([r['y'] for r in te]); g = [r['t'] for r in te]
        eb = (yte - T.X_of(te, plain) @ T.ols(T.X_of(tr, plain), ytr)) ** 2
        for name, (forms, labels) in fam.items():
            _, pick = T.loco(tr, forms); ctr = np.array([r['c'] for r in tr]); best, j = None, 0
            for i, f in enumerate(forms):
                X = T.X_of(tr, f); sse = sum(float(((ytr[ctr == h] - X[ctr == h] @ T.ols(X[ctr != h], ytr[ctr != h])) ** 2).sum()) for h in sorted(set(ctr)))
                if best is None or sse < best: best, j = sse, i
            e = (yte - T.X_of(te, forms[j]) @ T.ols(T.X_of(tr, forms[j]), ytr)) ** 2
            fw[name] = {'pick': labels[j], 'd': round(float((eb - e).mean()), 5), 't': round(T.t_cluster(eb - e, g), 2)}
        for k, v in res['forms'].items(): v['pass'] = bool(v['pass'] and fw[k]['d'] > 0); v['pick'] = sorted(set(map(str, v['pick'].values())))
        b = T.ols(T.X_of(rows, plain), np.array([r['y'] for r in rows]))
        wr = rows_of(sp, S, C, key='wp'); wres = T.compare(wr, fam, base=plain) if len(wr) > 500 else None
        out[sp] = {'n': res['n'], 'seasons': res['classes'], 'base': res['base_rmse'], 'forms': res['forms'], 'forward': fw,
                   'plain': {'perPoint': round(float(b[-1]), 5), 't': none['forms']['plain']['t'], 'up': none['forms']['plain']['classes_up'], 'noneRmse': none['base_rmse']},
                   'weights': {str(k): weights(rows, k) for k in T.CFG[sp]['k']},
                   'wins': {'n': len(wr), 'weights': weights(wr, T.CFG[sp]['live_k']), 'forms': {k: {'t': v['t'], 'up': v['classes_up']} for k, v in wres['forms'].items()} if wres else None},
                   'nil': {'n': sum(r['c'] >= 2022 for r in rows), 'weights': weights([r for r in rows if r['c'] >= 2022], T.CFG[sp]['live_k'])},
                   'pre': {'n': sum(r['c'] < 2022 for r in rows), 'weights': weights([r for r in rows if r['c'] < 2022], T.CFG[sp]['live_k'])}}
        o = out[sp]; print(sp, 'n', o['n'], 'seasons', o['seasons'], 'base', o['base'], 'plain', o['plain'])
        for k, v in o['forms'].items(): print(f"  {k:14s} rmse {v['rmse']} t {v['t']:+.2f} up {v['classes_up']} pass {v['pass']} pick {v['pick']} fwd {fw[k]}")
        for k, w in o['weights'].items(): print('  w', k, w['top'], w['depth'], 'ratio', w['ratio'], 't_diff', w['t_diff'], 'per sd', w['per_sd'], 'r', w['r'], 'partial', w['partial'], 'share', w['share_top'])
        print('  wins', o['wins']['weights']['top'], o['wins']['weights']['depth'], o['wins']['weights']['t_diff'], o['wins']['forms'])
        print('  NIL', o['nil']['n'], o['nil']['weights']['top'], o['nil']['weights']['depth'], o['nil']['weights']['t_diff'], ' before', o['pre']['weights']['top'], o['pre']['weights']['depth'], o['pre']['weights']['t_diff'])
    json.dump(out, open(os.path.join(T.HERE, 'stock.json'), 'w'), indent=1)


if __name__ == '__main__': main()
