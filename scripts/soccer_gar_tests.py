#!/usr/bin/env python3
"""Backtests for the soccer GAR inputs (scripts/soccer_players.py), audit items #19 and #34 (Oct 25 2026).

    python3 scripts/soccer_gar_tests.py gk  <fotmob dir>   # #19: FotMob goals prevented (xGOT faced - goals) as the GK term
    python3 scripts/soccer_gar_tests.py lg                  # #34: league strength for movers + a newcomer prior

The harness is soccer_players.py's own fit: last season's shrunk rates x this season's minutes -> team goal
difference a match, centred within league-season, ridge, leave-one-season-out (shrink 200, lambda 1 as fitted).
GATE (registered before results): paired t >= 2 on the team-season squared-error change, a majority of seasons better
(6 of 9 when all seasons are scored), and 2022+ not worse. Results go to data/soccer_gar_tests.json.

FotMob season stat lists (data.fotmob.com/stats/<league>/season/<id>/_goals_prevented.json) give each regular keeper's
goals prevented: post-shot xG (xGOT) of the shots on target he faced minus the goals he let in. They exist for the
big five from 2019-20 (a handful of keepers that season) and in full from 2020-21; the lists hold the keepers who
qualify (about 20 a league), so backups carry no FotMob number.
"""
import glob
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D
import soccer_players as SP
import names as N

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_gar_tests.json')
LID = {'47': 'eng.1', '87': 'esp.1', '54': 'ger.1', '55': 'ita.1', '53': 'fra.1'}
SHRINK, LAM = 200, 1.0
BASE = ['ona', 'rel', 'npxg', 'xas', 'bup', 'gk']


def load():
    rows = D.load(SP.ROWS)
    S1 = D.current_season()
    rows = [r for r in rows if r['S'] < S1]
    ts = {k: v for k, v in SP.team_seasons(SP.FIRST, S1).items() if k[1] < S1}
    return rows, ts, S1


def team_ok(a, b):
    import soccer_games as SG
    return SG.name_sim(a, b) >= 0.5 or N.same_team(a, b)


def fotmob_gp(fmd, rows):
    """join FotMob goals prevented to the Understat keeper rows: r['fgp'] (total), r['fmin']"""
    cover, nj, nk = set(), 0, 0
    for fn in glob.glob(os.path.join(fmd, '*.json.gz')):
        lid, sn = os.path.basename(fn)[:-8].split('_')
        S, lg = int(sn.split('-')[1]), LID[lid]
        d = json.load(gzip.open(fn, 'rt'))
        L = d.get('_goals_prevented') or []
        if len(L) < 15:                      # 2019-20 lists hold 3-6 keepers: not a season's coverage
            continue
        cover.add((lg, S))
        gks = [r for r in rows if r['lg'] == lg and r['S'] == S and r['pos'] == 'GK']
        for pid, nm, tm, val, mins, mp, sub, pos in L:
            nk += 1
            if val is None or not mins:
                continue
            c = [r for r in gks if (N.key(r['n']) == N.key(nm) or N.same(r['n'], nm)) and team_ok(r['team'], tm)]
            if not c:
                c = [r for r in gks if N.same(r['n'], nm)]
            if c:
                r = max(c, key=lambda r: r['min'])
                r['fgp'], r['fmin'] = float(val), float(mins)
                nj += 1
    return cover, nj, nk


def gate(y, p0, p1, ks, seasons):
    d = (y - p0) ** 2 - (y - p1) ** 2                  # positive = the candidate is better
    Sk = np.array([k[1] for k in ks])
    byS = {int(s): float(d[Sk == s].mean()) for s in seasons if (Sk == s).any()}
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    late = float(d[Sk >= 2022].mean())
    wins = sum(v > 0 for v in byS.values())
    var = float(np.mean(y ** 2))
    return {'r2Base': round(1 - float(np.mean((y - p0) ** 2)) / var, 4), 'r2': round(1 - float(np.mean((y - p1) ** 2)) / var, 4),
            'dMse': round(float(d.mean()), 5), 't': round(float(t), 2), 'wins': wins, 'of': len(byS),
            'late': round(late, 5), 'bySeason': {k: round(v, 5) for k, v in byS.items()},
            'pass': bool(t >= 2 and wins > len(byS) / 2 and wins >= min(6, len(byS)) * (len(byS) >= 9) and late >= 0)}


