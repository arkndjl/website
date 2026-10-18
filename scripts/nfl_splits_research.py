#!/usr/bin/env python3
"""Situational splits, kickers and coach traits as NFL game-model inputs, on the walk-forward of
scripts/nfl_games_research.py (which tested the first round: success rates, 3rd-down rate, red zone, special teams
EPA, 4th-down aggressiveness, pass rate over expected and the rest).

    python3 scripts/nfl_splits_research.py      # writes data/nfl_splits_research.json (numpy; a few minutes)

New here: conversion rates by down and distance over what the league converts from the same distance (3rd and short,
medium, long; 4th downs; goal to go), opponent-adjusted and shrunk toward the league by a prior of k average games
(2, 6 or 12); the kicker (the team's most recent one) rated on field goals and extra points over the league's make
rate from the same distance, all distances and 50+ (range), in points; and coach traits: two-minute offense, tempo
(no-huddle rate), penalty yards, 2-point tries a touchdown. Interactions: the kicker in an expected close game and in
wind or cold, 4th-down conversion times the coach's 4th-down aggressiveness. Same rule as before: an input ships
only if it gains on 2015-20 at t <= -1.5 and the held-out 2021-25 gains too.
"""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N
import nfl_pbp as P
import nfl_splits as SP
from nfl_games_research import Rater

OUT = os.path.join(N.ROOT, 'data', 'nfl_splits_research.json')

# (numerator, denominator, name); numerators over expected subtract the league's rate from the same distance
RATIO = {
    'td3x':  (lambda A: A['t3c'] - A['t3x'], lambda A: A['t3n'], '3rd-down conversion over expected (by distance)'),
    'td3s':  (lambda A: A['t3sc'] - A['t3sx'], lambda A: A['t3sn'], '3rd and short (1-3) conversion over expected'),
    'td3m':  (lambda A: A['t3mc'] - A['t3mx'], lambda A: A['t3mn'], '3rd and medium (4-6) conversion over expected'),
    'td3mr': (lambda A: A['t3mc'], lambda A: A['t3mn'], '3rd and medium (4-6) conversion rate, raw'),
    'td3l':  (lambda A: A['t3lc'] - A['t3lx'], lambda A: A['t3ln'], '3rd and long (7+) conversion over expected'),
    'cv4':   (lambda A: A['f4c'], lambda A: A['f4n'], '4th-down conversion rate, raw'),
    'cv4x':  (lambda A: A['f4c'] - A['f4x'], lambda A: A['f4n'], '4th-down conversion over expected (by distance)'),
    'ldx':   (lambda A: A['t3c'] + A['f4c'] - A['t3x'] - A['f4x'], lambda A: A['t3n'] + A['f4n'], '3rd and 4th downs, conversion over expected'),
    'gtg':   (lambda A: A['gtc'], lambda A: A['gtn'], 'goal-to-go 3rd and 4th down conversion rate'),
    'twom':  (lambda A: A['twe'], lambda A: A['twn'], 'two-minute offense EPA a play (end of half, one-score 4th quarter)'),
}
OWN = {
    'nh':    (lambda A: A['nh'], lambda A: A['n'], 'tempo: no-huddle rate'),
    'pen':   (lambda A: A['pen'], lambda A: 1.0, 'penalty yards committed a game'),
    'go2':   (lambda A: A['two'], lambda A: A['td'], '2-point tries a touchdown'),
}


class KRater(Rater):
    """Rater with the prior set to k average games of the stat's denominator."""
    def __init__(self, *a, k=2.0, **kw):
        super().__init__(*a, **kw); self.k = k

    def r(self, side, t):
        v, w = side[t]
        w0 = self.k * self.lg[1] / self.games if self.games else 1.0
        return (v + self.L() * w0) / (w + w0)


