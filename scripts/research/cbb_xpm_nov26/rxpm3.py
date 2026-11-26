#!/usr/bin/env python3
"""CBB rXPM round 2, amendment (prereg.md): D7/D8 team adjustment to raw / mixed net rating, player-scale guard G.
    python3 rxpm3.py -> rxpm3.json"""
import json, os
from collections import defaultdict
import numpy as np
import rxpm2 as X
A = X.A; YS = X.YS; HERE = X.HERE


def raw_net(P, sel=lambda r: True):
    pm, po = defaultdict(float), defaultdict(float); seen = set()
    for r in P:
        if not sel(r) or (r['d'], r['t']) in seen: continue
        seen.add((r['d'], r['t']))
        # mg is per 100 possessions; weight by possessions = e / share -> use 1 per game (games ~ equal pace within team)
        pm[r['t']] += r['mg']; po[r['t']] += 1
    v = {t: pm[t] / po[t] for t in pm}; m = np.mean(list(v.values()))
    return {t: x - m for t, x in v.items()}


def shift(y, val, target, parts=None):
    """GBPM + one shift a minute per team: 5 x minutes-weighted team mean = target[team]"""
    parts = parts or A.S[y]['parts']; num, den = defaultdict(float), defaultdict(float)
    for pid, t, e in parts:
        if pid in val: num[t] += val[pid] * e; den[t] += e
    sh = {t: target[t] / 5 - num[t] / den[t] for t in den if t in target and den[t]}
    acc = defaultdict(lambda: [0.0, 0.0])
    for pid, t, e in parts:
        if t in sh: acc[pid][0] += sh[t] * e; acc[pid][1] += e
    return {p: v + (acc[p][0] / acc[p][1] if acc[p][1] else 0.0) for p, v in val.items()}


def sd300(y, val):
    pl = A.S[y]['pl']; xs = [(val[p], v['e']) for p, v in pl.items() if p in val and v['e'] >= 300]
    x, w = np.array([a for a, _ in xs]), np.array([b for _, b in xs]); m = np.average(x, weights=w)
    return float(np.sqrt(np.average((x - m) ** 2, weights=w)))


def main():
    G = {y: X.load_games(y) for y in YS}
    gb = {y: A.vals(y, 'gbpm') for y in YS}
    RN = {y: raw_net(G[y][0]) for y in YS}
    EM = {y: {t: v - np.mean([q[0] / q[1] for q in A.S[y]['em'].values()]) for t, v in ((t, a / b) for t, (a, b) in A.S[y]['em'].items())} for y in YS}
    base = {y: X.t1_rows(y, gb[y]) for y in YS}; LG = X.slope_score(base, YS); sst = sum(LG[y][1] for y in YS)
    out = {'GBPM': round(1 - sum(LG[y][0] for y in YS) / sst, 4)}
    mix = lambda y, a: {t: a * RN[y][t] + (1 - a) * EM[y].get(t, 0.0) for t in RN[y]}
    GR = {a: {y: X.t1_rows(y, shift(y, gb[y], mix(y, a))) for y in YS} for a in (.25, .5, .75, 1.0)}
    cand = {'D7 team-adjusted to raw net': ({y: v[0] for y, v in X.slope_score(GR[1.0], YS).items()}, {})}
    cand['D8 team-adjusted to raw/adjEM mix'] = X.nested({a: GR[a] for a in (.25, .5, .75)}, YS, X.slope_score)
    T1 = {}
    for nm, (sse, ch) in cand.items():
        d = [LG[y][0] - sse[y] for y in YS]; t, p = A.paired_t(d)
        T1[nm] = {'heldOutWinR2': round(1 - sum(sse.values()) / sst, 4), 'seasonsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': p,
                  'chosen': {str(k): v for k, v in ch.items()}}
        print(nm, T1[nm], flush=True)
    out['T1'] = T1
    am = max(set(cand['D8 team-adjusted to raw/adjEM mix'][1].values()), key=list(cand['D8 team-adjusted to raw/adjEM mix'][1].values()).count)
    out['D8 alpha'] = am
    # guard G: player SD vs GBPM
    out['G'] = {'GBPM sd': round(float(np.mean([sd300(y, gb[y]) for y in YS])), 3),
                'D7 sd': round(float(np.mean([sd300(y, shift(y, gb[y], mix(y, 1.0))) for y in YS])), 3),
                'D8 sd': round(float(np.mean([sd300(y, shift(y, gb[y], mix(y, am))) for y in YS])), 3)}
    # D4 player SD (box correction weights from rxpm2.json)
    W = json.load(open(os.path.join(HERE, 'rxpm2.json')))['D4 weights (c/b per SD of box z)']
    w = np.array([W[k] for k in X.BOX]); sds = []
    for y in YS:
        Z = X.boxz(G[y][0]); v = {p: gb[y][p] + float(Z[p] @ w) for p in gb[y] if p in Z}; sds.append(sd300(y, v))
    out['G']['D4 sd'] = round(float(np.mean(sds)), 3)
    print('G', out['G'], flush=True)
    # T3 adjEM
    def em_rows(y, v): return A.drows(y, {p: v.get(p, gb[y][p]) for p in gb[y]}, 'em')
    L0 = X.slope_score({y: em_rows(y, gb[y]) for y in YS}, YS); s3 = sum(L0[y][1] for y in YS)
    T3 = {'GBPM': round(1 - sum(L0[y][0] for y in YS) / s3, 4)}
    for nm, a in (('D7', 1.0), ('D8', am)):
        L = X.slope_score({y: em_rows(y, shift(y, gb[y], mix(y, a))) for y in YS}, YS)
        T3[nm] = round(1 - sum(L[y][0] for y in YS) / s3, 4)
    out['T3 adjEM'] = T3; print('T3', T3, flush=True)
    # T2: odd games -> even games, shift from odd-game raw net (and adjEM mix) on odd-game GBPM
    odd = lambda r: r['odd']; T2 = {}
    for key in ('wp', 'mg'):
        def rows(y, val): return t2(G, y, val, key)
        B = {y: rows(y, X.values(G[y][0], sel=odd)) for y in YS}; LB = X.slope_score(B, YS); s2 = sum(LB[y][1] for y in YS)
        T2[key] = {'D1 odd GBPM': round(1 - sum(LB[y][0] for y in YS) / s2, 4)}
        for nm, a in (('D7', 1.0), ('D8', am)):
            R = {}
            for y in YS:
                P = G[y][0]; ro = raw_net(P, odd); tg = {t: a * ro[t] + (1 - a) * EM[y].get(t, 0.0) for t in ro}
                e = defaultdict(float)
                for r in P:
                    if r['odd']: e[(r['pid'], r['t'])] += r['e']
                parts = [(p, t, w) for (p, t), w in e.items()]
                R[y] = rows(y, shift(y, X.values(P, sel=odd), tg, parts))
            L = X.slope_score(R, YS); d = [LB[y][0] - L[y][0] for y in YS]
            T2[key][nm] = {'R2': round(1 - sum(L[y][0] for y in YS) / s2, 4), 't': A.paired_t(d), 'better': int(sum(x > 0 for x in d))}
        print('T2', key, T2[key], flush=True)
    out['T2'] = T2
    json.dump(out, open(os.path.join(HERE, 'rxpm3.json'), 'w'), indent=1, default=float)


def t2(G, y, val, key):
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


if __name__ == '__main__':
    main()
