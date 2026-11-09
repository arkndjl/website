#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA position projection for college players (research; Nov 3 2026, thread "Project NBA positions for CBB players").

    python3 scripts/research/nbapos/nbapos.py <bbref_pos.json> [outdir]

Outcome: the share of NBA minutes a player spent at PG / SG / SF / PF / C (Basketball-Reference play-by-play position
estimates, bbref_pos.py), minutes-weighted over his first six NBA seasons, players with 500+ NBA minutes.
Model: multinomial logit with soft targets (minutes shares), L2, on one college season's line (any season, so it can
grade every board row). Scored leave-one-draft-class-out (final college season = class) on each player's final
college season: cross-entropy vs the realized shares, MAE of expected position (1-5), modal-position accuracy.
Writes <outdir>/nbapos_fit.json (coefficients, standardization, NBA position norms) and nbapos_cv.json."""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_fit as F

POS = ['PG', 'SG', 'SF', 'PF', 'C']
NBA_SEASONS = 6
MIN_NBA_MP = 500
MIN_COL_MPT = 150


def shrink(x, n, prior, k):
    if x is None or n is None: return prior
    return (x * n + prior * k) / (n + k)


def col_feats(s):
    """one college season's position-relevant line (rates shrunk toward the D-I mean by minutes / attempts)"""
    L = F.season_line(s)
    mpt = L['mpt']
    fga = (s['tpa'] or 0) + (s['twopa'] or 0)
    f = {'ht': s['hti'] or 77.0}
    for k in ('ast', 'to', 'usg', 'tpa100', 'ftr', 'orb', 'drb', 'blk', 'stl', 'ft', 'tp'):
        f[k] = L[k]
    f['pfr'] = shrink(s['pfr'], mpt, 3.4, 300)
    f['tp_sh'] = shrink((s['tpa'] or 0) / fga if fga else None, fga, 0.33, 60)
    f['rim_sh'] = shrink((s['rima'] or 0) / fga if fga else None, fga, 0.35, 60)
    f['mid_sh'] = shrink((s['mida'] or 0) / fga if fga else None, fga, 0.32, 60)
    f['dunk40'] = math.log1p((s['dunka'] or 0) / max(40, mpt) * 40)
    f['yr'] = F.CLS.get(s['yr'], 1)
    f['role'] = s.get('role')
    return f


ROLES8 = ['Pure PG', 'Scoring PG', 'Combo G', 'Wing G', 'Wing F', 'Stretch 4', 'PF/C', 'C']
SKILL = ['ast', 'to', 'usg', 'tpa100', 'tp_sh', 'ftr', 'orb', 'drb', 'blk', 'stl', 'pfr', 'rim_sh', 'mid_sh', 'dunk40', 'ft', 'tp']


def design(rows, spec):
    """the model matrix for a feature spec (no intercept; Std on train)"""
    out = []
    for f in rows:
        v = []
        if 'ht' in spec:
            v += [f['ht'], (f['ht'] - 78) ** 2]
        if 'role' in spec:
            v += [1.0 if f['role'] == r else 0.0 for r in ROLES8[1:]]
        if 'skill' in spec:
            v += [f[k] for k in SKILL] + [f['yr']]
        if 'inter' in spec:   # height x the size-skill stats (a tall passer, a short shot-blocker)
            v += [(f['ht'] - 78) * f[k] for k in ('ast', 'blk', 'drb', 'tp_sh')]
        out.append(v)
    return np.array(out, float) if out and out[0] else np.zeros((len(rows), 0))


def softmax(Z):
    Z = Z - Z.max(1, keepdims=True)
    E = np.exp(Z)
    return E / E.sum(1, keepdims=True)


def fit(X, Y, w, lam):
    """multinomial logit (class 0 = reference) with soft targets Y, row weights w, L2 lam on slopes; Newton steps"""
    n, d = X.shape
    K = Y.shape[1]
    Xb = np.hstack([np.ones((n, 1)), X])
    B = np.zeros((d + 1, K))
    reg = np.full(d + 1, lam); reg[0] = 1e-6
    for it in range(60):
        P = softmax(Xb @ B)
        G = Xb.T @ ((P - Y) * w[:, None])        # (d+1, K)
        G[:, 1:] += reg[:, None] * B[:, 1:]
        # full Hessian over the K-1 free classes
        m = d + 1
        H = np.zeros((m * (K - 1), m * (K - 1)))
        for a in range(1, K):
            for b in range(a, K):
                wt = w * P[:, a] * ((1.0 if a == b else 0.0) - P[:, b])
                h = (Xb * wt[:, None]).T @ Xb
                if a == b: h += np.diag(reg)
                H[(a - 1) * m:a * m, (b - 1) * m:b * m] = h
                if a != b: H[(b - 1) * m:b * m, (a - 1) * m:a * m] = h
        g = np.concatenate([G[:, a] for a in range(1, K)])
        step = np.linalg.solve(H + 1e-9 * np.eye(len(g)), g)
        for a in range(1, K): B[:, a] -= step[(a - 1) * m:a * m]
        if np.abs(step).max() < 1e-7: break
    return B


