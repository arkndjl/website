# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA XPM / VORX staple audit (Nov 3 2026) -> data/nba_xpm_research_nov03.json. Research only.

Pre-registered (written before any run):
  C1  one DPM weight w (XPM = w DPM + (1-w) BPM, both sides), grid 0..1 by .1, picked on training seasons only
      (inner leave-one-season-out inside each outer training set).
  C2  separate O and D DPM weights (wo, wd), same grid and nesting.
  C3  shrunk sxpm (board column) in place of raw xpm as the prior-season value.
  Frame (same as project files cbb/xpm): season t-1 value x actual season-t minutes (5 x share of team minutes, stints,
  no TOT rows) -> team ORtg / DRtg vs league, net = O + D; calibration (intercept, scale, rookie, shrink by prior
  MP / (MP + 600)) refit on training seasons. Splits: forward-chained (scored 2013-26) and LOSO (2011-26).
  Score: per-season MSE of net (and of W% for C3), paired t over seasons new - base, seasons improved.
  Pass: t < 0 in both splits, Holm-corrected one-sided p < .05 over the 3 candidates (worse split), and a majority
  of seasons improved.
  Audit (not a candidate): VORX constants (k, replacement r) refit same-season LOSO on the published files.

Inputs: static/data/nba-xpm/<S>.json (values by bbref id), project files cbb/xpm players.csv (stints) + teams.csv.
  python3 scripts/nba_xpm_research_nov03.py
