#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer context audit, Nov 27 2026: T1 (backup watch grade), T2 (1Y / 3Y prior inputs), T4 (breakout + p/90).
prereg.md has the rules. Season files 2015..2026 only (2027 never read as an outcome).

    python3 scripts/research/ctx_nov27/soccer/run.py [t1] [t2] [t4]     # -> results.json here
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCR)
OUT = os.path.join(HERE, 'results.json')
LOCK = 2027                                   # the season in progress: never an outcome


def tstat(d):
    d = np.asarray(d, float)
    return round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)


# ---------------------------------------------------------------- T1
def t1():
    import backup_age_fit as BA
    S = {y: d for y, d in BA.seasons('soccer-war').items() if y < LOCK}
    import gzip
    link = json.load(gzip.open(os.path.join(SCR, 'data', 'soccer_mv_link.json.gz'), 'rt'))
    dob = {u: link['dob'].get(str(t)) for u, t in link['p'].items()}
    age = lambda p, y: (y - 1 + 8 / 12 - (int(dob[p['p']][:4]) + (int(dob[p['p']][5:7]) - 1) / 12)) if dob.get(p['p']) else None
    by = {y: {p['p']: p for p in d['players']} for y, d in S.items()}
    shape, K, W, MN, H = {'GK': 1, 'D': 4, 'M': 4, 'F': 2}, 900, (1, .5), 270, BA.H
    use = lambda p: p['min']
    last = max(S)
    rows = []
    for y in sorted(S):
        if y - 1 not in S or y + H > last:
            continue
        g = lambda pid: BA.rate(by, pid, [y, y - 1], W, lambda p: p.get('gar90'), use, K, 0.0)
        fut = lambda pid, k: BA.rate(by, pid, [y + 1, y + 2], [1, 1], lambda p: p.get(k), use, K, 0.0)
        rooms = {}
        for p in S[y]['players']:
            if p.get('gar90') is None or not use(p) or age(p, y) is None or p.get('pg90') is None:
                continue
            rooms.setdefault(p['team'], {}).setdefault(p['pos'], []).append(p)
        for R in rooms.values():
            for gp, L in R.items():
                L.sort(key=lambda p: -use(p))
                n = shape[gp]
                if len(L) < n:
                    continue
                gs, s = min(((g(x['p']), x) for x in L[:n]), key=lambda t: t[0])
                for b in L[n:3 * n]:
                    if use(b) < MN:
                        continue
                    rows.append((y, g(b['p']) - gs, b['pg90'] - s['pg90'], age(s, y) - age(b, y),
                                 fut(b['p'], 'gar90') - fut(s['p'], 'gar90'), fut(b['p'], 'sv') - fut(s['p'], 'sv')))
    P = np.array(rows, float)
    ys = sorted(set(P[:, 0].astype(int)))
    out = {'n': len(P), 'seasons': [int(ys[0]), int(ys[-1])]}
    for name, tc in (('own', 4), ('guard_sv', 5)):
        eA, eB, ss = [], [], []
        for y in ys:
            tr, te = P[P[:, 0] + H <= y], P[P[:, 0] == y]
            if len(tr) < 100 or not len(te):
                continue
            for col, e in ((1, eA), (2, eB)):
                X = np.c_[np.ones(len(tr)), tr[:, [col, 3]]]
                b = np.linalg.lstsq(X, tr[:, tc], rcond=None)[0]
                e += list((np.c_[np.ones(len(te)), te[:, [col, 3]]] @ b - te[:, tc]) ** 2)
            ss += [y] * len(te)
        eA, eB, ss = np.array(eA), np.array(eB), np.array(ss)
        k = sum(eB[ss == y].mean() < eA[ss == y].mean() for y in sorted(set(ss)))
        out[name] = {'held': len(eA), 'mse_control': round(float(eA.mean()), 6), 'mse_pg90': round(float(eB.mean()), 6),
                     't': tstat(eB - eA), 'seasons_better': f'{k}/{len(set(ss))}',
                     'r_control': round(float(np.corrcoef(P[:, 1], P[:, tc])[0, 1]), 4),
                     'r_pg90': round(float(np.corrcoef(P[:, 2], P[:, tc])[0, 1]), 4)}
    o, gd = out['own'], out['guard_sv']
    k, n = map(int, o['seasons_better'].split('/'))
    out['pass'] = bool(o['t'] <= -2 and k * 2 > n and gd['t'] < 2 and gd['mse_pg90'] <= gd['mse_control'])
    return out


