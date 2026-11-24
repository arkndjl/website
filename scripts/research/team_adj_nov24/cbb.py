#!/usr/bin/env python3
"""CBB: Barttorvik BPM (the input of CBB WAR) with the team adjustment, per side as BPM: O-BPM to the team's adjusted
offensive efficiency over the D-I mean, D-BPM to the mean less adjusted defensive efficiency (barttorvik team results).
Exposure = minutes (mpg x games). Pairs 2012-13 ... 2025-26. Data: barttorvik getadvstats csv + <season>_team_results.json
(scripts/.cache/team_adj)."""
import csv, json, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..', '..', '..'); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import core
from cbb_data import BT_COLS
C = os.path.join(ROOT, 'scripts', '.cache', 'team_adj')
ix = {k: i for i, k in enumerate(BT_COLS)}


def f(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def season(y):
    tr = json.load(open(os.path.join(C, f'tr{y}.json')))
    T = {}
    for r in tr:
        try: g = sum(int(v) for v in str(r[3]).split('-')[:2])
        except ValueError: continue
        T[r[1]] = (r[4], r[6], g)
    lo, ld = sum(v[0] for v in T.values()) / len(T), sum(v[1] for v in T.values()) / len(T)
    parts, num, den, team, nm, val = [], defaultdict(float), defaultdict(float), {}, {}, {}
    vo, vd = {}, {}
    for row in csv.reader(open(os.path.join(C, f'adv{y}.csv'))):
        t, pid = row[ix['team']], row[ix['pid']]
        gp, mp, ob, db = f(row[ix['gp']]), f(row[ix['mp']]), f(row[ix['obpm']]), f(row[ix['dbpm']])
        if t not in T or not gp or not mp or ob is None or db is None: continue
        e = gp * mp; key = f'{pid}'
        parts.append((key + '|O', t + '|O', e)); parts.append((key + '|D', t + '|D', e))
        vo[key + '|O'] = ob; vd[key + '|D'] = db
    for t, (o, d, g) in T.items():
        team[t + '|O'] = ((o - lo) * g, g); team[t + '|D'] = ((ld - d) * g, g); nm[t + '|O'] = nm[t + '|D'] = t
    return {'parts': parts, 'val': {**vo, **vd}, 'team': team, 'net': nm}


D = {y: season(y) for y in range(2012, 2027)}
out = core.run(D, list(range(2012, 2026)), 200, 300, 'cbb BPM (O and D sides, player r per side)')
# player r on the total (O + D) as NBA: rebuild from the sides
import numpy as np
def tot(V): 
    o = defaultdict(float)
    for k, v in V.items(): o[k.rsplit('|', 1)[0]] += v
    return o
a, b = core.fit_line(D)
px = {k: [] for k in ('base', 'adj')}
for k in px:
    xs, ys, ws = [], [], []
    for n in range(2012, 2026):
        vn = tot(D[n]['val'] if k == 'base' else core.adjust(D[n], n, b)); vx = tot(D[n + 1]['val'])
        ex = defaultdict(float)
        for pid, t, e in D[n + 1]['parts']:
            if pid.endswith('|O'): ex[pid[:-2]] += e
        for pid, e in ex.items():
            if e >= 300 and pid in vn: xs.append(vn[pid]); ys.append(vx[pid]); ws.append(e)
    out[k]['playerRTotal'] = round(core.wcorr(xs, ys, ws), 4)
out['pass'] = bool(out['adj']['predict'] >= out['base']['predict'] and out['adj']['playerRTotal'] >= out['base']['playerRTotal'] - .01)
print('total player r', out['base']['playerRTotal'], out['adj']['playerRTotal'], 'pass', out['pass'])
json.dump(out, open(os.path.join(HERE, 'cbb.json'), 'w'), indent=1)