def team_splits(games, SG, TG, params):
    a = 0.5 ** (1 / params['hl']); carry = params['carry']
    R = {}
    for k, (n, d, _) in RATIO.items():
        for kk in (2, 6, 12):
            R[f'{k}@{kk}'] = KRater(n, d, a, carry, k=kk)
    for k, (n, d, _) in OWN.items():
        R[k] = KRater(n, d, a, carry, adjust=False, k=6)
    ag = KRater(lambda A: A['f4go'] - A['f4x'], lambda A: A['f4n'], a, carry, adjust=False, k=6)   # 4th-down aggressiveness
    out, season = {}, None
    for g in games:
        s = int(g['season'])
        if s != season:
            for r in list(R.values()) + [ag]:
                r.new_season()
            season = s
        h, aw = N.team(g['home_team']), N.team(g['away_team'])
        x = {k: r.net(h) - r.net(aw) for k, r in R.items()}
        c4 = R['cv4x@6']
        x['cv4xAg'] = (c4.net(h) * max(0.0, ag.net(h)) - c4.net(aw) * max(0.0, ag.net(aw))) * 10
        out[g['game_id']] = x
        if g['home_score'] in ('', 'NA'):
            continue
        A, B = SG.get((g['game_id'], h)), SG.get((g['game_id'], aw))
        if A and B:
            for r in R.values():
                r.league(A); r.league(B); r.update(h, aw, A, B); r.update(aw, h, B, A)
        A2, B2 = TG.get((g['game_id'], h)), TG.get((g['game_id'], aw))
        if A2 and B2:
            ag.league(A2); ag.league(B2); ag.update(h, aw, A2, B2); ag.update(aw, h, B2, A2)
    return out


