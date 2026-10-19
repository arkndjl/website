#!/usr/bin/env python3
"""Backtests for the NFL board's season odds and the margin model (data/nfl_season_backtest.json).

    python3 scripts/nfl_season_backtest.py            # tiebreak check, season-odds sd, market blend
    python3 scripts/nfl_season_backtest.py --check    # tiebreak check only
    python3 scripts/nfl_season_backtest.py --ratings  # ridge team ratings in the margin model (ratingsTest)

  tiebreaks  nfl_games.League on each finished season's actual results against the real playoff field (2002-25)
  simTest    the season odds' rating uncertainty (RATING_SD): for 2015-25, before weeks 1, 5, 9 and 13, the
             walk-forward team ratings as of then (coefficients fit only on earlier seasons; no injury term, the next
             game's listed starter at QB), the rest of the regular season simulated with the tiebreakers, scored
             against what happened: make the playoffs, win the division (log loss, Brier) and final wins (log loss of
             the simulated count, CRPS). A fixed sd and sd0 x sqrt(share of the season left) with a floor, tuned on
             2015-20, reported on 2021-25 against the old fixed 2.5; paired t over team-seasons
  blendTest  w x model + (1 - w) x closing spread: MAE and win log loss, w tuned on 2015-20, reported on 2021-25
  ratingsTest  ridge (least-squares) team ratings on capped margins with a prior, decayed by week and season,
             joining the margin model's features or replacing Elo, in its walk-forward refit
"""
import json
import math
import os
import random
import sys
from collections import defaultdict
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N  # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'nfl_season_backtest.json')
WEEKS = (1, 5, 9, 13)
SEASONS = range(2015, 2026)
NS = 2000                                      # sims a checkpoint
SDS = [round(0.25 * i, 2) for i in range(25)]  # rating sds simulated at every checkpoint (0-6)
FIXED = [0, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]
SHRINK = [(s0, fl) for s0 in (2, 2.5, 3, 3.5, 4, 4.5, 5, 6) for fl in (0, 1, 1.5, 2, 2.5)]


def walk(games, box, qbs, params, inj):
    """The model's walk over every game: each game's features, and at each checkpoint each team's rating parts."""
    m = N.Model(**params)
    data, snaps = [], {}
    nxt_qb = {}
    for i, g in enumerate(games):
        s, wk = int(g['season']), int(g['week'])
        x, tx = m.feats(g)
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        if s in SEASONS and g['game_type'] == 'REG' and wk in WEEKS and (s, wk) not in snaps:
            L = m.lgepa()
            # each team's QB: the listed starter of its next game (from this week on)
            q = {}
            for h in games[i:]:
                if int(h['season']) != s:
                    break
                for side in ('home', 'away'):
                    q.setdefault(N.team(h[f'{side}_team']), h[f'{side}_qb_id'])
            qa = lambda t: (m.qbval(q[t]) - m.rate(m.qbt, t, m.repl)) if q.get(t) else 0.0
            snaps[(s, wk)] = {t: {'elo': (m.elo[t] - 1505) / 25, 'epa': (m.rate(m.off, t, L) - m.rate(m.dfn, t, L)) * 62,
                                  'qb': qa(t) * 38, 'mkt': m.mkt[t]} for t in N.DIV_OF}
        data.append((g, x))
        m.update(g, box, qbs)
    return data, snaps