"""
import json, math, os, sys
import numpy as np, pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
X = os.environ.get('XPM_PF', '/mnt/project-files/cbb/xpm')
OUT = os.path.join(ROOT, 'data', 'nba_xpm_research_nov03.json')
K = 600.0
YRS = list(range(2011, 2027))
G = [round(0.1 * i, 1) for i in range(11)]

T = pd.read_csv(f'{X}/teams.csv')
for c in ('off_rtg', 'def_rtg', 'wins', 'losses'):
    T[c] = pd.to_numeric(T[c].astype(str).str.replace('+', '', regex=False), errors='coerce')
T['o_rel'] = T.off_rtg - T.groupby('year').off_rtg.transform('mean')
T['d_rel'] = T.groupby('year').def_rtg.transform('mean') - T.def_rtg
T['n_rel'] = T.o_rel + T.d_rel
T['wpct'] = T.wins / (T.wins + T.losses)

P = pd.read_csv(f'{X}/players.csv', low_memory=False, usecols=['year', 'pid', 'tm', 'mp'])
P['mp'] = pd.to_numeric(P.mp, errors='coerce').fillna(0)
ST = P[~P.tm.astype(str).str.match(r'^(TOT|\dTM)$') & (P.mp > 0)].copy()
ST['w'] = 5 * ST.mp / ST.groupby(['year', 'tm']).mp.transform('sum')

rows = []
for s in range(2010, 2027):
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{s}.json')))
    for p in d['players']:
        if p.get('pr'): continue
        rows.append({'year': s, 'pid': p['id'], 'mp': p['mp'], 'g': d['games'],
                     **{k: p.get(k) for k in ('bpm', 'obpm', 'dbpm', 'dpm', 'odpm', 'ddpm', 'xpm', 'oxpm', 'dxpm', 'sxpm', 'soxpm', 'sdxpm', 'vorx')}})
V = pd.DataFrame(rows)
for c in V.columns[3:]: V[c] = pd.to_numeric(V[c], errors='coerce')
pr = V.copy(); pr['year'] += 1; pr = pr.rename(columns={'mp': 'pmp'})
S = ST.merge(pr, on=['year', 'pid'], how='left')
S['has'] = S.pmp.notna() & (S.pmp > 0) & S.obpm.notna()
S['pmp'] = S.pmp.fillna(0)
R = np.where(S.has, S.pmp / (S.pmp + K), 0.0)


def blend(wo, wd):
    """prior-season (o, d) values at DPM weights wo / wd; BPM alone where no DPM"""
    o = np.where(S.odpm.notna(), wo * S.odpm.fillna(0) + (1 - wo) * S.obpm, S.obpm)
    d = np.where(S.ddpm.notna(), wd * S.ddpm.fillna(0) + (1 - wd) * S.dbpm, S.dbpm)
    return o, d


def design(o, d):
    out = pd.DataFrame({'year': S.year, 'tm': S.tm, 'rook': S.w * ~S.has, 'shr': S.w * S.has * (1 - R),
                        'o': S.w * R * np.where(S.has, o, 0), 'd': S.w * R * np.where(S.has, d, 0)})
    g = out.groupby(['year', 'tm']).sum().reset_index()
    g = g.merge(T[['year', 'tm', 'o_rel', 'd_rel', 'n_rel', 'wpct']], on=['year', 'tm'])
    return g[g.year.isin(YRS)].reset_index(drop=True)


def ols(Xm, y): return np.linalg.lstsq(np.c_[np.ones(len(Xm)), Xm], y, rcond=None)[0]


def predict(D, train, test, target=None):
    """net (or W%) prediction on test rows from a calibration fit on train rows"""
    if target == 'wpct':
        Xs = D[['rook', 'shr', 'o', 'd']].values
        b = ols(Xs[train], D.wpct.values[train]); return np.c_[np.ones(test.sum()), Xs[test]] @ b
    p = 0
    for s in 'od':
        Xs = D[['rook', 'shr', s]].values
        b = ols(Xs[train], D[f'{s}_rel'].values[train]); p = p + np.c_[np.ones(test.sum()), Xs[test]] @ b
    return p


def oos_err(D, split, target=None, years=YRS):
    """squared error per team-season, held out by split; NaN where not scored"""
    Y = D.year.values; e = np.full(len(D), np.nan); y = D.wpct.values if target == 'wpct' else D.n_rel.values
    for q in years:
        tr = np.isin(Y, years) & ((Y < q) if split == 'fwd' else (Y != q)); te = Y == q
        if len(np.unique(Y[tr])) < 2: continue
        e[te] = (predict(D, tr, te, target) - y[te]) ** 2
    return e


def inner_mse(D, years):
    """LOSO MSE inside the given seasons only (for picking a weight without the held-out season)"""
    Y = D.year.values; tot, n = 0.0, 0
    for q in years:
        tr = np.isin(Y, years) & (Y != q); te = Y == q
        tot += ((predict(D, tr, te) - D.n_rel.values[te]) ** 2).sum(); n += te.sum()
    return tot / n


DS = {}
def D_of(wo, wd):
    if (wo, wd) not in DS: DS[(wo, wd)] = design(*blend(wo, wd))
    return DS[(wo, wd)]


def nested(grid, split):
    """outer held-out error with the weight picked by inner LOSO on the outer training seasons"""
    D0 = D_of(.5, .5); Y = D0.year.values; e = np.full(len(D0), np.nan); picks = {}
    for q in YRS:
        trs = [y for y in YRS if (y < q if split == 'fwd' else y != q)]
        if len(trs) < 3: continue
        best = min(grid, key=lambda g: inner_mse(D_of(*g), trs))
        picks[q] = list(best); D = D_of(*best)
        tr = np.isin(Y, trs); te = Y == q
        e[te] = (predict(D, tr, te) - D.n_rel.values[te]) ** 2
    return e, picks


def paired(e_new, e_base, Y):
    m = ~np.isnan(e_new) & ~np.isnan(e_base); qs = sorted(np.unique(Y[m]))
    d = np.array([e_new[m & (Y == q)].mean() - e_base[m & (Y == q)].mean() for q in qs])
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    from math import erf
    # one-sided p from t with n-1 df (normal approx is too loose for 14-16 seasons: use a Student-t cdf by series)
    p = student_cdf(t, len(d) - 1)
    return {'rmse_new': round(float(np.sqrt(e_new[m].mean())), 4), 'rmse_base': round(float(np.sqrt(e_base[m].mean())), 4),
            't': round(t, 2), 'p_one_sided': round(p, 4), 'improved': f'{int((d < 0).sum())}/{len(d)}', 'n': int(m.sum())}


def student_cdf(t, df):
    x = df / (df + t * t)
    ib = betainc(df / 2, .5, x)
    return .5 * ib if t < 0 else 1 - .5 * ib


def betainc(a, b, x, n=200):
    """regularized incomplete beta by continued fraction (Numerical Recipes)"""
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x > (a + 1) / (a + b + 2): return 1 - betainc(b, a, 1 - x, n)
    c, d = 1.0, 1 - (a + b) * x / (a + 1); d = 1 / d; h = d
    for m in range(1, n):
        for k in (0, 1):
            if k == 0: num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
            else: num = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
            d = 1 + num * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
            c = 1 + num / c; c = c if abs(c) > 1e-30 else 1e-30
            h *= d * c
    return math.exp(lb) * h / a


res = {'frame': 'season t-1 value x season t stint minutes -> team net rel; calibration refit in training seasons',
       'fixed_grid': {}, 'candidates': {}}
base = {sp: oos_err(D_of(.5, .5), sp) for sp in ('fwd', 'loso')}
Y = D_of(.5, .5).year.values
for w in G:
    res['fixed_grid'][str(w)] = {sp: round(float(np.sqrt(np.nanmean(oos_err(D_of(w, w), sp)))), 4) for sp in ('fwd', 'loso')}
    print('w', w, res['fixed_grid'][str(w)], flush=True)

for nm, grid in (('C1_one_weight', [(w, w) for w in G]), ('C2_o_d_weights', [(a, b) for a in G for b in G])):
    row = {}
    for sp in ('fwd', 'loso'):
        e, picks = nested(grid, sp); row[sp] = paired(e, base[sp], Y); row[sp]['picks'] = {str(k): v for k, v in picks.items()}
    res['candidates'][nm] = row; print(nm, {k: {kk: vv for kk, vv in v.items() if kk != 'picks'} for k, v in row.items()}, flush=True)

# C3: shrunk board values (soxpm / sdxpm) in place of raw xpm; same frame, net and W%
o_s = np.where(S.soxpm.notna(), S.soxpm, S.oxpm); d_s = np.where(S.sdxpm.notna(), S.sdxpm, S.dxpm)
Ds = design(o_s, d_s); Dr = design(S.oxpm.values, S.dxpm.values)
row = {}
for sp in ('fwd', 'loso'):
    row[sp] = paired(oos_err(Ds, sp), oos_err(Dr, sp), Y)
    row[sp + '_wpct'] = paired(oos_err(Ds, sp, 'wpct'), oos_err(Dr, sp, 'wpct'), Y)
res['candidates']['C3_shrunk_sxpm'] = row; print('C3', row, flush=True)

# Holm over the 3 candidates, each on its worse split (net)
ps = {k: max(v['fwd']['p_one_sided'], v['loso']['p_one_sided']) for k, v in res['candidates'].items()}
order = sorted(ps, key=ps.get); holm = {}; run = 0.0
for i, k in enumerate(order):
    run = max(run, min(1.0, ps[k] * (len(order) - i))); holm[k] = round(run, 4)
for k, v in res['candidates'].items():
    maj = all(int(v[sp]['improved'].split('/')[0]) * 2 > int(v[sp]['improved'].split('/')[1]) for sp in ('fwd', 'loso'))
    v['holm_p'] = holm[k]; v['pass'] = bool(holm[k] < .05 and maj and v['fwd']['t'] < 0 and v['loso']['t'] < 0)

# Audit: VORX constants, same season (VORX is descriptive): W% = a + k x team sum((xpm - r) x mp) / team mp x 5 ... fit
# k as W% per point of minutes-weighted team XPM; r from the intercept (a = .5 at league-average team).
A = V.merge(ST[['year', 'pid', 'tm', 'mp']].rename(columns={'mp': 'smp'}), on=['year', 'pid'])
A = A[A.xpm.notna()]
A['wx'] = A.xpm * A.smp
for col in ('xpm', 'sxpm'):
    A['wx'] = A[col].fillna(A.xpm) * A.smp
    g = A.groupby(['year', 'tm']).agg(wx=('wx', 'sum'), m=('smp', 'sum')).reset_index().merge(T[['year', 'tm', 'wpct', 'wins', 'losses']], on=['year', 'tm'])
    g['x'] = 5 * g.wx / g.m; g = g[g.year.isin(YRS)].reset_index(drop=True)
    e = np.full(len(g), np.nan); ks = []
    for q in YRS:
        tr = g.year != q; b = ols(g.x.values[tr][:, None], g.wpct.values[tr]); ks.append(b[1])
        e[(g.year == q).values] = ((b[0] + b[1] * g.x[g.year == q] - g.wpct[g.year == q]) * 82) ** 2
    b = ols(g.x.values[:, None], g.wpct.values)
    res.setdefault('vorx_audit', {})[col] = {'k_all': round(float(b[1]), 4), 'k_loso_range': [round(min(ks), 4), round(max(ks), 4)],
                                             'intercept_wpct': round(float(b[0]), 4), 'loso_rmse_wins': round(float(np.sqrt(np.nanmean(e))), 3)}
print('vorx', res['vorx_audit'])
json.dump(res, open(OUT, 'w'), indent=1)