def kickers(games, K):
    """game_id -> kicker features (home minus away), from each team's most recent kicker before kickoff."""
    by = defaultdict(list)
    for kk in K:
        by[kk[0]].append(kk)
    # league make rate by 3-yard distance bin (field goals) and by season (extra points), from earlier seasons only
    lgF, lgX, cur = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    bins = lambda d: min(max(int(d) // 3, 6), 20)
    kv = defaultdict(lambda: [0.0, 0.0]); kr = defaultdict(lambda: [0.0, 0.0]); kx = defaultdict(lambda: [0.0, 0.0])
    last = {}; out = {}; season = None; xp_season = defaultdict(lambda: [0, 0])
    fga = defaultdict(lambda: [0.0, 0.0])          # team FG attempts a game, for the points scale
    def ef(d):
        b = bins(d); v = lgF[b] if lgF[b][0] >= 30 else cur[b]
        return (v[1] + 0.8 * 5) / (v[0] + 5) if v[0] else 0.8
    def ex(s):
        v = lgX[s] if lgX[s][0] >= 300 else xp_season[s]
        return v[1] / v[0] if v[0] else 0.94
    for g in games:
        s = int(g['season'])
        if s != season:
            if season is not None:
                for b, v in cur.items():
                    lgF[b][0] += v[0]; lgF[b][1] += v[1]
                lgX[s] = list(xp_season[season]) if season >= 2015 else [0, 0]
            cur = defaultdict(lambda: [0, 0])
            for d in (kv, kr, kx):
                for v in d.values():
                    v[0] *= 0.7; v[1] *= 0.7
            season = s
        h, aw = N.team(g['home_team']), N.team(g['away_team'])
        def val(t):
            k = last.get(t)
            if not k:
                return 0.0, 0.0, 0.0
            fg = kv[k][0] / (kv[k][1] + 30); rg = kr[k][0] / (kr[k][1] + 10); xp = kx[k][0] / (kx[k][1] + 40)
            return fg, rg, xp
        fh, rh, xh = val(h); fa, ra, xa = val(aw)
        out[g['game_id']] = {'kickFg': (fh - fa) * 3 * 1.7, 'kickRg': (rh - ra), 'kickXp': (xh - xa) * 2.3,
                             'kick': (fh - fa) * 3 * 1.7 + (xh - xa) * 2.3}
        for _, t, kid, kind, d, m in by.get(g['game_id'], []):
            if not kid or kid == 'NA':
                continue
            t = N.team(t); last[t] = kid
            if kind == 'fg':
                e = ef(d); kv[kid][0] += m - e; kv[kid][1] += 1
                if d >= 50:
                    kr[kid][0] += m - e; kr[kid][1] += 1
                cur[bins(d)][0] += 1; cur[bins(d)][1] += m
            elif s >= 2015:
                e = ex(s); kx[kid][0] += m - e; kx[kid][1] += 1
                xp_season[s][0] += 1; xp_season[s][1] += m
    return out


def main():
    import numpy as np
    last = 2025
    F = json.load(open(N.FIT)); params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    SG, TG, K = {}, {}, []
    for y in range(N.FIRST, last + 1):
        g_, k_ = SP.season(y); SG.update(g_); K.extend(k_); TG.update(P.season(y))
    _, data = N.walk(games, box, qbs, params)
    ts = team_splits(games, SG, TG, params)
    kk = kickers(games, K)
    D = []
    for g, x, tx in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        r = inj.get(g['game_id'])
        x = dict(x); x.update(ts[g['game_id']]); x.update(kk[g['game_id']])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        close = math.exp(-0.5 * ((x['mkt'] + 1.8 * x['home']) / 7) ** 2)
        outdoor = g['roof'] in ('outdoors', 'open')
        bad = 1.0 if outdoor and (N.num(g.get('wind'), 0) >= 12 or N.num(g.get('temp'), 60) <= 35) else 0.0
        x['kickClose'] = x['kick'] * close; x['kickWx'] = x['kick'] * bad; x['kickRgClose'] = x['kickRg'] * close
        D.append((g, x, tx))
    S = np.array([int(g['season']) for g, _, _ in D])
    y = np.array([N.num(g['result']) for g, _, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _, _ in D]); ok = ~np.isnan(line)
    A = (S >= 2015) & (S <= 2020) & ok; B = (S >= 2021) & ok
    win = np.where(y > 0, 1.0, np.where(y < 0, 0.0, 0.5)); sd = F['sd']
    from math import erf

    def wf(feats):
        X = np.array([[x[f] for f in feats] for _, x, _ in D])
        pred = np.full(len(y), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        p = np.clip(0.5 * (1 + np.vectorize(erf)(pred / sd / math.sqrt(2))), 1e-6, 1 - 1e-6)
        ll = -(win * np.log(p) + (1 - win) * np.log(1 - p))
        return np.abs(pred - y), ll, dict(zip(feats, b))

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return [round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)]

    base = list(N.FEATS)
    e0, l0, _ = wf(base)
    res = {'base': {'feats': base, 'mae1520': round(float(e0[A].mean()), 3), 'mae2125': round(float(e0[B].mean()), 3),
                    'll1520': round(float(l0[A].mean()), 4), 'll2125': round(float(l0[B].mean()), 4)}}
    names = {f'{k}@{kk}': f'{v[2]} (prior {kk} games)' for k, v in RATIO.items() for kk in (2, 6, 12)}
    names.update({k: v[2] for k, v in OWN.items()})
    names.update({'kick': 'kicker, field goals and extra points over expected (points a game)',
                  'kickFg': 'kicker, field goals over expected by distance (points a game)',
                  'kickXp': 'kicker, extra points over expected (points a game, 2015 on)',
                  'kickRg': 'kicker range: 50+ yard field goals over expected (a kick)',
                  'kickClose': 'kicker x expected close game', 'kickRgClose': 'kicker range x expected close game',
                  'kickWx': 'kicker x wind 12+ mph or 35F or colder, outdoors',
                  'cv4xAg': "4th-down conversion over expected x the coach's 4th-down aggressiveness"})
    alone = {}
    for k in names:
        e1, l1, b = wf(base + [k])
        alone[k] = {'name': names[k], 'mae1520': cmp(e1, e0, A), 'mae2125': cmp(e1, e0, B),
                    'll1520': cmp(l1, l0, A), 'll2125': cmp(l1, l0, B), 'coef': round(float(b[k]), 4)}
        print(k, alone[k], flush=True)
    chosen, cur, steps = [], e0, []
    while True:
        best = None
        for k in names:
            if k in chosen:
                continue
            e1, _, _ = wf(base + chosen + [k])
            d, t = cmp(e1, cur, A)
            if t <= -1.5 and (best is None or d < best[1]):
                best = (k, d, t, e1)
        if not best:
            break
        k, d, t, e1 = best
        hold = cmp(e1, cur, B)
        steps.append({'add': k, 'mae1520': [d, t], 'mae2125': hold, 'ships': hold[0] < 0})
        print('step', steps[-1], flush=True)
        chosen.append(k); cur = e1
    res.update({'alone': alone, 'steps': steps, 'ships': [s['add'] for s in steps if s['ships']]})
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
