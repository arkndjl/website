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
    # game-control rating (team model idea 8; scripts/cfb_control_backtest.mjs, data/cfb_control_backtest.json)
    cp = os.path.join(ROOT, 'data', 'cfb_control_backtest.json')
    if os.path.exists(cp):
        v = json.load(open(cp))['variants'].get('all10l15')
        if v:
            rows.append(row('gc', v['espnOnly']['ll'], 'game-control rating (long memory) on the ESPN-only model', shipped=True))
            if v.get('shipped'):
                rows.append(row('gc:shipped', v['shipped']['ll'], 'game-control rating on HIST_FIT (close target), tune 2021-22, held 2023-26', shipped=True))
    # stored rows other scripts wrote straight into the ledger (public_ratings_cfb.mjs: fpi stack, close target) stay
    if os.path.exists(H.LEDGER):
        have = {r['term'] for r in rows}
        for r in json.load(open(H.LEDGER))['models'].get('cfb_games', {}).get('rows', []):
            if r['term'] not in have and r.get('stored'):
                rows.append({k: v for k, v in r.items() if k not in ('z', 'p', 'q', 'verdict')})
    return {'desc': 'CFB game model (scripts/cfb_model.mjs, history fit)', 'loss': 'win log loss', 'split': 'tune 2017-20, held 2021-26',
            'cluster': 'game day, home team-season', 'source': 'data/cfb_hist_backtest.json', 'rows': rows}


def lineup_adj():
    """lineup-adjusted ratings (scripts/lineup_adj_research.py, Oct 23 2026): the shipped setting of each sport's
    lineup adjustment against the model without it, clustered paired t (game day x home team-season) stored there"""
    R = jload('lineup_adj_research.json')
    ship = {'nba': 'mkt .5 + opp 1'}
    rows = []
    for sp, lab in ship.items():
        r = next(x for x in R.get(sp, []) if x['label'] == lab)
        rows.append(H.from_t(f'{sp}:lineupAdj', r['tune']['t'], r['held']['t'], r['tune']['n'], r['held']['n'], d_held=r['held']['d'],
                             note=f'{lab} ({json.dumps(r["params"])}); abs margin error'))
    return {'desc': 'Lineup-adjusted ratings (scripts/lineup_adj_research.py)', 'loss': 'abs margin error',
            'split': 'NBA tune 2015-21, held 2022-26', 'cluster': 'game day x home team-season (stored)', 'source': 'stored', 'rows': rows}


def control():
    """game-control ratings in the basketball game models (scripts/control_research.py, Oct 23 2026): the setting
    picked on tune against the shipped model, abs margin error, clustered paired t stored there (CBB gc shipped)"""
    rows = []
    p = os.path.join(DATA, 'control_research_nba.json')
    if os.path.exists(p):
        b = json.load(open(p))['best']
        rows.append(H.from_t('nba:gc', b['tune']['t'], b['held']['t'], b['tune']['n'], b['held']['n'], d_held=b['held']['d'],
                             note=f"hl {b['hl']}, carry {b['carry']}, ridge {b['lam']}; abs margin error", shipped=False))
    # CBB: each column added to the shipped inputs (bpi included); gc shipped (best tune t), gm = the margin twin
    p = os.path.join(DATA, 'control_research_cbb.json')
    if os.path.exists(p):
        R = json.load(open(p))
        st = R['setting']
        for k, lab in (('+gc', 'cbb:gc'), ('+gm', 'cbb:gm')):
            r = R['rows'][k]
            rows.append(H.from_t(lab, r['tune'][1], r['held'][1], r['tune'][2], r['held'][2], d_held=r['held'][0],
                                 note=f"hl {st['hl']}, carry {st['carry']}, ridge {st['lam']}; held lined t {r['heldLined'][1]}; abs margin error",
                                 shipped=k == R['shipped']))
    return {'desc': 'Game-control ratings, basketball (scripts/control_research.py)', 'loss': 'abs margin error',
            'split': 'NBA tune 2015-21, held 2022-26; CBB tune 2016-20, held 2021-26', 'cluster': 'game day x home team-season (stored)',
            'source': 'stored', 'rows': rows}