def run(rows, ts, feats, keep):
    ks, X, y = SP.design(rows, ts, feats)
    m = np.array([k[1] in keep for k in ks])
    ks = [k for k, mm in zip(ks, m) if mm]
    X, y = X[m], y[m]
    _, p = SP.loso(ks, X, y, LAM)
    return ks, y, p


def repeat(rows, key, mins=1500):
    """year-to-year correlation of a keeper's per-90 rate (same keeper, consecutive seasons, any club)"""
    by = {}
    for r in rows:
        if r['pos'] == 'GK' and r['min'] >= mins and r.get(key) is not None:
            by[(r['p'], r['S'])] = r[key] / (r['min'] / 90)
    a = [(v, by[(p, S + 1)]) for (p, S), v in by.items() if (p, S + 1) in by]
    if len(a) < 10:
        return None
    a = np.array(a)
    return {'r': round(float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), 3), 'n': len(a)}


def gk_test(fmd):
    rows, ts, S1 = load()
    cover, nj, nk = fotmob_gp(fmd, rows)
    print('fotmob league-seasons', len(cover), 'keepers', nk, 'joined', nj, flush=True)
    fs = sorted({S for _, S in cover})
    for r in rows:
        r['gku'] = r['gks']
        # FotMob minutes can differ a little from Understat's; scale the total to Understat minutes
        r['gkf'] = r['fgp'] * r['min'] / r['fmin'] if r.get('fgp') is not None else None
    res = {'cover': sorted('%s %d' % c for c in cover), 'joined': nj, 'listed': nk}
    # repeatability on the seasons both exist
    both = [r for r in rows if r['pos'] == 'GK' and r.get('gkf') is not None]
    res['repeat'] = {'understat': repeat(both, 'gku'), 'fotmob': repeat(both, 'gkf'),
                     'understatAll': repeat([r for r in rows if r['pos'] == 'GK'], 'gku')}
    res['corrSameSeason'] = round(float(np.corrcoef([r['gku'] / r['min'] * 90 for r in both],
                                                    [r['gkf'] / r['min'] * 90 for r in both])[0, 1]), 3)
    # scored team-seasons: those whose prior season has FotMob
    keep = {S for S in range(SP.FIRST, S1) if S - 1 in fs}
    variants = {}
    # A: the current term
    SP.prep(rows, SHRINK)
    ks, y, p0 = run(rows, ts, BASE, keep)
    # B: FotMob goals prevented replaces it where the keeper is listed (others: the Understat number)
    for name, fill in (('fotmob_else_understat', 'u'), ('fotmob_else_zero', 'z')):
        for r in rows:
            if r['pos'] != 'GK':
                continue
            if r['gkf'] is not None:
                r['gks'] = r['gkf']
            elif (r['lg'], r['S']) in cover:
                r['gks'] = r['gku'] if fill == 'u' else 0.0
            else:
                r['gks'] = r['gku']
        SP.prep(rows, SHRINK)
        _, _, p1 = run(rows, ts, BASE, keep)
        variants[name] = gate(y, p0, p1, ks, sorted(keep))
        print(name, json.dumps(variants[name]), flush=True)
    # C: both terms (FotMob as an extra rate)
    for r in rows:
        r['gks'] = r['gku']
        r['_gkf'] = (r['gkf'] / (max(r['min'], 1) / 90)) if r['pos'] == 'GK' and r['gkf'] is not None else 0.0
    SP.FEATS.append('gkf')
    SP.prep(rows, SHRINK)
    _, _, p1 = run(rows, ts, BASE + ['gkf'], keep)
    variants['both'] = gate(y, p0, p1, ks, sorted(keep))
    print('both', json.dumps(variants['both']), flush=True)
    SP.FEATS.remove('gkf')
    res['variants'] = variants
    res['scoredSeasons'] = sorted(keep)
    res['teamSeasons'] = len(ks)
    save('gk', res)


