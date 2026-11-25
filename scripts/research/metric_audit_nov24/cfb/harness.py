#!/usr/bin/env python3
"""CFB metric audit harness (prereg.md). Rows: node scripts/research/metric_audit_nov24/cfb/export.mjs (2019-25, no 2026).
    python3 scripts/research/metric_audit_nov24/cfb/harness.py   -> player.json (metric table + candidates)"""
import json, os, sys, math
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'team_adj_nov24'))
import core

STARTERS = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OL': 5, 'EDGE': 2, 'DL': 2, 'LB': 2, 'CB': 3, 'S': 2}
P7 = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB']; P10 = list(STARTERS)
J = json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'av', 'metric_audit_cfb.json')))
CWAR_V, SAV_W = J['CWAR_V'], J['SAV_W']
XV_W = {'QB': 2.1, 'RB': 0.49, 'WR': 0.52, 'TE': 0.34, 'OL': 0.2, 'EDGE': 0.73, 'DL': 0.08, 'LB': 0.32, 'CB': 0.29, 'S': 0.67}
XV_C = {'QB': {'cmp': 0.842, 'nypa': 0.24, 'intr': 0.164, 'rush': 0.298}, 'RB': {'ypc': 0.147, 'elu': 0.372}, 'WR': {'ypr': 0.051},
        'OL': {'prs': 0.116, 'rb': 0.214}, 'EDGE': {'sk': 0.104, 'spl': 0.274}, 'DL': {'spl': 0.695, 'sk': 0.041},
        'LB': {'cov': 0.754, 'prs': 0.337}, 'CB': {'cov': 0.354, 'ypt': 0.175}, 'S': {'ball': 0.12}}
YEARS = list(range(2019, 2026))
assert all(r['season'] <= 2025 for r in J['rows']), 'lockbox'


def num(v): return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
def per(a, b): return None if a is None or not b else a / b
def neg(x): return None if x is None else -x


def parts(g, r):
    f = lambda k: num(r.get(k)); gp = f('gp') or f('gamesQ'); sn = f('snaps') or f('snapsQ')
    if g == 'QB': return dict(cmp=f('cmpPct'), nypa=f('nypa'), intr=neg(per(f('int'), f('att'))), rush=per(f('ryds'), gp))
    if g == 'RB': return dict(ypc=f('ypc'), elu=f('elu'))
    if g in ('WR', 'TE'): return dict(catch=f('catch'), ypr=f('ypr'), epa=f('epaTar'), blk=f('blk'))
    if g == 'OL': return dict(prs=neg(f('prsRate')), rb=f('rbScore'), pb=f('pbScore'))
    if g in ('EDGE', 'DL'): return dict(prs=f('prsRate'), sk=per(f('sk'), sn), spl=per(f('splash'), sn))
    if g == 'LB': return dict(cov=neg(f('rtg')) if f('tgt') else None, prs=per(f('prs'), sn), tfl=per(f('tfl'), sn))
    if g in ('CB', 'S'): return dict(cov=neg(f('rtg')) if f('tar') else None, ypt=neg(per(f('yds'), f('tar'))), ball=per((f('int') or 0) + (f('pbu') or 0), f('tar')))
    return {}


# ---- rows: z, XV quality, sos z, history ------------------------------------------------------------------------------
R = defaultdict(dict)          # R[y][pid] = row (pid = id|pos)
for y in YEARS:
    nT = len(J['SRS'][str(y)])
    for g in P10:
        L = [r for r in J['rows'] if r['season'] == y and r['pos'] == g and r.get('z') is not None]
        if not L: continue
        pool = sorted(L, key=lambda r: -r['score'])[:STARTERS[g] * nT]
        def zof(fn):
            v = [fn(r) for r in pool]; v = [x for x in v if x is not None]
            if len(v) < 20: return lambda r: 0.0
            m, s = float(np.mean(v)), float(np.std(v)) or 1.0
            return lambda r: 0.0 if fn(r) is None else max(-3, min(3, (fn(r) - m) / s))
        pc = {id(r): parts(g, r['raw']) for r in L}
        zs = zof(lambda r: r['score'])
        zp = [(w, zof(lambda r, k=k: pc[id(r)].get(k))) for k, w in XV_C.get(g, {}).items()]
        sv = [num(r['raw'].get('sos')) for r in L]; sv = [x for x in sv if x is not None]
        sm, ss = (float(np.mean(sv)), float(np.std(sv)) or 1.0) if sv else (0, 1)
        for r in L:
            pid = r['id'] + '|' + g
            if pid in R[y] and R[y][pid]['sh'] >= r['sh']: continue
            s = num(r['raw'].get('sos'))
            R[y][pid] = dict(pid=pid, pos=g, tid=r['tid'], sh=r['sh'], score=r['score'], z=r['z'],
                             xq=XV_W[g] * zs(r) + sum(w * z(r) for w, z in zp), sos=0.0 if s is None else (s - sm) / ss)


