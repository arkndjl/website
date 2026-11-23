#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer SV (season value) and SVAR: GAR rebuilt from this season alone (Noah, Nov 20 2026: season-only metrics are
SV, conviction rests on them). data/soccer_sv_fit.json; sv / svar on every row of static/data/soccer-war/<season>.json.

    python3 scripts/soccer_sv.py --fit      # fit on every finished big-five season, write the fit, refill the files
    python3 scripts/soccer_sv.py --inject   # refill sv / svar in the season files from the cached rows
    (the live run: scripts/soccer_players.py write() calls attach() for each season it writes)

What GAR leans on that SV drops: GAR's xG plus-minus is a three-season ridge (S-2..S) and its display rates (p/90,
1Y, 3Y) pool earlier seasons. SV reads one season:
- the xG part: GAR's rates and weights (data/soccer_war_fit.json: team xG for / against with him on, on minus off, own
  npxG, xGBuildup; opponent- and home-adjusted inside the season) with the xG plus-minus over this season's spells
  alone (rapm_window span 0; offence prior = his own npxG + xA this season), scaled so a side's players add up to its
  xG difference a match (one scale, fit on 2015-26 team-seasons). The weights are fixed parameters, like the
  replacement lines of the football SVs; no player's other season enters.
- what the xG missed: finishing (goals, penalties in, less non-penalty xG) and keepers' goals saved against the xG
  faced, each shrunk toward the league average by min / (min + k) (Noah, Nov 23 2026). k from split-half reliability
  within a season (odd vs even matches, scripts/soccer_sv_shrink_research.py): saves r .045 -> k 40,000 minutes,
  finishing r .12 -> k 6,000. No player's other season enters.
- league strength as GAR (one scale across the big five; a league constant), its scale re-measured on SV;
  replacement = the xG part of the regulars on each finished league-season's bottom three sides, finishing and saves
  at the league average (bottom-three sides are picked by goal difference, so their finishing and saves are
  unlucky by selection).
Tried first (Nov 23 2026): weights fit on the same season's team goal difference, or on the first half's rates to the
second half's goal difference. Team totals cannot tell how a side's xG splits between its players (shooter's npxG and
the on-pitch share add up to the same team total), so those fits gave all the attack to shooters or spread it evenly
(split-half held R2 .608 vs .603 for even shares) and put keepers at the top. GAR's split is kept instead.
SV = goals over replacement a 90 this season; SVAR = SV x 90s played, season total on the GAR scale (goals).
"""
import datetime as dt
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D
import soccer_players as P

ROOT = os.path.dirname(HERE)
FIT = os.path.join(ROOT, 'data', 'soccer_sv_fit.json')
RAPM_LAM = P.RAPM_LAM


def season_rapm(rows, segs, seasons, lam):
    """sorp / sdrp on every row of the given seasons: the xG plus-minus over that season's spells alone"""
    for S in seasons:
        co = P.rapm_window(segs, rows, S, lam=lam, span=0)
        for r in rows:
            if r['S'] == S:
                r['sorp'], r['sdrp'] = co.get(str(r['p']), (0.0, 0.0))


def _rel(g, key, raw, shrink):
    """a rate relative to the league-season (minutes-weighted), shrunk toward the position mean by `shrink` minutes"""
    tot = sum(r['min'] for r in g) or 1
    for r in g:
        r['_' + key] = raw(r) / (max(r['min'], 1) / 90)
    mu = sum(r['_' + key] * r['min'] for r in g) / tot
    for pos in ('GK', 'D', 'M', 'F'):
        ps = [r for r in g if r['pos'] == pos]
        pm = sum(r['min'] for r in ps) or 1
        pmu = sum((r['_' + key] - mu) * r['min'] for r in ps) / pm
        for r in ps:
            w = r['min'] / (r['min'] + shrink) if shrink else 1.0
            r[key] = w * (r['_' + key] - mu) + (1 - w) * pmu


SHRINK_FILE = os.path.join(ROOT, 'research', 'soccer_sv_shrink.json')


