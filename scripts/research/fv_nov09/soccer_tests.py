# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
#!/usr/bin/env python3
"""FV sweep Nov 9 2026, soccer prospects: pre-registered tests S1 (td), S2 (subpos), S3 (gbm).
Pre-registration /mnt/project-files/fv/sweep-nov09/prereg.md; design choices fixed before any fit in
soccer_s1_design.md (same folder). Rows from soccer_rows.py.

    python3 scripts/research/fv_nov09/soccer_tests.py [out.json]
"""
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_prospects as SP       # noqa: E402

ROWS = os.path.join(SP.CACHE, 'nov09_rows.pkl')
FWD = (2013, 2017)
SYM = os.path.join(SP.CACHE, 'nov09_symmv.pkl')
SUB = {'Centre-Back': 'CB', 'Left-Back': 'FB', 'Right-Back': 'FB', 'Defensive Midfield': 'DM', 'Central Midfield': 'CM',
       'Attacking Midfield': 'AM', 'Left Winger': 'W', 'Right Winger': 'W', 'Left Midfield': 'W', 'Right Midfield': 'W',
       'Centre-Forward': 'ST', 'Second Striker': 'ST'}
BLOCK = ['sp_CB', 'sp_FB', 'sp_DM', 'sp_AM', 'sp_W', 'sp_ST']      # CM is the reference; keepers and missing all zero
GBM = dict(max_depth=3, learning_rate=.05, max_iter=300, min_samples_leaf=40, l2_regularization=1.0,
           early_stopping=False, random_state=0)


def tstat(per):
    per = np.asarray(per, float)
    n = len(per)
    t = per.mean() / (per.std(ddof=1) / math.sqrt(n)) if n > 1 and per.std(ddof=1) > 0 else float('nan')
    p = float(stats.t.sf(t, n - 1)) if n > 1 else float('nan')
    return float(t), p


def top_mse(pb, pc, y, t, k=50):
    """mean over seasons of the MSE on each season's top k by the base grade: base, candidate"""
    a, b = [], []
    for s in np.unique(t):
        i = np.where(t == s)[0]
        o = i[np.argsort(-pb[i])[:k]]
        a.append(float(((y[o] - pb[o]) ** 2).mean())); b.append(float(((y[o] - pc[o]) ** 2).mean()))
    return float(np.mean(a)), float(np.mean(b)), a, b


def top_out(p, y, t, k=50):
    return float(np.mean([y[t == s][np.argsort(-p[t == s])[:k]].mean() for s in np.unique(t)]))


def clustered_t(d, pid):
    """t of mean(d) with a player-clustered standard error"""
    d = np.asarray(d, float)
    g = pd.Series(d - d.mean()).groupby(np.asarray(pid)).sum().values
    se = math.sqrt((g ** 2).sum()) / len(d)
    return float(d.mean() / se), int(len(g))


def report(name, y, t, pb, pc, fb, fc, te, extra=None):
    """board gate numbers: per-season gain, t, p, wins, top-50 MSE, forward MSE"""
    ss = np.unique(t)
    per = np.array([((y[t == s] - pb[t == s]) ** 2).mean() - ((y[t == s] - pc[t == s]) ** 2).mean() for s in ss])
    tt, p = tstat(per)
    tb, tc, _, _ = top_mse(pb, pc, y, t)
    fwb, fwc = float(((y[te] - fb) ** 2).mean()), float(((y[te] - fc) ** 2).mean())
    ftb, ftc, _, _ = top_mse(fb, fc, y[te], t[te])
    r = {'n': int(len(y)), 'mseBase': round(float(((y - pb) ** 2).mean()), 3), 'mseCand': round(float(((y - pc) ** 2).mean()), 3),
         'gain': round(float(per.mean()), 4), 'perSeason': {int(s): round(float(v), 4) for s, v in zip(ss, per)},
         't': round(tt, 3), 'p': p, 'df': len(per) - 1, 'wins': int((per > 0).sum()), 'of': len(per),
         'top50MseBase': round(tb, 3), 'top50MseCand': round(tc, 3),
         'top50OutBase': round(top_out(pb, y, t), 3), 'top50OutCand': round(top_out(pc, y, t), 3),
         'fwdMseBase': round(fwb, 3), 'fwdMseCand': round(fwc, 3), 'fwdN': int(te.sum()),
         'fwdTop50MseBase': round(ftb, 3), 'fwdTop50MseCand': round(ftc, 3)}
    need = math.ceil(len(per) * 6 / 8)
    r['gates'] = {'t>=2': bool(tt >= 2), f'wins>={need}': bool(r['wins'] >= need), 'top50': bool(tc <= tb), 'forward': bool(fwc <= fwb)}
    r['pass'] = all(r['gates'].values())
    if extra:
        r.update(extra)
    print(name, json.dumps(r), flush=True)
    return r


