#!/usr/bin/env python3
"""Tennis predictive badges (Noah, Nov 1 2026: "predictive badges like the ones we have in CFB"), shared by the two
tennis boards: scripts/tennis_model.py (TENNIS ARKBOARD rows) and scripts/tennis_prospects.py (prospects board).

A badge is one trait measured by one stat, regressed toward the tour pool's mean by volume (the CFB form,
scripts/cfb_badges.mjs): v' = m + (v - m) n / (n + k), k = n(1 - r) / r from the stat's year-to-year r at the mean
volume n. Tier = percentile of v' in the tour's pool (bronze 75th, silver 90th, gold 97th, platinum 99th). Only
badges that passed scripts/tennis_badge_backtest.py (data/tennis_badge_backtest.json: |t| >= 2 clustered by player,
positive, and a held-out gain beyond the board's own grade) are written; the backtest stores each one's k and the
volume floor, and the builds read them from there.
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.join(os.path.dirname(HERE), 'data', 'tennis_badge_backtest.json')
TIERS = ((99, 'p'), (97, 'g'), (90, 's'), (75, 'b'))
R_MIN = .15                 # year-to-year r below this: noise, never a badge


def regress(v, n, k):
    """v' toward the volume-weighted pool mean; v, n arrays (v NaN where unmeasured)"""
    v, n = np.asarray(v, float), np.asarray(n, float)
    ok = np.isfinite(v) & (n > 0)
    m = float(np.sum(v[ok] * n[ok]) / np.sum(n[ok])) if ok.any() else 0.0
    return np.where(ok, m + (v - m) * n / (n + k), np.nan)


def k_of(r, nbar):
    return float(nbar * (1 - r) / r) if r > 0 else float('inf')


def pct_in_pool(x, pool):
    """percentile (0-100) of each x within the pool values"""
    srt = np.sort(np.asarray(pool, float)[np.isfinite(pool)])
    if not len(srt):
        return np.full(len(x), np.nan)
    return 100.0 * np.searchsorted(srt, np.asarray(x, float), side='right') / len(srt)


def tier(p):
    for cut, t in TIERS:
        if p >= cut:
            return t
    return None


def passed(board, tour):
    """the badges that passed the backtest for a board ('pro' | 'prospects') and tour: [{key, name, stat, k, vmin}]"""
    try:
        B = json.load(open(BT))
    except (OSError, ValueError):
        return []
    return [dict(key=k, **{f: c[f] for f in ('name', 'stat', 'k', 'vmin')})
            for k, c in B.get(board, {}).get(tour, {}).get('badges', {}).items() if c.get('pass')]


def assign(vals, vols, defs, eligible):
    """vals / vols: {key: array}; defs: passed(); eligible: bool array (the pool: volume floors apply per badge).
    Returns one list per row: [[name, tier, pct, stat], ...] best first, bronze and up."""
    nrow = len(eligible)
    out = [[] for _ in range(nrow)]
    for d in defs:
        v, n = np.asarray(vals[d['key']], float), np.asarray(vols[d['key']], float)
        reg = regress(v, n, d['k'])
        pool = eligible & (n >= d['vmin']) & np.isfinite(reg)
        pc = pct_in_pool(reg, reg[pool])
        for i in np.nonzero(pool)[0]:
            p = float(pc[i])
            t = tier(p)
            if t:
                out[i].append([d['name'], t, int(min(99, np.floor(p))), d['stat']])
    order = {t: i for i, (_, t) in enumerate(TIERS)}
    for b in out:
        b.sort(key=lambda x: (order[x[1]], -x[2]))
    return out