def exposure(y, pos):
    """starter-slot fill (team_adj cfb.py): [(pid, tid, e)]"""
    by = defaultdict(list)
    for r in R[y].values():
        if r['pos'] in pos and r['sh'] > 0: by[(r['tid'], r['pos'])].append(r)
    out = []
    for (tid, g), rs in by.items():
        T = 0.0
        for r in sorted(rs, key=lambda r: -r['sh']):
            e = min(r['sh'], STARTERS[g] - T)
            if e <= 0: break
            T += e; out.append((r['pid'], tid, e))
    return out


SRS = {y: J['SRS'][str(y)] for y in YEARS}
PARTS = {(y, k): exposure(y, P7 if k == 7 else P10) for y in YEARS for k in (7, 10)}
POSK = {7: P7, 10: P10}
def g_(pid): return pid.split('|')[1]


# ---- metrics: value a full share --------------------------------------------------------------------------------------
M = {
    'pfn_raw': lambda y, p: R[y][p]['score'] - 50,
    'pfn_z': lambda y, p: R[y][p]['z'],
    'sav': lambda y, p: SAV_W[g_(p)] * (R[y][p]['z'] + 1) / .42,
    'cwar': lambda y, p: CWAR_V[g_(p)] + SAV_W[g_(p)] * R[y][p]['z'],
    'xv': lambda y, p: CWAR_V[g_(p)] + R[y][p]['xq'],
}
LABEL = {'pfn_raw': 'PFN impact score (public, score - 50)', 'pfn_z': 'Stat+ z (PFN score z, equal position weights)',
         'sav': 'Season AV (sav, q = PFN z)', 'cwar': 'cWAR (board war)', 'xv': 'XV (board xv)'}


def r2(x, y): return core.r2(list(x), list(y))


def feats(y, k, val, parts=None, fill=None, by_pos=False, extra=None):
    """team -> feature vector: sum value x exposure (one column, or one a position); extra(y, t) adds columns"""
    parts = parts or PARTS[(y, k)]; fill = fill or {}
    cols = POSK[k] if by_pos else ['all']
    X = defaultdict(lambda: np.zeros(len(cols)))
    for pid, t, e in parts:
        v = val(y, pid) if pid in R[y] else fill.get(pid)
        if v is None: v = fill.get(pid, 0.0)
        X[t][cols.index(g_(pid)) if by_pos else 0] += v * e
    out = {}
    for t in SRS[y]:
        if t not in X: continue
        x = X[t] if extra is None else np.concatenate([X[t], extra(y, t)])
        out[t] = x
    return out


def centre(F, yv):
    ts = [t for t in F if t in yv]
    Xm = np.mean([F[t] for t in ts], 0); ym = np.mean([yv[t] for t in ts])
    return [(F[t] - Xm, yv[t] - ym) for t in ts]


def fit(rows, lam):
    X = np.array([r[0] for r in rows]); Y = np.array([r[1] for r in rows])
    return np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ Y)


def score_rows(rows_by, lam=0.0, choose=None):
    """rows_by[s] = centred (xvec, y). In-sample pooled R2 (first column / fitted), OOS: weights on the other s.
    choose(train_s, held_s) -> rows_by-like dict to use (for grid-fit candidates)."""
    S = sorted(rows_by); sq = {}; se = ss = 0.0
    for h in S:
        rb = choose(h) if choose else rows_by
        tr = [r for s in S if s != h for r in rb[s]] or rb[h]
        w = fit(tr, lam)
        sq[h] = [float((yy - x @ w) ** 2) for x, yy in rb[h]]; se += sum(sq[h]); ss += sum(yy * yy for _, yy in rb[h])
    allr = [r for s in S for r in rows_by[s]]
    wa = fit(allr, lam); ins = r2([x @ wa for x, _ in allr], [yy for _, yy in allr])
    rng = np.random.default_rng(1); bi, bo = [], []
    tot = {h: (sum(sq[h]), sum(yy * yy for _, yy in rows_by[h])) for h in S}
    for _ in range(2000):
        pk = rng.choice(S, len(S)); rr = [r for s in pk for r in rows_by[s]]
        bi.append(r2([x @ wa for x, _ in rr], [yy for _, yy in rr])); bo.append(1 - sum(tot[s][0] for s in pk) / sum(tot[s][1] for s in pk))
    ci = lambda b: [round(float(np.percentile(b, 5)), 3), round(float(np.percentile(b, 95)), 3)]
    return dict(ins=round(ins, 4), insCI=ci(bi), oos=round(1 - se / ss, 4), oosCI=ci(bo), n=len(allr),
                bySeason={s: round(1 - tot[s][0] / tot[s][1], 3) for s in S}), sq