def board_rows(S):
    B = S[S.old & S.fv_out.notna() & (S.s22 <= SP.COHORTS[1])].reset_index(drop=True).copy()
    ref = float(S.groupby('t').mvlvl.first().mean())
    B['mvd'] = B.mv * np.exp(ref - B.mvlvl)
    return B


def subpos_block(B):
    m = B.subpos.map(SUB)
    return pd.DataFrame({c: (m == c[3:]).astype(float).values for c in BLOCK}, index=B.index)


def s2(B, F, kept):
    y, t = B.fv_out.values.astype(float), B.t.values
    known = B.subpos.map(SUB).notna() | B.subpos.eq('Goalkeeper')
    cov = {}
    for lab, m in (('fv20', y <= 20), ('fv20-30', (y > 20) & (y < 30)), ('fv30-40', (y >= 30) & (y < 40)),
                   ('fv40-50', (y >= 40) & (y < 50)), ('fv50+', y >= 50)):
        cov[lab] = {'n': int(m.sum()), 'known': round(float(known[m].mean()), 4)}
    cov['all'] = {'n': int(len(y)), 'known': round(float(known.mean()), 4)}
    cov['dump'] = {'n': int(B.in_dump.sum()), 'known': round(float(known[B.in_dump].mean()), 4)}
    cov['feeder'] = {'n': int((~B.in_dump).sum()), 'known': round(float(known[~B.in_dump].mean()), 4)}
    cov['raw'] = {str(k): int(v) for k, v in B.subpos.fillna('MISSING').value_counts().items()}
    gap = float(known[y >= 40].mean() - known[y <= 20].mean())
    cov['gap40_vs_20'] = round(gap, 4)
    print('S2 coverage', json.dumps(cov), flush=True)
    out = {'coverage': cov, 'leakStop': bool(gap > .05)}
    if out['leakStop']:
        out['note'] = 'coverage is outcome-selected (gap > 5 points): S2 stopped as a leak, per the design rule'
        return out
    Z = pd.concat([F, subpos_block(B)], axis=1)
    out['share'] = {c: round(float(Z[c].mean()), 4) for c in BLOCK}

    def run(Z, y, t, tag):
        _, pb = SP.loso(Z, y, t, kept)
        _, pc = SP.loso(Z, y, t, kept + BLOCK)
        tr = (t >= FWD[0]) & (t <= FWD[1]); te = ~tr
        fb = SP.pred(Z[te], kept, SP.ols(Z[tr], y[tr], kept))
        fc = SP.pred(Z[te], kept + BLOCK, SP.ols(Z[tr], y[tr], kept + BLOCK))
        coef = dict(zip(['const'] + kept + BLOCK, SP.ols(Z, y, kept + BLOCK)))
        return report(tag, y, t, pb, pc, fb, fc, te, {'coef': {c: round(float(coef[c]), 3) for c in BLOCK}})
    out['main'] = run(Z, y, t, 'S2')
    k = known.values
    out['knownOnly'] = run(Z[k].reset_index(drop=True), y[k], t[k], 'S2 known-position rows only')
    return out


def gbm_oof(Xa, y, fold):
    p = np.zeros(len(y))
    for f in np.unique(fold):
        tr, te = fold != f, fold == f
        p[te] = HistGradientBoostingRegressor(**GBM).fit(Xa[tr], y[tr]).predict(Xa[te])
    return p


def guard_ht(B, F):
    """GBM inputs with no trace of a missing height: the board fills a missing height with the mean (0), which a tree
    can isolate; here each such player gets a height drawn from the known heights of his position group"""
    rng = np.random.default_rng(0)
    Fg = F.copy()
    pl = B.drop_duplicates('player_id').set_index('player_id')
    draw = pd.Series(np.nan, index=pl.index)
    for g in 'GDMF':
        known = pl.ht[(pl.grp == g) & pl.ht.notna()].values
        miss = pl.index[(pl.grp == g) & pl.ht.isna()]
        draw.loc[miss] = rng.choice(known, len(miss))
    ht = B.ht.fillna(B.player_id.map(draw))
    Fg['ht'] = ((ht - 181) / 7).values
    Fg['ht_gk'] = Fg.ht * Fg.gk
    return Fg


