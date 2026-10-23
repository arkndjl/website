#!/usr/bin/env python3
"""Luck-stripped basketball efficiency (team model idea 6, Oct 23 2026): a result enters the efficiency ratings with
the threes and free throws each side made partly at expected rates, so a hot or cold shooting night moves the ratings
less. A defense has little say over its opponents' 3P% (it has more over how many threes they take), and a team's FT%
is its own shooters' skill, not the night's.

    python3 scripts/luck_research.py --attach          # team 3PM/3PA/FTM/FTA into scripts/nba_games_hist.json.gz ('sh')
    python3 scripts/luck_research.py nba [--only i,j]  # nba_games.Model lw3o / lw3d / lwft (+ lk3, lshl, ltot, lelo)

Each variant: the live model's walk with the change, the live inputs refit walk-forward, scored on absolute margin
error and absolute total error (harness.paired, clustered by game day x home team-season), tuning seasons and held out.
Ship bar (briefs.md): tune t <= -1.5, held out no worse. Results -> data/luck_research.json ({sport: [rows]}).
Team shooting comes from the box lines (scripts/nba_inseason.py --pull, or the copy in project files), and live
games carry it from ESPN's team box (nba_games.compact).
"""
import gzip
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'luck_research.json')


def save(sport, rows):
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    old = [r for r in d.get(sport, []) if r['label'] not in {o['label'] for o in rows}]
    d[sport] = old + rows
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1)


def attach(path=None):
    """team shooting lines (summed box lines) into the frozen NBA history"""
    import nba_games as N
    import nba_inseason as IS
    bx = json.load(gzip.open(path)) if path else IS.load_box()
    with gzip.open(N.HIST, 'rt') as f:
        d = json.load(f)
    c = 0
    for g in d['games']:
        b = bx.get(g['id'])
        if not b or not all(t in b for t in (g['h'], g['a'])):
            continue
        # columns: id, min, pts, fgm, fga, fg3m, fg3a, ftm, fta, ...
        g['sh'] = {t: [sum(r[i] for r in b[t]) for i in (5, 6, 7, 8)] for t in (g['h'], g['a'])}
        c += 1
    with gzip.open(N.HIST, 'wt') as f:
        json.dump(d, f, separators=(',', ':'))
    print(c, 'of', len(d['games']), 'games with team shooting')


def score(lab, pr, ref, y, line, k1, k2, cl, extra=None, kind='margin'):
    ok = ~np.isnan(line)
    r = {'label': lab, 'kind': kind, **(extra or {})}
    for nm, k in (('tune', k1), ('held', k2)):
        e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
        p = H.paired(e, e0, cluster=[c[k] for c in cl])
        kk = k & ok
        r[nm] = {'n': int(k.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4),
                 't': round(p['t'], 2), 'maeLined': round(float(np.abs(pr[kk] - y[kk]).mean()), 4),
                 'maeLine': round(float(np.abs(line[kk] - y[kk]).mean()), 4)}
    r['pass'] = r['tune']['t'] <= -1.5 and r['held']['d'] <= 0
    print(json.dumps(r), flush=True)
    return r


# ---------------------------------------------------------------- NBA
_NBA = {}


def nba_design(params):
    import nba_games as N
    import nba_games_fit as Fit
    if not _NBA:
        G, names = N.load_hist()
        _NBA.update(G=G, names=names, inj=Fit.load_inj(), F=json.load(open(N.FIT)))
    F = _NBA['F']
    _, data = N.walk(_NBA['G'], _NBA['names'], F['P'], params, inj=_NBA['inj'])
    D = [(g, x, tx) for g, x, tx in data if g.get('fin') and g['S'] >= N.FIRST + 1]
    X = {f: np.array([x[f] for _, x, _ in D], float) for f in F['feats']}
    return {'X': X, 'TX': np.array([[tx[f] for f in N.TFEATS] for _, _, tx in D], float),
            'y': np.array([g['hs'] - g['as'] for g, _, _ in D], float),
            'ty': np.array([g['hs'] + g['as'] for g, _, _ in D], float), 'S': np.array([g['S'] for g, _, _ in D]),
            'line': np.array([g['L'] if g.get('L') is not None else np.nan for g, _, _ in D]),
            'tline': np.array([g['T'] if g.get('T') else np.nan for g, _, _ in D]),
            'day': np.array([g['tip'][:10] for g, _, _ in D]),
            'team': np.array([f"{g['h']}{g['S']}" for g, _, _ in D])}


