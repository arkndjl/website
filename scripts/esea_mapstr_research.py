#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT pick/ban (Nov 20 2026): recency-weighted map strength vs the shipped lifetime map splits, and a
current-season opponent map pool vs the 90-day habit counts. Walk-forward on ESEA S53-S59 league maps.

    python3 scripts/esea_mapstr_research.py      # research/esea_matches.json.gz -> data/esea_mapstr_research.json (~5 min)

Target A, map win: every league map played (Bo1 + Bo3 maps), both sides priced by the page's live five rule.
  base     logit = b0 x RWA gap (shipped weekly walk-forward RWA, the page's match model)
  life     + the shipped map term: five-man mean lifetime FACEIT map deviation (later league maps taken back out), x 1.18
  team     + the team's map residual: decayed mean of (won - base p) on this map, shrunk by k maps, minus its all-map
           residual; current-season maps weigh S times older ones; half-life h days
  teamrd   the same on round share (round differential) residuals
  rwa      + the five's RWA by map: each player's decayed rounds-weighted RWA on this map shrunk by k rounds toward
           his all-map RWA, minus it; summed over the five (same h, S grid)
  Coefficients and (h, S, k) are fit on S54-S57; S58-S59 held; log loss of the played map, paired by match day.
Target B, decider (Bo1): the played map among the pool. Shipped = tree mix (HABIT_W .9 on 90-day counts, minimax on
  lifetime edges) + .85 softmax on 90-day shares (scripts/esea_veto_research.py E3). Candidate swaps the shares and
  habit counts for decayed, current-season-weighted ones, and the tree's edges for the winning map model.
Ship rule: a candidate must beat the shipped model on held log loss with t < -2 by day (map win), and not be worse
on the decider."""
import json
import math
import os
import sys
from collections import defaultdict, Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esea_standin_research as SR  # noqa: E402
import esea_rwa_research as R  # noqa: E402
from esea_veto_research import tree_poly  # noqa: E402

OUT = os.path.join(SR.ROOT, 'data', 'esea_mapstr_research.json')
FIT, HELD = (54, 57), (58, 59)
DAY = SR.DAY
MAP_K, MAP_COEF = 50, 1.18
HS = [30, 60, 120, 240, 100000]
SS = [1, 2, 4, 8]
KT = [2, 4, 8, 16, 32]          # team: maps
KR = [100, 200, 400, 800]       # rwa: rounds
lgt = lambda p: math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + np.exp(-x))


def fit_logit(X, y, lam=1e-4, it=40):
    X = np.asarray(X, float)
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = sig(np.clip(X @ b, -30, 30))
        g = X.T @ (p - y) + lam * b
        H = (X * (p * (1 - p))[:, None]).T @ X + lam * np.eye(len(b))
        d = np.linalg.solve(H, g)
        b -= d
        if np.abs(d).max() < 1e-8:
            break
    return b


def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


class Acc:
    """per (entity, map) decayed sums split into this season and earlier, half-life h days; query weights this season S"""
    def __init__(self, h):
        self.lam = math.log(2) / (h * DAY)
        self.d = {}   # key -> [t, season, cw, cx, pw, px]

    def _roll(self, v, t, season):
        f = math.exp(-self.lam * (t - v[0]))
        v[2] *= f
        v[3] *= f
        v[4] *= f
        v[5] *= f
        v[0] = t
        if season != v[1]:
            v[4] += v[2]
            v[5] += v[3]
            v[2] = v[3] = 0.0
            v[1] = season

    def add(self, key, t, season, w, x):
        v = self.d.get(key)
        if v is None:
            v = self.d[key] = [t, season, 0.0, 0.0, 0.0, 0.0]
        self._roll(v, t, season)
        v[2] += w
        v[3] += w * x

    def get(self, key, t, season):
        """-> (cw, cx, pw, px)"""
        v = self.d.get(key)
        if v is None:
            return (0.0, 0.0, 0.0, 0.0)
        v = list(v)
        self._roll(v, t, season)
        return tuple(v[2:])


def comb(q, S):
    return S * q[0] + q[2], S * q[1] + q[3]


def main():
    d, ms = SR.load()
    SR.predicted_fives(ms)
    PM = d['playerMaps']
    # ---- base: the shipped RWA gap (weekly walk-forward)
    M = R.Maps(ms)
    fitp = json.load(open(R.OUT))['params']
    tune_g = (M.gseason >= 53) & (M.gseason <= R.TUNE[1])
    c = R.ark_values(M, tune_g)
    cuts = R.weekly(ms)
    gap = R.rwa_gaps(ms, M, c, fitp, cuts, 'live')
    print('rwa gaps', len(gap), file=sys.stderr)
    # per (match index, map index) -> rows of M (player-map rwa contributions)
    gkey = []
    for mi, m in enumerate(ms):
        for xi, mp in enumerate(m['maps']):
            rr = mp['s1'] + mp['s2']
            if rr < 13:
                continue
            if any(R.line(p) is None for p in mp['p1'] + mp['p2']):
                continue
            gkey.append((mi, xi))
    assert len(gkey) == len(M.games)
    rows_of_g = defaultdict(list)
    for i, g in enumerate(M.g):
        rows_of_g[gkey[g]].append(i)
    inv = {i: q for q, i in M.pid.items()}

    # ---- lifetime dev (shipped), with later league maps taken back out (as esea_veto_research.py)
    fut = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for m in ms:
        for mp in m['maps']:
            for ps, won in ((mp['p1'], mp['s1'] > mp['s2']), (mp['p2'], mp['s2'] > mp['s1'])):
                for p in ps:
                    for k in (mp.get('map'), '*'):
                        fut[p[0]][k][0] += 1
                        fut[p[0]][k][1] += won

    def life_dev(q, mp):
        pm = PM.get(q)
        if not pm or not pm.get('life') or pm['life'][1] is None:
            return 0.0
        ln = pm['life'][0] - fut[q]['*'][0]
        lw = pm['life'][0] * pm['life'][1] / 100 - fut[q]['*'][1]
        x = pm['maps'].get(mp)
        if not x or x[1] is None or ln <= 0:
            return 0.0
        n = x[0] - fut[q][mp][0]
        w = x[0] * x[1] / 100 - fut[q][mp][1]
        lr = lw / ln
        if n <= 0 or not 0 < lr < 1:
            return 0.0
        r = min(0.99, max(0.01, w / n))
        return (lgt(r) - lgt(lr)) * n / (n + MAP_K)

    cnt = defaultdict(Counter)
    for m in ms:
        for mp in m['maps']:
            if mp.get('map'):
                cnt[m['season']][mp['map']] += 1
    pools = {s: sorted(k for k, v in c_.items() if v / sum(c_.values()) >= 0.02) for s, c_ in cnt.items()}

    # ---- walk forward
    TA = {h: Acc(h) for h in HS}     # team result residual: key (team, map) / (team, '*')
    TD = {h: Acc(h) for h in HS}     # team round-share residual
    PR = {h: Acc(h) for h in HS}     # player rwa: key (player, map) / (player, '*'); w = rounds, x = rwa
    SH = {h: Acc(h) for h in HS}     # team map share (counts): key (team, map) / (team, '*'); x = 1
    hist90 = defaultdict(list)
    RS_B = 0.0   # round share slope on the base logit, fit below on the fly (from the fit seasons' rows)
    maprows, dec_rows = [], []
    # round-share-from-logit slope: fit once from all S53 maps first (burn season, not scored)
    xs, ys = [], []
    for m in ms:
        if m['season'] != 53 or m['id'] not in gap:
            continue
        for mp in m['maps']:
            rr = mp['s1'] + mp['s2']
            if rr >= 13:
                xs.append(14.2 * gap[m['id']])
                ys.append(mp['s1'] / rr - 0.5)
    xs, ys = np.array(xs), np.array(ys)
    RS_B = float((xs * ys).sum() / (xs * xs).sum())
    print('round share slope', RS_B, file=sys.stderr)

    for mi, m in enumerate(ms):
        t, ssn = m['at'], m['season']
        g = gap.get(m['id'])
        pool = pools.get(ssn, [])
        five = m['pf']['live']
        if g is not None and m['pf_ok'] and ssn >= 54:
            for xi, mp in enumerate(m['maps']):
                mn = mp.get('map')
                rr = mp['s1'] + mp['s2']
                if mn not in pool or rr < 13:
                    continue
                r = {'id': f"{m['id']}:{xi}", 'mid': m['id'], 'season': ssn, 'day': int(t // DAY), 'y': 1.0 if mp['s1'] > mp['s2'] else 0.0,
                     'g': g, 'life': sum(w * life_dev(q, mn) for q, w in five[0]) - sum(w * life_dev(q, mn) for q, w in five[1]),
                     'team': {}, 'teamrd': {}, 'rwa': {}}
                for h in HS:
                    for S in SS:
                        tv, dv = [], []
                        for side in ('f1', 'f2'):
                            tid = m[side]['id']
                            a_m, a_s = comb(TA[h].get((tid, mn), t, ssn), S), comb(TA[h].get((tid, '*'), t, ssn), S)
                            d_m, d_s = comb(TD[h].get((tid, mn), t, ssn), S), comb(TD[h].get((tid, '*'), t, ssn), S)
                            tv.append((a_m, a_s))
                            dv.append((d_m, d_s))
                        for k in KT:
                            f = lambda am, as_: (am[1] / (am[0] + k)) - (as_[1] / (as_[0] + k))
                            r['team'][(h, S, k)] = f(*tv[0]) - f(*tv[1])
                            r['teamrd'][(h, S, k)] = f(*dv[0]) - f(*dv[1])
                        pv = []
                        for ws in five:
                            per = []
                            for q, w in ws:
                                pm_, ps_ = comb(PR[h].get((q, mn), t, ssn), S), comb(PR[h].get((q, '*'), t, ssn), S)
                                per.append((w, pm_, ps_))
                            pv.append(per)
                        for k in KR:
                            def five_v(per):
                                tot = 0.0
                                for w, pm_, ps_ in per:
                                    mu = ps_[1] / ps_[0] if ps_[0] > 0 else 0.0
                                    tot += w * ((pm_[1] + k * mu) / (pm_[0] + k) - mu)
                                return tot * 5 / 100
                            r['rwa'][(h, S, k)] = five_v(pv[0]) - five_v(pv[1])
                maprows.append(r)
        # decider rows (Bo1, one map)
        if m.get('bo') == 1 and len(m['maps']) == 1 and m['pf_ok'] and m['maps'][0].get('map') in pool and ssn >= 54 and g is not None:
            mn = m['maps'][0]['map']
            N90 = [Counter(mp for tt, mp in hist90[m[s]['id']] if t - tt <= 90 * DAY) for s in ('f1', 'f2')]
            dr = {'id': m['id'], 'season': ssn, 'day': int(t // DAY), 'y': mn, 'pool': pool, 'g': g,
                  'n90': N90, 'life': {x: sum(w * life_dev(q, x) for q, w in five[0]) - sum(w * life_dev(q, x) for q, w in five[1]) for x in pool},
                  'sh': {}, 'team': {}, 'rwa': {}}
            for h in HS:
                for S in SS:
                    sh = []
                    for s in ('f1', 'f2'):
                        tid = m[s]['id']
                        tot = comb(SH[h].get((tid, '*'), t, ssn), S)[1]
                        sh.append({x: (comb(SH[h].get((tid, x), t, ssn), S)[1] / tot if tot > 0 else 0.0) for x in pool})
                    dr['sh'][(h, S)] = sh
            dr['_m'] = m
            dec_rows.append(dr)
        # ---- update with this match's maps
        for xi, mp in enumerate(m['maps']):
            mn = mp.get('map')
            rr = mp['s1'] + mp['s2']
            if not mn:
                continue
            for s in ('f1', 'f2'):
                hist90[m[s]['id']].append((t, mn))
                for h in HS:
                    SH[h].add((m[s]['id'], mn), t, ssn, 1.0, 1.0)
                    SH[h].add((m[s]['id'], '*'), t, ssn, 1.0, 1.0)
            if g is None or rr < 13:
                continue
            p1 = 1 / (1 + math.exp(-14.2 * g))
            y1 = 1.0 if mp['s1'] > mp['s2'] else 0.0
            rs1 = mp['s1'] / rr - 0.5 - RS_B * 14.2 * g
            for s, sg in (('f1', 1), ('f2', -1)):
                tid = m[s]['id']
                res = (y1 - p1) * sg
                for h in HS:
                    for key in ((tid, mn), (tid, '*')):
                        TA[h].add(key, t, ssn, 1.0, res)
                        TD[h].add(key, t, ssn, 1.0, rs1 * sg)
            for i in rows_of_g.get((mi, xi), []):
                q, rw, cv = inv[M.p[i]], M.R[i], c[i]
                for h in HS:
                    PR[h].add((q, mn), t, ssn, rw, cv)
                    PR[h].add((q, '*'), t, ssn, rw, cv)
    print('map rows', len(maprows), 'decider rows', len(dec_rows), file=sys.stderr)

    # ---- target A: map win
    y = np.array([r['y'] for r in maprows])
    fitm = np.array([FIT[0] <= r['season'] <= FIT[1] for r in maprows])
    heldm = np.array([HELD[0] <= r['season'] <= HELD[1] for r in maprows])
    G = np.array([r['g'] for r in maprows])
    LF = np.array([r['life'] for r in maprows])
    days = {r['id']: r['day'] for r in maprows}

    def cols(feats):
        return np.column_stack([np.ones(len(maprows)), G] + feats)

    def score(X, tag=None):
        b = fit_logit(X[fitm], y[fitm])
        p = sig(X @ b)
        L = ll(p, y)
        return b, L

    out = {'asof': d.get('asof'), 'rows': {'fit': int(fitm.sum()), 'held': int(heldm.sum())}, 'round_share_slope': RS_B}
    # shipped: base fitted + life at fixed 1.18 (the page), and with its coefficient refit
    b0, L0 = score(cols([]))
    Xs = cols([]); bs = fit_logit(np.column_stack([Xs, MAP_COEF * LF])[fitm][:, :2], y[fitm]) if False else None
    p_ship = sig(Xs @ b0 + MAP_COEF * LF)
    L_ship = ll(p_ship, y)
    b1, L1 = score(cols([LF]))
    res = {'base': (b0, L0), 'ship': (None, L_ship), 'life_refit': (b1, L1)}
    best = {}
    for name in ('team', 'teamrd', 'rwa'):
        cand = []
        for key in maprows[0][name]:
            F = np.array([r[name][key] for r in maprows])
            b, L = score(cols([LF, F]))
            cand.append((float(L[fitm].mean()), key, b, L))
        cand.sort(key=lambda x: x[0])
        best[name] = cand[0]
        out[f'{name}_grid_top'] = [{'h': k[0], 'S': k[1], 'k': k[2], 'fit_ll': round(v, 5)} for v, k, _, _ in cand[:8]]
        res[name] = (cand[0][2], cand[0][3])
        print(name, out[f'{name}_grid_top'][:3], file=sys.stderr)
    # season-only and history-only references at the winning k (S = huge ~ season only; S = 1 = no season boost)
    feats = {n: np.array([r[n][best[n][1]] for r in maprows]) for n in ('team', 'teamrd', 'rwa')}
    b, L = score(cols([LF, feats['team'], feats['rwa']]))
    res['team+rwa'] = (b, L)
    b, L = score(cols([LF, feats['teamrd'], feats['rwa']]))
    res['teamrd+rwa'] = (b, L)
    b, L = score(cols([feats['rwa']]))
    res['rwa_nolife'] = (b, L)
    b, L = score(cols([feats['team']]))
    res['team_nolife'] = (b, L)
    ids = [r['id'] for r in maprows]

    def cmp(La, Lb, mask):
        a = {ids[i]: float(La[i]) for i in np.where(mask)[0]}
        bb = {ids[i]: float(Lb[i]) for i in np.where(mask)[0]}
        return SR.day_t(a, bb, days)
    out['map_win'] = {}
    for n, (b, L) in res.items():
        out['map_win'][n] = {'coef': None if b is None else [round(float(x), 4) for x in b], 'fit_ll': round(float(L[fitm].mean()), 5), 'held_ll': round(float(L[heldm].mean()), 5),
                             'vs_ship_held': cmp(L, L_ship, heldm), 'vs_ship_fit': cmp(L, L_ship, fitm)}
    for n in ('team', 'teamrd', 'rwa'):
        out['map_win'][n]['params'] = {'h': best[n][1][0], 'S': best[n][1][1], 'k': best[n][1][2]}
    # season weight curve for the rwa and team terms at their best h, k
    for n in ('team', 'rwa'):
        h, S, k = best[n][1]
        out[f'{n}_S_curve'] = {}
        for S2 in SS:
            F = np.array([r[n][(h, S2, k)] for r in maprows])
            b, L = score(cols([LF, F]))
            out[f'{n}_S_curve'][S2] = {'held_ll': round(float(L[heldm].mean()), 5), 'fit_ll': round(float(L[fitm].mean()), 5)}
        out[f'{n}_h_curve'] = {}
        for h2 in HS:
            F = np.array([r[n][(h2, S, k)] for r in maprows])
            b, L = score(cols([LF, F]))
            out[f'{n}_h_curve'][h2] = {'held_ll': round(float(L[heldm].mean()), 5), 'fit_ll': round(float(L[fitm].mean()), 5)}
    print(json.dumps(out['map_win'], indent=1), file=sys.stderr)

    # pick the map model: best held-safe = lowest fit ll among candidates (choice on fit only)
    choices = ['life_refit', 'team', 'teamrd', 'rwa', 'team+rwa', 'teamrd+rwa']
    pick = min(choices, key=lambda n: out['map_win'][n]['fit_ll'])
    out['map_pick'] = pick
    bpick = res[pick][0]

    # ---- target B: decider
    fitd = [r for r in dec_rows if FIT[0] <= r['season'] <= FIT[1]]
    heldd = [r for r in dec_rows if HELD[0] <= r['season'] <= HELD[1]]
    for r in dec_rows:
        # edges: shipped (life x 1.18) and the picked model, as map win p - match p (logit scale is what the tree needs: rank only)
        r['d_ship'] = {x: MAP_COEF * r['life'][x] for x in r['pool']}
    # picked model edge needs per-map features for each pool map: recompute from the map rows is not possible for
    # unplayed maps, so the decider test uses the shipped edges for the tree in both arms (the edge test is target A)

    def soft(r, a, b_, sh):
        z = {x: a * (sh[0][x] + sh[1][x]) + b_ * ((sh[0][x] == 0) + (sh[1][x] == 0)) for x in r['pool']}
        mx = max(z.values())
        tot = sum(math.exp(v - mx) for v in z.values())
        return {x: math.exp(v - mx) / tot for x, v in z.items()}

    def sh90(r):
        out_ = []
        for c_ in r['n90']:
            tot = sum(c_.values())
            out_.append({x: (c_.get(x, 0) / tot if tot else 0.0) for x in r['pool']})
        return out_

    def fit_soft(rs, shf):
        a, b_, step = 0.0, 0.0, 2.0
        f = lambda a, b_: -sum(math.log(soft(r, a, b_, shf(r))[r['y']]) for r in rs) / len(rs)
        best_ = f(a, b_)
        while step > 1e-3:
            moved = False
            for da, db in ((step, 0), (-step, 0), (0, step), (0, -step)):
                v = f(a + da, b_ + db)
                if v < best_ - 1e-9:
                    a, b_, best_, moved = a + da, b_ + db, v, True
            if not moved:
                step /= 2
        return a, b_, best_

    def tree_p(r, w, n1, n2, dd):
        cc = tree_poly(r['pool'], dd, n1, n2)[r['y']]
        return sum(ck * w ** k * (1 - w) ** (6 - k) for k, ck in enumerate(cc))

    def arm(shf, nf, label, L=0.85, w=0.9):
        a, b_, fl = fit_soft(fitd, shf)
        lo = {}
        for r in dec_rows:
            n1, n2 = nf(r)
            pt = tree_p(r, w, n1, n2, r['d_ship'])
            ps = soft(r, a, b_, shf(r))[r['y']]
            lo[r['id']] = -math.log(max(1e-12, (1 - L) * pt + L * ps))
        return {'a': a, 'b': b_, 'soft_fit_ll': fl}, lo
    dday = {r['id']: r['day'] for r in dec_rows}
    meta0, lo0 = arm(sh90, lambda r: (r['n90'][0], r['n90'][1]), 'ship')
    out['decider'] = {'ship': {**meta0, 'fit_ll': round(sum(lo0[r['id']] for r in fitd) / len(fitd), 5), 'held_ll': round(sum(lo0[r['id']] for r in heldd) / len(heldd), 5)}}
    cand = []
    for h in HS:
        for S in SS:
            shf = lambda r, h=h, S=S: r['sh'][(h, S)]
            a, b_, fl = fit_soft(fitd, shf)
            cand.append((fl, h, S, a, b_))
    cand.sort()
    out['decider_grid_top'] = [{'h': h, 'S': S, 'soft_fit_ll': round(fl, 5)} for fl, h, S, _, _ in cand[:8]]
    _, h, S, _, _ = cand[0]
    # habit counts in the tree: decayed season-weighted shares (rank is what matters)
    shf = lambda r: r['sh'][(h, S)]
    meta1, lo1 = arm(shf, lambda r: (r['sh'][(h, S)][0], r['sh'][(h, S)][1]), 'cand')
    out['decider']['cand'] = {**meta1, 'h': h, 'S': S, 'fit_ll': round(sum(lo1[r['id']] for r in fitd) / len(fitd), 5),
                              'held_ll': round(sum(lo1[r['id']] for r in heldd) / len(heldd), 5),
                              'vs_ship_held': SR.day_t({r['id']: lo1[r['id']] for r in heldd}, {r['id']: lo0[r['id']] for r in heldd}, dday),
                              'vs_ship_fit': SR.day_t({r['id']: lo1[r['id']] for r in fitd}, {r['id']: lo0[r['id']] for r in fitd}, dday)}
    print(json.dumps(out['decider'], indent=1), file=sys.stderr)
    json.dump(out, open(OUT, 'w'), indent=1, default=str)
    print('wrote', OUT, file=sys.stderr)


if __name__ == '__main__':
    main()
