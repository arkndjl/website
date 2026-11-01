#!/usr/bin/env python3
"""Player badges for the College Basketball ARKBOARD (the football board's medals, scripts/cfb_badges.mjs).

A badge is one trait measured by one Barttorvik stat (or a z-composite of two) on the player's last college season,
the season his preseason grade is built from. Each stat is regressed toward the role family's mean by volume,
v' = m + (v - m) * n / (n + k), with k = n (1 - r) / r from the year-to-year r at the pairs' mean volume n (measured by
scripts/cbb_badge_backtest.py on Barttorvik 2008-26, back-to-back seasons with 300+ minutes; the r is in each
comment). Stats under r .15 are dropped as noise. The tier is the percentile of v' among the board's returners of the
same role family (guards, wings, bigs: Barttorvik's role) who played 300+ minutes: bronze 75th, silver 90th, gold
97th, platinum 99th.

Only badges that predicted NBA value beyond the board's FV held out are listed in SHIP (scripts/cbb_badge_backtest.py,
data/cbb_badge_backtest.json); CANDIDATES holds everything tested.
"""
import math

ROLES = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'W', 'Wing F': 'W', 'Stretch 4': 'B', 'PF/C': 'B', 'C': 'B'}
TIERS = [('p', 0.99), ('g', 0.97), ('s', 0.90), ('b', 0.75)]
PTS = {'p': 4, 'g': 3, 's': 2, 'b': 1}
MIN_MPT = 300          # minutes in the season to be in the pool (and to hold a badge)


def mpt(r): return (r.get('mp') or 0) * (r.get('gp') or 0)


# stat parts: key -> (value, volume). Higher is better (turnover rate enters negated).
PARTS = {
    'tp': (lambda r: r.get('tp'), lambda r: r.get('tpa') or 0),
    'tpa100': (lambda r: r.get('tpa100'), mpt),
    'ft': (lambda r: r.get('ft'), lambda r: r.get('fta') or 0),
    'ast': (lambda r: r.get('ast'), mpt),
    'stl': (lambda r: r.get('stl'), mpt),
    'blk': (lambda r: r.get('blk'), mpt),
    'drb': (lambda r: r.get('drb'), mpt),
    'orb': (lambda r: r.get('orb'), mpt),
    'rim': (lambda r: r.get('rim'), lambda r: r.get('rima') or 0),
    'nto': (lambda r: -r['to'] if r.get('to') is not None else None, mpt),
}
# k per part (minutes, or attempts for 3P%, FT% and rim FG%) = n (1 - r) / r, from scripts/cbb_badge_backtest.py:
# 3P% r .39 at 77 3PA, 3PA rate .87, FT% .49 at 75 FTA, assist rate .72, steal rate .62, block rate .80, DREB .66,
# OREB .75, turnover rate .60, rim FG% .30 at 76 rim attempts (minutes: 740 a season). None under .15
K = {'tp': 121, 'tpa100': 115, 'ft': 78, 'ast': 293, 'stl': 449, 'blk': 182, 'drb': 379, 'orb': 244, 'rim': 181, 'nto': 502}

# key -> (name, parts, label, FV driver already?) ; the FV model already reads ast, stl, blk, rim (and ftr, not a badge)
CANDIDATES = {
    'shooter': ('Shooter', ['tp', 'tpa100'], '3P% and 3PA rate', False),
    'ft': ('FT Touch', ['ft'], 'FT%', False),
    'playmaker': ('Playmaker', ['ast'], 'assist rate', True),
    'ballhawk': ('Ball Hawk', ['stl'], 'steal rate', True),
    'rimprot': ('Rim Protector', ['blk'], 'block rate', True),
    'rebounder': ('Rebounder', ['drb'], 'defensive rebounding', False),
    'glass': ('Offensive Glass', ['orb'], 'offensive rebounding', False),
    'finisher': ('Finisher', ['rim'], 'FG% at the rim', True),
    'secure': ('Ball Security', ['nto'], 'turnover rate', False),
}
GROUPS = {
    'G': ['shooter', 'ft', 'playmaker', 'ballhawk', 'secure', 'finisher'],
    'W': ['shooter', 'ft', 'playmaker', 'ballhawk', 'rimprot', 'rebounder', 'finisher'],
    'B': ['rimprot', 'rebounder', 'glass', 'finisher', 'shooter', 'ft', 'playmaker'],
}
# passed (Nov 1 2026, data/cbb_badge_backtest.json): bigs' FT Touch only (t 3.0 clustered by player, leave-one-season-out
# R^2 +.66 pts, held-out 2017-19 boards +.39). Big Shooter passed alone but not next to FT Touch (same touch, t 1.55);
# big Rebounder passed in sample but lost on the 2017-19 boards. Shown only: as a driver in the FV ladder it doesn't
# lower out-of-fold deviance (-.03), so FV doesn't read it
SHIP = {'B': ['ft']}


