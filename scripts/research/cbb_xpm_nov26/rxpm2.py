#!/usr/bin/env python3
"""CBB rXPM round 2 (prereg.md, "rXPM round 2"): descriptive candidates from Barttorvik player game logs against GBPM.
Data: scripts/.cache/cbb/games_bt/{y}.json.gz (2013-2026), scripts/.cache/team_adj adv/tr files. No 2026-27.
    python3 rxpm2.py -> rxpm2.json"""
import gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb'))
import audit as A
import core
GB = os.path.join(ROOT, 'scripts', '.cache', 'cbb', 'games_bt')
YS = list(range(2013, 2027))
BOX = ['stl', 'blk', 'orb', 'drb', 'ast', 'to', 'ftr', 'tpa100', 'rims', 'usg', 'ts', 'ht']
KB = 350.0      # box reliability e/(e+KB), possessions (about 200 minutes)
f = lambda x: float(x) if x not in (None, '') else 0.0


def tr_em(y):
    tr = json.load(open(os.path.join(A.C, f'tr{y}.json'))); out = {}
    for r in tr:
        try: out[r[1]] = float(r[4]) - float(r[6])
        except (TypeError, ValueError): pass
    m = np.mean(list(out.values())); return {k: v - m for k, v in out.items()}


def load_games(y):
    rows = json.load(gzip.open(os.path.join(GB, f'{y}.json.gz'), 'rt'))
    pts = defaultdict(float); poss = {}
    for g in rows:
        k = (g[0], g[47]); pts[k] += f(g[33]); poss[k] = f(g[43])
    dates = defaultdict(set)
    for (d, t) in pts: dates[t].add(d)
    par = {}
    for t, ds in dates.items():
        for i, d in enumerate(sorted(ds)): par[(d, t)] = i % 2
    em = tr_em(y); P = []
    for g in rows:
        t, o, d = g[47], g[5], g[0]
        if (d, o) not in pts or not poss.get((d, t)): continue
        e = f(g[8]) / 100 * f(g[43])
        if e <= 0 or g[44] is None: continue
        mg = (pts[(d, t)] - pts[(d, o)]) / poss[(d, t)] * 100
        P.append({'pid': str(g[51]), 't': t, 'd': d, 'odd': par[(d, t)] == 0, 'e': e, 'gb': f(g[44]), 'mg': mg,
                  'opp': em.get(o, min(em.values())), 'stl': f(g[38]), 'blk': f(g[39]), 'orb': f(g[34]), 'drb': f(g[35]),
                  'ast': f(g[36]), 'to': f(g[37]), 'fta': f(g[28]), 'fga': f(g[24]) + f(g[26]), 'tpa': f(g[26]),
                  'rima': f(g[20]), 'pts': f(g[33]), 'ht': f(g[49])})
    TG = {}
    for (d, t), p in pts.items():
        if (d, t) not in poss: continue
        TG[(d, t)] = None
    # team-game results (for T2): one row per team-game with both sides logged
    res = defaultdict(list)
    seen = {(r['d'], r['t']): r for r in P}
    for (d, t), r in seen.items():
        res[t].append((r['odd'], r['mg'], 1.0 if r['mg'] > 0 else 0.0))
    return P, res


def values(P, wfn=lambda r: 1.0, adj=lambda r: 0.0, sel=lambda r: True):
    num = defaultdict(float); den = defaultdict(float)
    for r in P:
        if not sel(r): continue
        w = r['e'] * wfn(r); num[r['pid']] += w * (r['gb'] + adj(r)); den[r['pid']] += w
    return {p: num[p] / den[p] for p in num if den[p] > 0}