# ---------------------------------------------------------------- #34: league strength and newcomers
def league_strength():
    """(league, season) -> mean end-of-season club rating (goals a match vs the average big-five club), from the game
    model's club ratings (scripts/data/soccer_team_ratings.json.gz)"""
    d = D.load(os.path.join(HERE, 'data', 'soccer_team_ratings.json.gz'))['seasons']
    m = defaultdict(list)
    for S, cl in d.items():
        for v in cl.values():
            m[(v[0], int(S))].append(v[1])
    return {k: sum(v) / len(v) for k, v in m.items()}


def tm_values():
    """Understat id -> (dob, [(date, value EUR m)]) from the Transfermarkt dump's valuation history"""
    import csv
    link = D.load(SP.MV_LINK) if hasattr(SP, 'MV_LINK') else D.load(os.path.join(HERE, 'data', 'soccer_mv_link.json.gz'))
    tm2us = defaultdict(list)
    for u, t in link['p'].items():
        tm2us[str(t)].append(u)
    vals = defaultdict(list)
    fn = os.path.join(HERE, '.cache', 'soccer_prospects', 'dump', 'player_valuations.csv.gz')
    with gzip.open(fn, 'rt') as f:
        for r in csv.DictReader(f):
            if r['player_id'] in tm2us:
                vals[r['player_id']].append((r['date'], float(r['market_value_in_eur']) / 1e6))
    out = {}
    for t, us in tm2us.items():
        v = sorted(vals.get(t, []))
        for u in us:
            out[u] = (link['dob'].get(t), v)
    return out


def value_before(v, day):
    x = None
    for d, m in v:
        if d < day:
            x = m
        else:
            break
    return x


def design_x(rows, ts, feats, LS, TMV, extras):
    """soccer_players.design plus extra team columns: 'lgm' movers' league gap, 'new*' the newcomer prior"""
    last = {}
    for r in sorted(rows, key=lambda r: r['S']):
        last.setdefault(r['p'], {})[r['S']] = r
    nx = len(extras)
    has = set()
    X = defaultdict(lambda: np.zeros(len(feats) + nx))
    for r in rows:
        k = (r['lg'], r['S'], r['tid'])
        if k not in ts:
            continue
        share = r['min'] / (90 * ts[k]['mp'])
        pr = None
        for S0 in (r['S'] - 1, r['S'] - 2):
            q = last.get(r['p'], {}).get(S0)
            if q and q['min'] >= 300:
                pr = q; break
        e = np.zeros(nx)
        if pr:
            has.add(k)                                   # the team-seasons soccer_players.design scores
            v = np.array([pr[f_] for f_ in feats])
            if 'lgm' in extras and pr['lg'] != r['lg']:
                S0 = pr['S']
                e[extras.index('lgm')] = LS.get((pr['lg'], S0), 0) - LS.get((r['lg'], S0), 0)
        else:
            v = np.zeros(len(feats))
            dob, hist = TMV.get(r['p'], (None, []))
            mv = value_before(hist, f"{r['S'] - 1}-08-15")
            age = (r['S'] - 1 + 8 / 12 - (int(dob[:4]) + (int(dob[5:7]) - 1) / 12)) if dob else 26.0
            z = {'new': 1.0, 'new_lmv': (math.log(mv) - math.log(5.0)) if mv else 0.0, 'new_nomv': 0.0 if mv else 1.0,
                 'new_age': age - 26, 'new_age2': (age - 26) ** 2 / 10, 'new_gk': 1.0 if r['pos'] == 'GK' else 0.0,
                 'new_fwd': 1.0 if r['pos'] == 'F' else 0.0}
            for j, x in enumerate(extras):
                if x in z:
                    e[j] = z[x]
        X[k] += share * np.concatenate([v, e])
    ks = sorted(k for k in X if k in has)
    Xm = np.array([X[k] for k in ks]); ym = np.array([ts[k]['gd'] / ts[k]['mp'] for k in ks])
    grp = defaultdict(list)
    for i, k in enumerate(ks):
        grp[(k[0], k[1])].append(i)
    for idx in grp.values():
        Xm[idx] -= Xm[idx].mean(0); ym[idx] -= ym[idx].mean()
    return ks, Xm, ym


