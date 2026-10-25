#!/usr/bin/env python3
"""Score the NHL season sims (audit item 21) and tune how sure they are.

    python3 scripts/nhl_sim_backtest.py          # -> data/nhl_sim_backtest.json

From checkpoints in each season (before game 1, and after each team's 10th, 20th, 41st and 61st game on average),
take the game model's ratings as they stood (weights fit on earlier seasons only), simulate the rest of the regular
season and the playoffs, and score the chances against what happened: playoffs, division title, Cup (Brier, log
loss) and final points (MAE). Two knobs are tuned walk-forward (each scored season uses settings chosen on the
seasons before it):
    a     shrink of the team logits toward the league mean, scaled by the share of the season left: k = 1 - a x left
    sd    season-level rating error (logits), drawn once a sim: sd x sqrt(left)
Scored seasons: 2016-17 to 2018-19 and 2021-22 to 2025-26 (the 2019-20 and 2020-21 formats differ); 2013-14 to
2015-16 only train the first settings. Elo is re-tested the same way (weights refit without it).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H                                     # noqa: E402
import nhl_games as G                                   # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'nhl_sim_backtest.json')
TRAIN_ONLY = [2014, 2015, 2016]
SCORED = [2017, 2018, 2019, 2022, 2023, 2024, 2025, 2026]
CPS = [0, 10, 20, 41, 61]
A_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
SD_GRID = [0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
NSIM = 2000


def divisions(S):
    d = {k: list(v) for k, v in G.DIV.items()}
    if S < 2022:                         # Arizona (UTA's franchise) in the Pacific, no Seattle
        d['Central'].remove('UTA'); d['Pacific'].remove('SEA'); d['Pacific'].append('UTA')
    if S < 2018:
        d['Pacific'].remove('VGK')
    return d


def snapshots(P):
    """walk every game; at each checkpoint keep the rating parts of every team, the points so far and the games left"""
    hist = G.load_hist()
    m = G.Model(P)
    rows, snaps = [], []
    by_s = {}
    for g in hist:
        by_s.setdefault(g['S'], []).append(g)
    cpday = {}
    for S, gs in by_s.items():
        reg = sorted([g for g in gs if not g['po']], key=lambda g: (g['day'], g['id']))
        nt = len({g['h'] for g in reg})
        days = []
        for k in CPS:
            i = int(round(k * nt / 2))
            days.append((k, reg[min(i, len(reg) - 1)]['day']))
        cpday[S] = days
    pending = {S: list(v) for S, v in cpday.items()}
    for g in hist:
        S = g['S']
        m.advance(g['day'], S)
        while not g['po'] and pending.get(S) and g['day'] >= pending[S][0][1]:
            k, day = pending[S].pop(0)
            teams = sorted({x for d in divisions(S).values() for x in d})
            snaps.append({'S': S, 'k': k, 'day': day,
                          'comp': {t: {'elo': (m.elo.r[t] - 1505) / 100, 'xg': m.xg.strength(t), 'g': m.gl.strength(t),
                                       'gk': m.gk.expected(t)} for t in teams},
                          'pts': {t: 2 * m.W[t] + m.OTL[t] for t in teams}})
        if g.get('hs') is not None and g['S'] >= 2012:
            rows.append((g, m.feats(g)))
        m.update(g)
    return hist, rows, snaps


def outcomes(hist, S):
    reg = [g for g in hist if g['S'] == S and not g['po']]
    po = sorted([g for g in hist if g['S'] == S and g['po']], key=lambda g: (g['day'], g['id']))
    pts, rw = {}, {}
    for g in reg:
        hw = g['hs'] > g['as']
        w, l = (g['h'], g['a']) if hw else (g['a'], g['h'])
        pts[w] = pts.get(w, 0) + 2
        pts.setdefault(l, 0)
        if (g.get('per') or 3) > 3:
            pts[l] += 1
        else:
            rw[w] = rw.get(w, 0) + 1
    made = {g['h'] for g in po} | {g['a'] for g in po}
    last = po[-1]
    cup = last['h'] if last['hs'] > last['as'] else last['a']
    divw = {max(ts, key=lambda t: (pts[t], rw.get(t, 0))) for ts in divisions(S).values()}
    return pts, made, divw, cup


def sim(S, base, pts0, left_games, hc, otc, a, sd, left, rng):
    """vectorized season + playoffs; returns per-team P(playoffs), P(division), P(Cup), mean points"""
    divs = divisions(S)
    teams = sorted({x for d in divs.values() for x in d})
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    b = np.array([base[t] for t in teams])
    b = b.mean() + (1 - a * left) * (b - b.mean())
    R = b[:, None] + rng.normal(0, 1, (n, NSIM)) * sd * math.sqrt(max(left, 0.0))
    P = np.array([pts0[t] for t in teams], float)[:, None].repeat(NSIM, 1)
    if left_games:
        hi = np.array([ix[g['h']] for g in left_games]); ai = np.array([ix[g['a']] for g in left_games])
        z = R[hi] - R[ai] + hc
        hw = rng.random(z.shape) < 1 / (1 + np.exp(-z))
        mm = z * 1.6
        ot = rng.random(z.shape) < 1 / (1 + np.exp(-(otc[0] + otc[1] * mm * mm + otc[2] * 6.0)))
        Mh = np.zeros((n, len(hi))); Mh[hi, np.arange(len(hi))] = 1
        Ma = np.zeros((n, len(ai))); Ma[ai, np.arange(len(ai))] = 1
        P += Mh @ (2 * hw + (ot & ~hw)) + Ma @ (2 * ~hw + (ot & hw))
    order = P + rng.random(P.shape) * 0.01
    cols = np.arange(NSIM)
    made = np.zeros((n, NSIM), bool); divw = np.zeros((n, NSIM), bool); cup = np.zeros((n, NSIM), bool)

    def series(x, y):
        hi_ = np.where(order[x, cols] >= order[y, cols], x, y); lo_ = np.where(hi_ == x, y, x)
        d = R[hi_, cols] - R[lo_, cols]
        wins = np.zeros(NSIM)
        for k in range(7):
            home = 1.0 if k in (0, 1, 4, 6) else -1.0
            wins += rng.random(NSIM) < 1 / (1 + np.exp(-(d + home * hc)))
        return np.where(wins >= 4, hi_, lo_)
    champs = []
    for cf, ds in G.CONF.items():
        tops, rest = [], []
        for d in ds:
            di = np.array([ix[t] for t in divs[d]])
            srt = di[np.argsort(-order[di], axis=0)]
            tops.append(srt[:3]); rest.append(srt[3:])
            divw[srt[0], cols] = True
        rs = np.concatenate(rest)
        rs = np.take_along_axis(rs, np.argsort(-order[rs, cols[None, :].repeat(len(rs), 0)], axis=0), 0)
        wc1, wc2 = rs[0], rs[1]
        for tp in tops:
            for j in range(3):
                made[tp[j], cols] = True
        made[wc1, cols] = True; made[wc2, cols] = True
        first_best = order[tops[0][0], cols] >= order[tops[1][0], cols]
        opp0 = np.where(first_best, wc2, wc1); opp1 = np.where(first_best, wc1, wc2)
        r2 = []
        for tp, opp in ((tops[0], opp0), (tops[1], opp1)):
            r2.append(series(series(tp[0], opp), series(tp[1], tp[2])))
        champs.append(series(r2[0], r2[1]))
    cw = series(champs[0], champs[1])
    cup[cw, cols] = True
    return teams, made.mean(1), divw.mean(1), cup.mean(1), P.mean(1)


def bases(snaps, rows, feats):
    """walk-forward weights: season S's logits use a logistic fit on 2012..S-1 games"""
    X = G.design(rows, feats)
    y = np.array([g['hs'] > g['as'] for g, f in rows], float)
    Ss = np.array([g['S'] for g, f in rows])
    coefs = {}
    for S in sorted({s['S'] for s in snaps}):
        tr = Ss < S
        coefs[S] = dict(zip(feats, G.logit_fit(X[tr], y[tr])))
    return coefs


