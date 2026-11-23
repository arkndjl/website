#!/usr/bin/env python3
"""MM1-MM3 (prereg.md addendum): model-to-model inputs into the NBA 3Y projection (F4 form, season end)."""
import os, sys, json, gzip, math, collections
import numpy as np
SCR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, SCR)
import nba_proj3y_research as R
import nba_proj as P
HERE = os.path.dirname(os.path.abspath(__file__))

rows = [r for r in R.load() if r['y3y'] is not None]
assert max(r['S'] for r in rows) + 3 <= 2026
n, proj, prior, age, lm, M = R.inputs(rows, 1.0, np.random.default_rng(0))
y = np.array([r['y3y'] for r in rows]); S = np.array([r['S'] for r in rows]); ids = [r['id'] for r in rows]
# team per player-season and season files
files = {s: P.load(s) for s in range(2010, 2027)}
tm = {}
mates = collections.defaultdict(lambda: [0.0, 0.0])
for s, d in files.items():
    if not d: continue
    for p in d['players']:
        if p.get('pr') or p.get('xpm') is None: continue
        t = (p.get('tm') or '').split('/')[-1]
        tm[(s, p['id'])] = t
        mates[(s, t)][0] += p['xpm'] * p['mp']; mates[(s, t)][1] += p['mp']
pos = {(s, p['id']): p.get('pos') for s, d in files.items() if d for p in d['players']}
# team season margins from game history (regular season)
H = json.load(gzip.open(os.path.join(SCR, 'nba_games_hist.json.gz')))
mg = collections.defaultdict(list)
for g in H['games']:
    if not g.get('fin') or g.get('t', 2) != 2: continue
    mg[(g['S'], g['h'])].append(g['hs'] - g['as']); mg[(g['S'], g['a'])].append(g['as'] - g['hs'])
print('hist seasons', sorted({k[0] for k in mg})[:3], '...', len(mg), 'team-seasons')
ab = {}
def team_margin(s, t):
    v = mg.get((s, t))
    return float(np.mean(v)) if v else None
# ESPN codes vs bbref codes: map by trying common differences
ALIAS = {'BRK': 'BKN', 'CHO': 'CHA', 'PHO': 'PHX', 'NOP': 'NO', 'NYK': 'NY', 'GSW': 'GS', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH',
         'NOH': 'NO', 'NJN': 'NJ', 'CHA': 'CHA', 'CHH': 'CHA'}
tmx, mx, pg = [], [], []
miss = 0
for r in rows:
    s, pid = r['S'], r['id']
    t = tm.get((s, pid), '')
    v = team_margin(s, t)
    if v is None: v = team_margin(s, ALIAS.get(t, t))
    if v is None: miss += 1; v = 0.0
    tmx.append(v)
    a, b = mates[(s, t)]
    me = r['xpm'] * r['mp']
    mx.append((a - me) / max(b - r['mp'], 1.0) if b - r['mp'] > 0 else 0.0)
    p = pos.get((s, pid)) or ''
    pg.append('G' if p in ('PG', 'SG') else 'C' if p == 'C' else 'F')
print('rows', len(rows), 'team margin missing', miss)
tmx, mx = np.array(tmx), np.array(mx)
G = np.array([1.0 if x == 'G' else 0.0 for x in pg]); C = np.array([1.0 if x == 'C' else 0.0 for x in pg])
base = R.design('F4', proj, prior, age, lm)
cands = {'MM1 team margin': [tmx], 'MM2 position (Stat+)': [G, C], 'MM3 mates XPM': [mx]}


def loso(X):
    pr = np.zeros(len(y))
    for s in sorted(set(S)):
        tr = np.abs(S - s) > 3; te = S == s
        b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        pr[te] = X[te] @ b
    return pr


pb = loso(base); eb = (pb - y) ** 2
out = {'base_rmse': round(float(np.sqrt(eb.mean())), 4), 'n': len(y)}
from math import erf, sqrt
for k, cols in cands.items():
    X = np.column_stack([base] + cols)
    pn = loso(X); en = (pn - y) ** 2
    t = R.tstat(en - eb, ids)
    ws = sum(1 for s in set(S) if en[S == s].mean() < eb[S == s].mean())
    full = np.linalg.lstsq(X, y, rcond=None)[0][-len(cols):]
    out[k] = {'rmse': round(float(np.sqrt(en.mean())), 4), 't': round(t, 2), 'p': 0.5 * (1 + erf(t / sqrt(2))),
              'seasons_better': f'{ws}/{len(set(S))}', 'coef': [round(float(c), 3) for c in full]}
    print(k, out[k])
p = [out[k]['p'] for k in cands]
import harness as Hh
for k, a in zip(cands, Hh.holm(p)): out[k]['holm'] = round(float(a), 4)
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, 'mm_proj3y_results.json'), 'w'), indent=1)