def movers(rows, LS, F):
    """players who changed big-five league between consecutive seasons (900+ minutes in each): this season's value a
    90 (league-relative, the fitted weights, this season's own rates) on last season's and the league gap"""
    by = {(r['p'], r['S']): r for r in rows if r['min'] >= 900}
    a = []
    for (p, S), r in by.items():
        q = by.get((p, S - 1))
        if q and q['lg'] != r['lg']:
            gap = LS.get((q['lg'], S - 1), 0) - LS.get((r['lg'], S - 1), 0)
            a.append((SP.value(r, F), SP.value(q, F), gap))
    a = np.array(a)
    X = np.column_stack([np.ones(len(a)), a[:, 1], a[:, 2]])
    b, *_ = np.linalg.lstsq(X, a[:, 0], rcond=None)
    e = a[:, 0] - X @ b
    cov = np.linalg.inv(X.T @ X) * (e @ e) / (len(a) - 3)
    se = np.sqrt(np.diag(cov))
    return {'n': len(a), 'b0': round(float(b[0]), 4), 'bPrev': round(float(b[1]), 3), 'bGap': round(float(b[2]), 4),
            'tGap': round(float(b[2] / se[2]), 2), 'perPlayerIf11': round(1 / 11, 4)}


def lg_test():
    rows, ts, S1 = load()
    LS = league_strength()
    TMV = tm_values()
    print('values for', sum(1 for v in TMV.values() if v[1]), 'linked players', flush=True)
    SP.prep(rows, SHRINK)
    F = json.load(open(SP.FIT))
    res = {'movers': movers(rows, LS, F)}
    print('movers', res['movers'], flush=True)
    seasons = sorted({r['S'] for r in rows} - {SP.FIRST})
    ks, X0, y = design_x(rows, ts, BASE, LS, TMV, [])
    _, p0 = SP.loso(ks, X0, y, LAM)
    res['base'] = round(1 - float(np.mean((y - p0) ** 2)) / float(np.mean(y ** 2)), 4)
    print('base', res['base'], flush=True)
    cands = {'lgm': ['lgm'], 'new': ['new'], 'new+lmv': ['new', 'new_lmv', 'new_nomv'],
             'new+lmv+age': ['new', 'new_lmv', 'new_nomv', 'new_age', 'new_age2'],
             'new+lmv+age+pos': ['new', 'new_lmv', 'new_nomv', 'new_age', 'new_age2', 'new_gk', 'new_fwd'],
             'lgm+new+lmv+age': ['lgm', 'new', 'new_lmv', 'new_nomv', 'new_age', 'new_age2']}
    cands['final'] = FINAL = ['lgm', 'new', 'new_lmv', 'new_nomv']
    res['cands'] = {}
    for nm, ex in cands.items():
        ks1, X1, y1 = design_x(rows, ts, BASE, LS, TMV, ex)
        assert ks1 == ks
        _, p1 = SP.loso(ks, X1, y, LAM)
        g = gate(y, p0, p1, ks, seasons)
        g['coef'] = {f_: round(float(c), 4) for f_, c in zip(BASE + ex, SP.ridge(X1, y, LAM))}
        res['cands'][nm] = g
        print(nm, json.dumps({k: v for k, v in g.items() if k != 'bySeason'}), flush=True)
    # drop-one from the final set: each part must hold its own against the rest
    ksf, Xf, _ = design_x(rows, ts, BASE, LS, TMV, FINAL)
    _, pf = SP.loso(ks, Xf, y, LAM)
    res['dropOne'] = {}
    for x in FINAL:
        ex = [e for e in FINAL if e != x]
        _, Xd, _ = design_x(rows, ts, BASE, LS, TMV, ex)
        _, pd_ = SP.loso(ks, Xd, y, LAM)
        g = gate(y, pd_, pf, ks, seasons)
        res['dropOne'][x] = g
        print('keep', x, 'over the rest', json.dumps({k: v for k, v in g.items() if k != 'bySeason'}), flush=True)
    save('league', res)


def save(k, v):
    d = json.load(open(OUT)) if os.path.exists(OUT) else {}
    d[k] = v
    json.dump(d, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    if sys.argv[1] == 'gk':
        gk_test(sys.argv[2])
    elif sys.argv[1] == 'lg':
        lg_test()