def score_cp(snap, hist, coefs, otc, a, sd, out, rng):
    S = snap['S']
    c = coefs[S]
    base = {t: sum(c[k] * v for k, v in snap['comp'][t].items() if k in c) for t in snap['comp']}
    reg = [g for g in hist if g['S'] == S and not g['po']]
    left_games = [g for g in reg if g['day'] >= snap['day']]
    left = len(left_games) / len(reg)
    teams, pm, pd_, pc, xp = sim(S, base, snap['pts'], left_games, c.get('home', 0.13), otc, a, sd, left, rng)
    pts, made, divw, cup = out
    ym = np.array([t in made for t in teams], float); yd = np.array([t in divw for t in teams], float)
    yc = np.array([t == cup for t in teams], float); yp = np.array([pts[t] for t in teams], float)
    eps = 1e-3
    return {'brier_po': ((pm - ym) ** 2), 'brier_div': ((pd_ - yd) ** 2), 'brier_cup': ((pc - yc) ** 2),
            'll_cup': -np.log(np.clip(np.where(yc == 1, pc, 1 - pc), eps, 1)),
            'll_po': -np.log(np.clip(np.where(ym == 1, pm, 1 - pm), eps, 1)),
            'mae_pts': np.abs(xp - yp), 'gate': (pm - ym) ** 2 + (pd_ - yd) ** 2 + (pc - yc) ** 2, 'maxcup': float(pc.max()), 'left': left}


