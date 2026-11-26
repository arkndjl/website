# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Class score forms against results, held out by class (prereg.md). python3 tests.py cfb|cbb -> <sport>_tests.json"""
import json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'classscore')
CFG = {'cfb': {'classes': range(2012, 2023), 'out': (1, 2, 3), 'pre': (-1, -2), 'k': [3, 5, 8, 10], 'cap': [10, 15, 20, 25], 'live_k': 5, 'last': 2025},
       'cbb': {'classes': range(2012, 2024), 'out': (1, 2, 3), 'pre': (0, -1), 'k': [1, 2, 3], 'cap': [2, 3, 4, 5], 'live_k': 2, 'last': 2026}}
DEC = [.80, .85, .90, .95, .975]
POW = [.5, .75, 1.25, 1.5, 2]


def load(sp):
    P = json.load(open(os.path.join(CACHE, f'{sp}_panel.json')))
    S = {int(y): v for y, v in P['seasons'].items()}; C = {int(y): v for y, v in P['classes'].items()}
    return P, S, C


def rows_of(sp, S, C, classes=None, out=None, key='z', extra=None, r2=False):
    cfg = CFG[sp]; rows = []
    for c in classes or cfg['classes']:
        for t in S.get(c + cfg['out'][0], {}):
            ys = [(S.get(c + k) or {}).get(t, {}).get(key) for k in (out or cfg['out'])]
            pre = [(S.get(c + k) or {}).get(t, {}).get('z') for k in cfg['pre']]
            if any(v is None for v in ys + pre): continue
            pts = sorted((p[2] for p in C.get(c, {}).get(t, [])), reverse=True)
            prev = [sum(p[2] for p in C.get(c - j, {}).get(t, [])) for j in (1, 2, 3)]
            r = {'t': t, 'c': c, 'y': float(np.mean(ys)), 'pre': pre, 'prev': prev, 'pts': pts, 'pos': None}
            if r2:      # round 2 controls: program baseline, level
                lo = min(cfg['pre'])
                b = [(S.get(c + k) or {}).get(t, {}).get('z') for k in (lo - 1, lo - 2, lo - 3)]
                b = [v for v in b if v is not None]
                if not b or (sp == 'cbb' and not pts): continue
                r['pre'] = pre + [float(np.mean(b))] + ([float(bool(((S.get(c - 1) or {}).get(t) or {}).get('p4')))] if sp == 'cfb' else [])
            if extra:
                e = extra(t, c)
                if e is None: continue
                r['x'] = e
            rows.append(r)
    return rows


# ---- forms: rows -> columns that replace the plain score --------------------------------------------------------
def f_plain(r): return [sum(r['pts'])]
def f_split(k): return lambda r: [sum(r['pts'][:k]), sum(r['pts'][k:])]
def f_decay(d): return lambda r: [sum(p * d ** i for i, p in enumerate(r['pts']))]
def f_cap(n): return lambda r: [sum(r['pts'][:n])]
def f_pow(p): return lambda r: [sum(x ** p for x in r['pts'])]
def f_avg(r): return [float(np.mean(r['pts'])) if r['pts'] else 0.0, math.log(1 + len(r['pts']))]
def f_pos(r): return [sum(r['pts']), r['pos'][0], r['pos'][1]]


def X_of(rows, form, ctl=True):
    return np.array([[1.0] + (r['pre'] + r['prev'] if ctl else []) + (r.get('x') or []) + form(r) for r in rows])


def ols(X, y):
    return np.linalg.solve(X.T @ X + 1e-8 * np.eye(X.shape[1]), X.T @ y)


def loco(rows, forms, inner=True):
    """held-out prediction per row; forms = list of candidate forms, the one used in each fold picked by leave-one-
    class-out inside the training classes"""
    y = np.array([r['y'] for r in rows]); c = np.array([r['c'] for r in rows]); Xs = [X_of(rows, f) for f in forms]
    pred = np.zeros(len(rows)); pick = {}
    for h in sorted(set(c)):
        tr, te = c != h, c == h
        j = 0
        if len(forms) > 1:
            best = None
            for i, X in enumerate(Xs):
                sse = 0.0
                for h2 in sorted(set(c[tr])):
                    a, b = tr & (c != h2), tr & (c == h2)
                    sse += float(((y[b] - X[b] @ ols(X[a], y[a])) ** 2).sum())
                if best is None or sse < best: best, j = sse, i
        pick[int(h)] = j
        pred[te] = Xs[j][te] @ ols(Xs[j][tr], y[tr])
    return pred, pick


