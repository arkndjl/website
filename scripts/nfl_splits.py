"""Situational splits and coach traits from nflverse play-by-play (stdlib), for the game-model research in
scripts/nfl_splits_research.py: conversion rates by down and distance with what the league converts from the same
distance, two-minute offense, tempo, discipline, 2-point choices, and every field goal and extra point with its kicker.
Reads the raw files nfl_pbp.py keeps (scripts/.cache/nfl/play_by_play_YYYY.csv.gz); the lines are cached per season
in scripts/.cache/nfl/pbp/sp_YYYY.json."""
import csv
import gzip
import json
import os
from collections import defaultdict

import nfl_pbp as P

KEYS = ['t3n', 't3c', 't3x', 't3sn', 't3sc', 't3sx', 't3mn', 't3mc', 't3mx', 't3ln', 't3lc', 't3lx',
        'f4n', 'f4c', 'f4x', 'twn', 'twe', 'n', 'nh', 'pen', 'td', 'two', 'gtn', 'gtc']


def dbin(d):
    """distance to go, 1-15+ yards"""
    return int(min(max(d, 1), 15))


def agg(path):
    rd = csv.reader(gzip.open(path, 'rt'))
    h = next(rd); I = {k: i for i, k in enumerate(h)}
    G = defaultdict(lambda: dict.fromkeys(KEYS, 0.0))
    late = []          # (game, team, down, distance bin, converted)
    kicks = []         # (game, team, kicker, kind, distance, made)
    for r in rd:
        g = r[I['game_id']]; pt = P.tm(r[I['posteam']]); dt = P.tm(r[I['defteam']])
        if not pt or pt == 'NA' or not dt or dt == 'NA':
            continue
        ptype = r[I['play_type']]
        if r[I['penalty']] == '1' and r[I['penalty_team']] not in ('', 'NA'):
            G[(g, P.tm(r[I['penalty_team']]))]['pen'] += P.f(r[I['penalty_yards']], 0.0)
        if ptype == 'field_goal' and r[I['field_goal_result']] in ('made', 'missed', 'blocked'):
            kicks.append((g, pt, r[I['kicker_player_id']], 'fg', P.f(r[I['kick_distance']], 40.0), 1 if r[I['field_goal_result']] == 'made' else 0))
            continue
        if ptype == 'extra_point' and r[I['extra_point_result']] in ('good', 'failed', 'blocked'):
            kicks.append((g, pt, r[I['kicker_player_id']], 'xp', P.f(r[I['kick_distance']], 33.0), 1 if r[I['extra_point_result']] == 'good' else 0))
            continue
        if r[I['two_point_attempt']] == '1':
            G[(g, pt)]['two'] += 1
            continue
        if r[I['touchdown']] == '1' and r[I['td_team']] not in ('', 'NA'):
            G[(g, P.tm(r[I['td_team']]))]['td'] += 1
        if ptype not in ('pass', 'run') or r[I['qb_kneel']] == '1' or r[I['qb_spike']] == '1':
            continue
        A = G[(g, pt)]
        A['n'] += 1
        if r[I['no_huddle']] == '1':
            A['nh'] += 1
        down, d = r[I['down']], P.f(r[I['ydstogo']], 10)
        wp = P.f(r[I['wp']], 0.5)
        if down in ('3', '4') and 0.05 <= wp <= 0.95:
            conv = r[I['third_down_converted' if down == '3' else 'fourth_down_converted']] == '1'
            late.append((g, pt, down, dbin(d), 1 if conv else 0))
            if r[I['goal_to_go']] == '1':
                A['gtn'] += 1; A['gtc'] += 1 if conv else 0
        # two-minute offense: the last two minutes of the first half, and of a one-score fourth quarter
        hs = P.f(r[I['half_seconds_remaining']], 999); q = r[I['qtr']]
        epa = P.f(r[I['epa']])
        if epa is not None and hs <= 120 and (q == '2' or (q == '4' and abs(P.f(r[I['score_differential']], 0)) <= 8)):
            A['twn'] += 1; A['twe'] += epa
    L = defaultdict(lambda: [0, 0])
    for _, _, dn, b, c in late:
        L[(dn, b)][0] += 1; L[(dn, b)][1] += c
    for g, pt, dn, b, c in late:
        A = G[(g, pt)]; x = L[(dn, b)][1] / L[(dn, b)][0]
        if dn == '3':
            A['t3n'] += 1; A['t3c'] += c; A['t3x'] += x
            k = 't3s' if b <= 3 else 't3m' if b <= 6 else 't3l'
            A[k + 'n'] += 1; A[k + 'c'] += c; A[k + 'x'] += x
        else:
            A['f4n'] += 1; A['f4c'] += c; A['f4x'] += x
    return G, kicks


def season(y):
    """({(game_id, team): line}, [kick]) for season y."""
    os.makedirs(P.DIR, exist_ok=True)
    out = os.path.join(P.DIR, f'sp_{y}.json')
    if not os.path.exists(out):
        P.season(y)                              # fetches the raw file if missing
        G, kicks = agg(P.RAW.format(y=y))
        with open(out, 'w') as f:
            json.dump({'g': {f'{g}|{t}': {k: round(v, 4) for k, v in a.items()} for (g, t), a in G.items()}, 'k': kicks}, f)
    with open(out) as f:
        d = json.load(f)
    return {tuple(k.split('|')): v for k, v in d['g'].items()}, d['k']
