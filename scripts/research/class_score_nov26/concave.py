"""Check: is the CBB gain a within-class reweighting, or only curvature in the total (which leaves the order alone)?
Each score enters with its square root too, so the plain sum gets the same freedom to bend."""
import json, math, os, sys
import numpy as np
import tests as T, stock as K
out = {}
bend = lambda f: (lambda r: (lambda v: v + [math.sqrt(max(0.0, x)) for x in v[:1]])(list(f(r))))
for sp in ('cfb', 'cbb'):
    P, S, C = T.load(sp)
    for nm, rows, plain, fam in (('class', T.rows_of(sp, S, C, r2=True), T.f_plain, T.family(sp, r2=True)), ('roster', K.rows_of(sp, S, C), K.lift(T.f_plain), K.family(sp))):
        fam = {k: v for k, v in fam.items() if k in ('decay', 'cap', 'star premium', 'power x decay')}
        fam2 = {k: ([bend(f) for f in fs], lab) for k, (fs, lab) in fam.items()}
        res = T.compare(rows, fam2, base=bend(plain))
        res0 = T.compare(rows, {'plain, bent': ([bend(plain)], ['-'])}, base=plain)
        # top end and depth beside the bent total
        k = T.CFG[sp]['live_k']; sp_f = K.lift(T.f_split(k)) if nm == 'roster' else T.f_split(k)
        y = np.array([r['y'] for r in rows]); X = T.X_of(rows, lambda r: (lambda v: [math.sqrt(v[0] + v[1])] + v)(list(sp_f(r)))); b = T.ols(X, y); e = y - X @ b
        XtXi = np.linalg.inv(X.T @ X); u = {}
        for x, ei, r in zip(X, e, rows): u[r['t']] = u.get(r['t'], 0) + x * ei
        V = XtXi @ sum(np.outer(v, v) for v in u.values()) @ XtXi; i, j = X.shape[1] - 2, X.shape[1] - 1
        w = {'top': [round(float(b[i]), 5), round(float(math.sqrt(V[i, i])), 5)], 'depth': [round(float(b[j]), 5), round(float(math.sqrt(V[j, j])), 5)], 't_diff': round(float((b[i] - b[j]) / math.sqrt(V[i, i] + V[j, j] - 2 * V[i, j])), 2)}
        out[f'{sp} {nm}'] = {'n': res['n'], 'bent_vs_plain': {'t': res0['forms']['plain, bent']['t'], 'up': res0['forms']['plain, bent']['classes_up']}, 'base': res['base_rmse'],
                             'forms': {k_: {'t': v['t'], 'up': v['classes_up'], 'rmse': v['rmse'], 'holm': v['holm']} for k_, v in res['forms'].items()}, 'weights': w}
        print(sp, nm, out[f'{sp} {nm}'])
json.dump(out, open(os.path.join(T.HERE, 'concave.json'), 'w'), indent=1)

# CBB, first season, returning and transfer value in, totals free to bend: does any within-class discount survive?
PB, SB, CB = T.load('cbb')
def cbb_x(t, c):
    x = PB['prior'].get(str(c + 1), {}).get(t)
    return None if x is None or x.get('ret') is None or x.get('tr') is None else [float(x['ret']), float(x['tr'])]
for nm, ex in (('no roster controls', None), ('roster controls', cbb_x)):
    rows = T.rows_of('cbb', SB, CB, classes=range(2013, 2026), out=(1,), extra=ex, r2=True)
    fam = {k: ([bend(f) for f in fs], lab) for k, (fs, lab) in T.family('cbb', r2=True).items() if k in ('decay', 'cap', 'star premium', 'power x decay')}
    res = T.compare(rows, fam, base=bend(T.f_plain))
    out[f'cbb first season, {nm}'] = {'n': res['n'], 'base': res['base_rmse'], 'forms': {k_: {'t': v['t'], 'up': v['classes_up'], 'of': res['classes']} for k_, v in res['forms'].items()}}
    print(nm, out[f'cbb first season, {nm}'])
json.dump(out, open(os.path.join(T.HERE, 'concave.json'), 'w'), indent=1)
