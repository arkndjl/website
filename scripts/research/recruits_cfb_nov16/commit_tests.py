# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family COMMIT (prereg.md): C1 conversion, C2 on-field strength, C3 place in his list, C4 high-school pipeline,
C5 recency weights, each on top of the shipped LIST model (CFB), walk-forward by class."""
import json, math, os, sys
from collections import defaultdict
import numpy as np
from common import R, T, p_one, holm, HERE
import recruit_commit_fit as C

NEW = ['conv', 'elo', 'delo', 'best', 'near', 'hsp']
C.COLS = C.BASE + C.DIST + NEW
KEPT = ['pull', 'tier', 'gxt', 'gap', 'ld', 'inst']
_ELO = {}


def elo(y):
    if y not in _ELO:
        try: _ELO[y] = {t: v['eloZ'] for t, v in T.programs_hist(y).items()}
        except SystemExit: _ELO[y] = {}
    return _ELO[y]


def school_stats(cls, y, loc):
    n, s, bys, listed, hsn = defaultdict(int), defaultdict(float), defaultdict(int), defaultdict(int), defaultdict(int)
    for k in (y - 3, y - 2, y - 1):
        for x in cls.get(k, []):
            for t in x['list']: listed[t] += 1
            if x['chose'] in loc:
                n[x['chose']] += 1; s[x['chose']] += x['g']; bys[(x['chose'], x['st'])] += 1
                if x.get('hs'): hsn[(x['chose'], x['hs'])] += 1
    allm = sum(s.values()) / max(1, sum(n.values()))
    tier = {t: (s[t] + 5 * allm) / (n[t] + 5) for t in n}
    return n, tier, bys, listed, hsn, elo(y), elo(y - 1)


def feats(x, alts, st, loc):
    n, tier, bys, listed, hsn, e1, e0 = st
    F = []
    for t in alts:
        lat, lon, sst, _ = loc[t]
        ld = math.log1p(C.miles(x['home'], (lat, lon)) / 100); tr = tier.get(t, -1.0)
        F.append([math.log1p(n.get(t, 0)), tr, x['g'] * tr, abs(x['g'] - tr), ld, float(sst == x['st']),
                  math.log1p(bys.get((t, x['st']), 0)), ld * tr, ld * x['g'],
                  math.log((n.get(t, 0) + 1) / (listed.get(t, 0) + 5)), e1.get(t, 0.0), e1.get(t, 0.0) - e0.get(t, e1.get(t, 0.0)), 0.0, 0.0,
                  math.log1p(hsn.get((t, x.get('hs')), 0)) if x.get('hs') else 0.0])
    F = np.array(F); F[:, 12] = F[:, 1] >= F[:, 1].max() - 1e-12; F[:, 13] = F[:, 4] <= F[:, 4].min() + 1e-12
    return F


C.school_stats, C.feats = school_stats, feats


def fit_w(X, yv, cols, w, lam=C.LAM):
    """C.fit with a weight on each recruit"""
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


def walk(loc, cls, specs):
    """specs: {name: (cols, decay or None)}; per held class fit on all earlier classes, score the class"""
    res = {k: defaultdict(list) for k in specs}; start = C.YEARS['cfb'][0] + 3
    for y in C.HELD['cfb']:
        Xt, yt, mt = C.build('cfb', loc, cls, range(start, y), 'list', True); Xh, yh, _ = C.build('cfb', loc, cls, [y], 'list', False)
        for k, (cols, dec) in specs.items():
            w = np.array([dec ** (y - 1 - m[0]) for m in mt]) if dec else np.ones(len(mt)); w = w / w.mean()
            m = fit_w(Xt, yt, cols, w); ll, br, t1, t3 = C.score(m, Xh, yh)
            for key, v in (('ll', ll), ('br', br), ('t1', t1), ('t3', t3)): res[k][key].append(v)
            res[k]['yr'].append(np.full(len(ll), y))
        print(y, len(yh), {k: round(float(np.mean(res[k]['ll'][-1])), 4) for k in res}, flush=True)
    return {k: {kk: np.concatenate(v) for kk, v in d.items()} for k, d in res.items()}


def main():
    loc, cls = C.load('cfb')
    for y, rows in cls.items():   # the ESPN high-school id (cleaned of colleges named in the field), by recruit id
        hs = {str(r['rid']): r.get('hs') for r in R.recruit_class(y)}
        for x in rows: x['hs'] = hs.get(str(x['rid']))
    print('hs coverage', {y: round(float(np.mean([bool(x['hs']) for x in rows])), 2) for y, rows in cls.items()})
    print('elo seasons', {y: len(elo(y)) for y in range(2014, 2028)})
    specs = {'base': (KEPT, None), 'C1 conv': (KEPT + ['conv'], None), 'C2 elo': (KEPT + ['elo', 'delo'], None), 'C3 place': (KEPT + ['best', 'near'], None),
             'C4 hs': (KEPT + ['hsp'], None), 'C5 recency': (KEPT, .75)}
    r = walk(loc, cls, specs); out = {'base': C.summ(r['base'])}
    for k in specs:
        if k == 'base': continue
        g = C.gate(r['base'], r[k]); g['p'] = p_one(g['t']); g['with'] = C.summ(r[k]); out[k] = g
    hp = holm({k: out[k]['p'] for k in out if k != 'base'})
    for k in hp: out[k]['holm'] = hp[k]; out[k]['pass'] = bool(hp[k] and out[k]['gain'] > 0 and out[k]['classesPos'] >= 2 / 3 and not (out[k]['nilGain'] < 0 and out[k]['nilT'] <= -1))
    win = [k for k in hp if out[k]['pass']]; print('pass', win)
    if win:
        cols = list(KEPT); dec = None
        for k in win:
            if k == 'C5 recency': dec = .75
            else: cols += [c for c in specs[k][0] if c not in cols]
        j = walk(loc, cls, {'base': (KEPT, None), 'joint': (cols, dec)})
        out['joint'] = {**C.gate(j['base'], j['joint']), 'cols': cols, 'decay': dec, 'with': C.summ(j['joint'])}
        # calibration of the joint model's top lean, held out
    for k, v in out.items(): print(k, {a: (round(b, 5) if isinstance(b, float) else b) for a, b in v.items() if a != 'byClass'}, v.get('byClass'))
    json.dump(out, open(os.path.join(HERE, 'commit_tests.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
