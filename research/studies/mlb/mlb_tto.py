# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Study mlb-tto: times-through-the-order penalty, within pitcher-season, with batter quality and pitch count."""
import importlib.util, json, numpy as np, pandas as pd
spec = importlib.util.spec_from_file_location("c", "/home/user/website/research/studies/mlb/mlb_common.py"); c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
d = c.load()
d = d[~d.dh7].copy()
q, lg = c.batter_quality(d)
# starter = first pitcher of each team in each game
first = d.groupby(['gid', 'pitteam']).pitcher.transform('first')
d['starter'] = d.pitcher == first
# pitch count before the PA (PA rows carry the full pitch sequence)
d['np_pa'] = np.where(d.pa == 1, d.nump.fillna(0), 0)
d['pc'] = d.groupby(['gid', 'pitcher']).np_pa.cumsum() - d.np_pa
x = d[c.woba_pa(d)].copy()
x['y'] = c.woba_num(x)
x['q'] = q.reindex(pd.MultiIndex.from_arrays([x.season, x.batter])).values - lg
x['same'] = (x.bathand == x.pithand).astype(float)
x['home'] = (x.home_bat == 0).astype(float)  # pitcher at home
x['bf'] = x.groupby(['gid', 'pitcher']).cumcount() + 1  # among wOBA PAs; close to batters faced
x['tto'] = x.groupby(['gid', 'pitcher', 'batter']).cumcount() + 1
x['ps'] = x.pitcher + '_' + x.season.astype(str)
# season-level league adjustment
x['yl'] = x.y - x.groupby('season').y.transform('mean')

def fe_ols(df, cols, fe='ps', cl='gid'):
    X = df[cols].astype(float)
    Y = df['yl'].astype(float)
    Xd = X - X.groupby(df[fe]).transform('mean')
    Yd = Y - Y.groupby(df[fe]).transform('mean')
    A = Xd.values; b = Yd.values
    XtX = A.T @ A
    beta = np.linalg.solve(XtX, A.T @ b)
    u = b - A @ beta
    S = pd.DataFrame(A * u[:, None]).groupby(df[cl].values).sum().values
    V = np.linalg.inv(XtX) @ (S.T @ S) @ np.linalg.inv(XtX)
    return pd.Series(beta, cols), pd.Series(np.sqrt(np.diag(V)), cols)

s = x[x.starter & (x.tto <= 3)].copy()
s['t2'] = (s.tto == 2).astype(float); s['t3'] = (s.tto == 3).astype(float)
s['pc_c'] = s.pc / 10.0
res = {}
for name, cols in [('A', ['t2', 't3']), ('B', ['t2', 't3', 'q', 'same', 'home']),
                   ('C', ['t2', 't3', 'q', 'same', 'home', 'pc_c'])]:
    b, se = fe_ols(s, cols)
    res[name] = (b, se)
    print(name, {k: (round(b[k], 4), round(se[k], 4)) for k in cols})
# Brill-style: linear trend in batters faced + jumps at 10 and 19
s['bfl'] = s.bf / 9.0
s['j2'] = (s.bf >= 10).astype(float); s['j3'] = (s.bf >= 19).astype(float)
sb = s[s.bf <= 27]
bD, seD = fe_ols(sb, ['bfl', 'j2', 'j3', 'q', 'same', 'home'])
print('D', bD.round(4).to_dict(), seD.round(4).to_dict())
bE, seE = fe_ols(sb, ['j2', 'j3', 'q', 'same', 'home', 'pc_c'])
print('E (pc instead of bf trend)', bE.round(4).to_dict(), seE.round(4).to_dict())
# split by halves
for nm, yrs in [('2015-19', range(2015, 2020)), ('2020-25', range(2020, 2026))]:
    bb, ss = fe_ols(sb[sb.season.isin(yrs)], ['bfl', 'j2', 'j3', 'q', 'same', 'home'])
    print(nm, bb.round(4).to_dict(), ss.round(4).to_dict())
# bins of 3 batters faced
sb = sb.copy(); sb['bin'] = (sb.bf - 1) // 3
dums = []
for k in range(1, 9):
    sb[f'b{k}'] = (sb.bin == k).astype(float); dums.append(f'b{k}')
