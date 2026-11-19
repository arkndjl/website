# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""3Y projection candidates on the live form's harness (PREREG.md: cross-sport 2 cap share, 10a archetype aging).

    python3 proj_test.py cap             # H4 + rookie-scale flag, flag x -ln pick, ln cap share -> impl/nba/proj_cap.json
    python3 proj_test.py age TRACK_DIR   # H4 + (age - 27) x z for four skills, each alone  -> impl/nba/proj_age.json

Harness = scripts/nba_proj3y_star_research.py (leave one season out with a buffer, simulated partial seasons at each
season share f, same draws for every form). Tune S <= 2018, held S >= 2019; squared error on y1 and y3y, paired,
players as clusters (season-clustered t alongside)."""
import json, math, os, sys
import numpy as np
import common as C
import nba_proj3y_research as R
import nba_proj3y_star_research as SR

CAP = {2012: 58.044, 2013: 58.044, 2014: 58.679, 2015: 63.065, 2016: 70.0, 2017: 94.143, 2018: 99.093, 2019: 101.869,
       2020: 109.14, 2021: 109.14, 2022: 112.414, 2023: 123.655, 2024: 136.021, 2025: 140.588, 2026: 154.647, 2027: 165.0}
SAL = os.path.join(C.SCRIPTS, 'data', 'nba_salary_hist.json')
FLOOR = 0.0025


def cap_cols(rows):
    sal = json.load(open(SAL))
    dr = json.load(open(os.path.join(C.SCRIPTS, 'nba_draft.json')))
    pick = {r[1]: (int(y), r[0]) for y, L in dr.items() for r in L}
    out, miss = [], 0
    for r in rows:
        S, pid = r['S'], r['id']
        d = pick.get(pid)
        rk = 1.0 if d and d[1] <= 30 and 1 <= S - d[0] <= 4 else 0.0
        s = sal.get(str(S), {}).get(pid)
        miss += s is None
        share = max((s or 0) / 1e6 / CAP[S], FLOOR)
        out.append([rk, rk * -math.log(d[1]) if rk else 0.0, (1 - rk) * math.log(share)])
    print('salary missing', miss, 'of', len(rows), flush=True)
    return {'M': np.array(out)}


def age_cols(rows, folder):
    import pandas as pd
    by = {}
    for r in rows: by.setdefault(r['S'], []).append(r)
    sz = pd.read_csv(os.path.join(folder, 'shotzone.csv')); pa = pd.read_csv(os.path.join(folder, 'passing.csv'))
    tr = pd.read_csv(os.path.join(folder, 'tracking.csv')); tr = tr[tr.type == 'drives']
    val = {}
    for S, rs in by.items():
        if S < 2014: continue
        import nba_proj as P
        nm = {p['id']: p['n'] for p in P.load(S)['players']}
        find = C.matcher([(r['id'], nm.get(r['id'], r['id'])) for r in rs])
        a = sz[sz.year == S].groupby('EntityId').agg(nm=('Name', 'first'), ftp=('FtPoints', 'sum'), fta=('FTA', 'sum'), f2=('FG2A', 'sum'), f3=('FG3A', 'sum'),
                                                     m2=('FG2M', 'sum'), a3=('NonHeaveArc3FGM', 'sum'), c3=('Corner3FGM', 'sum'))
        b = pa[pa.year == S].groupby('nba_id').agg(ua=('UAFGM', 'sum'))
        c = tr[tr.year == S].groupby('PLAYER_ID').agg(dr=('DRIVES', 'sum'), mn=('MIN', 'sum'))
        for nid, x in a.iterrows():
            pid = find(str(x.nm))
            if not pid: continue
            fgm = x.m2 + x.a3 + x.c3
            v = {'ft': x.ftp / x.fta if x.fta >= 50 else None, 'tpr': x.f3 / (x.f2 + x.f3) if x.f2 + x.f3 >= 100 else None,
                 'drv': float(c.dr[nid] / c.mn[nid] * 36) if nid in c.index and c.mn[nid] >= 200 else None,
                 'self': float(b.ua[nid] / fgm) if nid in b.index and fgm >= 50 else None}
            val[(S, pid)] = v
    keys = ('ft', 'tpr', 'drv', 'self')
    Z = {k: np.zeros(len(rows)) for k in keys}
    for S, rs in by.items():
        for k in keys:
            ref = [val[(S, r['id'])][k] for r in rs if r['mp'] >= 500 and val.get((S, r['id']), {}).get(k) is not None]
            if len(ref) < 30: continue
            mu, sd = float(np.mean(ref)), float(np.std(ref))
            for i, r in enumerate(rows):
                if r['S'] == S:
                    v = val.get((S, r['id']), {}).get(k)
                    if v is not None: Z[k][i] = max(-3.0, min(3.0, (v - mu) / sd))
    age = np.array([r['age'] - 27 for r in rows], float)
    print('matched', {k: int((Z[k] != 0).sum()) for k in keys}, 'of', len(rows), flush=True)
    return {k: (age * Z[k])[:, None] for k in keys}


def run(rows, cols, fs, smin, out):
    rng = np.random.default_rng(20261103)
    res = {'cands': list(cols), 'grid': []}
    for f in R.FS:
        SR.inputs_with_mp(rows, f, rng)
        n, proj, prior, age, lm, M = R.inputs(rows, f, rng)
        if f not in fs: continue
        rep = lambda k: np.repeat(np.array([r[k] for r in rows], float), n)
        S, ids = rep('S'), np.repeat([r['id'] for r in rows], n)
        d1 = (rep('x1') + 2) * rep('m1') / (rep('m1') + 1000); d2 = (rep('x2') + 2) * rep('m2') / (rep('m2') + 1000)
        lc = np.log1p(SR.MPF[0] + rep('m1') + rep('m2'))
        X0 = SR.design('H4', proj, prior, age, lm, d1, d2, lc)
        Y = np.repeat(np.array([r['y'] for r in rows], float), n, axis=0)
        y3y = np.repeat(np.array([np.nan if r['y3y'] is None else r['y3y'] for r in rows]), n)
        g = {'f': f}
        for tn, T, buf, smax in (('y1', Y[:, 0], 1, 2025), ('y3y', y3y, 3, 2023)):
            ok = ~np.isnan(T) & (S <= smax) & (S >= smin)
            seas = sorted(set(S[ok].astype(int)))
            def loso(X):
                p = np.zeros_like(T)
                for c in seas:
                    tr = ok & (np.abs(S - c) > buf); te = ok & (S == c)
                    p[te] = X[te] @ np.linalg.lstsq(X[tr], T[tr], rcond=None)[0]
                return p
            p0 = loso(X0); e0 = (p0 - T) ** 2
            top = ok & (proj >= 4)
            o = {'n': int(ok.sum() // n), 'rmseH4': round(float(np.sqrt(e0[ok].mean())), 4),
                 'top4': {'actual': round(float(T[top].mean()), 3), 'H4': round(float(p0[top].mean()), 3)}}
            for k, col in cols.items():
                Xc = np.column_stack([X0, np.repeat(col, n, axis=0)])
                p1 = loso(Xc); d = (p1 - T) ** 2 - e0
                r = {'rmse': round(float(np.sqrt(((p1 - T) ** 2)[ok].mean())), 4), 'top4': round(float(p1[top].mean()), 3),
                     'coef': [round(float(v), 4) for v in np.linalg.lstsq(Xc[ok], T[ok], rcond=None)[0][X0.shape[1]:]]}
                for nm, msk in (('tune', ok & (S <= 2018)), ('held', ok & (S >= 2019))):
                    if not msk.any(): continue
                    hs = sorted(set(S[msk].astype(int)))
                    r[nm] = {'d': round(float(d[msk].mean()), 5), 't': round(R.tstat(d[msk], ids[msk]), 2), 'tSeason': round(C.paired(d[msk], S[msk])['t'], 2),
                             'seasonsLower': int(sum(d[msk & (S == c)].mean() < 0 for c in hs)), 'seasons': len(hs)}
                o[k] = r
            g[tn] = o
        res['grid'].append(g)
        print(json.dumps(g), flush=True)
    json.dump(res, open(out, 'w'), indent=1)
    return res


def main():
    rows = SR.add_history(R.load())
    if sys.argv[1] == 'cap':
        res = run(rows, cap_cols(rows), R.FS, 2012, os.path.join(C.IMPL, 'proj_cap.json'))
        G = {g['f']: g for g in res['grid']}
        key = all(G[f][tn]['M']['held']['t'] <= -2 and G[f][tn]['M']['tune']['d'] < 0 for f in (0.5, 1.0) for tn in ('y1', 'y3y'))
        maj = all(G[1.0][tn]['M']['held']['seasonsLower'] * 2 > G[1.0][tn]['M']['held']['seasons'] for tn in ('y1', 'y3y'))
        oth = all(G[f][tn]['M']['held']['t'] <= 0 for f in G for tn in ('y1', 'y3y'))
        res['verdict'] = {'key': key, 'majority': maj, 'otherF': oth, 'pass': bool(key and maj and oth)}
        print(res['verdict'])
        json.dump(res, open(os.path.join(C.IMPL, 'proj_cap.json'), 'w'), indent=1)
    else:
        rows = [r for r in rows]
        cols = age_cols(rows, sys.argv[2])
        res = run(rows, cols, (1.0,), 2014, os.path.join(C.IMPL, 'proj_age.json'))
        g = res['grid'][0]
        ps = {k: max(C.p2(g[tn][k]['held']['t']) if g[tn][k]['held']['t'] < 0 else 1.0 for tn in ('y1', 'y3y')) for k in cols}
        hp = C.holm(ps)
        res['verdict'] = {k: {'p': round(ps[k], 4), 'holm': round(hp[k], 4),
                              'pass': bool(all(g[tn][k]['held']['t'] <= -2 and g[tn][k]['tune']['d'] < 0 and g[tn][k]['held']['seasonsLower'] * 2 > g[tn][k]['held']['seasons']
                                               for tn in ('y1', 'y3y')) and hp[k] <= 0.05)} for k in cols}
        print(json.dumps(res['verdict']))
        json.dump(res, open(os.path.join(C.IMPL, 'proj_age.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
