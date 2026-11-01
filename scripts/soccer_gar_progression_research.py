#!/usr/bin/env python3
"""Does soccer GAR (scripts/soccer_players.py) undercredit deep progressors, the Busquets type who moves the ball
without shots or key passes? (Nov 1 2026, from a reply to the GAR post.)

    python3 scripts/soccer_gar_progression_research.py          # pull FotMob big-five lists (cached), test, write
                                                                 # data/soccer_gar_progression.json

GAR already carries xGBuildup (xG of possessions a player was part of before the last pass and the shot) and the
team's xG against / on-off with him on the pitch. Candidates added to that fit, one at a time and together:
  ch    Understat xGChain a 90 (every possession he touched that ended in a shot; with xGBuildup in the fit this is
        the final-third share)
  kp    key passes a 90
  FotMob season lists (data.fotmob.com, free, per 90, about 300 regulars a league-season, from 2016-17):
  pas   accurate passes          lb   accurate long balls     drb  dribbles won (the carry proxy: free sources carry
  rec   ball recoveries          int  interceptions           tkl  tackles won        no progressive passes/carries)
  pw3   possession won in the final third
No free source has progressive passes or carries for the big five (FBref dropped Opta's advanced tables; it also
blocks this runner).

Harness: soccer_gar_tests.py's, i.e. soccer_players.py's own fit without the team priors: last season's shrunk
rates x this season's minutes -> team goal difference a match, centred within league-season, ridge (lambda 1),
leave-one-season-out, shrink 300 as fitted. Scored: team-seasons 2018-2026 (prior season 2016-17+ has FotMob).
GATE (registered before results, same as soccer_gar_tests.py): paired t >= 2 on the team-season squared-error change,
a majority of seasons better (6 of 9), and 2022+ not worse.
Deep midfielders: before/after rank of each value a 90 (same-season rates at the all-season weights, players with
1500+ minutes) for a named list and for a data-defined group (midfielders in the top third of xGBuildup a 90 and the
bottom third of npxG + xA a 90).
"""
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D  # noqa: E402
import soccer_players as SP  # noqa: E402
import soccer_gar_tests as GT  # noqa: E402
import names as N  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_gar_progression.json')
CACHE = os.path.join(D.CACHE, 'fmb5')
FMID = {'eng.1': 47, 'esp.1': 87, 'ger.1': 54, 'ita.1': 55, 'fra.1': 53}
FMST = {'accurate_pass': 'pas', 'accurate_long_balls': 'lb', 'won_contest': 'drb', 'ball_recovery': 'rec',
        'interception': 'int', 'total_tackle': 'tkl', 'poss_won_att_3rd': 'pw3'}
FMK = list(FMST.values())
SHRINK, LAM = 300, 1.0
BASE = ['ona', 'rel', 'npxg', 'xas', 'bup', 'gk']
DEEP = ['Sergio Busquets', 'Rodri', 'Joshua Kimmich', 'Jorginho', 'Fabinho', 'Casemiro', "N'Golo Kanté", 'Declan Rice',
        'Martín Zubimendi', 'Manuel Ugarte', 'Fernandinho', 'Marcelo Brozovic', 'Marco Verratti', 'Toni Kroos',
        'Miralem Pjanic', 'Thomas Partey', 'Stanislav Lobotka', 'Frenkie de Jong', 'Aurélien Tchouaméni',
        'Moisés Caicedo', 'Granit Xhaka', 'Rúben Neves', 'Sergej Milinkovic-Savic', 'Leon Goretzka', 'Thiago Alcántara']


def pull():
    """(league, season) -> [FotMob rows {n, team, min, <key>: per 90}]"""
    os.makedirs(CACHE, exist_ok=True)
    out = {}
    for lg, i in FMID.items():
        d = D.get(f'https://www.fotmob.com/api/data/leagues?id={i}')
        for L in ((d or {}).get('stats') or {}).get('seasonStatLinks') or []:
            S = int(L['Name'][-4:])
            if S >= D.current_season():
                continue
            p = os.path.join(CACHE, f'{lg}_{S}.json.gz')
            if os.path.exists(p):
                out[(lg, S)] = D.load(p); continue
            base = 'https://data.fotmob.com/' + L['RelativePath'].rsplit('/', 1)[0] + '/'
            P = {}
            for st, k in FMST.items():
                x = D.get(base + st + '.json') or {}
                for q in (row for t in x.get('TopLists') or [] for row in t.get('StatList') or []):
                    o = P.setdefault(str(q.get('ParticiantId')), {'n': q.get('ParticipantName'), 'team': q.get('TeamName'),
                                                                  'min': 0})
                    o['min'] = max(o['min'], q.get('MinutesPlayed') or 0)
                    o[k] = q.get('StatValue')
                time.sleep(0.15)
            rows = list(P.values())
            D.save(p, rows)
            out[(lg, S)] = rows
            print('fotmob', lg, S, len(rows), flush=True)
    return out


