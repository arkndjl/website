#!/usr/bin/env python3
"""Closing-line training target (team model idea 2, Oct 23 2026): each game model's weights fit against the close
(or results + lam x close), put back on the results' scale, scored on results with the shared harness.

    python3 scripts/close_target_research.py --build nba      # cache a sport's shipped design (nba, nfl, cbb)
    python3 scripts/close_target_research.py nba nfl cbb      # margin weights: lam grid, calibration, screen
    python3 scripts/close_target_research.py --nba-extra      # NBA totals, coach O/U under the close, rating grid
    CT=<out.json> node scripts/cfb_game_backtest.mjs md.json.gz none    # CFB margin weights and the prior's target

The fit itself is harness.fit_ols / walk_ols (close=, lam=, calib=, screen=); lam 0 is the old results fit.
Writes data/close_target.json.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H

CACHE = os.path.join(HERE, '.cache', 'ct')
LAMS = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 9.0, np.inf]
SPLIT = {'nba': (2015, 2021, 2022, 2015), 'nfl': (2015, 2020, 2021, 2015), 'cbb': (2016, 2020, 2021, 2016)}


def load(sp):
    z = np.load(os.path.join(CACHE, sp + '.npz'), allow_pickle=False)
    keys = list(z['keys']); feats = list(z['feats'])
    X = z['X'][:, [keys.index(f) for f in feats]]
    return z, X, feats


def build(sp):
    import harness_rescore as R
    if sp == 'nba':
        import nba_games as N, nba_games_fit as NF
        F = R.jload('nba_games_fit.json')
        games, names = N.load_hist(); inj = NF.load_inj()
        D, X, TX, y, ty, S, line, tline = NF.design(games, names, F['P'], dict(F['params']), inj, F['feats'])
        keys = sorted(X)
        np.savez(f'{CACHE}/nba.npz', X=np.column_stack([X[k] for k in keys]), keys=np.array(keys), feats=np.array(F['feats']), TX=TX, y=y, ty=ty, S=S, line=line, tline=tline,
                 lo=np.array([g.get('Lo') if g.get('Lo') is not None else np.nan for g, _, _ in D], float),
                 day=np.array([g['tip'][:10] for g, _, _ in D]), team=np.array([f"{g['h']}|{g['S']}" for g, _, _ in D]), gid=np.array([str(g['id']) for g, _, _ in D]))
    elif sp == 'nfl':
        import nfl_games as G
        F = R.jload('nfl_games_fit.json'); last = 2025
        games, box, qbs = G.load(last); G.index_qbs(qbs, games); G.load_qb_teams(last)
        inj = G.injury_history(games, range(G.INJ_FIRST, last + 1))
        _, data = G.walk(games, box, qbs, F['params'])
        for g, x, _ in data:
            r = inj.get(g['game_id'])
            if r: x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        Dd = [(g, x, tx) for g, x, tx in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
        feats = list(G.FEATS); allk = sorted(Dd[0][1])
        tk = sorted(Dd[0][2]) if isinstance(Dd[0][2], dict) else []
        np.savez(f'{CACHE}/nfl.npz', X=np.array([[x.get(f, 0.0) for f in allk] for _, x, _ in Dd], float), keys=np.array(allk), feats=np.array(feats),
                 y=np.array([G.num(g['result']) for g, _, _ in Dd], float), ty=np.array([G.num(g['home_score']) + G.num(g['away_score']) for g, _, _ in Dd], float),
                 S=np.array([int(g['season']) for g, _, _ in Dd]), line=np.array([G.num(g['spread_line'], np.nan) for g, _, _ in Dd]),
                 tline=np.array([G.num(g['total_line'], np.nan) for g, _, _ in Dd]),
                 day=np.array([f"{g['season']}|{g['week']}" for g, _, _ in Dd]), team=np.array([f"{g['home_team']}|{g['season']}" for g, _, _ in Dd]),
                 gid=np.array([g['game_id'] for g, _, _ in Dd]))
        json.dump({'tkeys': tk, 'params': F['params']}, open(f'{CACHE}/nfl_meta.json', 'w'))
    elif sp == 'cbb':
        import cbb_games as C
        F = R.jload('cbb_games_fit.json'); P, feats = F['params'], list(F['feats'])
        games, btname, d1s, tprior, avs = C.load_all()
        W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        np.savez(f'{CACHE}/cbb.npz', X=Xm, keys=np.array(feats), feats=np.array(feats), TX=TX, y=y, ty=ty, S=S, line=line, tline=tline, d1=d1,
                 day=np.array([g['date'][:10] for g, _, _ in D]), team=np.array([f"{g['home']}|{g['season']}" for g, _, _ in D]),
                 gid=np.array([str(g.get('id', '')) for g, _, _ in D]))


def lab(lam):
    return 'inf' if np.isinf(lam) else f'{lam:g}'


def run(sp):
    z, X, feats = load(sp)
    y, S, L = z['y'], z['S'], z['line']
    t0, t1, h0, first = SPLIT[sp]
    train = z['d1'] if 'd1' in z.files else None
    valid = np.ones(len(y), bool) if train is None else train.copy()
    cl = [z['day'], z['team']]
    home = [feats.index('home')] if 'home' in feats else []
    base = H.walk_ols(X, y, S, first, train=train)
    ok = ~np.isnan(base) & valid
    tune, held = H.season_masks(S, (t0, t1), h0, ok)
    lined = ~np.isnan(L)
    lb = H.ae(base, y)
    out = {'feats': feats, 'n': {'tune': int(tune.sum()), 'held': int(held.sum()), 'lined': int((lined & ok).sum())},
           'base': {'tuneMae': round(float(lb[tune].mean()), 4), 'heldMae': round(float(lb[held].mean()), 4),
                    'heldMaeLined': round(float(lb[held & lined].mean()), 4),
                    'closeHeldMae': round(float(H.ae(L, y)[held & lined].mean()), 4)},
           'grid': []}
    side = lambda a, m: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in H.paired(a[m], lb[m], [c[m] for c in cl]).items() if k in ('d', 't', 'n', 'G')}
    for screen in (None, 5.0):
        for calib in ((), tuple(home)):
            for lam in LAMS:
                if lam == 0 and (screen or calib):
                    continue
                pr = H.walk_ols(X, y, S, first, train=train, close=L, lam=lam, calib=calib, screen=screen)
                la = H.ae(pr, y)
                row = {'lam': lab(lam), 'calib': 'home' if calib else 'scale', 'screen': screen,
                       'tune': side(la, tune), 'held': side(la, held), 'heldLined': side(la, held & lined),
                       'tuneMae': round(float(la[tune].mean()), 4), 'heldMae': round(float(la[held].mean()), 4),
                       'gapClose': round(float(np.mean(np.abs(pr - L)[held & lined])), 4)}
                out['grid'].append(row)
                print(sp, row['lam'], row['calib'], screen, 'tune', row['tuneMae'], row['tune']['t'], 'held', row['heldMae'], row['held']['t'], 'gap', row['gapClose'], flush=True)
    # weights: results fit vs close fit on every season (what the close changes)
    tr = np.ones(len(y), bool) if train is None else train
    wr = H.fit_ols(X[tr], y[tr])
    wc = H.fit_ols(X[tr], y[tr], L[tr], np.inf, calib=tuple(home), screen=5.0)
    out['weights'] = {f: [round(float(a), 4), round(float(b), 4)] for f, a, b in zip(feats, wr, wc)}
    best = min((r for r in out['grid'] if r['lam'] != '0'), key=lambda r: r['tuneMae'])
    out['best'] = best
    return out


def nba_extra():
    """NBA totals weights on the closing total; the coach O/U residual (an Oct 21 near miss) under that fit; the
    rating-memory grid scored on 2015-21 by the close instead of results (which label picks better held-out settings)"""
    import multiprocessing as mp
    import nba_games as N
    import nba_games_fit as NF
    import nba_coaches as C
    from nba_coach_research import shrunk
    z = np.load(os.path.join(CACHE, 'nba.npz'))
    TX, ty, S, T, cl = z['TX'], z['ty'], z['S'], z['tline'], [z['day'], z['team']]
    games, names = N.load_hist()
    out = {'totals': [], 'coachOU': [], 'grid': []}

    def judge(new, base):
        ok = ~np.isnan(base)
        tu, he = H.season_masks(S, (2015, 2021), 2022, ok)
        la, lb = H.ae(new, ty), H.ae(base, ty)
        a, h = (H.paired(la[m], lb[m], [c[m] for c in cl]) for m in (tu, he))
        return {'tune': [round(a['d'], 4), round(a['t'], 2)], 'held': [round(h['d'], 4), round(h['t'], 2)]}
    base = H.walk_ols(TX, ty, S, 2015)
    for lam in LAMS[1:]:
        out['totals'].append({'lam': lab(lam), **judge(H.walk_ols(TX, ty, S, 2015, close=T, lam=lam, screen=5.0), base)})
    by = {str(g['id']): g for g in games}
    G = [by[i] for i in z['gid']]
    CB = C.by_game(G)
    order = np.argsort([g['tip'] for g in G], kind='stable')
    for n0 in (100, 300):
        ou, c = {}, np.zeros(len(G))
        for i in order:
            ch, ca = CB[G[i]['id']][0]['id'], CB[G[i]['id']][1]['id']
            c[i] = shrunk(ou, ch, n0) + shrunk(ou, ca, n0)
            if not np.isnan(T[i]):
                for cc in (ch, ca):
                    a = ou.setdefault(cc, [0.0, 0]); a[0] += ty[i] - T[i]; a[1] += 1
        TXc = np.column_stack([TX, c])
        for lam in LAMS:
            b = H.walk_ols(TX, ty, S, 2015, close=T, lam=lam)
            n = H.walk_ols(TXc, ty, S, 2015, close=T, lam=lam)
            out['coachOU'].append({'n0': n0, 'lam': lab(lam), 'vsSameFit': judge(n, b), 'vsShipped': judge(n, base)})
    F = json.load(open(N.FIT))
    prm, feats, inj = dict(F['params']), list(F['feats']), NF.load_inj()
    cands = [prm] + [{**prm, 'hl': float(hl), 'carry': c} for hl in (12, 20, 30) for c in (0.3, 0.5, 0.7)]
    cands += [{**prm, k: v} for k, vs in (('mk', (0.05, 0.15, 0.25)), ('mrev', (0.3, 0.7)), ('rhl', (5.0, 20.0)), ('elo_k', (15.0, 25.0))) for v in vs]
    uc = list({json.dumps(c, sort_keys=True): c for c in cands}.values())
    _G['nba'] = (games, names, F['P'], inj, feats)
    with mp.get_context('fork').Pool(3) as pool:
        preds = pool.map(_nba_grid_one, uc)
    y, L = z['y'], z['line']
    ok = ~np.isnan(preds[0])
    tu, he = H.season_masks(S, (2015, 2021), 2022, ok)
    ln = ~np.isnan(L)
    for p, pr in zip(uc, preds):
        out['grid'].append({'p': {k: v for k, v in p.items() if prm.get(k) != v}, 'tuneRes': round(float(H.ae(pr, y)[tu].mean()), 4),
                            'tuneClose': round(float(H.ae(pr, L)[tu & ln].mean()), 4), 'heldRes': round(float(H.ae(pr, y)[he].mean()), 4)})
    for k in ('tuneRes', 'tuneClose'):
        b = min(out['grid'], key=lambda r: r[k])
        out['pickedBy_' + k] = {'p': b['p'], 'heldRes': b['heldRes'], 'heldShipped': out['grid'][0]['heldRes']}
    return out


_G = {}


def _nba_grid_one(p):
    import nba_games as N
    import nba_games_fit as NF
    games, names, P, inj, feats = _G['nba']
    D, X, TX, y, ty, S, line, tline = NF.design(games, names, P, p, inj, feats)
    return NF.wf(NF.mat(X, feats), y, S)


def main(args):
    path = os.path.join(ROOT, 'data', 'close_target.json')
    res = json.load(open(path)) if os.path.exists(path) else {}
    if args and args[0] == '--build':
        for sp in args[1:]:
            build(sp)
        return
    if args and args[0] == '--nba-extra':
        res['nbaExtra'] = nba_extra()
    else:
        for sp in args or ['nba', 'nfl', 'cbb']:
            res[sp] = run(sp)
    with open(path, 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main(sys.argv[1:])