def sym_design(B, SY):
    """the design with market values as visible on a player's own lineup dates only (soccer_rows_symmv.py)"""
    B2 = B.merge(SY, on=['player_id', 't'], how='left')
    assert len(B2) == len(B)
    B2['mv'], B2['mv1'] = B2.mv_sym, B2.mv1_sym
    B2['mvd'] = B2.mv * np.exp(float(SY.groupby('t').mvlvl_sym.first().mean()) - B2.mvlvl_sym)
    B2.index = B.index
    return SP.design(B2)


def s3(B, F, kept, Fg=None, tag='S3'):
    y, t, co = B.fv_out.values.astype(float), B.t.values, B.s22.values
    cols = list(F.columns)
    Xa = (F if Fg is None else Fg)[cols].values.astype(float)
    _, pb = SP.loso(F, y, t, kept)
    pg = gbm_oof(Xa, y, t)
    tr = (t >= FWD[0]) & (t <= FWD[1]); te = ~tr
    fb = SP.pred(F[te], kept, SP.ols(F[tr], y[tr], kept))
    fg = HistGradientBoostingRegressor(**GBM).fit(Xa[tr], y[tr]).predict(Xa[te])
    out = {'columns': cols,
           'main': report(tag + ' blend', y, t, pb, (pb + pg) / 2, fb, (fb + fg) / 2, te),
           'gbmAlone': report(tag + ' gbm alone (not the test)', y, t, pb, pg, fb, fg, te)}
    # beside: birth-cohort folds (a player's every row out together), scored per cohort
    _, pbc = SP.loso(F, y, co, kept)
    pgc = gbm_oof(Xa, y, co)
    pcc = (pbc + pgc) / 2
    per = np.array([((y[co == c] - pbc[co == c]) ** 2).mean() - ((y[co == c] - pcc[co == c]) ** 2).mean() for c in np.unique(co)])
    tt, p = tstat(per)
    d = (y - pbc) ** 2 - (y - pcc) ** 2
    ct, npl = clustered_t(d, B.player_id.values)
    tb, tc, _, _ = top_mse(pbc, pcc, y, t)
    out['cohortOut'] = {'mseBase': round(float(((y - pbc) ** 2).mean()), 3), 'mseCand': round(float(((y - pcc) ** 2).mean()), 3),
                        'mseGbm': round(float(((y - pgc) ** 2).mean()), 3),
                        'gain': round(float(per.mean()), 4), 't': round(tt, 3), 'p': p, 'wins': int((per > 0).sum()), 'of': len(per),
                        'perCohort': {int(c): round(float(v), 4) for c, v in zip(np.unique(co), per)},
                        'playerClusteredT': round(ct, 3), 'players': npl, 'top50MseBase': round(tb, 3), 'top50MseCand': round(tc, 3)}
    # the live grade is the isotonic-calibrated OLS (map fit on the other cohorts' out-of-sample grades, as SP.fit)
    cal = np.zeros(len(y))
    for c in np.unique(co):
        m = co == c
        pp, yy = pbc[~m], y[~m]
        cal[m] = SP.calibrate(pbc[m], {'k': SP.isotonic(pp, yy), 'slope': float(np.polyfit(pp[pp >= 50], yy[pp >= 50], 1)[0])})
    cb = (cal + pgc) / 2
    # and the blend calibrated the same way (how it would ship: isotonic map after the grade)
    calb = np.zeros(len(y))
    for c in np.unique(co):
        m = co == c
        pp, yy = pcc[~m], y[~m]
        calb[m] = SP.calibrate(pcc[m], {'k': SP.isotonic(pp, yy), 'slope': float(np.polyfit(pp[pp >= 50], yy[pp >= 50], 1)[0])})
    per3 = np.array([((y[co == c] - cal[co == c]) ** 2).mean() - ((y[co == c] - calb[co == c]) ** 2).mean() for c in np.unique(co)])
    t3, p3 = tstat(per3)
    tb3, tc3, _, _ = top_mse(cal, calb, y, t)
    per2 = np.array([((y[co == c] - cal[co == c]) ** 2).mean() - ((y[co == c] - cb[co == c]) ** 2).mean() for c in np.unique(co)])
    t2, p2 = tstat(per2)
    tb2, tc2, _, _ = top_mse(cal, cb, y, t)
    out['cohortOut'].update({'mseCalOls': round(float(((y - cal) ** 2).mean()), 3), 'mseCalOlsBlend': round(float(((y - cb) ** 2).mean()), 3),
                             'calGain': round(float(per2.mean()), 4), 'calT': round(t2, 3), 'calP': p2, 'calWins': int((per2 > 0).sum()),
                             'calTop50MseBase': round(tb2, 3), 'calTop50MseCand': round(tc2, 3),
                             'mseCalBlend': round(float(((y - calb) ** 2).mean()), 3), 'cal2Gain': round(float(per3.mean()), 4),
                             'cal2T': round(t3, 3), 'cal2P': p3, 'cal2Wins': int((per3 > 0).sum()), 'cal2Top50MseCand': round(tc3, 3),
                             'cal2Top50OutBase': round(top_out(cal, y, t), 3), 'cal2Top50OutCand': round(top_out(calb, y, t), 3)})
    print(tag + ' cohort-out', json.dumps(out['cohortOut']), flush=True)
    return out


