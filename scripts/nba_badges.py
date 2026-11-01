#!/usr/bin/env python3
"""Predictive trait badges for the NBA ARKBOARD's XPM board (the CFB board's medals, scripts/cfb_badges.mjs).

A badge is one trait measured by one rate on Basketball-Reference's season line (the advanced table nba_xpm.py already
reads, plus the totals table for shooting). Each rate is regressed toward the position mean by its volume,
v' = m + (v - m) x n / (n + k), k = n (1 - r) / r from the year-to-year r at the pairs' mean volume n (2010-26, 500+ MP
both seasons). Rates with r < .15 are dropped as noise. Tier = percentile of v' among the position's players with 500+
MP (pro-rated to the games played so far in season): bronze 75th, silver 90th, gold 97th, platinum 99th. Positions:
guards (PG, SG), forwards (SF, PF), centers.

Only the badges that passed scripts/nba_badge_backtest.py ship (next season's XPM on this season's shrunk XPM, minutes
and age; partial t clustered by player >= 2, positive, and a leave-one-season-out gain). The list and k come from
data/nba_badge_backtest.json, so a rerun of the backtest changes what the board shows. Stdlib only.
"""
import html
import json
import math
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
BT = os.path.join(ROOT, 'data', 'nba_badge_backtest.json')
MIN_MP = 500
TIERS = [('p', 0.99), ('g', 0.97), ('s', 0.90), ('b', 0.75)]
GRP = {'PG': 'G', 'SG': 'G', 'G': 'G', 'SF': 'F', 'PF': 'F', 'F': 'F', 'GF': 'F', 'C': 'C', 'FC': 'C'}


def _per(a, b):
    return (a / b, b) if a is not None and b else (None, 0)


def _g(s, k):
    v = s.get(k)
    return v if isinstance(v, (int, float)) else None


# [key, name, groups, rate fn(stats) -> (value up = good, volume), label]
BADGES = [
    ('shooter', 'Shooter', ('G', 'F', 'C'), lambda s: _per(_g(s, 'fg3'), _g(s, 'fg3a')), '3-point %'),
    ('spacer', 'Floor Spacer', ('G', 'F', 'C'), lambda s: (_per(_g(s, 'fg3a'), _g(s, 'mp'))[0], _g(s, 'mp') or 0), '3-point attempts a minute'),
    ('touch', 'Touch', ('G', 'F', 'C'), lambda s: _per(_g(s, 'ft'), _g(s, 'fta')), 'free throw %'),
    ('scorer', 'Efficient Scorer', ('G', 'F', 'C'), lambda s: (_g(s, 'ts_pct'), (_g(s, 'fga') or 0) + .44 * (_g(s, 'fta') or 0)), 'true shooting %'),
    ('creator', 'Shot Creator', ('G', 'F', 'C'), lambda s: (_g(s, 'usg_pct'), _g(s, 'mp') or 0), 'usage %'),
    ('foul', 'Foul Drawer', ('G', 'F', 'C'), lambda s: _per(_g(s, 'fta'), _g(s, 'fga')), 'free throws a shot'),
    ('playmaker', 'Playmaker', ('G', 'F', 'C'), lambda s: (_g(s, 'ast_pct'), _g(s, 'mp') or 0), 'assist %'),
    ('secure', 'Ball Security', ('G', 'F', 'C'), lambda s: (None if _g(s, 'tov_pct') is None else -s['tov_pct'], _g(s, 'mp') or 0), 'turnover % (lower)'),
    ('rim', 'Rim Protector', ('G', 'F', 'C'), lambda s: (_g(s, 'blk_pct'), _g(s, 'mp') or 0), 'block %'),
    ('thief', 'Disruptor', ('G', 'F', 'C'), lambda s: (_g(s, 'stl_pct'), _g(s, 'mp') or 0), 'steal %'),
    ('board', 'Rebounder', ('G', 'F', 'C'), lambda s: (_g(s, 'drb_pct'), _g(s, 'mp') or 0), 'defensive rebound %'),
    ('oboard', 'Offensive Rebounder', ('G', 'F', 'C'), lambda s: (_g(s, 'orb_pct'), _g(s, 'mp') or 0), 'offensive rebound %'),
]
BY_KEY = {b[0]: b for b in BADGES}
ADV = ['ts_pct', 'orb_pct', 'drb_pct', 'ast_pct', 'stl_pct', 'blk_pct', 'tov_pct', 'usg_pct']
TOT = ['fg3', 'fg3a', 'ft', 'fta', 'fga']


