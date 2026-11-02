#!/usr/bin/env python3
"""Team special teams rating: badge and rating tests, and the team table (see scripts/st_teams.py).

Tests (the team badge recipe, scripts/team_badges.py, pre-registered):
  display  the shrunk rating at each team-season's midpoint against the raw rate over the rest of that season:
           r >= .15 and t >= 2 in the tune AND the held seasons. Pass = shown as a badge.
  rating   home minus away shrunk rating (points a game, and within-season z) against the result minus the close
           (margin): tune t >= 1.5, held b > 0, held-out squared error of close + b x below the close at paired
           t <= -1.5, BH q <= .10 over the family; 'model' = the same against the walk-forward game model's residual.
           A pass then goes into the game model's own walk-forward (nfl_games.py --fit; cfb harness) before shipping.
"""
import collections
import datetime
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import style_research as SR  # noqa: E402
import penalty_research as PR  # noqa: E402
import team_badges as TB  # noqa: E402
import st_teams as ST  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'st_teams_research.json')
STATS = ['st'] + ST.UNITS
NAMES = {'st': 'special teams', 'kr': 'kick returns', 'pr': 'punt returns', 'cov': 'coverage', 'ko': 'kickoffs',
         'punt': 'punting', 'fg': 'field goals and extra points', 'blk': 'blocks'}


def events(sp, raw=None):
    ev = []
    for e in (raw if raw is not None else ST.load(sp)):
        if not e['date']:
            continue
        ev.append(dict(t=SR.when(e['date']), S=e['S'], h=e['h'], a=e['a'], gid=str(e['gid']),
                       sh={k: (e['sh'][k], 1.0) for k in STATS}, sa={k: (e['sa'][k], 1.0) for k in STATS}))
    ev.sort(key=lambda e: e['t'])
    return ev


def n0s(sp, ev):
    rel = PR.reliability(ev, STATS)
    fl = TB.N0_FLOOR[sp]
    return rel, {st: max(fl, min(round(rel[st]['n50']), 40)) if st in rel and math.isfinite(rel[st]['n50']) else 40 for st in STATS}


def pregame(ev, n0):
    pre = {}
    for v in sorted(set(n0.values())):
        ss = [st for st in STATS if n0[st] == v]
        for gid, d in SR.run_roll(ev, v, ss).items():
            q = pre.setdefault(gid, {'h': {}, 'a': {}})
            for s in ('h', 'a'):
                q[s].update(d[s])
    return pre


def main(sp):
    ev = events(sp)
    rel, n0 = n0s(sp, ev)
    pre = pregame(ev, n0)
    tune = SR.TUNE[sp]
    held0 = min(y for y in range(1990, 2100) if y not in tune and y > min(tune))
    own = TB.own_trait(ev, pre, STATS, held0)
    rows = PR.rows_from_wf(sp, pre)
    print(sp, 'rows joined to the walk-forward file', len(rows), flush=True)
    SR.zs(rows, STATS)
    rating = {}
    for k in STATS:
        rating[k] = SR.score(rows, PR.mterm(rows, lambda z, k=k: z.get(k)), False, tune, 1)
        # raw points a game (not z): the model input's natural scale
        x = np.array([(r['st']['h'][k] - r['st']['a'][k]) if r['st']['h'].get(k) is not None and r['st']['a'].get(k) is not None
                      else np.nan for r in rows], float)
        rating[k + '_pts'] = SR.score(rows, x, False, tune, 1)
    # non-return units on top of returns (the NFL model already carries the Return Game term)
    nr = lambda z: (z['st'] - z['kr'] - z['pr']) if all(z.get(u) is not None for u in ('st', 'kr', 'pr')) else None
    xs = np.array([(nr(r['st']['h']) - nr(r['st']['a'])) if nr(r['st']['h']) is not None and nr(r['st']['a']) is not None else np.nan
                   for r in rows], float)
    rating['nonret_pts'] = SR.score(rows, xs, False, tune, 1)
    keys = list(rating)
    p = [2 * (1 - 0.5 * (1 + math.erf(abs(rating[k]['z']) / math.sqrt(2)))) for k in keys]
    for k, pi, q in zip(keys, p, H.bh(p)):
        rating[k]['p'], rating[k]['q'] = round(pi, 5), round(float(q), 4)
        rating[k]['pass'] = bool(rating[k]['pass_split'] and q <= .10)
    for k in STATS:
        print(f"{sp} {k:5} rel {rel.get(k, {}).get('season_r')} n0 {n0[k]:3}  own {own[k]}", flush=True)
    for k in keys:
        o = rating[k]
        print(f"{sp} {k:10} tune {o['tune']} held {o['held']} seHeld {o['seHeld']} model {o.get('model')} q {o['q']} pass {o['pass']}", flush=True)
    res = json.load(open(OUT)) if os.path.exists(OUT) else {'sports': {}}
    res['asof'] = datetime.date.today().isoformat()
    S = max(e['S'] for e in ev)
    res['sports'][sp] = {'cuts': end_cuts([e for e in ev if e['S'] < S], n0['st']), 'prior': prior_of(ev, S - 1), 'n0': n0, 'reliability': rel, 'own': own, 'rating': rating, 'held_from': held0, 'tune': [min(tune), max(tune)],
                         'shown': [k for k in STATS if own[k]['pass']], 'names': NAMES}
    with open(OUT, 'w') as fh:
        json.dump(res, fh, indent=1, allow_nan=False)


def end_cuts(ev, n0):
    """tier cuts: pooled within-season z of each team-season's final shrunk rating (all seasons in the cache)"""
    R = SR.Roll(n0)
    for e in ev:
        for s, k in (('h', 'sh'), ('a', 'sa')):
            R.add(e['S'], e[s], 'st', *e[k]['st'])
    ends = {(SS, t): R.get(SS, t, 'st') for (SS, t) in list(R.cur.keys())}
    return TB.cuts_from(ends, 1)