# ---------------------------------------------------------------- S1 (descriptive: the registered rule selects no season)
def partial_fv(gar, ids, grp, scale, upto=None, m=None):
    """FV of the best three GAR seasons over the seen part of the 22-26 window (seasons <= upto, or the first m ages)"""
    g = gar[gar.player_id.isin(ids)]
    if upto is not None:
        g = g[g.season <= upto]
    if m is not None:
        g = g[g.age <= SP.PEAK_AGES[0] + m - 1]
    pk = g.groupby('player_id').gar.apply(lambda v: float(np.sort(np.r_[v.values, 0, 0, 0])[-3:].mean()))
    pk = pk.reindex(ids).fillna(0.0).values
    return SP.fv_from_peak(pk, np.asarray(grp), scale), pk


def s1_season(S, gar, scale, kept, N):
    A = S[S.old & S.s22.notna() & (S.t <= N)].reset_index(drop=True).copy()
    A['s22'] = A.w22          # the design's s22: the season he is 22 on July 1 (SP's s22 label runs 2 seasons early for
                              # July-December births; with that label the first run used outcomes not complete at N-1)
    lv = A.groupby('t').mvlvl.first()
    A['mvd'] = A.mv * np.exp(float(lv[lv.index <= N - 1].mean()) - A.mvlvl)
    F = SP.design(A)
    t, s22, pid = A.t.values, A.s22.values, A.player_id.values
    base = (t <= N - 1) & (s22 <= N - 5)
    y = A.fv_out.values.astype(float)              # true outcome: used only where base (complete as of N-1) and for scoring
    b0 = SP.ols(F[base], y[base], kept)
    raw = SP.pred(F, kept, b0)
    cos = np.unique(s22[base])
    oos = raw.copy()
    if len(cos) >= 2:
        _, pp = SP.loso(F[base], y[base], s22[base], kept)
        oos[base] = pp
    pp, yy = oos[base], y[base]
    hi = pp >= 50
    knots = {'k': SP.isotonic(pp, yy), 'slope': float(np.polyfit(pp[hi], yy[hi], 1)[0]) if hi.sum() >= 20 else 1.0}
    cal = np.clip(SP.calibrate(oos, knots), 20, 80)
    A['cal'] = cal
    hist = A[A.t <= N - 1]
    last_t = hist.groupby('player_id').t.transform('max').reindex(A.index)
    is_last = (A.t == last_t).values
    glast = hist[hist.t == hist.groupby('player_id').t.transform('max')].set_index('player_id').cal
    target = np.full(len(A), np.nan)
    target[base] = y[base]
    # (a) still under 22 at N-1: his latest grade is the target of his earlier rows
    a_rows = (t <= N - 1) & (s22 >= N) & ~is_last
    target[a_rows] = glast.reindex(pid[a_rows]).values
    # (b) past 22, window unfinished: imputation per number of seen window seasons m
    fin = hist[hist.s22 <= N - 5].drop_duplicates('player_id').set_index('player_id')
    imp = {}
    b_rows = np.zeros(len(A), bool)
    for m in range(1, 5):
        c = N - m
        un = hist[hist.s22 == c].drop_duplicates('player_id').set_index('player_id')
        if not len(un) or len(fin) < 50:
            continue
        ff, _ = partial_fv(gar, fin.index, fin.grp.values, scale, m=m)
        Xf = np.column_stack([np.ones(len(fin)), ff, (ff > 20).astype(float), glast.reindex(fin.index).values])
        w = np.linalg.lstsq(Xf, fin.fv_out.values.astype(float), rcond=None)[0]
        fu, _ = partial_fv(gar, un.index, un.grp.values, scale, upto=N - 1)
        Xu = np.column_stack([np.ones(len(un)), fu, (fu > 20).astype(float), glast.reindex(un.index).values])
        tg = pd.Series(np.clip(Xu @ w, 20, 80), index=un.index)
        r = (t <= N - 1) & (s22 == c)
        target[r] = tg.reindex(pid[r]).values
        b_rows |= r
        truth = un.fv_out.values.astype(float)
        imp[m] = {'cohort': int(c), 'players': int(len(un)), 'finPlayers': int(len(fin)), 'w': [round(float(v), 3) for v in w],
                  'targetMean': round(float(tg.mean()), 2),
                  'truthMean': round(float(np.nanmean(truth)), 2) if c <= SP.COHORTS[1] else None,
                  'targetRmse': round(float(np.sqrt(np.nanmean((tg.values - truth) ** 2))), 2) if c <= SP.COHORTS[1] else None}
    td = base | ((a_rows | b_rows) & ~np.isnan(target))
    b1 = SP.ols(F[td], target[td], kept)
    te = (t == N) & (s22 <= SP.COHORTS[1]) & ~np.isnan(y)
    pb, pc = SP.pred(F[te], kept, b0), SP.pred(F[te], kept, b1)
    yt = y[te]
    o = np.argsort(-pb)[:50]
    am = (a_rows & (s22 <= SP.COHORTS[1]) & ~np.isnan(y))
    res = {'N': N, 'baseRows': int(base.sum()), 'baseCohorts': [int(c) for c in cos], 'baseSeasons': sorted(int(v) for v in np.unique(t[base])),
           'tdRowsA': int((a_rows & ~np.isnan(target)).sum()), 'tdRowsB': int(b_rows.sum()), 'scored': int(te.sum()),
           'scoredAges': [round(float(A.age.values[te].min()), 1), round(float(A.age.values[te].max()), 1)],
           'mseBase': round(float(((yt - pb) ** 2).mean()), 3), 'mseTd': round(float(((yt - pc) ** 2).mean()), 3),
           'gain': round(float(((yt - pb) ** 2).mean() - ((yt - pc) ** 2).mean()), 4),
           'mseConst': round(float(((yt - y[base].mean()) ** 2).mean()), 3),
           'top50MseBase': round(float(((yt[o] - pb[o]) ** 2).mean()), 3), 'top50MseTd': round(float(((yt[o] - pc[o]) ** 2).mean()), 3),
           'top50OutBase': round(float(yt[o].mean()), 2), 'top50OutTd': round(float(yt[np.argsort(-pc)[:50]].mean()), 2),
           'aTargetRmseVsTruth': round(float(np.sqrt(((target[am] - y[am]) ** 2).mean())), 2) if am.sum() else None,
           'aTargetMean': round(float(target[am].mean()), 2) if am.sum() else None, 'aTruthMean': round(float(y[am].mean()), 2) if am.sum() else None,
           'imputation': imp}
    print('S1', json.dumps(res), flush=True)
    return res, (yt - pb) ** 2 - (yt - pc) ** 2, pid[te]


