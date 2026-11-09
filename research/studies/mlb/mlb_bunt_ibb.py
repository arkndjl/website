# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Studies mlb-sac-bunt and mlb-ibb: win-expectancy change of sacrifice-bunt tries and intentional walks, 2015-2025."""
import importlib.util, json, numpy as np, pandas as pd
spec = importlib.util.spec_from_file_location("c", "/home/user/website/research/studies/mlb/mlb_common.py"); c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
d = c.load()
we = c.WE(d)
d = d[~d.dh7].copy()
d = c.add_we(d, we)
q, lg = c.batter_quality(d)
d['pa_id'] = d.groupby('gid').pa.cumsum() - d.pa
d['we_half_end'] = d.groupby('half', sort=False).we_post.transform('last')
d['buntsig'] = ((d.bunt == 1) | d.pitches.fillna('').str.contains('[LMO]', regex=True)).astype(int)
g = d.groupby(['gid', 'pa_id'], sort=False)
P = g.first()[['season', 'inning', 'home_bat', 'outs_pre', 'bases', 'diff_home', 'we_pre', 'ghost', 'pitteam', 'we_half_end']]
L = g.last()[['pa', 'we_post', 'batter', 'bat_f', 'iw', 'sh']]
P = P.join(L).join(g.buntsig.max().rename('bunt_att'))
P = P[(P.pa == 1)].reset_index()
P['dwe'] = np.where(P.home_bat == 1, 1, -1) * (P.we_post - P.we_pre)  # batting-team view
P['q'] = q.reindex(pd.MultiIndex.from_arrays([P.season, P.batter])).values - lg
P['dwe_h'] = np.where(P.home_bat == 1, 1, -1) * (P.we_half_end - P.we_pre)  # to end of half-inning
P['next_batter'] = P.groupby(['gid', 'home_bat']).batter.shift(-1)
P['q_next'] = (q.reindex(pd.MultiIndex.from_arrays([P.season, P.next_batter])).values - lg)
P['q_next'] = P.q_next.fillna(0.0)
P['bdiff'] = np.where(P.home_bat == 1, P.diff_home, -P.diff_home)
P['late_close'] = (P.inning >= 7) & (P.bdiff.abs() <= 1)
P = P[(P.inning <= 9) & P.dwe.notna() & P.dwe_h.notna() & P.q.notna()]
print(len(P), P.dwe.mean())

def ols_cl(z, y, treat, ctrl=('q', 'q_next')):
    """y ~ treat + q + season FE + inning x score-diff cell FE; SE clustered by game."""
    cell = z.inning.clip(upper=9).astype(str) + '_' + z.bdiff.clip(-3, 3).astype(str) + '_' + z.season.astype(str)
    cols = [treat] + list(ctrl)
    X = z[cols].astype(float); Y = z[y].astype(float)
    Xd = X - X.groupby(cell.values).transform('mean'); Yd = Y - Y.groupby(cell.values).transform('mean')
    A = Xd.values; b = Yd.values
    XtX = A.T @ A; beta = np.linalg.solve(XtX, A.T @ b); u = b - A @ beta
    S = pd.DataFrame(A * u[:, None]).groupby(z.gid.values).sum().values
    V = np.linalg.inv(XtX) @ (S.T @ S) @ np.linalg.inv(XtX)
    return beta[0], np.sqrt(V[0, 0]), z[treat].sum(), len(z)

# ---------------- sacrifice bunts (non-pitchers)
B = P[(P.bat_f != 1) & (P.outs_pre == 0) & P.bases.isin([1, 2, 3]) & (P.iw == 0)]
labs = {1: '1st', 2: '2nd', 3: '1st+2nd'}
bres = {}
for b in [1, 2, 3]:
    for lc in [False, True]:
        z = B[(B.bases == b) & ((B.late_close) if lc else True)]
        bres[(b, lc)] = ols_cl(z, 'dwe', 'bunt_att')
        raw = z.groupby('bunt_att').dwe.mean()
        bres[(b, lc, 'h')] = ols_cl(z, 'dwe_h', 'bunt_att')
        print('   half-inning outcome', np.round(bres[(b, lc, 'h')][:2], 4))
        print('bunt', labs[b], 'late_close' if lc else 'all', np.round(bres[(b, lc)][:2], 4), bres[(b, lc)][2:], 'raw', np.round(raw[1] - raw[0], 4),
              'q', round(z[z.bunt_att == 1].q.mean(), 4), round(z[z.bunt_att == 0].q.mean(), 4))