def luck():
    """luck-stripped efficiency (scripts/luck_research.py, Oct 23 2026): the shipped setting against the model without
    it, margin and totals, clustered paired t (game day x home team-season) stored there"""
    R = jload('luck_research.json')
    ship = {'nba': '3 both .75', 'cbb': '3 .5'}
    rows = []
    for sp, lab in ship.items():
        for suf, kind in (('', 'margin'), (' (total)', 'total')):
            r = next(x for x in R.get(sp, []) if x['label'] == lab + suf)
            rows.append(H.from_t(f'{sp}:luck3{"" if kind == "margin" else "Total"}', r['tune']['t'], r['held']['t'], r['tune']['n'],
                                 r['held']['n'], d_held=r['held']['d'], note=f'{lab} ({json.dumps(r["params"])}); abs {kind} error'))
    return {'desc': 'Luck-stripped efficiency (scripts/luck_research.py)', 'loss': 'abs margin / total error',
            'split': 'NBA tune 2015-21, held 2022-26; CBB tune 2016-20, held 2021-26', 'cluster': 'game day x home team-season (stored)',
            'source': 'stored', 'rows': rows}


def nhl_games():
    """NHL game model (scripts/nhl_games.py --fit, data/nhl_games_fit.json): each shipped input's paired test, stored
    there with the split it was chosen on (lined games 2021-23 / 2024-26)"""
    F = jload('nhl_games_fit.json')
    rows = [H.from_t(k, -e['tTune'], -e['tHeld'], d_held=e['dHeld'], note=f"{e['split']}; win log loss x1000", core=k == 'home')
            for k, e in F['evidence'].items() if k in F['feats']]     # evidence 'kept' marks the candidate list, feats the shipped inputs
    return {'desc': 'NHL game win chance (scripts/nhl_games.py)', 'loss': 'win log loss', 'split': 'tune 2017-23 (lined 2021-23), held 2024-26',
            'cluster': 'none (stored t)', 'source': 'stored', 'tested': F.get('updated'), 'rows': rows}


def soccer_games():
    """soccer game model (scripts/soccer_games.py --fit): squad market value, the Oct 24 source-sweep ship, held-out t
    3.9 (4 of 4 seasons); the earlier blend steps (xG, market goals) store losses only, no t (pending)"""
    F = jload('soccer_games_fit.json')
    t = {x['name']: x for x in F['tests']}
    mv, base = t.get('+ squad market value (final model)'), t.get('+ market ratings')
    rows = []
    if mv and base:
        rows.append(H.from_t('squad mv', None, -3.9, d_held=round(base['hold'] - mv['hold'], 5),
                             note=f"Transfermarkt top-18 value; 1X2 log loss held {base['hold']} -> {mv['hold']} (scripts/data/soccer_squad_mv.json.gz)"))
    return {'desc': 'Soccer match model (scripts/soccer_games.py)', 'loss': '1X2 log loss', 'split': f"tune {F['tune'][0]}-{F['holdFrom'] - 1}, held {F['holdFrom']}+",
            'cluster': 'none (stored t)', 'source': 'stored', 'tested': F['asof'][:10], 'rows': rows}


