#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Unit badges and game-model tests for the team unit ratings.

The unit tables (scripts/team_units.py) rate each team's offense and defense, opponent-adjusted. This asks two
questions, by the same pre-registered recipe as scripts/team_badges.py:
  1. badge: is a team's midseason value (shrunk season-to-date, raw or opponent-adjusted) related to its own
     rest-of-season rate? r >= .15 and t >= 2 in both the tune and held seasons -> the badge is shown.
  2. game model: does home minus away (offense, defense allowed, net) predict the result minus the closing line,
     tune t >= 1.5, held slope the same sign, held squared error down (paired t <= -1.5), BH q <= .10 over every
     test here? The residual against our own walk-forward model is reported too.
Metrics (o = the offense of the row, d = the defense it faced):
  nfl  epa (EPA a play), sr (success rate): nflverse pbp, run/pass plays, win prob 5-95%
  cfb  epa, sr: ESPN pbp, our EP model (net drive points), garbage time out (team_units.cfb_*)
  nba  rtg: points a 100 possessions (nba_games_hist)
  cbb  rtg: points a 100 possessions (Barttorvik game stats)
  nhl  x5: 5v5 xG a game; pp: power-play xG a minute (the defense side is the penalty kill)
  soccer xg: match xG (soccer_games_hist), opponent adjustment within each league
Adjusted values: each morning a ridge (offense + defense + home) on the season's games so far, each team held
toward half its last-season effect with k = the exposure at which split-half reliability is .5 (tune seasons).
    python3 scripts/unit_badges.py research [sport ...]   -> data/unit_badges_research.json, data/unit_badges.json