def boxz(P, sel=lambda r: True, thr=2 * KB):
    a = defaultdict(lambda: defaultdict(float)); ht = {}
    for r in P:
        if not sel(r): continue
        q = a[r['pid']]
        for k in ('e', 'stl', 'blk', 'orb', 'drb', 'ast', 'to', 'fta', 'fga', 'tpa', 'rima', 'pts'): q[k] += r[k]
        if 66 <= r['ht'] <= 90: ht[r['pid']] = r['ht']
    rt = {}
    for p, q in a.items():
        e = q['e']
        if e <= 0: continue
        fg, sh = q['fga'], q['fga'] + .44 * q['fta']
        rt[p] = {'e': e, 'stl': q['stl'] / e, 'blk': q['blk'] / e, 'orb': q['orb'] / e, 'drb': q['drb'] / e, 'ast': q['ast'] / e,
                 'to': q['to'] / e, 'ftr': q['fta'] / fg if fg else None, 'tpa100': q['tpa'] / e * 100,
                 'rims': q['rima'] / fg if fg else None, 'usg': (sh + q['to']) / e, 'ts': q['pts'] / (2 * sh) if sh else None,
                 'ht': ht.get(p)}
    big = [v for v in rt.values() if v['e'] >= thr]; Z = {}
    for k in BOX:
        xs = np.array([v[k] for v in big if v[k] is not None]); ws = np.array([v['e'] for v in big if v[k] is not None])
        m = float(np.average(xs, weights=ws)); s = float(math.sqrt(np.average((xs - m) ** 2, weights=ws))) or 1.0
        for p, v in rt.items():
            z = 0.0 if v[k] is None else max(-3.0, min(3.0, (v[k] - m) / s))
            Z.setdefault(p, []).append(z * v['e'] / (v['e'] + KB))
    return {p: np.array(z) for p, z in Z.items()}


# ------------------------------------------------------------------ T1: team win% on the audit harness
def t1_rows(y, val):
    fb = A.vals(y, 'gbpm'); v = {p: val.get(p, fb[p]) for p in fb}
    return A.drows(y, v, 'wp')


def t1_mrows(y, cols, res='wp'):
    """multi-column team rows: cols = list of pid->value dicts; centred x per column, centred win%"""
    fb = A.vals(y, 'gbpm'); X = []
    for j, c in enumerate(cols):
        v = {p: c.get(p, fb[p] if j == 0 else 0.0) for p in fb}
        X.append({t: (x, yy) for t, x, yy, _ in core.centred(A.D(y, v, res), y, v)})
    ts = sorted(set.intersection(*[set(x) for x in X]))
    return np.array([[X[j][t][0] for j in range(len(X))] for t in ts]), np.array([X[0][t][1] for t in ts])


def loso_multi(XY, ys, pen):
    """held-out SSE per season of a no-intercept ridge on the other seasons (pen = diagonal penalty vector)"""
    out = {}
    for y in ys:
        X = np.vstack([XY[s][0] for s in ys if s != y]); Y = np.concatenate([XY[s][1] for s in ys if s != y])
        b = np.linalg.solve(X.T @ X + np.diag(pen), X.T @ Y)
        out[y] = (float(((XY[y][1] - XY[y][0] @ b) ** 2).sum()), float((XY[y][1] ** 2).sum()), b)
    return out


def nested(G, ys, score):
    """G: grid value -> per-season rows; score(rows_by_season, seasons) -> loso dict; inner LOSO choice per held-out season"""
    sse, ch = {}, {}
    for y in ys:
        oth = [s for s in ys if s != y]
        def inner(g):
            L = score(G[g], oth); return sum(a[0] for a in L.values()) / sum(a[1] for a in L.values())
        g = min(G, key=inner) if len(G) > 1 else next(iter(G)); ch[y] = g
        sse[y] = score(G[g], ys)[y][0]
    return sse, ch


def slope_score(R, ys):
    return {y: v for y, v in A.loso_sse({s: R[s] for s in ys}, ys).items()}


def box_score_fn(lam):
    return lambda XY, ys: loso_multi(XY, ys, np.array([0.0] + [lam] * len(BOX)))


