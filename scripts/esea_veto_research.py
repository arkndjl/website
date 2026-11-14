#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT pick/ban tree: how much of a team's ban is HABIT and how much is EDGE? Scored on the map that was played.

    python3 scripts/esea_veto_research.py    # research/esea_matches.json.gz -> data/esea_veto_research.json (~1 min)

Rows: Bo1 league matches, the played map in the season pool (maps with 2%+ of the season's Bo1 maps), both sides
with 5+ players under the page's who-plays count. Fit S53-S57, held S58-S59, paired by match, summed by day.
  softmax  P(m) ~ exp(a (s1 + s2) + b (u1 + u2)); s = the team's share of its league maps in the prior 90 days
           on m, u = 1 when it has none (HABIT only)
  tree     the page tree's opponent applied to both teams: six alternating bans, each HABIT with chance w (ban
           the map with the fewest own maps) or EDGE (the minimax ban on the map edges); first ban unknown, both
           orders averaged
  mix      (1 - L) tree_w + L softmax; (w, L) by grid on the fit seasons. L = 1 is the softmax.
Map edges are the page's veto model walked forward: each side's predicted five, mean shrunk lifetime map deviation
(logit map wr - logit lifetime wr) x n / (n + 50). The lifetime splits are one snapshot, so every league map of the
player dated at or after the match is taken back out first (later pug maps cannot be).
Also applies Holm over the family (E1, E2 from data/esea_five_research.json, E3 here)."""
import json
import math
import os
import sys
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esea_standin_research as SR  # noqa: E402
from esea_five_research import pnorm, holm  # noqa: E402

OUT = os.path.join(SR.ROOT, 'data', 'esea_veto_research.json')
FIT, HELD = (53, 57), (58, 59)
MAP_K = 50
lgt = lambda p: math.log(p / (1 - p))


def tree_poly(pool, d, n1, n2):
    """-> {map: [c0..c6]}: P(decider = map) = sum_k c_k w^k (1-w)^(6-k), both ban orders averaged"""
    memo = {}

    def mm(left, t, first):      # value of d under minimax; f1 maximises
        if len(left) == 1:
            return d[left[0]]
        key = (left, t, first)
        if key in memo:
            return memo[key]
        f1 = (t % 2 == 0) == first
        vals = [mm(tuple(x for x in left if x != m), t + 1, first) for m in left]
        memo[key] = max(vals) if f1 else min(vals)
        return memo[key]
    out = {m: [0.0] * 7 for m in pool}
    for first in (True, False):
        def walk(left, t, k, wt):
            if len(left) == 1:
                out[left[0]][k] += wt
                return
            f1 = (t % 2 == 0) == first
            n, sg = (n1, 1) if f1 else (n2, -1)
            h = min(left, key=lambda m: (n.get(m, 0), sg * d[m], m))
            e = max(left, key=lambda m: (sg * mm(tuple(x for x in left if x != m), t + 1, first), -sg * d[m], m))
            walk(tuple(x for x in left if x != h), t + 1, k + 1, wt)
            walk(tuple(x for x in left if x != e), t + 1, k, wt)
        walk(tuple(sorted(pool)), 0, 0, 0.5)
    return out


def main():
    d, ms = SR.load()
    SR.predicted_fives(ms)
    PM = d['playerMaps']
    # league maps still ahead of each player: [n, wins] by map and in all
    fut = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for m in ms:
        for mp in m['maps']:
            for ps, won in ((mp['p1'], mp['s1'] > mp['s2']), (mp['p2'], mp['s2'] > mp['s1'])):
                for p in ps:
                    for k in (mp.get('map'), '*'):
                        fut[p[0]][k][0] += 1
                        fut[p[0]][k][1] += won
    bo1 = [m for m in ms if m.get('bo') == 1 and len(m['maps']) == 1 and m['maps'][0].get('map')]
    cnt = defaultdict(Counter)
    for m in bo1:
        cnt[m['season']][m['maps'][0]['map']] += 1
    pools = {s: sorted(k for k, v in c.items() if v / sum(c.values()) >= 0.02) for s, c in cnt.items()}

    def dev(q, mp):
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
    hist = defaultdict(list)   # team -> [(at, map)]
    rows = []
    for m in ms:
        t = m['at']
        if m in bo1 and False:
            pass
        if m.get('bo') == 1 and len(m['maps']) == 1 and m['pf_ok'] and m['maps'][0].get('map') in pools.get(m['season'], []):
            pool = pools[m['season']]
            N = []
            for side in ('f1', 'f2'):
                c = Counter(mp for tt, mp in hist[m[side]['id']] if t - tt <= 90 * SR.DAY)
                N.append(c)
            S = [{mp: (c.get(mp, 0) / sum(c.values()) if c else 0.0) for mp in pool} for c in N]
            U = [{mp: 0.0 if c.get(mp) else 1.0 for mp in pool} for c in N]
            dm = {mp: sum(w * dev(q, mp) for q, w in m['pf']['live'][0]) - sum(w * dev(q, mp) for q, w in m['pf']['live'][1]) for mp in pool}
            rows.append({'id': m['id'], 'season': m['season'], 'day': int(t // SR.DAY), 'y': m['maps'][0]['map'], 'pool': pool,
                         's': {mp: S[0][mp] + S[1][mp] for mp in pool}, 'u': {mp: U[0][mp] + U[1][mp] for mp in pool},
                         'poly': tree_poly(pool, dm, N[0], N[1]), 'd': dm})
        for mp in m['maps']:
            if mp.get('map'):
                hist[m['f1']['id']].append((t, mp['map']))
                hist[m['f2']['id']].append((t, mp['map']))
            for ps, won in ((mp['p1'], mp['s1'] > mp['s2']), (mp['p2'], mp['s2'] > mp['s1'])):
                for p in ps:
                    for k in (mp.get('map'), '*'):
                        fut[p[0]][k][0] -= 1
                        fut[p[0]][k][1] -= won
    fit = [r for r in rows if FIT[0] <= r['season'] <= FIT[1]]
    held = [r for r in rows if HELD[0] <= r['season'] <= HELD[1]]

    def soft(r, a, b):
        z = {mp: a * r['s'][mp] + b * r['u'][mp] for mp in r['pool']}
        mx = max(z.values())
        tot = sum(math.exp(v - mx) for v in z.values())
        return {mp: math.exp(v - mx) / tot for mp, v in z.items()}

    def nll_soft(rs, a, b):
        return -sum(math.log(soft(r, a, b)[r['y']]) for r in rs) / len(rs)
    # a, b by coordinate search (the surface is smooth and two-dimensional)
    a, b, step = 0.0, 0.0, 2.0
    best = nll_soft(fit, a, b)
    while step > 1e-3:
        moved = False
        for da, db in ((step, 0), (-step, 0), (0, step), (0, -step)):
            v = nll_soft(fit, a + da, b + db)
            if v < best - 1e-9:
                a, b, best, moved = a + da, b + db, v, True
        if not moved:
            step /= 2
    for r in rows:
        r['soft'] = soft(r, a, b)[r['y']]

    def tree_p(r, w):
        c = r['poly'][r['y']]
        return sum(ck * w ** k * (1 - w) ** (6 - k) for k, ck in enumerate(c))

    def nll(rs, w, L):
        return -sum(math.log(max(1e-12, (1 - L) * tree_p(r, w) + L * r['soft'])) for r in rs) / len(rs)
    grid = sorted(((nll(fit, w / 20, L / 20), w / 20, L / 20) for w in range(21) for L in range(1, 21)))
    _, w, L = grid[0]
    loss = lambda rs, f: {r['id']: -math.log(max(1e-12, f(r))) for r in rs}
    day = {r['id']: r['day'] for r in rows}
    cand = lambda r: (1 - L) * tree_p(r, w) + L * r['soft']
    base = lambda r: r['soft']
    th, tf = SR.day_t(loss(held, cand), loss(held, base), day), SR.day_t(loss(fit, cand), loss(fit, base), day)
    uni = sum(math.log(len(r['pool'])) for r in held) / len(held)
    res = {'asof': d.get('asof'), 'rows': {'fit': len(fit), 'held': len(held)}, 'pools': {str(k): v for k, v in sorted(pools.items())},
           'softmax': {'a': round(a, 3), 'b': round(b, 3), 'fit_ll': round(best, 4), 'held_ll': round(nll_soft(held, a, b), 4), 'uniform_held_ll': round(uni, 4)},
           'grid_top': [{'w': gw, 'L': gl, 'fit_ll': round(v, 4)} for v, gw, gl in grid[:6]],
           'fitted': {'w_habit': w, 'L_softmax': L},
           'tree_alone_fit_ll': {str(x / 4): round(nll(fit, x / 4, 0.05), 4) for x in range(5)},
           'minimax_decider_hit': {'held': round(sum(tree_p(r, 0.0) for r in held) / len(held), 4), 'habit_line': round(sum(tree_p(r, 1.0) for r in held) / len(held), 4),
                                   'softmax_mean_p': round(sum(r['soft'] for r in held) / len(held), 4)},
           'E3': {'held': th, 'fit': tf, 'p': round(pnorm(th['t']), 5)}}
    ps = {'E3': res['E3']['p']}
    try:
        f = json.load(open(os.path.join(SR.ROOT, 'data', 'esea_five_research.json')))
        ps.update({'E1': f['E1']['p'], 'E2': f['E2']['p']})
    except Exception:
        pass
    hp = holm(ps)
    sign = {'E3': th['diff'] < 0 and tf['diff'] < 0}
    if 'E1' in ps:
        sign.update({k: f[k]['held']['diff'] < 0 and f[k]['tune']['t'] < 0 for k in ('E1', 'E2')})
    res['holm'] = {k: {'p': ps[k], 'holm_p': round(hp[k], 5), 'pass': bool(hp[k] < 0.05 and sign[k])} for k in sorted(ps)}
    json.dump(res, open(OUT, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
