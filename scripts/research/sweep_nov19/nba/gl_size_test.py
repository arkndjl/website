# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 6a (PREREG.md): height, weight and a college flag in the G League call-up model's history features.

    python3 gl_size_test.py BIO_DIR     # -> impl/nba/gl_size.json

Rows and folds = gleague_callup.research (leave one season out, 2009-2025); NBA% log loss per row against the shipped
features, paired, clustered by season; tune seasons to 2017, held 2018-2025."""
import collections, json, os, sys
import numpy as np
import common as C
import gleague_callup as GC


def rows_():
    W = GC.World()
    seasons = {y: (GC.gl_season(y), [GC.gl_season(y, ('SC',))] if y >= 2022 else []) for y in range(2009, GC.LAST1 + 1)}
    births, nm = collections.defaultdict(list), {}
    for y, (full, scs) in seasons.items():
        for p, o in full.items():
            if o['n']: nm[p] = o['n']
            if o['age']: births[p].append(y - o['age'])
    for p, n in nm.items(): W.link(p, n, births[p])
    rows = []
    for y, (full, scs) in seasons.items():
        for part, src in [(0.0, full)] + [(1.0, s) for s in scs]:
            for p, o in src.items():
                o['n'] = o['n'] or nm.get(p)
                if (o['MIN'] or 0) < GC.MIN_ROW or not o['n']: continue
                f, t, info = W.row(y, o, part)
                rows.append((y, f, t, part, p))
    return rows


def main():
    rows = rows_()
    bio = {}
    for y in range(2009, 2026):
        fn = os.path.join(sys.argv[1], f'bio_{y}.json')
        d = json.load(open(fn))['resultSets'][0]; h = d['headers']
        for r in d['rowSet']:
            x = dict(zip(h, r))
            ht, wt = C.num(x['PLAYER_HEIGHT_INCHES']), C.num(x['PLAYER_WEIGHT'])
            col = x.get('COLLEGE'); us = 1.0 if col and col not in ('None', 'No College') and x.get('COUNTRY') == 'USA' else 0.0
            bio[(y, x['PLAYER_ID'])] = (ht if ht and ht > 60 else None, wt if wt and wt > 120 else None, 1.0 if col and col not in ('None', 'No College') else 0.0)
    got = 0
    for y in sorted({r[0] for r in rows}):
        rs = [r for r in rows if r[0] == y]
        hs = [bio[(y, r[4])][0] for r in rs if bio.get((y, r[4])) and bio[(y, r[4])][0]]
        ws = [bio[(y, r[4])][1] for r in rs if bio.get((y, r[4])) and bio[(y, r[4])][1]]
        mh, mw = float(np.mean(hs)) if hs else 78.0, float(np.mean(ws)) if ws else 210.0
        for r in rs:
            b = bio.get((y, r[4]))
            ok = bool(b and b[0] and b[1]); got += ok
            r[1].update({'ht': b[0] if ok else mh, 'wt': b[1] if ok else mw, 'col': b[2] if b else 0.0, 'bio_na': 0.0 if ok else 1.0})
    print('rows', len(rows), 'with bio', got, flush=True)
    NEW = GC.FEATS + ['ht', 'wt', 'col', 'bio_na']
    yrs = sorted({r[0] for r in rows})
    L = {'base': [], 'new': []}; Yr = []
    for s in yrs:
        tr = [r for r in rows if r[0] != s]; te = [r for r in rows if r[0] == s]
        y = np.array([r[2]['nba1'] for r in te])
        for nm, feats in (('base', GC.FEATS), ('new', NEW)):
            X, mu, sd = GC.design([r[1] for r in tr], feats)
            b = GC.logit_fit(X, np.array([r[2]['nba1'] for r in tr]))
            Xt, _, _ = GC.design([r[1] for r in te], feats, mu, sd)
            p = np.clip(GC.sig(GC.lin(b, Xt)), 1e-4, 1 - 1e-4)
            L[nm] += list(-(y * np.log(p) + (1 - y) * np.log(1 - p)))
        Yr += [s] * len(te)
    Yr = np.array(Yr); d = np.array(L['new']) - np.array(L['base'])
    res = {'n': len(d), 'withBio': got}
    for nm, k in (('tune', Yr <= 2017), ('held', Yr >= 2018), ('all', Yr > 0)):
        p = C.paired(d[k], Yr[k]); ss = sorted(set(Yr[k]))
        res[nm] = {'n': int(k.sum()), 'll0': round(float(np.array(L['base'])[k].mean()), 5), 'll1': round(float(np.array(L['new'])[k].mean()), 5),
                   'd': round(p['d'], 5), 't': round(p['t'], 2), 'seasonsLower': int(sum(d[Yr == s].mean() < 0 for s in ss)), 'seasons': len(ss)}
    X, mu, sd = GC.design([r[1] for r in rows], NEW)
    b = GC.logit_fit(X, np.array([r[2]['nba1'] for r in rows]))
    res['coef'] = dict(zip(['ht', 'wt', 'col', 'bio_na'], [round(float(v), 3) for v in b[1 + len(GC.FEATS):1 + len(NEW)]]))
    res['p'] = C.p2(res['held']['t']) if res['held']['t'] < 0 else 1.0
    res['pass_pre_holm'] = bool(res['held']['t'] <= -2 and res['tune']['d'] < 0 and res['held']['seasonsLower'] * 2 > res['held']['seasons'])
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(C.IMPL, 'gl_size.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