KEYS = ['gate', 'brier_po', 'brier_div', 'brier_cup', 'll_po', 'll_cup', 'mae_pts']


def grid_scores(snaps, hist, coefs, otc):
    """every (a, sd) on every checkpoint, common random numbers"""
    outs = {S: outcomes(hist, S) for S in TRAIN_ONLY + SCORED}
    res = {}
    for sn in snaps:
        if sn['S'] not in outs:
            continue
        for a in A_GRID:
            for sd in SD_GRID:
                rng = np.random.default_rng(1000 * sn['S'] + sn['k'])
                res[(sn['S'], sn['k'], a, sd)] = score_cp(sn, hist, coefs, otc, a, sd, outs[sn['S']], rng)
        print(sn['S'], sn['k'], flush=True)
    return res


def objective(r):
    """the gate: summed Brier of playoffs, division and Cup"""
    return float(r['brier_po'].mean() + r['brier_div'].mean() + r['brier_cup'].mean())


def walkforward(res, base_cfg, a_grid=None):
    """each scored season: the (a, sd) with the lowest summed Brier over every earlier season's checkpoints"""
    chosen, rows = {}, []
    for S in SCORED:
        prior = [s for s in TRAIN_ONLY + SCORED if s < S]
        best = min(((a, sd) for a in (a_grid or A_GRID) for sd in SD_GRID),
                   key=lambda c: sum(objective(res[(s, k, c[0], c[1])]) for s in prior for k in CPS if (s, k, c[0], c[1]) in res))
        chosen[S] = best
        for k in CPS:
            if (S, k, *best) in res:
                rows.append((S, k, res[(S, k, *best)], res[(S, k, *base_cfg)]))
    return chosen, rows


def summarize(rows, label):
    out = {}
    for key in KEYS:
        c = np.concatenate([r[2][key] for r in rows]); b = np.concatenate([r[3][key] for r in rows])
        cl = np.concatenate([[r[0]] * len(r[2][key]) for r in rows])
        pr = H.paired(c, b, cl)
        won = sum(1 for S in SCORED if np.mean(np.concatenate([r[2][key] for r in rows if r[0] == S])) <
                  np.mean(np.concatenate([r[3][key] for r in rows if r[0] == S])))
        out[key] = {'new': round(float(c.mean()), 4), 'base': round(float(b.mean()), 4), 't': round(pr['t'], 2),
                    'seasonsWon': f'{won}/{len(SCORED)}'}
    bycp = {}
    for k in CPS:
        rr = [r for r in rows if r[1] == k]
        bycp[str(k)] = {'new': round(float(np.mean([objective(r[2]) for r in rr])), 4),
                        'base': round(float(np.mean([objective(r[3]) for r in rr])), 4),
                        'maxCupNew': round(float(np.mean([r[2]['maxcup'] for r in rr])), 3),
                        'maxCupBase': round(float(np.mean([r[3]['maxcup'] for r in rr])), 3)}
    print(label, json.dumps(out), json.dumps(bycp), flush=True)
    return {'scores': out, 'byCheckpoint': bycp}


