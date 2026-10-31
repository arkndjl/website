#!/usr/bin/env python3
"""Soccer academy and feeder leagues as FV drivers (Noah, Oct 31 2026): youth leagues (UEFA Youth League, U18 Premier
League, Primavera, French/Turkish/Danish/Dutch U19, Liga Revelacao U23, Swiss U21, plus Premier League 2 already on the
board) and the senior leagues where B teams and young players start (3. Liga and the Regionalligen, Serie C, the
Spanish third tier, Ligue 3/National, Austria's 2. Liga, Challenger Pro League, the Czech, Croatian, Danish, Norwegian,
Swedish and Scottish second tiers, MLS NEXT Pro, USL Championship), all from Transfermarkt's JSON API.

    python3 scripts/soccer_prospect_data.py games <ACADEMY + RESERVE comps> --seasons 2012-2026
    python3 scripts/soccer_academy_research.py      # -> data/soccer_academy_research.json

Two questions, both on the board's Oct 24 rows (2013-20 seasons, outcome = FV of best three GAR seasons at 22-26):
  1. drivers: for prospects already on the board, do academy/reserve minutes, scoring, level and age-for-level add
     to the kept model? Gate = scripts/soccer_fv_drivers.py's: season-out MSE t >= 2 and 2/3 seasons, top 50 not
     lower, forward (fit 2013-17, grade 2018-20) MSE and top 50 not worse.
  2. pool: players seen only in these leagues are not on the board today. Graded provisionally (age, market value,
     the kept inputs at zero plus any academy driver that passes), does fitting on the wider pool keep the existing
     rows' error and top 50, and are the new rows graded better than the 20 floor?
A third check feeds the game model question: does a club's academy results rating add to its next-season first-team
rating beyond this season's rating and squad value? If it can't predict first-team results it can't beat a close.
"""
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import soccer_prospect_data as SD      # noqa: E402
import soccer_prospects as SP          # noqa: E402
import soccer_fv_drivers as DR         # noqa: E402

OUT = os.path.join(ROOT, 'data', 'soccer_academy_research.json')
CACHE = os.path.join(SP.CACHE, 'academy')
ACAD, U23, RES = SD.ACADEMY, SD.U23, SD.RESERVE


def clubs_parent(ids):
    """Transfermarkt club -> its first team (mainClubId) and club type, cached"""
    fn = os.path.join(CACHE, 'clubs.json')
    have = json.load(open(fn)) if os.path.exists(fn) else {}
    todo = [str(int(i)) for i in ids if str(int(i)) not in have]
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(10) as ex:
        for i, r in zip(todo, ex.map(lambda i: SD.get(f'/club/{i}', tries=3), todo)):
            d = (r or {}).get('data') or {}
            bd = d.get('baseDetails') or {}
            have[i] = [bd.get('mainClubId'), bd.get('clubTypeId'), d.get('name')]
    json.dump(have, open(fn, 'w'))
    return have


