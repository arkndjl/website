#!/usr/bin/env python3
"""rXPM round 3, tests B, C, guards G / N / R1 / R2 and S0 (prereg.md). Needs rxpm4.py's pickles.
    python3 rxpm5.py -> rxpm5.json"""
import json, math, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gl, rxpm4 as R4
from rxpm4 import paired, rates, CNT, YEARS, COL, ZC
HCA, B = pickle.load(open(os.path.join(gl.GB, 'built.pkl'), 'rb'))
FITS = pickle.load(open(os.path.join(gl.GB, 'fitsA.pkl'), 'rb'))
RA = pickle.load(open(os.path.join(gl.GB, 'ra.pkl'), 'rb'))
OUT = {}


def dvec(y): f = FITS[y]; return f['a'], f['b2'][1:] / f['b2'][0]


def loso_slope_sse(rows):
    """rows: season -> (x, y) arrays centred within season; SSE of the other-seasons no-intercept slope, and SST"""
    out = {}
    for y in rows:
        xs = np.concatenate([rows[s][0] for s in rows if s != y]); yy = np.concatenate([rows[s][1] for s in rows if s != y])
        b = float(xs @ yy / (xs @ xs)); out[y] = (float(((rows[y][1] - b * rows[y][0]) ** 2).sum()), float((rows[y][1] ** 2).sum()))
    return out


def r2(L): return round(1 - sum(a for a, _ in L.values()) / sum(b for _, b in L.values()), 4)


# ------------------------------------------------------------------ full-season player values
def full_values(y, frozen=None):
    """(pid, team) -> dict(bpm, gbpm, x1, x2, e minutes) ; x2 = base + d.z, zero-sum within team (minutes weighted)"""
    st = B[y]['st']; Z, _ = rates(st, None); a, d = frozen if frozen else dvec(y)
    V = {}; num = defaultdict(float); den = defaultdict(float)
    for k, q in st.items():
        if q['bpm'] is None or k not in Z: continue
        c = float(d @ Z[k]); V[k] = {'bpm': q['bpm'], 'gbpm': q['gbpm'], 'x1': a * q['bpm'] + (1 - a) * q['gbpm'], 'c': c, 'e': q['min'], 'rot': q['rot'], 'name': q['name']}
        num[k[1]] += c * q['min']; den[k[1]] += q['min']
    for k, v in V.items(): v['x2'] = v['x1'] + v['c'] - num[k[1]] / den[k[1]]
    return V


FV = {y: full_values(y) for y in YEARS}


# ------------------------------------------------------------------ test C (team level, full season)
def test_c():
    res = {}
    for tgt in ('em', 'wab_g', 'wp'):
        res[tgt] = {}
        for m in ('bpm', 'gbpm', 'x1', 'x2'):
            rows = {}
            for y in YEARS:
                num = defaultdict(float); den = defaultdict(float)
                for (pid, t), v in FV[y].items(): num[t] += v[m] * v['e']; den[t] += v['e']
                ts = [t for t in num if t in B[y]['tr']]
                x = np.array([5 * num[t] / den[t] for t in ts]); yy = np.array([B[y]['tr'][t][tgt] for t in ts])
                rows[y] = (x - x.mean(), yy - yy.mean())
            L = loso_slope_sse(rows); res[tgt][m] = {'R2': r2(L), 'sse': {y: L[y][0] for y in L}}
        for m in ('x1', 'x2'):
            for b in ('bpm', 'gbpm'):
                t, p, n = paired([res[tgt][b]['sse'][y] - res[tgt][m]['sse'][y] for y in YEARS]); res[tgt][m]['vs_' + b] = {'t': t, 'better': n}
        for m in res[tgt]: res[tgt][m].pop('sse')
    return res