def main():
    fit = json.load(open(G.FIT))
    P, feats, otc = fit['params'], fit['feats'], fit['ot']
    hist, rows, snaps = snapshots(P)
    print('snapshots', len(snaps), 'rows', len(rows), flush=True)
    rep = {'checkpoints': CPS, 'seasons': SCORED, 'sims': NSIM, 'feats': feats}
    coefs = bases(snaps, rows, feats)
    res = grid_scores(snaps, hist, coefs, otc)
    base_cfg = (0.0, min(SD_GRID, key=lambda s: abs(s - fit['seasonSd'])))
    chosen, wrows = walkforward(res, base_cfg)
    rep['chosen'] = {str(S): list(v) for S, v in chosen.items()}
    rep['shipped'] = {'base': list(base_cfg), 'walkForward': summarize(wrows, 'tuned vs shipped')}
    ch0, wr0 = walkforward(res, base_cfg, [0.0])
    rep['sdOnly'] = {'chosen': {str(S): list(v) for S, v in ch0.items()}, **summarize(wr0, 'sd only vs shipped')}
    rep['shrinkVsSdOnly'] = summarize([(S, k, r, b[2]) for (S, k, r, _), b in zip(wrows, wr0)], 'tuned vs sd only')
    # pooled best over every scored season (what would ship)
    allk = [(s, k) for s in TRAIN_ONLY + SCORED for k in CPS]
    best = min(((a, sd) for a in A_GRID for sd in SD_GRID),
               key=lambda c: sum(objective(res[(s, k, *c)]) for s, k in allk if (s, k, *c) in res))
    rep['pooledBest'] = list(best)
    rep['surface'] = {f'{a},{sd}': round(sum(objective(res[(s, k, a, sd)]) for s in SCORED for k in CPS) / (len(SCORED) * len(CPS)), 5)
                      for a in A_GRID for sd in SD_GRID}
    if '--no-elo' in sys.argv:
        old = json.load(open(OUT)) if os.path.exists(OUT) else {}
        rep['eloRetest'] = old.get('eloRetest')
        json.dump(rep, open(OUT, 'w'), indent=1)
        return
    # Elo re-test: weights refit without it, same tuned (a, sd) walk-forward, scored against the full model
    nf = [f for f in feats if f != 'elo']
    coefs_ne = bases(snaps, rows, nf)
    res_ne = grid_scores(snaps, hist, coefs_ne, otc)
    _, wr_ne = walkforward(res_ne, base_cfg)
    pair = [(S, k, r2, r) for (S, k, r, _), (_, _, r2, _) in zip(wrows, wr_ne)]
    rep['eloRetest'] = {'note': 'no-Elo minus full model, each with its own walk-forward (a, sd)',
                        **summarize(pair, 'no elo vs full')}
    # game-level walk-forward log loss with and without Elo (every scored season's regular-season games)
    X = G.design(rows, feats); Xn = G.design(rows, nf)
    y = np.array([g['hs'] > g['as'] for g, f in rows], float)
    Ss = np.array([g['S'] for g, f in rows]); day = np.array([g['day'] for g, f in rows])
    p1 = G.walk_logit(X, y, Ss, 2014); p0 = G.walk_logit(Xn, y, Ss, 2014)
    ok = ~np.isnan(p1) & ~np.isnan(p0)
    for lab, msk in (('2014-23', ok & (Ss <= 2023)), ('2024-26', ok & (Ss >= 2024))):
        pr = H.paired(H.logloss(p0[msk], y[msk]), H.logloss(p1[msk], y[msk]), day[msk])
        rep['eloRetest'][f'games {lab}'] = {'llFull': round(float(H.logloss(p1[msk], y[msk]).mean()), 5),
                                           'llNoElo': round(float(H.logloss(p0[msk], y[msk]).mean()), 5),
                                           't': round(pr['t'], 2), 'n': int(msk.sum())}
    print(json.dumps(rep['eloRetest']), flush=True)
    json.dump(rep, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
