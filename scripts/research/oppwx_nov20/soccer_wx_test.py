# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer: weather at kickoff against the game model's walk-forward misses (Nov 20 2026).
    python3 scripts/research/oppwx_nov20/soccer_wx_test.py SOCCER_WX_JSON

Matches: the big five's first and second divisions in scripts/data/games_wf/soccer.json.gz with an airport report
inside 60 km for kickoff .. +2 h (soccer_wx_pull.py). Weather terms: wind over 10 mph (per mph), gusts over 20, cold
under 40 F (per degree), heat over 80 F, wet (rain or snow reported), snow.
  total   goals ~ Poisson(model total x exp(Xb)): b fit on the seasons before, scored on Poisson deviance of the total
  xg      the same on Understat / FotMob xG totals where the history has them (less noise; squared error)
  margin  (home - away goals) - model margin ~ X x sign of the model's favourite (does weather pull games level?)
Walk-forward by season from 2018; paired t over matches, seasons better. Ships at t <= -2 with most seasons better,
Holm over the three targets.
"""
import gzip, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..')
wx = json.load(open(sys.argv[1]))
hist = {r['id']: r for r in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))}
wf = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'soccer.json.gz')))
rows = []
for g in wf:
    w = wx.get(g['id'])
    if not w or g.get('hs') is None: continue
    h = hist[g['id']]
    t, wind, gust, wet, snow = w[0], w[1], w[2], w[3], w[4]
    x = [max(wind - 10, 0), max((gust or 0) - 20, 0), max(40 - t, 0), max(t - 80, 0), wet, snow]
    xg = (h['hx'] + h['ax']) if h.get('hx') is not None and h.get('ax') is not None else None
    rows.append((g['S'], g['hs'] + g['as'], g['l'][0] + g['l'][1], g['hs'] - g['as'], g['l'][0] - g['l'][1], xg, x, g['lg']))
S = np.array([r[0] for r in rows]); T = np.array([r[1] for r in rows], float); L = np.array([r[2] for r in rows])
M = np.array([r[3] for r in rows], float); LM = np.array([r[4] for r in rows]); X = np.array([r[6] for r in rows], float)
XG = np.array([np.nan if r[5] is None else r[5] for r in rows])
NAMES = ['wind>10 /mph', 'gust>20 /mph', 'cold<40 /F', 'heat>80 /F', 'wet', 'snow']
out = {'n': len(rows), 'seasons': [int(S.min()), int(S.max())], 'share': {n: round(float((X[:, i] > 0).mean()), 3) for i, n in enumerate(NAMES)}}
print(out)

def pois_fit(X_, y, off, it=30):
    b = np.zeros(X_.shape[1])
    for _ in range(it):
        mu = off * np.exp(X_ @ b)
        g = X_.T @ (y - mu); H = (X_ * mu[:, None]).T @ X_ + np.eye(len(b)) * 1e-6
        b = b + np.linalg.solve(H, g)
    return b

def dev(y, mu):
    return 2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / mu), 0) - (y - mu))

def tt(d, seas):
    bs = [float(d[seas == s].mean()) for s in sorted(set(seas))]
    return {'d': round(float(d.mean()), 5), 't': round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2),
            'seasonsBetter': f"{sum(1 for b in bs if b < 0)}/{len(bs)}"}

def ols_t(X_, y):
    b = np.linalg.lstsq(X_, y, rcond=None)[0]; e = y - X_ @ b
    se = np.sqrt(np.diag(np.linalg.inv(X_.T @ X_)) * e.var())
    return b, b / se

for cols, tag in ((list(range(6)), 'all six'), ([0, 4], 'wind + wet'), ([0], 'wind'), ([4], 'wet'), ([2, 3], 'cold + heat')):
    Xc = np.column_stack([np.ones(len(X)), X[:, cols]])
    # full-sample coefficients (description)
    b = pois_fit(Xc, T, L)
    res = {'coef (log goals)': {NAMES[c]: round(float(v), 4) for c, v in zip(cols, b[1:])}}
    bo, to = ols_t(Xc, T - L)
    res['ols t'] = {NAMES[c]: round(float(v), 2) for c, v in zip(cols, to[1:])}
    d_tot = np.zeros(len(T)); d_xg = np.full(len(T), np.nan); d_m = np.zeros(len(T)); use = S >= 2018
    for s in sorted(set(S[use])):
        tr = S < s; te = S == s
        bt = pois_fit(Xc[tr], T[tr], L[tr])
        d_tot[te] = dev(T[te], L[te] * np.exp(Xc[te] @ bt)) - dev(T[te], L[te] * np.exp(bt[0]))
        k = tr & ~np.isnan(XG); kt = te & ~np.isnan(XG)
        if k.sum() > 2000 and kt.sum():
            bx = np.linalg.lstsq(Xc[k], XG[k] - L[k], rcond=None)[0]
            d_xg[kt] = (XG[kt] - L[kt] - Xc[kt] @ bx) ** 2 - (XG[kt] - L[kt] - bx[0]) ** 2
        sg = np.sign(LM)[:, None]
        Xm = X[:, cols] * sg
        bm = np.linalg.lstsq(Xm[tr], (M - LM)[tr], rcond=None)[0]
        d_m[te] = (M[te] - LM[te] - Xm[te] @ bm) ** 2 - (M[te] - LM[te]) ** 2
    res['total (Poisson deviance)'] = tt(d_tot[use], S[use])
    ok = use & ~np.isnan(d_xg)
    res['xg total (sq err)'] = dict(tt(d_xg[ok], S[ok]), n=int(ok.sum()))
    res['margin toward level (sq err)'] = tt(d_m[use], S[use])
    out[tag] = res
    print(tag, json.dumps(res))
json.dump(out, open(os.path.join(HERE, 'soccer_wx_results.json'), 'w'), indent=1)
