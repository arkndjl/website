#!/usr/bin/env python3
"""Agency tendency scores (Nov 28 2026): which per-client measures say something about the agency, not the client?

Each candidate is a per-client residual against every board player like him. An agency score is only worth showing if it
replicates on clients not used to compute it, so the test is split-half: each agency's clients are halved at random, the
two half-means are correlated across agencies (agencies with 2+ clients, weighted by size), averaged over 400 splits.
The null shuffles the residuals across all represented clients (agency sizes kept), 300 times. Ship at p < .05.

  python3 scripts/research/agencies_nov28/tendency.py     -> research/agency_tendency.json
"""
import json, math, os, random, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import agencies as A, names  # noqa: E402

P4 = {'cfb': {'SEC', 'Big Ten', 'Big 12', 'ACC'}, 'cbb': {'SEC', 'B10', 'B12', 'ACC', 'BE'}}
INDEP_P4 = {'Notre Dame'}


def board(sp):
    if sp == 'cfb':
        a = A.load('static/data/cfb-all.json'); I = {k: i for i, k in enumerate(a['cols'])}
        past = A.load('static/data/cfb-past.json')['players']
        hs = (A.load('data/arkstars_hs.json', {}).get('cfb') or {}).get('by', {})
        out = []
        for r in a['rows']:
            g = lambda k: r[I[k]]
            if g('fv') is None: continue
            pr = {s[0]: s for s in past.get('%s|%s' % (g('name'), g('team')), [])}.get(2025)
            out.append(dict(name=g('name'), team=g('team'), pos=g('pos'), cls=g('cls'), fv=g('fv'), z=g('znil'), conf=g('conf'),
                            ark=hs.get('%s|%s' % (g('name'), g('team'))), fvp=pr[4] if pr else None, teamp=pr[3] if pr else None))
        return out
    a = A.load('static/data/cbb-all.json'); I = {k: i for i, k in enumerate(a['cols'])}
    m = {(r['name'], r['team']): r for r in A.load('data/cbb_market.json')['nil']}
    hs = (A.load('data/arkstars_hs.json', {}).get('cbb') or {}).get('by', {})
    out = []
    for r in a['rows']:
        g = lambda k: r[I[k]]
        if g('fv') is None: continue
        out.append(dict(name=g('name'), team=g('team'), pos=g('pos'), cls=g('cls'), fv=g('fv'), z=(m.get((g('name'), g('team'))) or {}).get('z'),
                        conf=g('conf'), ark=hs.get('%s|%s' % (g('name'), g('team'))), fvp=g('fv0'), teamp=None))
    return out


def binmean(rows, val, keyf):
    """mean of val by key cell, falling back to the overall mean in a thin cell (under 15 players)"""
    cell = defaultdict(list)
    for r in rows:
        v = val(r)
        if v is not None: cell[keyf(r)].append(v)
    allv = [v for l in cell.values() for v in l]; mu = sum(allv) / len(allv) if allv else 0.0
    return lambda r: (sum(cell[keyf(r)]) / len(cell[keyf(r)])) if len(cell.get(keyf(r), [])) >= 15 else mu


