#!/usr/bin/env python3
"""CBB game model: the preseason prior's fvtop / agew train/serve check (basketball audit, Nov 4 2026).

History (cbb_games.team_fv) counts a returner or transfer only with a line the season before (by[y - 1]); a player back
from a lost season (last line two or more seasons back) is in neither fvtop nor agew. Live (team_fv_live) took each
player's latest line before the season, whatever its year, so the 2027 prior counted 98 lost-season players (Caden
Pierce, Kalu Anya, Ty Rodgers, ...) the model was never fit on. This replays history the way live served it:

    base   team_fv as fit (by[y - 1] lines only)
    serve  plus the season's players whose latest line is from y - 2 or y - 3 (age carried to Nov 1 of season y),
           at the base arm's prior coefficients (what live served)
    both   the same features, prior coefficients refit on them

Shipped params and inputs (data/cbb_games_fit.json), every prior term rebuilt from the research seasons, cres kept;
scored like cbb_prior_lookahead_research.py (walk-forward margin MAE on D-I games, tune 2016-20, held 2021-26, paired
t, lined games). Writes data/cbb_fvgap_research.json. Needs the BPI cache (public_ratings.py --cbb-bpi).

Result (Nov 4 2026, 706 team seasons' fvtop change): serve MAE -.0003 tune (t -3.54), -.0002 held (t -1.55), lined
-.0001 (t -1.18); both -.0008 (t -4.59) / -.0004 (t -2.12) / lined 0.0 (t +0.16). The mismatch costs nothing, so live
keeps serving them (the 2027 prior moves under .1 a team either way). History's version knows which lost-season players
went on to play, so neither arm is a clean case for refitting with them.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_games as C

OUT = os.path.join(C.ROOT, 'data', 'cbb_fvgap_research.json')
_team_fv = C.team_fv


def team_fv_serve(y, by):
    """team_fv plus lost-season players at their latest line, as team_fv_live served them before the fix"""
    out = _team_fv(y, by)
    add = defaultdict(lambda: {'es': [], 'agen': 0.0, 'aged': 0.0})
    for pid, r in by[y].items():
        if by[y - 1].get(pid) or r['yr'] == 'Fr':
            continue
        p = next((by[y - k][pid] for k in (2, 3) if y - k in by and pid in by[y - k] and by[y - k][pid]['min_per']), None)
        if not p:
            continue
        x = C.research_feats(p, r['team'])
        if x['age']:
            x['age'] += (y - 1) - int(p['year'])
        f = add[r['team']]
        f['es'].append(C.player_fv(x, 'returner'))
        if x['age']:
            share = float(p['min_per']) / 100
            f['agen'] += x['age'] * share; f['aged'] += share
    if not add:
        return out
    # recompute fvtop / agew with them: team_fv's own lists are not exposed, so rebuild the top 5 and age from scratch
    base = defaultdict(lambda: {'es': [], 'agen': 0.0, 'aged': 0.0})
    for pid, r in by[y].items():
        p = by[y - 1].get(pid)
        b = base[r['team']]
        if p and p['min_per']:
            x = C.research_feats(p, r['team'])
            b['es'].append(C.player_fv(x, 'returner'))
            if x['age']:
                share = float(p['min_per']) / 100
                b['agen'] += x['age'] * share; b['aged'] += share
        elif r['yr'] == 'Fr':
            import math
            lr = [-math.log(min(float(v), 500)) for v in (r.get('on3rk'), r.get('rk247')) if v not in (None, '', 'nan') and float(v) > 0]
            l = sum(lr) / len(lr) if lr else -math.log(600)
            b['es'].append(C.player_fv({'rg_lrk': l, 'top': max(0.0, l + math.log(25)), 'top5': max(0.0, l + math.log(5)), 'yr': 1.0}, 'newcomer'))
    for t, a in add.items():
        b = base[t]
        es = sorted(b['es'] + a['es'], reverse=True)[:5]
        n, dd = b['agen'] + a['agen'], b['aged'] + a['aged']
        o = out.setdefault(t, {})
        o['fvtop'] = round(sum(es) / len(es) - 20, 3) if es else 0.0
        o['agew'] = round(n / dd - 21, 3) if dd else 0.0
    return out


def prior(serve, old):
    C.team_fv = team_fv_serve if serve else _team_fv
    tp = C.team_prior_hist()
    C.team_fv = _team_fv
    for y, T in tp.items():
        for t, v in T.items():
            c = (old.get(y) or {}).get(t, {}).get('cres')
            if c is not None:
                v['cres'] = c
    return tp


def main():
    F = json.load(open(C.FIT))
    P, feats = F['params'], F['feats']
    old = json.load(open(C.TPRIOR))
    games, btname, d1s, _, avs = C.load_all()
    tps = {False: prior(False, old), True: prior(True, old)}
    nch = sum(1 for y in tps[True] for t, v in tps[True][y].items()
              if abs(v.get('fvtop', 0) - tps[False][y].get(t, {}).get('fvtop', 0)) > 1e-9)
    print('team seasons with a different fvtop:', nch, flush=True)

    def run(sv, coefs=None):
        W = C.Walk(P, tps[sv], btname, coefs=dict(coefs) if coefs else None)
        by_s, rows = defaultdict(list), []
        for g in games:
            by_s[g['season']].append(g)
        for s in sorted(by_s):
            gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))
            C.season_walk(W, s, gs, d1s[s], avs.get(s), lambda g, x, tx, R: rows.append((g, x, tx)) if g.get('hs') is not None else None)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        return (C.walk_pred(Xm, y, S, d1), y, S, d1, line, {k: round(float(v), 3) for k, v in W.prior_coef(C.LAST + 1).items()}), W.pcoef
    R, pc = {}, {}
    R['base'], pc['base'] = run(False)
    R['serve'], _ = run(True, pc['base'])       # live before the fix: coefficients fit without them, served with them
    R['both'], _ = run(True)                    # fit and served with them (a model change, not the fix)
    b, y, S, d1, line, _ = R['base']
    ok = ~np.isnan(b) & d1
    tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    lined = ~np.isnan(line)
    res = {'changedTeamSeasons': nch, 'arms': {}}
    for a, (p, _, _, _, _, coef) in R.items():
        e1, e0 = np.abs(p - y), np.abs(b - y)
        r = {}
        for nm, k in (('tune', tune), ('held', held), ('heldLined', held & lined)):
            r[nm] = {'n': int(k.sum()), 'mae': round(float(e1[k].mean()), 4), 'dMae': round(float((e1 - e0)[k].mean()), 4)}
            if a != 'base':
                r[nm]['t'] = round(C.paired_t(e1[k], e0[k]), 2)
        r['bySeason'] = {str(s): round(float((e1 - e0)[ok & (S == s)].mean()), 4) for s in range(C.SCORE0, C.LAST + 1)}
        r['priorCoef2027'] = coef
        res['arms'][a] = r
        print(a, json.dumps({k: v for k, v in r.items() if k in ('tune', 'held', 'heldLined')}), flush=True)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
