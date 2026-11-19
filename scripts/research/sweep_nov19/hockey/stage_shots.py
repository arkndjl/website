# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Prospect stage terms from league shot tables: NCAA shots (ncaas) and pooled shots over league (pshots)
(pre-registered H3, H5). Board gate as scripts/hockey_fv_sweep2.py evalc, on top of each stage's live kept set.

usage: stage_shots.py <shots.json from shots_tables.py> <out.json>
"""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import hockey_prospects as H      # noqa: E402
import hockey_fv_drivers as HD    # noqa: E402
import hockey_fv_sweep2 as SW     # noqa: E402
import names as NM                # noqa: E402
import nhl_data as D              # noqa: E402

MINGP = {'NCAA': 15, 'SHL': 20, 'HockeyAllsvenskan': 20}
LG = {'SHL': 'SHL', 'HockeyAllsvenskan': 'HockeyAllsvenskan', 'Sweden': 'SHL', 'Sweden-2': 'HockeyAllsvenskan', 'Allsvenskan': 'HockeyAllsvenskan'}


def tables(T):
    """per league-season: position means among qualified skaters, sd of the centred value, and rows by name key"""
    out = {}
    for lg, d in T.items():
        for y, rows in d.items():
            q = [r for r in rows if r[2] >= MINGP[lg] and r[3] > 0]
            if len(q) < 50:
                continue
            norm = {p: float(np.mean([r[3] / r[2] for r in q if r[1] == p])) for p in ('F', 'D')}
            by = {}
            for r in q:
                by.setdefault((NM.key(r[0]), r[1]), []).append(r)
            out[(lg, int(y))] = {'norm': norm, 'by': by, 'rows': q}
    for lg in T:
        v = [r[3] / r[2] - t['norm'][r[1]] for (l, y), t in out.items() if l == lg for r in t['rows']]
        for (l, y), t in out.items():
            if l == lg:
                t['sd'] = float(np.std(v))
    return out


def lookup(tb, lg, y, r):
    t = tb.get((lg, y))
    if not t or r['G']:
        return None
    pos = 'D' if r['D'] else 'F'
    c = t['by'].get((NM.key(r['name']), pos), [])
    if len(c) != 1:
        c = [x for k, v in t['by'].items() if k[1] == pos for x in v if NM.same(x[0], r['name'])]
    if len(c) != 1:
        return None
    return (c[0][3] / c[0][2] - t['norm'][pos]), t['sd']


def main(shots, outp):
    tb = tables(json.load(open(shots)))
    W = H.war_tables()
    rows = H.read_rows(W); H.nhl_so_far(rows, W)
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr])
    fitd = json.load(open(H.FIT))
    F = [H.feats(r) for r in tr]
    babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
    S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
    _, p0 = H.score(F, y, cls, fitd['kept'])
    fv0 = {id(r): float(p) for r, p in zip(tr, p0)}
    A = json.load(__import__('gzip').open(H.AHL, 'rt'))
    ahl_sd = float(np.std([p[3] / p[2] - t['norm']['D' if False else 'F'] for t in A.values() for p in t['p'] if p[2] >= 20])) if A else 1.0
    res = {'ahlSd': round(ahl_sd, 3), 'leagueSd': {f'{k[0]}': round(v['sd'], 3) for k, v in tb.items()}}
    for k in range(1, 5):
        sub = [r for r in tr if r['year'] + k < D.current_season() and H.onboard(r, k)]
        yk = np.array([H.fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub]); pk = np.array([r['pick'] for r in sub])
        st = fitd['stages'][str(k)]
        kk = st['kept']
        Fk = [H.stage_feats(r, k, fv0[id(r)]) for r in sub]
        if 'comp' in kk:
            bc = kk[:kk.index('comp')]
            pool = H.comp_pool(Fk, yk - np.clip(H.loco(Fk, yk, ck, bc), 20, 80), [H.comp_grp(r) for r in sub], ck)
            for f, r, c in zip(Fk, sub, ck):
                f['comp'] = H.comp_of(pool, f, H.comp_grp(r), own=c)
        n = {'ncaa_line': 0, 'ncaa_join': 0, 'swe_line': 0, 'swe_join': 0}
        for f, r in zip(Fk, sub):
            q = r['post'].get(k)
            lg = (q or {}).get('lg')
            f['ncaas'] = 0.0; f['pshots'] = f['ahls'] if 'ahls' in f else 0.0
            if q and q.get('grp') == 'ncaa':
                n['ncaa_line'] += 1
                v = lookup(tb, 'NCAA', r['year'] + k, r)
                if v:
                    n['ncaa_join'] += 1
                    f['ncaas'] = v[0]; f['pshots'] = v[0] / v[1] * ahl_sd
            elif lg in LG and not r['G']:
                n['swe_line'] += 1
                v = lookup(tb, LG[lg], r['year'] + k, r)
                if v:
                    n['swe_join'] += 1
                    f['pshots'] = v[0] / v[1] * ahl_sd
        o = {'kept': kk, 'join': n, 'ncaas': SW.evalc(Fk, yk, ck, pk, kk, 'ncaas')}
        if 'ahls' in kk:
            base = [c for c in kk if c != 'ahls']
            o['pshots_swap'] = SW.evalc(Fk, yk, ck, pk, base, 'pshots')
            o['ahls_alone'] = SW.evalc(Fk, yk, ck, pk, base, 'ahls')
            s_a, _ = H.score(Fk, yk, ck, kk); s_p, _ = H.score(Fk, yk, ck, base + ['pshots'])
            d = s_a - s_p
            ca, cp = HD.checks(Fk, yk, ck, pk, kk), HD.checks(Fk, yk, ck, pk, base + ['pshots'])
            o['pshots_vs_ahls'] = {'gain': round(float(d.mean()), 3), 't': round(SW.tval(d), 2), 'wins': int((d > 0).sum()), 'of': len(d),
                                   **{'d' + a: round(cp[a] - ca[a], 4) for a in cp}}
        else:
            o['pshots'] = SW.evalc(Fk, yk, ck, pk, kk, 'pshots')
            o['ahls_alone'] = SW.evalc(Fk, yk, ck, pk, kk, 'ahls')
        res[str(k)] = o
        print(k, json.dumps(o), flush=True)
    json.dump(res, open(outp, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