def join(rows, fm):
    by = defaultdict(list)
    for r in rows:
        by[(r['lg'], r['S'])].append(r)
    nj = nl = 0
    for k, L in fm.items():
        us = by.get(k, [])
        for q in L:
            nl += 1
            c = [r for r in us if (N.key(r['n']) == N.key(q['n']) or N.same(r['n'], q['n'])) and GT.team_ok(r['team'], q['team'])]
            if not c:
                continue
            r = max(c, key=lambda r: r['min'])
            r['fm'] = q; nj += 1
    return {'listed': nl, 'joined': nj, 'leagueSeasons': len(fm)}


def fm_rates(rows, shrink):
    """FotMob rates relative to the league-season (joined players, FotMob minutes), shrunk toward the position mean;
    a player not on the lists sits at the position mean"""
    by = defaultdict(list)
    for r in rows:
        by[(r['lg'], r['S'])].append(r)
    for rs in by.values():
        for k in FMK:
            have = [r for r in rs if r.get('fm') and r['fm'].get(k) is not None]
            tot = sum(r['fm']['min'] for r in have) or 1
            mu = sum(r['fm'][k] * r['fm']['min'] for r in have) / tot
            for pos in ('GK', 'D', 'M', 'F'):
                ps = [r for r in have if r['pos'] == pos]
                pm = sum(r['fm']['min'] for r in ps) or 1
                pmu = sum((r['fm'][k] - mu) * r['fm']['min'] for r in ps) / pm
                for r in rs:
                    if r['pos'] != pos:
                        continue
                    if r.get('fm') and r['fm'].get(k) is not None:
                        w = r['fm']['min'] / (r['fm']['min'] + shrink)
                        r[k] = w * (r['fm'][k] - mu) + (1 - w) * pmu
                    else:
                        r[k] = pmu
    return rows


def prep(rows):
    for r in rows:
        m90 = max(r['min'], 1) / 90
        r['_ch'] = r['ch'] / m90
        r['_kp'] = r['kp'] / m90
    for k in ('ch', 'kp'):
        if k not in SP.FEATS:
            SP.FEATS.append(k)
    SP.prep(rows, SHRINK)
    fm_rates(rows, SHRINK)


def scored(rows, ts, feats, keep):
    ks, X, y = SP.design(rows, ts, feats)
    m = np.array([k[1] in keep for k in ks])
    ks = [k for k, mm in zip(ks, m) if mm]
    return ks, X[m], y[m]


def values(rows, ts, feats):
    """value a 90 on each player-season (same-season rates) at weights fitted on every scored team-season"""
    ks, X, y = SP.design(rows, ts, feats)
    b = SP.ridge(X, y, LAM)
    w = dict(zip(feats, b))
    return {id(r): sum(w[f_] * r[f_] for f_ in feats) for r in rows}, {f_: round(float(v), 4) for f_, v in w.items()}


def ranks(rows, v, pool):
    """percentile (0 = best) of each pool row's value among outfield players 1500+ minutes in the same season"""
    by = defaultdict(list)
    for r in rows:
        if r['min'] >= 1500 and r['pos'] != 'GK':
            by[r['S']].append(v[id(r)])
    for S in by:
        by[S] = np.sort(by[S])[::-1]
    return {id(r): float(np.searchsorted(-by[r['S']], -v[id(r)])) / len(by[r['S']]) for r in pool}


