#!/usr/bin/env python3
"""rXPM round 3 (prereg.md "rXPM round 3"): schedule-neutral descriptive tests on Barttorvik game logs 2008-2026.
    python3 rxpm4.py -> rxpm4.json (+ rxpm4_fit.json: the shipped weights when a candidate passes)"""
import json, math, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gl
YEARS = gl.YEARS; CNT = gl.CNT; HCA = None
ROT_G, ROT_M, KREL = 8, 10.0, 200.0


def t_sf(t, df):
    x = np.linspace(abs(t), abs(t) + 400, 400001)
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    p = float(np.trapezoid(c * (1 + x ** 2 / df) ** (-(df + 1) / 2), x))
    return p if t >= 0 else 1 - p


def paired(d):
    d = np.asarray(d, float); t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std() > 0 else 0.0
    return round(t, 2), t_sf(t, len(d) - 1), int((d > 0).sum())


def build(y, hca):
    """season tables: stints (pid, team) with full / odd / even aggregates, team-games with adjusted margin"""
    S = gl.season(y); tg = S['tg']; sm = S['sm']; TR = S['tr']
    for r in tg.values():
        r['a'] = r['mg'] + r['oem'] - hca * r['h']
        r['ao'] = r['pf'] + r['ode'] - hca / 2 * r['h']; r['ad'] = r['pa'] + r['ooe'] + hca / 2 * r['h']   # adjusted pts for / against per 100
    st = defaultdict(lambda: {'g': 0, 'min': 0.0, 'h': [defaultdict(float), defaultdict(float)], 'games': {}})
    for p in S['pg']:
        k = (p['pid'], p['t']); q = st[k]; q['g'] += 1; q['min'] += p['min']; q['games'][p['d']] = p['min']
        hh = q['h'][0 if tg[(p['d'], p['t'])]['odd'] else 1]
        hh['e'] += p['e']; hh['min'] += p['min']; hh['gb'] += p['e'] * p['gb']; hh['ogb'] += p['e'] * p['ogb']; hh['dgb'] += p['e'] * p['dgb']
        for c in CNT: hh[c] += p[c]
    for k, q in st.items():
        q['mpg'] = q['min'] / q['g']; m = sm.get(k)
        q['bpm'] = m['bpm'] if m else None; q['gbpm'] = m['gbpm'] if m else None
        for s_ in ('obpm', 'dbpm', 'ogbpm', 'dgbpm'): q[s_] = m[s_] if m else None
        q['name'] = m['name'] if m else ''; q['yr'] = m['yr'] if m else ''
        q['e'] = q['h'][0]['e'] + q['h'][1]['e']
        q['rot'] = q['g'] >= ROT_G and q['mpg'] >= ROT_M and m is not None
    return {'y': y, 'tg': tg, 'st': dict(st), 'tr': TR}


def rates(st, which):
    """stint -> 13 rates per 100 possessions from the chosen halves (0 odd, 1 even, None both), z x reliability"""
    R = {}
    for k, q in st.items():
        hs = q['h'] if which is None else [q['h'][which]]
        e = sum(h['e'] for h in hs)
        if e <= 0: continue
        R[k] = (e, np.array([sum(h[c] for h in hs) / e * 100 for c in CNT]))
    big = [k for k in R if st[k]['rot']]
    X = np.array([R[k][1] for k in big]); w = np.array([R[k][0] for k in big])
    m = np.average(X, axis=0, weights=w); sd = np.sqrt(np.average((X - m) ** 2, axis=0, weights=w)); sd[sd == 0] = 1
    return {k: np.clip((x - m) / sd, -3, 3) * e / (e + KREL) for k, (e, x) in R.items()}, (m, sd)