def coefs(data):
    """Each season's coefficients, fit on the seasons before it (as nfl_games.fit's walk-forward)."""
    D = [(g, x) for g, x in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
    X = np.array([[x[f] for f in N.FEATS] for _, x in D]); y = np.array([N.num(g['result']) for g, _ in D])
    S = np.array([int(g['season']) for g, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D])
    B, pred = {}, np.full(len(y), np.nan)
    for s in SEASONS:
        b = np.linalg.lstsq(X[S < s], y[S < s], rcond=None)[0]
        B[s] = dict(zip(N.FEATS, b)); pred[S == s] = X[S == s] @ b
    return B, D, X, y, S, line, pred


# ---------------------------------------------------------------- season odds
def sim_checkpoint(job):
    """One checkpoint: for every sd in SDS, each team's P(playoffs), P(division), and its simulated win counts."""
    s, wk, R, b, sched, res0, mus_ix = job
    lg = N.League(sched, 3 if s >= 2020 else 2)
    left = [k for k, r in enumerate(res0) if r is None]
    mu = np.array([mus_ix[k] for k in left])
    hi = np.array([lg.g[k][0] for k in left]); ai = np.array([lg.g[k][1] for k in left])
    rs = np.random.default_rng(1000 * s + wk)
    z = rs.standard_normal((NS, 32)); e = rs.standard_normal((NS, len(left)))
    out = {}
    T = lg.T
    tix = {t: i for i, t in enumerate(T)}
    for rsd in SDS:
        win = (mu[None, :] + rsd * (z[:, hi] - z[:, ai]) + b['sd'] * e) > 0
        rng = random.Random(s * 100 + wk)
        po, dv = np.zeros(32), np.zeros(32)
        W = np.zeros((NS, 32))
        for n in range(NS):
            res = list(res0)
            for j, k in enumerate(left):
                res[k] = 1.0 if win[n, j] else 0.0
            field, w = lg.seeds(res, rng)
            for c, sd_ in field.items():
                for i, t in enumerate(sd_):
                    ti = tix[t]
                    po[ti] += 1
                    if i < 4:
                        dv[ti] += 1
            W[n] = [w[t] for t in T]
        out[rsd] = (po / NS, dv / NS, W)
    return s, wk, out


def score(p, y, clip):
    p = np.clip(p, clip, 1 - clip)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p)), (p - y) ** 2


def wins_scores(W, act):
    """Log loss of the simulated win count at the actual one (a tie's half win splits between neighbours), and CRPS."""
    ll, crps = np.zeros(W.shape[1]), np.zeros(W.shape[1])
    for t in range(W.shape[1]):
        w = W[:, t]
        d = np.abs(w - act[t])
        p = np.mean(np.where(d < 0.25, 1.0, np.where(d < 0.75, 0.5, 0.0)))
        ll[t] = -math.log(max(p, 0.5 / len(w)))
        srt = np.sort(w); n = len(srt)
        # E|X - y| - E|X - X'| / 2, from the sorted sample
        crps[t] = np.mean(np.abs(srt - act[t])) - np.sum((2 * np.arange(1, n + 1) - n - 1) * srt) / n ** 2
    return ll, crps


def sim_test(games, data, snaps, B, sd):
    jobs, facts = [], {}
    for s in SEASONS:
        sg, res_all = N.season_results(games, s)
        sched = [(g['home_team'], g['away_team']) for g in sg]
        lg = N.League(sched, 3 if s >= 2020 else 2)
        field, wact = lg.seeds(res_all, random.Random(1))
        po = {t for c in field.values() for t in c}
        dv = {t for c in field.values() for t in c[:4]}
        facts[s] = {'po': np.array([t in po for t in lg.T], float), 'dv': np.array([t in dv for t in lg.T], float),
                    'w': np.array([wact[t] for t in lg.T])}
        b = dict(B[s]); b['sd'] = sd
        rest = lambda x: max(-7, min(7, N.num(x, 7) - 7))
        for wk in WEEKS:
            snap = snaps[(s, wk)]
            R = {t: sum(b[f] * v[f] for f in ('elo', 'epa', 'qb', 'mkt')) for t, v in snap.items()}
            res0 = [r if int(g['week']) < wk else None for g, r in zip(sg, res_all)]
            mus = {k: R[N.team(g['home_team'])] - R[N.team(g['away_team'])] + (b['home'] if g['location'] != 'Neutral' else 0)
                   + b['rest'] * (rest(g['home_rest']) - rest(g['away_rest'])) for k, g in enumerate(sg) if res0[k] is None}
            # a cancelled game (2022 BUF-CIN) is simulated from week 1 to 13 but has no result
            jobs.append((s, wk, R, b, sched, res0, mus))
            facts[(s, wk)] = sum(1 for r in res0 if r is None) / len(sg)
    with Pool(int(os.environ.get('PROCS', 4))) as pool:
        got = pool.map(sim_checkpoint, jobs, chunksize=1)
    # per (season, week, sd): team arrays of each score
    sc = {}
    for s, wk, out in got:
        f = facts[s]
        for rsd, (po, dv, W) in out.items():
            llp, brp = score(po, f['po'], 0.5 / NS)
            lld, brd = score(dv, f['dv'], 0.5 / NS)
            llw, crps = wins_scores(W, f['w'])
            sc[(s, wk, rsd)] = np.array([llp, brp, lld, brd, llw, crps])     # 6 x 32
    return sc, facts