def main():
    rows, ts, S1 = GT.load()
    fm = pull()
    res = {'join': join(rows, fm)}
    print(res['join'], flush=True)
    fs = {S for _, S in fm}
    keep = sorted(S for S in range(SP.FIRST, S1) if S - 1 in fs)
    prep(rows)
    ks, X0, y = scored(rows, ts, BASE, set(keep))
    _, p0 = SP.loso(ks, X0, y, LAM)
    var = float(np.mean(y ** 2))
    res['base'] = {'r2Held': round(1 - float(np.mean((y - p0) ** 2)) / var, 4), 'teamSeasons': len(ks), 'seasons': keep}
    print('base', res['base'], flush=True)
    cands = {k: [k] for k in ['ch', 'kp'] + FMK}
    cands['fotmob_all'] = FMK
    cands['progression'] = ['ch', 'pas', 'lb', 'drb']
    cands['defending'] = ['rec', 'int', 'tkl', 'pw3']
    cands['all'] = ['ch', 'kp'] + FMK
    res['cands'] = {}
    for nm, ex in cands.items():
        ks1, X1, _ = scored(rows, ts, BASE + ex, set(keep))
        assert ks1 == ks
        _, p1 = SP.loso(ks, X1, y, LAM)
        g = GT.gate(y, p0, p1, ks, keep)
        g['coef'] = {f_: round(float(c), 4) for f_, c in zip(BASE + ex, SP.ridge(X1, y, LAM))}
        res['cands'][nm] = g
        print(nm, json.dumps({k: v for k, v in g.items() if k != 'bySeason'}), flush=True)
    # xGBuildup itself: what dropping it costs (the term the reply is asking about)
    noB = [f_ for f_ in BASE if f_ != 'bup']
    _, Xd, _ = scored(rows, ts, noB, set(keep))
    _, pd_ = SP.loso(ks, Xd, y, LAM)
    res['bupOverRest'] = GT.gate(y, pd_, p0, ks, keep)
    print('bup over rest', json.dumps({k: v for k, v in res['bupOverRest'].items() if k != 'bySeason'}), flush=True)

    # deep midfielders, before / after
    sc = [r for r in rows if r['S'] in set(keep) | {k - 1 for k in keep}]
    tsk = {k: v for k, v in ts.items() if k[1] in keep}
    vb, wb = values(rows, tsk, BASE)
    best = max(res['cands'], key=lambda c: res['cands'][c]['t'])
    va, wa = values(rows, tsk, BASE + cands['all'])
    vn, wn = values(rows, tsk, noB)
    res['weights'] = {'base': wb, 'all': wa, 'noBuildup': wn}
    mids = [r for r in sc if r['pos'] == 'M' and r['min'] >= 1500]
    m90 = lambda r, k: r[k] / (r['min'] / 90)  # noqa: E731
    by = defaultdict(list)
    for r in mids:
        by[r['S']].append(r)
    deep = []
    for S, L in by.items():
        b = np.array([m90(r, 'bu') for r in L]); e = np.array([m90(r, 'x') - m90(r, 'pen') + m90(r, 'xA') for r in L])
        hb, le = np.quantile(b, 2 / 3), np.quantile(e, 1 / 3)
        deep += [r for r, bb, ee in zip(L, b, e) if bb >= hb and ee <= le]
    named = [r for r in mids if any(N.same(r['n'], n) for n in DEEP)]
    out = {}
    for nm, pool in (('dataDefined', deep), ('named', named), ('allMidfielders', mids)):
        rb, ra, rn = ranks(rows, vb, pool), ranks(rows, va, pool), ranks(rows, vn, pool)
        out[nm] = {'n': len(pool), 'pctBase': round(100 * float(np.mean(list(rb.values()))), 1),
                   'pctAll': round(100 * float(np.mean(list(ra.values()))), 1),
                   'pctNoBuildup': round(100 * float(np.mean(list(rn.values()))), 1)}
    rb, ra, rn = ranks(rows, vb, named), ranks(rows, va, named), ranks(rows, vn, named)
    out['players'] = sorted(({'n': r['n'], 'S': r['S'], 'team': r['team'], 'min': r['min'],
                              'pctNoBuildup': round(100 * rn[id(r)], 1), 'pctBase': round(100 * rb[id(r)], 1),
                              'pctAll': round(100 * ra[id(r)], 1)} for r in named), key=lambda x: (x['n'], x['S']))
    res['deep'] = out
    print(json.dumps({k: v for k, v in out.items() if k != 'players'}), flush=True)
    res['note'] = 'pct = mean percentile among outfield players with 1500+ minutes that season, 0 = best'
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
