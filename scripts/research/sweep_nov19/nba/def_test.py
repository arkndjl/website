# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Leads 2 and 3 (PREREG.md): a hustle index and matchup points-allowed-over-expected as additions to D-XPM, on the
XPM test's team-season frame.

    python3 def_test.py HUSTLE.csv MATCHUP_DIR   # -> impl/nba/def_test.json

Team-season t: D_pred = a + b x sum(share x dval(t-1)) [+ c x sum(share x extra(t-1))], coefficients fit on seasons
before t; net error = (O_pred - D_pred) - net_rtg with the same O side in both. Scored t 2021-2026 (tune 2021-22,
held 2023-26), paired squared error clustered by season."""
import json, math, os, sys
import numpy as np
import pandas as pd
import common as C

K = 600.0
ZC = ['DEFLECTIONS', 'CONTESTED_SHOTS', 'CHARGES_DRAWN', 'DEF_BOXOUTS', 'DEF_LOOSE_BALLS_RECOVERED']


def grp(pos):
    p = (pos or '').upper()
    return 'C' if p.startswith('C') else 'G' if p in ('PG', 'SG', 'G') or p.startswith(('PG', 'SG')) else 'F'


def hustle(fn, st):
    """{(season, bbref pid): (raw index, minutes)}: mean of five within-position z-scores of per-36 hustle counts"""
    H = pd.read_csv(fn)
    H = H[H.year <= 2026]
    out = {}
    pos = {}
    for y, pid, tm, mp, ps, aw, nm in st: pos[(y, pid)] = grp(ps)
    for y, d in H.groupby('year'):
        find = C.matcher([(pid, nm) for (yy, pid, tm, mp, ps, aw, nm) in st if yy == y])
        d = d.groupby('PLAYER_ID').agg({**{c: 'sum' for c in ZC}, 'MIN': 'sum', 'PLAYER_NAME': 'first'}).reset_index()
        d = d[d.MIN > 0]
        d['pid'] = [find(n) for n in d.PLAYER_NAME]
        d = d[d.pid.notna()].copy()
        d['g'] = [pos.get((y, p), 'F') for p in d.pid]
        z = np.zeros(len(d))
        for c in ZC:
            r = d[c] / d.MIN * 36
            for g in 'GFC':
                k = (d.g == g).values; ref = k & (d.MIN >= 300).values
                if ref.sum() < 10: continue
                z[k] += ((r[k] - r[ref].mean()) / r[ref].std()).values / len(ZC)
        for p, v, m in zip(d.pid, z, d.MIN): out[(int(y), p)] = (float(np.clip(v, -4, 4)), float(m))
    return out


def matchups(folder, st):
    """{(season, bbref pid): (PAOE per 100, poss, matchup difficulty)} and the odd/even reliability"""
    out, rel = {}, []
    for y in range(2018, 2027):
        fn = os.path.join(folder, f'matchups_{y - 1}.csv')
        if not os.path.exists(fn): continue
        d = pd.read_csv(fn, usecols=['game_id', 'person_id', 'matchups_person_id', 'matchups_first_name', 'matchups_family_name', 'partial_possessions', 'player_points'])
        d = d[d.partial_possessions > 0]
        off = d.groupby('person_id').agg(p=('player_points', 'sum'), n=('partial_possessions', 'sum'))
        lg = off.p.sum() / off.n.sum()
        rate = (off.p + lg * 100) / (off.n + 100)                      # the offensive player's points per matchup possession
        d['exp'] = d.partial_possessions * d.person_id.map(rate)
        d['odd'] = d.game_id % 2
        d['nm'] = d.matchups_first_name.fillna('') + ' ' + d.matchups_family_name.fillna('')
        a = d.groupby('matchups_person_id').agg(p=('player_points', 'sum'), e=('exp', 'sum'), n=('partial_possessions', 'sum'), nm=('nm', 'first'))
        h = d.groupby(['matchups_person_id', 'odd']).agg(p=('player_points', 'sum'), e=('exp', 'sum'), n=('partial_possessions', 'sum')).unstack()
        big = a.index[a.n >= 1000]
        r0 = ((h['p'][0] - h['e'][0]) / h['n'][0] * 100).reindex(big); r1 = ((h['p'][1] - h['e'][1]) / h['n'][1] * 100).reindex(big)
        ok = r0.notna() & r1.notna()
        rel.append((y, float(np.corrcoef(r0[ok], r1[ok])[0, 1]), int(ok.sum())))
        find = C.matcher([(pid, nm) for (yy, pid, tm, mp, ps, aw, nm) in st if yy == y])
        for nid, r in a.iterrows():
            pid = find(r.nm.strip())
            if pid: out[(y, pid)] = (float((r.p - r.e) / r.n * 100), float(r.n), float(r.e / r.n * 100))
    return out, rel


def main():
    ps, tm, st = C.frame()
    hu = hustle(sys.argv[1], st)
    mu, rel = matchups(sys.argv[2], st)
    rbar = float(np.mean([r for _, r, _ in rel]))
    print('matchup PAOE odd/even r by season', [(y, round(r, 3), n) for y, r, n in rel], 'mean', round(rbar, 3), flush=True)
    dv = {}
    for (y, pid), r in ps.items():
        mp, d, o = C.num(r['mp']) or 0.0, C.num(r['dblend']), C.num(r['oblend'])
        if d is None or o is None: continue
        w = mp / (mp + K)
        dv[(y, pid)] = (-0.5 + (d + 0.5) * w, -0.5 + (o + 0.5) * w, d, mp)
    # residualise the extras on raw D-XPM per training window, then shrink by minutes (hustle) / possessions (matchups)
    def resid(src, upto, kk, sign):
        ks = [k for k in src if k[0] < upto and k in dv and src[k][1] >= 300]
        if len(ks) < 50: return {}
        x = np.array([dv[k][2] for k in ks]); v = np.array([src[k][0] for k in ks])
        b = np.polyfit(x, v, 1)
        return {k: sign * (src[k][0] - (b[0] * dv[k][2] + b[1] if k in dv else 0.0)) * src[k][1] / (src[k][1] + kk) for k in src if k[0] < upto}
    rows = []
    for (y, t), T in sorted(tm.items()):
        if y < 2019 or y > 2026: continue
        mem = [(pid, mp) for (yy, pid, tt, mp, *_ ) in st if yy == y and tt == t and mp > 0]
        tot = sum(m for _, m in mem)
        if tot <= 0: continue
        hr, mr = resid(hu, y, K, 1.0), resid(mu, y, 300.0, -1.0)
        sd = so = sh = sm = 0.0
        for pid, m in mem:
            s = 5 * m / tot
            d, o = dv.get((y - 1, pid), (-0.5, -0.5))[:2]
            sd += s * d; so += s * o
            sh += s * hr.get((y - 1, pid), 0.0); sm += s * mr.get((y - 1, pid), 0.0)
        rows.append((y, t, sd, so, sh, sm, float(T['off_rtg']), float(T['def_rtg']), float(T['net_rtg'])))
    A = np.array([r[2:] for r in rows], float); Y = np.array([r[0] for r in rows])
    lgo = {y: A[Y == y][:, 4].mean() for y in set(Y)}
    O = A[:, 4] - np.array([lgo[y] for y in Y]); D = -(A[:, 5] - np.array([lgo[y] for y in Y])); NET = A[:, 6]
    pred = {k: np.full(len(Y), np.nan) for k in ('base', 'hustle', 'paoe')}
    predD = {k: np.full(len(Y), np.nan) for k in pred}
    for y in range(2021, 2027):
        tr, te = Y < y, Y == y
        one = np.ones(len(Y))
        bo = np.linalg.lstsq(np.column_stack([one, A[:, 1]])[tr], O[tr], rcond=None)[0]
        op = np.column_stack([one, A[:, 1]])[te] @ bo
        for k, cols in (('base', [0]), ('hustle', [0, 2]), ('paoe', [0, 3])):
            X = np.column_stack([one] + [A[:, c] for c in cols])
            b = np.linalg.lstsq(X[tr], D[tr], rcond=None)[0]
            predD[k][te] = X[te] @ b
            pred[k][te] = op + predD[k][te]
    res = {'matchupReliability': {'bySeason': rel, 'mean': rbar, 'gate': rbar >= 0.3}, 'n': {}}
    tune, held = np.isin(Y, (2021, 2022)), Y >= 2023
    for k in ('hustle', 'paoe'):
        r = {}
        for nm, msk in (('tune', tune), ('held', held)):
            dn = (pred[k] - NET) ** 2 - (pred['base'] - NET) ** 2
            dd = (predD[k] - D) ** 2 - (predD['base'] - D) ** 2
            pn, pd_ = C.paired(dn[msk], Y[msk]), C.paired(dd[msk], Y[msk])
            r[nm] = {'n': int(msk.sum()), 'rmseNetBase': round(float(np.sqrt(((pred['base'] - NET)[msk] ** 2).mean())), 4),
                     'rmseNet': round(float(np.sqrt(((pred[k] - NET)[msk] ** 2).mean())), 4), 'dNet': round(pn['d'], 4), 'tNet': round(pn['t'], 2),
                     'rmseDBase': round(float(np.sqrt(((predD['base'] - D)[msk] ** 2).mean())), 4), 'rmseD': round(float(np.sqrt(((predD[k] - D)[msk] ** 2).mean())), 4),
                     'tD': round(pd_['t'], 2),
                     'seasonsLower': int(sum(dn[Y == y].mean() < 0 for y in sorted(set(Y[msk])))), 'seasons': int(len(set(Y[msk])))}
        r['p'] = C.p2(r['held']['tNet']) if r['held']['tNet'] < 0 else 1.0
        res[k] = r
    hp = C.holm({k: res[k]['p'] for k in ('hustle', 'paoe')})
    for k in ('hustle', 'paoe'):
        r = res[k]; r['holm'] = round(hp[k], 4)
        r['pass'] = bool(r['held']['tNet'] <= -2 and r['tune']['dNet'] < 0 and r['held']['seasonsLower'] * 2 > r['held']['seasons'] and hp[k] <= 0.05
                         and (k != 'paoe' or rbar >= 0.3))
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(C.IMPL, 'def_test.json'), 'w'), indent=1)
    # the display metric's past-season table source (not a test): top matchup difficulty 2026
    json.dump({f'{y}|{p}': [round(v[0], 2), round(v[1]), round(v[2], 1)] for (y, p), v in mu.items() if v[1] >= 1000},
              open(os.path.join(C.SCR, 'matchup_metrics.json'), 'w'))


if __name__ == '__main__':
    main()