def describe(val, k, seasons, by_pos=False, lam=0.0, extra=None, choose=None):
    rows = {y: centre(feats(y, k, val, by_pos=by_pos, extra=extra), SRS[y]) for y in seasons}
    return score_rows(rows, lam, choose)


def pred_rows(n, k, pval, val, pk=.2, by_pos=False):
    """season n predictor x season n+1 exposure (newcomers: low-exposure group mean) -> n+1 SRS; player pairs"""
    expo = defaultdict(float)
    for pid, t, x in PARTS[(n, k)]: expo[pid] += x
    vn = {pid: pval(n, pid) * expo[pid] / (expo[pid] + pk) for pid in expo if pid in R[n]}
    gf, af = core.fillv(vn, expo, {p: g_(p) for p in vn}, .25)
    nx = PARTS[(n + 1, k)]
    fill = {pid: gf.get(g_(pid), af) for pid, t, x in nx if pid not in vn}
    F = feats(n + 1, k, lambda y, p: vn[p] if p in vn else None, parts=nx, fill=fill, by_pos=by_pos)
    rows = centre(F, SRS[n + 1])
    e1 = defaultdict(float)
    for pid, t, x in nx: e1[pid] += x
    pl = [(vn[pid], val(n + 1, pid), x, g_(pid)) for pid, x in e1.items() if x >= .4 and pid in vn and pid in R[n + 1]]
    return rows, pl


def predict(val, k, pairs, pval=None, pk=.2, by_pos=False, lam=0.0, pval_for=None):
    """pval_for(held pair) -> predictor fn fit without that pair (else pval or val)"""
    rows, pls = {}, []
    for n in pairs:
        pv = pval_for(n) if pval_for else (pval or val)
        rows[n], pl = pred_rows(n, k, pv, val, pk, by_pos); pls += pl
    o, sq = score_rows(rows, lam)
    px, py, pw, pg = zip(*pls)
    # position means removed (weighted)
    dx, dy = list(px), list(py)
    for g in set(pg):
        ix = [i for i in range(len(pg)) if pg[i] == g]; w = [pw[i] for i in ix]
        mx = np.average([px[i] for i in ix], weights=w); my = np.average([py[i] for i in ix], weights=w)
        for i in ix: dx[i] = px[i] - mx; dy[i] = py[i] - my
    o.update(team=o.pop('ins'), teamCI=o.pop('insCI'), teamOOS=o.pop('oos'), teamOOSCI=o.pop('oosCI'),
             playerR=round(core.wcorr(px, py, pw), 4), playerRwithinPos=round(core.wcorr(dx, dy, pw), 4), nPlayers=len(px))
    return o, sq


def paired(sqA, sqB):
    """B (candidate) minus A (base) squared error a team-season; t, one-sided p (B better = negative), seasons better"""
    d = [b - a for y in sqA for a, b in zip(sqA[y], sqB[y])]
    t = float(np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d))))
    better = sum(np.mean(sqB[y]) < np.mean(sqA[y]) for y in sqA)
    return dict(t=round(t, 2), p=round(0.5 * math.erfc(-t / math.sqrt(2)), 4), seasonsBetter=f'{better}/{len(sqA)}', n=len(d))


# ---- candidates (prereg.md) -------------------------------------------------------------------------------------------
def hist(pid, n, back=3):
    return [(i, R[n - i][pid]) for i in range(back) if n - i in R and pid in R[n - i]]


def marcel(K):
    W = (1, .7, .5)
    def f(n, pid):
        h = hist(pid, n); num = sum(W[i] * r['sh'] * r['z'] for i, r in h); den = sum(W[i] * r['sh'] for i, r in h)
        return num / (den + K)
    return f


