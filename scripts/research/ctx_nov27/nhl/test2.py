#!/usr/bin/env python3
"""NHL context audit, round 2 (prereg.md C, D) and the backup_age NHL block on today's season files -> results2.json

    python3 scripts/research/ctx_nov27/nhl/test2.py

Reads static/data/nhl-war/2009..2026.json only."""
import json
import math
import os
import sys

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import test as T  # noqa: E402
import backup_age_fit as BF  # noqa: E402

H = BF.H
SHAPE = {'C': 1, 'L': 1, 'R': 1, 'D': 2, 'G': 1}
S = {y: T.F[y] for y in T.F}
BY = T.BY


def rate(pid, ys, w, val, k, r):
    num = den = 0.0
    for y, wt in zip(ys, w):
        p = BY.get(y, {}).get(pid)
        if p and val(p) is not None and p.get('toi'):
            num += wt * p['toi'] * val(p); den += wt * p['toi']
    return (num + k * r) / (den + k)


def pairs():
    """backup_age_fit.pro_pairs for the NHL with two more columns: the Marcel GAR a 60 gap today and the pair's
    descriptive GAR a 60 gap over the next H seasons"""
    last = max(S)
    out = []
    g60 = lambda p: p['gar'] / p['toi'] * 60 if p.get('gar') is not None and p.get('toi') else None
    for y in sorted(S):
        if y - 2 not in S or y + H > last:
            continue
        kk = lambda p: 1500.0 if p['pos'] == 'G' else 600.0
        rp = lambda p: S[y].get('repl', {}).get(p['grp'], 0.0)
        g = lambda p: rate(p['id'], [y, y - 1, y - 2], (1, .5, .25), lambda q: q.get('hpm'), kk(p), rp(p))
        f = lambda p: rate(p['id'], [y + j for j in range(1, H + 1)], [1] * H, lambda q: q.get('hpm'), kk(p), rp(p))
        m = lambda p: rate(p['id'], [y, y - 1, y - 2], T.MARCEL, g60, T.K, 0.0)
        fd = lambda p: rate(p['id'], [y + j for j in range(1, H + 1)], [1] * H, g60, kk(p), 0.0)
        rooms = {}
        for p in S[y]['players']:
            if p.get('hpm') is None or not p.get('toi') or p.get('age') is None:
                continue
            rooms.setdefault(p['tm'], {}).setdefault(p['pos'], []).append(p)
        for R in rooms.values():
            for pos, L in R.items():
                n = SHAPE.get(pos)
                if not n or len(L) < n:
                    continue
                L.sort(key=lambda p: -p['toi'])
                gs, s = min(((g(x), x) for x in L[:n]), key=lambda t: t[0])
                for b in L[n:3 * n]:
                    gb = g(b)
                    if b['toi'] < 100 or gb <= gs:
                        continue
                    out.append((y, gb - gs, s['age'] - b['age'], f(b) - f(s), m(b) - m(s), fd(b) - fd(s)))
    return np.array(out, float)


def walk(P, cols, tgt, start_after=4):
    ys = sorted(set(P[:, 0].astype(int)))
    e, yy = [], []
    for y in ys[start_after:]:
        tr, te = P[P[:, 0] + H <= y], P[P[:, 0] == y]
        if len(tr) < 100 or not len(te):
            continue
        b = np.linalg.lstsq(np.c_[np.ones(len(tr)), tr[:, cols]], tr[:, tgt], rcond=None)[0]
        e += list((np.c_[np.ones(len(te)), te[:, cols]] @ b - te[:, tgt]) ** 2); yy += [y] * len(te)
    return np.array(e), np.array(yy)