def t_cluster(d, g):
    d = np.asarray(d, float); u = {}
    for x, k in zip(d - d.mean(), g): u[k] = u.get(k, 0.0) + x
    se = math.sqrt(sum(v * v for v in u.values())) / len(d) * math.sqrt(len(u) / (len(u) - 1))
    return float(d.mean() / se) if se else 0.0


def p_one(t): return 0.5 * math.erfc(t / math.sqrt(2))


def holm(ps, alpha=0.05):
    o = sorted(ps, key=ps.get); out, ok = {}, True
    for i, k in enumerate(o):
        ok = ok and ps[k] <= alpha / (len(o) - i); out[k] = ok
    return out


def compare(rows, fam, base=None):
    y = np.array([r['y'] for r in rows]); c = np.array([r['c'] for r in rows]); g = [r['t'] for r in rows]
    pb, _ = loco(rows, [base or f_plain]); eb = (y - pb) ** 2
    out = {'n': len(rows), 'classes': len(set(c)), 'base_rmse': round(float(math.sqrt(eb.mean())), 4), 'forms': {}}
    for name, (forms, labels) in fam.items():
        p, pick = loco(rows, forms); e = (y - p) ** 2; d = eb - e
        by = {int(h): float(d[c == h].mean()) for h in sorted(set(c))}
        t = t_cluster(d, g)
        out['forms'][name] = {'rmse': round(float(math.sqrt(e.mean())), 4), 'd': round(float(d.mean()), 5), 't': round(t, 2), 'p': round(p_one(t), 4),
                              'classes_up': sum(v > 0 for v in by.values()), 'pick': {h: labels[j] for h, j in pick.items()}}
    ok = holm({k: v['p'] for k, v in out['forms'].items()})
    for k, v in out['forms'].items(): v['holm'] = bool(ok[k]); v['pass'] = bool(ok[k] and v['classes_up'] >= math.ceil(2 * out['classes'] / 3))
    return out


PD = [(p, d) for p in (.33, .5, .75, 1) for d in (.6, .7, .8, .9, 1)]
def f_pd(p, d): return lambda r: [sum(x ** p * d ** i for i, x in enumerate(r['pts']))]


def family(sp, pos=False, r2=False):
    cfg = CFG[sp]
    fam = {'split': ([f_split(k) for k in cfg['k']], cfg['k']), 'decay': ([f_decay(d) for d in DEC], DEC), 'cap': ([f_cap(n) for n in cfg['cap']], cfg['cap']),
           'star premium': ([f_pow(p) for p in POW], POW), 'average + size': ([f_avg], ['-'])}
    if pos: fam['position mix'] = ([f_pos], ['-'])
    if r2: fam['power x decay'] = ([f_pd(p, d) for p, d in PD], [f'{p}/{d}' for p, d in PD])
    return fam


def weights(rows, k):
    """full-sample weights per FV point for the top end and the depth, program-clustered SE"""
    y = np.array([r['y'] for r in rows]); X = X_of(rows, f_split(k)); b = ols(X, y); e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X); u = {}
    for x, ei, r in zip(X, e, rows): u[r['t']] = u.get(r['t'], 0) + x * ei
    M = sum(np.outer(v, v) for v in u.values()); V = XtXi @ M @ XtXi
    se = np.sqrt(np.diag(V)); i, j = X.shape[1] - 2, X.shape[1] - 1
    top = np.array([sum(r['pts'][:k]) for r in rows]); dep = np.array([sum(r['pts'][k:]) for r in rows])
    dv = b[i] - b[j]; sed = math.sqrt(V[i, i] + V[j, j] - 2 * V[i, j])
    # raw and partial correlations with the outcome
    Z = X_of(rows, lambda r: []); res = lambda v: v - Z @ ols(Z, v)
    return {'k': k, 'top': [round(float(b[i]), 5), round(float(se[i]), 5)], 'depth': [round(float(b[j]), 5), round(float(se[j]), 5)],
            'ratio': round(float(b[i] / b[j]), 2) if b[j] > 0 else None, 't_diff': round(float(dv / sed), 2),
            'sd': [round(float(top.std()), 2), round(float(dep.std()), 2)], 'per_sd': [round(float(b[i] * top.std()), 4), round(float(b[j] * dep.std()), 4)],
            'r': [round(float(np.corrcoef(top, y)[0, 1]), 3), round(float(np.corrcoef(dep, y)[0, 1]), 3)], 'r_top_depth': round(float(np.corrcoef(top, dep)[0, 1]), 3),
            'partial': [round(float(np.corrcoef(res(top), res(y))[0, 1]), 3), round(float(np.corrcoef(res(dep), res(y))[0, 1]), 3)]}


