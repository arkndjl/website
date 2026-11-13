#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The injury term's value of a missing player: last season's GAR a 90 (live) against two seasons pooled, his
Transfermarkt value the July before (mapped to GAR a 90 on 2015-22 regulars), and blends. Each variant rebuilds avz
on every scored row; the weight av is retuned on 2013-22 for each, then compared with the live term."""
import json
import math
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine as E
import soccer_data as D
import soccer_games as G
import soccer_tm_injuries as TI

OUT = os.environ.get('INJ_PKL', os.path.join(HERE, 'inj_rows.pkl'))


def tables():
    F = json.load(open(os.path.join(G.ROOT, 'data', 'soccer_war_fit.json')))
    dl = {k: F['repl'][k] - F['replFringe'][k] for k in F['repl']}
    gar, mn = {}, {}
    for S in range(2015, 2028):
        try:
            ps = json.load(open(os.path.join(TI.WARD, f'{S}.json')))['players']
        except OSError:
            continue
        rows = sorted(((x['gar'] + dl.get(x['pos'], 0.0) * x['min'] / 90, x) for x in ps), key=lambda t: -t[0])
        gar[S] = {x['p']: x['gar90'] + dl.get(x['pos'], 0.0) for _, x in rows}
        mn[S] = {}
        for _, x in rows:
            mn[S][x['p']] = mn[S].get(x['p'], 0) + x['min']
    mvh = D.load(os.path.join(G.HERE, 'data', 'soccer_mv_hist.json.gz'))['h']
    mv = {int(S): {p: v[1] for p, v in d.items() if v[1]} for S, d in mvh.items()}
    # log value -> GAR a 90: regulars (900+ minutes) of 2016-22, value the July before
    xs, ys = [], []
    for S in range(2016, 2023):
        for p, g in gar.get(S, {}).items():
            if mn[S].get(p, 0) >= 900 and mv.get(S - 1, {}).get(p):
                xs.append(math.log(mv[S - 1][p])); ys.append(g)
    b, a = np.polyfit(xs, ys, 1)
    print('GAR a 90 = %.4f + %.4f log value (n %d, r %.2f)' % (a, b, len(xs), np.corrcoef(xs, ys)[0, 1]), flush=True)
    return gar, mn, mv, a, b


def variants():
    gar, mn, mv, a, b = tables()
    V0 = TI.V0

    def live(S, p):
        return gar.get(S, {}).get(p, V0)

    def pooled(S, p):
        n1, n2 = mn.get(S, {}).get(p, 0), mn.get(S - 1, {}).get(p, 0)
        if n1 + n2 == 0:
            return V0
        return (n1 * gar.get(S, {}).get(p, 0.0) + 0.5 * n2 * gar.get(S - 1, {}).get(p, 0.0)) / (n1 + 0.5 * n2)

    def value(S, p):
        m = mv.get(S, {}).get(p)
        return a + b * math.log(m) if m else live(S, p)

    def blend(S, p):
        return 0.5 * live(S, p) + 0.5 * value(S, p)
    return {'live': live, 'pooled': pooled, 'value': value, 'blend': blend}


if __name__ == '__main__':
    rows = E.load_rows()
    P = G.params()
    if os.path.exists(OUT):
        AV = pickle.load(open(OUT, 'rb'))
    else:
        AV = {}
        for nm, v in variants().items():
            TI.value_table = lambda v=v: v
            TI.add_avz(rows)
            AV[nm] = {r['id']: r.get('avz', 0.0) for r in rows if r.get('avz')}
            print(nm, len(AV[nm]), flush=True)
        pickle.dump(AV, open(OUT, 'wb'))

    def put(nm):
        for r in rows:
            if 'avz' in r:
                r['avz'] = AV[nm].get(r['id'], 0.0)

    def per(Q, lo, hi):
        out = {}

        def score(r, S, lh, la, R):
            if lo <= S <= hi:
                p = G.wdl(lh, la, Q['rho'])
                out[r['id']] = (r['day'], -math.log(max(1e-9, (p[2], p[1], p[0])[G.res90(r) + 1])))
        G.run(rows, Q, score, et=True)
        return out
    lo, hi = (2023, 2026) if '--held' in sys.argv else (2013, 2022)
    put('live')
    base = per(P, lo, hi)
    print('live', round(sum(v[1] for v in base.values()) / len(base), 5), len(base))
    for nm in ('pooled', 'value', 'blend'):
        put(nm)
        for av in ((0.35,) if '--held' in sys.argv else (0.25, 0.35, 0.5)):
            o = per(dict(P, av=av), lo, hi)
            d = [o[i][1] - base[i][1] for i in base]
            print(nm, 'av', av, 'd', round(sum(d) / len(d), 6), 't', G.cl_t(d, [base[i][0] for i in base]), flush=True)