def face_k(F=None):
    """(keeper saves k, finishing k) in minutes: split-half shrink (scripts/soccer_sv_shrink_research.py)"""
    if F and 'kGk' in F:
        return F['kGk'], F['kFin']
    try:
        R = json.load(open(SHRINK_FILE))
        return R['gk0']['k'] or 1e9, R['fin']['k'] or 1e9
    except (OSError, KeyError, ValueError):
        return 0, 0


def sv_rows(rows, shrink, F=None):
    """a copy of the rows with the season-only plus-minus in orp / drp, rates at `shrink`; fin (goals less npxG a 90)
    and gk0 (keeper goals saved vs xG faced a 90) relative to the league-season (gk0: its keepers), each shrunk toward
    that average (0) by min / (min + k), k from the split-half test (no player prior)"""
    kg, kf = face_k(F)
    rs = [dict(r, orp=r.get('sorp', 0.0), drp=r.get('sdrp', 0.0)) for r in rows]
    P.prep(rs, shrink)
    by = defaultdict(list)
    for r in rs:
        by[(r['lg'], r['S'])].append(r)
    for g in by.values():
        tot = sum(r['min'] for r in g) or 1
        fm = sum(r['g'] - r['x'] + r['pen'] for r in g) / tot * 90
        ks = [r for r in g if r['pos'] == 'GK']
        km = sum(r['gks'] for r in ks) / max(1, sum(r['min'] for r in ks)) * 90
        for r in g:
            m = max(r['min'], 1)
            r['fin'] = ((r['g'] - r['x'] + r['pen']) / (m / 90) - fm) * m / (m + kf)
            r['gk0'] = (r['gks'] / (m / 90) - km) * m / (m + kg) if r['pos'] == 'GK' else 0.0
    return rs


def xg_part(r, F):
    return F['scale'] * sum(F['w'][f_] * r.get(f_, 0.0) for f_ in F['feats'])


def flat(F):
    """the fit as one weight per rate (the xG part scaled, finishing and keeper saves at 1), for soccer_players'
    movers() / repl_line()"""
    w = {f_: F['scale'] * F['w'][f_] for f_ in F['feats']}
    w.update(fin=1.0, gk0=1.0)
    return dict(F, feats=list(F['feats']) + ['fin', 'gk0'], w=w)


def value(r, F):
    """goals a 90 vs the league-season average, before league strength and replacement"""
    return xg_part(r, F) + r.get('fin', 0.0) + r.get('gk0', 0.0)


def lg_adj(r, F, LS):
    return F['lgScale']['k'] * P.lg_of(LS, r['lg'], r['S'])


