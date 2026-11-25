#!/usr/bin/env python3
"""Does the CFP committee ranking add to the CFB game model (= ARK Ranking) margins? Point in time: the latest CFP
release before kickoff; residual = actual margin - walk-forward model margin. Fit 2017-21, held 2022-25 (not 2020).
Terms: d_lin = (26-rank_h)/25 - (26-rank_a)/25 (unranked 0); d_log = log(26/rank) diff. Game day clustered t."""
import gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import cfb_cfp as C
hist, polls, wf = C.load()
games = {int(S): g for S, g in hist['games'].items()}
by_id = {str(g['id']): g for S in games for g in games[S]}
rels = defaultdict(list)
for r in polls['releases']:
    if r['poll'] == 'cfp': rels[r['S']].append((C.pday(r['date']), {x['id']: x['rk'] for x in r['ranks']}))
for S in rels: rels[S].sort(key=lambda x: x[0])
rows = []
for r in wf:
    g = by_id.get(str(r['id']))
    if not g or r['m'] is None or g.get('homePoints') is None or r['S'] == 2020 or r['S'] < 2017: continue
    D = C.pday(r['date']); prev = [x for x in rels.get(r['S'], []) if x[0] < D]
    if not prev: continue
    rk = prev[-1][1]; h, a = str(g['homeId']), str(g['awayId'])
    if h not in rk and a not in rk: continue          # only games with a ranked team
    lin = lambda t: (26 - rk[t]) / 25 if t in rk else 0.0
    lg = lambda t: math.log(26 / rk[t]) if t in rk else 0.0
    y = (g['homePoints'] - g['awayPoints']) - r['m']
    rows.append({'S': r['S'], 'day': r['date'][:10], 'y': y, 'm': r['m'], 'lin': lin(h) - lin(a), 'log': lg(h) - lg(a),
                 'bowl': g['seasonType'] != 'regular', 'sig': r['sigma']})
print('games', len(rows), 'bowl', sum(r['bowl'] for r in rows))
def fit(rr, k):
    x = np.array([r[k] for r in rr]); y = np.array([r['y'] for r in rr]); return float(x @ y / (x @ x))
def score(rr, k, b):
    y = np.array([r['y'] for r in rr]); x = np.array([r[k] for r in rr])
    d = (y - b * x) ** 2 - y ** 2      # squared error change per game
    by = defaultdict(float)
    for r, v in zip(rr, d): by[(r['S'], r['day'])] += v
    v = np.array(list(by.values())); t = v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))
    ae = np.abs(y - b * x).mean() - np.abs(y).mean()
    return {'dMSE': round(float(d.mean()), 3), 'dMAE': round(float(ae), 3), 't': round(float(t), 2), 'n': len(rr)}
out = {}
for sub in ('all', 'regular'):
    R = [r for r in rows if sub == 'all' or not r['bowl']]
    tune = [r for r in R if r['S'] <= 2021]; hold = [r for r in R if r['S'] >= 2022]
    for k in ('lin', 'log'):
        b = fit(tune, k)
        out[f'{sub}_{k}'] = {'b': round(b, 2), 'tune': score(tune, k, b), 'hold': score(hold, k, b), 'bHold': round(fit(hold, k), 2)}
        print(sub, k, out[f'{sub}_{k}'])
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result.json'), 'w'), indent=1)