# ---------------------------------------------------------------- T2
def t2():
    import soccer_players as SP
    import soccer_proj_research as R
    SF = R.season_files()
    SV = {}
    for fn in sorted(os.listdir(SP.SDIR)):
        S_ = int(fn[:4])
        m = defaultdict(float)
        for o in json.load(open(os.path.join(SP.SDIR, fn)))['players']:
            m[o['p']] += o.get('svar') or 0.0
        SV[S_] = m
    snap = R.D.load(R.SNAPS)
    assert snap.get('garLine') == 'bottom3'
    dob = SP.proj_dobs()
    cols = SP.PROJ_COLS
    base_ix = [cols.index(c) for c in ('one', 'g0', 'p1', 'lm0', 'a', 'a2', 'am', 'd', 'm', 'fw', 'ad', 'am_', 'af')]
    p1 = base_ix.index(cols.index('p1'))
    res = {}
    for tgt in ('1y', '3y'):
        last = 2025 if tgt == '1y' else 2023
        res[tgt] = []
        for f in R.FS:
            X, Y, SS, PID, PS = [], [], [], [], []
            for S in range(R.S_FIRST, last + 1):
                if f < 1:
                    sn = snap[f'{S}_{f}']; cur, fl = sn['p'], sn['f']
                else:
                    cur, fl = SF[S], R.full_f(S)
                nxt = SF.get(S + 1, {})
                for p, (mn, g, pos, lg) in cur.items():
                    if p not in nxt or p not in dob or lg not in fl:
                        continue
                    y = nxt[p][1] if tgt == '1y' else sum(SF.get(S + k, {}).get(p, [0, 0.0])[1] for k in (1, 2, 3))
                    x1, x2 = SF.get(S - 1, {}).get(p), SF.get(S - 2, {}).get(p)
                    pr = [(x1 or [0, 0.0])[0], (x1 or [0, 0.0])[1], (x2 or [0, 0.0])[0], (x2 or [0, 0.0])[1]]
                    fx = max(fl[lg], 0.05)
                    X.append(SP.proj_x(mn, g, pos, SP.age_on(S, dob[p]), pr, fx)); Y.append(y); SS.append(S); PID.append(p)
                    sv = (SV[S - 1].get(p, 0.0) if x1 else 0.0) + (SV[S - 2].get(p, 0.0) if x2 else 0.0)
                    PS.append(sv / (pr[0] + pr[2] + SP.PROJ_K) * (mn / fx))
            X, Y, SS, PID, PS = np.array(X, float)[:, base_ix], np.array(Y), np.array(SS), np.array(PID), np.array(PS)
            forms = {'control': X, 'T2a_add': np.c_[X, PS], 'T2b_swap': np.c_[np.delete(X, p1, 1), PS]}
            seasons = sorted(set(SS.tolist()))
            e, sl = {}, {}
            for k, M in forms.items():
                p_ = np.zeros(len(Y))
                for s in seasons:
                    tr, te = SS != s, SS == s
                    p_[te] = M[te] @ np.linalg.lstsq(M[tr], Y[tr], rcond=None)[0]
                e[k] = (p_ - Y) ** 2; sl[k] = round(float(np.polyfit(p_, Y, 1)[0]), 3)
            g = {'f': f, 'n': len(Y), 'rmse': {k: round(float(np.sqrt(v.mean())), 4) for k, v in e.items()}, 'slope': sl}
            for k in ('T2a_add', 'T2b_swap'):
                d = defaultdict(list)
                for pid, x in zip(PID, e[k] - e['control']):
                    d[pid].append(x)
                g[k] = {'t': tstat([np.mean(v) for v in d.values()]),
                        'won': f"{sum(e[k][SS == s].mean() < e['control'][SS == s].mean() for s in seasons)}/{len(seasons)}"}
            res[tgt].append(g)
            print(tgt, json.dumps(g), flush=True)
    for k in ('T2a_add', 'T2b_swap'):
        ok1 = all(g[k]['t'] <= -2 and int(g[k]['won'].split('/')[0]) * 2 > int(g[k]['won'].split('/')[1])
                  and .8 <= g['slope'][k] <= 1.2 for g in res['1y'])
        ok3 = all(g['rmse'][k] <= g['rmse']['control'] for g in res['3y'])
        res[k + '_pass'] = bool(ok1 and ok3)
    return res