def _cell(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse(h, table, fields):
    """{bbref id: {field: value, mp, pos}} from one bbref season table, the TOT row for traded players (the first row)"""
    tb = re.search(r'<table[^>]*id="' + table + r'"[^>]*>(.*?)</table>', h or '', re.S)
    out = {}
    if not tb:
        return out
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb.group(1), re.S):
        c = dict(re.findall(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', tr, re.S))
        m = re.search(r'/players/\w/(\w+)\.html', c.get('name_display', c.get('player', '')) or '')
        if not m or m.group(1) in out:
            continue
        r = {f: _num(_cell(c.get(f, ''))) for f in fields}
        r['mp'] = _num(_cell(c.get('mp', '')))
        r['pos'] = _cell(c.get('pos', '')).split('-')[0]
        out[m.group(1)] = r
    return out


def season_stats(adv_html, tot_html):
    """{bbref id: stats} joining the advanced and totals tables; bbref's percentages (TS%) scaled to fractions as given"""
    A, T = parse(adv_html, 'advanced', ADV), parse(tot_html, 'totals_stats', TOT)
    out = {}
    for pid, a in A.items():
        s = dict(a)
        for k, v in T.get(pid, {}).items():
            if k not in ('mp', 'pos'):
                s[k] = v
        s['grp'] = GRP.get(s['pos'])
        out[pid] = s
    return out


def regress(stats, key, k, frac=1.0):
    """{id: (v', z, pct)} for one badge over a season: regressed with k toward the volume-weighted pool mean of his
    position group, z and percentile within the pool (MIN_MP x frac)"""
    _, _, grps, fn, _ = BY_KEY[key]
    out = {}
    for g in grps:
        L = []
        for pid, s in stats.items():
            if s.get('grp') != g or (s.get('mp') or 0) < MIN_MP * frac:
                continue
            v, n = fn(s)
            if v is not None:
                L.append((pid, v, max(n, 0)))
        if len(L) < 12:
            continue
        nw = sum(n for _, _, n in L) or 1
        m = sum(v * n for _, v, n in L) / nw
        reg = [(pid, m + (v - m) * n / (n + k)) for pid, v, n in L]
        mm = sum(x for _, x in reg) / len(reg)
        sd = math.sqrt(sum((x - mm) ** 2 for _, x in reg) / len(reg)) or 1.0
        srt = sorted(x for _, x in reg)
        for pid, x in reg:
            below = sum(1 for y in srt if y < x) + 0.5 * sum(1 for y in srt if y == x)
            out[pid] = (x, (x - mm) / sd, below / len(srt))
    return out


def shipped():
    """[(key, k)] of the badges that passed the backtest, best t first"""
    try:
        with open(BT) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    return [(k, kk) for _, k, kk in sorted(((v['t'], k, v['k']) for k, v in d['badges'].items() if v.get('pass')), reverse=True)]


def board_badges(stats, frac=1.0):
    """{bbref id: [[name, tier, pct, label], ...]} best first"""
    out = {}
    for key, k in shipped():
        _, name, _, _, label = BY_KEY[key]
        for pid, (_, _, pct) in regress(stats, key, k, frac).items():
            tier = next((t for t, q in TIERS if pct >= q), None)
            if tier:
                out.setdefault(pid, []).append([name, tier, int(pct * 100), label])
    order = {t: i for i, (t, _) in enumerate(TIERS)}
    for L in out.values():
        L.sort(key=lambda b: (order[b[1]], -b[2]))
    return out
