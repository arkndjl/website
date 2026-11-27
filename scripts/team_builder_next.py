#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Team builder, next season: adds to each plan in static/data/cfb-builder.json (scripts/cfb_transfer.mjs teamBuilder)
and static/data/cbb-builder.json (scripts/cbb_market.py) what the page needs to read it as next season's team.

    python3 scripts/team_builder_next.py          # after fetch_cfb.mjs / cbb_market.py (cfb-board.yml, cbb.yml)
    python3 scripts/team_builder_next.py --test

Per team:
  nx    next season's strength. CFB: Elo from the plan's AV a season (this season's Elo on this season's AV across FBS,
        least squares with a Power 4 step; r2 kept), before the portal (ret), with the usual portal (exp) and after the
        plan. CBB: the builder's ARK rating (returning, after). Rank among FBS / D-I teams on the same projection.
  xw    wins over a conference schedule at those strengths: CFB 12 games, each Elo's win chance against every
        conference mate at its own projection (1 / (1 + 10^(-d/400))); CBB 31 games, P(win) = Phi(d x .68 / 11.4) (the
        rating is points per 100 possessions; 68 a game, the game model's margin sd 11.4)
  war   wins over a replacement team (the 10th percentile projection) on the same schedule
  eff   NIL dollars a win over replacement: next season's spend (kept roster + class + plan) / war, and its rank
  bud   the reported budget for next season (data/nil_budgets.json, low and high, x the market's yearly growth)
  cls   the incoming class: FV, Y1 FV, ARK stars, On% (CFB), $ (xNIL)
  dect  DECT on returners and departures (Declare / Even / College / Transfer), where the draft boards carry it
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SD = os.path.join(ROOT, 'static', 'data')
CFB_GAMES, CBB_GAMES = 12, 31
CBB_POSS, CBB_SD = 0.68, 11.4
REPL_Q = 0.10


def ncdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def lsq(X, y):
    """ordinary least squares, small dense (no numpy needed here)"""
    k = len(X[0]); A = [[sum(X[i][a] * X[i][b] for i in range(len(X))) for b in range(k)] for a in range(k)]
    v = [sum(X[i][a] * y[i] for i in range(len(X))) for a in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(A[r][c])); A[c], A[p] = A[p], A[c]; v[c], v[p] = v[p], v[c]
        for r in range(k):
            if r != c and A[c][c]:
                f = A[r][c] / A[c][c]; A[r] = [x - f * y_ for x, y_ in zip(A[r], A[c])]; v[r] -= f * v[c]
    return [v[i] / A[i][i] for i in range(k)]


def quant(xs, q):
    s = sorted(xs); return s[min(len(s) - 1, max(0, int(q * len(s))))] if s else None


def sched(teams, key, conf_of, pwin, games):
    """xw for every team at strength key, against its conference mates (all teams when it has none)"""
    by = {}
    for t in teams: by.setdefault(conf_of(t), []).append(t)
    def xw(t, s):
        opp = [o for o in by.get(conf_of(t), []) if o is not t] or [o for o in teams if o is not t]
        return games * sum(pwin(s, key(o)) for o in opp) / len(opp)
    return xw


def budget_next(sport, team, season_next):
    B = json.load(open(os.path.join(ROOT, 'data', 'nil_budgets.json')))[sport]
    v = B['teams'].get(team)
    if not v: return None
    g = B.get('growth', 1.0) ** max(0, season_next - B.get('season', season_next))
    return [round(v[0] * g * 1e6, -4), round(v[1] * g * 1e6, -4)]


def rank(teams, key):
    o = sorted(teams, key=lambda t: -key(t)); return {id(t): i + 1 for i, t in enumerate(o)}


def r1(x): return None if x is None else round(x, 1)


# ---------------------------------------------------------------------------------------------------------- CFB
def cfb():
    p = os.path.join(SD, 'cfb-builder.json')
    if not os.path.exists(p): return None
    D = json.load(open(p)); T = D['teams']
    tj = json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))
    elo = {t['tid']: t.get('elo') for t in tj['teams'] if t.get('elo') is not None}
    # this season's Elo on this season's roster AV (FV-based, depth-weighted), with a Power 4 step
    fit = [t for t in T if t['tid'] in elo]
    X = [[1.0, t['av26'], 1.0 if t['level'] == 'P4' else 0.0] for t in fit]; y = [elo[t['tid']] for t in fit]
    b = lsq(X, y)
    pred = [sum(bi * xi for bi, xi in zip(b, x)) for x in X]; my = sum(y) / len(y)
    r2 = 1 - sum((a - c) ** 2 for a, c in zip(y, pred)) / sum((a - my) ** 2 for a in y)
    E = lambda av, t: b[0] + b[1] * av + b[2] * (t['level'] == 'P4')
    pw = lambda a, c: 1 / (1 + 10 ** (-(a - c) / 400))
    for t in T:
        t['_e'] = {'now': elo.get(t['tid'], E(t['av26'], t)), 'ret': E(t['av27'], t), 'exp': E(t['avExp'], t), 'plan': E(t['avPlan'], t)}
    conf = lambda t: t.get('conf') if t.get('conf') and not str(t.get('conf')).startswith('IND') else '_' + t['level']
    WK = json.load(open(os.path.join(ROOT, 'data', 'cfb_war_backtest.json')))['constants']['cwarPerAv']
    out = {}
    for k in ('now', 'ret', 'exp', 'plan'):
        xw = sched(T, lambda o: o['_e']['plan' if k != 'now' else 'now'], conf, pw, CFB_GAMES)
        rk = rank(T, lambda o: o['_e'][k])
        for t in T: out.setdefault(id(t), {})[k] = {'e': round(t['_e'][k]), 'rk': rk[id(t)], 'xw': round(xw(t, t['_e'][k]), 1)}
    rep = quant([t['_e']['plan'] for t in T], REPL_Q)
    xwp = sched(T, lambda o: o['_e']['plan'], conf, pw, CFB_GAMES)
    for t in T:
        war = out[id(t)]['plan']['xw'] - xwp(t, rep)
        spend = t['budget'] - t['left']
        t['nx'] = out[id(t)]; t['war'] = r1(max(0.0, war)); t['spendNext'] = int(spend)
        t['eff'] = int(round(spend / max(war, 0.5), -3))
        t['warSea'] = r1(t['avPlan'] * WK)
        t['bud'] = budget_next('cfb', t['team'], D['next'])
    for t in T: del t['_e']
    er = rank(T, lambda o: -o['eff'])
    for t in T: t['effRk'] = er[id(t)]
    # the class (static/data/cfb-recruits.json) and the redshirts and young players' next FV are already in the chart;
    # here the committed class with its grades
    try:
        R = json.load(open(os.path.join(SD, 'cfb-recruits.json')))
        cls = {}
        for x in R.get('class') or []:
            if x.get('tid') and x.get('status') in ('committed', 'signed', 'enrolled'):
                cls.setdefault(x['tid'], []).append({'name': x['name'], 'pos': x.get('pos'), 'fv': r1(x.get('xfv')), 'y1': r1(x.get('fvOn')), 'on': x.get('pOn'),
                                                     'ark': x.get('ark'), 'stars': x.get('stars'), 'rk': x.get('rank'), 'x': x.get('xnil')})
        for t in T: t['cls'] = sorted(cls.get(t['tid'], []), key=lambda c: -(c['fv'] or 0))
    except (OSError, ValueError): pass
    # DECT from the draft board (cfb-all.json rows carry dectL once the board run writes it)
    try:
        A = json.load(open(os.path.join(SD, 'cfb-all.json'))); c = {k: i for i, k in enumerate(A['cols'])}
        dk = {}
        if 'dectL' in c:
            for r in A['rows']:
                if r[c['dectL']]: dk[(r[c['name']], r[c['team']])] = [r[c['dectL']], r[c['dect']] if 'dect' in c else None, r[c['dectP']] if 'dectP' in c else None]
        for t in T:
            for L in (t.get('leaving') or [], t.get('keep') or [], t.get('priced') or []):
                for x in L:
                    v = dk.get((x['name'], t['team']))
                    if v: x['dect'] = v
            for pz in t['positions']:
                for x in pz.get('chart') or []:
                    v = dk.get((x.get('name'), t['team']))
                    if v and x.get('kind') == 'back': x['dect'] = v
    except (OSError, ValueError, KeyError): pass
    D['nxFit'] = {'b': [round(v, 3) for v in b], 'r2': round(r2, 3), 'n': len(fit), 'games': CFB_GAMES, 'replQ': REPL_Q, 'warPerAv': WK}
    json.dump(D, open(p, 'w'), separators=(',', ':'), allow_nan=False)
    return D['nxFit']


