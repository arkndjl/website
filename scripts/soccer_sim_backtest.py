#!/usr/bin/env python3
"""Score the soccer league sims (audit item 21) and tune how sure they are.

    python3 scripts/soccer_sim_backtest.py       # -> data/soccer_sim_backtest.json

From checkpoints in every big-five season (before matchday 1, and after matchdays 9, 19 and 28), take each club's
attack and defence as the game model had them (walk-forward, scripts/soccer_games.py), simulate the rest of the
season the way the live sims do, and score title, top four and the automatic relegation places (Brier, log loss)
and final points (MAE) against the final table. Three knobs, tuned walk-forward (each scored season uses the
settings with the lowest summed Brier on the seasons before it):
    a       shrink of attack and defence toward the league mean by the share of the season left: 1 - a x left
    sd0     rating error (goals of margin a match) before matchday 1
    sd1     the same with the season over; in between sd^2 = sd1^2 + (sd0^2 - sd1^2) x left (the live form)
Scored seasons: 2016-17 to 2018-19 and 2021-22 to 2025-26 (the 2019-20 and 2020-21 seasons straddle the calendar);
2012-13 to 2015-16 only train the first settings.
"""
import json
import math
import os
import multiprocessing as mp
import pickle
import sys
import zlib
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H                                     # noqa: E402
import soccer_data as D                                 # noqa: E402
import soccer_games as G                                # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_sim_backtest.json')
TRAIN_ONLY = [2013, 2014, 2015, 2016]
SCORED = [2017, 2018, 2019, 2022, 2023, 2024, 2025, 2026]
MDS = [0, 9, 19, 28]
A_GRID = [0.0, 0.1, 0.2, 0.3, 0.4]
SD0_GRID = [0.2, 0.3, 0.38, 0.45, 0.55]
SD1_GRID = [0.0, 0.15, 0.3]
BASE = (0.0, 0.38, 0.3)                                 # live: rank_sd soccer a .09 b .054, no shrink
NSIM = 2000
MVK = G.params().get('mv', 0.0)


def league_seasons(rows):
    by = defaultdict(list)
    for r in rows:
        if r['lg'] in D.BIG5 and r.get('hs') is not None and r.get('st') == 'FT':
            S = D.season_of(r['day'], r['lg'])
            if S in TRAIN_ONLY or S in SCORED:
                by[(r['lg'], S)].append(r)
    out = {}
    for k, rs in by.items():
        c = defaultdict(int)
        for r in rs:
            c[r['h']] += 1; c[r['a']] += 1
        teams = sorted(t for t, v in c.items() if v >= 20)
        rs = sorted([r for r in rs if r['h'] in teams and r['a'] in teams], key=lambda r: (r['day'], r.get('t') or '', r['id']))
        n = len(teams)
        if len(rs) >= 0.97 * n * (n - 1):
            out[k] = (teams, rs)
    return out


def table_of(teams, rs):
    T = {t: [0, 0, 0] for t in teams}           # pts, gd, gf
    for r in rs:
        for t, gf, ga in ((r['h'], r['hs'], r['as']), (r['a'], r['as'], r['hs'])):
            T[t][0] += 3 if gf > ga else 1 if gf == ga else 0
            T[t][1] += gf - ga; T[t][2] += gf
    return T


