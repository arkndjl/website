#!/usr/bin/env python3
"""NFL props: three ways to bet a player with several rule props in one game (Noah, Oct 29 2026: "why not just choose
the most profitable pick as the one pick for each player, or list them all as a parlay?"). Held-out 2025-26 weeks:
  shared  - every prop, the player's stake split by 1/(1+(m-1)rho)  (live since PR #559)
  best    - only the player's highest-chance prop, full stake
  parlay  - the player's props as one Novig parlay (RFQ, priced by liquidity providers who see the correlation),
            legs that contain another (rush+rec yds with rush or rec yds) dropped as Novig blocks them
All at the house rule (full Kelly x TIMING .5, Novig -103 singles), weekly budget 100%. Research only.
Run from scripts/: python3 nfl_props_onebet_research.py"""
import sys, os, json, gzip, math, numpy as np
from collections import defaultdict
from statistics import NormalDist
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_props_research as R
RHO = .42                                   # same-player result correlation (nfl_props_corr_research.py)
LAT = math.sin(math.pi * RHO / 2)           # latent normal correlation giving binary corr .42 at p .5
DEC = 1 + 100 / 103; B = DEC - 1
CONTAINS = {('rwy', 'ry'), ('rwy', 'wy')}
rows = R.build_rows()
ix = {(int(s), int(w), i): k for k, (s, w, i) in enumerate(zip(rows['s'], rows['w'], rows['id']))}
g2 = {str(r[0]): (int(r[1]), int(r[2])) for r in rows['g2']}; a2 = {str(r[0]): r[1] for r in rows['a2']}
O = json.load(gzip.open(R.OPENS, 'rt'))
F = json.load(open(os.path.join(R.ROOT, 'data', 'nfl_props_fit.json'))); c = F['c']

def bets(ver):
    sh = R.shape(rows, ver); out = []
    for gid, g in O.items():
        sw = g2.get(gid)
        if not sw: continue
        for a, st, L in g['props']:
            if st not in R.STATS: continue
            k = ix.get((sw[0], sw[1], a2.get(a)))
            if k is None: continue
            y = sum(rows['y_' + q][k] for q in R.STATS[st]); mu = sum(rows[ver + '_' + q][k] for q in R.STATS[st])
            if y == L: continue
            p = R.p_over(sh, st, mu, L)
            if p is None or max(p, 1 - p) < F['pstar']: continue
            win = (y > L) if p >= .5 else (y < L)
            out.append(dict(s=sw[0], w=sw[1], g=gid, a=a, st=st, ch=.5 + c * (max(p, 1 - p) - .5), win=bool(win)))
    return out

def kel(ch, b=B):  # house rule: full Kelly x TIMING .5, % of bankroll
    e = ch * b - (1 - ch)
    return max(0., .5 * e / b * 100)

def pall(ps):  # chance every leg wins, legs equicorrelated through a normal copula
    if len(ps) == 1: return ps[0]
    z = _Z[:, :len(ps)] < np.array([NormalDist().inv_cdf(p) for p in ps])
    return float(z.all(1).mean())
_g = np.random.default_rng(7); _Z = math.sqrt(LAT) * _g.standard_normal((400000, 1)) + math.sqrt(1 - LAT) * _g.standard_normal((400000, 6))

def plan(bs, how, margin=0.):
    """[(stake %, return per unit if win)] per player-game unit, before the weekly budget."""
    byp = defaultdict(list)
    for b in bs: byp[(b['g'], b['a'])].append(b)
    out = []
    for legs in byp.values():
        m = len(legs)
        if how == 'perprop':
            out += [(kel(b['ch']), B, b['win']) for b in legs]
        elif how == 'shared':
            out += [(kel(b['ch']) / (1 + (m - 1) * RHO), B, b['win']) for b in legs]
        elif how == 'best':
            b = max(legs, key=lambda b: b['ch']); out.append((kel(b['ch']), B, b['win']))
        else:  # parlay: drop contained legs (keep the higher chance), price = fair joint at the market (.5 a leg net of
            legs = sorted(legs, key=lambda b: -b['ch']); keep = []   # the -103 hold) plus the LP margin
            for b in legs:
                if not any((b['st'], k['st']) in CONTAINS or (k['st'], b['st']) in CONTAINS for k in keep): keep.append(b)
            if len(keep) == 1:
                b = keep[0]; out.append((kel(b['ch']), B, b['win'])); continue
            q = pall([1 / DEC] * len(keep)) * (1 + margin)       # what the LP asks: joint chance at the market price
            ours = pall([.5 + .5 * (b['ch'] - .5) for b in keep])  # TIMING .5 on every leg's edge
            bb = 1 / q - 1; e = ours * bb - (1 - ours)
            out.append((max(0., e / bb * 100), bb, all(b['win'] for b in keep)))
    return out

def run(S, how, budget=100., margin=0.):
    byw = defaultdict(list)
    for b in S: byw[(b['s'], b['w'])].append(b)
    lg, ex, n, ret, stk = [], [], 0, 0., 0.
    for bs in byw.values():
        P = plan(bs, how, margin); tot = sum(x for x, _, _ in P)
        sc = min(1., budget / tot) if tot > 0 else 1.
        P = [(x * sc, bb, w) for x, bb, w in P if x > 0]
        r = sum(x / 100 * (bb if w else -1) for x, bb, w in P)
        lg.append(math.log(max(1e-9, 1 + r))); ex.append(sum(x for x, _, _ in P)); n += len(P)
        ret += sum(x * (bb if w else -1) for x, bb, w in P); stk += sum(x for x, _, _ in P)
    lg = np.array(lg)
    return {'bets': n, 'roi': round(ret / stk, 4), 'logWeek': round(float(lg.mean()), 4),
            't': round(float(lg.mean() / (lg.std(ddof=1) / math.sqrt(len(lg)))), 2),
            'growth': round(math.expm1(lg.sum()), 2), 'worstWeek': round(math.expm1(lg.min()), 3),
            'avgExposure': round(float(np.mean(ex)), 1), 'weeks': len(lg), '_lg': lg}

res = {'registered': '2026-10-29', 'rho': RHO, 'price': -103, 'budget': 100, 'versions': {}}
for ver in ('wed', 'full'):
    sel = bets(ver); res['versions'][ver] = {}
    for name, ss in (('tune', (2024,)), ('held', (2025, 2026))):
        S = [b for b in sel if b['s'] in ss]; m = defaultdict(int)
        for b in S: m[(b['g'], b['a'])] += 1
        d = {'props': len(S), 'players': len(m), 'multi': sum(v > 1 for v in m.values())}
        for how in ('perprop', 'shared', 'best'): d[how] = run(S, how)
        for mg in (0., .05, .10, .20): d['parlay%d' % round(mg * 100)] = run(S, 'parlay', margin=mg)
        base = d['shared'].pop('_lg')
        for k in d:
            if isinstance(d[k], dict) and '_lg' in d[k]:
                df = d[k].pop('_lg') - base   # same weeks, same order
                d[k]['vsShared'] = {'logWeek': round(float(df.mean()), 4),
                                    't': round(float(df.mean() / (df.std(ddof=1) / math.sqrt(len(df)))), 2)}
        res['versions'][ver][name] = d
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(R.ROOT, 'data', 'nfl_props_onebet_research.json'), 'w'), indent=1)
