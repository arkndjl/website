#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA season sims: injury return times in the games left, and the playoff Elo term in series
(pre-registration: /mnt/project-files/nba-audit-nov13/prereg.md, family S).

    python3 scripts/nba_sim_research.py        # data/nba_sim_research.json (rows: scripts/.cache/nba/sim_research_rows.json)

S1: at 0, 1/4, 1/2, 3/4 of each regular season 2016-26 the live rating (nba_games_build.season_views: every player at
his no-report chance to play given his missed streak, held for every game left) against a rating per horizon band,
each player's chance = the share of players with his streak who played k team games later (seasons before, minutes
weighted). Expected wins left against actual. S2: playoff series win chance at each series' first game, the sims'
rating difference with and without the game model's playoff Elo term. Walk-forward coefficients throughout.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as NF

OUT = os.path.join(N.ROOT, 'data', 'nba_sim_research.json')
BANDS = ((5, 3), (15, 10), (30, 22), (999, 45))      # (games ahead up to, offset measured)
SSD = json.load(open(os.path.join(N.ROOT, 'data', 'nba_season_sd.json')))


def band(j):
    return next(i for i, (hi, _) in enumerate(BANDS) if j <= hi)


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def lineup(m, t, prob):
    """Model.lineup with no report and each player's chance from prob(pid)"""
    exp = []
    for p in m.roster(t):
        mn, w = m.role[p]
        if w > 0:
            exp.append((p, mn / w * prob(p)))
    tot = sum(e for _, e in exp)
    sc = 240.0 / tot if tot > 240 else 1.0
    V = sum(m.v(p) * e * sc for p, e in exp) / 48
    return V + (N.REPL * (240 - tot * sc) / 48 if tot * sc < 240 else 0.0)


def ratings(m, b, teams, prob=None):
    Lp = m.lgp[0] / m.lgp[1]
    net = lambda t: m.rate(m.off, t) - m.rate(m.dfn, t)
    mk = sum(m.mkt[t] for t in teams) / len(teams)
    R = {}
    for t in teams:
        V = m.lineup(t) if prob is None else lineup(m, t, prob)
        R[t] = (b.get('elo', 0) * (m.elo[t] - 1505) / 28 + b.get('eff', 0) * net(t) * (Lp + m.rate(m.pace, t)) / 100
                + b.get('mkt', 0) * (m.mkt[t] - mk) + b.get('lin', 0) * (V - m.rate(m.base, t, 1.0)))
    avg = sum(R.values()) / len(R)
    return {t: v - avg for t, v in R.items()}


def series_p(mu_home, mu_road, sd, rsd):
    """P(the game-1 home team wins a best of seven, 2-2-1-1-1), a rating shock difference ~ N(0, 2 rsd^2) held for the series"""
    zs, ws = np.polynomial.hermite_e.hermegauss(15)
    tot = 0.0
    for z, w in zip(zs, ws):
        sh = z * rsd * math.sqrt(2)
        ph, pr = phi((mu_home + sh) / sd), phi((mu_road + sh) / sd)
        st = {(0, 0): 1.0}
        win = 0.0
        for i in range(7):
            p = ph if i in (0, 1, 4, 6) else pr
            nx = defaultdict(float)
            for (a, c), q in st.items():
                if a + 1 == 4: win += q * p
                else: nx[(a + 1, c)] += q * p
                if c + 1 < 4: nx[(a, c + 1)] += q * (1 - p)
            st = nx
        tot += w * win
    return tot / ws.sum()


def pt(d):
    d = np.asarray(d, float)
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0


