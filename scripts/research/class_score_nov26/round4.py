# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Round 4 (prereg.md): value basis, development, timing, attrition, portal net class. python3 round4.py -> round4.json"""
import gzip, json, math, os, sys
from collections import Counter, defaultdict
import numpy as np
import tests as T, stock as K
sys.path.insert(0, os.path.join(T.ROOT, 'scripts'))
import names as N  # noqa: E402

out = {}


def binmap(x, y, nb=24):
    x, y = np.asarray(x, float), np.asarray(y, float)
    edges = np.unique(np.concatenate([np.quantile(x, np.linspace(0, .9, nb)), np.quantile(x, [.93, .96, .98, .99, 1.0])]))
    xs, ys = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (x >= a) & (x <= b)
        if m.sum() >= 5: xs.append(float(x[m].mean())); ys.append(float(y[m].mean()))
    return lambda v: float(np.interp(v, xs, ys))


def run(rows, forms, base, folds_name='classes'):
    res = T.compare(rows, {k: ([f], ['-']) for k, f in forms.items()}, base=base)
    return {'n': res['n'], 'folds': res['classes'], 'base': res['base_rmse'], 'forms': {k: {'t': v['t'], 'p': v['p'], 'up': v['classes_up'], 'rmse': v['rmse']} for k, v in res['forms'].items()}}


def coef(rows, form, k=1):
    y = np.array([r['y'] for r in rows]); X = T.X_of(rows, form); b = T.ols(X, y); e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X); u = {}
    for x, ei, r in zip(X, e, rows): u[r['t']] = u.get(r['t'], 0) + x * ei
    se = np.sqrt(np.diag(XtXi @ sum(np.outer(v, v) for v in u.values()) @ XtXi))
    return [[round(float(b[-i]), 5), round(float(se[-i]), 5)] for i in range(k, 0, -1)]


def stock_dev(sp, S, C):
    """program development: season rating residual on the four-class stock, cross-section by season"""
    cfg = K.CFG[sp]; res = {}
    for s in sorted(S):
        ts = [t for t in S[s] if S[s][t].get('z') is not None]
        st = np.array([sum(p[2] for k in cfg['cls'] for p in C.get(s + k, {}).get(t, [])) for t in ts]); z = np.array([S[s][t]['z'] for t in ts])
        if len(ts) < 50 or st.std() == 0: continue
        b = np.polyfit(st, z, 1)
        for t, a, zz in zip(ts, st, z): res[(s, t)] = float(zz - np.polyval(b, a))
    return res