# ------------------------------------------------------------------ guard G
def guard_g():
    sd = {}
    for m in ('bpm', 'gbpm', 'x1', 'x2'):
        x = np.array([v[m] for y in YEARS for v in FV[y].values() if v['e'] >= 300]); w = np.array([v['e'] for y in YEARS for v in FV[y].values() if v['e'] >= 300])
        mu = np.average(x, weights=w); sd[m] = round(float(math.sqrt(np.average((x - mu) ** 2, weights=w))), 3)
    d = np.array([dvec(y)[1] for y in YEARS])
    c = np.array([v['x2'] - v['x1'] for y in YEARS for v in FV[y].values() if v['e'] >= 300])
    r = np.corrcoef([v['x2'] for y in YEARS for v in FV[y].values() if v['e'] >= 300], [v['bpm'] for y in YEARS for v in FV[y].values() if v['e'] >= 300])[0, 1]
    return {'sd': sd, 'maxWeightPerSD': round(float(np.abs(d).max()), 3), 'weightsMean': {k: round(float(v), 3) for k, v in zip(CNT, d.mean(axis=0))},
            'weightsSDacrossFolds': {k: round(float(v), 3) for k, v in zip(CNT, d.std(axis=0))}, 'correctionSD': round(float(c.std()), 3), 'r_x2_bpm': round(float(r), 4)}