Result (Nov 2 2026, 54 tests): every unit passes the badge test in all six sports (adjusted midseason r .39-.80 with
the rest of the season); none beats the close. Against our own model only CFB success-rate net (adjusted) passes on
squared error (held t -1.50) while absolute error gets worse (t +.39), the same as the Oct 29 CFB sweep, so no game
model changed. Watch: CBB efficiency slopes vs the close (tune t +5.0, held +2.9) do not cut squared error; NHL power
play vs our model turned negative in held seasons (t -2.7 to -4.2) after a positive tune.
Badges: team_units.unit_tiers (medals in the unit tables) and team_badges_build.unit_badges (team pages).
"""
import collections
import datetime
import gzip
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

OUT = os.path.join(ROOT, 'data', 'unit_badges_research.json')
CUTS = os.path.join(ROOT, 'data', 'unit_badges.json')
SPORTS = ['nfl', 'cfb', 'nba', 'cbb', 'nhl', 'soccer']
# sport -> [(metric, offense badge, defense badge, what it is)]
METRICS = {
    'nfl': [('epa', 'Top Offense', 'Top Defense', 'EPA a play'), ('sr', 'Efficient Offense', 'Efficient Defense', 'success rate')],
    'cfb': [('epa', 'Top Offense', 'Top Defense', 'EPA a play'), ('sr', 'Efficient Offense', 'Efficient Defense', 'success rate')],
    'nba': [('rtg', 'Top Offense', 'Top Defense', 'points a 100 possessions')],
    'cbb': [('rtg', 'Top Offense', 'Top Defense', 'points a 100 possessions')],
    'nhl': [('x5', 'Top 5v5 Offense', 'Top 5v5 Defense', '5v5 xG a game'), ('pp', 'Top Power Play', 'Top Penalty Kill', 'power-play xG a minute')],
    'soccer': [('xg', 'Top Attack', 'Top Defence', 'xG a match')],
}


def day(x):
    return x if isinstance(x, datetime.date) and not isinstance(x, datetime.datetime) else SR.when(str(x)).date()


# ---------------------------------------------------------------- observations: one row per game side per metric
# {S, grp, date, gid, o, d, h (+1 o at home, -1 away, 0 neutral), home (home team), away, v, e}
def obs_nfl():
    import csv
    NFL_FR = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA'}
    T = lambda t: NFL_FR.get(t, t)
    out = collections.defaultdict(list)
    for y in range(2014, 2027):
        p = os.path.join(HERE, '.cache', 'nfl', f'play_by_play_{y}.csv.gz')
        if not os.path.exists(p):
            continue
        M = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
        meta = {}
        with gzip.open(p, 'rt', encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                if r['season_type'] != 'REG' or r['play_type'] not in ('run', 'pass'):
                    continue
                try:
                    epa, wp = float(r['epa']), float(r['wp'])
                except ValueError:
                    continue
                o, d = T(r['posteam']), T(r['defteam'])
                if not o or not d:
                    continue
                g = r['game_id']
                meta[(g, o)] = (d, T(r['home_team']), T(r['away_team']), r['game_date'])
                if not (0.05 <= wp <= 0.95):
                    continue
                M['epa'][(g, o)][0] += epa; M['epa'][(g, o)][1] += 1
                M['sr'][(g, o)][0] += float(r['success'] or 0); M['sr'][(g, o)][1] += 1
        for m, D in M.items():
            for (g, o), (v, e) in D.items():
                d, hm, aw, dt = meta[(g, o)]
                out[m].append(dict(S=int(g[:4]), grp='nfl', date=day(dt), gid=g, o=o, d=d, h=1 if o == hm else -1,
                                   home=hm, away=aw, v=v, e=e))
        print('nfl', y, len(M['epa']), flush=True)
    return out


def obs_cfb():
    import team_units as TU
    out = collections.defaultdict(list)
    wf = {str(r['id']): r for r in json.load(gzip.open(SR.WF.format('cfb')))}
    prev = None
    for S in range(2016, 2027):
        g = TU.cfb_games(S)
        if not g:
            continue
        pl = TU.cfb_plays(g)
        ep = TU.cfb_ep(pl + (prev or []))   # EP fit on this and last season's plays (no outcome of the test in it)
        TU.cfb_epa(pl, ep)
        hm = {}
        for d in g:
            ha = {t.get('ha'): str(t.get('id')) for t in d.get('teams') or []}
            hm[d['id']] = (ha.get('home'), ha.get('away'))
        M = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
        meta = {}
        for p in pl:
            meta[(p['g'], p['o'])] = (p['d'], p['h'], p['date'])
            if p['garb']:
                continue
            M['epa'][(p['g'], p['o'])][0] += p['epa']; M['epa'][(p['g'], p['o'])][1] += 1
            M['sr'][(p['g'], p['o'])][0] += p['succ']; M['sr'][(p['g'], p['o'])][1] += 1
        for m, D in M.items():
            for (gid, o), (v, e) in D.items():
                d, h, dt = meta[(gid, o)]
                if not dt:
                    continue
                out[m].append(dict(S=S, grp='cfb', date=day(dt), gid=gid, o=o, d=d, h=h, home=hm[gid][0], away=hm[gid][1], v=v, e=e))
        prev = pl
        print('cfb', S, len(g), 'games', sum(1 for x in M['epa'] if x[0] in wf), 'sides in wf', flush=True)
    return out


def obs_nba():
    out = collections.defaultdict(list)
    for g in json.load(gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz')))['games']:
        if not g.get('fin') or not g.get('poss') or g.get('hs') is None:
            continue
        dt = day(SR.when(g['tip']) - datetime.timedelta(hours=8))   # US evening tips are the next UTC day
        for o, d, h, v in ((g['h'], g['a'], 1, g['hs']), (g['a'], g['h'], -1, g['as'])):
            out['rtg'].append(dict(S=g['S'], grp='nba', date=dt, gid=str(g['id']), o=o, d=d, h=h, home=g['h'], away=g['a'],
                                   v=float(v), e=g['poss'] / 100))
    return out


def obs_cbb():
    """Barttorvik box lists (scripts/.cache/style/cbb_gs{Y}.csv via team_badges_pull.py cbb); t1 is the home side of the
    list, venue from the game record is not in the box, so h = 0 (the ridge carries no home edge) -- the wf join is by
    date and score (penalty_research.cbb_rows)"""
    import ast as A
    import csv
    out = collections.defaultdict(list)
    idx = collections.defaultdict(list)
    seen = set()
    for y in range(2015, 2028):
        p = os.path.join(SR.C, f'cbb_gs{y}.csv')
        if not os.path.exists(p):
            continue
        for r in csv.reader(open(p, encoding='utf-8', errors='replace')):
            if len(r) < 30:
                continue
            try:
                b = A.literal_eval(r[29])
                v1, v2 = [float(v) for v in b[4:19]], [float(v) for v in b[19:34]]
            except (ValueError, SyntaxError, TypeError):
                continue
            m = f'{y}:{r[24]}'
            if m in seen or v1[1] < 30 or v2[1] < 30:
                continue
            seen.add(m)
            mo, dd, yy = b[0].split('/')
            dt = datetime.date(int(yy) + (2000 if len(yy) == 2 else 0), int(mo), int(dd))
            P = 0.5 * ((v1[1] - v1[6] + v1[12] + .44 * v1[5]) + (v2[1] - v2[6] + v2[12] + .44 * v2[5]))
            for o, d, v in ((b[2], b[3], v1[14]), (b[3], b[2], v2[14])):
                out['rtg'].append(dict(S=y, grp='cbb', date=dt, gid=m, o=o, d=d, h=0, home=b[2], away=b[3], v=v, e=P / 100))
            idx[(dt, tuple(sorted((v1[14], v2[14]))))].append((m, v1[14], v2[14]))
    return out, idx


def obs_nhl():
    out = collections.defaultdict(list)
    for g in json.load(gzip.open(os.path.join(HERE, 'nhl_games_hist.json.gz'))):
        x = g.get('x')
        if not x or g.get('hs') is None:
            continue
        dt = day(g['day'])
        for s, o_, d_, h in (('h', g['h'], g['a'], 1), ('a', g['a'], g['h'], -1)):
            me = x[s]
            base = dict(S=g['S'], grp='nhl', date=dt, gid=str(g['id']), o=o_, d=d_, h=h, home=g['h'], away=g['a'])
            out['x5'].append(dict(base, v=me[3], e=1.0))
            if me[7] > 0:
                out['pp'].append(dict(base, v=me[5], e=me[7]))
    return out


def obs_soccer():
    wf = json.load(gzip.open(SR.WF.format('soccer')))
    lgs = collections.Counter(r['lg'] for r in wf)
    Sof = {r['id']: r['S'] for r in wf}
    out = collections.defaultdict(list)
    bad = 0
    for g in json.load(gzip.open(os.path.join(HERE, 'soccer_games_hist.json.gz'))):
        if g.get('hx') is None or g.get('ax') is None or g['lg'] not in lgs:
            continue
        dt = day(g['day'])
        S = Sof.get(g['id'])
        if S is None:
            S = dt.year + (1 if dt.month >= 7 else 0)
        elif S != dt.year + (1 if dt.month >= 7 else 0):
            bad += 1
        h = 0 if g.get('neu') else 1
        for o, d, hh, v in ((g['h'], g['a'], h, g['hx']), (g['a'], g['h'], -h, g['ax'])):
            out['xg'].append(dict(S=S, grp=g['lg'], date=dt, gid=g['id'], o=o, d=d, h=hh, home=g['h'], away=g['a'], v=float(v), e=1.0))
    print('soccer xG sides', len(out['xg']), 'season-rule mismatches', bad, flush=True)
    return out


# ---------------------------------------------------------------- events for the badge machinery
def events(obs, metrics):
    """per game: home/away {m_o: (own offense v, e), m_d: (opponent offense v, e)}"""
    G = {}
    for m in metrics:
        for x in obs[m]:
            g = G.setdefault(x['gid'], dict(t=datetime.datetime.combine(x['date'], datetime.time(12)), S=x['S'], h=x['home'],
                                            a=x['away'], gid=x['gid'], sh={}, sa={}))
            own, opp = ('sh', 'sa') if x['o'] == x['home'] else ('sa', 'sh')
            g[own][m + '_o'] = (x['v'], x['e'])
            g[opp][m + '_d'] = (x['v'], x['e'])
    return sorted(G.values(), key=lambda e: e['t'])


# ---------------------------------------------------------------- opponent-adjusted, as of each morning
def k_tune(obs, sp):
    """k (o, d) = median over tune seasons of split-half k, per group"""
    import team_units as TU
    tune = set(SR.TUNE[sp])
    by = collections.defaultdict(list)
    for x in obs:
        if x['S'] in tune:
            by[(x['S'], x['grp'])].append(dict(x, date=x['date'].isoformat()))
    ko = [TU.split_k(v, 'o')[0] for v in by.values() if len(v) > 60]
    kd = [TU.split_k(v, 'd')[0] for v in by.values() if len(v) > 60]
    ko, kd = [k for k in ko if k], [k for k in kd if k]
    return float(np.median(ko)), float(np.median(kd))


def roll_adj(obs, ko, kd, home=True):
    """gid -> {team: (offense effect, defense effect allowed)} before the game, from a ridge on the season's
    games so far in the team's group, each effect held toward half its last-season final effect"""
    obs = sorted([x for x in obs if x['e'] > 0], key=lambda x: x['date'])
    teams = collections.defaultdict(set)
    for x in obs:
        teams[(x['S'], x['grp'])] |= {x['o'], x['d']}
    ix = {g: {t: i for i, t in enumerate(sorted(ts))} for g, ts in teams.items()}
    acc = {}
    final = {}            # (S, grp) -> (mu, O, D)
    state = {}            # (S, team) -> (o, d)
    out = {}

    def solve(g):
        A, y, n = acc[g]
        S, grp = g
        pm, pO, pD = final.get((S - 1, grp), (None, {}, {}))
        A2, y2 = A.copy(), y.copy()
        kmu = 2.0 * max(ko, kd)
        if pm is None:
            pm = y[0] / A[0, 0] if A[0, 0] > 0 else 0.0
            kmu = 1e-6
        A2[0, 0] += kmu; y2[0] += kmu * pm
        A2[1, 1] += 1e-6
        for t, i in ix[g].items():
            A2[2 + i, 2 + i] += ko; y2[2 + i] += ko * 0.5 * pO.get(t, 0.0)
            A2[2 + n + i, 2 + n + i] += kd; y2[2 + n + i] += kd * 0.5 * pD.get(t, 0.0)
        s = np.linalg.solve(A2, y2)
        O = {t: float(s[2 + i]) for t, i in ix[g].items()}
        D = {t: float(s[2 + n + i]) for t, i in ix[g].items()}
        return float(s[0]), O, D

    by = collections.OrderedDict()
    for x in obs:
        by.setdefault(x['date'], []).append(x)
    seasons_done = set()
    for dt, xs in by.items():
        for x in xs:          # the morning's table
            q = out.setdefault(x['gid'], {})
            for t in (x['o'], x['d']):
                if t not in q:
                    q[t] = state.get((x['S'], t))
        dirty = set()
        for x in xs:
            g = (x['S'], x['grp'])
            if g not in acc:
                # a new season in this group: freeze last season's final fit
                n = len(ix[g])
                acc[g] = [np.zeros((2 + 2 * n, 2 + 2 * n)), np.zeros(2 + 2 * n), n]
                if (x['S'] - 1, x['grp']) in acc and (x['S'] - 1, x['grp']) not in seasons_done:
                    final[(x['S'] - 1, x['grp'])] = solve((x['S'] - 1, x['grp']))
                    seasons_done.add((x['S'] - 1, x['grp']))
            A, y, n = acc[g]
            r = np.zeros(2 + 2 * n); r[0] = 1; r[1] = x['h'] if home else 0
            r[2 + ix[g][x['o']]] = 1; r[2 + n + ix[g][x['d']]] = 1
            A += x['e'] * np.outer(r, r); y += x['v'] * r
            dirty.add(g)
        for g in dirty:
            mu, O, D = solve(g)
            for t in ix[g]:
                state[(g[0], t)] = (O[t], D[t])      # effects relative to the group's mean (soccer: the league)
    return out


