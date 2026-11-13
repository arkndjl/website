#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family C (prereg-market.md): Bet365 closes 2007-2022 joined to the match history.
Sources in /mnt/project-files/tennis/odds/: mendeley_all.dta (Mendeley Data 10.17632/62grx4j7r4.1, CC BY 4.0, tour
matches without the Slams, a row per player) and deuce's atp_odds / wta_odds .RData (GPL-2, Grand Slams).
Writes scripts/.cache/tennis/nov13/closes.pkl: {(d, tid, w, l, rd): winner's no-vig chance}."""
import sys, os, pickle, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import *
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import names
SRC = '/mnt/project-files/tennis/odds/'
rows, players, tn = load_rows()
def dn(d): return dt.date(d // 10000, d // 100 % 100, d % 100).toordinal()
def keys(pid):
    """surname keys + first initial of a history player"""
    n = players.get(pid, {}).get('n', '')
    k = names.key(n).split()
    if not k: return set()
    out = {(' '.join(k[1:]), k[0][0]), (k[-1], k[0][0])}
    if len(k) >= 2: out.add((' '.join(k[:-1]), k[-1][0])); out.add((k[0], k[-1][0]))      # surname first
    return out
def td_key(s):
    """tennis-data 'Del Potro J.M.' -> (surname key, initial)"""
    s = str(s).strip()
    parts = s.rsplit(' ', 1)
    if len(parts) < 2: return None
    return names.key(parts[0]), names.key(parts[1])[:1]
idx = {}
for r in rows:
    if r[0] < 20061201 or r[0] > 20230201 or r[2] not in ('G', 'M', 'A', 'F', 'O'): continue
    if r[4].startswith('Q'): continue
    for side, pid in ((0, r[7]), (1, r[8])):
        for k in keys(pid): idx.setdefault((r[1], k), []).append((dn(r[0]), side, r))
out, stat = {}, dict(m_rows=0, m_hit=0, m_amb=0, g_rows=0, g_hit=0, conflict=0)
def put(r, pw):
    k = (r[0], r[6], r[7], r[8], r[4])
    if k in out and abs(out[k] - pw) > .03: stat['conflict'] += 1
    out[k] = pw
# Mendeley: a row per player
M_ = pd.read_stata(SRC + 'mendeley_all.dta')
M_ = M_[M_.b365.notna() & M_.b365diff.notna() & M_.year.notna() & M_.month.notna() & M_.day.notna()]
for x in M_.itertuples():
    stat['m_rows'] += 1
    k = td_key(x.player)
    if not k: continue
    o1, o2 = float(x.b365), float(x.b365) - float(x.b365diff)
    if o1 <= 1 or o2 <= 1: continue
    day = dt.date(int(x.year), int(x.month), int(x.day)).toordinal()
    tour = 'atp' if x.gender == 1 else 'wta'
    won = x.swon == 2
    c = []
    for d0, side, r in idx.get((tour, k), []):
        if not (-2 <= day - d0 <= 15) or (side == 0) != won: continue
        mine, opp = (r[12], r[13]) if side == 0 else (r[13], r[12])
        if (mine and x.rank == x.rank and mine != int(x.rank)) or (opp and x.rankop == x.rankop and opp != int(x.rankop)): continue
        c.append(r)
    if len(c) > 1:
        # same player twice in the window (two events, or two rounds): the round closest in day order
        c2 = sorted(c, key=lambda r: abs(day - (dn(r[0]) + M.rday(r[4], r[2], r[6]))))
        if abs(day - (dn(c2[0][0]) + M.rday(c2[0][4], c2[0][2], c2[0][6]))) == abs(day - (dn(c2[1][0]) + M.rday(c2[1][4], c2[1][2], c2[1][6]))):
            stat['m_amb'] += 1; continue
        c = c2[:1]
    if not c: continue
    stat['m_hit'] += 1
    p1 = (1 / o1) / (1 / o1 + 1 / o2)
    put(c[0], p1 if won else 1 - p1)
# deuce: Grand Slams, winner / loser named
import pyreadr
RD = {'1st Round': 'R128', '2nd Round': 'R64', '3rd Round': 'R32', '4th Round': 'R16', 'Quarterfinals': 'QF', 'Semifinals': 'SF', 'The Final': 'F'}
for tour in ('atp', 'wta'):
    D = list(pyreadr.read_r(SRC + f'{tour}_odds.RData').values())[0]
    D = D[pd.to_datetime(D.Date) >= '2007-01-01']
    for x in D.itertuples():
        ow, ol = x.B365W, x.B365L
        if not (ow == ow and ol == ol and ow > 1 and ol > 1): continue
        stat['g_rows'] += 1
        kw, kl = td_key(x.Winner), td_key(x.Loser)
        if not kw or not kl: continue
        day = pd.Timestamp(x.Date).date().toordinal()
        c = [r for d0, side, r in idx.get((tour, kw), []) if side == 0 and r[2] == 'G' and -2 <= day - d0 <= 16 and kl in keys(r[8]) and r[4] == RD.get(x.Round, r[4])]
        if len(c) != 1: continue
        stat['g_hit'] += 1
        put(c[0], (1 / ow) / (1 / ow + 1 / ol))
print(stat, 'closes', len(out))
from collections import Counter
have = Counter((k[0] // 10000) for k in out)
tot = Counter(r[0] // 10000 for r in rows if 20070000 < r[0] < 20230201 and M.scored(r, 2007, 2023))
print({y: f'{have[y]}/{tot[y]}' for y in sorted(tot)})
pickle.dump(out, open(os.path.join(CACHE, 'closes.pkl'), 'wb'))
pickle.dump(out, open(SRC + 'closes_2007_2022.pkl', 'wb'))
