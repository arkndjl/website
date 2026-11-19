#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Leads 8, 9, 11 (family F): era-stable P(NBA) label, precision-weighted upper rungs, NBA-father name flag.
Pre-registered in impl/cbb/prereg.md. Needs scripts/.cache/cbb/careers.json (scripts/cbb_careers_kit.py).

    python3 scripts/research/sweep_nov19/cbb/fv_tests.py [engelmann.csv]
"""
import csv, gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import names as N
import cbb_data as D
import cbb_fit as F
import cbb_fv_core as FC
import cbb_live as L

KIT = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit')
OUT = os.environ.get('OUT', '/mnt/project-files/research-sweep-nov19/impl/cbb/fv_results.json')
FIT = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))


def clustered_t(d, g):
    """t of the mean of d with cluster sums over g"""
    s = defaultdict(float); n = defaultdict(int)
    for x, k in zip(d, g): s[k] += x; n[k] += 1
    v = np.array([s[k] for k in s]); G = len(v)
    if G < 2 or v.std(ddof=1) == 0: return 0.0
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(G)))


def wlogit(Z, y, lam, w):
    n, k = Z.shape
    A = np.hstack([np.ones((n, 1)), Z]); b = np.zeros(k + 1)
    m = float((w * y).sum() / w.sum())
    b[0] = math.log(max(m, 1e-4) / max(1 - m, 1e-4))
    P = np.eye(k + 1) * lam; P[0, 0] = 1e-3
    for _ in range(60):
        p = 1 / (1 + np.exp(-(A @ b)))
        g = A.T @ (w * (p - y)) + P @ b
        H = (A * (w * np.maximum(p * (1 - p), 1e-9))[:, None]).T @ A + P
        step = np.linalg.solve(H, g)
        step *= min(1.0, 2.0 / max(1e-12, np.abs(step).max()))
        b -= step
        if np.abs(step).max() < 1e-7: break
    return b


def fit_w(rows, X, lam, wts):
    """cbb_fit.fit with row weights on rungs 40+ (wts None = the shipped fit)"""
    y = np.array([r['y'] for r in rows], float)
    idx = list(range(X.shape[1]))
    std = F.Std(X, 4); Z = std(X)
    ws = []
    lams = lam if isinstance(lam, (list, tuple)) else [lam] * len(F.LADDER)
    for j, t in enumerate(F.LADDER):
        on = y >= (F.LADDER[j - 1] if j else -1)
        pen = lams[j] * max(1.0, on.sum() / 1000)
        if wts is None or j == 0:
            ws.append(F.logit_fit(Z[on], (y[on] >= t).astype(float), pen))
        else:
            w = wts[on]; w = w / w.mean()
            ws.append(wlogit(Z[on], (y[on] >= t).astype(float), pen, w))
    return {'std': std, 'idx': idx, 'w': ws}


def nba_minutes():
    by = defaultdict(list)
    for s in json.load(open(f'{KIT}/bbref_nba_seasons.json')): by[s['bref']].append((s['year'], s['mp'] or 0.0, s['g'] or 0.0))
    return by


def lead8(careers, rows, MP):
    def win(c):
        ss = [(y, mp, g) for y, mp, g in MP.get(c['nba'].get('bref'), []) if c['last'] < y <= c['last'] + 6]
        return sum(g for _, _, g in ss), sum(mp for _, mp, _ in ss)
    W = {c['pid']: win(c) for c in careers}
    cnt = defaultdict(lambda: [0, 0, 0, 0])
    for c in careers:
        if 2009 <= c['last'] <= 2022:
            g, mp = W[c['pid']]
            z = cnt[c['last']]
            z[0] += g >= 1; z[1] += g >= 1 and mp < 200; z[2] += mp >= 200; z[3] += mp >= 500
    era = lambda a, b: (sum(cnt[y][1] for y in range(a, b + 1)) / max(1, sum(cnt[y][0] for y in range(a, b + 1))))
    out = {'byClass': {str(y): cnt[y] for y in sorted(cnt)}, 'cols': ['1+ game', '1+ game <200 MP', '200+ MP', '500+ MP'],
           'lowShare_2009_16': round(era(2009, 2016), 4), 'lowShare_2017_20': round(era(2017, 2020), 4)}
    out['alive'] = out['lowShare_2017_20'] > out['lowShare_2009_16']
    if not out['alive']: return out
    for r in rows: r['l200'] = float(W[r['pid']][1] >= 200); r['l1'] = float(W[r['pid']][0] >= 1)
    tr = [r for r in rows if r['year'] <= 2016 and r['last'] <= 2020]
    te = [r for r in rows if 2017 <= r['year'] <= 2020 and r['last'] <= 2020]
    p0 = L.score_many([r['f'] for r in te], FIT)[1]
    p1 = np.zeros(len(te))
    for grp in ('newcomer', 'returner'):
        m = FIT['models'][grp]
        a = [r for r in tr if r['f']['newcomer'] == (grp == 'newcomer')]
        ix = [i for i, r in enumerate(te) if r['f']['newcomer'] == (grp == 'newcomer')]
        Xa = F.matrix(a, m['kept']); std = F.Std(Xa, 4)
        lam = m['lam'][0] if isinstance(m['lam'], list) else m['lam']
        w = F.logit_fit(std(Xa), np.array([r['l200'] for r in a]), lam * max(1.0, len(a) / 1000))
        Z = std(F.matrix([te[i] for i in ix], m['kept']))
        p1[ix] = 1 / (1 + np.exp(-(w[0] + Z @ w[1:])))
    y = np.array([r['l200'] for r in te]); y1 = np.array([r['l1'] for r in te]); yr = np.array([r['year'] for r in te])
    d = (p0 - y) ** 2 - (p1 - y) ** 2              # > 0: candidate better
    out['held'] = {'n': len(te), 'brier_shipped_on_L200': round(float(((p0 - y) ** 2).mean()), 5), 'brier_cand_on_L200': round(float(((p1 - y) ** 2).mean()), 5),
                   'brier_shipped_on_1game': round(float(((p0 - y1) ** 2).mean()), 5), 't_board': round(clustered_t(d, yr), 2),
                   'boards_better': int(sum(d[yr == b].sum() > 0 for b in sorted(set(yr)))), 'boards': len(set(yr)),
                   'sumP_cand': round(float(p1.sum()), 1), 'sumP_shipped': round(float(p0.sum()), 1), 'real_L200': float(y.sum()), 'real_1game': float(y1.sum())}
    h = out['held']
    h['pass'] = bool(h['t_board'] >= 2 and h['boards_better'] >= 3 and abs(h['sumP_cand'] / h['real_L200'] - 1) <= 0.10)
    return out


def lead9(careers, rows, MP, sheet):
    mp = {c['pid']: sum(m for _, m, _ in MP.get(c['nba'].get('bref'), [])) for c in careers}
    for r in rows:
        r['y'] = r['yfull']
        m = mp.get(r['pid'], 0.0)
        r['w'] = m / (m + 1500) if r['yfull'] >= 30 else 1.0
    base = [r for r in rows if r['year'] <= 2016 and r['last'] <= 2020]

    def run(train, test, weighted):
        e = np.zeros(len(test))
        for grp in ('newcomer', 'returner'):
            m = FIT['models'][grp]
            a = [r for r in train if r['f']['newcomer'] == (grp == 'newcomer')]
            ix = [i for i, r in enumerate(test) if r['f']['newcomer'] == (grp == 'newcomer')]
            if not ix: continue
            mod = fit_w(a, F.matrix(a, m['kept']), m['lam'], np.array([r['w'] for r in a]) if weighted else None)
            e[ix] = F.predict(mod, F.matrix([test[i] for i in ix], m['kept']))[2]
        return e
    cv = []
    for t in range(2009, 2017):
        test = [r for r in base if r['year'] == t]
        out_ = {r['pid'] for r in test}
        train = [r for r in base if r['year'] != t and r['pid'] not in out_]
        s0 = FC.board_scores(test, run(train, test, False), 'yfull'); s1 = FC.board_scores(test, run(train, test, True), 'yfull')
        cv.append((t, s0['corr300'], s1['corr300'], s0['top50'], s1['top50']))
    d = np.array([b - a for _, a, b, _, _ in cv])
    fw = []
    eng = []
    for t in (2017, 2018, 2019):
        test = [r for r in rows if r['year'] == t and r['y6'] is not None]
        e0, e1 = run(base, test, False), run(base, test, True)
        s0 = FC.board_scores(test, e0, 'y6'); s1 = FC.board_scores(test, e1, 'y6')
        fw.append((t, s0['corr300'], s1['corr300'], s0['top50'], s1['top50']))
    # Engelmann NBA_impact: each drafted 2017-22 player's last college board row (scoring only)
    if sheet:
        last = {}
        for r in rows:
            if r['year'] >= 2017 and (r['pid'] not in last or r['year'] > last[r['pid']]['year']): last[r['pid']] = r
        test = [r for r in last.values() if r['year'] == r['last']]
        e0, e1 = run(base, test, False), run(base, test, True)
        bykey = {(N.key(r['name']), r['last']): i for i, r in enumerate(test)}
        a0, a1, imp = [], [], []
        for s in sheet:
            try: yr = int(s['season']); v = float(s['NBA_impact'])
            except (ValueError, KeyError): continue
            i = bykey.get((N.key(s['name']), yr))
            if i is None or not 2017 <= yr <= 2022: continue
            a0.append(e0[i]); a1.append(e1[i]); imp.append(v)
        if len(imp) > 20:
            eng = [len(imp), round(F.spearman(np.array(a0), np.array(imp)), 4), round(F.spearman(np.array(a1), np.array(imp)), 4)]
    out = {'cv': [[t, round(a, 4), round(b, 4), round(c, 2), round(e, 2)] for t, a, b, c, e in cv], 'cols': ['board', 'corr300 base', 'corr300 weighted', 'top50 base', 'top50 weighted'],
           'cv_t': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'cv_meanD': round(float(d.mean()), 4), 'cv_better': int((d > 0).sum()),
           'forward': [[t, round(a, 4), round(b, 4), round(c, 2), round(e, 2)] for t, a, b, c, e in fw],
           'engelmann_n_rho_base_rho_weighted': eng}
    fa, fb = np.mean([x[1] for x in fw]), np.mean([x[2] for x in fw]); ta, tb = np.mean([x[3] for x in fw]), np.mean([x[4] for x in fw])
    out['pass'] = bool(out['cv_t'] >= 2 and fb >= fa and tb >= ta)
    return out


def lead11(careers, rows):
    src = json.load(gzip.open(os.path.join(D.HERE, 'data', 'alltime_src.json.gz')))['nbaS']
    first = {}
    for s in src:
        k = N.key(s['n'])
        first.setdefault(k, {}).setdefault(s['id'], s['y'])
        first[k][s['id']] = min(first[k][s['id']], s['y'])
    nw = [r for r in rows if r['f']['newcomer'] and r['year'] <= 2016 and r['last'] <= 2020]
    for r in nw:
        r['y'] = r['yfull']
        r['f']['dad'] = 1.0 if any(y <= r['year'] - 18 for y in first.get(N.key(r['name']), {}).values()) else 0.0
    flagged = [r for r in nw if r['f']['dad']]
    out = {'n': len(nw), 'flagged': len(flagged), 'flagged_nba': int(sum(r['yfull'] >= 30 for r in flagged)),
           'names': sorted({r['name'] for r in flagged})[:60]}
    if len(flagged) < 15:
        out['pass'] = False; out['why'] = 'fewer than 15 flagged rows'
        return out
    m = FIT['models']['newcomer']
    y = np.array([r['y'] for r in nw]); yr = np.array([r['year'] for r in nw])
    P = {}
    for name, cols in (('base', m['kept']), ('dad', m['kept'] + ['dad'])):
        X = F.matrix(nw, cols); Pm = np.zeros((len(nw), 4))
        for t in sorted(set(yr)):
            tr, te = yr != t, yr == t
            Pm[te] = F.predict(F.fit([r for r, k in zip(nw, tr) if k], X[tr], list(range(len(cols))), m['lam']), X[te])[1]
        P[name] = Pm
    d = FC.row_dev(P['base'], y).sum(1) - FC.row_dev(P['dad'], y).sum(1)       # > 0: flag better
    top = lambda Pm: float(np.mean([y[np.where(yr == b)[0][np.argsort(-F.expected(Pm)[yr == b])[:50]]].mean() for b in sorted(set(yr))]))
    out.update({'devGainPct': round(float(d.sum()) * 100, 3), 't_board': round(clustered_t(d, yr), 2),
                'folds_better': int(sum(d[yr == b].sum() > 0 for b in sorted(set(yr)))), 'top50_base': round(top(P['base']), 2), 'top50_flag': round(top(P['dad']), 2)})
    out['pass'] = bool(out['t_board'] >= 2 and out['folds_better'] >= 5 and out['top50_flag'] >= out['top50_base'])
    return out


if __name__ == '__main__':
    careers, rows, sc = FC.load()
    MP = nba_minutes()
    sheet = list(csv.DictReader(open(sys.argv[1], encoding='utf-8'))) if len(sys.argv) > 1 else None
    out = {'lead8': lead8(careers, rows, MP), 'lead9': lead9(careers, rows, MP, sheet), 'lead11': lead11(careers, rows)}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(out, indent=1))