# ---------------------------------------------------------------- research
def model_score(rows, x, tune_yrs):
    """the same split against our walk-forward model: slope of (result - model) on x in tune and held seasons, and
    the held squared error of model + tune-fit term vs the model (paired, clustered by day)"""
    ok = np.array([r['mm'] is not None for r in rows]) & ~np.isnan(x)
    R = [r for r, o in zip(rows, ok) if o]
    x = x[ok]
    y = np.array([r['ym'] for r in R], float)
    mm = np.array([r['mm'] for r in R], float)
    S = np.array([r['S'] for r in R])
    dd = np.array([r['day'] for r in R])
    tune = np.isin(S, list(tune_yrs)); held = ~tune
    X = np.c_[np.ones(len(x)), x]
    res = y - mm
    o = {}
    for part, m in (('tune', tune), ('held', held)):
        b, s_ = SR.ols_cl(X[m], res[m], dd[m])
        o[part] = [round(float(b[1]), 4), round(float(b[1] / s_[1]), 2)]
    bt = SR.ols_cl(X[tune], res[tune], dd[tune])[0]
    new, old = mm + bt[0] + bt[1] * x, mm + res[tune].mean()
    pr = H.paired(H.se(new[held], y[held]), H.se(old[held], y[held]), cluster=dd[held])
    o['seHeld'] = [round(float(pr['d']), 6), round(pr['t'], 2)]
    pa = H.paired(np.abs(new[held] - y[held]), np.abs(old[held] - y[held]), cluster=dd[held])
    o['aeHeld'] = [round(float(pa['d']), 6), round(pa['t'], 2)]
    d = 1 if o['tune'][1] > 0 else -1
    o['z'] = round(H.stouffer([d * o['tune'][1], d * o['held'][1]]), 2)
    o['pass_split'] = bool(d * o['tune'][1] >= 1.5 and d * o['held'][0] > 0 and o['seHeld'][1] <= -1.5)
    return o