# ------------------------------------------------------------------ guard N (next season; audit harness, pairs 2012-2025)
def guard_n():
    sys.path.insert(0, os.path.join(gl.ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb'))
    import audit as A
    def vals(n, m):
        num = defaultdict(float); den = defaultdict(float)
        for (pid, t), v in FV[n].items(): num[pid] += v[m] * v['e']; den[pid] += v['e']
        return {pid: num[pid] / den[pid] for pid in num if pid in A.S[n]['pl']}
    res = {}; sc = {}
    for m in ('bpm', 'gbpm', 'x1', 'x2'):
        _, _, s = A.predict(lambda n: vals(n, m)); sc[m] = s
        res[m] = {'teamR2': s['teamR2'], 'playerR_vsBPM': s['playerR_vsBPM']}
    for b in ('bpm', 'gbpm', 'x1'):
        t, p, n = paired([sc['x2']['byPair'][k] - sc[b]['byPair'][k] for k in A.PAIRS]); res['x2']['vs_' + b] = {'t': t, 'pairsBetter': n, 'of': len(A.PAIRS)}
    t, p, n = paired([sc['x1']['byPair'][k] - sc['bpm']['byPair'][k] for k in A.PAIRS]); res['x1']['vs_bpm'] = {'t': t, 'pairsBetter': n}
    return res


# ------------------------------------------------------------------ test B (split half, leak-free) + S0
def half_values(y, H):
    """(pid, team) -> dict of half-H values: gb (odd-game GBPM), bl (BPM-like), d8, x1, x2; team half means"""
    st, tg = B[y]['st'], B[y]['tg']; a, d = dvec(y); Z, _ = rates(st, H)
    am = defaultdict(list); rm = defaultdict(list)
    for (dd, t), r in tg.items():
        if r['odd'] == (H == 0): am[t].append(r['a']); rm[t].append(r['mg'])
    gb = {}; num = defaultdict(float); den = defaultdict(float); cn = defaultdict(float)
    for k, q in st.items():
        h = q['h'][H]
        if h['e'] <= 0 or k not in Z: continue
        gb[k] = h['gb'] / h['e']; num[k[1]] += gb[k] * h['min']; den[k[1]] += h['min']; cn[k[1]] += float(d @ Z[k]) * h['min']
    V = {}
    for k, g in gb.items():
        t = k[1]
        if t not in am: continue
        sh = (np.mean(am[t]) - 5 * num[t] / den[t]) / 5; sh8 = (.75 * np.mean(rm[t]) + .25 * np.mean(am[t]) - 5 * num[t] / den[t]) / 5
        bl = g + sh; x1 = a * bl + (1 - a) * g
        V[k] = {'gb': g, 'bl': bl, 'd8': g + sh8, 'x1': x1, 'x2': x1 + float(d @ Z[k]) - cn[t] / den[t], 'e': st[k]['h'][H]['e']}
    return V


def test_b():
    M = ('gb', 'bl', 'd8', 'x1', 'x2'); rows = {m: {} for m in M}; rows_raw = {m: {} for m in M}
    for y in YEARS:
        st, tg = B[y]['st'], B[y]['tg']; acc = {m: ([], [], []) for m in M}
        for H in (0, 1):
            V = half_values(y, H); O = 1 - H
            fill = {m: float(np.mean([v[m] for v in V.values() if v['e'] < 150])) for m in M}
            am = defaultdict(list); rm = defaultdict(list)
            for (dd, t), r in tg.items():
                if r['odd'] == (O == 0): am[t].append(r['a']); rm[t].append(r['mg'])
            num = {m: defaultdict(float) for m in M}; den = defaultdict(float)
            for k, q in st.items():
                mn = q['h'][O]['min']
                if mn <= 0: continue
                den[k[1]] += mn
                for m in M: num[m][k[1]] += mn * (V[k][m] if k in V else fill[m])
            ts = [t for t in den if len(am[t]) >= 5]
            for m in M:
                x = np.array([5 * num[m][t] / den[t] for t in ts]); ya = np.array([np.mean(am[t]) for t in ts]); yr = np.array([np.mean(rm[t]) for t in ts])
                acc[m][0].append(x - x.mean()); acc[m][1].append(ya - ya.mean()); acc[m][2].append(yr - yr.mean())
        for m in M:
            rows[m][y] = (np.concatenate(acc[m][0]), np.concatenate(acc[m][1])); rows_raw[m][y] = (np.concatenate(acc[m][0]), np.concatenate(acc[m][2]))
    res = {}
    for nm, RW in (('adjusted margin (schedule-neutral)', rows), ('raw margin (round 2 target)', rows_raw)):
        L = {m: loso_slope_sse(RW[m]) for m in M}; res[nm] = {}
        for m in M:
            res[nm][m] = {'R2': r2(L[m])}
            for b in ('gb', 'bl'):
                if m == b: continue
                t, p, n = paired([L[b][y][0] - L[m][y][0] for y in YEARS]); res[nm][m]['vs_' + b] = {'t': t, 'better': n}
    return res


# ------------------------------------------------------------------ R1 starters only (weights frozen from test A)
def r1():
    sse = defaultdict(dict)
    rows = {}
    for y in YEARS:
        st, tg = B[y]['st'], B[y]['tg']; V = FV[y]
        byteam = defaultdict(list)
        for k in V: byteam[k[1]].append(k)
        games = defaultdict(list)
        for (d, t), r in tg.items(): games[t].append(r)
        out = []
        for t, ks in byteam.items():
            core = [k for k in ks if st[k]['g'] >= 8 and st[k]['mpg'] >= 20]; rest = [k for k in ks if k not in core]
            G = games[t]
            if len(core) < 3 or not rest or len(G) < 10: continue
            wr = np.array([V[k]['e'] for k in rest])
            F = np.array([[V[k][m] - float(np.average([V[j][m] for j in rest], weights=wr)) for m in ('bpm', 'gbpm', 'x1', 'x2')] for k in core])
            w = np.array([st[k]['mpg'] / 40 for k in core])
            L = np.array([(w * np.array([1.0 if r['d'] in st[k]['games'] else 0.0 for k in core])) @ F for r in G])
            ya = np.array([r['a'] for r in G]); n = len(G); c = n / (n - 1)
            X = (L - L.mean(axis=0)) * c; Y = (ya - ya.mean()) * c
            keep = np.abs(X).max(axis=1) > 1e-9
            out.append(np.column_stack([Y[keep], X[keep]]))
        rows[y] = np.vstack(out)
    res = {'rows': int(sum(len(r) for r in rows.values()))}
    for j, m in enumerate(('bpm', 'gbpm', 'x1', 'x2')):
        L = loso_slope_sse({y: (rows[y][:, 1 + j], rows[y][:, 0]) for y in YEARS}); sse[m] = {y: L[y][0] for y in YEARS}
        xs = np.concatenate([rows[y][:, 1 + j] for y in YEARS]); yy = np.concatenate([rows[y][:, 0] for y in YEARS])
        res[m] = {'R2': r2(L), 'slope': round(float(xs @ yy / (xs @ xs)), 3)}
    for m in ('x1', 'x2'):
        for b in ('bpm', 'gbpm'):
            t, p, n = paired([sse[b][y] - sse[m][y] for y in YEARS]); res[m]['vs_' + b] = {'t': t, 'better': n}
    return res


# ------------------------------------------------------------------ R2 leave-the-game-out ratings (test A rows rebuilt)
def r2_rows(y):
    S = gl.season(y); st, tg = B[y]['st'], B[y]['tg']; _, (mu, sd) = rates(st, None)
    per = defaultdict(dict)
    for p in S['pg']: per[(p['pid'], p['t'])][p['d']] = (p['e'], p['gb'], np.array([p[c] for c in CNT]))
    byteam = defaultdict(list)
    for k, q in st.items():
        if q['rot']: byteam[k[1]].append(k)
    games = defaultdict(list)
    for (d, t), r in tg.items(): games[t].append(r)
    rows = []
    for t, ks in byteam.items():
        G = games[t]
        if len(G) < 10 or len(ks) < 5: continue
        E = np.array([st[k]['e'] for k in ks]); Cn = np.array([sum(v[2] for v in per[k].values()) for k in ks]); GBs = np.array([sum(v[0] * v[1] for v in per[k].values()) for k in ks])
        bpm = np.array([st[k]['bpm'] for k in ks]); gbp = np.array([st[k]['gbpm'] for k in ks]); w = np.array([st[k]['mpg'] for k in ks])
        zfull = np.clip((Cn / E[:, None] * 100 - mu) / sd, -3, 3) * (E / (E + R4.KREL))[:, None]
        Lg = []
        for r in G:
            a = np.zeros(len(ks)); Fb = np.column_stack([bpm, gbp]).astype(float); Z = zfull.copy()
            for i, k in enumerate(ks):
                g = per[k].get(r['d'])
                if g is None: continue
                a[i] = 1.0; e1 = E[i] - g[0]
                if e1 <= 0: a[i] = 0.0; continue
                dl = GBs[i] / E[i] - (GBs[i] - g[0] * g[1]) / e1
                Fb[i, 0] -= dl; Fb[i, 1] -= dl
                Z[i] = np.clip(((Cn[i] - g[2]) / e1 * 100 - mu) / sd, -3, 3) * e1 / (e1 + R4.KREL)
            ww = w * a
            F = np.column_stack([Fb, np.zeros((len(ks), 4)), Z])
            Lg.append((ww @ F) / ww.sum() if ww.sum() > 0 else np.full(F.shape[1], np.nan))
        Lg = np.array(Lg); ok = ~np.isnan(Lg[:, 0]); Lm = Lg[ok].mean(axis=0); ya = np.array([r['a'] for r in G]); n = ok.sum(); c = n / (n - 1)
        for i in np.where(ok)[0]:
            x = Lg[i] - Lm
            rows.append(np.concatenate([[(ya[i] - ya[ok].mean()) * c, 0, 0], x * c]))
    return np.array(rows)


def r2_test():
    RL = {y: r2_rows(y) for y in YEARS}
    ys = YEARS; sse = defaultdict(dict); a = .75
    def base(R, a_): return a_ * R[:, COL['bpm']] + (1 - a_) * R[:, COL['gbpm']]
    for y in ys:
        tr = [s for s in ys if s != y]; R = RL[y]; sse['none'][y] = float((R[:, 0] ** 2).sum())
        for nm, a_ in (('BPM', 1.0), ('GBPM', 0.0), ('X1', a)):
            x = np.concatenate([base(RL[s], a_) for s in tr]); yy = np.concatenate([RL[s][:, 0] for s in tr]); b = float(x @ yy / (x @ x))
            sse[nm][y] = float(((R[:, 0] - b * base(R, a_)) ** 2).sum())
        X = np.vstack([np.column_stack([base(RL[s], a), RL[s][:, ZC]]) for s in tr]); yy = np.concatenate([RL[s][:, 0] for s in tr])
        b2 = R4.ridge(X, yy, 30, 1); sse['X2 refit'][y] = float(((R[:, 0] - np.column_stack([base(R, a), R[:, ZC]]) @ b2) ** 2).sum())
        f = FITS[y]; sse['X2 frozen'][y] = float(((R[:, 0] - np.column_stack([base(R, a), R[:, ZC]]) @ f['b2']) ** 2).sum())
        if y == ys[-1]: w_last = {c: round(float(v / b2[0]), 3) for c, v in zip(CNT, b2[1:])}
    res = R4.summarize(sse, ['BPM', 'GBPM'], ['X1', 'X2 refit', 'X2 frozen']); res['weights (refit, last fold)'] = w_last
    return res


if __name__ == '__main__':
    for nm, fn in (('C', test_c), ('G', guard_g), ('N', guard_n), ('B', test_b), ('R1', r1), ('R2', r2_test)):
        OUT[nm] = fn(); print(nm, json.dumps(OUT[nm], indent=None), flush=True)
        json.dump(OUT, open(os.path.join(HERE, 'rxpm5.json'), 'w'), indent=1)