def cfg_sd(cfg, left):
    if cfg[0] == 'fixed':
        return cfg[1]
    return max(cfg[2], cfg[1] * math.sqrt(left))


def snap_sd(x):
    return min(SDS, key=lambda v: abs(v - x))


def table(sc, facts, cfg, seasons):
    """Mean scores over teams x checkpoints, and per team-season combined log loss (playoffs + division + wins)."""
    rows, units = [], []
    for s in seasons:
        u = np.zeros(32)
        for wk in WEEKS:
            a = sc[(s, wk, snap_sd(cfg_sd(cfg, facts[(s, wk)])))]
            rows.append(a)
            u += a[0] + a[2] + a[4]
        units.append(u)
    A = np.concatenate(rows, axis=1)
    m = A.mean(axis=1)
    return {'llPlayoff': round(m[0], 4), 'brierPlayoff': round(m[1], 4), 'llDiv': round(m[2], 4), 'brierDiv': round(m[3], 4),
            'llWins': round(m[4], 4), 'crpsWins': round(m[5], 4), 'llAll': round(m[0] + m[2] + m[4], 4)}, np.concatenate(units)


def tstat(d):
    sd = d.std(ddof=1)
    return float(d.mean() / (sd / math.sqrt(len(d)))) if sd > 0 else None


def rnd(x, k=2):
    return None if x is None else round(x, k)


# ---------------------------------------------------------------- market blend
def blend_test(D, y, S, line, pred, sd):
    ok = ~np.isnan(line) & ~np.isnan(pred)
    tune, held = ok & (S >= 2015) & (S <= 2020), ok & (S >= 2021)
    nt = lambda k: k & (y != 0)

    def ll(p, k):
        k = nt(k)
        sd_ = np.std((p - y)[tune])                     # the blend's residual sd on the tuning seasons
        q = np.clip([N.phi(v / sd_) for v in p[k]], 1e-6, 1 - 1e-6)
        h = (y[k] > 0).astype(float)
        return -(h * np.log(q) + (1 - h) * np.log(1 - q))
    ws = [round(0.05 * i, 2) for i in range(21)]
    bl = lambda w: w * pred + (1 - w) * line
    out = {'grid': {}}
    for w in ws:
        p = bl(w)
        out['grid'][w] = {'maeTune': round(float(np.mean(np.abs(p - y)[tune])), 4), 'maeHeld': round(float(np.mean(np.abs(p - y)[held])), 4),
                          'llTune': round(float(np.mean(ll(p, tune))), 5), 'llHeld': round(float(np.mean(ll(p, held))), 5)}
    g = out['grid']
    out['bestMaeTune'] = min(ws, key=lambda w: g[w]['maeTune']); out['bestMaeHeld'] = min(ws, key=lambda w: g[w]['maeHeld'])
    out['bestLlTune'] = min(ws, key=lambda w: g[w]['llTune']); out['bestLlHeld'] = min(ws, key=lambda w: g[w]['llHeld'])
    for key, w in (('atMaeTune', out['bestMaeTune']), ('atLlTune', out['bestLlTune']), ('atMaeHeld', out['bestMaeHeld']), ('atLlHeld', out['bestLlHeld'])):
        p = bl(w)
        r = {'w': w}
        for lab, k in (('tune', tune), ('held', held)):
            da = np.abs(p - y)[k] - np.abs(line - y)[k]
            dl = ll(p, k) - ll(line, k)
            r[lab] = {'games': int(k.sum()), 'mae': round(float(np.mean(np.abs(p - y)[k])), 3), 'maeClose': round(float(np.mean(np.abs(line - y)[k])), 3),
                      'tMae': rnd(tstat(da)), 'll': round(float(np.mean(ll(p, k))), 4), 'llClose': round(float(np.mean(ll(line, k))), 4), 'tLl': rnd(tstat(dl))}
        out[key] = r
    return out