def research(sp):
    idx = None
    if sp == 'cbb':
        obs, idx = obs_cbb()
    else:
        obs = {'nfl': obs_nfl, 'cfb': obs_cfb, 'nba': obs_nba, 'nhl': obs_nhl, 'soccer': obs_soccer}[sp]()
    Ms = [m[0] for m in METRICS[sp]]
    ev = events(obs, Ms)
    raw = [m + s for m in Ms for s in ('_o', '_d')]
    rel = PR.reliability(ev, raw)
    n0 = {st: max(PR.N0_FLOOR[sp], min(round(rel[st]['n50']), 40)) if st in rel else PR.N0_FLOOR[sp] for st in raw}
    pre = {}
    for v in sorted(set(n0.values())):
        ss = [st for st in raw if n0[st] == v]
        for gid, d in SR.run_roll(ev, v, ss).items():
            q = pre.setdefault(gid, {'h': {}, 'a': {}})
            for s in ('h', 'a'):
                q[s].update({k: d[s][k] for k in ss})
    ks = {}
    for m in Ms:
        ko, kd = k_tune(obs[m], sp)
        ks[m] = [round(ko, 2), round(kd, 2)]
        A = roll_adj(obs[m], ko, kd, home=sp != 'cbb')
        for e in ev:
            a = A.get(e['gid'], {})
            for s in ('h', 'a'):
                v = a.get(e[s])
                pre.setdefault(e['gid'], {'h': {}, 'a': {}})[s].update({m + '_oA': v[0] if v else None, m + '_dA': v[1] if v else None})
        for e in ev:          # adjusted stats score against the same raw rest-of-season rates
            for k in ('sh', 'sa'):
                for s in ('_o', '_d'):
                    if m + s in e[k]:
                        e[k][m + s + 'A'] = e[k][m + s]
        print(sp, m, 'k', ks[m], flush=True)
    allst = raw + [s + 'A' for s in raw]
    held0 = min(y for y in range(1990, 2100) if y not in SR.TUNE[sp] and y > min(SR.TUNE[sp]))
    own = TB.own_trait(ev, pre, allst, held0)
    orient = lambda st: -1 if '_d' in st else 1
    end = TB.season_end(ev, lambda gid, s, st: pre.get(gid, {}).get(s, {}).get(st), allst)
    cuts = {st: TB.cuts_from({k: v[st] for k, v in end.items()}, orient(st)) for st in allst}
    rows = PR.cbb_rows(pre, idx) if sp == 'cbb' else PR.rows_from_wf(sp, pre)
    SR.zs(rows, allst)
    rating = {}
    for m in Ms:
        for A_ in ('', 'A'):
            o, d = f'{m}_o{A_}', f'{m}_d{A_}'
            for nm, f in ((o, lambda z, o=o: z.get(o)), (d, lambda z, d=d: -z[d] if z.get(d) is not None else None),
                          (f'{m}_net{A_}', PR.net(o, d))):
                x = PR.mterm(rows, f)
                rating[nm] = SR.score(rows, x, False, SR.TUNE[sp], 1)
                rating[nm]['vs_model'] = model_score(rows, x, SR.TUNE[sp])
                r_ = rating[nm]
                print(f"{sp:7}{nm:12} n {r_['n']} close: tune {r_['tune']} held {r_['held']} seHeld {r_['seHeld']}  model: {r_['vs_model']}", flush=True)
    for st in allst:
        print(f"{sp:7}{st:12} rel {rel.get(st.rstrip('A'), {}).get('season_r')} n0 {n0.get(st.rstrip('A'))} own {own[st]}", flush=True)
    names = {}
    for m, on, dn, what in METRICS[sp]:
        names[m + '_o'] = names[m + '_oA'] = [on, 1, what]
        names[m + '_d'] = names[m + '_dA'] = [dn, -1, what + ' allowed']
    return {'n0': n0, 'k': ks, 'reliability': rel, 'own': own, 'cuts': cuts, 'rating': rating, 'held_from': held0,
            'names': names, 'rows': len(rows)}