def main():
    F = json.load(open(N.FIT))
    feats, params = F['feats'], F['params']
    games, names = N.load_hist()
    inj = NF.load_inj()
    _, _, PT = NF.measure_P(games, names, inj, {k: v for k, v in params.items() if k != 'b2b'})
    # walk-forward coefficients and win sd by season
    D, X, TX, y, ty, S, line, tline = NF.design(games, names, PT, params, inj, feats)
    Xm = NF.mat(X, feats)
    coef, sdw = {}, {}
    pred = NF.wf(Xm, y, S)
    for s in range(2016, int(S.max()) + 1):
        coef[s] = dict(zip(feats, np.linalg.lstsq(Xm[S < s], y[S < s], rcond=None)[0]))
        k = (S < s) & (S >= max(2015, s - 3)) & ~np.isnan(pred)
        sdw[s] = float(np.std((pred - y)[k]))
    by = defaultdict(list)
    for i, g in enumerate(games):
        by[g['S']].append(i)
    reg = {s: [i for i in ix if games[i]['t'] == 2] for s, ix in by.items()}
    cps = {}
    for s in range(2016, 2027):
        n = len(reg[s])
        for q in range(4):
            cps[reg[s][n * q // 4]] = (s, q)
    teams_of = {s: sorted({games[i]['h'] for i in reg[s]} | {games[i]['a'] for i in reg[s]}) for s in reg}
    m = N.Model(names, PT, inj=inj, **params)
    hz = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))      # season -> (bucket, band) -> [role minutes played later, role minutes]
    snaps = defaultdict(list)                                        # (S, team) -> [(pre-game [(pid, R, bucket)], played set)]
    rows, ser, seen = [], [], set()
    for i, g in enumerate(games):
        s = g['S']
        if i in cps:
            if m.season != s:
                m.new_season(s)
            if hasattr(PT, 'at'):
                PT.at(g)
            b, teams, q = coef[s], teams_of[s], cps[i][1]
            H = defaultdict(lambda: [0.0, 0.0])
            for s0, d in hz.items():
                if s0 < s:
                    for k, v in d.items():
                        H[k][0] += v[0]; H[k][1] += v[1]
            left = [games[j] for j in reg[s] if j >= i]
            rsd = math.sqrt(SSD['a'] + SSD['b'] * min(1.0, len(left) / 1230))
            den = math.sqrt(sdw[s] ** 2 + 2 * rsd ** 2)
            R0 = ratings(m, b, teams)
            Rk = [ratings(m, b, teams, lambda p, kb=kb: (H[(N.bucket(m.streak[p]), kb)][0] / H[(N.bucket(m.streak[p]), kb)][1]) if H[(N.bucket(m.streak[p]), kb)][1] > 0 else 0.9)
                  for kb in range(len(BANDS))]
            e0, e1, act, cnt = defaultdict(float), defaultdict(float), defaultdict(int), defaultdict(int)
            for gg in left:
                h, a = gg['h'], gg['a']
                cnt[h] += 1; cnt[a] += 1
                hf = 0.0 if gg['n'] else b['home']
                p0 = phi((R0[h] - R0[a] + hf) / den)
                p1 = phi((Rk[band(cnt[h])][h] - Rk[band(cnt[a])][a] + hf) / den)
                e0[h] += p0; e0[a] += 1 - p0; e1[h] += p1; e1[a] += 1 - p1
                act[h if gg['hs'] > gg['as'] else a] += 1
            for t in teams:
                rows.append((s, q, t, e0[t], e1[t], act[t], cnt[t]))
        x, tx = m.feats(g)
        if g['t'] == 2 and g.get('pl'):
            for t in (g['h'], g['a']):
                pre = [(p, m.role[p][0] / m.role[p][1], N.bucket(m.streak[p])) for p in m.roster(t) if m.role[p][1] > 0 and m.role[p][0] / m.role[p][1] >= 8]
                snaps[(s, t)].append((pre, {p for p, mn in (g['pl'].get(t) or []) if mn > 0}))
        if g['t'] == 3 and s >= 2016 and (s, frozenset((g['h'], g['a']))) not in seen:
            seen.add((s, frozenset((g['h'], g['a']))))
            b = coef[s]
            R0 = ratings(m, b, teams_of[s])
            hi, lo = g['h'], g['a']
            hf = 0.0 if g['n'] else b['home']
            d0 = R0[hi] - R0[lo]
            d1 = d0 + b.get('eloPo', 0.0) * (m.elo[hi] - m.elo[lo]) / 28
            rsd = math.sqrt(SSD['a'])
            ser.append([s, hi, lo, series_p(d0 + hf, d0 - hf, sdw[s], rsd), series_p(d1 + hf, d1 - hf, sdw[s], rsd), None])
        m.update(g)
    # hazard table from the snapshots (after the walk; each checkpoint above only read seasons before its own)
        if i == by[s][-1]:
            for (s0, t), lst in list(snaps.items()):
                for n, (pre, _) in enumerate(lst):
                    for kb, (_, off) in enumerate(BANDS):
                        if n + off < len(lst):
                            on = lst[n + off][1]
                            for p, R, bk in pre:
                                a_ = hz[s0][(bk, kb)]
                                a_[0] += R * (p in on); a_[1] += R
                del snaps[(s0, t)]
    # series results
    wins = defaultdict(lambda: defaultdict(int))
    for g in games:
        if g['t'] == 3 and g['S'] >= 2016:
            wins[(g['S'], frozenset((g['h'], g['a'])))][g['h'] if g['hs'] > g['as'] else g['a']] += 1
    ser = [r[:5] + [1.0 if wins[(r[0], frozenset((r[1], r[2])))][r[1]] > wins[(r[0], frozenset((r[1], r[2])))][r[2]] else 0.0] for r in ser
           if max(wins[(r[0], frozenset((r[1], r[2])))].values()) >= 3]
    R = np.array([(r[0], r[1], r[3], r[4], r[5], r[6]) for r in rows], float)
    out = {'prereg': '/mnt/project-files/nba-audit-nov13/prereg.md', 'S1': {}, 'S2': {}}
    Hall = defaultdict(lambda: [0.0, 0.0])
    for d in hz.values():
        for k, v in d.items():
            Hall[k][0] += v[0]; Hall[k][1] += v[1]
    out['hazard'] = {f'streak{bk}': [round(Hall[(bk, kb)][0] / Hall[(bk, kb)][1], 3) if Hall[(bk, kb)][1] else None for kb in range(len(BANDS))] for bk in range(5)}
    print('hazard (share playing 3, 10, 22, 45 team games later by streak bucket)', out['hazard'])
    d = np.abs(R[:, 3] - R[:, 4]) - np.abs(R[:, 2] - R[:, 4])
    for nm, k in [('all', R[:, 1] >= 0)] + [(f'q{q}', R[:, 1] == q) for q in range(4)]:
        se = [d[k & (R[:, 0] == s)].mean() for s in range(2016, 2027)]
        out['S1'][nm] = {'n': int(k.sum()), 'maeBase': round(float(np.abs(R[k, 2] - R[k, 4]).mean()), 3), 'maeNew': round(float(np.abs(R[k, 3] - R[k, 4]).mean()), 3),
                         't_season': round(pt(se), 2), 'seasonsBetter': int(sum(x < 0 for x in se)), 't_rows': round(pt(d[k]), 2)}
        print('S1', nm, out['S1'][nm])
    ll = lambda p, w: -math.log(max(1e-9, p if w else 1 - p))
    l0 = np.array([ll(r[3], r[5]) for r in ser]); l1 = np.array([ll(r[4], r[5]) for r in ser]); ss = np.array([r[0] for r in ser])
    se = [(l1 - l0)[ss == s].mean() for s in range(2016, 2027)]
    out['S2'] = {'n': len(ser), 'llBase': round(float(l0.mean()), 4), 'llNew': round(float(l1.mean()), 4), 't': round(pt(l1 - l0), 2),
                 'seasonsBetter': int(sum(x < 0 for x in se)), 't_season': round(pt(se), 2),
                 'favWinBase': round(float(np.mean([(r[3] > .5) == (r[5] == 1) for r in ser])), 3), 'meanPfav': [round(float(np.mean([max(r[3], 1 - r[3]) for r in ser])), 3), round(float(np.mean([max(r[4], 1 - r[4]) for r in ser])), 3)]}
    print('S2', out['S2'])
    out['rows'] = [[int(r[0]), int(r[1]), r[2], round(r[3], 3), round(r[4], 3), int(r[5]), int(r[6])] for r in rows]
    out['series'] = [[r[0], r[1], r[2], round(r[3], 4), round(r[4], 4), int(r[5])] for r in ser]
    # the per-team and per-series rows stay out of data/ (Hugo loads every file there)
    os.makedirs(os.path.join(N.ROOT, 'scripts', '.cache', 'nba'), exist_ok=True)
    with open(os.path.join(N.ROOT, 'scripts', '.cache', 'nba', 'sim_research_rows.json'), 'w') as f:
        json.dump({'rows': out.pop('rows'), 'series': out.pop('series')}, f)
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