def predict(B, X):
    return softmax(np.hstack([np.ones((len(X), 1)), X]) @ B)


def scores(P, Y):
    ce = -(Y * np.log(np.clip(P, 1e-9, 1))).sum(1)
    pos = np.arange(1, 6)
    ep, ey = P @ pos, Y @ pos
    return {'ce': float(ce.mean()), 'mae': float(np.abs(ep - ey).mean()), 'rmse': float(np.sqrt(((ep - ey) ** 2).mean())),
            'acc': float((P.argmax(1) == Y.argmax(1)).mean()),
            'acc_adj': float((np.abs(P.argmax(1) - Y.argmax(1)) <= 1).mean()),
            'grp': float((np.digitize(ep, [2.5, 3.5]) == np.digitize(ey, [2.5, 3.5])).mean())}


def load(bbref_path):
    careers = json.load(open(os.path.join(F.D.CACHE, 'careers.json')))
    pos = defaultdict(list)
    for r in json.load(open(bbref_path)): pos[r['bref']].append(r)
    players = []
    for c in careers:
        b = c['nba'].get('bref')
        if not b or b not in pos: continue
        last = c['seasons'][-1]['year']
        ss = sorted((r for r in pos[b] if r['year'] > last), key=lambda r: r['year'])[:NBA_SEASONS]
        mp = sum(r['mp'] for r in ss)
        if mp < MIN_NBA_MP: continue
        y = np.array([sum(r['mp'] * r['pct'][k] for r in ss) / mp for k in range(5)])
        rows = [(s, col_feats(s)) for s in c['seasons'] if (s['mp'] or 0) * (s['gp'] or 0) >= MIN_COL_MPT and s['hti']]
        if not rows: continue
        players.append({'pid': c['pid'], 'name': c['name'], 'cls': last, 'y': y / y.sum(), 'mp': mp, 'rows': rows,
                        'fv': c['nba'].get('fv'), 'bref': b})
    return careers, players


SPECS = {'base': [], 'ht': ['ht'], 'role': ['ht', 'role'], 'skill': ['ht', 'skill'], 'skill+inter': ['ht', 'skill', 'inter'],
         'skill+role': ['ht', 'skill', 'role'], 'skill+inter+role': ['ht', 'skill', 'inter', 'role']}


def cv(players, spec, lam, final_only_train=False):
    classes = sorted({p['cls'] for p in players})
    P_all, Y_all = [], []
    for k in classes:
        tr = [p for p in players if p['cls'] != k]
        te = [p for p in players if p['cls'] == k]
        R, Y, W = [], [], []
        for p in tr:
            rr = p['rows'][-1:] if final_only_train else p['rows']
            for s, f in rr:
                R.append(f); Y.append(p['y']); W.append(1.0 / len(rr))
        X = design(R, spec)
        mu, sd = X.mean(0), X.std(0) + 1e-9
        B = fit((X - mu) / sd, np.array(Y), np.array(W), lam)
        Xt = design([p['rows'][-1][1] for p in te], spec)
        P_all.append(predict(B, (Xt - mu) / sd)); Y_all.append(np.array([p['y'] for p in te]))
    return np.vstack(P_all), np.vstack(Y_all)


def main():
    bb = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else '/mnt/project-files/cbb/nbapos'
    careers, players = load(bb)
    players.sort(key=lambda p: p['cls'])
    print(len(players), 'NBA players with 500+ min and college lines; classes', players[0]['cls'], '-', players[-1]['cls'])
    res = {}
    for name, spec in SPECS.items():
        best = None
        for lam in ([1.0] if not spec else [1, 3, 10, 30]):
            P, Y = cv(players, spec, lam)
            s = scores(P, Y); s['lam'] = lam
            if best is None or s['ce'] < best['ce']: best = s; bestP = P
        res[name] = best
        print(f"{name:18s} lam {best['lam']:>4} CE {best['ce']:.4f} MAE {best['mae']:.3f} RMSE {best['rmse']:.3f} acc {best['acc']:.3f} "
              f"adj {best['acc_adj']:.3f} grp {best['grp']:.3f}")
        if name == 'skill+inter+role': res['_P'] = bestP.tolist()
    json.dump(res, open(os.path.join(outdir, 'nbapos_cv.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
