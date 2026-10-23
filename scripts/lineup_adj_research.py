#!/usr/bin/env python3
"""Lineup-adjusted ratings (team model idea 1, Oct 23 2026): each past result enters the ratings net of who played.

Before a game's result updates the ratings, its margin is corrected for the lineup gap that night on both sides:
the team's own (the lineup value it played against its baseline) and the opponent's (so a win over a team missing
its star counts as one over the team it was that night). Tonight's lineup term stays in the model as it is.

    python3 scripts/lineup_adj_research.py nba [--only i,j]   # nba_games.Model lk_own / lk_opp / lk_mkt
    python3 scripts/lineup_adj_research.py cbb                # cbb_games ratings: Barttorvik absences, lk
    python3 scripts/lineup_adj_research.py nfl                # nfl_games Elo + market: QB played and injuries, lk

Each variant: the live model's walk with the adjustment, the live inputs refit walk-forward, scored on absolute
margin error (harness.paired, clustered by game day x home team-season) on the tuning seasons and held out. Ship bar
(briefs.md): tune t <= -1.5, held out no worse. Results -> data/lineup_adj_research.json ({sport: [rows]}).
"""
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'lineup_adj_research.json')


def save(sport, rows):
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    old = [r for r in d.get(sport, []) if r['label'] not in {o['label'] for o in rows}]
    d[sport] = old + rows
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1)


def score(lab, pr, ref, y, line, k1, k2, cl, extra=None):
    ok = ~np.isnan(line)
    r = {'label': lab, **(extra or {})}
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
    D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
    X = {f: np.array([x[f] for _, x in D], float) for f in F['feats']}
    return {'X': X, 'y': np.array([g['hs'] - g['as'] for g, _ in D], float), 'S': np.array([g['S'] for g, _ in D]),
            'line': np.array([g['L'] if g.get('L') is not None else np.nan for g, _ in D]),
            'day': np.array([g['tip'][:10] for g, _ in D]), 'team': np.array([f"{g['h']}{g['S']}" for g, _ in D])}


NBA_V = [('base', {}),
         ('own .5', {'lk_own': 0.5}), ('own 1', {'lk_own': 1.0}),
         ('opp .5', {'lk_opp': 0.5}), ('opp 1', {'lk_opp': 1.0}),
         ('both .5', {'lk_own': 0.5, 'lk_opp': 0.5}), ('both 1', {'lk_own': 1.0, 'lk_opp': 1.0}),
         ('mkt .5', {'lk_mkt': 0.5}), ('mkt 1', {'lk_mkt': 1.0}),
         ('both .5 + mkt .5', {'lk_own': 0.5, 'lk_opp': 0.5, 'lk_mkt': 0.5}),
         ('both 1 + mkt 1', {'lk_own': 1.0, 'lk_opp': 1.0, 'lk_mkt': 1.0}),
         # second round, around the first one's winner (mkt .5) and the opponent-only side
         ('mkt .25', {'lk_mkt': 0.25}), ('mkt .75', {'lk_mkt': 0.75}),
         ('mkt .5 + opp .5', {'lk_mkt': 0.5, 'lk_opp': 0.5}), ('mkt .5 + opp 1', {'lk_mkt': 0.5, 'lk_opp': 1.0}),
         ('mkt .75 + opp .5', {'lk_mkt': 0.75, 'lk_opp': 0.5})]


def _nba_one(v):
    import nba_games as N
    F = json.load(open(N.FIT))
    return v[0], nba_design({**F['params'], **v[1]})


def nba():
    import nba_games as N
    import nba_games_fit as Fit
    F = json.load(open(N.FIT))
    V = NBA_V
    if '--only' in sys.argv:
        V = [V[0]] + [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    with Pool(int(os.environ.get('PROCS', 4))) as pool:
        res = dict(pool.map(_nba_one, V))
    b = res['base']
    y, S, line = b['y'], b['S'], b['line']
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(b['X'], F['feats']), y, S)
    out = []
    for lab, extra in V[1:]:
        pr = Fit.wf(Fit.mat(res[lab]['X'], F['feats']), y, S)
        out.append(score(lab, pr, ref, y, line, k1, k2, [b['day'], b['team']], {'params': extra}))
    save('nba', out)


# ---------------------------------------------------------------- CBB
_CBB = {}
CBB_V = [('base', {}), ('lk .25', {'lk': 0.25}), ('lk .5', {'lk': 0.5}), ('lk 1', {'lk': 1.0}),
         ('lk .5 + elo .5', {'lk': 0.5, 'lke': 0.5})]