def s1(S, gar, scale, kept):
    out = {'firstRunNote': 'a first run used SP.outcome\'s s22 label as the window start; for July-December births that label is 2 '
                           'seasons early, so the base arm saw outcomes not complete at N-1 (gains -4.00 / -3.62, not as-of). '
                           'Rerun below on the true window start, as the design file defines s22',
           'registered': 'NOT RUN: the rule (scoring seasons with >= 3 finished base-arm training seasons) selects no season',
           'descriptive': {}}
    ds, ps = [], []
    for N in (2019, 2020):
        r, d, p = s1_season(S, gar, scale, kept, N)
        out['descriptive'][N] = r
        ds.append(d); ps.append(p)
    per = np.array([out['descriptive'][N]['gain'] for N in (2019, 2020)])
    tt, p = tstat(per)
    ct, npl = clustered_t(np.concatenate(ds), np.concatenate(ps))
    tb = np.mean([out['descriptive'][N]['top50MseBase'] for N in (2019, 2020)])
    tc = np.mean([out['descriptive'][N]['top50MseTd'] for N in (2019, 2020)])
    out['summary'] = {'seasons': [2019, 2020], 'gain': round(float(per.mean()), 4), 't': round(tt, 3), 'p': p, 'df': 1,
                      'wins': int((per > 0).sum()), 'of': 2, 'playerClusteredT': round(ct, 3), 'players': npl,
                      'rows': int(sum(len(d) for d in ds)), 'top50MseBase': round(float(tb), 3), 'top50MseTd': round(float(tc), 3)}
    print('S1 summary', json.dumps(out['summary']), flush=True)
    return out


