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
