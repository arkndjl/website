#!/usr/bin/env python3
"""Predictive trait badges for the soccer player board (scripts/soccer_players.py), the CFB board's medals
(scripts/cfb_badges.mjs) in soccer terms. A badge is one trait measured by one stat a 90, relative to the league-season
mean at his position, regressed toward that mean by minutes: v' = m + (v - m) n / (n + k), k = n(1 - r) / r from the
stat's season-to-season r at the mean minutes of players with 900+ in both seasons. Tier = percentile of v' among his
position's players with 900+ minutes that season (every big-five league together): bronze 75th, silver 90th, gold 97th,
platinum 99th.

Only badges that predicted next season's GAR a 90 beyond this season's (and last season's, minutes, age) ship; the
test and every candidate's numbers are in scripts/soccer_badge_backtest.py / data/soccer_badge_backtest.json. The
candidate list lives here so the backtest and the board measure the same thing.
"""
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MIN_POOL = 900
TIERS = [(99, 'p'), (97, 'g'), (90, 's'), (75, 'b')]

# id -> (badge name, positions, label for the tooltip, stat a 90 from a player-season line)
CANDS = {
    'fin': ('Finisher', 'FM', 'goals minus xG a 90', lambda a: (a['g'] - a['x'])),
    'vol': ('Shot Volume', 'FM', 'shots a 90', lambda a: a['sh']),
    'cre': ('xA Creator', 'FMD', 'xA a 90', lambda a: a['xA']),
    'kp': ('Chance Creator', 'FMD', 'key passes a 90', lambda a: a['kp']),
    'prg': ('Progressor', 'MD', 'xGBuildup a 90', lambda a: a['bu']),
    'chn': ('Final Third', 'FM', 'xGChain minus xGBuildup a 90', lambda a: a['ch'] - a['bu']),
    'gks': ('Shot Stopper', 'G', 'goals saved vs xG faced a 90', lambda a: a['gks']),
}

# shipped (data/soccer_badge_backtest.json 'pro', Nov 1 2026): candidate -> (positions it passed at, k in 90s). Each
# passed alone (clustered t >= 2, leave-one-season-out gain, a majority of seasons) and kept t >= 2 in the forward
# joint set: F key passes + shots; M key passes + xGBuildup + shots; D xGBuildup + key passes. xA (r .83-.88 with key
# passes) and FotMob dribbles passed alone and fell out jointly; finishing (r .07) and keeper shot stopping (r .11)
# are noise season to season; FotMob tackles + interceptions, defensive actions and goals prevented failed
SHIP = {'kp': ('FMD', 7.4), 'prg': ('MD', 10.9), 'vol': ('FM', 7.7)}


def agg_seasons(rows):
    """(Understat player id, season) -> one line over his clubs and leagues that season: minutes, raw totals, his
    main position and league (the club where he played most)"""
    out = {}
    for r in sorted(rows, key=lambda r: -r['min']):
        k = (r['p'], r['S'])
        a = out.get(k)
        if a is None:
            a = out[k] = {'p': r['p'], 'S': r['S'], 'n': r['n'], 'pos': r['pos'], 'lg': r['lg'], 'team': r['team'], 'min': 0,
                          'teams': []}
            for s in ('g', 'x', 'pen', 'xA', 'kp', 'bu', 'ch', 'sh', 'gks'):
                a[s] = 0.0
        a['min'] += r['min']
        a['teams'].append((r['lg'], r['team'], r['min']))
        for s in ('g', 'x', 'pen', 'xA', 'kp', 'bu', 'ch', 'sh', 'gks'):
            a[s] += r.get(s, 0) or 0
    return out


def per90(a, fn):
    return fn(a) / max(a['min'], 1) * 90


PG = {'GK': 'G', 'D': 'D', 'M': 'M', 'F': 'F'}


def regress(lines, cid, k):
    """v' (regressed, relative to the league-season mean at his position) for every line with 90+ minutes"""
    fn = CANDS[cid][3]
    grp = defaultdict(list)
    for a in lines:
        if a['min'] >= 90:
            grp[(a['lg'], a['S'], a['pos'])].append(a)
    out = {}
    for g, L in grp.items():
        tot = sum(a['min'] for a in L) or 1
        mu = sum(per90(a, fn) * a['min'] for a in L) / tot
        for a in L:
            n = a['min'] / 90
            out[(a['p'], a['S'])] = (per90(a, fn) - mu) * n / (n + k)
    return out


def tier(pct):
    for c, t in TIERS:
        if pct >= c:
            return t
    return None


