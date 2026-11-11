#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer prospects: frame (height) as an FV driver within the position, Nov 3 2026.

    python3 scripts/research/frame_nov03/soccer_pull.py dump / games ... / profiles   # the board's rebuild (generic UA)
    python3 scripts/research/frame_nov03/soccer_frame.py                               # -> <out dir>/soccer_frame.json

Height is the only frame measure (Transfermarkt; no weight). The kept model already has ht = (cm - 181) / 7 pooled and
ht x goalkeeper. Tested here, each on the board's own rows (old pool, MV in the fit seasons' money), on top of the live
kept model, Oct 24 (selection snapshot) and Jan 15 (check):
  htz_grp   height z within the position group (GK / DEF / MID / FWD), replacing ht and ht_gk
  +htz_grp  the same added on top of ht and ht_gk
  htz_role  z within the role (GK, CB, FB, DM, CM, AM, W, ST; Transfermarkt sub-position), replacing ht and ht_gk
  ht_by_grp height slopes by group (ht x DEF, ht x FWD added; ht = MID, ht_gk = GK already in)
  ht_cb_st  height slopes where the job is aerial: ht x centre-back, ht x striker
Gate (soccer_trust_research.test): birth-cohort-out (folds cluster by player) t >= 2 and 2/3 of cohorts; season-out shown;
each season's top 50 by the base grade: MSE not worse, top 50 by the new grade not lower in outcome; forward (fit
2013-17, grade 2018-20) MSE and top-50 MSE not worse, top-50 outcome >= -.1. Holm over every fit.
Sources: the dump's height_in_cm (a scrape of Transfermarkt) and Transfermarkt's API profile (feeder players); the same
site, so no second measurement to weight; FBref, Sofascore and worldfootball return 403 (not tried again).
"""
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
import soccer_prospects as SP  # noqa: E402
import soccer_trust_research as TR  # noqa: E402
import harness as HS  # noqa: E402

OUTD = os.environ.get('FRAME_OUT') or '/mnt/project-files/fv/frame-nov03/soccer/'
CACHE = os.path.join(SP.CACHE, 'frame')
ROLE = {'Goalkeeper': 'GK', 'Centre-Back': 'CB', 'Left-Back': 'FB', 'Right-Back': 'FB', 'Defensive Midfield': 'DM',
        'Central Midfield': 'CM', 'Left Midfield': 'CM', 'Right Midfield': 'CM', 'Attacking Midfield': 'AM',
        'Left Winger': 'W', 'Right Winger': 'W', 'Centre-Forward': 'ST', 'Second Striker': 'ST'}
SNAPS = [SP.SEL_SNAP, (1, 15)]


def rows():
    fn = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    os.makedirs(CACHE, exist_ok=True)
    G, A, P, V = SP.load()
    # this rebuild skips the 2026 lineups of the dump leagues (no fit row uses them): the empty frame in load()'s concat
    # leaves object dtypes behind
    for c in ('mins', 'gl', 'ast', 'start', 'age', 'mv', 'club', 'napp', 'nbench'):
        if c in A:
            A[c] = pd.to_numeric(A[c], errors='coerce')
    print('loaded', len(G), len(A), len(P), flush=True)
    R = SP.club_ratings(G, A, V)
    A = SP.add_value(A, R)
    O, scale = SP.outcome(A, P)
    TG = SP.team_games(G)
    done = O[O.s22 <= SP.COHORTS[1]]
    fitj = json.load(open(SP.FIT))
    out = {}
    for md in SNAPS:
        xs = []
        for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
            X = SP.features(A, P, V, R, TG, t, SP.snapdate(t, md))
            X['mvlvl'] = SP.mv_level(X.mv)
            X = X[X.index.isin(done.index) & X.old]
            X['mvd'] = X.mv * np.exp(fitj['mvRef']['%02d-%02d' % md] - X.mvlvl)
            F = SP.design(X)
            F['htcm'] = X.ht.values
            F['grp'] = X.grp.values
            F['role'] = P.sub_position.reindex(X.index).map(ROLE).values
            F['fv_out'] = done.fv.reindex(X.index).values
            F['s22'] = done.s22.reindex(X.index).values
            F['t'] = t
            F['pid'] = X.index.values
            xs.append(F.reset_index(drop=True))
            print('rows', md, t, len(F), flush=True)
        out[md] = pd.concat(xs, ignore_index=True)
    pickle.dump(out, open(fn, 'wb'))
    return out


def frame_cols(Z):
    h = Z.htcm
    for key, col in (('grp', 'htz_grp'), ('role', 'htz_role')):
        g = Z[key].fillna(Z.grp.map({'G': 'GK', 'D': 'CB', 'M': 'CM', 'F': 'ST'}) if key == 'role' else 'M')
        st = h.groupby(g).agg(['mean', 'std'])
        Z[col] = ((h - g.map(st['mean'])) / g.map(st['std'])).fillna(0.0)
    Z['ht_d'] = Z.ht * Z.grp.eq('D')
    Z['ht_f'] = Z.ht * Z.grp.eq('F')
    Z['ht_cb'] = Z.ht * Z.role.eq('CB')
    Z['ht_st'] = Z.ht * Z.role.eq('ST')
    return Z


def main():
    Rw = rows()
    kept = json.load(open(SP.FIT))['kept']
    rest = [c for c in kept if c not in ('ht', 'ht_gk')]
    tests = {'htz_grp (replaces ht, ht_gk)': (rest, ['htz_grp']), '+htz_grp': (kept, ['htz_grp']),
             'htz_role (replaces ht, ht_gk)': (rest, ['htz_role']), 'ht_by_grp': (kept, ['ht_d', 'ht_f']),
             'ht_cb_st': (kept, ['ht_cb', 'ht_st'])}
    out = {'kept': kept, 'snap': {}}
    allc = {}
    for md, Z in Rw.items():
        key = '%02d-%02d' % md
        Z = frame_cols(Z)
        y, co = Z.fv_out.values, Z.s22.values
        e, p = SP.loso(Z, y, co, kept)
        res = {'n': int(len(Z)), 'mse': round(float((e ** 2).mean()), 2), 'htCov': round(float(Z.htcm.notna().mean()), 3),
               'roleCov': round(float(Z.role.notna().mean()), 3),
               'htByGrp': {g: [round(float(v), 1) for v in Z.htcm[Z.grp.eq(g)].agg(['mean', 'std'])] for g in 'GDMF'},
               'cands': {}}
        for nm, (base, add) in tests.items():
            # an addition goes through the board's own test; a replacement swaps the pooled height out of the kept model
            r = TR.test(Z, kept, add) if base is kept else swap_test(Z, kept, base + add)
            r['p1'] = round(float(1 - HS.t_cdf(r['t'], r['of'] - 1)), 4)
            res['cands'][nm] = r
            allc[f'{key} {nm}'] = r
            print(key, nm, r, flush=True)
        out['snap'][key] = res
    ks = sorted(allc, key=lambda k: allc[k]['p1'])
    for i, k in enumerate(ks):
        allc[k]['holm'] = bool(all(allc[j]['p1'] <= .05 / (len(ks) - n) for n, j in enumerate(ks[:i + 1])))
    out['nTests'] = len(allc)
    out['passed'] = [k for k, v in allc.items() if v['pass'] and v['holm']]
    os.makedirs(OUTD, exist_ok=True)
    json.dump(out, open(os.path.join(OUTD, 'soccer_frame.json'), 'w'), indent=1, allow_nan=False)
    print('passed', out['passed'])


def swap_test(Z, kept, new):
    """TR.test's numbers for the model `new` against the kept model (same gate)"""
    y, t, co = Z.fv_out.values, Z.t.values, Z.s22.values
    e0, p0 = SP.loso(Z, y, co, kept)
    e1, p1 = SP.loso(Z, y, co, new)
    gain, tt, wins, of = TR.folds_t(e0, e1, co)
    es0, _ = SP.loso(Z, y, t, kept)
    es1, _ = SP.loso(Z, y, t, new)
    sg, st, sw, so = TR.folds_t(es0, es1, t)
    b50 = TR.top_mask(p0, t)
    tr, te = Z.t.between(*TR.FWD).values, ~Z.t.between(*TR.FWD).values
    b0, b1 = SP.ols(Z[tr], y[tr], kept), SP.ols(Z[tr], y[tr], new)
    f0, f1 = SP.pred(Z[te], kept, b0), SP.pred(Z[te], new, b1)
    fb50 = TR.top_mask(f0, t[te])
    coef = dict(zip(['const'] + new, SP.ols(Z, y, new)))
    r = {'gain': round(gain, 3), 't': round(tt, 2), 'wins': wins, 'of': of,
         'seasonGain': round(sg, 3), 'seasonT': round(st, 2), 'seasonWins': sw, 'seasonOf': so,
         'b50Mse': round(float((e1[b50] ** 2).mean() - (e0[b50] ** 2).mean()), 3),
         'top50': round(TR.top_mean(p1, y, t) - TR.top_mean(p0, y, t), 2),
         'fwdMse': round(float(((y[te] - f1) ** 2).mean() - ((y[te] - f0) ** 2).mean()), 3),
         'fwdB50Mse': round(float(((y[te] - f1)[fb50] ** 2).mean() - ((y[te] - f0)[fb50] ** 2).mean()), 3),
         'fwdTop50': round(TR.top_mean(f1, y[te], t[te]) - TR.top_mean(f0, y[te], t[te]), 2),
         'coef': {c: round(float(coef[c]), 3) for c in new if c not in kept}}
    r['cv'] = r['t'] >= 2 and r['wins'] >= math.ceil(r['of'] * 2 / 3)
    r['pass'] = bool(r['cv'] and r['b50Mse'] <= 0 and r['top50'] >= 0 and r['fwdMse'] <= 0 and r['fwdB50Mse'] <= 0
                     and r['fwdTop50'] >= -.1)
    return r


if __name__ == '__main__':
    main()
