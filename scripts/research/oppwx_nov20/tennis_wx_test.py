# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Tennis: does the day's weather move serve points won (and aces) once the server, the returner and the event are
accounted for? (Nov 20 2026)   python3 scripts/research/oppwx_nov20/tennis_wx_test.py MATCHES_CSV_GZ TENNIS_WX_JSON

Outdoor tour-level main draws 2012-26. A row = one player's serve in one match (serve points won / serve points, aces /
serve points), weighted by serve points. Per tour and year: server, returner and event effects are taken out of the
rate AND of the weather (so only day-to-day weather inside an event is left, the same courts and balls). The match day
is not in the archive: it is the round's usual day(s) in the event's week, weather averaged over them, 11:00-19:00.
Weather: wind mph, temperature F, share of wet hours. Coefficients fit 2012-19, scored 2020-26 on the residual rate.
"""
import csv, gzip, json, os, sys
from collections import defaultdict
import numpy as np
WEEK = {'R64': [0, 1], 'R32': [0, 1, 2], 'R16': [2, 3], 'QF': [4], 'SF': [5], 'F': [6]}
LONG = {'R128': [0, 1, 2], 'R64': [2, 3, 4], 'R32': [4, 5, 6], 'R16': [6, 7, 8], 'QF': [8, 9, 10], 'SF': [10, 11, 12], 'F': [12, 13]}
wx = json.load(open(sys.argv[2]))
ev = defaultdict(list)
for r in csv.DictReader(gzip.open(sys.argv[1], 'rt')):
    if r['tid'] in wx and r['w_svpt'] and r['l_svpt']:
        ev[r['tid']].append(r)
rows = []      # (tour, year, tid, server, returner, svpt, spw, ace rate, wind, temp, wet, dayspan)
for tid, ms in ev.items():
    long_ = any(m['rd'] == 'R128' for m in ms)
    W = wx[tid]
    for m in ms:
        days = (LONG if long_ else WEEK).get(m['rd'])
        if not days: continue
        d = [W[str(j)] for j in days if str(j) in W]
        if not d: continue
        wind = float(np.mean([x[1] for x in d])); temp = float(np.mean([x[0] for x in d])); wet = float(np.mean([x[3] for x in d]))
        for a, b in (('w', 'l'), ('l', 'w')):
            try:
                sv = int(m[a + '_svpt']); won = int(m[a + '_1stWon']) + int(m[a + '_2ndWon']); ace = int(m[a + '_ace'])
            except ValueError:
                continue
            if sv < 20: continue
            rows.append((m['tour'], int(m['d'][:4]), tid, m[a], m[b], sv, won / sv, ace / sv, wind, temp, wet, m['rd']))
print(len(rows), 'serve rows', len(ev), 'events')
# residualize inside tour-year
R = {'spw': [], 'ace': []}; X = []; meta = []
by = defaultdict(list)
for r in rows: by[(r[0], r[1])].append(r)
for (tour, yr), L in sorted(by.items()):
    sv = {p: i for i, p in enumerate(sorted({r[3] for r in L}))}
    rt = {p: i for i, p in enumerate(sorted({r[4] for r in L}))}
    es = {p: i for i, p in enumerate(sorted({r[2] for r in L}))}
    n = len(L); k = len(sv) + len(rt) + len(es)
    A = np.zeros((n, k)); w = np.sqrt(np.array([r[5] for r in L], float))
    for i, r in enumerate(L):
        A[i, sv[r[3]]] = 1; A[i, len(sv) + rt[r[4]]] = 1; A[i, len(sv) + len(rt) + es[r[2]]] = 1
    Aw = A * w[:, None]
    G = Aw.T @ Aw + np.eye(k) * 2.0          # light ridge: players with one match
    def resid(v):
        b = np.linalg.solve(G, Aw.T @ (v * w))
        return v - A @ b
    R['spw'].append(resid(np.array([r[6] for r in L]))); R['ace'].append(resid(np.array([r[7] for r in L])))
    X.append(np.column_stack([resid(np.array([r[c] for r in L], float)) for c in (8, 9, 10)]))
    meta += [(yr, r[2], r[11], r[5]) for r in L]
X = np.vstack(X); yrs = np.array([m[0] for m in meta]); wts = np.array([m[3] for m in meta], float)
cl = np.array([hash((m[1], m[2])) for m in meta])
out = {'rows': len(meta), 'events': len(ev), 'sd': {'wind': round(float(X[:, 0].std()), 2), 'temp': round(float(X[:, 1].std()), 2), 'wet': round(float(X[:, 2].std()), 3)}}
def wls(Xs, y, w, cl_):
    Xw = Xs * np.sqrt(w)[:, None]; b = np.linalg.solve(Xw.T @ Xw, Xw.T @ (y * np.sqrt(w)))
    e = y - Xs @ b
    # cluster-robust (event x round) standard errors
    M = np.zeros((Xs.shape[1], Xs.shape[1]))
    order = np.argsort(cl_); c_s = cl_[order]; cut = np.flatnonzero(np.diff(c_s)) + 1
    for ix in np.split(order, cut):
        g = (Xs[ix] * (w[ix] * e[ix])[:, None]).sum(0); M += np.outer(g, g)
    Bi = np.linalg.inv(Xw.T @ Xw); V = Bi @ M @ Bi
    return b, np.sqrt(np.diag(V))
for nm in ('spw', 'ace'):
    y = np.concatenate(R[nm])
    b, se = wls(X, y, wts, cl)
    tr = yrs <= 2019; te = ~tr
    bt, _ = wls(X[tr], y[tr], wts[tr], cl[tr])
    e0 = y[te] ** 2 * wts[te]; e1 = (y[te] - X[te] @ bt) ** 2 * wts[te]
    d = e1 - e0
    # paired t over event-round clusters
    order = np.argsort(cl[te]); cs = cl[te][order]; cut = np.flatnonzero(np.diff(cs)) + 1
    g = np.array([d[ix].sum() for ix in np.split(order, cut)])
    out[nm] = {'coef per mph wind': round(float(b[0]) * 100, 4), 'per 10F': round(float(b[1]) * 1000, 4), 'wet (all hours)': round(float(b[2]) * 100, 3),
               't': [round(float(x), 2) for x in b / se], 'fit 2012-19': [round(float(x), 6) for x in bt],
               'held 2020-26': {'n': int(te.sum()), 'sse ratio': round(float(e1.sum() / e0.sum()), 5), 't': round(float(g.mean() / (g.std(ddof=1) / np.sqrt(len(g)))), 2)},
               'sd of rate left': round(float(np.sqrt(np.average(y ** 2, weights=wts))) * 100, 2)}
    print(nm, out[nm])
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tennis_wx_results.json'), 'w'), indent=1)