# ---------------------------------------------------------------- T4
def t4():
    import breakout_lib as L
    import soccer_breakout as B
    import soccer_breakout_research as R
    P, T, squad, last = R.data()
    assert last < LOCK
    pg = {}
    for s in B.seasons():
        if s >= LOCK:
            continue
        m = defaultdict(lambda: [0.0, 0.0])
        for o in json.load(open(os.path.join(B.SDIR, f'{s}.json')))['players']:
            if o.get('pg90') is not None:
                m[o['p']][0] += o['pg90'] * o['min']; m[o['p']][1] += o['min']
        pg[s] = {p: a / b for p, (a, b) in m.items() if b}
    Rw, C = [], B.careers(P)
    for (p, s), a in P.items():
        b = P.get((p, s + 1))
        if s + 1 > last or not b or a['pos'] == 'GK' or a['min'] < B.MIN_BASE or a['inv'] < 5:
            continue
        ref = max(v for q, v in C[p] if q <= s)
        if ref >= B.LEVEL or p not in pg[s]:
            continue
        s0, f = B.bo_row(a, B.history(P, p, s), T[s], b['team'], squad[s + 1][b['team']], ref)
        f['p/90'] = [pg[s][p] - s0]
        Rw.append((s, f, 1.0 if (b['min'] >= B.MIN_NEXT and B.shr(b['g90'], b['min']) >= B.LEVEL) else 0.0))
    S = np.array([s + 1 for s, _, _ in Rw], float)
    y = np.array([h for _, _, h in Rw])
    base = np.array([f['base'] for _, f, _ in Rw])
    keep = json.load(open(R.OUT))['breakout']['keep']
    kept = np.column_stack([base] + [np.array([f[k] for _, f, _ in Rw]) for k in keep])
    c = np.array([f['p/90'] for _, f, _ in Rw])

    def run(X):
        def fp(trn, te):
            b0, b = L.logit(X[trn], y[trn])
            return L.sig(b0 + X[te] @ b)

        def err(p, te):
            p = np.clip(p, 1e-6, 1 - 1e-6)
            return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))
        return L.loso(S, fp, err)
    a = L.compare(run(base), run(np.column_stack([base, c])))
    b = L.compare(run(kept), run(np.column_stack([kept, c])))
    return {'n': len(y), 'rate': round(float(y.mean()), 4), 'keep': keep, 'a_vs_base': a, 'b_vs_kept': b,
            'pass': bool(b['t'] >= 2 and b['won'] >= 7)}


if __name__ == '__main__':
    want = sys.argv[1:] or ['t1', 't2', 't4']
    try:
        res = json.load(open(OUT))
    except (OSError, ValueError):
        res = {}
    for k in want:
        res[k.upper()] = {'t1': t1, 't2': t2, 't4': t4}[k]()
        print(k, json.dumps(res[k.upper()])[:3000], flush=True)
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False)