def test_a_rows(B):
    """per team-game with a rotation absence: y (adjusted margin - team mean), x for bpm, gbpm, the 13 box z, O/D targets"""
    st, tg = B['st'], B['tg']; Z, _ = rates(st, None)
    byteam = defaultdict(list)
    for k, q in st.items():
        if q['rot'] and k in Z: byteam[k[1]].append(k)
    games = defaultdict(list)
    for (d, t), r in tg.items(): games[t].append(r)
    rows = []
    for t, ks in byteam.items():
        G = games[t]
        if len(G) < 10 or len(ks) < 5: continue
        F = np.array([[st[k]['bpm'], st[k]['gbpm'], st[k]['obpm'], st[k]['dbpm'], st[k]['ogbpm'], st[k]['dgbpm']] + list(Z[k]) for k in ks])
        w = np.array([st[k]['mpg'] for k in ks])
        Lg = []
        for r in G:
            a = np.array([1.0 if r['d'] in st[k]['games'] else 0.0 for k in ks]); ww = w * a
            Lg.append((ww @ F) / ww.sum() if ww.sum() > 0 else np.full(F.shape[1], np.nan))
        Lg = np.array(Lg); ok = ~np.isnan(Lg[:, 0])
        Lm = Lg[ok].mean(axis=0); ya = np.array([r['a'] for r in G]); yo = np.array([r['ao'] for r in G]); yd = np.array([r['ad'] for r in G])
        for i in np.where(ok)[0]:
            x = Lg[i] - Lm
            if np.abs(x).max() < 1e-9: continue
            n = ok.sum(); c = n / (n - 1)                       # leave-this-game-out team mean
            rows.append(np.concatenate([[(ya[i] - ya[ok].mean()) * c, (yo[i] - yo[ok].mean()) * c, (yd[i] - yd[ok].mean()) * c], x * c]))
    return np.array(rows)


def ridge(X, y, lam, nfree):
    P = np.full(X.shape[1], lam); P[:nfree] = 0.0
    return np.linalg.solve(X.T @ X + np.diag(P), X.T @ y)


LAMS = [30, 100, 300, 1000]
AG = [0, .25, .5, .75, 1]
COL = {'y': 0, 'yo': 1, 'yd': 2, 'bpm': 3, 'gbpm': 4, 'obpm': 5, 'dbpm': 6, 'ogbpm': 7, 'dgbpm': 8}
ZC = slice(9, 9 + len(CNT))


def test_a(RA):
    """leave-one-season-out SSE by candidate; returns per-season SSE dicts and the per-held-out-season fits"""
    ys = sorted(RA); sse = defaultdict(dict); fits = {}
    def base(R, a): return a * R[:, COL['bpm']] + (1 - a) * R[:, COL['gbpm']]
    def fit1(Rs, a):
        x = np.concatenate([base(R, a) for R in Rs]); yy = np.concatenate([R[:, 0] for R in Rs]); return float(x @ yy / (x @ x))
    def sse1(R, a, b): return float(((R[:, 0] - b * base(R, a)) ** 2).sum())
    def x2(R, a): return np.column_stack([base(R, a), R[:, ZC]])
    def fit2(Rs, a, lam): return ridge(np.vstack([x2(R, a) for R in Rs]), np.concatenate([R[:, 0] for R in Rs]), lam, 1)
    def side(R, s, a): return np.column_stack([a * R[:, COL[s + 'bpm']] + (1 - a) * R[:, COL[s + 'gbpm']], R[:, ZC]])
    def fits_(Rs, s, a, lam): return ridge(np.vstack([side(R, s, a) for R in Rs]), np.concatenate([R[:, COL['y' + s]] for R in Rs]), lam, 1)
    for y in ys:
        tr = [s for s in ys if s != y]; R = RA[y]
        sse['none'][y] = float((R[:, 0] ** 2).sum())
        for nm, a in (('BPM', 1.0), ('GBPM', 0.0)): sse[nm][y] = sse1(R, a, fit1([RA[s] for s in tr], a))
        # X1: a by inner LOSO
        def inner1(a): return sum(sse1(RA[m], a, fit1([RA[s] for s in tr if s != m], a)) for m in tr)
        a1 = min(AG, key=inner1); sse['X1'][y] = sse1(R, a1, fit1([RA[s] for s in tr], a1))
        # X2: lambda by inner LOSO at a1
        def inner2(lam): return sum(float(((RA[m][:, 0] - x2(RA[m], a1) @ fit2([RA[s] for s in tr if s != m], a1, lam)) ** 2).sum()) for m in tr)
        l2 = min(LAMS, key=inner2); b2 = fit2([RA[s] for s in tr], a1, l2); sse['X2'][y] = float(((R[:, 0] - x2(R, a1) @ b2) ** 2).sum())
        # X3: per side (offence target up is good; defence target = points allowed, so the base enters negatively)
        def inner3(lam):
            t = 0.0
            for m in tr:
                o = [s for s in tr if s != m]
                p = side(RA[m], 'o', a1) @ fits_([RA[s] for s in o], 'o', a1, lam) - side(RA[m], 'd', a1) @ fits_([RA[s] for s in o], 'd', a1, lam)
                t += float(((RA[m][:, 0] - p) ** 2).sum())
            return t
        l3 = min(LAMS, key=inner3)
        bo, bd = fits_([RA[s] for s in tr], 'o', a1, l3), fits_([RA[s] for s in tr], 'd', a1, l3)
        sse['X3'][y] = float(((R[:, 0] - (side(R, 'o', a1) @ bo - side(R, 'd', a1) @ bd)) ** 2).sum())
        fits[y] = {'a': a1, 'lam2': l2, 'b2': b2, 'lam3': l3, 'bo': bo, 'bd': bd, 'slopeBPM': fit1([RA[s] for s in tr], 1.0), 'slopeGBPM': fit1([RA[s] for s in tr], 0.0)}
        print('A', y, len(R), a1, l2, l3, {k: round(1 - sse[k][y] / sse['none'][y], 5) for k in sse if k != 'none'}, flush=True)
    return sse, fits