def prior_of(ev, S):
    """season S's totals by team and the league's (num, den, games) for every stat: the next season's prior in CI"""
    tm = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0, 0]))
    lg = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for e in ev:
        if e['S'] != S:
            continue
        for s, k in (('h', 'sh'), ('a', 'sa')):
            for st, (n, d) in e[k].items():
                for x in (tm[e[s]][st], lg[st]):
                    x[0] += n; x[1] += d; x[2] += 1
    r = lambda x: [round(x[0], 3), x[1], x[2]]
    return {'season': S, 'teams': {t: {st: r(x) for st, x in d.items()} for t, d in tm.items()}, 'lg': {st: r(x) for st, x in lg.items()}}


def build(sp):
    """this season's table: per team games, raw per-game units, the shrunk rating (as of now), the badge tier"""
    S = ST.season_now()
    raw_ev = (ST.nfl_events if sp == 'nfl' else ST.cfb_events)(first=S - 1, save=False)
    ev = events(sp, raw_ev)
    res = json.load(open(OUT))['sports'][sp]
    n0 = res['n0']
    R = {v: SR.Roll(v) for v in set(n0.values())}
    if sum(1 for e in ev if e['S'] == S - 1) < 100 and res.get('prior', {}).get('season') == S - 1:
        for v, RR in R.items():         # last season from the committed totals (CI's cache may lack it)
            for t, d in res['prior']['teams'].items():
                for st, x in d.items():
                    RR.cur[(S - 1, t)][st] = list(x)
            for st, x in res['prior']['lg'].items():
                RR.lg[S - 1][st] = list(x)
    raw = collections.defaultdict(lambda: collections.defaultdict(float))
    gp = collections.Counter()
    for e in ev:
        for s, k in (('h', 'sh'), ('a', 'sa')):
            for st in STATS:
                R[n0[st]].add(e['S'], e[s], st, *e[k][st])
            if e['S'] == S:
                gp[e[s]] += 1
                for st in STATS:
                    raw[e[s]][st] += e[k][st][0]
    cuts = res['cuts']
    teams = [t for t in gp if sp == 'nfl' or gp[t] >= 4]     # CFB: FBS teams (FCS sides play 1-2 FBS games)
    cur = {t: {st: R[n0[st]].get(S, t, st) for st in STATS} for t in teams}
    lgm = {st: float(np.mean([cur[t][st] for t in teams])) for st in STATS}
    sd = float(np.std([cur[t]['st'] for t in teams])) or 1.0
    names = team_names(sp, teams, raw_ev)
    rows = []
    for t in teams:
        z = (cur[t]['st'] - lgm['st']) / sd
        tier = next((tt for _, tt in TB.TIERS if z >= cuts[tt]), None) if res['own']['st']['pass'] else None
        pct = sum(1 for q in cuts['q'] if z >= q)
        n = gp[t]
        rows.append({'id': t, 'pct': pct, 't': names.get(t, {}).get('n', t), 'ab': names.get(t, {}).get('ab', t), 'lg': names.get(t, {}).get('lg'),
                     'g': n, 'adj': round(cur[t]['st'] - lgm['st'], 2), 'pts': round(raw[t]['st'], 1),
                     'pg': round(raw[t]['st'] / n, 2), **{u: round(raw[t][u] / n, 2) for u in ST.UNITS},
                     **({'tier': tier} if tier else {}), 'z': round(z, 2)})
    rows.sort(key=lambda r: -r['adj'])
    wk = max((e.get('wk', 0) for e in raw_ev if e['S'] == S), default=0)
    out = {'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'season': S, 'week': wk,
           'n0': n0['st'], 'rel': res['reliability']['st']['season_r'], 'own': res['own']['st'],
           'rating': {k: {'held': res['rating'][k]['held'], 'seHeld': res['rating'][k]['seHeld'], 'pass': res['rating'][k]['pass']}
                      for k in ('st_pts',)},
           'game_model': GAME_MODEL.get(sp), 'rows': rows}
    with open(os.path.join(ROOT, 'data', f'st_teams_{sp}.json'), 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    print(sp, S, 'teams', len(rows), 'top', [(r['ab'], r['adj']) for r in rows[:5]], flush=True)


# the game-model tests (Nov 2 2026), one line under each table
GAME_MODEL = {
    'nfl': 'Not a game model input: against the close it gains in neither 2015-21 (t 1.7) nor 2022-26 (t 0.8, no held-out '
           'error gain), and in the NFL model\'s walk-forward it adds error in 2015-20 and 2021-25 (alone, in place of the '
           'Return Game term, or its non-return units beside it). The model keeps the Return Game term.',
    'cfb': 'Not a game model input: against the close and the CFB model it gains in 2023-26 (t 2.3) but not in 2017-22 '
           '(t 0.8), so it fails the both-periods rule.',
}


def team_names(sp, teams, raw_ev):
    """NFL: abbreviations. CFB: ESPN team id -> the site's short name (the walk-forward file's, joined by game id) + logo"""
    if sp == 'nfl':
        return {t: {'n': t, 'ab': t} for t in teams}
    import gzip
    wf = {str(r['id']): r for r in json.load(gzip.open(SR.WF.format('cfb')))}
    out = {}
    for e in raw_ev:
        r = wf.get(str(e['gid']))
        if r:
            for s, k in (('h', 'home'), ('a', 'away')):
                out[e[s]] = {'n': r[k], 'ab': r[k], 'lg': f'/img/cfb/logos/{e[s]}.png'}
    return out


if __name__ == '__main__':
    {'research': main, 'build': build}[sys.argv[1]](sys.argv[2])
