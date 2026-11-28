# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""5-star+ weight in the class score (prereg.md). Needs the Nov 26 panels (class_score_nov26/cfb_build.py, cbb_build.py).
python3 test.py -> result.json"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'class_score_nov26'))
import tests as T  # noqa: E402
import stock as ST  # noqa: E402

KS = {'cfb': [2, 4, 6, 8, 12], 'cbb': [2, 3, 5, 8]}
LIVE_K = {'cfb': 4, 'cbb': 5}


def ranked(sp, C):
    """class -> team -> [(points, national rank in the class)]"""
    out = {}
    for c, by in C.items():
        allp = [(t, p) for t, v in by.items() for p in v]
        allp.sort(key=lambda x: -x[1][1] if sp == 'cfb' else x[1][1])
        out[c] = {}
        for i, (t, p) in enumerate(allp): out[c].setdefault(t, []).append((p[2], (i + 1) if sp == 'cfb' else p[1]))
    return out


def f_plain(r): return [sum(p for cl in r['ck'] for p, _ in cl)]
def f_mult(k): return lambda r: [sum(p for cl in r['ck'] for p, n in cl if n <= k), sum(p for cl in r['ck'] for p, n in cl if n > k)]
def f_count(k): return lambda r: [sum(p for cl in r['ck'] for p, _ in cl), float(sum(1 for cl in r['ck'] for _, n in cl if n <= k))]


def fam(sp):
    return {'multiplier': ([f_mult(k) for k in KS[sp]], KS[sp]), 'count bonus': ([f_count(k) for k in KS[sp]], KS[sp])}


def cl_ols(rows, form):
    y = np.array([r['y'] for r in rows]); X = T.X_of(rows, form); b = T.ols(X, y); e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X); u = {}
    for x, ei, r in zip(X, e, rows): u[r['t']] = u.get(r['t'], 0) + x * ei
    V = XtXi @ sum(np.outer(v, v) for v in u.values()) @ XtXi
    return b, V


def mult_fit(rows, k):
    b, V = cl_ols(rows, f_mult(k)); i, j = len(b) - 2, len(b) - 1
    m = b[i] / b[j] if b[j] > 0 else None
    # delta-method SE of the ratio
    g = np.array([1 / b[j], -b[i] / b[j] ** 2]); Vs = V[np.ix_([i, j], [i, j])]
    return {'k': k, 'plus': [round(float(b[i]), 5), round(float(math.sqrt(V[i, i])), 5)], 'rest': [round(float(b[j]), 5), round(float(math.sqrt(V[j, j])), 5)],
            'm': round(float(m), 2) if m else None, 'm_se': round(float(math.sqrt(g @ Vs @ g)), 2) if m else None,
            't_diff': round(float((b[i] - b[j]) / math.sqrt(V[i, i] + V[j, j] - 2 * V[i, j])), 2), 'n': len(rows)}


def forward(rows, cut, forms, base):
    tr = [r for r in rows if r['c'] <= cut]; te = [r for r in rows if r['c'] > cut]
    ytr = np.array([r['y'] for r in tr]); yte = np.array([r['y'] for r in te]); g = [r['t'] for r in te]
    eb = (yte - T.X_of(te, base) @ T.ols(T.X_of(tr, base), ytr)) ** 2
    _, pick = T.loco(tr, forms); j = max(set(pick.values()), key=list(pick.values()).count)
    e = (yte - T.X_of(te, forms[j]) @ T.ols(T.X_of(tr, forms[j]), ytr)) ** 2
    return {'pick_i': j, 'd': round(float((eb - e).mean()), 5), 't': round(T.t_cluster(eb - e, g), 2), 'n': len(te)}


def summarize(res, labels):
    return {k: {'rmse': v['rmse'], 'd': v['d'], 't': v['t'], 'p': v['p'], 'holm': v['holm'], 'up': v['classes_up'], 'pass': v['pass'],
                'k': sorted(set(map(str, v['pick'].values())))} for k, v in res['forms'].items()}


def main():
    out = {}
    for sp in ('cfb', 'cbb'):
        P, S, C = T.load(sp); R = ranked(sp, C); F = fam(sp); o = out[sp] = {}
        # primary: roster stock
        rows = ST.rows_of(sp, S, C)
        cfg = ST.CFG[sp]
        for r in rows: r['ck'] = [R.get(r['c'] + k, {}).get(r['t'], []) for k in cfg['cls']]
        res = T.compare(rows, F, base=f_plain)
        o['stock'] = {'n': res['n'], 'seasons': res['classes'], 'base_rmse': res['base_rmse'], 'forms': summarize(res, None)}
        for name, (forms, labels) in F.items():
            fw = forward(rows, 2019, forms, f_plain); fw['k'] = labels[fw.pop('pick_i')]; o['stock']['forms'][name]['forward'] = fw
            o['stock']['forms'][name]['pass'] = bool(o['stock']['forms'][name]['pass'] and fw['d'] > 0)
        o['stock']['fit'] = {str(k): mult_fit(rows, k) for k in KS[sp]}
        o['stock']['nil'] = mult_fit([r for r in rows if r['c'] >= 2022], LIVE_K[sp])
        wr = ST.rows_of(sp, S, C, key='wp')
        for r in wr: r['ck'] = [R.get(r['c'] + k, {}).get(r['t'], []) for k in cfg['cls']]
        if len(wr) > 500:
            wres = T.compare(wr, F, base=f_plain); o['stock_winpct'] = {k: {'t': v['t'], 'up': v['classes_up']} for k, v in wres['forms'].items()}
            o['stock_winpct_fit'] = mult_fit(wr, LIVE_K[sp])
        # secondary: one class, three seasons, round 2 controls
        r1 = T.rows_of(sp, S, C, r2=True)
        for r in r1: r['ck'] = [R.get(r['c'], {}).get(r['t'], [])]
        res = T.compare(r1, F, base=f_plain)
        o['one_class'] = {'n': res['n'], 'classes': res['classes'], 'base_rmse': res['base_rmse'], 'forms': summarize(res, None), 'fit': mult_fit(r1, LIVE_K[sp])}
        # CBB: first season with returning and transfer value
        if sp == 'cbb':
            def cbb_x(t, c):
                x = P['prior'].get(str(c + 1), {}).get(t)
                return None if not x or x.get('ret') is None or x.get('tr') is None else [x['ret'], x['tr']]
            r3 = T.rows_of(sp, S, C, classes=range(2012, 2026), out=(1,), extra=cbb_x, r2=True)
            for r in r3: r['ck'] = [R.get(r['c'], {}).get(r['t'], [])]
            res = T.compare(r3, F, base=f_plain)
            o['roster_check'] = {'n': res['n'], 'classes': res['classes'], 'forms': summarize(res, None), 'fit': mult_fit(r3, LIVE_K[sp])}
        print(sp, json.dumps(o, indent=1))
    json.dump(out, open(os.path.join(HERE, 'result.json'), 'w'), indent=1)


if __name__ == '__main__': main()
