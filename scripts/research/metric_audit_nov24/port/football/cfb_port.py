#!/usr/bin/env python3
"""CFB port tests (prereg.md): (a) XV fit per side, (b) pXR form of the predictive value, (d) G5 level weighting.
Rows/harness: ../../cfb/harness.py (2019-25, seven positions; no 2026).   -> cfb_port.json"""
import json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cfb'))
import harness as H

YEARS, PAIRS, J, R = H.YEARS, H.PAIRS, H.J, H.R
CWAR_V, SAV_W = H.CWAR_V, H.SAV_W
P7, OFF7, DEF7 = H.P7, ['QB', 'RB', 'WR', 'TE'], ['EDGE', 'DL', 'LB']
PARTS = {'QB': ['cmp', 'nypa', 'intr', 'rush'], 'RB': ['ypc', 'elu'], 'WR': ['catch', 'ypr', 'epa'], 'TE': ['catch', 'epa', 'blk'],
         'EDGE': ['prs', 'sk', 'spl'], 'DL': ['prs', 'spl', 'sk'], 'LB': ['cov', 'prs', 'tfl']}
COLS = [(g, k) for g in P7 for k in PARTS[g]]
SAV_REPL, LAM = -1, 50
P4 = {'SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12'}

# ---- part z per player (as cfb_xv_backtest.py: starter pool, cap 3, missing 0) and conference --------------------------
Z, CONF = {}, {}
for y in YEARS:
    nT = len(J['SRS'][str(y)])
    for g in P7:
        L = [r for r in J['rows'] if r['season'] == y and r['pos'] == g and r.get('z') is not None]
        pool = sorted(L, key=lambda r: -r['score'])[:H.STARTERS[g] * nT]
        pc = {id(r): H.parts(g, r['raw']) for r in L}
        zz = defaultdict(dict)
        for k in ['score'] + PARTS[g]:
            get = (lambda r: r['score']) if k == 'score' else (lambda r, k=k: pc[id(r)].get(k))
            v = [get(r) for r in pool if get(r) is not None]
            m, s = (float(np.mean(v)), float(np.std(v)) or 1.0) if len(v) >= 20 else (0.0, None)
            for r in L:
                x = get(r); zz[id(r)][k] = 0.0 if x is None or s is None else max(-3.0, min(3.0, (x - m) / s))
        for r in L:
            pid = r['id'] + '|' + g
            if pid in R[y] and R[y][pid]['tid'] == r['tid'] and abs(R[y][pid]['sh'] - r['sh']) < 1e-9:
                Z[(y, pid)] = zz[id(r)]
                c = r['raw'].get('conf'); CONF[(y, pid)] = c in P4 or r['raw'].get('team') == 'Notre Dame'

# ---- opponent-adjusted offense / defense ratings (points, cap 63, ridge 2, home) ---------------------------------------
def od(y):
    fbs = sorted(J['SRS'][str(y)]); ix = {t: i for i, t in enumerate(fbs)}; n = len(fbs); rows, ys = [], []
    for g in J['GAMES'][str(y)]:
        h, a = ix.get(g['h']), ix.get(g['a'])
        if h is None or a is None: continue
        hfa = 0 if g['n'] else 1
        for o, d, s, sg in ((h, a, g['hs'], 1), (a, h, g['as'], -1)):
            r = np.zeros(2 * n + 2); r[o], r[n + d], r[2 * n], r[2 * n + 1] = 1, -1, hfa * sg, 1
            rows.append(r); ys.append(min(s, 63))
    X, Y = np.array(rows), np.array(ys)
    b = np.linalg.solve(X.T @ X + np.diag([2.0] * (2 * n) + [0.0, 0.0]), X.T @ Y)
    o, dd = b[:n] - b[:n].mean(), b[n:2 * n] - b[n:2 * n].mean()
    return {t: o[i] for i, t in enumerate(fbs)}, {t: dd[i] for i, t in enumerate(fbs)}
OD = {y: od(y) for y in YEARS}
TGT = {y: {'srs': H.SRS[y], 'off': OD[y][0], 'dfn': OD[y][1]} for y in YEARS}

# ---- team XV features ---------------------------------------------------------------------------------------------------
TF = {}
for y in YEARS:
    S, C = defaultdict(lambda: np.zeros(len(P7))), defaultdict(lambda: np.zeros(len(COLS)))
    for pid, t, e in H.PARTS[(y, 7)]:
        g = H.g_(pid); z = Z.get((y, pid))
        if z is None: continue
        S[t][P7.index(g)] += e * (z['score'] - SAV_REPL)
        for i, (gg, k) in enumerate(COLS):
            if gg == g: C[t][i] += e * z[k]
    TF[y] = {t: (S[t], C[t]) for t in H.SRS[y] if t in S}