def snapshots(rows, P, LS):
    """walk the game model; at each checkpoint keep every club's attack and defence, the league's goal environment
    and home edge, and the squad-value edge as known that day"""
    mvT = G.D.load(G.MVF) if os.path.exists(G.MVF) else None
    cpd = {}
    for k, (teams, rs) in LS.items():
        n = len(teams)
        for md in MDS:
            i = min(int(round(md * n / 2)), len(rs) - 1)
            cpd.setdefault(k, []).append((md, rs[i]['day']))
    snaps = []

    def mv_at(t, day):
        if not mvT:
            return None
        tm = mvT['espn2tm'].get(t)
        cps = [c for c in mvT['cp'] if c <= day]
        return mvT['sq'][cps[-1]].get(tm) if tm and cps else None

    def score(r, S, lh, la, R):
        k = (r['lg'], S)
        pend = cpd.get(k)
        while pend and r['day'] >= pend[0][1]:
            md, day = pend.pop(0)
            teams, rs = LS[k]
            for x in rs:                                  # clubs yet to play this season: into the league now
                if R.season.get(x['h']) != S or R.season.get(x['a']) != S:
                    R.prep(x)
            L = r['lg']
            eff = {t: R.eff(t) for t in teams}
            mv = {t: mv_at(t, day) for t in teams}
            snaps.append({'lg': L, 'S': S, 'md': md, 'day': day, 'eff': eff, 'env': R.env[L], 'hfa': R.hfa[L],
                          'mv': mv})
    G.run(rows, P, score)
    return snaps


def sim(sn, LS, a, sd0, sd1, rng):
    teams, rs = LS[(sn['lg'], sn['S'])]
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    played = [r for r in rs if r['day'] < sn['day']]
    fx = [r for r in rs if r['day'] >= sn['day']]
    left = len(fx) / len(rs)
    T0 = table_of(teams, played)
    A = np.array([sn['eff'][t][0] for t in teams]); Dd = np.array([sn['eff'][t][1] for t in teams])
    k = 1 - a * left
    A = A.mean() + k * (A - A.mean()); Dd = Dd.mean() + k * (Dd - Dd.mean())
    hi = np.array([ix[r['h']] for r in fx]); ai = np.array([ix[r['a']] for r in fx])
    mvz = np.array([(sn['mv'][r['h']] - sn['mv'][r['a']]) / 2 if sn['mv'][r['h']] is not None and sn['mv'][r['a']] is not None
                    else 0.0 for r in fx])
    mvc = MVK * mvz
    x = G.M0 + sn['env'] + sn['hfa'] + A[hi] - Dd[ai] + mvc
    y = G.M0 + sn['env'] + A[ai] - Dd[hi] - mvc
    lh = np.exp(np.clip(x, -4, 2.5)); la = np.exp(np.clip(y, -4, 2.5))
    sd = math.sqrt(max(0.0, sd1 ** 2 + (sd0 ** 2 - sd1 ** 2) * left))
    dl = rng.normal(0.0, 1.0, (NSIM, n)) * sd
    sh = (dl[:, hi] - dl[:, ai]) / (2 * G.GPM)
    gh = rng.poisson(lh[None, :] * np.exp(sh)); ga = rng.poisson(la[None, :] * np.exp(-sh))
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
    return teams, (pos == 0).mean(0), (pos < 4).mean(0), (pos >= n - auto).mean(0), pts.mean(0), left


def outcome(LS, k):
    teams, rs = LS[k]
    T = table_of(teams, rs)
    srt = sorted(teams, key=lambda t: (-T[t][0], -T[t][1], -T[t][2]))
    return {t: i for i, t in enumerate(srt)}, {t: T[t][0] for t in teams}


KEYS = ['gate', 'brier_title', 'brier_top4', 'brier_rel', 'll_title', 'll_rel', 'mae_pts']


def score_cp(sn, LS, a, sd0, sd1):
    rng = np.random.default_rng(zlib.crc32(f"{sn['lg']}{sn['S']}{sn['md']}".encode()))
    teams, pt, p4, pr, xp, left = sim(sn, LS, a, sd0, sd1, rng)
    pos, pts = outcome(LS, (sn['lg'], sn['S']))
    n = len(teams); auto = G.REL[sn['lg']][0]
    yt = np.array([pos[t] == 0 for t in teams], float); y4 = np.array([pos[t] < 4 for t in teams], float)
    yr = np.array([pos[t] >= n - auto for t in teams], float); yp = np.array([pts[t] for t in teams], float)

    def ll(p, y):
        return -np.log(np.clip(np.where(y == 1, p, 1 - p), 1e-3, 1))
    return {'brier_title': (pt - yt) ** 2, 'brier_top4': (p4 - y4) ** 2, 'brier_rel': (pr - yr) ** 2,
            'll_title': ll(pt, yt), 'll_rel': ll(pr, yr), 'mae_pts': np.abs(xp - yp), 'gate': (pt - yt) ** 2 + (p4 - y4) ** 2 + (pr - yr) ** 2, 'maxtitle': float(pt.max())}


