#!/usr/bin/env python3
"""Re-score every model's kept terms through the shared harness (scripts/harness.py) -> data/model_ledger.json.

    python3 scripts/harness_rescore.py               # every model this script can rebuild, then the ledger
    python3 scripts/harness_rescore.py nba cbb       # some models (others keep their last rows in the ledger)
    python3 scripts/harness_rescore.py --ledger      # re-judge the saved rows only (no refits)

Each adapter rebuilds its model's walk-forward design with the shipped settings, takes each kept term out, refits
the walk-forward and scores both splits on the model's own loss, paired per row with cluster-robust errors.
Models whose data can't be rebuilt here enter from their own stored backtest t statistics ('stored': true); the
FDR control runs over every row at once (harness.judge). Rows are cached per model in scripts/.cache/harness/.
"""
import gzip
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H

CACHE = os.path.join(HERE, '.cache', 'harness')
DATA = os.path.join(ROOT, 'data')


def jload(name):
    return json.load(open(os.path.join(DATA, name)))


def joint(full, red, y, tune, held, cl, without):
    """the shipped model against the one without every dropped term, both splits (d < 0: the reduced model is better)"""
    if not without:
        return {}
    a, b = H.ae(red, y), H.ae(full, y)
    side = lambda m: {k: (round(v, 5) if isinstance(v, float) else v) for k, v in H.paired(a[m], b[m], [c[m] for c in cl]).items()}
    return {'dropped': list(without), 'joint': {'tune': side(tune), 'held': side(held),
            'tuneMae': [round(float(b[tune].mean()), 4), round(float(a[tune].mean()), 4)], 'heldMae': [round(float(b[held].mean()), 4), round(float(a[held].mean()), 4)]}}


# ---------------------------------------------------------------- NBA game model
def nba():
    import nba_games as N
    import nba_games_fit as NF
    F = jload('nba_games_fit.json')
    games, names = N.load_hist()
    inj = NF.load_inj()
    P, prm, feats = F['P'], dict(F['params']), list(F['feats'])
    D, X, TX, y, ty, S, line, tline = NF.design(games, names, P, prm, inj, feats)
    day = np.array([g['tip'][:10] for g, _, _ in D])
    team = np.array([f"{g['h']}|{g['S']}" for g, _, _ in D])
    pr = lambda fs: NF.wf(NF.mat(X, fs), y, S)
    full = pr(feats)
    ok = ~np.isnan(full)
    tune, held = H.season_masks(S, (N.SCORE_FROM, N.HOLD_FROM - 1), N.HOLD_FROM, ok)
    rows = H.drop_one(pr, feats, y, tune, held, cluster=[day, team], core=('eff', 'home'), base=full)
    # design-time terms: rookies at slot value (rk) and their college BPM (rkc), each switched off in the walk
    lf = H.ae(full, y)
    for k in ('rk', 'rkc'):
        if not prm.get(k):
            continue
        q = dict(prm, **{k: 0})
        if k == 'rk':
            q['rkc'] = 0
        Xq = NF.design(games, names, P, q, inj, feats)[1]
        lw = H.ae(NF.wf(NF.mat(Xq, feats), y, S), y)
        rows.append(H.record(k, H.paired(lf[tune], lw[tune], [day[tune], team[tune]]), H.paired(lf[held], lw[held], [day[held], team[held]]),
                             tune_loss=(lf[tune].mean(), lw[tune].mean()), held_loss=(lf[held].mean(), lw[held].mean()),
                             note='walk rebuilt with the term off'))
    return {'desc': 'NBA game margin (scripts/nba_games_fit.py)', 'loss': 'abs margin error', 'split': f'tune {N.SCORE_FROM}-{N.HOLD_FROM - 1}, held {N.HOLD_FROM}-26',
            'cluster': 'game day x home team-season', 'source': 'rebuilt', 'rows': rows}


