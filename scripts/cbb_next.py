#!/usr/bin/env python3
"""CBB next-season WAR (Nov 3 2026): the inputs and the live projection shared by scripts/cbb_next_research.py (fit)
and scripts/cbb_tabs.py (the WAR tab's Next column). Pure Python; coefficients in data/cbb_next_fit.json.

    WAR (31 games) = (BPM + 2) x min% / 100 x 31 x .68 x .01432       (scripts/cbb_tabs.py WAR at a 31-game season)
    last season's view: M2 = OLS on last season's line (BPM, 3-year BPM, min%, class, transfer and team strength,
                        recruit rank, WAR, age, seasons, BPM over position, OBPM, usage, height)
    this season's view: the in-season grid, coefficients by season share f = team games / 31 (linear between points)
"""
import datetime as dt
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_next_fit.json')
WPP, PACE, REPL, G31 = 0.01432, 0.68, -2.0, 31
K = G31 * PACE * WPP
POSMAP = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'G', 'Wing F': 'F', 'Stretch 4': 'F', 'PF/C': 'C', 'C': 'C'}
CLS = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4}
NX = 11                                   # inputs without an in-season line (f 0)


def f(x, d=None):
    try:
        v = float(x)
        return d if math.isnan(v) else v
    except (TypeError, ValueError):
        return d


def war(bpm, mp):
    """WAR at a 31-game season from BPM and min% (share of team minutes)"""
    return (bpm - REPL) * mp / 100 * K


def line(gbpm, obpm, usg, mins, team_games):
    """a to-date line from game logs: minute-weighted game BPM, game OBPM, usage; min% of the team's minutes; minutes"""
    return (gbpm, obpm, usg, min(100.0, 100 * mins / (40 * team_games)), mins)


def pxrow(r, td, prev, pm):
    """in-season inputs: r = the season in progress (yr, rg_lrk, unranked, age, seasons, hti, role; its BPM and minutes
    are not read), td = to-date line (None at f 0), prev = the season before ({bpm3, min_per} or None), pm = position
    -> minutes-weighted BPM mean of the season before"""
    lr = f(r.get('rg_lrk'))
    lr = lr if lr is not None and f(r.get('unranked'), 1) == 0 else -math.log(600)
    c = CLS.get(r['yr'], 3)
    a = f(r.get('age'), 21.0)
    b3 = f(prev['bpm3']) if prev is not None and f(prev.get('bpm3')) is not None else None
    m3 = f(prev['min_per'], 0) / 100 if prev is not None else 0.0
    x = [1.0, 1.0 if c == 1 else 0.0, 1.0 if c == 2 else 0.0, lr, b3 if b3 is not None else 0.0, 1.0 if b3 is None else 0.0, m3,
         a - 21, (a - 21) ** 2, min(f(r.get('seasons'), 2), 6) - 2, f(r.get('hti'), 78) - 78]
    if td is None:
        return x
    b, ob, us, mp, mins = td
    b = max(-15, min(15, b))
    return x + [b, mp / 100, b * mp / 100, war(b, mp), b - pm.get(POSMAP.get(r['role'], 'F'), 0.0), ob, us - 18, math.log1p(mins)]


def grid_coef(grid, fr):
    """coefficients at season share fr, linear between grid points (f 0, no line to date, gets zeros on the to-date
    inputs, so a first game moves the projection a little and f .1 fully)"""
    n = len(grid[-1]['c'])
    g = [{'f': p['f'], 'c': p['c'] + [0.0] * (n - len(p['c']))} for p in grid]
    fr = min(max(fr, 0.0), 1.0)
    for a, b in zip(g, g[1:]):
        if fr <= b['f']:
            w = (fr - a['f']) / (b['f'] - a['f'])
            return [u + (v - u) * w for u, v in zip(a['c'], b['c'])]
    return g[-1]['c']