def objective(r):
    return float(r['brier_title'].sum() + r['brier_top4'].sum() + r['brier_rel'].sum())


CFG = [(a, s0, s1) for a in A_GRID for s0 in SD0_GRID for s1 in SD1_GRID]
_LS = None


def _one(sn):
    return {(sn['lg'], sn['S'], sn['md'], c): score_cp(sn, _LS, *c) for c in CFG}


def main():
    rows = G.add_mv(G.add_market(D.load(G.HIST)))
    P = G.params()
    LS = league_seasons(rows)
    cache = os.path.join(HERE, '.cache', 'soccer_sim_snaps.pkl')
    if os.path.exists(cache) and '--fresh' not in sys.argv:
        snaps = pickle.load(open(cache, 'rb'))
    else:
        snaps = snapshots(rows, P, LS)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        pickle.dump(snaps, open(cache, 'wb'))
    print('snapshots', len(snaps), flush=True)
    global _LS
    _LS = LS
    res = {}
    with mp.get_context('fork').Pool(min(4, os.cpu_count() or 1)) as pool:
        for i, part in enumerate(pool.imap_unordered(_one, snaps)):
            res.update(part)
            if i % 20 == 0:
                print(i, flush=True)
    keys = sorted({k[:3] for k in res})

    def tot(c, seasons):
        return sum(objective(res[(lg, S, md, c)]) for lg, S, md in keys if S in seasons)
    chosen, pairs = {}, []
    for S in SCORED:
        best = min(CFG, key=lambda c: tot(c, [s for s in TRAIN_ONLY + SCORED if s < S]))
        chosen[S] = best
        for lg, S2, md in keys:
            if S2 == S:
                pairs.append((S, lg, md, res[(lg, S, md, best)], res[(lg, S, md, BASE)]))
    rep = {'matchdays': MDS, 'seasons': SCORED, 'sims': NSIM, 'base': list(BASE),
           'chosen': {str(S): list(c) for S, c in chosen.items()},
           'pooledBest': list(min(CFG, key=lambda c: tot(c, TRAIN_ONLY + SCORED))),
           'surface': {','.join(map(str, c)): round(tot(c, SCORED), 3) for c in CFG}}
    sc = {}
    for key in KEYS:
        c = np.concatenate([p[3][key] for p in pairs]); b = np.concatenate([p[4][key] for p in pairs])
        cl = np.concatenate([[p[0]] * len(p[3][key]) for p in pairs])
        pr = H.paired(c, b, cl)
        won = sum(1 for S in SCORED if np.mean(np.concatenate([p[3][key] for p in pairs if p[0] == S])) <
                  np.mean(np.concatenate([p[4][key] for p in pairs if p[0] == S])))
        sc[key] = {'new': round(float(c.mean()), 5), 'base': round(float(b.mean()), 5), 't': round(pr['t'], 2),
                   'seasonsWon': f'{won}/{len(SCORED)}'}
    rep['walkForward'] = sc
    rep['byMatchday'] = {str(md): {'new': round(float(np.mean([objective(p[3]) for p in pairs if p[2] == md])), 4),
                                   'base': round(float(np.mean([objective(p[4]) for p in pairs if p[2] == md])), 4),
                                   'maxTitleNew': round(float(np.mean([p[3]['maxtitle'] for p in pairs if p[2] == md])), 3),
                                   'maxTitleBase': round(float(np.mean([p[4]['maxtitle'] for p in pairs if p[2] == md])), 3)}
                         for md in MDS}
    print(json.dumps({k: rep[k] for k in ('chosen', 'pooledBest', 'walkForward', 'byMatchday')}, indent=1), flush=True)
    json.dump(rep, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