rate = B.groupby('season').bunt_att.mean()
print(rate.round(4).to_dict())
bsplit = {}
for nm, yrs in [('2015-19', range(2015, 2020)), ('2020-25', range(2020, 2026))]:
    bsplit[nm] = {b: ols_cl(B[(B.bases == b) & B.season.isin(yrs)], 'dwe_h', 'bunt_att') for b in [1, 2, 3]}
    print(nm, {b: np.round(v[:2], 4) for b, v in bsplit[nm].items()})

# ---------------- intentional walks: defense view, compare IBB vs pitching to the batter
P['dwe_def'] = -P.dwe
P['dwe_h_def'] = -P.dwe_h
I = P[(P.bat_f != 1)]
ilabs = {(2, 1): '2nd, 1 out', (2, 2): '2nd, 2 out', (6, 1): '2nd+3rd, 1 out', (6, 0): '2nd+3rd, 0 out', (4, 1): '3rd, 1 out', (4, 2): '3rd, 2 out', (6, 2): '2nd+3rd, 2 out'}
ires = {}
for (b, o), lab in ilabs.items():
    for lc in [False, True]:
        z = I[(I.bases == b) & (I.outs_pre == o) & ((I.late_close) if lc else True)]
        if z.iw.sum() < 30:
            continue
        ires[(b, o, lc)] = ols_cl(z, 'dwe_def', 'iw')
        ires[(b, o, lc, 'h')] = ols_cl(z, 'dwe_h_def', 'iw')
        print('   half-inning outcome', np.round(ires[(b, o, lc, 'h')][:2], 4), 'q_next ibb', round(z[z.iw == 1].q_next.mean(), 4), round(z[z.iw == 0].q_next.mean(), 4))
        print('ibb', lab, 'late_close' if lc else 'all', np.round(ires[(b, o, lc)][:2], 4), ires[(b, o, lc)][2:],
              'q ibb', round(z[z.iw == 1].q.mean(), 4), 'q other', round(z[z.iw == 0].q.mean(), 4))
irate = P.groupby('season').iw.sum()
print(irate.to_dict())
isplit = {}
for nm, yrs in [('2015-19', range(2015, 2020)), ('2020-25', range(2020, 2026))]:
    z = I[I.season.isin(yrs)]
    isplit[nm] = {k: ols_cl(z[(z.bases == k[0]) & (z.outs_pre == k[1])], 'dwe_h_def', 'iw') for k in [(2, 1), (2, 2), (6, 1)]}
    print(nm, {k: np.round(v[:2], 4) for k, v in isplit[nm].items()})

for nm, yrs in [('2015-19', range(2015, 2020)), ('2020-25', range(2020, 2026))]:
    bsplit[nm + 'pa'] = {b: ols_cl(B[(B.bases == b) & B.season.isin(yrs)], 'dwe', 'bunt_att') for b in [1, 2, 3]}
    z = I[I.season.isin(yrs)]
    isplit[nm + 'pa'] = {k: ols_cl(z[(z.bases == k[0]) & (z.outs_pre == k[1])], 'dwe_def', 'iw') for k in [(2, 1), (2, 2), (6, 1)]}
    print(nm, 'PA-level', {b: np.round(v[:2], 4) for b, v in bsplit[nm + 'pa'].items()}, {k: np.round(v[:2], 4) for k, v in isplit[nm + 'pa'].items()})

pt = lambda r: f"{r[0]*100:+.1f} pts (CI {(r[0]-1.96*r[1])*100:+.1f} to {(r[0]+1.96*r[1])*100:+.1f})"
def point(lab, r):
    return {'x': lab, 'y': round(r[0] * 100, 2), 'lo': round((r[0] - 1.96 * r[1]) * 100, 2), 'hi': round((r[0] + 1.96 * r[1]) * 100, 2), 'n': int(r[3])}
# ---- sac bunt JSON
s1, s2_ = [], []
for b in [1, 2, 3]:
    for lc in [False, True]:
        lab = labs[b] + (', late' if lc else ', all')
        s1.append(point(lab, bres[(b, lc)])); s2_.append(point(lab, bres[(b, lc, 'h')]))