def forward(rows, fam, split=2016):
    tr = [r for r in rows if r['c'] <= split]; te = [r for r in rows if r['c'] > split]
    y = np.array([r['y'] for r in te]); g = [r['t'] for r in te]
    eb = (y - X_of(te, f_plain) @ ols(X_of(tr, f_plain), np.array([r['y'] for r in tr]))) ** 2
    out = {'n': len(te)}
    for name, (forms, labels) in fam.items():
        _, pick = loco(tr, forms) if len(forms) > 1 else (None, {})
        ytr = np.array([r['y'] for r in tr]); ctr = np.array([r['c'] for r in tr]); best, j = None, 0
        for i, f in enumerate(forms):
            X = X_of(tr, f); sse = 0.0
            for h in sorted(set(ctr)):
                a, b = ctr != h, ctr == h; sse += float(((ytr[b] - X[b] @ ols(X[a], ytr[a])) ** 2).sum())
            if best is None or sse < best: best, j = sse, i
        e = (y - X_of(te, forms[j]) @ ols(X_of(tr, forms[j]), ytr)) ** 2
        out[name] = {'pick': labels[j], 'd': round(float((eb - e).mean()), 5), 't': round(t_cluster(eb - e, g), 2)}
    return out


def main(sp, r2=False):
    P, S, C = load(sp); cfg = CFG[sp]
    if r2:
        global rows_of
        base_rows = rows_of
        rows_of = lambda *a, **k: base_rows(*a, **{**k, 'r2': True})
    rows = rows_of(sp, S, C); fam = family(sp, r2=r2)
    res = {'map': P['check'], 'primary': compare(rows, fam), 'forward': forward(rows, fam), 'weights': {str(k): weights(rows, k) for k in cfg['k']}}
    res['secondary'] = {}
    for nm, kw in [('win %', {'key': 'wp'})] + ([('elo', {'key': 'elo'})] if sp == 'cfb' else []) + [(f'season +{k}', {'out': (k,)}) for k in (1, 2, 3, 4)] + [('NIL era', {'classes': range(2021, max(cfg['classes']) + 1)})]:
        kw2 = dict(kw)
        if 'out' in kw2 and kw2['out'] == (4,): kw2['classes'] = range(min(cfg['classes']), cfg['last'] - 3)
        rr = rows_of(sp, S, C, **kw2)
        if len(set(r['c'] for r in rr)) < 3: res['secondary'][nm] = {'n': len(rr), 'weights': weights(rr, cfg['live_k'])}; continue
        res['secondary'][nm] = {**compare(rr, fam), 'weights': weights(rr, cfg['live_k'])}
    json.dump(res, open(os.path.join(HERE, f"{sp}_tests{'_r2' if r2 else ''}.json"), 'w'), indent=1)
    pr = res['primary']; print(sp, 'n', pr['n'], 'classes', pr['classes'], 'base rmse', pr['base_rmse'], 'map', res['map'])
    for k, v in pr['forms'].items(): print(f"  {k:16s} rmse {v['rmse']} d {v['d']:+.5f} t {v['t']:+.2f} up {v['classes_up']}/{pr['classes']} pass {v['pass']} pick {sorted(set(v['pick'].values()), key=str)}")
    print('  forward', res['forward'])
    for k, w in res['weights'].items(): print('  weights k', k, w)
    for nm, v in res['secondary'].items():
        print(' ', nm, 'n', v['n'], {k: (f['t'], f['classes_up']) for k, f in v.get('forms', {}).items()}, 'w', v['weights']['top'], v['weights']['depth'], v['weights']['ratio'], v['weights']['t_diff'])


if __name__ == '__main__': main(sys.argv[1], 'r2' in sys.argv)
