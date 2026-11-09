#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research + fit (Nov 3 2026): NHL multi-year projection (next season's and next three seasons' WAR) for the WAR
leaders table, from pWAR + age (by F / D / G) + ice time.

    python3 scripts/nhl_proj_research.py --partial   # writes data/nhl_proj_fit.json (numpy; --partial needs the
                                                     # MoneyPuck summaries in scripts/.cache/nhl/mp)

Rows: every player-season S 2010-25 in static/data/nhl-war/<S>.json with 100+ minutes (the files carry PR #768's
traded-player split and the refit pWAR: 1/.5/.25, K 5 h, KG 200 h).
Targets: y1 = WAR in S+1, y3 = WAR summed over S+1..S+3 (S <= 2023), each season at an 82-game pace (2013 48,
2020 70, 2021 56 games); a season out of the league counts 0 (replacement).
Inputs at the end of season S:
    pw   pWAR at an 82-game pace (pWAR x 82 / games): HPM over replacement x TOI82
    pm   the percentile tab's Marcel value (scripts/player_pctl.py): descriptive WAR a minute over S, S-1, S-2
         (1/.7/.5), shrunk with 1,600 minutes toward the group mean, x TOI82
    A    age - 27 (age on Sep 15 of the season's start year), by group
    r    HPM - replacement (goals a 60), lt = ln(1 + TOI82 / 100)
Forms, pre-registered (7, both targets, skaters and goalies apart), leave one season out:
    flat   y1 = pw, y3 = 3 pw                                    (the live pWAR held flat)
    cal    a + b pw                                              (baseline: pWAR, calibrated)
    marcel a + b pm                                              (baseline: percentile Marcel, calibrated)
    both   a + b pw + c pm                                       (baseline: the two together)
    age    cal + A, A^2 by group
    agex   age + pw x A
    full   agex + r + lt
  added after the first run showed `both` beating `cal` (so 9 forms in all):
    bage   both + A, A^2 by group + pw x A
    bfull  bage + r + lt
Gate: beat the best baseline with paired t <= -2 (players as units; t also on season means), win most seasons,
calibration slope .8-1.2, on the full LOSO and on a time split (fit <= 2016, test 2017+); the simpler form unless the
richer one beats it with t <= -2.
Season in progress: see partial() (needs scripts/.cache/nhl/mp, pulled by nhl_players.mp_file).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
SD = os.path.join(ROOT, 'static', 'data', 'nhl-war')
OUT = os.path.join(ROOT, 'data', 'nhl_proj_fit.json')
GAMES = {2013: 48, 2020: 70, 2021: 56}
A0, KP, MW = 27, 1600.0, (1.0, 0.7, 0.5)
MU = {'F': 0.001065, 'D': 0.000392, 'G': 0.000787}   # data/pctl_fit_nhl.json rates.war.mu (vets), WAR a minute
FORMS = ['flat', 'cal', 'marcel', 'both', 'age', 'agex', 'full', 'bage', 'bfull']
MODELS = ['age', 'agex', 'full', 'bage', 'bfull']
BASE = ['flat', 'cal', 'marcel', 'both']


def games(S):
    return GAMES.get(S, 82)


def load():
    files = {}
    for fn in os.listdir(SD):
        if fn[:4].isdigit():
            S = int(fn[:4])
            files[S] = json.load(open(os.path.join(SD, fn)))
    return files


def pm_of(files, S, pid, grp, toi82):
    num = den = 0.0
    for w, s in zip(MW, (S, S - 1, S - 2)):
        p = files.get(s, {}).get('_ix', {}).get(pid)
        if p and p['toi'] > 0:
            num += w * p['war']; den += w * p['toi']
    return (num + KP * MU[grp]) / (den + KP) * toi82


def rows(files, last):
    for S, d in files.items():
        d['_ix'] = {p['id']: p for p in d['players']}
    out = []
    for S in range(2010, last + 1):
        d = files[S]
        gS = games(S)
        for p in d['players']:
            if p['toi'] < 100 or p.get('age') is None or p.get('pwar') is None:
                continue
            fut = []
            for k in (1, 2, 3):
                q = files.get(S + k, {}).get('_ix', {}).get(p['id']) if S + k in files else None
                fut.append(q['war'] * 82 / games(S + k) if q else 0.0)
            toi82 = p['toi'] * 82 / gS
            grp = p['grp']
            repl = d['repl'][grp]
            nx = files.get(S + 1, {}).get('_ix', {}).get(p['id'])
            past = [(w, files.get(s_, {}).get('_ix', {}).get(p['id'])) for w, s_ in zip(MW, (S, S - 1, S - 2))]
            out.append({'S': S, 'id': p['id'], 'grp': grp, 'age': p['age'], 'pw': p['pwar'] * 82 / gS,
                        'hpm': p['hpm'], 'repl': repl, 'toi82': toi82, 'toi': p['toi'], 'war': p['war'],
                        'wh': p['war'] / (p['toi'] / 60), 'wh1': nx['war'] / (nx['toi'] / 60) if nx and nx['toi'] >= 100 else None,
                        'pmnum': sum(w * q['war'] for w, q in past if q), 'pmden': sum(w * q['toi'] for w, q in past if q),
                        'key': ('g' if grp == 'G' else '') + p['id'],
                        'pm': pm_of(files, S, p['id'], grp, toi82), 'r': p['hpm'] - repl, 'lt': math.log1p(toi82 / 100),
                        'y1': fut[0], 'y3': sum(fut), 'n3': S + 3 <= 2026})
    return out


def X(form, R, grps):
    pw, pm = R['pw'], R['pm']
    one = np.ones_like(pw)
    if form == 'cal':
        c = [pw]
    elif form == 'marcel':
        c = [pm]
    elif form == 'both':
        c = [pw, pm]
    else:
        A = R['age'] - A0
        c = [pw] + ([pm] if form in ('bage', 'bfull') else [])
        for g in grps:
            m = (R['grp'] == g).astype(float)
            c += [m * A, m * A * A] + ([m] if len(grps) > 1 and g != grps[0] else [])
        if form in ('agex', 'full', 'bage', 'bfull'):
            c.append(pw * A)
        if form in ('full', 'bfull'):
            c += [R['r'], R['lt']]
    return np.column_stack([one] + c)


def tstat(d):
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


def evaluate(R, y, grps, mult, train_mask=None):
    """LOSO predictions per form (or, with train_mask, fit on the mask and predict the rest)"""
    S = R['S']
    pr = {}
    for form in FORMS:
        p = np.full(len(y), np.nan)
        if form == 'flat':
            p = R['pw'] * mult
        elif train_mask is None:
            for s in sorted(set(S)):
                tr, te = S != s, S == s
                b = np.linalg.lstsq(X(form, {k: v[tr] for k, v in R.items()}, grps), y[tr], rcond=None)[0]
                p[te] = X(form, {k: v[te] for k, v in R.items()}, grps) @ b
        else:
            b = np.linalg.lstsq(X(form, {k: v[train_mask] for k, v in R.items()}, grps), y[train_mask], rcond=None)[0]
            p = X(form, R, grps) @ b
        pr[form] = p
    return pr


def report(pr, y, S, mask):
    y, S = y[mask], S[mask]
    e = {k: (v[mask] - y) ** 2 for k, v in pr.items()}
    out = {'n': int(mask.sum()), 'seasons': int(len(set(S))), 'rmse': {k: round(float(np.sqrt(v.mean())), 4) for k, v in e.items()}}
    bb = min(BASE, key=lambda k: e[k].mean())
    out['bestBase'] = bb
    for f in MODELS + (['both'] if bb != 'both' else []):
        d = e[f] - e[bb]
        sm = np.array([d[S == s].mean() for s in sorted(set(S))])
        out[f] = {'t': round(tstat(d), 2), 'tSeason': round(tstat(sm), 2), 'won': int((sm < 0).sum()),
                  'slope': round(float(np.polyfit(pr[f][mask], y, 1)[0]), 3)}
    for f in BASE:
        out.setdefault('slopes', {})[f] = round(float(np.polyfit(pr[f][mask], y, 1)[0]), 3)
    return out


def arr(rs, keys=('S', 'age', 'pw', 'pm', 'r', 'lt', 'y1', 'y3')):
    R = {k: np.array([r[k] for r in rs], float) for k in keys}
    R['grp'] = np.array([r['grp'] for r in rs])
    return R


def h1_tables(fitd):
    """{S: {key: (h1, toi s)}}: one season's HPM-weighted rate (goals a 60, uncentred, before the shrink), from the
    MoneyPuck summaries (scripts/.cache/nhl/mp): skaters sum w_c x component, goalies w_gsax x GSAx a 60"""
    import nhl_players as P
    w = fitd['w']
    out = {}
    for S in range(2008, 2027):
        t = {}
        for r in P.skaters(S):
            t[r['id']] = (sum(w.get(c, 0) * r[c] for c in P.COMPS), r['toi'])
        for r in P.goalies(S):
            t['g' + r['id']] = (w.get('gsax', 0) * r['gsax60'], r['toi'])
        out[S] = t
    return out


def noise(rs, H):
    """per-hour sampling variance of h1 and of WAR an hour, and their covariance, from consecutive seasons (100+ min
    each): E[d d'] = const + s x (1 / h_S + 1 / h_S+1)"""
    pairs = []
    for r in rs:
        a, b = H.get(r['S'], {}).get(r['key']), H.get(r['S'] + 1, {}).get(r['key'])
        if a and b and r['wh1'] is not None and b[1] >= 6000:
            pairs.append((a[0] - b[0], r['wh'] - r['wh1'], 3600 / a[1] + 3600 / b[1]))
    P_ = np.array(pairs)
    A = np.column_stack([np.ones(len(P_)), P_[:, 2]])
    sl = lambda v: float(np.linalg.lstsq(A, v, rcond=None)[0][1])
    return {'hh': max(sl(P_[:, 0] ** 2), 1e-6), 'ww': max(sl(P_[:, 1] ** 2), 1e-6), 'hw': sl(P_[:, 0] * P_[:, 1]), 'pairs': len(P_)}


FS = [0.1, 0.2, 0.35, 0.5, 0.75, 1.0]
DRAWS, TSD = 10, 0.25


def partial(rs, grps, fitd, H, rng):
    """the season in progress: features from a share f of season S, simulated from the full one. h1_S and WAR an hour
    get correlated sampling noise (noise()), scaled 1 / (h f) - 1 / h; TOI82 gets ln noise N(0, .25 sqrt((1 - f) / f))
    (role changes: an assumption, as on the NBA rookie board); HPM moves by the change in its Marcel mean (K and the
    shrink target as the live fit), and pWAR, the Marcel WAR, r and lt follow. bfull vs both per f, leave one season
    out; t by player (draws averaged)."""
    G = grps == ['G']
    wts, K, gpw = fitd['wts'], fitd['KG'] if G else fitd['K'], fitd['goalsPerWin']
    ns = noise(rs, H)
    C1 = np.array([[ns['hh'], ns['hw']], [ns['hw'], ns['ww']]])
    base = []
    for r in rs:
        cur = H[r['S']].get(r['key'])
        if not cur:
            continue
        hist = [H.get(r['S'] - j, {}).get(r['key']) for j in range(len(wts))]
        den0 = sum(w * h[1] for w, h in zip(wts, hist) if h)
        num0 = sum(w * h[1] * h[0] for w, h in zip(wts, hist) if h)
        pl = fitd['w'].get('gpl' if G else 'pl', 0) + (fitd['w'].get('pD', 0) if r['grp'] == 'D' else 0)
        base.append((r, cur, den0, num0, pl))
    y = np.array([b[0]['y'] for b in base])
    Sv = np.array([b[0]['S'] for b in base], float)
    grid = []
    for f in FS:
        n = 1 if f == 1 else DRAWS
        R = {k: [] for k in ('S', 'age', 'pw', 'pm', 'r', 'lt', 'grp')}
        for r, cur, den0, num0, pl in base:
            h = cur[1] / 3600
            if f < 1:
                E = rng.multivariate_normal([0, 0], C1 * (1 / (h * f) - 1 / h), n)
                Z = rng.normal(0, TSD * math.sqrt((1 - f) / f), n)
            else:
                E, Z = np.zeros((1, 2)), np.zeros(1)
            tf = cur[1] * f
            raw0 = (num0 + pl * K) / (den0 + K)
            for (eh, ew), z in zip(E, Z):
                den = den0 - (1 - f) * cur[1]
                num = num0 - cur[1] * cur[0] + tf * (cur[0] + eh)
                hpm = r['hpm'] + (num + pl * K) / (den + K) - raw0
                toi82 = r['toi82'] * math.exp(z)
                pnum = r['pmnum'] - r['war'] + (r['wh'] + ew) * tf / 3600
                pden = r['pmden'] - r['toi'] + tf / 60
                R['S'].append(r['S']); R['age'].append(r['age']); R['grp'].append(r['grp'])
                R['pw'].append((hpm - r['repl']) * toi82 / 60 / gpw)
                R['pm'].append((pnum + KP * MU[r['grp']]) / (pden + KP) * toi82)
                R['r'].append(hpm - r['repl']); R['lt'].append(math.log1p(toi82 / 100))
        R = {k: np.array(v) if k == 'grp' else np.array(v, float) for k, v in R.items()}
        yd = np.repeat(y, n)
        pr = {}
        for form in ('both', 'bfull'):
            p = np.zeros(len(yd))
            for s in sorted(set(Sv)):
                tr, te = R['S'] != s, R['S'] == s
                b = np.linalg.lstsq(X(form, {k: v[tr] for k, v in R.items()}, grps), yd[tr], rcond=None)[0]
                p[te] = X(form, {k: v[te] for k, v in R.items()}, grps) @ b
            pr[form] = p
        e = {k: (v - yd) ** 2 for k, v in pr.items()}
        dp = (e['bfull'] - e['both']).reshape(len(y), n).mean(1)
        sm = np.array([dp[Sv == s].mean() for s in sorted(set(Sv))])
        b = np.linalg.lstsq(X('bfull', R, grps), yd, rcond=None)[0]
        g = {'f': f, 'c': [round(float(v), 5) for v in b], 'rmse': {k: round(float(np.sqrt(v.mean())), 4) for k, v in e.items()},
             't': round(tstat(dp), 2), 'won': int((sm < 0).sum()), 'seasons': len(sm),
             'slope': round(float(np.polyfit(pr['bfull'], yd, 1)[0]), 3)}
        grid.append(g)
        print('  f', json.dumps(g), flush=True)
    return {'noise': {k: round(v, 6) if isinstance(v, float) else v for k, v in ns.items()}, 'n': len(base), 'grid': grid}


def main():
    files = load()
    allr = rows(files, 2025)
    fitd = json.load(open(os.path.join(ROOT, 'data', 'nhl_war_fit.json')))
    rng = np.random.default_rng(20261103)
    H = h1_tables(fitd) if '--partial' in sys.argv else None
    out = {'updated': '2026-11-03', 'A0': A0, 'forms': FORMS, 'note': 'pred = X(form) . c; see scripts/nhl_proj_research.py', 'res': {}}
    for part, grps in (('skaters', ['F', 'D']), ('goalies', ['G'])):
        rs = [r for r in allr if (r['grp'] == 'G') == (part == 'goalies')]
        for tgt, mult in (('y1', 1), ('y3', 3)):
            sub = [r for r in rs if tgt == 'y1' or r['n3']]
            R = arr(sub)
            y = R[tgt]
            pr = evaluate(R, y, grps, mult)
            full = report(pr, y, R['S'], np.ones(len(y), bool))
            tm = R['S'] <= 2016
            pt = evaluate(R, y, grps, mult, train_mask=tm)
            held = report(pt, y, R['S'], ~tm)
            fits = {}
            for f in FORMS[1:]:
                fits[f] = [round(float(v), 5) for v in np.linalg.lstsq(X(f, R, grps), y, rcond=None)[0]]
            out['res'][f'{part}:{tgt}'] = {'loso': full, 'held2017': held, 'c': fits}
            print(part, tgt, json.dumps(full), '\n  held', json.dumps(held), flush=True)
            if H is not None and tgt == 'y3':
                for r in sub:
                    r['y'] = r[tgt]
                out['res'][f'{part}:{tgt}']['partial'] = partial(sub, grps, fitd, H, rng)
    # what the live board reads (scripts/nhl_players.py proj3): the kept form's coefficients per season share
    out['mu'] = MU
    for part, grps in (('skaters', ['F', 'D']), ('goalies', ['G'])):
        pa = out['res'][f'{part}:y3'].get('partial')
        if pa:
            out[part] = {'form': 'bfull', 'grps': grps, 'grid': [{'f': g['f'], 'c': g['c']} for g in pa['grid']]}
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