def exp_of(pid, n): return min(2, sum(1 for y in R if y < n and pid in R[y]))


def exp_delta(train_pairs, k=7):
    a = defaultdict(list)
    for n in train_pairs:
        for pid, r in R[n].items():
            if r['pos'] in POSK[k] and pid in R[n + 1] and R[n + 1][pid]['sh'] >= .4: a[exp_of(pid, n)].append(R[n + 1][pid]['z'] - r['z'])
    return {e: float(np.mean(v)) for e, v in a.items()}


def cw(zf):
    return lambda n, pid: CWAR_V[g_(pid)] + SAV_W[g_(pid)] * zf(n, pid)


PAIRS = YEARS[:-1]


def run_candidates():
    C = {}
    val = M['cwar']
    base_p, sqP = predict(val, 7, PAIRS)
    base_d, sqD = describe(val, 7, YEARS)
    # P1 Marcel, K on the other pairs (by their OOS team error, using the in-pairs predict)
    def best_K(train):
        sc = {}
        for K in (.25, .5, 1, 2):
            rows = {n: pred_rows(n, 7, cw(marcel(K)), val, 0)[0] for n in train}
            o, sq = score_rows(rows); sc[K] = sum(sum(v) for v in sq.values())
        return min(sc, key=sc.get)
    Kp = {n: best_K([m for m in PAIRS if m != n]) for n in PAIRS}
    o, sq = predict(val, 7, PAIRS, pk=0, pval_for=lambda n: cw(marcel(Kp[n])))
    C['P1_marcel'] = dict(target='predict', base=base_p['teamOOS'], cand=o['teamOOS'], baseR=base_p['playerR'], candR=o['playerR'],
                          candRwithin=o['playerRwithinPos'], baseRwithin=base_p['playerRwithinPos'], K=Kp, **paired(sqP, sq))
    # P2 experience delta
    dl = {n: exp_delta([m for m in PAIRS if m != n]) for n in PAIRS}
    pz = lambda n0: (lambda n, pid: R[n][pid]['z'] + dl[n0].get(exp_of(pid, n), 0))
    o, sq = predict(val, 7, PAIRS, pval_for=lambda n: cw(pz(n)))
    C['P2_experience'] = dict(target='predict', base=base_p['teamOOS'], cand=o['teamOOS'], baseR=base_p['playerR'], candR=o['playerR'],
                              candRwithin=o['playerRwithinPos'], baseRwithin=base_p['playerRwithinPos'], delta=dl, **paired(sqP, sq))
    # P3 both (exp delta added to the Marcel mean)
    pm = lambda n0: (lambda n, pid: marcel(Kp[n0])(n, pid) + dl[n0].get(exp_of(pid, n), 0))
    o, sq = predict(val, 7, PAIRS, pk=0, pval_for=lambda n: cw(pm(n)))
    C['P3_marcel_exp'] = dict(target='predict', base=base_p['teamOOS'], cand=o['teamOOS'], baseR=base_p['playerR'], candR=o['playerR'],
                              candRwithin=o['playerRwithinPos'], baseRwithin=base_p['playerRwithinPos'], **paired(sqP, sq))
    # P4 predictor position weights refit (ridge lam 1 on per-position z sums), player r unchanged by construction (z)
    o, sq = predict(M['pfn_z'], 7, PAIRS, by_pos=True, lam=1.0)
    C['P4_posweights_pred'] = dict(target='predict', base=base_p['teamOOS'], cand=o['teamOOS'], **paired(sqP, sq))
    o2, sq2 = predict(M['pfn_z'], 7, PAIRS)
    C['posthoc_equal_weights_pred'] = dict(target='predict', base=base_p['teamOOS'], cand=o2['teamOOS'], note='post hoc, not in Holm', **paired(sqP, sq2))
    # D1 position weights refit for describe: per-position z sums + the cWAR line sum
    line = lambda y, t: np.array([sum(CWAR_V[g_(p)] * e for p, tt, e in PARTS[(y, 7)] if tt == t)])
    o, sq = describe(M['pfn_z'], 7, YEARS, by_pos=True, lam=1.0, extra=line)
    C['D1_posweights_desc'] = dict(target='describe', base=base_d['oos'], cand=o['oos'], bySeason=o['bySeason'], baseBy=base_d['bySeason'], **paired(sqD, sq))
    # D2 schedule: z + c x sos z, c on the other seasons (grid)
    def dz(c): return lambda y, p: CWAR_V[g_(p)] + SAV_W[g_(p)] * (R[y][p]['z'] + c * R[y][p]['sos'])
    grid = [-.5, -.25, -.1, 0, .1, .25, .5]
    rowsC = {c: {y: centre(feats(y, 7, dz(c)), SRS[y]) for y in YEARS} for c in grid}
    def chooseD2(h):
        sc = {c: score_rows({y: rowsC[c][y] for y in YEARS if y != h})[0]['oos'] for c in grid}
        cb = max(sc, key=sc.get); chooseD2.c[h] = cb; return rowsC[cb]
    chooseD2.c = {}
    o, sq = score_rows(rowsC[0], 0.0, chooseD2)
    C['D2_sos'] = dict(target='describe', base=base_d['oos'], cand=o['oos'], c=chooseD2.c, **paired(sqD, sq))
    # D3 XV in place of cWAR
    o, sq = describe(M['xv'], 7, YEARS)
    C['D3_xv'] = dict(target='describe', base=base_d['oos'], cand=o['oos'], bySeason=o['bySeason'], baseBy=base_d['bySeason'], **paired(sqD, sq))
    # D4 ungraded starter time at CWAR_V + SAV_W c
    def unf(y, t, c):
        e = defaultdict(float)
        for p, tt, x in PARTS[(y, 7)]:
            if tt == t: e[g_(p)] += x
        return sum((STARTERS[g] - e[g]) * (CWAR_V[g] + SAV_W[g] * c) for g in P7)
    gridc = [-2, -1.5, -1, -.5, 0]
    rows4 = {}
    for c in gridc:
        rows4[c] = {}
        for y in YEARS:
            F = feats(y, 7, val); F = {t: x + unf(y, t, c) for t, x in F.items()}; rows4[c][y] = centre(F, SRS[y])
    def chooseD4(h):
        sc = {c: score_rows({y: rows4[c][y] for y in YEARS if y != h})[0]['oos'] for c in gridc}
        cb = max(sc, key=sc.get); chooseD4.c[h] = cb; return rows4[cb]
    chooseD4.c = {}
    base4 = {y: centre(feats(y, 7, val), SRS[y]) for y in YEARS}
    o, sq = score_rows(base4, 0.0, chooseD4)
    C['D4_ungraded_line'] = dict(target='describe', base=base_d['oos'], cand=o['oos'], c=chooseD4.c, bySeason=o['bySeason'], **paired(sqD, sq))
    # Holm over the eight (one-sided p, candidate better = negative t)
    ks = [k for k in C if not k.startswith('posthoc')]
    order = sorted(ks, key=lambda k: C[k]['p'])
    for i, k in enumerate(order):
        C[k]['holmAlpha'] = round(.05 / (len(ks) - i), 4)
    stop = False
    for k in order:
        ok = (not stop) and C[k]['p'] <= C[k]['holmAlpha']
        if C[k]['target'] == 'predict' and 'candR' in C[k]: ok = ok and C[k]['candR'] >= C[k]['baseR'] - .01
        C[k]['pass'] = bool(ok); stop = stop or not ok
    return C