for sp in ('cfb', 'cbb'):
    P, S, C = T.load(sp); cfg = T.CFG[sp]; o = {}
    # ---- 1. value basis --------------------------------------------------------------------------------------------
    if sp == 'cfb':
        d = json.load(open(os.path.join(T.ROOT, 'static', 'data', 'cfb-recruits.json'))); fl = d['floor']
        live = [x for x in d['class'] + [y for f in d['future'] for y in f['list']] if x.get('comp') and x.get('tid') and x.get('level') in ('P4', 'G5')]
        maps = {nm: {lv: binmap([x['comp'] for x in live if x['level'] == lv], [g(x) - fl for x in live if x['level'] == lv], 24 if lv == 'P4' else 8) for lv in ('P4', 'G5')}
                for nm, g in (('FV if on the board', lambda x: x['fvOn']), ('year-3 xFV', lambda x: x['path'][2]))}
        lvl = lambda t, c: 'P4' if (S[min(max(S), c)].get(t) or {}).get('p4') else 'G5'
        alt = {nm: {c: {t: sorted((m[lvl(t, c)](p[1]) for p in ps), reverse=True) for t, ps in cl.items()} for c, cl in C.items()} for nm, m in maps.items()}
    else:
        d = json.load(open(os.path.join(T.ROOT, 'data', 'cbb_recruits.json')))
        live = [x for c in d['classes'] for x in c['list'] if x.get('rk')]
        maps = {nm: binmap([math.log(x['rk']) for x in live], [g(x) - 20 for x in live]) for nm, g in (('headline FV', lambda x: x['fvx']), ('Y1 FV', lambda x: x['y1fv']))}
        alt = {nm: {c: {t: sorted((max(0.0, m(math.log(p[1]))) for p in ps), reverse=True) for t, ps in cl.items()} for c, cl in C.items()} for nm, m in maps.items()}
    rows_c = T.rows_of(sp, S, C, r2=True); rows_s = K.rows_of(sp, S, C)
    a_c = lambda nm: (lambda r: [sum(alt[nm].get(r['c'], {}).get(r['t'], []))])
    a_s = lambda nm: (lambda r: [sum(sum(alt[nm].get(r['c'] + k, {}).get(r['t'], [])) for k in K.CFG[sp]['cls'])])
    plain_s = K.lift(T.f_plain)
    fc = {nm: a_c(nm) for nm in alt}; fc.update({f'blend with {nm}': (lambda r, nm=nm: T.f_plain(r) + a_c(nm)(r)) for nm in alt})
    fs = {nm: a_s(nm) for nm in alt}; fs.update({f'blend with {nm}': (lambda r, nm=nm: plain_s(r) + a_s(nm)(r)) for nm in alt})
    o['value'] = {'roster': run(rows_s, fs, plain_s), 'class': run(rows_c, fc, T.f_plain)}
    # ---- 2. development --------------------------------------------------------------------------------------------
    dev = stock_dev(sp, S, C); pre0 = max(cfg['pre'])
    rr = []
    for r in rows_c:
        v = [dev.get((r['c'] + pre0 - j, r['t'])) for j in (0, 1, 2)]; v = [x for x in v if x is not None]
        if not v: continue
        q = dict(r); q['dv'] = float(np.mean(v)); q['pre'] = r['pre'] + [q['dv']]; rr.append(q)
    o['development'] = run(rr, {'sum x development': lambda r: [sum(r['pts']), sum(r['pts']) * r['dv']]}, T.f_plain)
    o['development']['coef'] = coef(rr, lambda r: [sum(r['pts']), sum(r['pts']) * r['dv']], 2)
    # ---- 3. timing -------------------------------------------------------------------------------------------------
    if sp == 'cfb':
        O = json.load(gzip.open(os.path.join(T.ROOT, 'scripts', 'data', 'cfb_on3_hist.json.gz')))
        dt = {(int(y), N.key(r[0])): r[7] for y, rs in O.items() for r in rs}
    else:
        H = json.load(gzip.open(os.path.join(T.ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz')))
        dt = {(r['cls'], N.key(r['name'])): (r.get('x') or {}).get('commit') for r in H['recruits']}
    def tim(r):
        e = l = u = 0.0
        for nm, _, pts in C.get(r['c'], {}).get(r['t'], []):
            d_ = dt.get((r['c'], N.key(nm)))
            if not d_: u += pts
            elif d_ < f"{r['c'] - 1}-08-01": e += pts
            else: l += pts
        return [e, l, u]
    rt = [r for r in rows_c if r['c'] >= (2012 if sp == 'cfb' else 2012)]
    o['timing'] = run(rt, {'early / late / undated': tim}, T.f_plain); o['timing']['coef'] = coef(rt, tim, 3)
    tot = np.array([tim(r) for r in rt]).sum(0); o['timing']['share'] = [round(float(x / tot.sum()), 3) for x in tot]
    # ---- 4. attrition (CBB) ----------------------------------------------------------------------------------------
    if sp == 'cbb':
        pairs = defaultdict(Counter)
        for r in H['recruits']:
            if r.get('team') and r.get('college'): pairs[r['team']][r['college']['team']] += 1
        smap = {s: c.most_common(1)[0][0] for s, c in pairs.items() if c.most_common(1)[0][1] >= 3}
        en = defaultdict(lambda: [0, 0])
        for r in H['recruits']:
            t = smap.get(r.get('team'))
            if t and r.get('rk'): en[(r['cls'], t)][1] += 1; en[(r['cls'], t)][0] += bool(r.get('college') and r['college']['team'] == t)
        allr = sum(v[0] for v in en.values()) / sum(v[1] for v in en.values())
        ra = []
        for r in rows_c:
            a = sum(en[(r['c'] - j, r['t'])][0] for j in (1, 2, 3)); b = sum(en[(r['c'] - j, r['t'])][1] for j in (1, 2, 3))
            q = dict(r); q['er'] = (a + 5 * allr) / (b + 5) - allr; q['pre'] = r['pre'] + [q['er']]; ra.append(q)
        o['attrition'] = run(ra, {'sum x enrol rate': lambda r: [sum(r['pts']), sum(r['pts']) * r['er']]}, T.f_plain)
        o['attrition']['coef'] = coef(ra, lambda r: [sum(r['pts']), sum(r['pts']) * r['er']], 2); o['attrition']['rate'] = round(allr, 3)
    # ---- 5. portal net class ---------------------------------------------------------------------------------------
    if sp == 'cfb':
        F = json.load(open(os.path.join(T.ROOT, 'scripts', 'data', 'cfb_roster_feats.json')))['feats']
        def ex(t, c):
            x = F.get(str(c + 1), {}).get(t)
            return None if x is None else [x['offRet'], x['qbRet'], x['offIn']]
        nb = 2
    else:
        def ex(t, c):
            x = P['prior'].get(str(c + 1), {}).get(t)
            return None if x is None or x.get('ret') is None or x.get('tr') is None else [float(x['ret']), float(x['tr'])]
        nb = 1
    rp = T.rows_of(sp, S, C, classes=range(min(cfg['classes']), cfg['last']), out=(1,), extra=ex, r2=True)
    for r in rp: r['tr'] = r['x'][nb]; r['x'] = r['x'][:nb]
    o['portal'] = run(rp, {'class + transfers': lambda r: [sum(r['pts']), r['tr']]}, T.f_plain)
    o['portal']['coef'] = coef(rp, lambda r: [sum(r['pts']), r['tr']], 2)
    o['portal']['sd'] = [round(float(np.std([sum(r['pts']) for r in rp])), 2), round(float(np.std([r['tr'] for r in rp])), 3)]
    nil = [r for r in rp if r['c'] >= 2021]
    o['portal']['nil'] = {'n': len(nil), 'coef': coef(nil, lambda r: [sum(r['pts']), r['tr']], 2), **{k: v for k, v in run(nil, {'class + transfers': lambda r: [sum(r['pts']), r['tr']]}, T.f_plain)['forms']['class + transfers'].items()}}
    # Holm across the sport's round 4 tests (value decided on the roster design)
    ps = {f'value: {k}': v['p'] for k, v in o['value']['roster']['forms'].items()}
    for k in ('development', 'timing', 'attrition', 'portal'):
        if k in o: ps.update({f'{k}: {n}': v['p'] for n, v in o[k]['forms'].items()})
    o['holm'] = T.holm(ps)
    out[sp] = o
    print('==', sp)
    for k in ('roster', 'class'): print(' value', k, o['value'][k]['n'], o['value'][k]['base'], {n: (v['t'], v['up']) for n, v in o['value'][k]['forms'].items()})
    for k in ('development', 'timing', 'attrition', 'portal'):
        if k in o: print(' ', k, o[k]['n'], o[k]['folds'], o[k]['base'], {n: (v['t'], v['up']) for n, v in o[k]['forms'].items()}, 'coef', o[k].get('coef'), o[k].get('share', ''), o[k].get('sd', ''), o[k].get('nil', ''))
    print('  holm', {k: v for k, v in o['holm'].items() if v})
json.dump(out, open(os.path.join(T.HERE, 'round4.json'), 'w'), indent=1)
