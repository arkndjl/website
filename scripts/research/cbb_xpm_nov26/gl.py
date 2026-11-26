#!/usr/bin/env python3
"""Barttorvik player game logs -> per-season tables for rXPM round 3 (prereg.md).
Cache: scripts/.cache/cbb/games_bt/{y}.json.gz ({y}_all_advgames.json.gz), scripts/.cache/team_adj/adv{y}.csv, tr{y}.json.
    season(y) -> dict(tg=team-games, pg=player-games (numpy), players, teams)   (pickled beside the cache)"""
import csv, gzip, json, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from cbb_data import BT_COLS
GB = os.path.join(ROOT, 'scripts', '.cache', 'cbb', 'games_bt'); TA = os.path.join(ROOT, 'scripts', '.cache', 'team_adj')
ix = {k: i for i, k in enumerate(BT_COLS)}
YEARS = list(range(2008, 2027))
CNT = ['m2', 'x2', 'm3', 'x3', 'mft', 'xft', 'orb', 'drb', 'ast', 'tov', 'stl', 'blk', 'pf']   # makes / misses / counts


def f(x):
    try:
        v = float(x); return v if v == v else 0.0
    except (TypeError, ValueError): return 0.0


def team_results(y):
    """team -> dict(em, oe, de, wab_g, wp, g) (adjEM etc. centred on the D-I mean)"""
    tr = json.load(open(os.path.join(TA, f'tr{y}.json'))); out = {}
    for r in tr:
        try: w, l = (int(v) for v in str(r[3]).split('-')[:2])
        except ValueError: continue
        if not w + l: continue
        out[r[1]] = {'oe': float(r[4]), 'de': float(r[6]), 'wab': f(r[41]), 'w': w, 'g': w + l}
    mo = np.mean([v['oe'] for v in out.values()]); md = np.mean([v['de'] for v in out.values()])
    for v in out.values():
        v['oe'] -= mo; v['de'] -= md; v['em'] = v['oe'] - v['de']; v['wab_g'] = v['wab'] / v['g']; v['wp'] = v['w'] / v['g']
    return out


def season_metrics(y):
    """(pid, team) -> dict(e minutes, bpm, gbpm, obpm, dbpm, ogbpm, dgbpm) from the season file, and pid-level merges"""
    st = {}
    for row in csv.reader(open(os.path.join(TA, f'adv{y}.csv'), encoding='utf-8', errors='replace')):
        if len(row) < 66: continue
        gp, mp = f(row[ix['gp']]), f(row[ix['mp']])
        if not gp or not mp or row[ix['bpm']] in ('', None): continue
        st[(row[ix['pid']], row[ix['team']])] = {'e': gp * mp, **{k: f(row[ix[k]]) for k in ('bpm', 'gbpm', 'obpm', 'dbpm', 'ogbpm', 'dgbpm')},
                                                'yr': row[ix['yr']], 'name': row[ix['name']]}
    return st


def season(y):
    pk = os.path.join(GB, f'{y}.pkl')
    if os.path.exists(pk): return pickle.load(open(pk, 'rb'))
    rows = json.load(gzip.open(os.path.join(GB, f'{y}.json.gz'), 'rt'))
    TR = team_results(y)
    pts = defaultdict(float); poss = {}; loc = {}; opp = {}
    for g in rows:
        k = (g[0], g[47]); pts[k] += f(g[33]); poss[k] = f(g[43]); loc[k] = g[46]; opp[k] = g[5]
    tg = {}     # (date, team) -> row
    for k, p in pts.items():
        d, t = k; o = opp[k]
        if (d, o) not in pts or t not in TR or o not in TR or not poss[k]: continue
        ps = (poss[k] + poss[(d, o)]) / 2 if poss.get((d, o)) else poss[k]
        h = {'H': 1.0, 'A': -1.0}.get(loc[k], 0.0)
        tg[k] = {'d': d, 't': t, 'o': o, 'h': h, 'poss': ps, 'pf': p / ps * 100, 'pa': pts[(d, o)] / ps * 100,
                 'mg': (p - pts[(d, o)]) / ps * 100, 'oem': TR[o]['em'], 'ooe': TR[o]['oe'], 'ode': TR[o]['de'], 'win': 1.0 if p > pts[(d, o)] else 0.0}
    order = defaultdict(list)
    for (d, t) in tg: order[t].append(d)
    for t, ds in order.items():
        for i, d in enumerate(sorted(ds)): tg[(d, t)]['odd'] = i % 2 == 0; tg[(d, t)]['i'] = i
    pg = []
    for g in rows:
        k = (g[0], g[47])
        if k not in tg or f(g[8]) <= 0: continue
        mn = f(g[8]); e = mn / 40.0 * tg[k]['poss']        # possessions on the floor (minutes share x game possessions)
        m2, a2, m3, a3, mf, af = f(g[23]), f(g[24]), f(g[25]), f(g[26]), f(g[27]), f(g[28])
        pg.append({'pid': str(g[51]), 't': g[47], 'd': g[0], 'min': mn, 'e': e, 'gb': f(g[44]), 'ogb': f(g[30]), 'dgb': f(g[31]),
                   'm2': m2, 'x2': a2 - m2, 'm3': m3, 'x3': a3 - m3, 'mft': mf, 'xft': af - mf, 'orb': f(g[34]), 'drb': f(g[35]),
                   'ast': f(g[36]), 'tov': f(g[37]), 'stl': f(g[38]), 'blk': f(g[39]), 'pf': f(g[42]), 'ht': f(g[49]), 'cls': g[50], 'name': g[48]})
    out = {'tg': tg, 'pg': pg, 'sm': season_metrics(y), 'tr': TR}
    pickle.dump(out, open(pk, 'wb'))
    return out


if __name__ == '__main__':
    for y in YEARS:
        s = season(y); print(y, len(s['tg']), len(s['pg']), len(s['sm']), flush=True)
