#!/usr/bin/env python3
"""Research (Nov 4 2026, wave 2; pre-registered in fv/sweep-nov04/nba/prereg2.md), Holm over 2 tests:

T1  3Y / 1Y: H5 = live H4 + max(0, proj - 3) x (age - 27), against H4 on the nba_proj3y_star_research.py harness.
T2  XPM board shrink toward a reliability-weighted Marcel prior: mu = mu_role(MP) + r (prior - mu_role(MP)),
    r = H / (H + h0), H = MP(S-1) + .5 MP(S-2); (h0, k) chosen on training seasons (nested leave one season out),
    target = next-season raw XPM (250+ MP, weight min(MP, 2000)), as the Oct 31 shrink fit. Against shipped sxpm.

    python3 scripts/nba_xpm_wave2_research.py        # writes data/nba_xpm_wave2_research.json

Result (Nov 4 2026): T1 FAILS (H5 vs H4 worst t +... see json; y3y f 1 t -1.84, y1 t -1.39: helps the old stars, not
significant). T2 PASSES (p 4e-6, Holm): every fold picks h0 1000, k 600 (k at the grid's edge); held-out weighted RMSE
1.235 vs 1.259 (t -4.63, 12/15), <250 MP 1.61 vs 1.70, 250-1000 1.31 vs 1.34, 1000+ 1.20 vs 1.22; top 25 better.
Shipped as nba_xpm.shrink (SHRINK_K 600, SHRINK_H0 1000).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_proj3y_research as R
import nba_proj3y_star_research as SR
import nba_proj as P
import nba_xpm as X

OUT = os.path.join(X.ROOT, 'data', 'nba_xpm_wave2_research.json')


def norm_p(t):
    return math.erfc(abs(t) / math.sqrt(2))


def t1():
    rows = SR.add_history(R.load())
    rng = np.random.default_rng(20261103)
    grid = []
    for f in R.FS:
        SR.inputs_with_mp(rows, f, rng)
        n, proj, prior, age, lm, M = R.inputs(rows, f, rng)
        rep = lambda k: np.repeat(np.array([r[k] for r in rows], float), n)
        S, ids = rep('S'), np.repeat([r['id'] for r in rows], n)
        d1 = (rep('x1') + 2) * rep('m1') / (rep('m1') + 1000)
        d2 = (rep('x2') + 2) * rep('m2') / (rep('m2') + 1000)
        lc = np.log1p(SR.MPF[0] + rep('m1') + rep('m2'))
        X4 = SR.design('H4', proj, prior, age, lm, d1, d2, lc)
        X5 = np.column_stack([X4, np.maximum(0, proj - SR.HC) * (age - R.A0)])
        Y = np.repeat(np.array([r['y'] for r in rows], float), n, axis=0)
        y3y = np.repeat(np.array([np.nan if r['y3y'] is None else r['y3y'] for r in rows]), n)
        g = {'f': f}
        for tn, T, buf in (('y1', Y[:, 0], 1), ('y3y', y3y, 3)):
            ok = ~np.isnan(T)
            if tn == 'y3y': ok &= S <= 2023
            seasons = sorted(set(S[ok].astype(int)))
            pr = {}
            for nm, Xd in (('H4', X4), ('H5', X5)):
                p = np.zeros_like(T)
                for c in seasons:
                    tr = ok & (np.abs(S - c) > buf); te = ok & (S == c)
                    p[te] = Xd[te] @ np.linalg.lstsq(Xd[tr], T[tr], rcond=None)[0]
                pr[nm] = p
            E = {k: (v - T) ** 2 for k, v in pr.items()}
            top, old = ok & (proj >= 4), ok & (proj >= 4) & (age >= 29)
            t25 = np.zeros_like(ok)
            for c in seasons:
                idx = np.where(ok & (S == c))[0]
                t25[idx[np.argsort(-proj[idx])[:25 * n]]] = True
            g[tn] = {'rmse': {k: round(float(np.sqrt(e[ok].mean())), 4) for k, e in E.items()},
                     't': round(R.tstat((E['H5'] - E['H4'])[ok], ids[ok]), 2),
                     'won': int(sum(E['H5'][ok & (S == c)].mean() < E['H4'][ok & (S == c)].mean() for c in seasons)), 'of': len(seasons),
                     'slope': round(float(np.polyfit(pr['H5'][ok], T[ok], 1)[0]), 3),
                     'top4': {k: round(float(v[top].mean()), 3) for k, v in pr.items()} | {'actual': round(float(T[top].mean()), 3)},
                     'top4old': {k: round(float(v[old].mean()), 3) for k, v in pr.items()} | {'actual': round(float(T[old].mean()), 3), 'n': int(old.sum() // n)},
                     'top25mse': {k: round(float(E[k][t25].mean()), 4) for k in E}}
            if f == 1.0:
                g[tn]['coefH5'] = [round(float(v), 4) for v in np.linalg.lstsq(X5[ok], T[ok], rcond=None)[0]]
        grid.append(g); print('T1', f, json.dumps(g), flush=True)
    ts = [g[tn]['t'] for g in grid for tn in ('y1', 'y3y')]
    b = lambda d: abs(d['H5'] - d['actual']) - abs(d['H4'] - d['actual'])
    g1 = grid[-1]['y3y']
    v = {'tmax': max(ts), 'p': max(norm_p(t) if t < 0 else 1.0 for t in ts),
         'won': 2 * g1['won'] > g1['of'],
         'slope': all(0.8 <= g[tn]['slope'] <= 1.2 for g in grid for tn in ('y1', 'y3y')),
         'top4': all(b(g[tn]['top4']) <= 0 for g in grid for tn in ('y1', 'y3y')),
         'top25': g1['top25mse']['H5'] <= g1['top25mse']['H4'],
         'old': b(g1['top4old']) < 0}
    return {'grid': grid, 'verdict': v}


def t2():
    D = {}
    for s in range(2010, 2027):
        d = P.load(s)
        D[s] = {p['id']: p for p in d['players'] if not p.get('pr') and p.get('xpm') is not None}
    rows = []
    for s in range(2011, 2026):
        prior = X.prior_xpm(s)
        for pid, p in D[s].items():
            nx = D[s + 1].get(pid)
            if not nx or nx['mp'] < 250 or p['mp'] <= 0: continue
            H = (D.get(s - 1, {}).get(pid) or {}).get('mp', 0) + 0.5 * (D.get(s - 2, {}).get(pid) or {}).get('mp', 0)
            rows.append((s, pid, p['mp'], p['xpm'], prior(pid)[0], H, nx['xpm'], min(nx['mp'], 2000), p.get('sxpm')))
    s_, ids = np.array([r[0] for r in rows]), np.array([r[1] for r in rows])
    mp, x, pri, H, y, w, sx = (np.array([r[i] for r in rows], float) for i in (2, 3, 4, 5, 6, 7, 8))
    games = {s: json.load(open(os.path.join(X.OUT, f'{s}.json')))['games'] for s in range(2011, 2026)}
    gm = np.array([games[s] for s in s_], float)
    mur = sum(a + b * np.log(1 + mp * 82 / np.maximum(gm, 1) / 100) for a, b in X.SHRINK_MU.values())
    k0 = 300                                          # the Oct 31 shrink (role mean, k 300)
    base = mur + (x - mur) * mp / (mp + k0)            # shipped sxpm (unrounded)
    G = [(h0, k) for h0 in (500, 1000, 2000, 4000, 8000) for k in (200, 300, 400, 600)]
    def pred(h0, k):
        mu = mur + H / (H + h0) * (pri - mur)
        return mu + (x - mu) * mp / (mp + k)
    P_ = {g: pred(*g) for g in G}
    def wmse(p, m): return float((w[m] * (p[m] - y[m]) ** 2).sum() / w[m].sum())
    hold, picks, won = np.zeros_like(y), [], 0
    seasons = sorted(set(s_))
    for c in seasons:
        tr, te = s_ != c, s_ == c
        g = min(G, key=lambda g: wmse(P_[g], tr)); picks.append(g)
        hold[te] = P_[g][te]
        won += wmse(hold, te) < wmse(base, te)
    e1, e0 = w * (hold - y) ** 2, w * (base - y) ** 2
    t = R.tstat(e1 - e0, ids)
    t25 = np.zeros(len(y), bool)
    for c in seasons:
        idx = np.where(s_ == c)[0]; t25[idx[np.argsort(-base[idx])[:25]]] = True
    allm = np.ones(len(y), bool)
    v = {'rmse': round(math.sqrt(wmse(hold, allm)), 4), 'rmseShipped': round(math.sqrt(wmse(base, allm)), 4),
         't': round(t, 2), 'p': norm_p(t) if t < 0 else 1.0, 'won': won, 'of': len(seasons), 'picks': sorted(set(picks)),
         'top25': [round(wmse(hold, t25), 4), round(wmse(base, t25), 4)],
         'byMP': {f'{lo}-{hi}': [round(math.sqrt(wmse(hold, (mp >= lo) & (mp < hi))), 3), round(math.sqrt(wmse(base, (mp >= lo) & (mp < hi))), 3)]
                  for lo, hi in ((0, 250), (250, 1000), (1000, 99999))}}
    v['pass_ex_holm'] = v['t'] <= -2 and 2 * won > len(seasons) and v['top25'][0] <= v['top25'][1]
    print('T2', json.dumps(v), flush=True)
    return v


def main():
    r1, r2 = t1(), t2()
    v1 = r1['verdict']
    v1['pass_ex_holm'] = v1['tmax'] <= -2 and all(v1[k] for k in ('won', 'slope', 'top4', 'top25', 'old'))
    tests = {'T1': v1, 'T2': r2}
    order = sorted(tests, key=lambda k: tests[k]['p'])
    ok = True
    for i, k in enumerate(order):
        ok = ok and tests[k]['p'] <= 0.05 / (len(order) - i)
        tests[k]['holm'] = ok
        tests[k]['pass'] = ok and tests[k]['pass_ex_holm']
    print(json.dumps({k: {kk: v[kk] for kk in ('p', 'holm', 'pass')} for k, v in tests.items()}))
    json.dump({'prereg': 'fv/sweep-nov04/nba/prereg2.md', 'T1': r1, 'T2': r2}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
