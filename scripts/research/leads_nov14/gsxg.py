# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Game-state weights for Understat shots: a shot after the match's first red card counts 0, a shot by a side two or
more goals ahead counts w, every other shot 1. The score is rebuilt from the shot rows (Goal to the shooting side,
OwnGoal to the other), the red card minute from the sent-off player's minutes."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_data as D
import soccer_players as SP


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def red_minute(m):
    """minute of the first red card (None: none before the 90th)"""
    best = None
    for s in 'ha':
        rs = {}
        for r in m['ro'][s]:
            if all(str(q.get('player_id')) != str(r.get('player_id')) for q in rs.values()):
                rs[r['id']] = r
        start = {}
        for r in rs.values():
            if int(f(r.get('positionOrder'))) < 17 and str(r.get('roster_out')) in ('0', 'None', ''):
                start[r['id']] = 0
        for _ in range(6):
            for r in rs.values():
                ro_ = str(r.get('roster_out') or '0')
                if r['id'] not in start and ro_ in start and ro_ in rs:
                    start[r['id']] = start[ro_] + int(f(rs[ro_]['time']))
        for r in rs.values():
            if int(f(r.get('red_card'))) > 0 and r['id'] in start:
                t = start[r['id']] + int(f(r['time']))
                if 0 < t < 90 and (best is None or t < best):
                    best = t
    return best


def states(m, hg=None, ag=None):
    """per side: [(shot row, state)] with state 'r' (after a red card), 'l' (shooter's side 2+ ahead), '' (kept).
    None when the rebuilt final score is not (hg, ag)"""
    red = red_minute(m)
    ev = []
    for s in 'ha':
        for i, x in enumerate(m['sh'].get(s, [])):
            ev.append((int(f(x[0])), s, i, x))
    ev.sort(key=lambda e: (e[0], 0))                              # stable: listed order inside a minute
    sc = {'h': 0, 'a': 0}
    out = {'h': [], 'a': []}
    for mn, s, i, x in ev:
        o = 'a' if s == 'h' else 'h'
        st = 'r' if red is not None and mn > red else 'l' if sc[s] - sc[o] >= 2 else ''
        out[s].append((x, st))
        if x[3] == 'Goal':
            sc[s] += 1
        elif x[3] == 'OwnGoal':
            sc[o] += 1
    if hg is not None and (sc['h'], sc['a']) != (int(hg), int(ag)):
        return None
    return out


def wt(st, w):
    return 0.0 if st == 'r' else w if st == 'l' else 1.0


def team_xg(m, w, hg=None, ag=None):
    """(home, away) weighted xG, own goals left out; None when the score can't be rebuilt"""
    S = states(m, hg, ag)
    if S is None:
        return None
    return tuple(sum(f(x[1]) * wt(st, w) for x, st in S[s] if x[3] != 'OwnGoal') for s in 'ha')