def test_c():
    P = pairs()
    out = {'pairs': len(P)}
    for name, tgt in (('hpm_gap_2y', 3), ('gar60_gap_2y', 5)):
        e0, yy = walk(P, [1, 2], tgt)
        e1, _ = walk(P, [1, 2, 4], tgt)
        d = e1 - e0
        won = sum(1 for y in set(yy) if d[yy == y].mean() < 0)
        out[name] = {'held': len(d), 'mse_before': round(float(e0.mean()), 6), 'mse_after': round(float(e1.mean()), 6),
                     't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'won': won, 'seasons': len(set(yy))}
    b = np.linalg.lstsq(np.c_[np.ones(len(P)), P[:, [1, 2, 4]]], P[:, 3], rcond=None)[0]
    out['coef'] = {'a': round(float(b[0]), 5), 'b': round(float(b[1]), 4), 'c': round(float(b[2]), 5), 'd': round(float(b[3]), 5)}
    h, gd = out['hpm_gap_2y'], out['gar60_gap_2y']
    out['p'] = round(float(stats.t.cdf(h['t'], h['held'] - 1)), 4)
    out['pass'] = bool(h['t'] <= -2 and h['won'] > h['seasons'] / 2 and gd['mse_after'] <= gd['mse_before'])
    # the shipped block's own form on today's files (P5: data/backup_age.json nhl is from Nov 11, before the Nov 24 pWAR rebuild)
    f = BF.fit([tuple(r[:4]) for r in P])
    out['backup_age_refit'] = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in f.items() if k != 'z'}
    out['backup_age_live'] = json.load(open(os.path.join(T.ROOT, 'data', 'backup_age.json')))['sports']['nhl']
    return out


def test_d():
    seas = []
    for n in range(2012, T.LAST):
        num, den = {}, {}
        for y in range(2011, n):
            for p in T.F[y]['players']:
                if p.get('war') is None or not p.get('toi'):
                    continue
                new = p['id'] not in BY[y - 1] and p['id'] not in BY[y - 2]
                for k in (p['grp'], p['grp'] + ':n') if new else (p['grp'],):
                    num[k] = num.get(k, 0.0) + p['war']; den[k] = den.get(k, 0.0) + p['toi']
        eb, ea = [], []
        for pid, p in BY[n].items():
            q = BY[n + 1].get(pid)
            if pid in BY[n - 1] or pid in BY[n - 2] or not q or (p.get('toi') or 0) < 200 or (q.get('toi') or 0) < 200 or p.get('war') is None:
                continue
            g = p['grp']
            if g + ':n' not in den:
                continue
            for mu, e in ((num[g] / den[g], eb), (num[g + ':n'] / den[g + ':n'], ea)):
                e.append(((p['war'] + T.K * mu) / (p['toi'] + T.K) * q['toi'] - q['war']) ** 2)
        if eb:
            seas.append((n, len(eb), float(np.mean(eb)), float(np.mean(ea))))
    A = np.array(seas)
    d = A[:, 2] - A[:, 3]
    t, p = T.tstat(d)
    return {'seasons': len(A), 'rows': int(A[:, 1].sum()), 'mse_before': round(float(A[:, 2].mean()), 4), 'mse_after': round(float(A[:, 3].mean()), 4),
            't': t, 'p': p, 'won': int((d > 0).sum()), 'pass': bool(t >= 2 and (d > 0).sum() >= math.ceil(2 * len(A) / 3))}


if __name__ == '__main__':
    C, Dd = test_c(), test_d()
    ps = sorted([('C', C['p']), ('D', Dd['p'])], key=lambda x: x[1])
    holm = {ps[0][0]: min(1.0, ps[0][1] * 2)}
    holm[ps[1][0]] = min(1.0, max(ps[1][1], ps[0][1] * 2))
    C['p_holm'], Dd['p_holm'] = round(holm['C'], 4), round(holm['D'], 4)
    C['pass'] = bool(C['pass'] and C['p_holm'] <= .05); Dd['pass'] = bool(Dd['pass'] and Dd['p_holm'] <= .05)
    out = {'C_xgap_marcel_gap': C, 'D_awards_newcomer_mean': Dd}
    json.dump(out, open(os.path.join(HERE, 'results2.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))
