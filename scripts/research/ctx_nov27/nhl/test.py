#!/usr/bin/env python3
"""NHL context audit, Nov 27 2026: the two pre-registered swaps (prereg.md) -> results.json

    python3 scripts/research/ctx_nov27/nhl/test.py

Reads static/data/nhl-war/2009..2026.json only (2026-27 is never opened)."""
import json
import math
import os

import numpy as np
from scipy import stats

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
W = os.path.join(ROOT, 'static', 'data', 'nhl-war')
LAST = 2026
MARCEL, K = (1.0, 0.7, 0.5), 1600.0
F = {y: json.load(open(os.path.join(W, f'{y}.json'))) for y in range(2009, LAST + 1)}
BY = {y: {p['id']: p for p in d['players']} for y, d in F.items()}


def tstat(d):
    d = np.asarray(d, float)
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    return round(t, 2), round(float(stats.t.sf(t, len(d) - 1)), 4)


def mu_before(n):
    """each group's WAR a minute over the seasons before n"""
    num, den = {}, {}
    for y in range(2009, n):
        for p in F[y]['players']:
            if p.get('war') is not None and p.get('toi'):
                num[p['grp']] = num.get(p['grp'], 0.0) + p['war']; den[p['grp']] = den.get(p['grp'], 0.0) + p['toi']
    return {g: num[g] / den[g] for g in num}


def marcel(pid, n, key, mu):
    num = den = 0.0
    for w, y in zip(MARCEL, (n, n - 1, n - 2)):
        p = BY.get(y, {}).get(pid)
        if p and p.get(key) is not None and p.get('toi'):
            num += w * p[key]; den += w * p['toi']
    return (num + K * mu) / (den + K)


def test_a():
    seas, pool_mse, pool_rho, grp = [], [], [], {}
    for n in range(2011, LAST):
        mu = mu_before(n)
        rows = []
        for pid, p in BY[n].items():
            q = BY[n + 1].get(pid)
            if not q or (p.get('toi') or 0) < 200 or (q.get('toi') or 0) < 200 or p.get('war') is None:
                continue
            b = (p.get('pwar') or 0.0) / p['toi'] * q['toi']
            a = marcel(pid, n, 'war', mu[p['grp']]) * q['toi']
            rows.append((p['grp'], p['war'], p['gp'], q['war'], b, a))
        R = np.array([r[1:] for r in rows], float)
        g = np.array([r[0] for r in rows])
        eb, ea = (R[:, 3] - R[:, 2]) ** 2, (R[:, 4] - R[:, 2]) ** 2
        seas.append((n, len(R), eb.mean(), ea.mean(), float(np.mean(R[:, 3] - R[:, 2])), float(np.mean(R[:, 4] - R[:, 2]))))
        top = np.zeros(len(R), bool)
        top[np.argsort(-R[:, 0])[:50]] = True
        top |= (g == 'G') & (R[:, 1] >= 20)
        pool_mse.append((eb[top].mean(), ea[top].mean()))
        pool_rho.append((stats.spearmanr(R[top, 3], R[top, 2])[0], stats.spearmanr(R[top, 4], R[top, 2])[0]))
        for k in 'FDG':
            m = g == k
            grp.setdefault(k, []).append((eb[m].mean(), ea[m].mean(), float(np.mean(R[m, 3] - R[m, 2])), float(np.mean(R[m, 4] - R[m, 2])),
                                          float(np.corrcoef(R[m, 3], R[m, 2])[0, 1]), float(np.corrcoef(R[m, 4], R[m, 2])[0, 1])))
    S = np.array(seas)
    d = S[:, 2] - S[:, 3]
    t, p = tstat(d)
    P, Q = np.array(pool_mse), np.array(pool_rho)
    tp, pp = tstat(P[:, 0] - P[:, 1])
    out = {'seasons': len(S), 'rows': int(S[:, 1].sum()), 'mse_before': round(float(S[:, 2].mean()), 4), 'mse_after': round(float(S[:, 3].mean()), 4),
           't': t, 'p': p, 'won': int((d > 0).sum()), 'bias_before': round(float(S[:, 4].mean()), 3), 'bias_after': round(float(S[:, 5].mean()), 3),
           'pool': {'mse_before': round(float(P[:, 0].mean()), 4), 'mse_after': round(float(P[:, 1].mean()), 4), 't': tp, 'p': pp,
                    'won': int((P[:, 0] > P[:, 1]).sum()), 'rho_before': round(float(Q[:, 0].mean()), 3), 'rho_after': round(float(Q[:, 1].mean()), 3)},
           'by_group': {k: dict(zip(('mse_before', 'mse_after', 'bias_before', 'bias_after', 'r_before', 'r_after'),
                                    [round(float(x), 4) for x in np.array(v).mean(0)])) for k, v in grp.items()},
           'by_season': [[int(r[0]), int(r[1]), round(r[2], 4), round(r[3], 4)] for r in seas]}
    out['pass'] = bool(t >= 2 and out['won'] >= 10 and out['pool']['mse_after'] <= out['pool']['mse_before']
                       and out['pool']['rho_after'] >= out['pool']['rho_before'] - .01)
    return out


SHAPE = {'C': 1, 'L': 1, 'R': 1, 'D': 2, 'G': 1}