def pctiles(lines, vals, S, minpool=MIN_POOL):
    """position pool (minpool+ minutes, season S, every league) -> percentile of each line's v' (0-99)"""
    import bisect
    pool = defaultdict(list)
    for a in lines:
        if a['S'] == S and a['min'] >= minpool and (a['p'], S) in vals:
            pool[a['pos']].append(vals[(a['p'], S)])
    srt = {k: sorted(v) for k, v in pool.items()}
    out = {}
    for a in lines:
        if a['S'] != S or (a['p'], S) not in vals:
            continue
        L = srt.get(a['pos']) or []
        if len(L) < 20:
            continue
        v = vals[(a['p'], S)]
        out[a['p']] = min(99, int(100 * bisect.bisect_left(L, v) / len(L)))
    return out


def badges(rows, S, minpool=MIN_POOL):
    """Understat player id -> [[name, tier, pct, stat label], ...] best first, for season S, the shipped badges only.
    minpool: the minutes for the position pool and for a badge (900; this season scaled to the matches played)"""
    lines = list(agg_seasons(rows).values())
    out = defaultdict(list)
    for cid, (pos, k) in SHIP.items():
        name, _, lab, _ = CANDS[cid]
        vals = regress(lines, cid, k)
        pc = pctiles(lines, vals, S, minpool)
        for a in lines:
            if a['S'] != S or PG[a['pos']] not in pos or a['min'] < minpool or a['p'] not in pc:
                continue
            t = tier(pc[a['p']])
            if t:
                out[a['p']].append([name, t, pc[a['p']], lab])
    for p in out:
        out[p].sort(key=lambda b: -b[2])
    return dict(out)


# ---------------------------------------------------------------- prospect board (scripts/soccer_prospects.py)
# Shipped (data/soccer_badge_backtest.json 'prospects', Nov 1 2026): candidate -> (position groups, k in 90s). Senior
# assists a 90 for defenders predicted outcome FV beyond the board's FV drivers (cohort-out, t 2.50 clustered, 7 of 10
# cohorts; 2.23 with a full-back dummy). Goals a 90 (F t -.56, M .33), assists for F (1.37) and M (1.41), and a keeper's
# goals conceded a 90 (1.91) failed.
P_SHIP = {'cre': ('D', 25.1)}
P_NAMES = {'cre': ('Chance Creator', 'assists a 90, senior, last season + this one'),
           'fin': ('Finisher', 'goals a 90, senior, last season + this one')}


def prospect_vals(X, cid, k):
    """v' for a prospect row (0 for rows without senior minutes: at the mean): b_<cid> senior count over b_min
    minutes, relative to his main league's mean at the position group (the group's mean where a league has under 300
    90s in the pool)"""
    import numpy as np
    import pandas as pd
    mn = 'b_gmin' if cid == 'gks' else 'b_min'
    n90 = X[mn].values / 90
    rate = np.where(n90 > 0, X['b_' + cid].values / np.maximum(n90, 1e-9), np.nan)
    grp = X.grp.values
    comp = X.comp_td.where(X.comp_td.notna(), X.comp1).fillna('none').values
    df = pd.DataFrame({'g': grp, 'c': comp, 'v': rate, 'n': n90})
    ok = (df.v.notna() & (df.n >= 3)).values
    d = df[ok].assign(w=lambda d: d.v * d.n)
    mu = d.groupby(['g', 'c']).agg(w=('w', 'sum'), n=('n', 'sum'))
    mug = d.groupby('g').agg(w=('w', 'sum'), n=('n', 'sum'))
    cm = (mu.w / mu.n).where(mu.n >= 300).to_dict()
    gm = (mug.w / mug.n).to_dict()
    mm = np.array([cm.get((g_, c_), np.nan) for g_, c_ in zip(grp, comp)])
    mm = np.where(np.isnan(mm), [gm.get(g_, 0.0) for g_ in grp], mm)
    return np.where(ok, (rate - mm) * n90 / (n90 + k), 0.0)


def prospect_badges(X, minpool=MIN_POOL):
    """prospect board rows (soccer_prospects.features) -> {row index: [[name, tier, pct, stat], ...]}: the shipped
    badges, percentile among the position group's prospects with minpool+ senior minutes last season + this one"""
    import numpy as np
    z = lambda c: X[c].fillna(0).values.astype(float) if c in X else np.zeros(len(X))
    X = X.assign(b_min=z('mins1') + z('mins_td'), b_cre=z('ast1') + z('ast_td'), b_fin=z('gl1') + z('gl_td'))
    out = defaultdict(list)
    for cid, (pos, k) in P_SHIP.items():
        v = prospect_vals(X, cid, k)
        for g in pos:
            pool = (X.grp.values == g) & (X.b_min.values >= minpool)
            L = np.sort(v[pool])
            if len(L) < 20:
                continue
            for i in np.flatnonzero(pool):
                t = tier(min(99, int(100 * np.searchsorted(L, v[i], 'left') / len(L))))
                if t:
                    out[X.index[i]].append([P_NAMES[cid][0], t, min(99, int(100 * np.searchsorted(L, v[i], 'left') / len(L))), P_NAMES[cid][1]])
    for i in out:
        out[i].sort(key=lambda b: -b[2])
    return dict(out)