def hockey_fv():
    """hockey prospect FV (scripts/hockey_prospects.py --fit, data/hockey_fit.json): class-out CV over the 2008-19 classes
    (12 folds), each kept driver's single-term t at the draft model and at each post-draft stage (one split, CV only)"""
    F = jload('hockey_fit.json')
    rows = []
    for k in F['kept']:
        e = F['ev'].get(k)
        if e:
            rows.append(H.from_t(f'draft:{k}', -e['t'], None, n_tune=e['of'], note=f"draft model, {e['wins']}/{e['of']} classes, MSE gain {e['gain']}"))
    for st, S in sorted(F.get('stages', {}).items()):
        for k in S['kept']:
            e = S['ev'].get(k)
            if e and k != 'fv0':
                rows.append(H.from_t(f'k{st}:{k}', -e['t'], None, n_tune=e['of'], note=f"after season {st}, {e['wins']}/{e['of']} classes"))
    return {'desc': 'Hockey prospect FV (scripts/hockey_prospects.py)', 'loss': 'outcome MSE (best-3 WAR, FV scale)', 'split': 'class-out CV 2008-19 (no held-out split)',
            'cluster': 'draft class folds', 'source': 'stored', 'tested': F['asof'], 'rows': rows}


def soccer_fv():
    """soccer prospect FV (scripts/soccer_prospects.py --fit, data/soccer_prospects_fit.json): leave-one-season-out over
    the 2013-20 seasons, each kept driver's t (one split, CV only); age, lmv and nomv are the base"""
    F = jload('soccer_prospects_fit.json')
    rows = [H.from_t(k, -F['ev'][k]['t'], None, n_tune=F['ev'][k]['of'], note=f"{F['ev'][k]['wins']}/{F['ev'][k]['of']} seasons")
            for k in F['kept'] if k in F['ev']]
    return {'desc': 'Soccer prospect FV (scripts/soccer_prospects.py)', 'loss': 'outcome MSE (peak value 22-26)', 'split': 'leave-one-season-out 2013-20 (no held-out split)',
            'cluster': 'season folds', 'source': 'stored', 'tested': F['asof'], 'rows': rows}


def nhl_war():
    """NHL projected WAR (scripts/nhl_players.py --fit, data/nhl_war_fit.json; audit W1-D): the Marcel + shrink-target
    projection against the Oct 24 spec, then each kept weight's drop-one t, team GD next season, leave-one-season-out"""
    F = jload('nhl_war_fit.json')
    g = F['gate']
    rows = [H.from_t('pwar vs Oct 24 spec', -g['t'], None, n_tune=g['seasons'], note=f"LOSO R2 {g['r2Old']} -> {F['r2']}, {g['seasonsWon']}/{g['seasons']} seasons")]
    rows += [H.from_t(k, -e['t'], None, note=f"dMSE {e['dMse']}") for k, e in F['evidence'].items() if k in F['w']]
    return {'desc': 'NHL projected WAR (scripts/nhl_players.py)', 'loss': 'team GD/GP squared error, next season', 'split': 'leave-one-season-out (no held-out split)',
            'cluster': 'season folds', 'source': 'stored', 'tested': F['updated'], 'rows': rows}


def soccer_gar():
    """soccer GAR priors (scripts/soccer_gar_tests.py, data/soccer_gar_tests.json; audit W1-F): drop-one of each shipped
    prior from the final team-GD model, leave-one-season-out over 11 seasons; the league scale from 1,022 movers"""
    R = jload('soccer_gar_tests.json')['league']
    rows = [H.from_t(k, -e['t'], None, n_tune=e['of'], note=f"drop-one, {e['wins']}/{e['of']} seasons, dMSE {e['dMse']}") for k, e in R['dropOne'].items()]
    m = R['movers']
    rows.append(H.from_t('league scale (movers)', -m['tGap'], None, n_tune=m['n'], note=f"league gap slope {m['bGap']} on {m['n']} movers"))
    return {'desc': 'Soccer GAR team-GD fit and priors (scripts/soccer_players.py)', 'loss': 'team GD squared error', 'split': 'leave-one-season-out 2016-26 (no held-out split)',
            'cluster': 'season folds', 'source': 'stored', 'rows': rows}