# ---------------------------------------------------------------- ridge team ratings
def ridge_feature(games, hl, carry, lam, cap):
    """game_id -> home minus away rating, neutral field: each week's ratings are weighted least squares on every earlier
    game's margin (capped), r_home - r_away + home edge, weights halving every `hl` weeks and x `carry` each season
    back, with a ridge prior of `lam` games at 0."""
    T = sorted(N.DIV_OF); ix = {t: i for i, t in enumerate(T)}
    rows, ys, ords, seas, out = [], [], [], [], {}
    key, ordn, r, pend = None, -1, np.zeros(33), []
    pen = np.diag([lam] * 32 + [0.0])
    for g in games:
        k = (int(g['season']), int(g['week']))
        if k != key:
            for x_, y_ in pend:
                rows.append(x_); ys.append(y_); ords.append(ordn); seas.append(key[0])
            pend, key, ordn = [], k, ordn + 1
            if rows:
                X = np.array(rows); w = 0.5 ** ((ordn - np.array(ords)) / hl) * carry ** (k[0] - np.array(seas))
                r = np.linalg.solve(X.T @ (X * w[:, None]) + pen, X.T @ (w * np.array(ys)))
        h, a = ix[N.team(g['home_team'])], ix[N.team(g['away_team'])]
        out[g['game_id']] = r[h] - r[a]
        if g['home_score'] not in ('', 'NA'):
            x = np.zeros(33); x[h] = 1; x[a] = -1; x[32] = 0.0 if g['location'] == 'Neutral' else 1.0
            m = N.num(g['result'])
            pend.append((x, max(-cap, min(cap, m)) if cap else m))
    return out


def ratings_test(G, D, X, y, S):
    """Ridge ratings joining the margin model's features, or replacing Elo: the walk-forward refit each season,
    grid on 2015-20 MAE, paired t (per game abs error) against the model as it is."""
    def wf(Xm):
        pred = np.full(len(y), np.nan)
        for s in SEASONS:
            b = np.linalg.lstsq(Xm[S < s], y[S < s], rcond=None)[0]; pred[S == s] = Xm[S == s] @ b
        return np.abs(pred - y)
    tune, held = (S >= 2015) & (S <= 2020), S >= 2021
    e0 = wf(X)
    gids = [g['game_id'] for g, _ in D]
    ie = N.FEATS.index('elo')
    res = []
    for hl in (6, 12, 24):
        for carry in (0.3, 0.6, 1.0):
            for lam in (2, 8, 32):
                for cap in (0, 24):
                    f = ridge_feature(G, hl, carry, lam, cap)
                    col = np.array([f[i] for i in gids])
                    for mode in ('join', 'replace'):
                        Xm = np.column_stack([X, col]) if mode == 'join' else np.column_stack([np.delete(X, ie, axis=1), col])
                        e = wf(Xm)
                        d = e - e0
                        res.append({'hl': hl, 'carry': carry, 'lam': lam, 'cap': cap, 'mode': mode,
                                    'maeTune': round(float(e[tune].mean()), 4), 'maeHeld': round(float(e[held].mean()), 4),
                                    'tTune': rnd(tstat(d[tune])), 'tHeld': rnd(tstat(d[held]))})
                    print(res[-2]); print(res[-1])
    res.sort(key=lambda r: r['maeTune'])
    best = res[0]
    return {'base': {'maeTune': round(float(e0[tune].mean()), 4), 'maeHeld': round(float(e0[held].mean()), 4)},
            'best': best, 'passes': bool(best['tTune'] is not None and best['tTune'] <= -1.5 and best['maeHeld'] <= round(float(e0[held].mean()), 4)),
            'grid': res}


