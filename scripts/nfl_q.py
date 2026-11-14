#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""A questionable NFL player's chance to play, from the league's report and snap counts (nflverse).

    python3 scripts/nfl_q.py --fit      # data/nfl_q_fit.json: 'full' (live) and 'walk' (each season on the seasons before)

Ridge logistic (scripts/logit_ridge.py) on last practice x played the club's last game, position group, body part,
last week's listing, games missed in a row, the club's share of its questionables who played earlier that season,
short week, his snap share in his last four games and the club's count of questionables that week. Rows: non-QBs
listed Questionable on the final report, regular season, 2016 on; played = any snap. nfl_games.play_prob reads it
through context() (the inputs for every listing of a season) and prob()."""
import datetime as dt
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIT = os.path.join(os.path.dirname(HERE), 'data', 'nfl_q_fit.json')
FIRST = 2016
POSG = {'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'OT': 'OL', 'OG': 'OL', 'WR': 'WRTE', 'TE': 'WRTE', 'RB': 'RB', 'FB': 'RB',
        'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB',
        'CB': 'DB', 'S': 'DB', 'SS': 'DB', 'FS': 'DB', 'DB': 'DB', 'K': 'ST', 'P': 'ST', 'LS': 'ST'}
PARTS = {'knee': 'knee', 'acl': 'knee', 'mcl': 'knee', 'ankle': 'ankle', 'hamstring': 'hamstring',
         'concussion': 'concussion', 'head': 'concussion', 'shoulder': 'shoulder', 'foot': 'foot', 'toe': 'foot',
         'heel': 'foot', 'achilles': 'achilles', 'calf': 'calf', 'groin': 'groin/hip', 'hip': 'groin/hip',
         'quadricep': 'groin/hip', 'thigh': 'groin/hip', 'back': 'back', 'neck': 'back', 'illness': 'illness',
         'personal': 'non-injury', 'resting': 'non-injury', 'not injury': 'non-injury', 'hand': 'hand/arm',
         'thumb': 'hand/arm', 'finger': 'hand/arm', 'wrist': 'hand/arm', 'elbow': 'hand/arm', 'forearm': 'hand/arm',
         'ribs': 'torso', 'chest': 'torso', 'pectoral': 'torso', 'oblique': 'torso', 'abdomen': 'torso'}
CELLS = ['dnp|False', 'dnp|True', 'full|False', 'full|True', 'limited|False', 'none|False', 'none|True']     # limited|True is the reference
POS = ['DL', 'LB', 'OL', 'RB', 'ST', 'WRTE', 'other']                                                         # DB
PART = ['achilles', 'ankle', 'back', 'calf', 'concussion', 'foot', 'groin/hip', 'hamstring', 'hand/arm', 'illness', 'knee',
        'non-injury', 'none', 'shoulder', 'torso']                                                            # other
LASTS = ['dout', 'qplay', 'qsat']                                                                             # not listed
NAMES = (['cell=' + c for c in CELLS] + ['pos=' + c for c in POS] + ['part=' + c for c in PART] + ['last=' + c for c in LASTS]
         + ['miss=1', 'miss=2', 'club share', 'short week', 'snap share', 'no snaps yet', 'club Q count'])
CLUB_M = 20.0


def part_of(text):
    t = (text or '').lower()
    for k, v in PARTS.items():
        if k in t:
            return v
    return 'other' if t else 'none'


def context(y, games, fresh=False):
    """{(club, week, gsis): inputs} for every non-QB listed Questionable in season y (regular season): what was known
    before that week's game, plus 'played' (None until the week's snap counts are out)."""
    import nfl_games as N
    pfr = {r['gsis_id']: r['pfr_id'] for r in N.rows(N.get('players.csv', f'{N.REL}/players/players.csv', fresh)) if r.get('pfr_id')}
    snaps, pct, tweeks = {}, {}, defaultdict(set)
    try:
        for r in N.rows(N.get(f'snap_counts_{y}.csv', f'{N.REL}/snap_counts/snap_counts_{y}.csv', fresh)):
            if r['game_type'] != 'REG':
                continue
            w = int(r['week'])
            tweeks[N.team(r['team'])].add(w)
            if int(float(r['offense_snaps'] or 0)) + int(float(r['defense_snaps'] or 0)) + int(float(r['st_snaps'] or 0)) > 0:
                snaps[(w, r['pfr_player_id'])] = True
                pct[(w, r['pfr_player_id'])] = max(float(r['offense_pct'] or 0), float(r['defense_pct'] or 0))
    except Exception as e:      # noqa: BLE001  (a season with no snap file yet: every input that needs one is empty)
        print('nfl q: snap counts', y, repr(e))
    day = {}
    for g in games:
        if int(g['season']) == y and g['game_type'] == 'REG':
            for s in ('home', 'away'):
                day[(N.team(g[f'{s}_team']), int(g['week']))] = dt.date.fromisoformat(g['gameday'])
    inj = [r for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv', fresh)) if r.get('game_type', 'REG') == 'REG']
    listed = defaultdict(dict)
    for r in inj:
        if r['report_status']:
            listed[(N.team(r['team']), int(r['week']))][r['gsis_id']] = r['report_status']
    nq = {k: sum(1 for s in v.values() if s == 'Questionable') for k, v in listed.items()}
    tq = defaultdict(lambda: [0.0, 0.0])
    out = {}
    for r in inj:
        if r['report_status'] != 'Questionable' or r['position'] == 'QB':
            continue
        p = pfr.get(r['gsis_id']); w = int(r['week']); t = N.team(r['team'])
        if not p or (t, w) not in day:
            continue
        prior = sorted(x for x in tweeks.get(t, ()) if x < w)
        pw = prior[-1] if prior else None
        miss = 0
        for x in reversed(prior):
            if snaps.get((x, p)):
                break
            miss += 1
        if prior and not any(snaps.get((x, p)) for x in prior):
            miss = 1                            # no game yet this season: one absence, not a run of them
        lw = listed.get((t, pw), {}).get(r['gsis_id']) if pw else None
        lastp = [pct[(x, p)] for x in reversed(prior) if (x, p) in pct][:4]
        played = float(bool(snaps.get((w, p)))) if w in tweeks.get(t, ()) else None
        if played is not None:
            tq[(t, w)][0] += played; tq[(t, w)][1] += 1
        out[(t, w, r['gsis_id'])] = {
            'prac': N.practice_of(r['practice_status']) or 'none', 'recent': pw is None or bool(snaps.get((pw, p))),
            'pos': POSG.get(r['position'], 'other'), 'part': part_of(r['report_primary_injury']),
            'last': 'none' if not lw else ('qplay' if snaps.get((pw, p)) else 'qsat') if lw == 'Questionable' else 'dout',
            'miss': min(miss, 2), 'short': float(pw is not None and (t, pw) in day and (day[(t, w)] - day[(t, pw)]).days <= 5),
            'share': sum(lastp) / len(lastp) if lastp else 0.0, 'noshare': float(not lastp), 'nq': nq[(t, w)], 'played': played}
    for (t, w, _), c in out.items():
        a = [0.0, 0.0]
        for (t2, w2), v in tq.items():
            if t2 == t and w2 < w:
                a[0] += v[0]; a[1] += v[1]
        c['club'] = a
    return out


def vector(c, league):
    cell = f"{c['prac']}|{c['recent']}"
    return ([float(cell == x) for x in CELLS] + [float(c['pos'] == x) for x in POS] + [float(c['part'] == x) for x in PART]
            + [float(c['last'] == x) for x in LASTS]
            + [float(c['miss'] == 1), float(c['miss'] == 2), (c['club'][0] + CLUB_M * league) / (c['club'][1] + CLUB_M) - league,
               c['short'], c['share'], c['noshare'], float(c['nq'])])


def prob(c, fit):
    """P(plays) for one listing's inputs under a fit ({'b', 'mu', 'sd', 'league'})"""
    import math
    x = vector(c, fit['league'])
    z = fit['b'][0] + sum(b * (v - m) / s for b, v, m, s in zip(fit['b'][1:], x, fit['mu'], fit['sd']))
    return min(0.995, max(0.005, 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))))


