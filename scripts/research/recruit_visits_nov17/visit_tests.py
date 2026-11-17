# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-registered tests (prereg.md): V visits, E expert picks, R RPM snapshot, each on top of the live LIST model,
walk-forward by class, features as of the On3 commitment date - H days.
  python3 scripts/research/recruit_visits_nov17/visit_tests.py [cfb|cbb] [--h 30]"""
import json, math, os, sys
from collections import defaultdict
from datetime import date, timedelta
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import recruit_commit_fit as C  # noqa: E402
import recruit_on3_join as J  # noqa: E402

NATIVE = 'ov' in C.COLS   # recruit_commit_fit.py has carried the On3 columns since the Nov 17 ship
if not NATIVE: C.COLS = C.BASE + C.DIST + C.MORE + J.COLS
SPEC = {'cfb': (['pull', 'tier', 'gxt', 'gap', 'ld', 'inst', 'conv', 'elo', 'delo'], .75),
        'cbb': (['pull', 'tier', 'gxt', 'gap', 'ld', 'inst'], None)}
FAM = {'V visits': ['ov', 'luv', 'vlast', 'vrec'], 'E experts': ['esh', 'eany'], 'R rpm': ['lrpm', 'rpm_has']}
_feats = C.feats


def feats(x, alts, st, loc):
    F = _feats(x, alts, st, loc)
    ex = x.get('ex') or {}
    return np.hstack([F, np.array([J.alt_feats(ex, t) for t in alts])])


if not NATIVE: C.feats = feats


def fit_w(X, yv, cols, w, lam=C.LAM):
    idx = [C.COLS.index(c) for c in cols]
    A = np.vstack([x[:, idx] for x in X]); mu, sd = A.mean(0), A.std(0) + 1e-9
    off = np.cumsum([0] + [len(x) for x in X]); Z = (A - mu) / sd; ch = off[:-1] + yv
    n = np.diff(off); b = np.zeros(len(idx)); wr = np.repeat(w, n)
    def obj(b):
        u = Z @ b; m = np.maximum.reduceat(u, off[:-1]); e = np.exp(u - np.repeat(m, n)); s = np.add.reduceat(e, off[:-1])
        return -(w * (u[ch] - m - np.log(s))).sum() + lam * b @ b, e / np.repeat(s, n)
    f0, p = obj(b)
    for _ in range(100):
        zb = np.add.reduceat(p[:, None] * Z, off[:-1])
        gr = (w[:, None] * Z[ch]).sum(0) - (w[:, None] * zb).sum(0) - 2 * lam * b
        H = ((wr * p)[:, None] * Z).T @ Z - (w[:, None] * zb).T @ zb + 2 * lam * np.eye(len(b))
        step, a = np.linalg.solve(H, gr), 1.0
        while a > 1e-6:
            f1, p1 = obj(b + a * step)
            if f1 <= f0 + 1e-10: break
            a /= 2
        b, f0, p = b + a * step, f1, p1
        if np.abs(a * step).max() < 1e-8: break
    return {'cols': cols, 'b': (b / sd).tolist(), 'mu': mu.tolist(), 'sd': sd.tolist(), 'b_std': b.tolist()}


def walk(sp, loc, cls, specs):
    res = {k: defaultdict(list) for k in specs}; start = C.YEARS[sp][0] + 3
    for y in C.HELD[sp]:
        Xt, yt, mt = C.build(sp, loc, cls, range(start, y), 'list', True); Xh, yh, mh = C.build(sp, loc, cls, [y], 'list', False)
        has = {(m[0], m[1]) for m in mh}
        hx = {(y, x['rid']): bool(x.get('ex')) for x in cls[y]}
        for k, (cols, dec) in specs.items():
            w = np.array([dec ** (y - 1 - m[0]) for m in mt]) if dec else np.ones(len(mt)); w = w / w.mean()
            m = fit_w(Xt, yt, cols, w); ll, br, t1, t3 = C.score(m, Xh, yh)
            top = [float(C.probs(m, F).max()) for F in Xh]; hit = [int(np.argmax(C.probs(m, F)) == c) for F, c in zip(Xh, yh)]
            for key, v in (('ll', ll), ('br', br), ('t1', t1), ('t3', t3), ('top', np.array(top)), ('hit', np.array(hit))): res[k][key].append(v)
            res[k]['yr'].append(np.full(len(ll), y)); res[k]['on3'].append(np.array([hx[(mm[0], mm[1])] for mm in mh]))
            if k != 'base': res[k]['coef'].append(dict(zip(cols, np.round(m['b_std'], 3).tolist())))
        print(sp, y, len(yh), int(sum(res[next(iter(res))]['on3'][-1])), {k: round(float(np.mean(res[k]['ll'][-1])), 4) for k in res}, flush=True)
    return {k: {kk: (np.concatenate(v) if kk != 'coef' else v) for kk, v in d.items()} for k, d in res.items()}


def p_one(t):
    return 0.5 * math.erfc(t / math.sqrt(2))


def holm(ps, a=.05):
    out, ks = {}, sorted(ps, key=ps.get)
    for i, k in enumerate(ks):
        out[k] = ps[k] <= a / (len(ks) - i) and all(out[j] for j in ks[:i])
    return out


def gate(a, b, sub=None):
    d = b['ll'] - a['ll']; yr = a['yr']
    if sub is not None: d, yr = d[sub], yr[sub]
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)) + 1e-12)
    yrs = sorted(set(yr)); pos = sum(d[yr == y].mean() > 0 for y in yrs) / len(yrs)
    return {'gain': float(d.mean()), 't': float(t), 'n': int(len(d)), 'classesPos': round(float(pos), 3),
            'byClass': {int(y): round(float(d[yr == y].mean()), 4) for y in yrs}}


def calib(r, bins=10):
    p, h = r['top'], r['hit']; q = np.minimum((p * bins).astype(int), bins - 1)
    return [[round(float(p[q == i].mean()), 3), round(float(h[q == i].mean()), 3), int((q == i).sum())] for i in range(bins) if (q == i).sum()]


def summ(r, sub=None):
    s = (lambda v: v[sub]) if sub is not None else (lambda v: v)
    return {'ll': float(s(r['ll']).mean()), 'brier': float(s(r['br']).mean()), 'top1': float(s(r['t1']).mean()), 'n': int(len(s(r['ll'])))}


def cover(cov, k, yr):
    """E, R: the held classes with 20+ recruits that have the data (V: every held class)"""
    if k[0] == 'V': return None
    cl = [int(y) for y, n in cov['byClass'].items() if n.get(k[0], 0) >= 20]
    return np.isin(yr, cl)


def main():
    sps = [a for a in sys.argv[1:] if a in C.YEARS] or ['cfb', 'cbb']
    H = int(sys.argv[sys.argv.index('--h') + 1]) if '--h' in sys.argv else 30
    out = json.load(open(os.path.join(HERE, 'visit_tests.json'))) if os.path.exists(os.path.join(HERE, 'visit_tests.json')) else {}
    for sp in sps:
        loc, cls = C.load(sp)
        cov = J.attach(sp, cls, H)
        print(sp, 'coverage', cov, flush=True)
        base, dec = SPEC[sp]
        specs = {'base': (base, dec), **{k: (base + v, dec) for k, v in FAM.items()}}
        r = walk(sp, loc, cls, specs)
        o = {'H': H, 'coverage': cov, 'base': summ(r['base']), 'baseOn3': summ(r['base'], r['base']['on3'])}
        for k in FAM:
            g = gate(r['base'], r[k]); g['on3'] = gate(r['base'], r[k], r['base']['on3'])
            # gate on the classes the family has data for (E, R: pick coverage); the t is over all recruits
            sub = cover(cov, k, r['base']['yr'])
            g['gateOn'] = gate(r['base'], r[k], sub) if sub is not None and sub.any() else gate(r['base'], r[k])
            g['p'] = p_one(g['gateOn']['t']); g['with'] = summ(r[k]); g['withOn3'] = summ(r[k], r['base']['on3'])
            g['calib'] = calib(r[k]); g['coefLast'] = r[k]['coef'][-1]; o[k] = g
        o['baseCalib'] = calib(r['base'])
        hp = holm({k: o[k]['p'] for k in FAM})
        for k in FAM:
            gg = o[k]['gateOn']; o[k]['holm'] = hp[k]
            o[k]['pass'] = bool(hp[k] and gg['gain'] > 0 and gg['classesPos'] >= 2 / 3)
        win = [k for k in FAM if o[k]['pass']]
        print(sp, 'pass', win, flush=True)
        for k in FAM:
            v = o[k]; print(sp, k, 'gain', round(v['gain'], 4), 't', round(v['t'], 2), 'on3', round(v['on3']['gain'], 4), round(v['on3']['t'], 2), 'gateOn', round(v['gateOn']['gain'], 4), round(v['gateOn']['t'], 2), v['gateOn']['classesPos'], 'pass', v['pass'], v['coefLast'], flush=True)
        if len(win) > 1:   # forward in order V, E, R: each passer on top of the ones before it
            kept = list(base); cur = r['base']; fw = []
            for k in win:
                j = walk(sp, loc, cls, {'cur': (kept, dec), 'add': (kept + FAM[k], dec)})
                g = gate(j['cur'], j['add'], cover(cov, k, j['cur']['yr'])); fw.append({'add': k, **g})
                if g['gain'] > 0 and g['t'] >= 2 and g['classesPos'] >= 2 / 3: kept += FAM[k]; cur = j['add']
            o['forward'] = fw; o['kept'] = kept
            jj = walk(sp, loc, cls, {'base': (base, dec), 'final': (kept, dec)})
            o['final'] = {**gate(jj['base'], jj['final']), 'with': summ(jj['final']), 'calib': calib(jj['final']), 'cols': kept}
        elif win:
            o['kept'] = base + FAM[win[0]]
            o['final'] = {**{a: o[win[0]][a] for a in ('gain', 't', 'classesPos', 'byClass')}, 'with': o[win[0]]['with'], 'calib': o[win[0]]['calib'], 'cols': o['kept']}
        out[f'{sp}_h{H}'] = o
        for k in FAM:
            v = o[k]; print(sp, k, 'gain', round(v['gain'], 4), 't', round(v['t'], 2), 'gateOn', round(v['gateOn']['gain'], 4), round(v['gateOn']['t'], 2), v['gateOn']['classesPos'], 'holm', v['holm'], 'pass', v['pass'])
            print('   byClass', v['gateOn']['byClass'], 'top1', round(v['with']['top1'], 4), 'vs', round(o['base']['top1'], 4))
        json.dump(out, open(os.path.join(HERE, 'visit_tests.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