def main():
    G = {y: load_games(y) for y in YS}
    print('loaded', flush=True)
    out = {'seasons': YS}
    base = {y: t1_rows(y, A.vals(y, 'gbpm')) for y in YS}
    LG = slope_score(base, YS); sst = sum(LG[y][1] for y in YS)
    LBp = slope_score({y: t1_rows(y, A.vals(y, 'bpm')) for y in YS}, YS)
    r2 = lambda sse: round(1 - sum(sse.values()) / sst, 4)
    out['GBPM'] = r2({y: LG[y][0] for y in YS}); out['BPM'] = r2({y: LBp[y][0] for y in YS})
    print('GBPM', out['GBPM'], 'BPM', out['BPM'], flush=True)
    cand = {}

    def blow(m): return (lambda r: 1.0) if m is None else (lambda r: 1.0 / (1 + (abs(r['mg']) / m) ** 2))
    def oppadj(k): return lambda r: k * r['opp']
    V1 = {y: values(G[y][0]) for y in YS}
    R1 = {y: t1_rows(y, V1[y]) for y in YS}; L1 = slope_score(R1, YS)
    cand['D1 pgBPM'] = ({y: L1[y][0] for y in YS}, {})
    MS = [10, 20, 40]
    GD2 = {m: {y: t1_rows(y, values(G[y][0], blow(m))) for y in YS} for m in MS}
    cand['D2 blowouts down-weighted'] = nested(GD2, YS, slope_score)
    KS = [0, .1, .2, .3, .5]
    GD3 = {k: {y: t1_rows(y, values(G[y][0], adj=oppadj(k))) for y in YS} for k in KS}
    cand['D3 opponent-adjusted'] = nested(GD3, YS, slope_score)
    print('D1-3 done', flush=True)
    Z = {y: boxz(G[y][0]) for y in YS}
    def box_rows(y, gv, res='wp'):
        cols = [gv] + [{p: z[j] for p, z in Z[y].items()} for j in range(len(BOX))]
        return t1_mrows(y, cols, res)
    gb = {y: A.vals(y, 'gbpm') for y in YS}
    XY4 = {y: box_rows(y, gb[y]) for y in YS}
    LAMS = [1, 10, 100]
    sse4, ch4 = {}, {}
    for y in YS:
        oth = [s for s in YS if s != y]
        def inner(l):
            L = box_score_fn(l)({s: XY4[s] for s in oth}, oth); return sum(a[0] for a in L.values()) / sum(a[1] for a in L.values())
        l = min(LAMS, key=inner); ch4[y] = l; sse4[y] = box_score_fn(l)(XY4, YS)[y][0]
    cand['D4 GBPM + box correction'] = (sse4, ch4)
    lm = max(set(ch4.values()), key=list(ch4.values()).count); full4 = box_score_fn(lm)(XY4, YS)
    bfull = np.mean([full4[y][2] for y in YS], axis=0)
    out['D4 weights (c/b per SD of box z)'] = {k: round(float(bfull[j + 1] / bfull[0]), 3) for j, k in enumerate(BOX)}
    # D5: blend of season metrics
    XY5 = {y: t1_mrows(y, [A.vals(y, 'gbpm'), A.vals(y, 'bpm'), A.vals(y, 'tprpg')]) for y in YS}
    L5 = loso_multi(XY5, YS, np.zeros(3)); cand['D5 GBPM/BPM/PRPG blend'] = ({y: L5[y][0] for y in YS}, {})
    out['D5 weights'] = [round(float(x), 4) for x in np.mean([L5[y][2] for y in YS], axis=0)]
    # D6: best of D2 / D3 grids (modal) + box correction
    m2 = max(set(cand['D2 blowouts down-weighted'][1].values()), key=list(cand['D2 blowouts down-weighted'][1].values()).count)
    k3 = max(set(cand['D3 opponent-adjusted'][1].values()), key=list(cand['D3 opponent-adjusted'][1].values()).count)
    V6 = {y: values(G[y][0], blow(m2), oppadj(k3)) for y in YS}
    XY6 = {y: box_rows(y, V6[y]) for y in YS}
    sse6, ch6 = {}, {}
    for y in YS:
        oth = [s for s in YS if s != y]
        def inner(l):
            L = box_score_fn(l)({s: XY6[s] for s in oth}, oth); return sum(a[0] for a in L.values()) / sum(a[1] for a in L.values())
        l = min(LAMS, key=inner); ch6[y] = l; sse6[y] = box_score_fn(l)(XY6, YS)[y][0]
    cand['D6 D2/D3 + box'] = (sse6, ch6)
    # T3: adjEM describe (Barttorvik's opponent-adjusted margin), same ridge forms
    T3 = {}
    XE0 = {y: t1_mrows(y, [gb[y]], 'em') for y in YS}; L0 = loso_multi(XE0, YS, np.zeros(1)); s3 = sum(L0[y][1] for y in YS)
    T3['GBPM'] = round(1 - sum(L0[y][0] for y in YS) / s3, 4)
    XE4 = {y: box_rows(y, gb[y], 'em') for y in YS}; L4 = box_score_fn(lm)(XE4, YS)
    T3['D4'] = round(1 - sum(L4[y][0] for y in YS) / s3, 4); T3['D4 t'] = A.paired_t([L0[y][0] - L4[y][0] for y in YS])
    b4e = np.mean([L4[y][2] for y in YS], axis=0)
    T3['D4 adjEM-fit weights'] = {k: round(float(b4e[j + 1] / b4e[0]), 3) for j, k in enumerate(BOX)}
    XE5 = {y: t1_mrows(y, [A.vals(y, 'gbpm'), A.vals(y, 'bpm'), A.vals(y, 'tprpg')], 'em') for y in YS}; L5e = loso_multi(XE5, YS, np.zeros(3))
    T3['D5'] = round(1 - sum(L5e[y][0] for y in YS) / s3, 4)
    XEB = {y: t1_mrows(y, [A.vals(y, 'bpm')], 'em') for y in YS}; LBe = loso_multi(XEB, YS, np.zeros(1))
    T3['BPM'] = round(1 - sum(LBe[y][0] for y in YS) / s3, 4)
    out['T3 adjEM'] = T3; print('T3', T3, flush=True)
    out['choices'] = {'D2 m': m2, 'D3 k': k3, 'D4 lambda': lm}

    T1 = {}
    for nm, (sse, ch) in cand.items():
        d = [LG[y][0] - sse[y] for y in YS]; t, p = A.paired_t(d)
        T1[nm] = {'heldOutWinR2': r2(sse), 'vsGBPM': out['GBPM'], 'seasonsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': p,
                  'chosen': {str(k): v for k, v in ch.items()}}
        print(nm, T1[nm]['heldOutWinR2'], t, T1[nm]['seasonsBetter'], flush=True)
    ps = sorted(T1, key=lambda k: T1[k]['p'])
    for i, k in enumerate(ps):
        T1[k]['holmPass'] = bool(all(T1[q]['p'] <= .05 / (len(ps) - j) for j, q in enumerate(ps[:i + 1])) and T1[k]['t'] > 0
                                 and T1[k]['seasonsBetter'] >= 9)
    out['T1'] = T1

    # ---- T2: odd games -> even games
    def t2_rows(y, val, key):
        P, res = G[y]; e = defaultdict(float); gm = defaultdict(set)
        for r in P:
            if r['odd']: e[(r['pid'], r['t'])] += r['e']; gm[r['t']].add(r['d'])
        x = defaultdict(float)
        for (p, t), w in e.items():
            if p in val: x[t] += val[p] * w
        rows = []
        for t, rr in res.items():
            ev = [q for q in rr if not q[0]]
            if not ev or t not in x or not gm[t]: continue
            rows.append((x[t] / len(gm[t]), np.mean([q[1 if key == 'mg' else 2] for q in ev])))
        mx, my = np.mean([a for a, _ in rows]), np.mean([b for _, b in rows])
        return [(a - mx, b - my) for a, b in rows]
    odd = lambda r: r['odd']
    T2 = {}
    for key in ('wp', 'mg'):
        B = {y: t2_rows(y, values(G[y][0], sel=odd), key) for y in YS}; LB = slope_score(B, YS); s2 = sum(LB[y][1] for y in YS)
        res2 = {'D1 (odd-game GBPM)': {y: LB[y][0] for y in YS}}
        res2['D2'] = {y: v[0] for y, v in slope_score({y: t2_rows(y, values(G[y][0], blow(m2), sel=odd), key) for y in YS}, YS).items()}
        res2['D3'] = {y: v[0] for y, v in slope_score({y: t2_rows(y, values(G[y][0], adj=oppadj(k3), sel=odd), key) for y in YS}, YS).items()}
        Zo = {y: boxz(G[y][0], sel=odd, thr=KB) for y in YS}
        for nm, vf in (('D4', lambda y: values(G[y][0], sel=odd)), ('D6', lambda y: values(G[y][0], blow(m2), oppadj(k3), sel=odd))):
            XY = {}
            for y in YS:
                base_v = vf(y); cols = [base_v] + [{p: z[j] for p, z in Zo[y].items()} for j in range(len(BOX))]
                rs = [t2_rows(y, c, key) for c in cols]
                XY[y] = (np.array([[r[i][0] for r in rs] for i in range(len(rs[0]))]), np.array([b for _, b in rs[0]]))
            Lq = box_score_fn(lm)(XY, YS); res2[nm] = {y: Lq[y][0] for y in YS}
        T2[key] = {}
        for nm, sse in res2.items():
            d = [LB[y][0] - sse[y] for y in YS]; t, p = A.paired_t(d)
            T2[key][nm] = {'R2': round(1 - sum(sse.values()) / s2, 4), 't_vsD1': t, 'better': int(sum(x > 0 for x in d))}
        print('T2', key, {k: (v['R2'], v['t_vsD1']) for k, v in T2[key].items()}, flush=True)
    out['T2'] = T2
    json.dump(out, open(os.path.join(HERE, 'rxpm2.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