def metrics(sp, pool, rec_pool):
    fb = lambda v: int((v or 0) // 5)
    p4 = lambda r: 1.0 if (r['conf'] in P4[sp] or r['team'] in INDEP_P4) else 0.0
    zs = sorted(r['z'] for r in pool if r['z'] is not None); sd_z = (sum(v * v for v in zs) / len(zs) - (sum(zs) / len(zs)) ** 2) ** .5
    lo, hi = zs[int(.01 * len(zs))], zs[int(.99 * len(zs)) - 1]
    grow = binmean(pool, lambda r: None if r['fvp'] is None else r['fv'] - r['fvp'], lambda r: (fb(r['fvp']), r['cls']))
    reach = binmean(pool, p4, lambda r: (fb(r['fv']), r['pos']))
    brk = binmean([r for r in pool if r['ark']], lambda r: r['fv'], lambda r: (round(r['ark'] * 2), r['cls']))
    stay = binmean([r for r in pool if r['teamp']], lambda r: 1.0 if names.same_team(r['team'], r['teamp']) else 0.0, lambda r: (fb(r['fvp']), r['cls']))
    rmu = sum(r['ark'] for r in rec_pool if r.get('ark')) / max(1, sum(1 for r in rec_pool if r.get('ark')))
    return {
        'Deal': lambda c, b: None if c['kind'] != 'college' or c['z'] is None or c['conf'] == 'low' else -max(lo, min(hi, c['z'])) / sd_z,
        'Situation': lambda c, b: None if b is None or b['fvp'] is None else (b['fv'] - b['fvp']) - grow(b),
        'Reach': lambda c, b: None if b is None else p4(b) - reach(b),
        'Breakout': lambda c, b: None if b is None or not b['ark'] else b['fv'] - brk(b),
        'Stability': lambda c, b: None if b is None or not b['teamp'] else (1.0 if names.same_team(b['team'], b['teamp']) else 0.0) - stay(b),
        'Recruit': lambda c, b: None if c['kind'] != 'recruit' or not c.get('ark') else c['ark'] - rmu,
    }


def corr(a, b, w):
    sw = sum(w); ma = sum(x * y for x, y in zip(a, w)) / sw; mb = sum(x * y for x, y in zip(b, w)) / sw
    va = sum(y * (x - ma) ** 2 for x, y in zip(a, w)); vb = sum(y * (x - mb) ** 2 for x, y in zip(b, w))
    if va <= 0 or vb <= 0: return 0.0
    return sum(y * (x - ma) * (z - mb) for x, z, y in zip(a, b, w)) / (va * vb) ** .5


def split_half(groups, R, rnd):
    gs = [g for g in groups if len(g) >= 2]
    if len(gs) < 4: return None
    tot = 0.0
    for _ in range(R):
        A1, B1, W = [], [], []
        for g in gs:
            h = g[:]; rnd.shuffle(h); m = len(h) // 2
            A1.append(sum(h[:m]) / m); B1.append(sum(h[m:]) / (len(h) - m)); W.append(len(h))
        tot += corr(A1, B1, W)
    return tot / R


def test(groups, rnd):
    w = test1(groups, rnd)
    if w is None: return None
    global corr
    keep = corr; corr = lambda a, b, ww: keep(a, b, [1] * len(ww))
    try: u = test1(groups, rnd)
    finally: corr = keep
    w.update(rU=u['r'], tU=u['t'], pU=u['p'], ship=w['p'] < .05 and u['p'] < .05)
    return w


def test1(groups, rnd):
    obs = split_half(groups, 400, rnd)
    if obs is None: return None
    sizes = [len(g) for g in groups]; flat = [v for g in groups for v in g]; null = []
    for _ in range(300):
        rnd.shuffle(flat); it = iter(flat)
        null.append(split_half([[next(it) for _ in range(n)] for n in sizes], 20, rnd))
    mu = sum(null) / len(null); sd = (sum((x - mu) ** 2 for x in null) / len(null)) ** .5
    return dict(r=round(obs, 3), null=round(mu, 3), t=round((obs - mu) / sd, 2) if sd else None,
                p=round(sum(1 for x in null if x >= obs) / len(null), 3), agencies=sum(1 for g in groups if len(g) >= 2), clients=len(flat))


def main():
    rnd = random.Random(11)
    led = A.load('data/agencies.json')['rows']
    res = {}
    for sp, col, rec in (('cfb', A.cfb_rows(), A.cfb_recruits()), ('cbb', A.cbb_rows(), A.cbb_recruits())):
        pool = board(sp); idx = {(r['name'], r['team']): r for r in pool}
        clients, _ = A.join(led, sp, col, rec)
        M = metrics(sp, pool, rec)
        T = A.tendencies(col)
        M['Deal'] = lambda c, b: T['Deal'](c)
        M['Breakout'] = lambda c, b: T['Breakout'](c)
        res[sp] = {}
        for name, f in M.items():
            by = defaultdict(list)
            for c in clients:
                if c['agency'] in A.SPECIAL: continue
                v = f(c, idx.get((c['name'], c['team'])) if c['kind'] == 'college' else None)
                if v is not None: by[c['agency']].append(v)
            res[sp][name] = test(list(by.values()), rnd)
            print(sp, name, res[sp][name])
    json.dump(res, open(os.path.join(ROOT, 'research', 'agency_tendency.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