_FIT = None


def load():
    global _FIT
    if _FIT is None:
        try:
            _FIT = json.load(open(FIT))
        except (OSError, ValueError):
            _FIT = {}
    return _FIT


def fit_for(y=None):
    """the fit a season's history reads (the seasons before it; None before two exist) or, with no season, live's"""
    F = load()
    if not F:
        return None
    return F.get('full') if y is None else F.get('walk', {}).get(str(y))


def fit(last=2025):
    import numpy as np
    import nfl_games as N
    from logit_ridge import fit_ridge, pick_lambda
    games, _, _ = N.load(last)
    rows = []
    for y in range(FIRST, last + 1):
        rows += [(y, c) for c in context(y, games).values() if c['played'] is not None]
    S = np.array([y for y, _ in rows]); yv = np.array([c['played'] for _, c in rows])

    def one(k, lam=None):
        lg = float(yv[k].mean())
        X = np.array([vector(c, lg) for _, c in rows])
        lam = lam or pick_lambda(X[k], yv[k], S[k])
        b, mu, sd = fit_ridge(X[k], yv[k], lam)
        return {'league': round(lg, 4), 'lambda': lam, 'n': int(k.sum()), 'b': [round(float(v), 5) for v in b],
                'mu': [round(float(v), 5) for v in mu], 'sd': [round(float(v), 5) for v in sd]}
    full = one(S <= last)
    out = {'asof': dt.date.today().isoformat(), 'seasons': [FIRST, last], 'names': NAMES, 'full': full,
           'walk': {str(y): one(S < y, full['lambda']) for y in range(FIRST + 2, last + 2)}}
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    print('nfl q fit', full['n'], 'listings, play rate', full['league'], 'lambda', full['lambda'])
    return out


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