def main():
    D = pickle.load(open(ROWS, 'rb'))
    S, gar, scale = D['S'], D['gar'], D['scale']
    S['old'] = S.old.astype(bool)
    S['w22'] = (S.t + 22 - np.floor(S.age)).groupby(S.player_id).transform('max').astype(int)   # true first age-22 season
    fit = json.load(open(SP.FIT))
    kept = list(fit['kept'])
    B = board_rows(S)
    F = SP.design(B)
    y, t = B.fv_out.values.astype(float), B.t.values
    e, p = SP.loso(F, y, t, kept)
    out = {'rows': {'n': int(len(B)), 'players': int(B.player_id.nunique()), 'perSeason': {int(k): int(v) for k, v in B.t.value_counts().sort_index().items()},
                    'losoMse': round(float((e ** 2).mean()), 3), 'fitFileN': fit['n'], 'fitFileMse': fit['models']['10-24']['mse'],
                    'top50Out': round(top_out(p, y, t), 2), 'fitFileTop50': fit.get('top50')}, 'kept': kept}
    print('rows', json.dumps(out['rows']), flush=True)
    out['S1'] = s1(S, gar, scale, kept)
    out['S2'] = s2(B, F, kept)
    out['S3'] = s3(B, F, kept)
    # leak guards for the GBM inputs (the OLS grade stays the live one). guarded = both guards; decided before running them
    Fh = guard_ht(B, F)
    out['S3_guard_ht'] = s3(B, F, kept, Fh, 'S3 guard ht')
    out['S3_guard_ht']['htMissing'] = {'share': round(float(B.ht.isna().mean()), 4), 'outMissing': round(float(y[B.ht.isna().values].mean()), 2),
                                       'outKnown': round(float(y[B.ht.notna().values].mean()), 2)}
    if os.path.exists(SYM):
        SY = pd.read_pickle(SYM)
        Fs = guard_ht(B, sym_design(B, SY))
        b2 = B.merge(SY, on=['player_id', 't'], how='left')
        out['S3_guarded'] = s3(B, F, kept, Fs, 'S3 guarded (ht + symmetric MV)')
        out['S3_guarded']['mvKnown'] = {'board': round(float(B.mv.notna().mean()), 4), 'sym': round(float(b2.mv_sym.notna().mean()), 4),
                                        'board1': round(float(B.mv1.notna().mean()), 4), 'sym1': round(float(b2.mv1_sym.notna().mean()), 4)}
    # sensitivity (added after the cohort-label finding): only rows whose 22-26 window is truly complete (w22 <= 2021)
    k = (B.w22 <= SP.COHORTS[1]).values
    Bk, Fk = B[k].reset_index(drop=True), F[k].reset_index(drop=True)
    out['window'] = {'rows': int(len(B)), 'complete': int(k.sum()), 'bySeason': {int(s): [int((k & (t == s)).sum()), int((t == s).sum())] for s in np.unique(t)}}
    print('window', json.dumps(out['window']), flush=True)
    out['S2_complete'] = s2(Bk, Fk, kept).get('main')
    out['S3_complete'] = s3(Bk, Fk, kept, guard_ht(Bk, Fk), 'S3 complete windows, guard ht')
    fn = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SP.CACHE, 'nov09_soccer.json')
    json.dump(out, open(fn, 'w'), indent=1)
    print('wrote', fn)


if __name__ == '__main__':
    main()
