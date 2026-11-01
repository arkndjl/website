#!/usr/bin/env python3
"""Youth national team call-ups as soccer prospect FV drivers (Noah, Oct 31 2026). MLS NEXT has no free player-level
source, so the nearest public signal for academy players is a youth international call-up. Transfermarkt's API carries
lineups for the U17 and U20 World Cups, the U17/U19/U21 Euros and their qualifiers, CONCACAF U17 and U20 (and U20
qualifying), the South American U17/U20, the Asian U17/U20 and the African U17/U20 championships.

    python3 scripts/soccer_prospect_data.py games 17WC 20WC U17Q U19Q U21Q 17EU 19EU 21EU SAM7 2SAM 17AC 20AC CO17 \
        C220 C20Q AU2C AA17 --seasons 2010-2026
    python3 scripts/soccer_youth_intl_research.py      # -> data/soccer_youth_intl_research.json

Three pools, all on the board's Oct 24 rows (2013-20 seasons, outcome = FV of the best three GAR seasons at 22-26),
youth inputs from games before the snapshot only (whole career to date):
  1. board rows (on a lineup in the board's own leagues): scripts/soccer_fv_drivers.py's gate (season-out MSE t >= 2
     and 2/3 seasons, top 50 not lower, forward fit 2013-17 / grade 2018-20 MSE and top 50 not worse)
  2. academy-only rows (seen only in academy/reserve leagues; graded provisionally by the board's model, then the fit's
     own line): does a youth term on that line beat the line alone, season-out?
  3. youth-international-only rows (no club minutes in any league we pull): would grading them (age, market value,
     youth inputs) beat the 20 floor they get by not being on the board?

Result (Oct 31 2026; data/soccer_youth_intl_research.json): 1. every youth term passes the season test on the board's
rows (yi_calls t 3.0, yi_fin + yi_lvl t 3.3) and fails the forward test or the top 50, as the UEFA qualifier caps did on
Oct 24: not added. 2. academy-only: the highest level played (yi_lvl) adds to the line, t 4.6, 7/8 seasons, forward
MSE 13.58 -> 13.48, top 50 27.5 -> 28.0: SHIPPED (fit provLine2). 3. youth-international-only (23.5k rows): the line on
the board's grade beats the floor (t 5.0; forward MSE 11.46 -> 10.49) and U17/U20 World Cup games add (t 3.7, 7/8,
forward 10.42, top 50 23.7 -> 24.0): SHIPPED as a provisional pool (fit yiLine). Lines refit against the live model by
the fit's own code path (scripts/soccer_prospects.py fit); the board's kept model is unchanged.
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import soccer_prospects as SP          # noqa: E402
import soccer_fv_drivers as DR         # noqa: E402

OUT = os.path.join(ROOT, 'data', 'soccer_youth_intl_research.json')
CACHE = os.path.join(SP.CACHE, 'youth_intl')
# competition -> (age cap, finals tournament)
YC = {'17WC': (17, 1), '20WC': (20, 1), 'U17Q': (17, 0), 'U19Q': (19, 0), 'U21Q': (21, 0), '17EU': (17, 1),
      '19EU': (19, 1), '21EU': (21, 1), 'SAM7': (17, 1), '2SAM': (20, 1), '17AC': (17, 1), '20AC': (20, 1),
      'CO17': (17, 1), 'C220': (20, 1), 'C20Q': (20, 0), 'AU2C': (20, 1), 'AA17': (17, 1)}
WC = ['17WC', '20WC']


def youth():
    fn = os.path.join(CACHE, 'youth.pkl')
    if os.path.exists(fn):
        return pd.read_pickle(fn)
    os.makedirs(CACHE, exist_ok=True)
    G, A = SP.tm_games(list(YC), range(2010, SP.LAST + 1))
    A = A.merge(G[['game_id', 'comp', 'date']], on='game_id')
    A['cap'] = A.comp.map(lambda c: YC[c][0])
    A['fin'] = A.comp.map(lambda c: YC[c][1])
    A.to_pickle(fn)
    return A


def yfeat(Y, P, ids, snap):
    """youth international inputs before the snapshot"""
    y = Y[Y.player_id.isin(ids) & (Y.date < snap)]
    a = y[y.mins > 0].copy()
    a['age_g'] = (a.date - a.player_id.map(P.dob)).dt.days / 365.25
    E = pd.DataFrame(index=ids)
    E['yi_calls'] = np.log1p(y.groupby('player_id').size().reindex(ids).fillna(0))
    E['yi_m'] = (a.groupby('player_id').mins.sum().reindex(ids).fillna(0) / 900).clip(upper=3)
    E['yi_fin'] = np.log1p(a[a.fin.eq(1)].groupby('player_id').size().reindex(ids).fillna(0))
    E['yi_wc'] = np.log1p(a[a.comp.isin(WC)].groupby('player_id').size().reindex(ids).fillna(0))
    # minutes young for the level: years under the age cap x minutes / 900
    E['yi_young'] = ((a.cap - a.age_g).clip(lower=0) * a.mins / 900).groupby(a.player_id).sum().reindex(ids).fillna(0).clip(upper=3)
    # the highest level reached: U21 3, U19/U20 2, U17 1
    lv = a.cap.map({17: 1, 19: 2, 20: 2, 21: 3}).groupby(a.player_id).max()
    E['yi_lvl'] = lv.reindex(ids).fillna(0)
    E['yi_ga'] = np.where(E.yi_m * 900 >= 270, (a.groupby('player_id').gl.sum() + a.groupby('player_id').ast.sum()).reindex(ids).fillna(0)
                          / (E.yi_m * 900).clip(lower=1) * 90, 0)
    E['yi_any'] = (E.yi_calls > 0).astype(float)
    return E


def rows():
    fn = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(fn):
        return pd.read_pickle(fn)
    b = DR.base()
    Y = youth()
    P, V = b['P'].copy(), b['V']
    # birth dates from youth lineup ages for anyone the profiles and dump miss
    ag = Y[Y.age.notna()]
    est = (ag.date - pd.to_timedelta((ag.age + .5) * 365.25, unit='D')).groupby(ag.player_id).median()
    miss = est.index.difference(P.index[P.dob.notna()])
    P = pd.concat([P[~P.index.isin(miss)], pd.DataFrame({'dob': est.loc[miss], 'grp': 'M'})])
    sp = Y[Y.pos.notna() & Y.start.eq(1)].groupby('player_id').pos.agg(lambda s: s.value_counts().index[0])
    POSG = {'GK': 'G', 'CB': 'D', 'LB': 'D', 'RB': 'D', 'LW': 'F', 'RW': 'F', 'SS': 'F', 'CF': 'F'}
    g2 = sp.map(lambda p: POSG.get(p, 'M'))
    P.loc[P.index.isin(miss), 'grp'] = g2.reindex(P.index[P.index.isin(miss)]).fillna('M').values
    O, _ = SP.outcome(b['A'], P)                  # same scale as the board; youth-only players never seen later get 20
    O0 = b['O']
    done = O[O.s22.between(*SP.COHORTS)]
    # the board's outcome for its own players (the scale is built from players on a lineup, unchanged)
    done.loc[done.index.isin(O0.index), 'fv'] = O0.fv.reindex(done.index[done.index.isin(O0.index)]).values
    YV = Y[Y.mv.notna()][['player_id', 'date', 'mv']]
    xs = []
    for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
        snap = SP.snapdate(t, SP.SEL_SNAP)
        X = SP.features(b['A'], b['P'], V, b['R'], b['TG'], t, snap)
        X['pool'] = np.where(X.old, 'board', 'acad')
        # youth-international-only: a youth game before the snapshot, under 22 on July 1, not in the club pool
        yi = Y[(Y.date < snap) & (Y.date >= snap - pd.Timedelta(days=730))].player_id.unique()
        age = (pd.Timestamp(f'{t}-07-01') - P.dob.reindex(yi)).dt.days / 365.25
        new = age[(age < SP.AGE_CUT) & (age >= 15)].index.difference(X.index)
        N = pd.DataFrame(index=new)
        N['age'] = age.loc[new]
        # hindsight guards: market values from youth lineups only (the dump's valuation history exists only for players
        # who later reached its leagues), no height and the youth-lineup position (profiles were pulled for players
        # later seen in club games, so a known height or profile position marks a later career)
        vv = YV[YV.player_id.isin(new) & (YV.date <= snap)].sort_values('date')
        N['mv'] = vv.groupby('player_id').mv.last()
        v1 = vv[vv.date <= snap - pd.Timedelta(days=365)]
        N['mv1'] = v1.groupby('player_id').mv.last()
        N['grp'] = g2.reindex(new).fillna('M')
        N['ht'] = np.nan
        for c in ('rclub_td', 'rclub1', 'rlg_td', 'club_td', 'club1', 'comp1'):
            N[c] = np.nan
        N['old'], N['pool'], N['t'] = False, 'yi', t
        X = pd.concat([X, N])
        X = X[X.index.isin(done.index)]
        X['mvlvl'] = SP.mv_level(X[X.pool.ne('yi')].mv)
        F = SP.design(X)
        E = yfeat(Y, P, X.index, snap)
        Z = pd.concat([F, E], axis=1)
        Z['pool'] = X.pool
        Z['mv'], Z['mvlvl'] = X.mv, X.mvlvl
        Z['fv_out'] = done.fv.reindex(X.index)
        Z['t'] = t
        Z['player_id'] = X.index
        xs.append(Z)
        print('rows', t, Z.pool.value_counts().to_dict(), flush=True)
    Z = pd.concat(xs, ignore_index=True)
    Z.to_pickle(fn)
    return Z


CANDS = [['yi_calls'], ['yi_m'], ['yi_fin'], ['yi_wc'], ['yi_young'], ['yi_lvl'], ['yi_ga'], ['yi_any'],
         ['yi_m', 'yi_young'], ['yi_fin', 'yi_lvl']]


def provgrade(Z, fitj):
    """the live board's grade (Oct 24 model, its isotonic map) on the fit seasons' money"""
    m = fitj['models']['%02d-%02d' % SP.SEL_SNAP]
    kept = fitj['kept']
    Zc = Z.copy()
    mvd = Zc.mv * np.exp(fitj['mvRef']['%02d-%02d' % SP.SEL_SNAP] - Zc.mvlvl)
    Zc['lmv'] = np.log(mvd.fillna(25000).clip(lower=25000) / 1e6)
    Zc['lmv2'] = Zc.lmv ** 2
    Zc['age_lmv'] = Zc.age * Zc.lmv
    Zc['lmv_fwd'], Zc['lmv_gk'] = Zc.lmv * Zc.fwd, Zc.lmv * Zc.gk
    p = SP.pred(Zc, kept, np.array([m['coef'][c] for c in ['const'] + kept]))
    return SP.calibrate(p, m['iso']).clip(20, 80)


def line_test(Z, pa, cols):
    """season-out: y - 20 ~ (grade - 20) [+ cols] vs the line alone (and vs the 20 floor)"""
    y, t = Z.fv_out.values, Z.t.values
    F0 = pd.DataFrame({'g': pa - 20}, index=Z.index)
    F1 = pd.concat([F0, Z[cols]], axis=1)
    def cv(F, c):
        e = np.zeros(len(y))
        for s in np.unique(t):
            tr, te = t != s, t == s
            b = SP.ols(F[tr], y[tr] - 20, c)
            e[te] = y[te] - 20 - SP.pred(F[te], c, b).clip(0, 60)
        return e
    e0, e1 = cv(F0, ['g']), cv(F1, ['g'] + cols)
    per = np.array([(e0[t == s] ** 2).mean() - (e1[t == s] ** 2).mean() for s in np.unique(t)])
    pf = np.array([((y[t == s] - 20) ** 2).mean() - (e0[t == s] ** 2).mean() for s in np.unique(t)])
    b = SP.ols(F1, y - 20, ['g'] + cols)
    tr, te = Z.t.between(*DR.FWD).values, ~Z.t.between(*DR.FWD).values
    f = {}
    for k, F, c in (('line', F0, ['g']), ('lineX', F1, ['g'] + cols)):
        bb = SP.ols(F[tr], y[tr] - 20, c)
        f[k] = 20 + SP.pred(F[te], c, bb).clip(0, 60)
    top = lambda q: float(np.mean([y[te][t[te] == s][np.argsort(-q[t[te] == s])[:50]].mean() for s in np.unique(t[te])]))
    fwd = {'mseFloor': round(float(((y[te] - 20) ** 2).mean()), 3), 'mseLine': round(float(((y[te] - f['line']) ** 2).mean()), 3),
           'mseLineX': round(float(((y[te] - f['lineX']) ** 2).mean()), 3), 'top50Line': round(top(f['line']), 2), 'top50LineX': round(top(f['lineX']), 2)}
    return {'fwd': fwd, 'n': int(len(y)), 'nz': int((Z[cols].abs().sum(axis=1) > 0).sum()), 'mseFloor': round(float(((y - 20) ** 2).mean()), 3),
            'mseLine': round(float((e0 ** 2).mean()), 3), 'mseLineX': round(float((e1 ** 2).mean()), 3),
            't': round(float(per.mean() / (per.std(ddof=1) / math.sqrt(len(per)) + 1e-12)), 2), 'wins': int((per > 0).sum()), 'of': len(per),
            'tLineVsFloor': round(float(pf.mean() / (pf.std(ddof=1) / math.sqrt(len(pf)) + 1e-12)), 2),
            'coef': dict(zip(['const', 'g'] + cols, [round(float(v), 3) for v in b]))}


def main():
    Z = rows()
    fitj = json.load(open(SP.FIT))
    kept = list(fitj['kept'])
    res = {'kept': kept, 'pools': Z.pool.value_counts().to_dict(),
           'coverage': {p: int((Z[Z.pool.eq(p)].yi_any > 0).sum()) for p in ('board', 'acad', 'yi')}}
    # 1. board rows
    Zo = Z[Z.pool.eq('board')].copy()
    y, t = Zo.fv_out.values, Zo.t.values
    e, p = SP.loso(Zo, y, t, kept)
    res['board'] = {'n': int(len(Zo)), 'mse': round(float((e ** 2).mean()), 2), 'top50': round(DR.top50(p, y, t), 2), 'cands': {}}
    for cols in CANDS:
        r = DR.test(Zo, kept, cols)
        res['board']['cands']['+'.join(cols)] = r
        print('board', '+'.join(cols), r, flush=True)
    # 2/3. provisional pools: the live grade, then a line on their own outcomes, with and without the youth inputs
    for pool in ('acad', 'yi'):
        Zp = Z[Z.pool.eq(pool)].copy()
        pa = provgrade(Zp, fitj)
        out = {'n': int(len(Zp)), 'outcome': {'mean': round(float(Zp.fv_out.mean()), 2), 'p40': round(float((Zp.fv_out >= 40).mean()), 4),
                                              'p50': round(float((Zp.fv_out >= 50).mean()), 4)}, 'cands': {}}
        if pool == 'yi':
            hit = Zp.yi_any > 0
            out['byLevel'] = {int(k): {'n': int(len(g)), 'mean': round(float(g.mean()), 2), 'p40': round(float((g >= 40).mean()), 3),
                                       'p50': round(float((g >= 50).mean()), 3)} for k, g in Zp[hit].groupby('yi_lvl').fv_out}
        for cols in CANDS:
            r = line_test(Zp, pa, cols)
            out['cands']['+'.join(cols)] = r
            print(pool, '+'.join(cols), r, flush=True)
        res[pool] = out
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False, default=float)


if __name__ == '__main__':
    main()