def hpm_grade(pid, n, grp):
    num = den = 0.0
    for w, y in zip((1.0, 0.5, 0.25), (n, n - 1, n - 2)):
        p = BY.get(y, {}).get(pid)
        if p and p.get('hpm') is not None and p.get('toi'):
            num += w * p['toi'] * p['hpm']; den += w * p['toi']
    k, r = (1500.0 if grp == 'G' else 600.0), F[n]['repl'].get(grp, 0.0)
    return (num + k * r) / (den + k)


def test_b():
    rows = []                                   # season, isG, gap hpm, gap marcel, overtake (or nan), future GAR/60 gap (or nan)
    for n in range(2011, LAST):
        rooms = {}
        for p in F[n]['players']:
            if p.get('hpm') is None or not p.get('toi') or p.get('gar') is None:
                continue
            rooms.setdefault((p['tm'].split('/')[-1], p['pos']), []).append(p)
        for (tm, pos), L in rooms.items():
            k = SHAPE.get(pos)
            if not k or len(L) <= k:
                continue
            L.sort(key=lambda p: -p['toi'])
            for b in L[k:3 * k]:
                if b['toi'] < 100:
                    continue
                for s in L[:k]:
                    gh = hpm_grade(b['id'], n, b['grp']) - hpm_grade(s['id'], n, s['grp'])
                    gm = (marcel(b['id'], n, 'gar', 0.0) - marcel(s['id'], n, 'gar', 0.0)) * 60
                    qb, qs = BY[n + 1].get(b['id']), BY[n + 1].get(s['id'])
                    ot = fg = float('nan')
                    if qb and qs and qb['gp'] >= 20 and qs['gp'] >= 20:
                        ot = float(qb['toi'] / qb['gp'] > qs['toi'] / qs['gp'])
                    if qb and qs and qb['toi'] >= 200 and qs['toi'] >= 200 and qb.get('gar') is not None and qs.get('gar') is not None:
                        fg = qb['gar'] / qb['toi'] * 60 - qs['gar'] / qs['toi'] * 60
                    rows.append((n, pos == 'G', gh, gm, ot, fg))
    R = np.array(rows, float)
    ys = sorted(set(R[:, 0].astype(int)))

    def logit_fit(x, y):
        a = b = 0.0
        for _ in range(50):
            p = 1 / (1 + np.exp(-(a + b * x)))
            g = np.array([np.sum(y - p), np.sum((y - p) * x)])
            w = p * (1 - p)
            Hm = np.array([[w.sum(), (w * x).sum()], [(w * x).sum(), (w * x * x).sum()]]) + 1e-9 * np.eye(2)
            da, db = np.linalg.solve(Hm, g)
            a += da; b += db
        return a, b

    def run(mask):
        ll, ms = [], []
        for y in ys[4:]:
            for col, tgt, store in ((2, 4, ll), (3, 4, ll), (2, 5, ms), (3, 5, ms)):
                ok = mask & ~np.isnan(R[:, tgt])
                tr, te = ok & (R[:, 0] < y), ok & (R[:, 0] == y)
                sd = R[tr, col].std()
                xtr, xte = R[tr, col] / sd, R[te, col] / sd
                if tgt == 4:
                    a, b = logit_fit(xtr, R[tr, 4])
                    p = np.clip(1 / (1 + np.exp(-(a + b * xte))), 1e-6, 1 - 1e-6)
                    store.append((y, col, float(-np.mean(R[te, 4] * np.log(p) + (1 - R[te, 4]) * np.log(1 - p))), int(te.sum())))
                else:
                    A = np.c_[np.ones(tr.sum()), xtr]
                    c = np.linalg.lstsq(A, R[tr, 5], rcond=None)[0]
                    store.append((y, col, float(np.mean((np.c_[np.ones(te.sum()), xte] @ c - R[te, 5]) ** 2)), int(te.sum())))
        res = {}
        for name, st in (('overtake_logloss', ll), ('gar60_gap_mse', ms)):
            b = np.array([v[2] for v in st if v[1] == 2]); a = np.array([v[2] for v in st if v[1] == 3])
            t, p = tstat(b - a)
            res[name] = {'before': round(float(b.mean()), 5), 'after': round(float(a.mean()), 5), 't': t, 'p': p,
                         'won': int((b > a).sum()), 'seasons': len(b), 'n': int(sum(v[3] for v in st if v[1] == 2))}
        return res
    allm = np.ones(len(R), bool)
    out = {'pairs': len(R), 'all': run(allm), 'skaters': run(R[:, 1] == 0), 'goalies': run(R[:, 1] == 1)}
    o, g = out['all']['overtake_logloss'], out['all']['gar60_gap_mse']
    out['pass'] = bool(o['t'] >= 2 and o['won'] >= math.ceil(2 * o['seasons'] / 3) and g['after'] <= g['before'])
    return out


if __name__ == '__main__':
    A, B = test_a(), test_b()
    ps = sorted([('A', A['p']), ('B', B['all']['overtake_logloss']['p'])], key=lambda x: x[1])
    holm = {ps[0][0]: round(min(1.0, ps[0][1] * 2), 4)}
    holm[ps[1][0]] = round(min(1.0, max(ps[1][1], ps[0][1] * 2)), 4)
    A['p_holm'], B['p_holm'] = holm['A'], holm['B']
    A['pass'] = bool(A['pass'] and A['p_holm'] <= .05); B['pass'] = bool(B['pass'] and B['p_holm'] <= .05)
    out = {'A_awards_rest_of_season_war_rate': A, 'B_backup_watch_grade': B}
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.json'), 'w'), indent=1)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != 'by_season'} for k, v in out.items()}, indent=1))