def regress(lines, part, k=None):
    """v' for each line (None where the stat is missing): toward the volume-weighted mean of the pool lines."""
    val, vol = PARTS[part]
    k = K[part] if k is None else k
    pool = [(val(r), vol(r)) for r in lines if mpt(r) >= MIN_MPT and val(r) is not None]
    nw = sum(n for _, n in pool)
    m = sum(v * n for v, n in pool) / nw if nw else 0.0
    out = []
    for r in lines:
        v, n = val(r), max(0.0, vol(r))
        out.append(None if v is None else m + (v - m) * n / (n + k))
    return out


def scores(lines, key, k=None):
    """the badge's score per line: one part regressed, or the mean z of its parts (z within the pool)."""
    _, parts, _, _ = CANDIDATES[key]
    pool = [mpt(r) >= MIN_MPT for r in lines]
    zs = []
    for p in parts:
        v = regress(lines, p, None if k is None else k.get(p))
        pv = [x for x, ok in zip(v, pool) if ok and x is not None]
        if len(pv) < 2: return [None] * len(lines)
        mu = sum(pv) / len(pv); sd = math.sqrt(sum((x - mu) ** 2 for x in pv) / len(pv)) or 1
        zs.append([None if x is None else (x - mu) / sd for x in v])
    return [None if any(z[i] is None for z in zs) else sum(z[i] for z in zs) / len(zs) for i in range(len(lines))]


def tiers(lines, key, k=None):
    """(tier letter or None, percentile 0-100) per line, within the pool (lines with MIN_MPT minutes)."""
    s = scores(lines, key, k)
    pool = sorted(x for x, r in zip(s, lines) if x is not None and mpt(r) >= MIN_MPT)
    out = []
    for x, r in zip(s, lines):
        if x is None or not pool or mpt(r) < MIN_MPT: out.append((None, None)); continue
        lo = sum(1 for y in pool if y < x); eq = sum(1 for y in pool if y == x)
        pct = (lo + 0.5 * eq) / len(pool)
        t = next((t for t, q in TIERS if pct >= q), None)
        out.append((t, pct))
    return out


def board_badges(lines, groups, ship=None):
    """bdg per line for the board: [[name, tier, pct, stat], ...] best first, shipped badges at bronze or better.
    lines: each player's last college season (dict of Barttorvik columns), groups: his role family (G/W/B)."""
    ship = SHIP if ship is None else ship
    out = [[] for _ in lines]
    for g, keys in ship.items():
        ix = [i for i, x in enumerate(groups) if x == g]
        sub = [lines[i] for i in ix]
        for key in keys:
            name, _, label, _ = CANDIDATES[key]
            for i, (t, pct) in zip(ix, tiers(sub, key)):
                if t: out[i].append([name, t, min(99, int(pct * 100)), label])
    for b in out: b.sort(key=lambda x: (-PTS[x[1]], -x[2]))
    return out


def prior_badges(prior):
    """bdg per row of the frozen preseason board (scripts/cbb_prior.json.gz): returners only, from their last college
    season (the one their preseason grade reads); the pool is the board's returners in the same role family."""
    keep = prior['keep']
    lines, groups, at = [], [], []
    for j, m in enumerate(prior['careers']):
        past = [s for s in (dict(zip(keep, x)) for x in m['seasons']) if s.get('gp')]
        if not past: continue
        lines.append(past[-1]); groups.append(ROLES.get(past[-1].get('role'), 'W')); at.append(j)
    out = [None] * len(prior['careers'])
    for j, b in zip(at, board_badges(lines, groups)):
        if b: out[j] = b
    return out
