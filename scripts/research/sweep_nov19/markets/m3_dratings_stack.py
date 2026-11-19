# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""M3: DRatings win chance stacked on the walk-forward game model (NHL, NBA).
    python3 m3_dratings_stack.py <nhl|nba> <dratings rows.jsonl> <out.json>
Join = ET day + final score. Tune seasons to 2023-24, held 2024-25 and 2025-26; log loss, clustered by day."""
import collections, datetime as dt, gzip, json, math, os, sys
import numpy as np
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')


def phi(x): return .5 * (1 + math.erf(x / math.sqrt(2)))
def lg(p): p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p / (1 - p))


def fit(X, y, l2=1e-6):
    b = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ b))
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.eye(X.shape[1])
        st = np.linalg.solve(H, X.T @ (y - p) - l2 * b)
        b += st
        if np.abs(st).max() < 1e-9: break
    return b


def main(sp, fn, outfn):
    W = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', sp + '.json.gz')))
    idx = collections.defaultdict(list)
    for g in W:
        if g['S'] < 2022 or g['S'] > 2026: continue
        if sp == 'nhl':
            if g.get('p') is None or g.get('hs') is None: continue
            idx[(g['day'], g['hs'], g['as'])].append((g['S'], g['p'], g['hs'] > g['as'], g['day']))
        else:
            if g.get('m') is None or g.get('res') is None or g.get('tot') is None: continue
            hs, as_ = int((g['tot'] + g['res']) / 2), int((g['tot'] - g['res']) / 2)
            d = (dt.datetime.fromisoformat(g['date'].replace('Z', '+00:00')) - dt.timedelta(hours=5)).date().isoformat()
            idx[(d, hs, as_)].append((g['S'], phi(g['m'] / 12.97), g['res'] > 0, d))
    R, seen, n_dr = [], set(), 0
    for l in open(fn):
        r = json.loads(l)
        n_dr += 1
        d = (dt.datetime.fromisoformat(r['t'].replace('Z', '+00:00')) - dt.timedelta(hours=5)).date().isoformat()
        c = idx.get((d, r['hs'], r['as']))
        if not c or len(c) != 1 or (d, r['hs'], r['as']) in seen: continue
        seen.add((d, r['hs'], r['as']))
        S, pm, y, day = c[0]
        if not (0 < r['ph'] < 1): continue
        R.append((S, lg(pm), lg(r['ph']), float(y), day))
    S = np.array([r[0] for r in R]); xm = np.array([r[1] for r in R]); xd = np.array([r[2] for r in R]); y = np.array([r[3] for r in R])
    days = [r[4] for r in R]
    tr, he = S <= 2024, S >= 2025
    one = np.ones(len(R))
    X0 = np.column_stack([one, xm]); X1 = np.column_stack([one, xm, xd])
    b0, b1 = fit(X0[tr], y[tr]), fit(X1[tr], y[tr])
    ll = lambda X, b: -(y * np.log(1 / (1 + np.exp(-X @ b))) + (1 - y) * np.log(1 - 1 / (1 + np.exp(-X @ b))))
    d = ll(X1, b1) - ll(X0, b0)                     # < 0: the stack is better
    def clt(mask):
        dd = d[mask]; n = len(dd); m = dd.mean()
        by = collections.defaultdict(float)
        for v, k in zip(dd, [days[i] for i in np.where(mask)[0]]): by[k] += v - m
        Gn = len(by); v = sum(s * s for s in by.values()) * Gn / (Gn - 1) / n / n
        return round(float(m), 5), round(float(m / math.sqrt(v)), 2), int(n)
    pd_ = 1 / (1 + np.exp(-xd)); pmo = 1 / (1 + np.exp(-xm))
    raw = lambda p, mask: round(float(-(y[mask] * np.log(p[mask]) + (1 - y[mask]) * np.log(1 - p[mask])).mean()), 4)
    out = {'sport': sp, 'dratings_rows': n_dr, 'joined': len(R), 'b_base': [round(float(v), 3) for v in b0],
           'b_stack': [round(float(v), 3) for v in b1], 'tune': clt(tr), 'held': clt(he),
           'held_2025': clt(S == 2025), 'held_2026': clt(S == 2026),
           'raw_ll_held': {'model': raw(pmo, he), 'dratings': raw(pd_, he)}}
    h = out['held']
    out['pass'] = bool(h[1] <= -2 and out['held_2025'][0] < 0 and out['held_2026'][0] < 0 and out['tune'][0] < 0)
    print(json.dumps(out, indent=1))
    json.dump(out, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    main(*sys.argv[1:4])
