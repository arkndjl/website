#!/usr/bin/env python3
"""Game-control ratings (scripts/control_ratings.py) as an input to the NBA and college basketball game models,
walk-forward on each model's shipped design, scored through the harness (paired abs margin error, clustered by game
day x home team-season). Variants (half-life, carry, ridge, form, ESPN's win probability vs score-only) are picked on
the tuning seasons alone; held out is scored once.
  python3 scripts/control_research.py nba|cbb      # writes data/control_research_<sport>.json
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H
import control_ratings as CR


def nba():
    import nba_games as N
    import nba_games_fit as NF
    F = json.load(open(os.path.join(ROOT, 'data', 'nba_games_fit.json')))
    games, names = N.load_hist()
    inj = NF.load_inj()
    feats = list(F['feats'])
    D, X, TX, y, ty, S, line, tline = NF.design(games, names, F['P'], dict(F['params']), inj, feats)
    gl = [(g['id'], g['tip'][:10], g['S'], g['h'], g['a'], bool(g['n'])) for g in games if g.get('fin')]
    return dict(ids=[g['id'] for g, _, _ in D], X=X, y=y, S=S, feats=feats, games=gl, line=line,
                day=np.array([g['tip'][:10] for g, _, _ in D]), team=np.array([f"{g['h']}|{g['S']}" for g, _, _ in D]),
                tune=(N.SCORE_FROM, N.HOLD_FROM - 1), held=N.HOLD_FROM, first=N.SCORE_FROM, ok=None,
                pred=lambda Xm: NF.wf(Xm, y, S))


def cbb():
    import cbb_games as C
    F = json.load(open(os.path.join(ROOT, 'data', 'cbb_games_fit.json')))
    P, feats = F['params'], list(F['feats'])
    games, btname, d1s, tprior, avs = C.load_all()
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xa, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    X = {f: Xa[:, i] for i, f in enumerate(feats)}
    gl = [(g['id'], g['date'][:10], g['season'], g['home'], g['away'], bool(g.get('neutral'))) for g in games if g.get('hs') is not None]
    return dict(ids=[g['id'] for g, _, _ in D], X=X, y=y, S=S, feats=feats, games=gl, line=line,
                day=np.array([g['date'][:10] for g, _, _ in D]), team=np.array([f"{g['home']}|{g['season']}" for g, _, _ in D]),
                tune=(C.SCORE0, C.TUNE_END), held=C.TUNE_END + 1, first=C.SCORE0, ok=d1, minn=10,
                pred=lambda Xm: C.walk_pred(Xm, y, S, d1))


def main(sport):
    M = {'nba': nba, 'cbb': cbb}[sport]()
    y, S, feats = M['y'], M['S'], M['feats']
    Xb = np.column_stack([M['X'][f] for f in feats])
    base = M['pred'](Xb)
    ok = ~np.isnan(base) if M['ok'] is None else ~np.isnan(base) & M['ok']
    tune, held = H.season_masks(S, M['tune'], M['held'], ok)
    cl = [M['day'], M['team']]
    lb = H.ae(base, y)
    recs = CR.records(sport)
    ctl = {'free': CR.game_control(sport, recs), 'espn': CR.game_control(sport, recs, kind='espn')}
    have = np.array([i in ctl['free'] for i in M['ids']])
    print(sport, len(M['ids']), 'rows,', int(have.sum()), 'with control;', len(ctl['espn']), 'with ESPN win prob', flush=True)

    def run(kind='free', hl=None, carry=0.5, lam=3.0, form='probit'):
        f, _ = CR.ratings(M['games'], ctl[kind], hl=hl, carry=carry, lam=lam, form=form, minn=M.get('minn', 0))
        col = np.array([f.get(i, 0.0) for i in M['ids']])
        p = M['pred'](np.column_stack([Xb, col]))
        lc = H.ae(p, y)
        side = lambda m: H.paired(lc[m], lb[m], [c[m] for c in cl])
        return {'kind': kind, 'hl': hl, 'carry': carry, 'lam': lam, 'form': form, 'tune': side(tune), 'held': side(held),
                'maeTune': round(float(np.nanmean(lc[tune])), 4), 'maeHeld': round(float(np.nanmean(lc[held])), 4)}, col, p

    out = {'sport': sport, 'feats': feats, 'base': {'maeTune': round(float(lb[tune].mean()), 4), 'maeHeld': round(float(lb[held].mean()), 4)},
           'sd': CR.SD[sport], 'grid': []}
    grid = [dict(hl=hl, carry=c, lam=l, form='probit') for hl in (None, 30, 60) for c in (0.3, 0.6, 1.0) for l in (1.5, 6.0)]
    best = None
    for g in grid:
        r, _, _ = run(**g)
        out['grid'].append(r)
        print(json.dumps({k: (v if not isinstance(v, dict) else {'d': round(v['d'], 4), 't': round(v['t'], 2)}) for k, v in r.items()}), flush=True)
        if best is None or r['tune']['t'] < best['tune']['t']:
            best = r
    out['best'] = best
    # ESPN's own win probability at the best setting (seasons it exists)
    r, _, _ = run(kind='espn', **{k: best[k] for k in ('hl', 'carry', 'lam', 'form')})
    out['espn'] = r
    print('espn', json.dumps(r), flush=True)
    json.dump(out, open(os.path.join(ROOT, 'data', f'control_research_{sport}.json'), 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1])
