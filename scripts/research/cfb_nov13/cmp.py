# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Paired comparison of two CFB walk-forward files (base, candidate): abs error and log loss on who won, t clustered
by game day; tune 2017-20, held 2021-26 (2026 weeks 1-10; week 11 on is the lockbox and is dropped)."""
import gzip, json, sys, math
import numpy as np
def load(p):
    return {r['id']: r for r in json.load(gzip.open(p)) if not (r['S'] == 2026 and r['wk'] >= 11)}
def ct(d, cl):
    d = np.asarray(d, float); n = len(d)
    if n < 5: return 0.0, 0.0
    by = {}
    for x, c in zip(d - 0, cl): by.setdefault(c, []).append(x)
    s = np.array([sum(v) for v in by.values()]); G = len(s)
    se = math.sqrt(G / (G - 1) * (s ** 2).sum()) / n if G > 1 else 1
    return d.mean(), d.mean() / se if se else 0
phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
def ll(m, s, res):
    p = min(1 - 1e-9, max(1e-9, phi(m / s))); y = 1 if res > 0 else 0 if res < 0 else .5
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))
def tot(r): return r.get('tm') if r.get('tm') is not None else r.get('tm1')
def main(a, b, label=''):
    A, B = load(a), load(b); ids = [i for i in A if i in B]
    segs = {'all': lambda r: True, 'fcs': lambda r: r['fcs'], 'nonfcs': lambda r: not r['fcs'], 'wk1': lambda r: r['wk'] == 1, 'wk1-3': lambda r: r['wk'] <= 3, 'wk4+': lambda r: r['wk'] >= 4}
    splits = {'tune 17-20': (2017, 2020), 'held 21-26': (2021, 2026), 'full': (2017, 2026)}
    out = {}
    print(f'== {label} {b}  n {len(ids)}')
    for sn, f in segs.items():
        line = f'{sn:7s}'
        for pn, (lo, hi) in splits.items():
            I = [i for i in ids if lo <= A[i]['S'] <= hi and f(A[i])]
            if len(I) < 20: line += f' | {pn} n {len(I)}'; continue
            day = [A[i]['date'][:10] for i in I]
            dae = [abs(B[i]['res'] - B[i]['m']) - abs(A[i]['res'] - A[i]['m']) for i in I]
            dll = [ll(B[i]['m'], B[i]['sigma'], B[i]['res']) - ll(A[i]['m'], A[i]['sigma'], A[i]['res']) for i in I]
            m, t = ct(dae, day); m2, t2 = ct(dll, day)
            gapA = np.mean([abs(A[i]['res'] - A[i]['m']) - abs(A[i]['res'] - A[i]['L']) for i in I])
            line += f' | {pn} n {len(I)} dMAE {m:+.3f} t {t:+.2f} dLL {m2:+.4f} t {t2:+.2f} (gap {gapA:+.2f})'
            out[(sn, pn)] = (len(I), m, t, m2, t2)
        print(line)
    # totals
    for sn in ('all', 'fcs', 'wk1'):
        line = f'tot {sn:4s}'
        for pn, (lo, hi) in splits.items():
            I = [i for i in ids if lo <= A[i]['S'] <= hi and segs[sn](A[i]) and tot(A[i]) is not None and tot(B[i]) is not None and A[i].get('tot') is not None]
            if len(I) < 20: continue
            d = [abs(B[i]['tot'] - tot(B[i])) - abs(A[i]['tot'] - tot(A[i])) for i in I]
            m, t = ct(d, [A[i]['date'][:10] for i in I]); line += f' | {pn} n {len(I)} dMAE {m:+.3f} t {t:+.2f}'
            out[('tot' + sn, pn)] = (len(I), m, t)
        print(line)
    # by season
    print('  by season dMAE:', ' '.join(f"{S}:{np.mean([abs(B[i]['res'] - B[i]['m']) - abs(A[i]['res'] - A[i]['m']) for i in ids if A[i]['S'] == S]):+.3f}" for S in range(2017, 2027)))
    return out
if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else '')