bF, seF = fe_ols(sb, dums + ['q', 'same', 'home'])
# pooled covariate adjustment for levels (starters and relievers)
allx = x.copy()
A = np.column_stack([np.ones(len(allx)), allx.q, allx.same, allx.home])
beta = np.linalg.lstsq(A, allx.yl.values, rcond=None)[0]
allx['adj'] = allx.yl - A[:, 1:] @ beta[1:] + lg
st = allx[allx.starter & (allx.bf <= 27)]
base = st.adj.mean()
coef = np.r_[0, bF[dums].values]; cse = np.r_[0, seF[dums].values]
w = st.groupby((st.bf - 1) // 3).size().values
coef_c = coef - np.average(coef, weights=w)
rel = allx[~allx.starter & (allx.inning >= 6)]
rm, rlo, rhi = c.cluster_mean_ci(rel.adj, rel.gid)
print('reliever inn6+ adj wOBA', rm, rlo, rhi, len(rel), 'starter mean', base)
for t in [1, 2, 3]:
    z = allx[allx.starter & (allx.tto == t)]
    print('starter tto', t, c.cluster_mean_ci(z.adj, z.gid), len(z))
pts = []
for k in range(9):
    n = int((sb.bin == k).sum())
    pts.append({'x': 3 * k + 2, 'y': round(base + coef_c[k], 4), 'lo': round(base + coef_c[k] - 1.96 * cse[k], 4),
                'hi': round(base + coef_c[k] + 1.96 * cse[k], 4), 'n': n})
print(pts)

splitB = {}
for nm, yrs in [('2015-19', range(2015, 2020)), ('2020-25', range(2020, 2026))]:
    bb, ss = fe_ols(s[s.season.isin(yrs)], ['t2', 't3', 'q', 'same', 'home'])
    splitB[nm] = (bb, ss); print('B', nm, bb.round(4).to_dict(), ss.round(4).to_dict())
dsp = {}
for nm, yrs in [('2015-19', range(2015, 2020)), ('2020-25', range(2020, 2026))]:
    dsp[nm] = fe_ols(sb[sb.season.isin(yrs)], ['bfl', 'j2', 'j3', 'q', 'same', 'home'])
t3m = {t: c.cluster_mean_ci(allx[allx.starter & (allx.tto == t)].adj, allx[allx.starter & (allx.tto == t)].gid) for t in [1, 3]}
B, SE = res['B']; C, SEC = res['C']
w3 = lambda v: f"{v:.3f}".replace("0.", ".", 1)
s3 = lambda v: (f"{v:+.3f}").replace("0.", ".", 1)
f = lambda b, se, k, m=1: f"{s3(m*b[k])} (CI {s3(m*(b[k]-1.96*se[k]))} to {s3(m*(b[k]+1.96*se[k]))})"
e1, e2 = dsp['2015-19'], dsp['2020-25']
n = int(len(s))
out = {
    "id": "mlb-tto", "sport": "MLB",
    "question": "Does the times-through-the-order penalty justify pulling starters before the 3rd time?",
    "answer": f"For an average starter, yes. 3rd time: {s3(B['t3'])} wOBA vs 1st (same pitcher), {w3(t3m[3][0])} vs relievers {w3(rm)}.",
    "findings": [
        f"Within pitcher-season: 2nd time {f(B, SE, 't2')}, 3rd time {f(B, SE, 't3')} wOBA vs 1st.",
        f"Pitch count adds nothing: {f(C, SEC, 'pc_c', 10)} per 100 pitches; 3rd time stays {s3(C['t3'])}.",
        f"Jump at batter 19: {s3(e1[0]['j3'])} (SE {w3(e1[1]['j3'])}) in 2015-19, {s3(e2[0]['j3'])} (SE {w3(e2[1]['j3'])}) in 2020-25, a smooth rise instead.",
        f"Batter-adjusted wOBA: starters 1st time {w3(t3m[1][0])}, 3rd time {w3(t3m[3][0])}; relievers inn. 6+ {w3(rm)} (n={len(rel):,}).",
    ],
    "method": "OLS on PA wOBA with pitcher-season fixed effects, batter-season wOBA, platoon and home; SE clustered by game. "
              "Survivors to the 3rd time are pitchers having better days, so the penalty is if anything understated.",
    "data": f"Retrosheet play-by-play, 2015-2025 regular season, {n:,} starter PAs (1st-3rd time), {s.gid.nunique():,} games.",
    "n": n, "robust": True, "interest": 3,
    "split_check": f"3rd-time penalty {s3(splitB['2015-19'][0]['t3'])} in 2015-19 and {s3(splitB['2020-25'][0]['t3'])} in 2020-25; "
                   "discrete jumps only in 2015-19.",
    "chart": {"type": "line", "title": "Starter wOBA allowed by batters faced, within pitcher",
              "x_label": "batters faced (3-batter bins)", "y_label": "wOBA allowed", "y_fmt": "num", "x_reverse": False,
              "ref": {"y": round(rm, 3), "label": "relievers, inn. 6+"}, "mark": {"x": 18.5, "label": "3rd time through"},
              "series": [{"name": "starters", "points": [{k: (float(v) if k != 'n' and k != 'x' else v) for k, v in p.items()} for p in pts]}]},
}
json.dump(out, open(c.OUT + '/mlb-tto.json', 'w'), indent=2)
print(json.dumps({k: out[k] for k in ['answer', 'findings', 'split_check']}, indent=1))