if __name__ == '__main__':
    out = {'labels': LABEL, 'metrics': {}}
    for key, val in M.items():
        o = {}
        o['describe7'] = describe(val, 7, YEARS)[0]
        o['describe7_2019_23'] = describe(val, 7, list(range(2019, 2024)))[0]
        o['describe10_2024_25'] = describe(val, 10, [2024, 2025])[0]
        o['predict7'] = predict(val, 7, PAIRS)[0]
        o['predict10_2024'] = predict(val, 10, [2024])[0]
        out['metrics'][key] = o
        d, p = o['describe7'], o['predict7']
        print(f"{key:8s} desc {d['ins']:.3f} oos {d['oos']:.3f} | pred team {p['team']:.3f} oos {p['teamOOS']:.3f} r {p['playerR']:.3f} rw {p['playerRwithinPos']:.3f}"
              f" | 10pos desc {o['describe10_2024_25']['ins']:.3f} pred {o['predict10_2024']['team']:.3f}", flush=True)
    out['candidates'] = run_candidates()
    for k, v in out['candidates'].items(): print(k, {a: b for a, b in v.items() if a not in ('K', 'delta', 'c', 'bySeason', 'baseBy')})
    json.dump(out, open(os.path.join(HERE, 'player.json'), 'w'), indent=1, default=str)
