#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer league sims: plain Poisson goals vs a low-score correction (math audit Nov 2 2026, OPEN item "soccer sims plain
Poisson"). Research script; results in data/soccer_sim_dc_research.json.

The game model prices win/draw/loss with Dixon-Coles (rho -.04, soccer_games.P0), but sim_matches draws independent
Poisson goals. Variants, each drawn on the same random numbers as the Poisson base (common seeds per checkpoint):
    dc<rho>   Dixon-Coles: 0-0, 1-0, 0-1, 1-1 reweighted by tau (rejection sampling on the Poisson draws, exact)
    bp<l3>    bivariate Poisson: home = X1 + X3, away = X2 + X3, X3 ~ Poisson(l3), means kept at lh / la
Same harness as scripts/soccer_sim_backtest.py (cached checkpoints at matchdays 0/9/19/28, scored seasons 2017-19 and
2022-26), with each season's knobs set to the walk-forward choice in data/soccer_sim_backtest.json. Scored on the gate
(title + top four + relegation Brier), each part, log losses and points MAE; paired t clustered by season.
    dc-.04   the game model's own rho: no new parameter, so the whole 2017-26 span is out of sample for it.
    wf       rho / l3 picked walk-forward (lowest gate on seasons before each scored one, 2013-16 train first).
Pass: gate t <= -1.5 and more seasons won than lost, title and position Brier not worse.

Result (Nov 2 2026, 4,000 sims, 240 checkpoints): FAIL, sims stay plain Poisson. Draw rate: actual .250, Poisson .244,
dc-.04 .253, bp.1 .255. dc-.04 (walk-forward picks it every season): gate .12836 -> .12828 (t -2.11, 6/8), top four t
-2.02, relegation t -1.70, but title Brier .01694 -> .01697 (t +1.40, 2/8 won) and title log loss t +1.25, points MAE
t +0.28. Larger rho: gate t -0.96 / +0.86 / -0.19. Bivariate Poisson (wf picks bp.15): gate t -0.30, title t -0.12,
points MAE 5.410 -> 5.396 (t -1.01); bp.05 gate t +4.0.

    python3 scripts/soccer_sim_dc_research.py       # needs scripts/.cache/soccer_sim_snaps.pkl (soccer_sim_backtest.py)