def bpm3(seasons, upto):
    """3-season BPM through season `upto` as the research column: minutes x 5/4/3 weighted, not shrunk (matches the
    research bpm3 to rounding), from prior-file career lines ({year, bpm, mp, gp})"""
    L = [s for s in seasons if upto - 2 <= s['year'] <= upto]
    num = den = 0.0
    for w, z in zip((5, 4, 3), reversed(L[-3:])):
        mm = (z.get('mp') or 0) * (z.get('gp') or 0)
        if z.get('bpm') is not None:
            num += w * mm * z['bpm']; den += w * mm
    return num / den if den else None


def live(games, prior, season, gl):
    """the season in progress -> {(board name, board team): next season's WAR}. prior = scripts/cbb_prior.json.gz (the
    frozen preseason board: rows, careers, keep); games = this season's Barttorvik-shaped game rows; gl = column index
    (min, usg, obpm, gbpm, team, pid, muid, name). A career without a Barttorvik pid (freshmen) joins its game rows by
    name key + Barttorvik team, as scripts/cbb_live.py does."""
    import names
    fit = json.load(open(FIT))
    ins = fit['inseason']
    pm = fit['posmean'][str(season - 1)]
    tg, acc, keys = {}, {}, {}
    for g in games:
        tg.setdefault(g[gl['team']], set()).add(g[gl['muid']])
        if not g[gl['min']]:
            continue
        pid = str(g[gl['pid']])
        keys[(names.key(g[gl['name']]), g[gl['team']])] = pid
        a = acc.setdefault(pid, [0.0, 0.0, 0.0, 0.0, g[gl['team']]])
        m = g[gl['min']]
        a[0] += m; a[1] += m * (g[gl['gbpm']] or 0); a[2] += m * (g[gl['obpm']] or 0); a[3] += m * (g[gl['usg']] or 0); a[4] = g[gl['team']]
    ci = {k: i for i, k in enumerate(prior['cols'])}
    feb = dt.date(season, 2, 1)
    out, used = {}, set()
    for row, c in zip(prior['rows'], prior['careers']):
        pid = str(c.get('pid') or '')
        if pid not in acc:
            pid = keys.get((c.get('key'), c.get('bt')))
        a = acc.get(pid)
        if not a or pid in used:
            continue
        used.add(pid)
        S = [dict(zip(prior['keep'], x)) for x in c['seasons']]
        now = next((s for s in S if s['year'] == season), None) or {}
        prev = next((s for s in S if s['year'] == season - 1), None)
        g = c.get('rec') or {}
        rk = [float(v) for v in (g.get('on3rk'), g.get('rk247')) if v]
        age = None
        try:
            if c.get('dob'):
                age = (feb - dt.date.fromisoformat(c['dob'])).days / 365.25
        except ValueError:
            pass
        if age is None:                  # the board's age entering the season (Nov), moved to Feb 1 like the research ages
            b = row[ci['age']] if row[ci['age']] is not None else row[ci['ageEst']]
            age = b + 0.25 if b is not None else None
        r = {'yr': now.get('yr') or row[ci['cls']], 'rg_lrk': sum(-math.log(min(v, 500)) for v in rk) / len(rk) if rk else None,
             'unranked': 0.0 if rk else 1.0, 'age': age, 'seasons': 1 + sum(1 for s in S if s['year'] < season and s.get('min_per')),
             'hti': now.get('hti'), 'role': now.get('role') or row[ci['role']]}
        pv = {'bpm3': bpm3(S, season - 1), 'min_per': prev.get('min_per')} if prev else None
        n = len(tg.get(a[4], ())) or 1
        td = line(a[1] / a[0], a[2] / a[0], a[3] / a[0], a[0], n)
        x = pxrow(r, td, pv, pm)
        out[(row[ci['name']], row[ci['team']])] = sum(u * v for u, v in zip(grid_coef(ins['grid'], n / G31), x))
    return out