def fit(train, pos, key):
    js = [P7.index(g) for g in pos]; ci = [i for i, (g, _) in enumerate(COLS) if g in pos]
    ts = [(y, t) for y in train for t in TF[y] if t in TGT[y][key]]
    Sm = np.array([TF[y][t][0][js] for y, t in ts]); Cm = np.array([TF[y][t][1][ci] for y, t in ts])
    Y = np.array([TGT[y][key][t] for y, t in ts])
    # centre within season (as the harness does for its targets)
    for y in train:
        ix = [i for i, (yy, _) in enumerate(ts) if yy == y]
        Sm[ix] -= Sm[ix].mean(0); Cm[ix] -= Cm[ix].mean(0); Y[ix] -= Y[ix].mean()
    sd = Cm.std(0) + 1e-9; act = list(range(len(ci)))
    while True:
        M = np.hstack([Sm, Cm[:, act] / sd[act]])
        b = np.linalg.solve(M.T @ M + np.diag([0.0] * len(js) + [LAM] * len(act)), M.T @ Y)
        bad = [a for i, a in enumerate(act) if b[len(js) + i] < 0]
        if not bad: break
        act.remove(min(bad, key=lambda a: b[len(js) + act.index(a)]))
    w = np.zeros(len(P7)); c = np.zeros(len(COLS))
    for i, j in enumerate(js): w[j] = b[i]
    for i, a in enumerate(act): c[ci[a]] = b[len(js) + i] / sd[a]
    return w, c


def xv_rows(train, side):
    if side: (w1, c1), (w2, c2) = fit(train, OFF7, 'off'), fit(train, DEF7, 'dfn'); w, c = w1 + w2, c1 + c2
    else: w, c = fit(train, P7, 'srs')
    return {y: H.centre({t: np.array([S @ w + C @ c]) for t, (S, C) in TF[y].items()}, H.SRS[y]) for y in YEARS}, (w, c)


def run_a():
    out = {}
    for side in (False, True):
        cache = {h: xv_rows([y for y in YEARS if y != h], side)[0] for h in YEARS}
        o, sq = H.score_rows(cache[YEARS[0]], 0.0, lambda h: cache[h])
        w, c = xv_rows(YEARS, side)[1]
        out['side' if side else 'margin'] = (o, sq, dict(zip(P7, np.round(w, 3).tolist())), {f'{g}.{k}': round(float(x), 3) for (g, k), x in zip(COLS, c) if x})
    (ob, sb, wb, cb), (oc, sc, wc, cc) = out['margin'], out['side']
    # side effects: next-season team predict of returning XV (weights fit without n, n+1) is not scored here (XV is descriptive)
    return dict(target='describe held out', base=ob['oos'], cand=oc['oos'], baseIns=ob['ins'], candIns=oc['ins'],
                bySeasonBase=ob['bySeason'], bySeasonCand=oc['bySeason'], weightsMargin=[wb, cb], weightsSide=[wc, cc], **H.paired(sb, sc))


# ---- (b) pXR form ----------------------------------------------------------------------------------------------------
E = {}
for y in YEARS:
    e = defaultdict(float)
    for pid, t, x in H.PARTS[(y, 7)]: e[pid] += x
    E[y] = e


def run_b():
    val = H.M['cwar']
    base, sqb = H.predict(val, 7, PAIRS)
    pxr = lambda n, p: CWAR_V[H.g_(p)] + SAV_W[H.g_(p)] * R[n][p]['z'] * E[n][p] / (E[n][p] + .2)
    cand, sqc = H.predict(val, 7, PAIRS, pval=pxr, pk=0)
    return dict(target='predict team (held out)', base=base['teamOOS'], cand=cand['teamOOS'], baseIns=base['team'], candIns=cand['team'],
                baseR=base['playerR'], candR=cand['playerR'], baseRwithin=base['playerRwithinPos'], candRwithin=cand['playerRwithinPos'], **H.paired(sqb, sqc))


# ---- (d) G5 level weighting --------------------------------------------------------------------------------------------
def run_d():
    val = H.M['cwar']; grid = [0, .25, .5, .75, 1]
    g5 = lambda n, p: 0.0 if CONF.get((n, p), True) else 1.0
    pv = lambda c: (lambda n, p: CWAR_V[H.g_(p)] + SAV_W[H.g_(p)] * (R[n][p]['z'] - c * g5(n, p)))
    rows = {c: {n: H.pred_rows(n, 7, pv(c), val)[0] for n in PAIRS} for c in grid}
    def best(train):
        sc = {c: sum(sum(v) for v in H.score_rows({n: rows[c][n] for n in train})[1].values()) for c in grid}
        return min(sc, key=sc.get)
    cs = {n: best([m for m in PAIRS if m != n]) for n in PAIRS}
    base, sqb = H.predict(val, 7, PAIRS)
    cand, sqc = H.predict(val, 7, PAIRS, pval_for=lambda n: pv(cs[n]))
    share = np.mean([g5(y, p) for y in YEARS for p in R[y] if (y, p) in CONF])
    return dict(target='predict team (held out)', base=base['teamOOS'], cand=cand['teamOOS'], c=cs, g5share=round(float(share), 3),
                baseR=base['playerR'], candR=cand['playerR'], baseRwithin=base['playerRwithinPos'], candRwithin=cand['playerRwithinPos'], **H.paired(sqb, sqc))


if __name__ == '__main__':
    print('z joined', len(Z), 'of', sum(1 for y in YEARS for p in R[y] if H.g_(p) in P7), flush=True)
    res = {}
    for k, f in (('a_xv_per_side', run_a), ('b_pxr_form', run_b), ('d_g5_weight', run_d)):
        res[k] = f(); print(k, {a: b for a, b in res[k].items() if not a.startswith('weights')}, flush=True)
    json.dump(res, open(os.path.join(HERE, 'cfb_port.json'), 'w'), indent=1, default=str)