def _cbb_one(v):
    import cbb_games as C
    games, btname, d1s, tprior, avs, P, feats = _CBB['args']
    W, rows = C.run_walk({**P, **v[1]}, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    return v[0], {'pr': C.walk_pred(Xm, y, S, d1), 'y': y, 'S': S, 'line': line, 'd1': d1,
                  'day': np.array([g['date'][:10] for g, _, _ in D]),
                  'team': np.array([f"{g['home']}|{g['season']}" for g, _, _ in D]), 'ids': [g['id'] for g, _, _ in D]}


def cbb():
    import multiprocessing as mp
    import cbb_games as C
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    _CBB['args'] = (games, btname, d1s, tprior, avs, F['params'], list(F['feats']))
    V = CBB_V
    if '--only' in sys.argv:
        V = [V[0]] + [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    with mp.get_context('fork').Pool(int(os.environ.get('PROCS', 3))) as pool:
        res = dict(pool.map(_cbb_one, V))
    b = res['base']
    ok = ~np.isnan(b['pr']) & b['d1']
    k1 = ok & (b['S'] >= C.SCORE0) & (b['S'] <= C.TUNE_END); k2 = ok & (b['S'] > C.TUNE_END)
    out = []
    for lab, extra in V[1:]:
        r = res[lab]
        assert r['ids'] == b['ids']
        out.append(score(lab, r['pr'], b['pr'], b['y'], b['line'], k1, k2, [b['day'], b['team']], {'params': extra}))
    save('cbb', out)


# ---------------------------------------------------------------- NFL
_NFL = {}
NFL_V = [('base', {}), ('elo .5', {'lk': 0.5}), ('elo 1', {'lk': 1.0}), ('mkt .5', {'lk_mkt': 0.5}),
         ('mkt 1', {'lk_mkt': 1.0}), ('elo .5 + mkt .5', {'lk': 0.5, 'lk_mkt': 0.5}), ('elo 1 + mkt 1', {'lk': 1.0, 'lk_mkt': 1.0}),
         # second round: the QB part and the injury part alone
         ('mkt .5 qb', {'lk_mkt': 0.5, 'lk_parts': 'qb'}), ('mkt 1 qb', {'lk_mkt': 1.0, 'lk_parts': 'qb'}),
         ('mkt .5 inj', {'lk_mkt': 0.5, 'lk_parts': 'inj'}), ('elo 1 qb', {'lk': 1.0, 'lk_parts': 'qb'}),
         ('elo 1 + mkt 1 qb', {'lk': 1.0, 'lk_mkt': 1.0, 'lk_parts': 'qb'})]


def _nfl_one(v):
    import nfl_games as G
    games, box, qbs, inj, P, feats = _NFL['args']
    _, data = G.walk(games, box, qbs, {**P, **v[1]}, inj=inj)
    for g, x, _ in data:
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
    D = [(g, x) for g, x, _ in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
    X = np.array([[x[f] for f in feats] for _, x in D]); y = np.array([G.num(g['result']) for g, _ in D])
    S = np.array([int(g['season']) for g, _ in D])
    pred = np.full(len(y), np.nan)
    for s in range(2015, int(S.max()) + 1):
        tr, te = S < s, S == s
        pred[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
    return v[0], {'pr': pred, 'y': y, 'S': S, 'line': np.array([G.num(g['spread_line'], np.nan) for g, _ in D]),
                  'wk': np.array([f"{g['season']}-{g['week']}" for g, _ in D]),
                  'team': np.array([f"{g['home_team']}{g['season']}" for g, _ in D])}


def nfl():
    import multiprocessing as mp
    import nfl_games as G
    F = json.load(open(G.FIT))
    games, box, qbs = G.load(2025)
    G.index_qbs(qbs, games); G.load_qb_teams(2025)
    inj = G.injury_history(games, range(G.INJ_FIRST, 2026))
    _NFL['args'] = (games, box, qbs, inj, F['params'], list(G.FEATS))
    V = NFL_V
    if '--only' in sys.argv:
        V = [V[0]] + [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    with mp.get_context('fork').Pool(int(os.environ.get('PROCS', 4))) as pool:
        res = dict(pool.map(_nfl_one, V))
    b = res['base']
    k1 = (b['S'] >= 2015) & (b['S'] <= 2020); k2 = b['S'] >= 2021
    out = [score(lab, res[lab]['pr'], b['pr'], b['y'], b['line'], k1, k2, [b['wk'], b['team']], {'params': extra})
           for lab, extra in V[1:]]
    save('nfl', out)


if __name__ == '__main__':
    {'nba': nba, 'cbb': cbb, 'nfl': nfl}[sys.argv[1]]()