# ---------------------------------------------------------------------------------------------------------- CBB
def cbb():
    p = os.path.join(SD, 'cbb-builder.json')
    if not os.path.exists(p): return None
    D = json.load(open(p)); T = D['teams']
    pw = lambda a, c: ncdf((a - c) * CBB_POSS / CBB_SD)
    conf = lambda t: t.get('conf') or '_'
    out = {}
    for k, key in (('now', 'now'), ('ret', 'ret'), ('plan', 'after')):
        xw = sched(T, lambda o: o['after'] if k != 'now' else o['now'], conf, pw, CBB_GAMES)
        rk = rank(T, lambda o: o[key])
        for t in T: out.setdefault(id(t), {})[k] = {'r': t[key], 'rk': rk[id(t)], 'xw': round(xw(t, t[key]), 1)}
    rep = quant([t['after'] for t in T], REPL_Q)
    xwp = sched(T, lambda o: o['after'], conf, pw, CBB_GAMES)
    for t in T:
        war = out[id(t)]['plan']['xw'] - xwp(t, rep)
        t['nx'] = out[id(t)]; t['war'] = r1(max(0.0, war))
        t['eff'] = int(round(t['spend'] / max(war, 0.5), -3))
        t['bud'] = budget_next('cbb', t['t'], D['season'])
    er = rank(T, lambda o: -o['eff'])
    for t in T: t['effRk'] = er[id(t)]
    try:
        R = json.load(open(os.path.join(ROOT, 'data', 'cbb_recruits.json')))
        cls = {}
        for c in R.get('classes') or []:
            if c.get('year') != D['season']: continue
            for x in c.get('list') or []:
                if x.get('team'):
                    cls.setdefault(x['team'], {})[x['name']] = {'fv': r1(x.get('fv')), 'y1': r1(x.get('y1fv')), 'ark': x.get('ark'), 'stars': x.get('stars')}
        for t in T:
            for cm in t.get('commits') or []:
                cm.update({k: v for k, v in (cls.get(t['t'], {}).get(cm['name']) or {}).items() if v is not None})
    except (OSError, ValueError): pass
    # DECT: the draft board tab rows (scripts/cbb_tabs.py) carry dectL by name and school
    dk = {}
    def walk(o):
        if isinstance(o, dict):
            if o.get('dectL') and o.get('n'): dk[(o['n'], o.get('tm'))] = [o['dectL'], o.get('dect'), o.get('dectP')]
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    try: walk(json.load(open(os.path.join(SD, 'cbb', 'draft.json'))))
    except (OSError, ValueError): pass
    for t in T:
        for L in (t.get('back') or [], t.get('leave') or []):
            for x in L:
                v = dk.get((x['name'], t['t']))
                if v: x['dect'] = v
    D['nxFit'] = {'games': CBB_GAMES, 'poss': CBB_POSS, 'sd': CBB_SD, 'replQ': REPL_Q}
    json.dump(D, open(p, 'w'), separators=(',', ':'), allow_nan=False)
    return D['nxFit']


def test():
    assert abs(ncdf(0) - 0.5) < 1e-9
    b = lsq([[1, 0], [1, 1], [1, 2]], [1, 3, 5]); assert abs(b[0] - 1) < 1e-9 and abs(b[1] - 2) < 1e-9
    T = [{'c': 'A', 's': 0}, {'c': 'A', 's': 0}, {'c': 'A', 's': 0}]
    xw = sched(T, lambda o: o['s'], lambda o: o['c'], lambda a, c: 0.5 if a == c else 1.0, 12)
    assert xw(T[0], 0) == 6 and xw(T[0], 1) == 12
    print('ok')


if __name__ == '__main__':
    if '--test' in sys.argv: test(); sys.exit()
    print('cfb', cfb()); print('cbb', cbb())