NBA_V = [('base', {}),
         # 1-: threes
         ('3d 0', {'lw3d': 0.0}), ('3d .5', {'lw3d': 0.5}), ('3o .5', {'lw3o': 0.5}),
         ('3 both .5', {'lw3o': 0.5, 'lw3d': 0.5}), ('3o .5 3d 0', {'lw3o': 0.5, 'lw3d': 0.0}),
         ('3 both 0', {'lw3o': 0.0, 'lw3d': 0.0}),
         # 7-: free throws, then everything
         ('ft 0', {'lwft': 0.0}), ('ft .5', {'lwft': 0.5}),
         ('3o .5 3d 0 ft 0', {'lw3o': 0.5, 'lw3d': 0.0, 'lwft': 0.0}),
         # 10-: margin ratings only (totals' copies raw); Elo on the stripped margin
         ('3o .5 3d 0 ft 0 margin only', {'lw3o': 0.5, 'lw3d': 0.0, 'lwft': 0.0, 'ltot': 0}),
         ('3o .5 3d 0 ft 0 + elo', {'lw3o': 0.5, 'lw3d': 0.0, 'lwft': 0.0, 'lelo': 1}),
         # 12-: second round around '3 both .5': the weight, the shrinkage of the expected 3P%, its memory
         ('3 both .25', {'lw3o': 0.25, 'lw3d': 0.25}), ('3 both .75', {'lw3o': 0.75, 'lw3d': 0.75}),
         ('3o .75 3d .25', {'lw3o': 0.75, 'lw3d': 0.25}), ('3o .25 3d .75', {'lw3o': 0.25, 'lw3d': 0.75}),
         ('3 both .5 k3 200', {'lw3o': 0.5, 'lw3d': 0.5, 'lk3': 200.0}),
         ('3 both .5 k3 2000', {'lw3o': 0.5, 'lw3d': 0.5, 'lk3': 2000.0}),
         ('3 both .5 league', {'lw3o': 0.5, 'lw3d': 0.5, 'lk3': 1e9}),
         ('3 both .5 shl 30', {'lw3o': 0.5, 'lw3d': 0.5, 'lshl': 30.0}),
         ('3 both .5 shl 200', {'lw3o': 0.5, 'lw3d': 0.5, 'lshl': 200.0}),
         ('3 both .5 tot .5', {'lw3o': 0.5, 'lw3d': 0.5, 'ltot': 0.5}),
         ('3 both .5 tot 1.5', {'lw3o': 0.5, 'lw3d': 0.5, 'ltot': 1.5})]


def _nba_one(v):
    import nba_games as N
    F = json.load(open(N.FIT))
    return v[0], nba_design({**F['params'], **v[1]})


def nba(V=None):
    import nba_games as N
    import nba_games_fit as Fit
    F = json.load(open(N.FIT))
    V = V or NBA_V
    if '--only' in sys.argv:
        V = [V[0]] + [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    with Pool(int(os.environ.get('PROCS', 4))) as pool:
        res = dict(pool.map(_nba_one, V))
    b = res['base']
    y, ty, S, line, tline = b['y'], b['ty'], b['S'], b['line'], b['tline']
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(b['X'], F['feats']), y, S)
    tref = Fit.wf(b['TX'], ty, S)
    cl = [b['day'], b['team']]
    out = []
    for lab, extra in V[1:]:
        pr = Fit.wf(Fit.mat(res[lab]['X'], F['feats']), y, S)
        out.append(score(lab, pr, ref, y, line, k1, k2, cl, {'params': extra}))
        tp = Fit.wf(res[lab]['TX'], ty, S)
        out.append(score(lab + ' (total)', tp, tref, ty, tline, k1, k2, cl, {'params': extra}, kind='total'))
    save('nba', out)
    return out


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--attach' in a:
        attach(a[a.index('--attach') + 1] if len(a) > a.index('--attach') + 1 else None)
    elif 'nba' in a:
        nba()