def fit():
    S1 = D.current_season()
    rows = D.load(P.ROWS)
    done = [r for r in rows if r['S'] < S1]
    seasons = sorted({r['S'] for r in done})
    G = json.load(open(P.FIT))
    feats = [f_ for f_ in G['feats'] if f_ != 'gk']               # keepers: saves at face value (gk0) instead
    kg, kf = face_k()
    F = {'feats': feats, 'w': {f_: G['w'][f_] for f_ in feats}, 'scale': 1.0, 'shrink': G['shrink'], 'rapmLam': RAPM_LAM,
         'kGk': kg, 'kFin': kf}
    segs = {S: P.segments(S) for S in seasons + [S1]}
    season_rapm(done, segs, seasons, RAPM_LAM)
    rs = sv_rows(done, F['shrink'], F)
    ts = P.team_seasons(P.FIRST, S1 - 1)
    agg = defaultdict(lambda: [0.0, 0.0])
    for r in rs:
        k = (r['lg'], r['S'], r['tid'])
        if k in ts:
            sh = r['min'] / (90 * ts[k]['mp'])
            agg[k][0] += sh * xg_part(r, F); agg[k][1] += sh * (r['fin'] + r['gk0'])
    kk = sorted(agg)
    A = np.array([agg[k] for k in kk]); g = np.array([ts[k]['gd'] / ts[k]['mp'] for k in kk])
    xd = np.array([ts[k]['xgd'] / ts[k]['mp'] for k in kk])
    grp = defaultdict(list)
    for i, k in enumerate(kk):
        grp[(k[0], k[1])].append(i)
    for ix in grp.values():
        A[ix] -= A[ix].mean(0); g[ix] -= g[ix].mean(); xd[ix] -= xd[ix].mean()
    F['scale'] = round(float((A[:, 0] @ xd) / (A[:, 0] @ A[:, 0])), 4)
    tot = F['scale'] * A[:, 0] + A[:, 1]
    r2 = lambda y, p: round(1 - float(np.mean((y - p) ** 2)) / float(np.mean(y ** 2)), 3)
    LS = P.league_strength()
    F['lgScale'] = P.movers(rs, LS, flat(F))
    xf = dict(flat(F), feats=feats)                               # the replacement line: the xG part only
    F['repl'] = P.repl_line(rs, xf, LS, S1)
    by = {S: r2(g[[i for i, k in enumerate(kk) if k[1] == S]], tot[[i for i, k in enumerate(kk) if k[1] == S]]) for S in seasons}
    out = dict(F, asof=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), ptsPerGoal=G['ptsPerGoal'],
               r2XgPart=r2(xd, F['scale'] * A[:, 0]), r2Gd=r2(g, tot), r2GdBySeason=by, r2GarGd=None,
               teamSeasons=len(kk), seasons=[seasons[0], seasons[-1]])
    # GAR's own values on the same team-seasons, for comparison
    rg = [dict(r) for r in done]
    P.prep(rg, G['shrink'])
    kg, Xg, yg = P.design(rg, ts, G['feats'], prior=False)
    out['r2GarGd'] = r2(yg, Xg @ np.array([G['w'][f_] for f_ in G['feats']]))
    json.dump(out, open(FIT, 'w'), indent=1, allow_nan=False)
    print(json.dumps(out, indent=1))
    _FIT[:] = [out]
    # keep the season-only plus-minus on the frozen rows; the live run adds the season in progress
    keep = {(r['p'], r['S'], r['tid']): (r['sorp'], r['sdrp']) for r in done}
    for r in rows:
        if (r['p'], r['S'], r['tid']) in keep:
            r['sorp'], r['sdrp'] = keep[(r['p'], r['S'], r['tid'])]
    season_rapm(rows, segs, [S1], RAPM_LAM)
    D.save(P.ROWS, rows)
    return out


_FIT = []


def _fit():
    if not _FIT:
        try:
            _FIT.append(json.load(open(FIT)))
        except OSError:
            _FIT.append(None)
    return _FIT[0]


def attach(S, rows, out, LS):
    """sv (goals over replacement a 90) and svar (season total) on a season file's rows, from that season's rows only"""
    F = _fit()
    if not F:
        return
    rs = sv_rows([r for r in rows if r['S'] == S], F['shrink'], F)
    by = {(r['p'], r['team']): r for r in rs}
    for o in out:
        r = by.get((o['p'], o['team']))
        if r is None:
            continue
        v = value(r, F) + lg_adj(r, F, LS) - F['repl'][r['pos']]
        o['sv'] = round(v, 3)
        o['svar'] = round(v * r['min'] / 90, 2)


def inject(seasons=None):
    """sv / svar into the written season files from the cached rows (no pull)"""
    rows = D.load(P.ROWS)
    LS = P.league_strength()
    for fn in sorted(os.listdir(P.SDIR)):
        S = int(fn[:4])
        if seasons and S not in seasons:
            continue
        path = os.path.join(P.SDIR, fn)
        d = json.load(open(path))
        attach(S, rows, d['players'], LS)
        open(path, 'w').write(json.dumps(d, separators=(',', ':'), allow_nan=False))
        print(S, sum(1 for o in d['players'] if 'sv' in o), 'of', len(d['players']), flush=True)


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
        inject()
    elif '--inject' in sys.argv:
        inject()