def summarize(sse, base_names, cands):
    ys = sorted(sse['none']); tot = sum(sse['none'].values()); out = {}
    for k in sse:
        if k == 'none': continue
        out[k] = {'R2': round(1 - sum(sse[k].values()) / tot, 5)}
    for c in cands:
        for b in base_names:
            t, p, n = paired([sse[b][y] - sse[c][y] for y in ys]); out[c][f'vs{b}'] = {'t': t, 'p': round(p, 5), 'seasonsBetter': n, 'of': len(ys)}
    return out


def main():
    global HCA
    # venue term: pooled slope of (margin + opponent adjEM - own adjEM) on h
    num = den = 0.0
    for y in YEARS:
        S = gl.season(y)
        for r in S['tg'].values():
            num += r['h'] * (r['mg'] + r['oem'] - S['tr'][r['t']]['em']); den += r['h'] ** 2
    HCA = num / den; print('hca', HCA, flush=True)
    B = {y: build(y, HCA) for y in YEARS}
    pickle.dump((HCA, B), open(os.path.join(gl.GB, 'built.pkl'), 'wb'))
    RA = {y: test_a_rows(B[y]) for y in YEARS}
    pickle.dump(RA, open(os.path.join(gl.GB, 'ra.pkl'), 'wb'))
    sse, fits = test_a(RA)
    out = {'hca': round(HCA, 3), 'rowsA': {y: len(RA[y]) for y in YEARS}, 'A': summarize(sse, ['BPM', 'GBPM'], ['X1', 'X2', 'X3']),
           'A_bySeason': {k: {y: round(1 - sse[k][y] / sse['none'][y], 5) for y in YEARS} for k in sse if k != 'none'},
           'A_fits': {y: {'a': f['a'], 'lam2': f['lam2'], 'lam3': f['lam3'], 'slopeBPM': round(f['slopeBPM'], 3), 'slopeGBPM': round(f['slopeGBPM'], 3),
                          'd2': {c: round(float(v / f['b2'][0]), 3) for c, v in zip(CNT, f['b2'][1:])}} for y, f in fits.items()}}
    pickle.dump(fits, open(os.path.join(gl.GB, 'fitsA.pkl'), 'wb'))
    json.dump(out, open(os.path.join(HERE, 'rxpm4.json'), 'w'), indent=1)
    print(json.dumps(out['A'], indent=1))


if __name__ == '__main__':
    main()