def main():
    games = list(N.rows(N.get('games.csv', N.GAMES)))
    bad = N.check_tiebreaks(games, range(2002, 2026))
    if '--check' in sys.argv:
        return
    F = json.load(open(N.FIT))
    G, box, qbs = N.load(2025)
    N.index_qbs(qbs, G); N.load_qb_teams(2025)
    inj = N.injury_history(G, range(N.INJ_FIRST, 2026))
    data, snaps = walk(G, box, qbs, F['params'], inj)
    B, D, X, y, S, line, pred = coefs(data)
    res = {'tiebreaks': {'seasons': '2002-25', 'mismatches': len(bad)}}
    if '--ratings' in sys.argv:
        r = ratings_test(G, D, X, y, S)
        print('ridge base', r['base'], 'best', r['best'], 'passes', r['passes'])
        old = json.load(open(OUT)) if os.path.exists(OUT) else {}
        old['ratingsTest'] = r
        with open(OUT, 'w') as f:
            json.dump(old, f, indent=1)
        return
    res['blendTest'] = blend_test(D, y, S, line, pred, F['sd'])
    print(json.dumps({k: v for k, v in res['blendTest'].items() if k != 'grid'}, indent=1))
    sc, facts = sim_test(G, data, snaps, B, F['sd'])
    cfgs = [('fixed', v) for v in FIXED] + [('shrink', s0, fl) for s0, fl in SHRINK]
    base = ('fixed', 2.5)
    tune, held = range(2015, 2021), range(2021, 2026)
    rows = []
    for c in cfgs:
        mt, ut = table(sc, facts, c, tune); mh, uh = table(sc, facts, c, held)
        rows.append((c, mt, mh, ut, uh))
    rows.sort(key=lambda r: r[1]['llAll'])
    bt, bh = table(sc, facts, base, tune)[1], table(sc, facts, base, held)[1]
    name = lambda c: f'fixed {c[1]}' if c[0] == 'fixed' else f'{c[1]} x sqrt(left), floor {c[2]}'
    grid = [{'cfg': name(c), 'tune': mt, 'held': mh, 'tTune': round(tstat(ut - bt), 2) if c != base else None,
             'tHeld': round(tstat(uh - bh), 2) if c != base else None} for c, mt, mh, ut, uh in rows]
    # each checkpoint's best fixed sd (tuning seasons), for the shape
    per = {}
    for wk in WEEKS:
        tot = {v: sum(float((sc[(s, wk, v)][0] + sc[(s, wk, v)][2] + sc[(s, wk, v)][4]).mean()) for s in tune) / len(tune) for v in SDS}
        per[f'week {wk}'] = {'left': round(float(np.mean([facts[(s, wk)] for s in tune])), 3), 'bestSd': min(tot, key=tot.get),
                             'llAll': {str(v): round(x, 4) for v, x in tot.items() if v in (0, 1, 2, 2.5, 3, 4, 5, 6)}}
    if os.path.exists(OUT):                    # keep the ratings test from its own run
        res = {**{k: v for k, v in json.load(open(OUT)).items() if k == 'ratingsTest'}, **res}
    res['simTest'] = {'sims': NS, 'weeks': WEEKS, 'units': 'team-seasons (sum of the checkpoints)', 'base': name(base),
                      'best': grid[0]['cfg'], 'grid': grid, 'byWeek': per}
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(json.dumps(per, indent=1))
    for r in grid[:12]:
        print(r)
    print('base', [r for r in grid if r['cfg'] == name(base)])


if __name__ == '__main__':
    main()
