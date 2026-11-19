# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L1: xG plus-minus as a regression (offence and defence coefficient per player, ridge toward a box prior) as GAR
input rates, judged as the GAR fit is. Prereg: /mnt/project-files/research-sweep-nov19/impl/soccer/prereg.md.

    python3 scripts/research/sweep_nov19/soccer/l1_rapm.py
"""
import json
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import cg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
import soccer_data as D
import soccer_players as SP

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')
LAST = 2026
LAMS = (1000.0, 3000.0, 9000.0)
f = SP.f


def segments():
    """[(league, season, home ids, away ids, minutes, home npxG, away npxG)]"""
    fn = os.path.join(OUT, 'rapm_segs.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    out = []
    for S in range(SP.FIRST, LAST + 1):
        for lg in D.BIG5:
            d = D.us_league(lg, S)
            for mt in (d or {}).get('matches', []):
                if not mt['res']:
                    continue
                m = D.us_match(mt['id'])
                if not m:
                    continue
                iv = {}
                for s in 'ha':
                    rs = {}
                    for r in m['ro'][s]:
                        if all(str(q.get('player_id')) != str(r.get('player_id')) for q in rs.values()):
                            rs[r['id']] = r
                    start = {}
                    for r in rs.values():
                        if int(f(r.get('positionOrder'))) < 17 and str(r.get('roster_out')) in ('0', 'None', ''):
                            start[r['id']] = 0
                    for _ in range(6):
                        for r in rs.values():
                            ro_ = str(r.get('roster_out') or '0')
                            if r['id'] not in start and ro_ in start and ro_ in rs:
                                start[r['id']] = start[ro_] + int(f(rs[ro_]['time']))
                    iv[s] = []
                    for r in rs.values():
                        mins = int(f(r['time']))
                        if mins <= 0 or r['id'] not in start:
                            continue
                        a = start[r['id']]
                        b = min(90, a + mins)
                        if b > a:
                            iv[s].append((str(r['player_id']), a, b))
                cuts = sorted({0, 90} | {x for s in 'ha' for _, a, b in iv[s] for x in (a, b)})
                sh = {s: [(int(f(x[0])), f(x[1])) for x in m['sh'].get(s, []) if x[4] != 'Penalty' and x[3] != 'OwnGoal'] for s in 'ha'}
                for a, b in zip(cuts, cuts[1:]):
                    last = b >= 90
                    on = {s: [p for p, x, y in iv[s] if x <= a and y >= b] for s in 'ha'}
                    if len(on['h']) < 7 or len(on['a']) < 7:
                        continue
                    xg = {s: sum(v for mn, v in sh[s] if a <= mn < b or (last and mn >= 90)) for s in 'ha'}
                    out.append((lg, S, on['h'], on['a'], b - a, xg['h'], xg['a']))
    pickle.dump(out, open(fn, 'wb'))
    return out


def fit_window(segs, rows, S, lam):
    """offence and defence coefficient per player from seasons S-2..S"""
    W = [x for x in segs if S - 2 <= x[1] <= S]
    box = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        if S - 2 <= r['S'] <= S:
            e = box[str(r['p'])]
            e[0] += r['x'] - r['pen'] + r['xA']
            e[1] += r['min']
    tot = sum(e[1] for e in box.values()) or 1
    mu = sum(e[0] for e in box.values()) / tot * 90
    pid = {}
    for x in W:
        for p in x[2] + x[3]:
            pid.setdefault(p, len(pid))
    n = len(pid)
    ls = {}
    for x in W:
        ls.setdefault((x[0], x[1]), len(ls))
    k = 2 * n + len(ls) + 1
    ri, ci, vv, y, w = [], [], [], [], []
    i = 0
    for lg, s_, H, A, mins, xh, xa in W:
        for att, dfn, xg, home in ((H, A, xh, 1.0), (A, H, xa, 0.0)):
            for p in att:
                ri.append(i); ci.append(pid[p]); vv.append(1.0)
            for p in dfn:
                ri.append(i); ci.append(n + pid[p]); vv.append(1.0)
            ri.append(i); ci.append(2 * n + ls[(lg, s_)]); vv.append(1.0)
            if home:
                ri.append(i); ci.append(k - 1); vv.append(1.0)
            y.append(xg / mins * 90); w.append(mins / 90)
            i += 1
    X = sp.csr_matrix((vv, (ri, ci)), shape=(i, k))
    y = np.array(y); w = np.array(w)
    prior = np.zeros(k)
    for p, j in pid.items():
        e = box.get(p)
        if e and e[1] > 0:
            m = e[1]
            prior[j] = (e[0] / m * 90 - mu) * m / (m + 450)        # the box rate itself shrunk with 450 minutes
    pen = np.r_[np.full(2 * n, lam), np.full(k - 2 * n, 1e-6)]
    Xw = X.multiply(w[:, None]).tocsr()
    A_ = (X.T @ Xw + sp.diags(pen)).tocsc()
    b = X.T @ (w * (y - X @ prior))
    sol, info = cg(A_, b, rtol=1e-8, maxiter=5000, M=sp.diags(1.0 / A_.diagonal()))
    assert info == 0, info
    beta = prior + sol
    return {p: (float(beta[j]), float(-beta[n + j])) for p, j in pid.items()}


def tstat(d, keys):
    m = sum(d) / len(d)
    gs = defaultdict(float)
    for x, k in zip(d, keys):
        gs[k] += x - m
    se = math.sqrt(sum(v * v for v in gs.values())) / len(d)
    return m, m / se


def main():
    F = json.load(open(SP.FIT))
    rows = [r for r in D.load(SP.ROWS) if r['S'] <= LAST]
    ts = SP.team_seasons(SP.FIRST, LAST)
    LS, TMV = SP.league_strength(), SP.tm_values()
    segs = segments()
    print('segments', len(segs), flush=True)
    feats, lam0 = F['feats'], F['lambda']
    pri = dict(priors=SP.PRIORS, LS=LS, TMV=TMV)
    SP.prep(rows, F['shrink'])
    ks, X0, y = SP.design(rows, ts, feats, **pri)
    e0, p0 = SP.loso(ks, X0, y, lam0)
    var = float(np.mean(y ** 2))
    Sarr = np.array([k[1] for k in ks])
    res = {'teamSeasons': len(ks), 'baseMse': round(e0, 5), 'baseR2': round(1 - e0 / var, 4), 'segments': len(segs), 'cands': {}}
    Xc = {}
    for lam in LAMS:
        co = {}
        for S in range(SP.FIRST, LAST + 1):
            co[S] = fit_window(segs, rows, S, lam)
        for r in rows:
            o, d_ = co[r['S']].get(str(r['p']), (0.0, 0.0))
            r['orp'], r['drp'] = o, d_
        if lam == LAMS[1]:
            pickle.dump({(r['lg'], r['S'], r['tid'], r['p']): (r['orp'], r['drp']) for r in rows}, open(os.path.join(OUT, 'rapm_coef.pkl'), 'wb'))
        for form, fs in (('ADD', feats + ['orp', 'drp']), ('REP', [x for x in feats if x not in ('ona', 'rel')] + ['orp', 'drp'])):
            k2, X, y2 = SP.design(rows, ts, fs, **pri)
            assert k2 == ks
            Xc[(form, lam)] = X
            e, p = SP.loso(ks, X, y, lam0)
            d = (y - p) ** 2 - (y - p0) ** 2
            m, t = tstat(list(d), list(Sarr))
            res['cands'][f'{form}_{int(lam)}'] = {'mse': round(e, 5), 'r2': round(1 - e / var, 4), 'd': round(m, 6), 't': round(t, 2),
                                                 'seasonsBetter': int(sum(1 for s in np.unique(Sarr) if d[Sarr == s].mean() < 0)),
                                                 'w': {a: round(float(b), 4) for a, b in zip(fs, SP.ridge(X, y, lam0))}}
            print(form, lam, res['cands'][f'{form}_{int(lam)}'], flush=True)
    pn = np.zeros(len(y))
    picks = {}
    for s in np.unique(Sarr):
        tr = Sarr != s
        kk = [k for k, f_ in zip(ks, tr) if f_]
        inner = {c: SP.loso(kk, Xc[c][tr], y[tr], lam0)[0] for c in Xc}
        c = min(inner, key=inner.get)
        picks[int(s)] = f'{c[0]}_{int(c[1])}'
        pn[Sarr == s] = Xc[c][Sarr == s] @ SP.ridge(Xc[c][tr], y[tr], lam0)
    d = (y - pn) ** 2 - (y - p0) ** 2
    m, t = tstat(list(d), list(Sarr))
    by = {int(s): round(float(d[Sarr == s].mean()), 5) for s in np.unique(Sarr)}
    res['nested'] = {'picks': picks, 'mse': round(float(np.mean((y - pn) ** 2)), 5), 'r2': round(1 - float(np.mean((y - pn) ** 2)) / var, 4),
                     'd': round(m, 6), 't': round(t, 2), 'clusters': len(by), 'seasonsBetter': sum(1 for v in by.values() if v < 0),
                     'bySeason': by, 'd2022on': round(float(d[Sarr >= 2022].mean()), 6)}
    json.dump(res, open(os.path.join(OUT, 'l1_rapm.json'), 'w'), indent=1)
    print(json.dumps(res['nested'], indent=1))


if __name__ == '__main__':
    main()
