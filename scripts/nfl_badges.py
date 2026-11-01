#!/usr/bin/env python3
"""Predictive trait badges for the NFL ARKBOARD's WAR board (the CFB board's medals, scripts/cfb_badges.mjs).

A badge is one trait measured by one rate on the player's season line (nflverse stats_player_week, PFR advanced stats
via nflverse pfr_advstats, and play-by-play: the same files nfl_war.py / nfl_xv.py already read). Each rate is regressed
toward the position mean by its volume, v' = m + (v - m) x n / (n + k), k = n (1 - r) / r from the year-to-year r at
the pairs' mean volume n (2018-25). Rates with r < .15 are dropped as noise. Tier = percentile of v' among the
position's regulars that season (snaps on his side >= 300 a 17-game season, pro-rated in season): bronze 75th, silver
90th, gold 97th, platinum 99th.

Only the badges that passed scripts/nfl_badge_backtest.py ship: next season's board WAR on this season's WAR (and age),
the badge's partial t clustered by player >= 2 with a positive sign, and a positive leave-one-season-out R^2 gain.
The list, k and r come from data/nfl_badge_backtest.json, so a rerun of the backtest changes what the board shows.
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_war as W   # noqa: E402

ROOT = W.ROOT
BT = os.path.join(ROOT, 'data', 'nfl_badge_backtest.json')
MIN_SNAPS = 300                     # a 17-game season's snaps on his side for the position pool
TIERS = [('p', 0.99), ('g', 0.97), ('s', 0.90), ('b', 0.75)]
# board position from the XV sub-position (nfl_xv.GROUPS splits)
POS = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'SWR': 'WR', 'TE': 'TE', 'EDGE': 'EDGE', 'DT': 'DL', 'LB': 'LB', 'CB': 'CB', 'NCB': 'CB', 'S': 'S'}


def _per(a, b):
    return (a / b, b) if b > 0 else (None, 0)


# [key, name, positions, rate fn(c, snaps) -> (value up = good, volume), label]
def _qb_drop(c): return c.get('att', 0) + c.get('sk', 0)


BADGES = [
    ('deep', 'Deep Ball', ('QB',), lambda c, s: _per(c.get('x:depa', 0), c.get('x:datt', 0)), 'EPA per pass 20+ air yards'),
    ('pocket', 'Pocket Presence', ('QB',), lambda c, s: _per(-c.get('sk', 0), c.get('pass:times_pressured', 0)), 'sacks per pressure (fewer)'),
    ('accurate', 'Accurate', ('QB',), lambda c, s: _per(c.get('cpoe_w', 0), c.get('cpoe_n', 0)), 'completion % over expected'),
    ('clean', 'Clean Thrower', ('QB',), lambda c, s: _per(-c.get('pass:passing_bad_throws', 0), c.get('att', 0)), 'bad-throw rate (lower)'),
    ('scramble', 'Scrambler', ('QB',), lambda c, s: _per(c.get('rfd', 0), _qb_drop(c) + c.get('car', 0)), 'rushing first downs a play'),
    ('recv', 'Receiving Back', ('RB',), lambda c, s: _per(c.get('rec', 0), s), 'receiving yards a snap'),
    ('btk', 'Tackle Breaker', ('RB',), lambda c, s: _per(c.get('rush:rushing_broken_tackles', 0) + c.get('rush:receiving_broken_tackles', 0), c.get('car', 0) + c.get('tgt', 0)), 'broken tackles a touch'),
    ('yco', 'After Contact', ('RB',), lambda c, s: _per(c.get('rush:rushing_yards_after_contact', 0), c.get('rush:carries', 0)), 'yards after contact a carry'),
    ('runeff', 'Efficient Runner', ('RB',), lambda c, s: _per(c.get('repa', 0), c.get('car', 0)), 'rushing EPA a carry'),
    ('yac', 'YAC', ('WR', 'TE'), lambda c, s: _per(c.get('x:yacx', 0), c.get('x:rcmp', 0)), 'yards after catch over expected'),
    ('target', 'Target Magnet', ('WR', 'TE'), lambda c, s: _per(c.get('tgt', 0), s), 'targets a snap'),
    ('hands', 'Hands', ('WR', 'TE'), lambda c, s: _per(-c.get('rec:receiving_drop', 0), c.get('tgt', 0)), 'drop rate (lower)'),
    ('chains', 'Chain Mover', ('WR', 'TE'), lambda c, s: _per(c.get('recfd', 0), s), 'receiving first downs a snap'),
    ('tgteff', 'Efficient Target', ('WR', 'TE'), lambda c, s: _per(c.get('recepa', 0), c.get('tgt', 0)), 'receiving EPA a target'),
    ('rush', 'Pass Rusher', ('EDGE', 'DL', 'LB'), lambda c, s: _per(c.get('prss', 0), s), 'pressures a snap'),
    ('sack', 'Sack Artist', ('EDGE', 'DL'), lambda c, s: _per(c.get('dsk', 0), s), 'sacks a snap'),
    ('run', 'Run Stopper', ('EDGE', 'DL', 'LB', 'S'), lambda c, s: _per(c.get('stopR', 0), s), 'run stops a snap'),
    ('tfl', 'Backfield', ('EDGE', 'DL'), lambda c, s: _per(c.get('rtfl', 0), s), 'run tackles for loss a snap'),
    ('tackle', 'Sure Tackler', ('LB', 'CB', 'S'), lambda c, s: _per(-c.get('def:def_missed_tackles', 0), c.get('def:def_tackles_combined', 0) + c.get('def:def_missed_tackles', 0)), 'missed-tackle rate (lower)'),
    ('ballhawk', 'Ballhawk', ('LB', 'CB', 'S'), lambda c, s: _per(c.get('int', 0) + c.get('pd', 0), s), 'INTs + passes defended a snap'),
    ('cover', 'Coverage', ('LB', 'CB', 'S'), lambda c, s: _per(-c.get('def:def_yards_allowed', 0), s), 'yards allowed in coverage a snap (fewer)'),
    ('lockdown', 'Lockdown', ('CB', 'S'), lambda c, s: _per(-c.get('def:def_completions_allowed', 0), c.get('def:def_targets', 0)), 'catch rate allowed (lower)'),
]
BY_KEY = {b[0]: b for b in BADGES}


def pbp_extras(y, fresh=False, thru=None):
    """{gsis: {x:datt, x:depa, x:rcmp, x:yacx}}: deep passes (20+ air yards: attempts, EPA) and receptions with yards
    after catch over nflverse's expected (xyac_mean_yardage), regular season, from the play-by-play nfl_war.py reads.
    Cached by week (scripts/.cache/nfl/badgepbp_<y>.json)."""
    src = W.get(f'play_by_play_{y}.csv.gz', f'{W.REL}/pbp/play_by_play_{y}.csv.gz', fresh)
    cache = os.path.join(W.CACHE, f'badgepbp_{y}.json')
    if not os.path.exists(cache) or os.path.getmtime(cache) < os.path.getmtime(src):
        f_ = lambda x: float(x) if x not in ('', 'NA') else None
        acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        with gzip.open(src, 'rt', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['season_type'] != 'REG' or r['pass_attempt'] != '1' or r['sack'] == '1' or r['qb_spike'] == '1' or r['two_point_attempt'] == '1':
                    continue
                ay, epa = f_(r['air_yards']), f_(r['epa'])
                w = r['week']
                if r['passer_player_id'] not in ('', 'NA') and ay is not None and ay >= 20 and epa is not None:
                    a = acc[w + '|' + r['passer_player_id']]; a[0] += 1; a[1] += epa
                if r['complete_pass'] == '1' and r['receiver_player_id'] not in ('', 'NA'):
                    yac, xy = f_(r['yards_after_catch']), f_(r['xyac_mean_yardage'])
                    if yac is not None and xy is not None:
                        a = acc[w + '|' + r['receiver_player_id']]; a[2] += 1; a[3] += yac - xy
        with open(cache, 'w') as f:
            json.dump(acc, f, separators=(',', ':'))
    with open(cache) as f:
        raw = json.load(f)
    out = defaultdict(lambda: Counter())
    for k, v in raw.items():
        w, g = k.split('|')
        if thru is None or int(w) < thru:
            o = out[g]
            o['x:datt'] += v[0]; o['x:depa'] += v[1]; o['x:rcmp'] += v[2]; o['x:yacx'] += v[3]
    return out


def seasons_of(players, ex):
    """player-team rows (nfl_xv.season_players) -> one row per player: counts summed over his teams, the extras joined
    on gsis, position by his most-played sub-position, snaps on his side"""
    by = {}
    for p in players:
        a = by.setdefault(p['pfr'], {'pfr': p['pfr'], 'gsis': p['gsis'], 'n': p['n'], 'c': Counter(), 'snaps': 0.0, 'subs': Counter(), 'sh': 0.0})
        a['c'].update({k: v for k, v in p['c'].items() if isinstance(v, (int, float))})
        a['snaps'] += p['snaps']; a['subs'][p['sub']] += p['snaps'] + .01; a['sh'] += p['sh']
        if p['gsis']:
            a['gsis'] = p['gsis']
    for a in by.values():
        a['c'].update(ex.get(a['gsis'], {}))
        a['sub'] = a['subs'].most_common(1)[0][0]
        a['pos'] = POS.get(a['sub'])
    return by


def regress(rows, key, k, frac=1.0):
    """{pfr: (v', z, pct)} for one badge over one season's player rows at its positions: v' regressed with k toward the
    volume-weighted mean of the position pool, z and percentile within the pool (snaps >= MIN_SNAPS x frac)"""
    _, _, poss, fn, _ = BY_KEY[key]
    out = {}
    for pos in poss:
        L = []
        for a in rows:
            if a['pos'] != pos or a['snaps'] < MIN_SNAPS * frac:
                continue
            v, n = fn(a['c'], a['snaps'])
            if v is not None:
                L.append((a['pfr'], v, n))
        if len(L) < 12:
            continue
        nw = sum(n for _, _, n in L)
        m = sum(v * n for _, v, n in L) / nw
        reg = [(pid, m + (v - m) * n / (n + k)) for pid, v, n in L]
        mm = sum(x for _, x in reg) / len(reg)
        sd = math.sqrt(sum((x - mm) ** 2 for _, x in reg) / len(reg)) or 1.0
        srt = sorted(x for _, x in reg)
        for pid, x in reg:
            below = sum(1 for y_ in srt if y_ < x) + 0.5 * sum(1 for y_ in srt if y_ == x)
            out[pid] = (x, (x - mm) / sd, below / len(srt))
    return out


def shipped():
    """[(key, k)] of badges that passed the backtest (data/nfl_badge_backtest.json), best t first"""
    try:
        with open(BT) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    L = [(v['t'], k, v['k']) for k, v in d['badges'].items() if v.get('pass')]
    return [(k, kk) for _, k, kk in sorted(L, reverse=True)]


def board_badges(y, players, fresh=False, thru=None, frac=1.0):
    """{pfr: [[name, tier, pct, label], ...]} best first for season y's board: players = nfl_xv.season_players rows"""
    ship = shipped()
    if not ship:
        return {}
    rows = list(seasons_of(players, pbp_extras(y, fresh, thru)).values())
    out = defaultdict(list)
    for key, k in ship:
        _, name, _, _, label = BY_KEY[key]
        for pid, (_, _, pct) in regress(rows, key, k, frac).items():
            tier = next((t for t, q in TIERS if pct >= q), None)
            if tier:
                out[pid].append([name, tier, int(pct * 100), label])
    order = {t: i for i, (t, _) in enumerate(TIERS)}
    for L in out.values():
        L.sort(key=lambda b: (order[b[1]], -b[2]))
    return dict(out)