"""
import json
import math
import multiprocessing as mp
import os
import pickle
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H                                     # noqa: E402
import soccer_sim_backtest as B                         # noqa: E402

G, D = B.G, B.D
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_sim_dc_research.json')
NSIM = 4000
VARS = [('poisson', None)] + [('dc', r) for r in (-0.04, -0.08, -0.12, -0.16)] + [('bp', l) for l in (0.05, 0.1, 0.15)]
KN = {int(S): tuple(c) for S, c in json.load(open(B.OUT))['chosen'].items()}
KN0 = tuple(json.load(open(B.OUT))['chosen']['2017'])           # train-only seasons: the first walk-forward choice


def draw(lh, la, kind, par, rng):
    gh = rng.poisson(lh); ga = rng.poisson(la)
    if kind == 'dc':
        rho = par
        shp = lh.shape
        lh, la, gh, ga = lh.ravel(), la.ravel(), gh.ravel(), ga.ravel()
        tmax = np.maximum.reduce([np.ones_like(lh), 1 - lh * la * rho, 1 + lh * rho, 1 + la * rho,
                                  np.full_like(lh, 1 - rho)])
        idx = np.arange(len(lh))
        while len(idx):
            x, y, a, b = gh[idx], ga[idx], lh[idx], la[idx]
            tau = np.ones_like(a)
            tau = np.where((x == 0) & (y == 0), 1 - a * b * rho, tau)
            tau = np.where((x == 0) & (y == 1), 1 + a * rho, tau)
            tau = np.where((x == 1) & (y == 0), 1 + b * rho, tau)
            tau = np.where((x == 1) & (y == 1), 1 - rho, tau)
            ok = rng.random(len(idx)) * tmax[idx] < np.maximum(tau, 0)
            idx = idx[~ok]
            gh[idx] = rng.poisson(lh[idx]); ga[idx] = rng.poisson(la[idx])
        return gh.reshape(shp), ga.reshape(shp)
    elif kind == 'bp':
        l3 = np.minimum(par, 0.9 * np.minimum(lh, la))
        z = rng.poisson(l3)
        gh = rng.poisson(lh - l3) + z; ga = rng.poisson(la - l3) + z
    return gh, ga


def sim(sn, LS, a, sd0, sd1, kind, par):
    rng = np.random.default_rng(zlib.crc32(f"{sn['lg']}{sn['S']}{sn['md']}".encode()))
    teams, rs = LS[(sn['lg'], sn['S'])]
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    played = [r for r in rs if r['day'] < sn['day']]
    fx = [r for r in rs if r['day'] >= sn['day']]
    left = len(fx) / len(rs)
    T0 = B.table_of(teams, played)
    A = np.array([sn['eff'][t][0] for t in teams]); Dd = np.array([sn['eff'][t][1] for t in teams])
    k = 1 - a * left
    A = A.mean() + k * (A - A.mean()); Dd = Dd.mean() + k * (Dd - Dd.mean())
    hi = np.array([ix[r['h']] for r in fx]); ai = np.array([ix[r['a']] for r in fx])
    mvz = np.array([(sn['mv'][r['h']] - sn['mv'][r['a']]) / 2 if sn['mv'][r['h']] is not None and sn['mv'][r['a']] is not None
                    else 0.0 for r in fx])
    mvc = B.MVK * mvz
    x = G.M0 + sn['env'] + sn['hfa'] + A[hi] - Dd[ai] + mvc
    y = G.M0 + sn['env'] + A[ai] - Dd[hi] - mvc
    lh = np.exp(np.clip(x, -4, 2.5)); la = np.exp(np.clip(y, -4, 2.5))
    sd = math.sqrt(max(0.0, sd1 ** 2 + (sd0 ** 2 - sd1 ** 2) * left))
    dl = rng.normal(0.0, 1.0, (NSIM, n)) * sd
    sh = (dl[:, hi] - dl[:, ai]) / (2 * G.GPM)
    gh, ga = draw(lh[None, :] * np.exp(sh), la[None, :] * np.exp(-sh), kind, par, rng)
    Mh = np.zeros((len(fx), n)); Mh[np.arange(len(fx)), hi] = 1
    Ma = np.zeros((len(fx), n)); Ma[np.arange(len(fx)), ai] = 1
    ph = np.where(gh > ga, 3, np.where(gh == ga, 1, 0)); pa = np.where(ga > gh, 3, np.where(gh == ga, 1, 0))
    pts = np.array([T0[t][0] for t in teams], float)[None, :] + ph @ Mh + pa @ Ma
    gd = np.array([T0[t][1] for t in teams], float)[None, :] + (gh - ga) @ Mh + (ga - gh) @ Ma
    gf = np.array([T0[t][2] for t in teams], float)[None, :] + gh @ Mh + ga @ Ma
    key = pts * 1e6 + (gd + 500) * 1e3 + gf + rng.random(pts.shape)
    order = np.argsort(-key, axis=1)
    pos = np.empty_like(order)
    pos[np.arange(NSIM)[:, None], order] = np.arange(n)[None, :]
    auto = G.REL[sn['lg']][0]
    drawrate = float((gh == ga).mean())
    return teams, (pos == 0).mean(0), (pos < 4).mean(0), (pos >= n - auto).mean(0), pts.mean(0), drawrate


def score(sn, LS, kind, par):
    kn = KN.get(sn['S'], KN0)
    teams, pt, p4, pr, xp, dr = sim(sn, LS, *kn, kind, par)
    pos, pts = B.outcome(LS, (sn['lg'], sn['S']))
    n = len(teams); auto = G.REL[sn['lg']][0]
    yt = np.array([pos[t] == 0 for t in teams], float); y4 = np.array([pos[t] < 4 for t in teams], float)
    yr = np.array([pos[t] >= n - auto for t in teams], float); yp = np.array([pts[t] for t in teams], float)

    def ll(p, y):
        return -np.log(np.clip(np.where(y == 1, p, 1 - p), 1e-3, 1))
    return {'brier_title': (pt - yt) ** 2, 'brier_top4': (p4 - y4) ** 2, 'brier_rel': (pr - yr) ** 2,
            'll_title': ll(pt, yt), 'll_top4': ll(p4, y4), 'll_rel': ll(pr, yr), 'mae_pts': np.abs(xp - yp),
            'gate': (pt - yt) ** 2 + (p4 - y4) ** 2 + (pr - yr) ** 2, 'draw': dr}


_LS = None


def _one(sn):
    return {(sn['lg'], sn['S'], sn['md'], v): score(sn, _LS, *v) for v in VARS}


def actual_draws(LS):
    out = {}
    for (lg, S), (teams, rs) in LS.items():
        out[(lg, S)] = float(np.mean([r['hs'] == r['as'] for r in rs]))
    return out


def main():
    global _LS
    rows = G.add_mv(G.add_market(D.load(G.HIST)))
    _LS = LS = B.league_seasons(rows)
    snaps = pickle.load(open(os.path.join(HERE, '.cache', 'soccer_sim_snaps.pkl'), 'rb'))
    res = {}
    with mp.get_context('fork').Pool(min(4, os.cpu_count() or 1)) as pool:
        for i, part in enumerate(pool.imap_unordered(_one, snaps)):
            res.update(part)
            if i % 40 == 0:
                print(i, flush=True)
    keys = sorted({k[:3] for k in res})
    gate = lambda v, seasons: sum(float(res[k + (v,)]['gate'].sum()) for k in keys if k[1] in seasons)
    allS = B.TRAIN_ONLY + B.SCORED
    chosen = {}
    for fam in ('dc', 'bp'):
        cands = [('poisson', None)] + [v for v in VARS if v[0] == fam]
        chosen[fam] = {S: min(cands, key=lambda v: gate(v, [s for s in allS if s < S])) for S in B.SCORED}
    MET = ['gate', 'brier_title', 'brier_top4', 'brier_rel', 'll_title', 'll_top4', 'll_rel', 'mae_pts']

    def compare(pick):
        out = {}
        for m in MET:
            c, b, cl = [], [], []
            for k in keys:
                if k[1] not in B.SCORED:
                    continue
                c.append(res[k + (pick(k[1]),)][m]); b.append(res[k + (('poisson', None),)][m]); cl += [k[1]] * len(c[-1])
            c, b = np.concatenate(c), np.concatenate(b)
            pr = H.paired(c, b, np.array(cl))
            won = lost = 0
            for S in B.SCORED:
                cs = np.mean(np.concatenate([res[k + (pick(S),)][m] for k in keys if k[1] == S]))
                bs = np.mean(np.concatenate([res[k + (('poisson', None),)][m] for k in keys if k[1] == S]))
                won += cs < bs; lost += cs > bs
            out[m] = {'new': round(float(c.mean()), 5), 'base': round(float(b.mean()), 5), 't': round(pr['t'], 2),
                      'seasonsWon': f'{won}/{len(B.SCORED)}', 'seasonsLost': int(lost)}
        return out
    rep = {'sims': NSIM, 'seasons': B.SCORED, 'matchdays': B.MDS, 'knobs': 'walk-forward chosen per season (soccer_sim_backtest.json)',
           'variants': {}}
    for v in VARS[1:]:
        rep['variants'][f'{v[0]}{v[1]}'] = compare(lambda S, v=v: v)
    for fam in ('dc', 'bp'):
        rep['variants'][f'{fam}-wf'] = compare(lambda S, fam=fam: chosen[fam][S])
        rep['variants'][f'{fam}-wf']['chosen'] = {str(S): f'{v[0]}{v[1] if v[1] is not None else ""}' for S, v in chosen[fam].items()}
    sim_dr = {f'{v[0]}{v[1] if v[1] is not None else ""}': round(float(np.mean([res[k + (v,)]['draw'] for k in keys if k[1] in B.SCORED])), 4)
              for v in VARS}
    ad = actual_draws(LS)
    rep['drawRate'] = {'actual': round(float(np.mean([ad[(k[0], k[1])] for k in keys if k[1] in B.SCORED])), 4), 'sims': sim_dr}
    print(json.dumps(rep, indent=1))
    json.dump(rep, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
