#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The market's read of an NFL player (stdlib): his draft slot while he is on a rookie deal, the cap share of his
contract in force after it. A prior for pXP/60 (scripts/nfl_rate.py) and an input of the 1Y / 3Y WAR projection
(scripts/nfl_war_proj.py); tests: scripts/research/nfl_nov13/ (data/nfl_audit_nov13.json).

Sources: nflverse players.csv (PFR, GSIS and OverTheCap ids, draft year and pick) and OverTheCap's contract history via
nflverse (historical_contracts.csv.gz: year signed, APY as a share of the cap).
"""
import csv
import gzip
import io
import math
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache', 'nfl')
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
PLAYERS = f'{REL}/players/players.csv'
CONTRACTS = f'{REL}/contracts/historical_contracts.csv.gz'
ROOKIE_DEAL = 3        # seasons since the draft (or the first season, undrafted) still read by draft slot
UNDRAFTED = 300
CAP_FLOOR = 0.002
OLD_NICK = {'Redskins': 'Commanders', 'Football Team': 'Commanders', 'Washington': 'Commanders'}

_P, _C = {}, {}
_OK = [None, False]     # loaded ok; refetched in this process


def _get(name, url, fresh):
    from nfl_pbp import download
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if fresh or not os.path.exists(p):
        download(url, p)
    return p


def contracts(players_path, contracts_path):
    """gsis -> [(year signed, cap %, club nickname, draft year)], oldest first"""
    otc = {}
    for p in csv.DictReader(open(players_path, newline='', encoding='utf-8')):
        if p['otc_id'] and p['gsis_id']:
            otc[p['otc_id']] = p['gsis_id']
    out = defaultdict(list)
    raw = gzip.open(contracts_path).read().decode('utf-8')
    for c in csv.DictReader(io.StringIO(raw)):
        g = otc.get(c['otc_id'])
        try:
            ys, cap = int(c['year_signed']), float(c['apy_cap_pct'])
        except ValueError:
            continue
        if not g or cap <= 0 or ys < 1995:
            continue
        try:
            dy = int(float(c['draft_year']))
        except ValueError:
            dy = None
        out[g].append((ys, cap, OLD_NICK.get(c['team'], c['team']), dy))
    for v in out.values():
        v.sort()
    return out


def cap_of(cons, gsis, y, last_club=None, strict=True):
    """APY share of the cap of the contract in force for season y. strict: signed before y, or in y by a rookie or by a
    player on a new club (an in-season extension would read the season being predicted); else any signed through y."""
    best = None
    for ys, cap, club, dy in cons.get(gsis, ()):
        if ys < y or (ys == y and (not strict or dy == y or last_club is None or club != last_club)):
            if best is None or ys > best[0] or (ys == best[0] and cap > best[1]):
                best = (ys, cap)
    return best[1] if best else None


def load(fresh=False):
    """True when both files are in (downloaded once into the cache; fresh refetches them)"""
    if _OK[0] is None or (fresh and not _OK[1]):
        _OK[1] = _OK[1] or fresh
        try:
            pp, cp = _get('players.csv', PLAYERS, fresh), _get('historical_contracts.csv.gz', CONTRACTS, fresh)
            _P.clear(); _C.clear()
            for p in csv.DictReader(open(pp, newline='', encoding='utf-8')):
                if p['pfr_id']:
                    _P[p['pfr_id']] = p
            _C.update(contracts(pp, cp))
            _OK[0] = len(_P) > 5000 and len(_C) > 5000
        except Exception as e:
            print(f'nfl market: not loaded ({e!r})')
            _OK[0] = False
    return _OK[0]


def signal(pfr, S):
    """('r', -ln pick) on a rookie deal (seasons since the draft <= 3; undrafted = pick 300), ('v', ln cap %) on a later
    contract signed through season S, None without either (or when the files did not load)"""
    if not load():
        return None
    p = _P.get(pfr)
    if not p:
        return None
    iv = lambda k: int(float(p[k])) if p.get(k) not in (None, '', 'NA') else None
    dy, pick, rs = iv('draft_year'), iv('draft_pick'), iv('rookie_season')
    start = dy if dy else rs
    if start is not None and S - start <= ROOKIE_DEAL:
        return ('r', -math.log(pick if (dy and pick) else UNDRAFTED))
    cap = cap_of(_C, p['gsis_id'], S, strict=False)
    return ('v', math.log(max(cap, CAP_FLOOR))) if cap else None