def load():
    fn = os.path.join(CACHE, 'core.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    os.makedirs(CACHE, exist_ok=True)
    b = DR.base()
    G, A = SP.tm_games(ACAD + U23 + RES, range(SP.FIRST, SP.LAST + 1))
    A = A.merge(G[['game_id', 'comp', 'date']], on='game_id')
    G['season'], A['season'] = SP.season_of(G.date), SP.season_of(A.date)
    A['napp'], A['nbench'], A['gar'], A['r'] = (A.mins > 0).astype(int), (A.mins == 0).astype(int), 0.0, np.nan
    A = A[~A.game_id.isin(b['A'].game_id)]
    par = clubs_parent(pd.concat([A.club, G.home, G.away]).dropna().unique())
    out = (b, G, A, par)
    pickle.dump(out, open(fn, 'wb'))
    return out


def extras(b, An, par, X, t, snap):
    """academy and reserve inputs for the rows in X, from games before the snapshot (last season and this one)"""
    snap = pd.Timestamp(snap)
    ids = X.index
    E = pd.DataFrame(index=ids)
    w = An[An.player_id.isin(ids) & An.season.isin([t - 1, t]) & (An.date < snap)]
    R1 = b['R'][b['R'].season.eq(t - 1)].set_index('club').r
    parent = {int(k): (int(v[0]) if v[0] else None) for k, v in par.items()}
    w = w.assign(par=w.club.map(lambda c: parent.get(int(c)) if pd.notna(c) else None))
    w['pr'] = w.par.map(R1)
    P = b['P']
    w['age_g'] = (w.date - w.player_id.map(P.dob)).dt.days / 365.25
    for k, comps in (('acad', ACAD), ('u23', U23 + ['GB21']), ('res', RES), ('uyl', ['19YL'])):
        d = w[w.comp.isin(comps)]
        if k == 'u23':        # PL2 also from the board's own appearances
            g = b['A'][b['A'].player_id.isin(ids) & b['A'].season.isin([t - 1, t]) & (b['A'].date < snap) & b['A'].comp.eq('GB21')]
            d = pd.concat([d, g.assign(par=None, pr=np.nan)], ignore_index=True)
        m = d.groupby('player_id').mins.sum().reindex(ids).fillna(0)
        ga = (d.groupby('player_id').gl.sum() + d.groupby('player_id').ast.sum()).reindex(ids).fillna(0)
        E[k + '_m'] = m / 900
        E[k + '_ga'] = np.where(m >= 450, ga / m.clip(lower=1) * 90, 0)
        # level: the first team behind the youth/B side (its rating last season over replacement), minutes-weighted
        dl = d[d.pr.notna() & d.mins.gt(0)]
        lvl = ((dl.pr - SP.REPL).clip(lower=0) * dl.mins).groupby(dl.player_id).sum() / dl.groupby('player_id').mins.sum()
        E[k + '_par'] = lvl.reindex(ids).fillna(0) * (m > 0)
        E[k + '_parm'] = E[k + '_par'] * np.log1p(m / 90)
        # age for level: minutes x years under the level's usual age (U19 17, U23 19.5, reserve 21)
        a0 = {'acad': 17, 'u23': 19.5, 'res': 21, 'uyl': 17.5}[k]
        dy = d[d.age_g.notna() & d.mins.gt(0)]
        E[k + '_young'] = ((a0 - dy.age_g).clip(lower=0) * dy.mins / 900).groupby(dy.player_id).sum().reindex(ids).fillna(0)
        E[k + '_st'] = (d.groupby('player_id').start.sum() / d[d.mins > 0].groupby('player_id').size().clip(lower=1)).reindex(ids).fillna(0) * (m >= 270)
    # reserve club squad value (the league level for independents): minutes-weighted club log MV vs a 0.5m squad
    dr = w[w.comp.isin(RES) & w.mins.gt(0)]
    if len(dr):
        cm = SP.club_mv(An[An.comp.isin(RES) & An.season.isin([t - 1, t]) & (An.date < snap)], b['V'])
        dr = dr.merge(cm.rename('clmv').reset_index(), on=['club', 'season'], how='left')
        lv = ((dr.clmv - np.log(5e5)).clip(lower=0) * dr.mins).groupby(dr.player_id).sum() / dr.groupby('player_id').mins.sum()
        E['res_lvl'] = lv.reindex(ids).fillna(0)
    else:
        E['res_lvl'] = 0.0
    E['any_acad'] = ((E.acad_m + E.u23_m) > 0).astype(float)
    E['any_res'] = (E.res_m > 0).astype(float)
    return E


def rows():
    fn = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    b, Gn, An, par = load()
    done = b['O'][b['O'].s22 <= SP.COHORTS[1]]
    Aall = pd.concat([b['A'], An[b['A'].columns.intersection(An.columns)]], ignore_index=True)
    xs = []
    for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
        snap = SP.snapdate(t, SP.SEL_SNAP)
        X0 = SP.features(b['A'], b['P'], b['V'], b['R'], b['TG'], t, snap)
        X = SP.features(Aall, b['P'], b['V'], b['R'], b['TG'], t, snap)
        X['orig'] = X.index.isin(X0.index)
        X = X[X.index.isin(done.index)]
        F = SP.design(X)
        E = extras(b, An, par, X, t, snap)
        Z = pd.concat([F, E], axis=1)
        Z['orig'] = X.orig
        Z['fv_out'] = done.fv.reindex(X.index)
        Z['t'] = t
        Z['player_id'] = X.index
        xs.append(Z)
        print('rows', t, len(Z), int(Z.orig.sum()), flush=True)
    Z = pd.concat(xs, ignore_index=True)
    pickle.dump(Z, open(fn, 'wb'))
    return Z


CANDS = [['acad_m'], ['acad_ga'], ['acad_par'], ['acad_parm'], ['acad_young'], ['acad_st'],
         ['u23_m'], ['u23_ga'], ['u23_par'], ['u23_parm'], ['u23_young'], ['u23_st'],
         ['res_m'], ['res_ga'], ['res_par'], ['res_parm'], ['res_young'], ['res_st'], ['res_lvl'],
         ['uyl_m'], ['uyl_ga'], ['uyl_parm'], ['uyl_young'], ['any_acad'], ['any_res'],
         ['acad_m', 'u23_m', 'res_m'], ['acad_parm', 'u23_parm', 'res_parm']]


def forward_select(Z, kept, pool):
    """the board's rule, greedy, then each pick must also pass the top-50 and forward checks"""
    cur, log = list(kept), []
    while True:
        best = None
        for c in pool:
            if c in cur:
                continue
            r = DR.test(Z, cur, [c])
            if r['pass'] and (best is None or r['gain'] > best[1]['gain']):
                best = (c, r)
        if not best:
            return cur[len(kept):], log
        cur.append(best[0]); log.append({'add': best[0], **best[1]})
        print('  add', best[0], best[1], flush=True)


def pool_test(Z, cols):
    """fit on the wider pool vs the board's pool; scored on the board's rows and on the new rows"""
    y, t = Z.fv_out.values, Z.t.values
    o = Z.orig.values
    e_all, p_all = SP.loso(Z, y, t, cols)
    Zo = Z[o]
    e_o, p_o = SP.loso(Zo, Zo.fv_out.values, Zo.t.values, cols)
    yo, to = Zo.fv_out.values, Zo.t.values
    per = np.array([((e_o[to == s]) ** 2).mean() - ((e_all[o][to == s]) ** 2).mean() for s in np.unique(to)])
    n = ~o
    yn = y[n]
    pn = np.clip(p_all[n], 20, 80)
    return {'nOrig': int(o.sum()), 'nNew': int(n.sum()),
            'origMse': [round(float((e_o ** 2).mean()), 3), round(float((e_all[o] ** 2).mean()), 3)],
            'origT': round(float(per.mean() / (per.std(ddof=1) / math.sqrt(len(per)) + 1e-12)), 2),
            'origTop50': [round(DR.top50(p_o, yo, to), 2), round(DR.top50(p_all[o], yo, to), 2)],
            'newMse': {'model': round(float(((yn - pn) ** 2).mean()), 3), 'floor20': round(float(((yn - 20) ** 2).mean()), 3),
                       'mean': round(float(((yn - yn.mean()) ** 2).mean()), 3)},
            'newOutcome': {'mean': round(float(yn.mean()), 2), 'p40': round(float((yn >= 40).mean()), 4),
                           'p50': round(float((yn >= 50).mean()), 4)},
            'newTop': [{'band': lo, 'n': int(((pn >= lo) & (pn < lo + 5)).sum()),
                        'pred': round(float(pn[(pn >= lo) & (pn < lo + 5)].mean()), 1) if ((pn >= lo) & (pn < lo + 5)).any() else None,
                        'real': round(float(yn[(pn >= lo) & (pn < lo + 5)].mean()), 1) if ((pn >= lo) & (pn < lo + 5)).any() else None}
                       for lo in range(20, 70, 5)],
            # mixed board: does putting the new rows on it push worse players into each season's top 50 / 200?
            'mixedTop50': [round(DR.top50(p_o, yo, to), 2), round(DR.top50(p_all, y, t), 2)],
            'mixedTop200': [round(DR.top50(p_o, yo, to, 200), 2), round(DR.top50(p_all, y, t, 200), 2)],
            'newInTop200': round(float(np.mean([(~o[t == s][np.argsort(-p_all[t == s])[:200]]).mean() for s in np.unique(t)])), 3)}


def academy_team_test(b, Gn, par):
    """first-team rating next season ~ this season's rating + squad value (+ academy results rating)"""
    R = b['R']
    out = []
    parent = {int(k): (int(v[0]) if v[0] else None) for k, v in par.items()}
    for s in range(SP.FIRST, SP.LAST - 1):
        g = Gn[Gn.season.eq(s) & Gn.comp.isin(ACAD + U23 + ['GB21'])]
        g = pd.concat([g, b['G'][b['G'].season.eq(s) & b['G'].comp.eq('GB21')]])
        if len(g) < 200:
            continue
        r, _ = SP.ridge(g, {}, 2.0)
        d = pd.DataFrame({'yr': r})
        d['club'] = [parent.get(int(c)) for c in d.index]
        d = d.dropna().groupby('club').yr.mean()
        cur = R[R.season.eq(s)].set_index('club')
        nxt = R[R.season.eq(s + 1)].set_index('club').r
        x = pd.DataFrame({'r0': cur.r, 'lmv': cur.lmv, 'yr': d, 'r1': nxt}).dropna()
        x['s'] = s
        out.append(x)
    X = pd.concat(out)
    y, t = X.r1.values, X.s.values
    F = X[['r0', 'lmv', 'yr']]
    e0, _ = SP.loso(F, y, t, ['r0', 'lmv'])
    e1, _ = SP.loso(F, y, t, ['r0', 'lmv', 'yr'])
    per = np.array([(e0[t == s] ** 2).mean() - (e1[t == s] ** 2).mean() for s in np.unique(t)])
    return {'n': int(len(X)), 'seasons': [int(t.min()), int(t.max())], 'mse': [round(float((e0 ** 2).mean()), 4), round(float((e1 ** 2).mean()), 4)],
            't': round(float(per.mean() / (per.std(ddof=1) / math.sqrt(len(per)) + 1e-12)), 2), 'wins': int((per > 0).sum()), 'of': len(per),
            'coef': round(float(SP.ols(F, y, ['r0', 'lmv', 'yr'])[3]), 3)}


def main():
    Z = rows()
    fitj = json.load(open(SP.FIT))
    kept = list(fitj['kept'])
    Zo = Z[Z.orig].copy()
    y, t = Zo.fv_out.values, Zo.t.values
    e, p = SP.loso(Zo, y, t, kept)
    res = {'kept': kept, 'n': int(len(Zo)), 'mse': round(float((e ** 2).mean()), 2), 'top50': round(DR.top50(p, y, t), 2),
           'coverage': {c: int((Zo[c] != 0).sum()) for c in Z.columns if c.endswith('_m')}, 'cands': {}}
    for cols in CANDS:
        r = DR.test(Zo, kept, cols)
        res['cands']['+'.join(cols)] = r
        print('+'.join(cols), r, flush=True)
    add, log = forward_select(Zo, kept, sorted({c for cols in CANDS for c in cols}))
    res['selected'], res['selectLog'] = add, log
    res['pool'] = {'kept': pool_test(Z, kept), 'kept+sel': pool_test(Z, kept + add) if add else None}
    print('pool', res['pool'], flush=True)
    b, Gn, An, par = load()
    res['teamTest'] = academy_team_test(b, Gn, par)
    print('team', res['teamTest'], flush=True)
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False, default=float)


if __name__ == '__main__':
    main()
