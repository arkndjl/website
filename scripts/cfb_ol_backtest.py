#!/usr/bin/env python3
"""College OL value test (2026-11-01): does the lineman's quality in college WAR/XV gain from PFN's blocking lines?
Run after node scripts/cfb_av_backtest.mjs (fills scripts/.cache/av): python3 scripts/cfb_ol_backtest.py
    -> data/cfb_ol_backtest.json

It reuses scripts/cfb_xv_backtest.py's ratings, rows and fit (executed up to its tests), with two more OL parts:
sacks and pressures allowed a snap (prsAllwd fills 2026, where PFN's pressure rate is often blank). Every other
position keeps its XV parts; only the OL parts change between variants. Tests: held-out team SRS and offense r
(2025 fit -> 2024, 2024 -> 2025, 2024-25 -> 2026), and next season's offense rating from returning offensive
players' last-season value, alone and with last season's offense (2025, 2026).
PFN grades linemen only from 2024, so there are three seasons; the variants differ by under .01 r and .01 R^2
everywhere, inside noise, and none is ahead in every season: nothing ships (college OL quality stays PFN score
x SAV_W.OL in WAR, score + pressure rate + run block in XV).
"""
import json, os
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, 'scripts', 'cfb_xv_backtest.py')).read()
cut = src.index('SPLITS = [')
src = src[:cut]
# extra OL parts: pressures and sacks allowed a snap (prsAllwd fills 2026, where prsRate is often blank)
src = src.replace("if g == 'OL': return dict(prs=neg(f('prsRate')), rb=f('rbScore'), pb=f('pbScore'))",
  "if g == 'OL': return dict(prs=neg(f('prsRate')), rb=f('rbScore'), pb=f('pbScore'), sk=neg(per(f('skAllwd'), sn)), pa=neg(per(f('prsAllwd'), sn)))")
src = src.replace("'OL': ['prs', 'rb', 'pb']", "'OL': ['prs', 'rb', 'pb', 'sk', 'pa']")
G = {'__file__': os.path.join(ROOT, 'scripts', 'cfb_xv_backtest.py'), '__name__': 'cfb_ol'}
exec(compile(src, 'cfbxv', 'exec'), G)
fit, team_value, DATA, TEAM, rows, cor, COLS, POS = G['fit'], G['team_value'], G['DATA'], G['TEAM'], G['rows'], G['cor'], G['COLS'], G['POS']
SAV_REPL = G['SAV_REPL']
SPLITS = [([2025], 2024), ([2024], 2025), ([2024, 2025], 2026)]
VARS = {'scoreOnly': [], 'xvNow': ['prs', 'rb', 'pb'], 'plusSk': ['prs', 'rb', 'pb', 'sk'], 'plusPa': ['pa', 'rb', 'pb', 'sk'], 'blockOnly': ['rb', 'pb'], 'allowed': ['pa', 'sk']}

def restricted_fit(train, keep):
    # zero the dropped OL parts' columns by fitting on a copy with them removed
    drop = [i for i, (g, k) in enumerate(COLS) if g == 'OL' and k not in keep]
    saved = {y: DATA[y]['C'][:, drop].copy() for y in DATA}
    for y in DATA: DATA[y]['C'][:, drop] = 0.0
    w, c = fit(train)
    for y in DATA: DATA[y]['C'][:, drop] = saved[y]
    c = {k: v for k, v in c.items() if not (k[0] == 'OL' and k[1] not in keep)}
    return w, c

out = {}
def r2_of(Y, cols):
    A = np.column_stack([np.ones(len(Y))] + cols); b = np.linalg.lstsq(A, Y, rcond=None)[0]
    return 1 - ((Y - A @ b) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()
def pval(p, w, c):
    g = p['pos']
    return p['sh'] * (w[g] * (p['z']['score'] - SAV_REPL) + sum(x * p['z'][k] for (gg, k), x in c.items() if gg == g))
for name, keep in VARS.items():
    res = {'held': {}, 'fwd': {}}
    for train, test in SPLITS:
        w, c = restricted_fit(train, keep)
        Y = DATA[test]['Y']
        res['held'][test] = dict(srs=cor(team_value(test, w, c), Y['srs']), off=cor(team_value(test, w, c, 'off'), Y['off']))
        res.setdefault('w', {})[test] = {'OLscore': round(w['OL'], 3), **{k[1]: round(v, 3) for k, v in c.items() if k[0] == 'OL'}}
    for y, train in ((2025, [2024]), (2026, [2024, 2025])):
        w, c = restricted_fit(train, keep)
        prev = {(p['id'], p['pos']): p for p in rows if p['season'] == y - 1}
        ts = [t for t in DATA[y]['t'] if (y - 1, t) in TEAM]
        Y = np.array([TEAM[(y, t)]['off'] for t in ts]); L = np.array([TEAM[(y - 1, t)]['off'] for t in ts])
        ret = {}
        for p in rows:
            q = prev.get((p['id'], p['pos'])) if p['season'] == y else None
            if q and q['pos'] in G['OFF']: ret[p['tid']] = ret.get(p['tid'], 0) + pval(q, w, c)
        R = np.array([ret.get(t, 0) for t in ts])
        res['fwd'][y] = dict(offRet=round(r2_of(Y, [R]), 4), offRetLast=round(r2_of(Y, [L, R]), 4))
    out[name] = res
    print(name, json.dumps(res))

with open(os.path.join(ROOT, 'data', 'cfb_ol_backtest.json'), 'w') as f:
    json.dump(out, f, indent=1)
    f.write('\n')
