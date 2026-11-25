#!/usr/bin/env python3
"""(e1) prep: each player's EPA a play on neutral plays (0.10 <= wp <= 0.90) less his EPA a play on all plays, by kind
(pass as passer: qb_epa on dropbacks, scrambles out; rush: epa as rusher; rec: epa as target), regular season, no 2-pt.
Fewer than 20 neutral plays of a kind -> 0. 2018-25 only (no 2026).  -> scripts/.cache/nfl/port_neutral_<y>.json"""
import json, os, sys
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..'))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
COLS = ['season_type', 'two_point_attempt', 'wp', 'epa', 'qb_epa', 'qb_dropback', 'qb_scramble', 'pass', 'rush',
        'passer_player_id', 'rusher_player_id', 'receiver_player_id']
LO, HI, MIN = .10, .90, 20
for y in [int(a) for a in sys.argv[1:]] or range(2018, 2026):
    assert y <= 2025, 'lockbox'
    d = pd.read_csv(os.path.join(CACHE, f'play_by_play_{y}.csv.gz'), usecols=COLS, low_memory=False)
    d = d[(d.season_type == 'REG') & (d.two_point_attempt.fillna(0) == 0) & d.epa.notna()]
    d['neu'] = d.wp.between(LO, HI)
    kinds = {'p': (d[(d.qb_dropback == 1) & (d.qb_scramble.fillna(0) != 1) & d.passer_player_id.notna()], 'passer_player_id', 'qb_epa'),
             'r': (d[(d.rush == 1) | (d.qb_scramble.fillna(0) == 1)][lambda x: x.rusher_player_id.notna()], 'rusher_player_id', 'epa'),
             't': (d[(d['pass'] == 1) & d.receiver_player_id.notna()], 'receiver_player_id', 'epa')}
    out = {}
    stat = {}
    for k, (x, idc, ec) in kinds.items():
        x = x[x[ec].notna()]
        a = x.groupby(idc)[ec].agg(['mean', 'count'])
        n = x[x.neu].groupby(idc)[ec].agg(['mean', 'count'])
        j = a.join(n, rsuffix='_n', how='left')
        j['delta'] = (j['mean_n'] - j['mean']).where(j['count_n'] >= MIN, 0.0).fillna(0.0)
        for g, v in j['delta'].items(): out.setdefault(g, [0.0, 0.0, 0.0])['prt'.index(k)] = round(float(v), 5)
        stat[k] = dict(players=len(j), neutralShare=round(float(x.neu.mean()), 3), sdDelta=round(float(j[j['count'] >= 100]['delta'].std()), 4))
    json.dump(out, open(os.path.join(CACHE, f'port_neutral_{y}.json'), 'w'))
    print(y, stat, flush=True)