nBatt = int(B.bunt_att.sum())
bt = {
    "id": "mlb-sac-bunt", "sport": "MLB",
    "question": "Do sacrifice-bunt tries with nobody out gain win probability?",
    "answer": f"No. Bunt tries cost {-bres[(1, False)][0]*100:.1f} to {-bres[(3, False)][0]*100:.1f} win-prob pts per try vs swinging; late and close, up to {-bres[(3, True)][0]*100:.1f}.",
    "findings": [
        f"Runner on 1st, 0 out: {pt(bres[(1, False)])}, n={bres[(1, False)][2]:,} tries of {bres[(1, False)][3]:,} PAs.",
        f"Runner on 2nd: {pt(bres[(2, False)])}. 1st and 2nd: {pt(bres[(3, False)])}.",
        f"1st and 2nd, 7th inning on, within 1 run: {pt(bres[(3, True)])}, n={bres[(3, True)][2]:,} tries.",
        f"Realized WE to end of inning: no CI excludes 0 (1st: {bres[(1, False, 'h')][0]*100:+.1f} pts). Try rate {rate[2015]:.1%} 2015, {rate[2025]:.1%} 2025.",
    ],
    "method": "Non-pitcher PAs, 0 out, innings 1-9. Bunt try = bunt in play or foul/missed bunt. Outcome: change in empirical WE over the PA. "
              "OLS with batter and on-deck season wOBA, inning x score x season cells; SE clustered by game.",
    "data": f"Retrosheet play-by-play, 2015-2025 regular season, {len(B):,} PAs with runners on and 0 out, {nBatt:,} bunt tries.",
    "n": int(len(B)), "robust": True, "interest": 2,
    "split_check": f"PA-level loss in both eras for 2nd and 1st+2nd; runner on 1st: {bsplit['2015-19pa'][1][0]*100:+.1f} pts 2015-19, "
                   f"{bsplit['2020-25pa'][1][0]*100:+.1f} 2020-25 (n.s.).",
    "chart": {"type": "bar", "title": "Bunt try minus swing away, 0 out",
              "x_label": "runners, game state", "y_label": "win-prob pts", "y_fmt": "signed", "x_reverse": False,
              "ref": {"y": 0, "label": "no effect"}, "mark": None,
              "series": [{"name": "over the PA", "points": s1}, {"name": "to end of inning", "points": s2_}]},
}
json.dump(bt, open(c.OUT + '/mlb-sac-bunt.json', 'w'), indent=2)
# ---- IBB JSON
keys = [(2, 1), (2, 2), (4, 1), (4, 2), (6, 1), (6, 2)]
i1 = [point(ilabs[k], ires[(k[0], k[1], False)]) for k in keys]
i2 = [point(ilabs[k], ires[(k[0], k[1], False, 'h')]) for k in keys]
nI = int(I.iw.sum())
r21, r21h, r21l = ires[(2, 1, False)], ires[(2, 1, False, 'h')], ires[(2, 1, True, 'h')]
r61, r61h = ires[(6, 1, False)], ires[(6, 1, False, 'h')]
ib = {
    "id": "mlb-ibb", "sport": "MLB",
    "question": "Do intentional walks gain win probability for the defense?",
    "answer": f"Mostly no. Runner on 2nd, 1 out: IBB costs the defense {-r21h[0]*100:.1f} win-prob pts. Other states: no gain distinguishable from 0.",
    "findings": [
        f"Runner on 2nd, 1 out: {pt(r21h)}, n={r21h[2]:,} IBB; late and close {pt(r21l)}.",
        f"2nd and 3rd, 1 out: {pt(r61)} over the PA but {r61h[0]*100:+.1f} (CI {(r61h[0]-1.96*r61h[1])*100:+.1f} to {(r61h[0]+1.96*r61h[1])*100:+.1f}) to end of inning.",
        f"IBB batters: +{(I[I.iw==1].q.mean()-I[I.iw==0].q.mean())*1000:.0f} pts of season wOBA over other batters in these states; in the model.",
        f"IBB per season: {irate[2016]} in 2016, {irate[2025]} in 2025 (non-pitcher batters, innings 1-9).",
    ],
    "method": "Defense-view change in empirical WE, from the PA start to the end of the half-inning (main) and over the PA. OLS with batter "
              "and on-deck season wOBA, inning x score x season cells; SE clustered by game. Compared with pitching to the batter in the same state.",
    "data": f"Retrosheet play-by-play, 2015-2025 regular season, {nI:,} intentional walks to non-pitchers in innings 1-9.",
    "n": nI, "robust": True, "interest": 3,
    "split_check": f"Runner on 2nd, 1 out: {isplit['2015-19'][(2, 1)][0]*100:+.1f} pts 2015-19, {isplit['2020-25'][(2, 1)][0]*100:+.1f} 2020-25 "
                   f"(SE {isplit['2015-19'][(2, 1)][1]*100:.1f}, {isplit['2020-25'][(2, 1)][1]*100:.1f}).",
    "chart": {"type": "bar", "title": "IBB minus pitching to the batter, defense view",
              "x_label": "runners, outs", "y_label": "win-prob pts", "y_fmt": "signed", "x_reverse": False,
              "ref": {"y": 0, "label": "no effect"}, "mark": None,
              "series": [{"name": "to end of inning", "points": i2}, {"name": "over the PA", "points": i1}]},
}
json.dump(ib, open(c.OUT + '/mlb-ibb.json', 'w'), indent=2)
for o in [bt, ib]:
    print(json.dumps({k: o[k] for k in ['answer', 'findings', 'split_check']}, indent=1))