# ---------------------------------------------------------------- NFL game model
def nfl(without=()):
    import nfl_games as G
    F = jload('nfl_games_fit.json')
    last = 2025
    games, box, qbs = G.load(last)
    G.index_qbs(qbs, games); G.load_qb_teams(last)
    inj = G.injury_history(games, range(G.INJ_FIRST, last + 1))
    _, data = G.walk(games, box, qbs, F['params'])
    for g, x, _ in data:
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
    Dd = [(g, x) for g, x, _ in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
    feats = list(G.FEATS)
    X = {f: np.array([x[f] for _, x in Dd], float) for f in feats}
    y = np.array([G.num(g['result']) for g, _ in Dd], float)
    S = np.array([int(g['season']) for g, _ in Dd])
    wk = np.array([f"{g['season']}|{g['week']}" for g, _ in Dd])
    team = np.array([f"{g['home_team']}|{g['season']}" for g, _ in Dd])
    line = np.array([G.num(g['spread_line'], np.nan) for g, _ in Dd])
    pr = lambda fs: H.walk_ols(np.column_stack([X[f] for f in fs]), y, S, 2015)
    full = pr(feats)
    tune, held = H.season_masks(S, (2015, 2020), 2021, ~np.isnan(full))
    check = {'heldMaeLined': round(float(H.ae(full, y)[held & ~np.isnan(line)].mean()), 3), 'shipped': jload('nfl_games_fit.json')['test']['2021-25 (held out)']['maeModel']}
    keep = [f for f in feats if f not in without]
    red = pr(keep)
    rows = H.drop_one(pr, keep, y, tune, held, cluster=[wk, team], core=('home',), base=red)
    return {'desc': 'NFL game margin (scripts/nfl_games.py --fit)', 'loss': 'abs margin error', 'split': 'tune 2015-20, held 2021-25',
            'cluster': 'week x home team-season', 'source': 'rebuilt', 'rows': rows, 'check': check,
            **joint(full, red, y, tune, held, [wk, team], without)}


# ---------------------------------------------------------------- college basketball game model and its preseason prior
_CBB = {}


def _cbb_walk(pf):
    import cbb_games as C
    C.PRIOR_F = pf
    games, btname, d1s, tprior, avs, P, feats = _CBB['args']
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    return C.walk_pred(Xm, y, S, d1)


def cbb(without=()):
    import multiprocessing as mp
    import cbb_games as C
    F = jload('cbb_games_fit.json')
    P, feats = F['params'], list(F['feats'])
    games, btname, d1s, tprior, avs = C.load_all()
    _CBB['args'] = (games, btname, d1s, tprior, avs, P, feats)
    ship_pf = list(C.PRIOR_F)
    base_pf = [k for k in ship_pf if 'prior:' + k not in without]
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xa, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    pr = lambda fs: C.walk_pred(Xa[:, [feats.index(f) for f in fs]], y, S, d1)
    full = pr(feats)
    ok = ~np.isnan(full) & d1
    tune, held = H.season_masks(S, (C.SCORE0, C.TUNE_END), C.TUNE_END + 1, ok)
    day = np.array([g['date'][:10] for g, _, _ in D])
    team = np.array([f"{g['home']}|{g['season']}" for g, _, _ in D])
    cl = [day, team]
    check = {'heldMaeLined': round(float(H.ae(full, y)[held & ~np.isnan(line)].mean()), 3), 'shipped': F['test']['2021-26 (held out)']['maeModel']}
    gfeats = [f for f in feats if f not in without]
    if base_pf != ship_pf:
        C.PRIOR_F = base_pf
        W, rows2 = C.run_walk(P, games, tprior, btname, d1s, avs)
        Xa = C.matrices(rows2, feats)[1]
    red = pr(gfeats)
    jt = joint(full, red, y, tune, held, cl, without)
    full = red
    out = H.drop_one(pr, gfeats, y, tune, held, cluster=cl, core=('eff', 'home'), base=full)
    terms = [k for k in base_pf if k != 'one']
    _CBB['args'] = (games, btname, d1s, tprior, avs, P, gfeats)
    with mp.get_context('fork').Pool(3) as pool:
        preds = pool.map(_cbb_walk, [[z for z in base_pf if z != k] for k in terms])
    lf = H.ae(full, y)
    for k, pw in zip(terms, preds):
        lw = H.ae(pw, y)
        out.append(H.record('prior:' + k, H.paired(lf[tune], lw[tune], [c[tune] for c in cl]), H.paired(lf[held], lw[held], [c[held] for c in cl]),
                            tune_loss=(lf[tune].mean(), np.nanmean(lw[tune])), held_loss=(lf[held].mean(), np.nanmean(lw[held])),
                            note='preseason prior term; walk rebuilt without it'))
    C.PRIOR_F = ship_pf
    return {'desc': 'College basketball game margin and preseason prior (scripts/cbb_games.py)', 'loss': 'abs margin error',
            'split': f'tune {C.SCORE0}-{C.TUNE_END}, held {C.TUNE_END + 1}-{C.LAST}', 'cluster': 'game day x home team-season',
            'source': 'rebuilt', 'rows': out, 'check': check, **jt}


# ---------------------------------------------------------------- stored evidence (models this script can't rebuild here)
def cfb_roster():
    """CFB roster-turnover prior (scripts/cfb_roster_prior.py): each kept term at the forward step that kept it,
    paired per game log loss, tune 2016-20 / held 2021-26 (portal terms 2022-23 / 2024-26)"""
    R = jload('cfb_roster_prior.json')
    rows = []
    for blk in ('roster', 'portal'):
        kept = R[blk]['kept']
        for e in R[blk]['log']:
            a = e.get('add')
            if a in kept and e['to'] == kept[:kept.index(a)] or (a in kept and blk == 'portal' and e['to'] == [k for k in kept if k != a]):
                if any(r['term'] == a for r in rows):
                    continue
                rows.append(H.from_t(a, e['tune']['t'], e['hold']['t'], d_held=-e['hold']['dLogLoss'], note=f'{blk} step, log loss'))
    return {'desc': 'CFB preseason roster prior (scripts/cfb_roster_prior.py)', 'loss': 'win log loss', 'split': 'tune 2016-20, held 2021-26',
            'cluster': 'none (stored i.i.d. t)', 'source': 'stored', 'rows': rows}


def cfb_recruit():
    """CFB recruit model (scripts/cfb_recruit_fit.py): kept blocks and drivers, school-held-out CV t (one split)"""
    R = jload('cfb_recruit_fit.json')
    rows = []
    for part, lab in (('on', 'P(on a roster)'), ('fv', 'FV')):
        for k, v in R['gains'][part].items():
            if v.get('kept'):
                rows.append(H.from_t(f'{part}:{k}', -v['t'], None, note=f'{lab} block, CV ({R["gainKeys"][part]})'))
        for k, v in R['drivers'][part].items():
            if v.get('kept'):
                rows.append(H.from_t(f'{part}:{k}', -v.get('tFinal', v['t']), None, note=f'{lab} driver, CV ({R["gainKeys"][part]})'))
    return {'desc': 'CFB recruit FV and roster odds (scripts/cfb_recruit_fit.py)', 'loss': 'log loss / FV squared error', 'split': 'school-held-out CV only',
            'cluster': 'school folds', 'source': 'stored', 'rows': rows}


def nfl_roster():
    R = jload('nfl_roster_fit.json')['test']
    a, b = R['all1520'], R['all2125']
    return {'desc': 'NFL offseason roster prior (scripts/nfl_roster.py)', 'loss': 'abs margin error', 'split': 'tune 2015-20, held 2021-25',
            'cluster': 'none (stored i.i.d. t)', 'source': 'stored',
            'rows': [H.from_t('moves', a[1], b[1], a[2], b[2], d_held=-b[0], note='roster moves in projected WAR, as one prior term')]}


def cfb_games():
    # scripts/cfb_hist_backtest.mjs (data/cfb_hist_backtest.json): the ESPN history 2015-26, walk-forward, paired t
    # clustered by game day and home team-season; tune 2017-20, held out 2021-26 (PFN inputs: tune 2021-22, held 2023-26)
    bt = json.load(open(os.path.join(ROOT, 'data', 'cfb_hist_backtest.json')))
    row = lambda term, c, note, **kw: H.from_t(term, c['tune']['t'], c['held']['t'], c['tune']['n'], c['held']['n'], d_held=c['held']['d'], note=note, **kw)
    rows = [row('pooled fit (prior + margin weights)', bt['scheme']['pooledBoth']['vsLive'], 'weights pooled from 2016 vs last season / last two')]
    steps = {x['add']: x for x in bt['inputs']['steps'] if x.get('add')}
    for k in ('p4', 'aggr', 'drv', 'stuff', 'line'):
        c = steps.get(k) or bt['inputs']['alone'].get(k)
        if c:
            rows.append(row(k, c, 'forward step' if k in steps else 'alone on the base', shipped=k in ('p4', 'aggr')))
    for k, c in bt['pfn']['inputs'].items():
        rows.append(row(k, c, 'PFN returning production, on the chosen inputs', shipped=k == 'ret'))
    for k in ('rosterAv', 'rosterAvRest'):
        rows.append(row('prior:' + k, bt['pfn']['prior'][k], 'returning college WAR in the preseason prior', shipped=False))
    rows.append(row('shipped vs live', bt['ship']['vsLive'], 'HIST_FIT vs the live scheme, 2021-26', shipped=True))
    return {'desc': 'CFB game model (scripts/cfb_model.mjs, history fit)', 'loss': 'win log loss', 'split': 'tune 2017-20, held 2021-26',
            'cluster': 'game day, home team-season', 'source': 'data/cfb_hist_backtest.json', 'rows': rows}


# terms the first pass (Oct 21 2026) judged noise, removed jointly and re-verified: each adapter scores the shipped
# model against the reduced one ('joint') and re-scores the remaining terms inside the reduced model
DROPS = {'nfl': ['epa'], 'cbb': ['alt', 'mkt', 'prior:fr', 'prior:lastret', 'prior:newmin']}   # newmin: second pass

ADAPTERS = {'nba': nba, 'nfl': nfl, 'cbb': cbb, 'cfb_games': cfb_games, 'cfb_roster': cfb_roster, 'cfb_recruit': cfb_recruit, 'nfl_roster': nfl_roster}
# not yet scoreable here (no per-term t stored; their own harnesses re-validate): CFB FV multipliers (cfb_fv_refit.mjs),
# CFB transfer/landing, coach, availability, NFL fantasy
PENDING = {'cbb_board': 'scripts/cbb_fit.py (stores folds helped and pooled OOS gain, no per-row losses; a 5-fold sign test is too coarse to rank drivers)',
           'cfb_fv': 'scripts/cfb_fv_refit.mjs (fold r gains, no per-row losses)', 'cfb_transfer': 'scripts/cfb_transfer_fit.py (in-sample se only)', 'nfl_fantasy': 'scripts/nfl_fantasy.py (ablation deltas, no t)',
           }


def main(args):
    os.makedirs(CACHE, exist_ok=True)
    want = [a for a in args if not a.startswith('--')] or list(ADAPTERS)
    if '--ledger' not in args:
        for name in want:
            print('rescoring', name, flush=True)
            m = ADAPTERS[name](*([DROPS[name]] if DROPS.get(name) else []))
            old = os.path.join(CACHE, f'{name}.json')
            if os.path.exists(old):
                m.setdefault('removed', json.load(open(old)).get('removed', []))     # dropped terms' rows from the pass that dropped them
            json.dump(m, open(os.path.join(CACHE, f'{name}.json'), 'w'), indent=1)
    models = {}
    for name in ADAPTERS:
        p = os.path.join(CACHE, f'{name}.json')
        if os.path.exists(p):
            models[name] = json.load(open(p))
            models[name]['rows'] = [r for r in models[name]['rows'] if not r.get('removed')] + models[name].pop('removed', [])
        elif os.path.exists(H.LEDGER) and name in json.load(open(H.LEDGER))['models']:
            models[name] = json.load(open(H.LEDGER))['models'][name]
    H.write_ledger(models, pending=PENDING)
    H.show()


if __name__ == '__main__':
    main(sys.argv[1:])