def cfb_recruit_nfl():
    """recruit NFL index (scripts/cfb_recruit_retarget.py, data/cfb_recruit_retarget.json; audit W1-H): each kept block's
    school-held-out t on the 2011-19 classes' NFL outcomes, and the shipped index against the board-fit model by class"""
    R = jload('cfb_recruit_retarget.json')
    rows = []
    for part, lab in (('on', 'P(drafted)'), ('fv', 'FV if drafted')):
        for k, v in R['gains'][part].items():
            rows.append(H.from_t(f'{part}:{k}', -v['t'], None, note=f'{lab} block, school folds'))
    v = R['vsLive']['shipped']
    rows.append(H.from_t('index vs board fit', -v['byClass']['t'], None, n_tune=9, note=f"rank corr gain {v['byClass']['mean']} by class, won {v['byClass']['won']}"))
    return {'desc': 'CFB recruit NFL index (scripts/cfb_recruit_retarget.py)', 'loss': 'NFL outcome rank / log loss', 'split': 'school-held-out CV, 2011-19 classes (no held-out split)',
            'cluster': 'school folds', 'source': 'stored', 'rows': rows}


def cfb_cfp():
    """CFP committee model (scripts/cfb_cfp.py, data/cfb_cfp.json; audit W1-G): field log loss held out 2022-25 against the
    old formula at its best temperature"""
    S = jload('cfb_cfp.json')['selection']
    return {'desc': 'CFP selection, committee Plackett-Luce (scripts/cfb_cfp.py)', 'loss': 'CFP field log loss', 'split': 'tune 2017-21, held 2022-25',
            'cluster': 'none (stored t)', 'source': 'stored',
            'rows': [H.from_t('committee model vs formula', None, S['t'], note=f"held field log loss {S['oldHeldFieldLL']} -> {S['heldFieldLL']}")]}


# terms the first pass (Oct 21 2026) judged noise, removed jointly and re-verified: each adapter scores the shipped
# model against the reduced one ('joint') and re-scores the remaining terms inside the reduced model
DROPS = {'nfl': ['epa'], 'cbb': ['alt', 'mkt', 'prior:fr', 'prior:lastret', 'prior:newmin']}   # newmin: second pass

ADAPTERS = {'nba': nba, 'nfl': nfl, 'cbb': cbb, 'cfb_games': cfb_games, 'cfb_roster': cfb_roster, 'cfb_recruit': cfb_recruit, 'nfl_roster': nfl_roster,
            'lineup_adj': lineup_adj, 'control': control, 'luck': luck, 'nhl_games': nhl_games, 'soccer_games': soccer_games,
            'hockey_fv': hockey_fv, 'soccer_fv': soccer_fv, 'nhl_war': nhl_war, 'soccer_gar': soccer_gar, 'cfb_recruit_nfl': cfb_recruit_nfl,
            'cfb_cfp': cfb_cfp}
STORED = ('cfb_roster', 'cfb_recruit', 'nfl_roster', 'cfb_games', 'lineup_adj', 'control', 'luck', 'nhl_games', 'soccer_games', 'hockey_fv',
          'soccer_fv', 'nhl_war', 'soccer_gar', 'cfb_recruit_nfl', 'cfb_cfp')
# not yet scoreable here (no per-term t stored; their own harnesses re-validate): CFB FV multipliers (cfb_fv_refit.mjs),
# CFB transfer/landing, coach, availability, NFL fantasy
PENDING = {'cbb_board': 'scripts/cbb_fit.py (stores folds helped and pooled OOS gain, no per-row losses; a 5-fold sign test is too coarse to rank drivers)',
           'cfb_fv': 'scripts/cfb_fv_refit.mjs (fold r gains, no per-row losses)',
           'soccer_games:blend': 'scripts/soccer_games.py --fit (the xG and market-goals blend steps store losses, no paired t)',
           'soccer_mv': 'scripts/soccer_mv.py (drop-one MSE deltas, no t)',
           'cbb_mock_combine': 'audit W1-C (PR #387): enters when it merges (data/cbb_combine.json)', 'cfb_transfer': 'scripts/cfb_transfer_fit.py (in-sample se only)', 'nfl_fantasy': 'scripts/nfl_fantasy.py (ablation deltas, no t)',
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
