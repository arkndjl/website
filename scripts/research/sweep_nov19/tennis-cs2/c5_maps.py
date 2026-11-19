#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""C5: the map-win scale fit on Polymarket Map 1 closes instead of map outcomes.

    python3 c5_maps.py queue    # join Map 1 markets (volume >= 2,000) to bo3.gg first maps, queue their price paths
    python3 c5_maps.py          # the test (reads what the worker has pulled)
"""
import datetime as dt, json, math, os, sys
from collections import defaultdict
import numpy as np
from scipy import stats
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cs_maps, pm  # noqa: E402
from cs2_data import key  # noqa: E402
C0 = json.load(open(os.path.join(cs_maps.SCRIPTS, '..', 'data', 'cs2_scale_research.json')))['cFinal']
FLOOR, CAP = 2000, 1300


def join():
    first = defaultdict(list)
    for r in cs_maps.rows():
        if r['d'] >= '2025-08-30' and r['idx'] == 0 and r['n'] == 1:
            first[(r['d'], frozenset((key(r['a']), key(r['b']))))].append(r)
    out = []
    for line in open(os.path.join(pm.CACHE, 'list_cs2.jsonl')):
        e = json.loads(line)
        for m in e['m']:
            if m['smt'] != 'child_moneyline' or (m['g'] or '') != 'Map 1 Winner' or (m['vol'] or 0) < FLOOR or not m['t0']: continue
            o = json.loads(m['o']); t0 = pm.ts(m['t0'])
            if len(o) != 2: continue
            hit = None
            for dd in (0, -1, 1):
                c = first.get(((t0.date() + dt.timedelta(days=dd)).isoformat(), frozenset((key(o[0]), key(o[1])))))
                if c: hit = c[0]; break
            if not hit: continue
            out.append({'tok': json.loads(m['tok'])[0], 't0': t0.timestamp(), 'vol': m['vol'], 'row': hit,
                        'flip': key(o[0]) != key(hit['a']), 'res': m['res']})
    seen, uniq = set(), []
    for j in sorted(out, key=lambda j: -j['vol']):
        if j['row']['gid'] in seen: continue
        seen.add(j['row']['gid']); uniq.append(j)
    return uniq


def tclust(d, g):
    s = defaultdict(float)
    for v, k in zip(d, g): s[k] += v
    a = np.array(list(s.values())); t = a.sum() / (a.std(ddof=1) * len(a) ** .5)
    return {'n': int(len(d)), 'd': round(float(np.mean(d)), 5), 't': round(float(t), 2), 'p1': float(stats.t.cdf(t, len(a) - 1))}


def main():
    J = join()[:CAP]
    H = pm.load_hist()
    R = []
    for j in J:
        h = H.get((j['tok'], 'map1'))
        if h is None: continue
        def at(lead):
            v = [p for t, p in h if t <= j['t0'] - lead and .02 < p < .98]
            return v[-1] if v else None
        c60, c10 = at(3600), at(600)
        if c60 is None: continue
        r = j['row']; f = -1 if j['flip'] else 1
        R.append({'d': r['d'], 'z': r['z'], 'y': r['ya'], 'p60': c60 if f == 1 else 1 - c60,
                  'p10': None if c10 is None else (c10 if f == 1 else 1 - c10), 'vol': j['vol']})
    z = np.array([r['z'] for r in R]); y = np.array([r['y'] for r in R], float); p = np.array([r['p60'] for r in R])
    day = np.array([r['d'] for r in R]); mon = np.array([r['d'][:7] for r in R])
    tune, held = day <= '2026-04-30', day >= '2026-05-01'
    c1 = 1.0
    for _ in range(40):                       # cross-entropy of sig(c z) against the tune closes
        q = 1 / (1 + np.exp(-c1 * z[tune])); g = float(z[tune] @ (q - p[tune])); h = float((z[tune] ** 2) @ (q * (1 - q))) + 1e-9
        c1 -= g / h
    ll = lambda q: -(y * np.log(q) + (1 - y) * np.log(1 - q))  # noqa: E731
    l0, l1, lp = ll(1 / (1 + np.exp(-C0 * z))), ll(1 / (1 + np.exp(-c1 * z))), ll(p)
    d = l1 - l0
    months = sorted(set(mon[held]))
    nb = sum(d[held & (mon == m)].mean() < 0 for m in months)
    ok10 = np.array([r['p10'] is not None for r in R])
    p10 = np.array([r['p10'] if r['p10'] is not None else .5 for r in R])
    out = {'joined_markets': len(J), 'with_close': len(R), 'n_tune': int(tune.sum()), 'n_held': int(held.sum()), 'c0': C0, 'c1': round(c1, 3),
           'tune': tclust(d[tune], day[tune]), 'held': tclust(d[held], day[held]), 'months_better': f'{nb}/{len(months)}',
           'll_held': {'live_scale': round(float(l0[held].mean()), 4), 'price_scale': round(float(l1[held].mean()), 4),
                       'close_1h': round(float(lp[held].mean()), 4)},
           'model_vs_close_1h_held': tclust((l0 - lp)[held], day[held]),
           'model_vs_close_10m_held': tclust((l0 - ll(p10))[held & ok10], day[held & ok10]),
           'll_close_10m_held': round(float(ll(p10)[held & ok10].mean()), 4), 'min_volume': round(min(r['vol'] for r in R))}
    out['pass'] = bool(out['held']['t'] <= -2 and out['tune']['d'] < 0 and nb > len(months) / 2)
    print(json.dumps(out, indent=1))
    for q in (HERE, '/mnt/project-files/research-sweep-nov19/impl/tennis-cs2/'):
        json.dump(out, open(os.path.join(q, 'c5_results.json'), 'w'), indent=1)


if __name__ == '__main__':
    if 'queue' in sys.argv[1:]:
        J = join(); print('joined Map 1 markets', len(J), 'queued', min(len(J), CAP), 'volume floor of the queue', round(J[:CAP][-1]['vol']))
        new = [{'tok': j['tok'], 'a': j['t0'] - 26 * 3600, 'b': j['t0'], 'f': 10, 'k': 'map1'} for j in J[:CAP]]
        p = os.path.join(pm.CACHE, 'queue.jsonl')
        old = [json.loads(x) for x in open(p)]
        # the map markets go in after every 3rd tennis row so all three pulls advance together
        other = [x for x in old if x.get('k') != 'map1']; q = []; it = iter(new)
        for i, x in enumerate(other):
            q.append(x)
            if i % 3 == 2:
                n = next(it, None)
                if n: q.append(n)
        q += list(it)
        with open(p, 'w') as f:
            for x in q: f.write(json.dumps(x) + '\n')
    else:
        main()