def main(only):
    res = {}
    if os.path.exists(OUT):
        res = json.load(open(OUT)).get('sports', {})
    for sp in only:
        res[sp] = research(sp)
    tests = [(sp, k) for sp in res for k in res[sp]['rating']]
    p = [2 * (1 - 0.5 * (1 + math.erf(abs(res[sp]['rating'][k]['z']) / math.sqrt(2)))) for sp, k in tests]
    for (sp, k), pi, q in zip(tests, p, H.bh(p)):
        o = res[sp]['rating'][k]
        o['p'], o['q'] = round(pi, 5), round(float(q), 4)
        o['pass'] = bool(o['pass_split'] and q <= .10)
    p = [2 * (1 - 0.5 * (1 + math.erf(abs(res[sp]['rating'][k]['vs_model']['z']) / math.sqrt(2)))) for sp, k in tests]
    for (sp, k), pi, q in zip(tests, p, H.bh(p)):
        o = res[sp]['rating'][k]['vs_model']
        o['p'], o['q'] = round(pi, 5), round(float(q), 4)
        o['pass'] = bool(o['pass_split'] and q <= .10)
    for sp in res:
        res[sp]['model_pass'] = [k for k in res[sp]['rating'] if res[sp]['rating'][k]['vs_model'].get('pass')]
        print(sp, 'vs model pass', res[sp]['model_pass'])
        res[sp]['shown'] = [k for k in res[sp]['own'] if res[sp]['own'][k]['pass']]
        res[sp]['in_rating'] = [k for k in res[sp]['rating'] if res[sp]['rating'][k].get('pass')]
        print(sp, 'shown', res[sp]['shown'], 'rating pass', res[sp]['in_rating'],
              'best q', min([o.get('q', 1) for o in res[sp]['rating'].values()] or [1]))
    json.dump({'asof': datetime.date.today().isoformat(), 'tests': len(tests), 'sports': res}, open(OUT, 'w'), indent=1, allow_nan=False)
    write_cuts()


def write_cuts():
    """data/unit_badges.json: tier cuts of the adjusted (A) values that passed the display test, read by
    team_units.unit_tiers"""
    res = json.load(open(OUT))['sports']
    out = {}
    for sp, r in res.items():
        keep = [k for k in r['shown'] if k.endswith('A')]
        out[sp] = {'cuts': {k: r['cuts'][k] for k in keep}, 'names': {k: r['names'][k] for k in keep}}
        if sp == 'nhl':        # same names as the trait badges they replace on the team pages
            ren = {'x5_oA': 'Play Drivers', 'x5_dA': 'Shot Suppression', 'pp_oA': 'Power Play', 'pp_dA': 'Penalty Kill'}
            for k, n in ren.items():
                if k in out[sp]['names']:
                    out[sp]['names'][k] = [n] + out[sp]['names'][k][1:]
    json.dump({'asof': datetime.date.today().isoformat(), 'sports': out}, open(CUTS, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    if sys.argv[1:2] == ['research']:
        main(sys.argv[2:] or SPORTS)
    elif sys.argv[1:2] == ['cuts']:
        write_cuts()
