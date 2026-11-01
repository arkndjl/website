#!/usr/bin/env python3
"""Team badges (thread "Add predictive team badges", Nov 1 2026; Noah: "team badges, modelled after CFB player badges,
to improve team rankings further and to display on team GFX pages").

A team badge is one trait stat, the CFB player badge recipe applied to a team: the team's season-to-date rate,
shrunk to a prior (half last season's team rate, half the league's) worth n0 games, n0 from the stat's split-half
reliability (the games at which a season-to-date rate is half signal, floored at the style_research n0). Tiers are
percentiles of the within-season z, pooled over every team-season since 2015 (absolute: a season with more elite
units gets more medals): bronze 75th, silver 90th, gold 97th, platinum 99th.

Two tests, pre-registered before any outcome was looked at:
  display  the badge predicts its own trait: at each team-season's midpoint, the shrunk value before that game against
           the raw rate over the rest of the season; r >= .15 with t >= 2 in the tune AND the held seasons. Only these
           badges are shown.
  ratings  the badge as a rating term: x = z(home) - z(away) in the good direction, residual vs the close (margin;
           NHL win, soccer home minus away), as style_research.score: tune t >= 1.5, held b > 0, held-out squared
           error of close + b x below the close at paired t <= -1.5, and BH q <= .10 over the whole family. A badge
           that passes would go into its sport's game model (then --fit and --rules). Badges already scored as main
           effects elsewhere (penalties: penalty_research.py) are display-tested only.

    python3 scripts/team_badges.py research [sport ...]   # -> data/team_badges_research.json (+ tier cuts)
    python3 scripts/team_badges.py build <sport>          # this season's badges into static/data/teams/<sport>.json
Data: scripts/team_badges_pull.py (CBB Barttorvik, NFL nflverse, CFB ESPN boxes) and the repo histories (NBA ESPN box
from the project files, NHL MoneyPuck nhl_games_hist, soccer soccer_games_hist).
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

C = SR.C
OUT = os.path.join(ROOT, 'data', 'team_badges_research.json')
CUTS = os.path.join(ROOT, 'data', 'team_badges.json')
TIERS = [(99, 'p'), (97, 'g'), (90, 's'), (75, 'b')]
MIN_GAMES = {'nba': 8, 'cbb': 6, 'nfl': 3, 'cfb': 3, 'nhl': 10, 'soccer': 5}

# sport -> [(key, name, orientation +1 higher is better / -1 lower, rating-tested, what it is)]
BADGES = {
    'nba': [('efg', 'Shot Makers', 1, 1, 'effective FG%'), ('3p', 'Sharpshooters', 1, 1, '3P%'),
            ('orb', 'Glass Cleaners', 1, 1, 'offensive rebound %'), ('drb', 'Board Control', -1, 1, 'opponent offensive rebound %'),
            ('tov', 'Ball Security', -1, 1, 'turnovers a possession'), ('tovf', 'Ball Hawks', 1, 1, 'turnovers forced a possession'),
            ('ftr', 'Foul Line', 1, 1, 'FTA a FGA'), ('ft', 'Free Throw Shooting', 1, 1, 'FT%'),
            ('rim', 'Rim Protection', 1, 1, 'blocks an opponent 2PA'), ('ast', 'Ball Movement', 1, 1, 'assists a FG made'),
            ('3pd', 'Perimeter D', -1, 1, 'opponent 3P%'), ('2pd', 'Interior D', -1, 1, 'opponent 2P%'),
            ('bench', 'Deep Bench', 1, 1, 'bench plus-minus a 48 minutes')],
    'nfl': [('pass_o', 'Air Attack', 1, 1, 'EPA a dropback'), ('run_o', 'Ground Game', 1, 1, 'EPA a carry'),
            ('pass_d', 'Pass Defense', -1, 1, 'EPA a dropback allowed'), ('run_d', 'Run Wall', -1, 1, 'EPA a carry allowed'),
            ('rush', 'Pass Rush', 1, 1, 'sack rate'), ('prot', 'Pass Protection', -1, 1, 'sack rate allowed'),
            ('secure', 'Ball Security', -1, 1, 'giveaways a play'), ('take', 'Takeaways', 1, 1, 'takeaways an opponent play'),
            ('expl', 'Explosive Plays', 1, 1, '20+ yard plays a play'), ('kick', 'Kicking', 1, 1, 'FG%'),
            ('ret', 'Return Game', 1, 1, 'yards a kick or punt return')],
    'cfb': [('pass_o', 'Air Attack', 1, 1, 'net yards a pass'), ('run_o', 'Ground Game', 1, 1, 'yards a carry'),
            ('pass_d', 'Pass Defense', -1, 1, 'net yards a pass allowed'), ('run_d', 'Run Wall', -1, 1, 'yards a carry allowed'),
            ('3d', 'Third Down Offense', 1, 1, '3rd-down conversion %'), ('3d_al', 'Third Down Defense', -1, 1, '3rd-down % allowed'),
            ('rush', 'Pass Rush', 1, 1, 'sacks an opponent pass'), ('havoc', 'Havoc', 1, 1, 'tackles for loss an opponent play'),
            ('secure', 'Ball Security', -1, 1, 'giveaways a play'), ('take', 'Takeaways', 1, 1, 'takeaways an opponent play'),
            ('kick', 'Kicking', 1, 1, 'FG%'), ('ret', 'Return Game', 1, 1, 'yards a kick or punt return'),
            ('disc', 'Discipline', -1, 0, 'penalty yards a play')],
    'nhl': [('x5f', 'Play Drivers', 1, 1, '5v5 xG for a game'), ('x5a', 'Shot Suppression', -1, 1, '5v5 xG against a game'),
            ('pp', 'Power Play', 1, 1, 'power-play xG a 60 minutes'), ('pk', 'Penalty Kill', -1, 1, 'penalty-kill xG against a 60 minutes'),
            ('fin', 'Finishers', 1, 1, 'goals over xG a game'), ('gk', 'Goaltending', 1, 1, 'saves over expected a game'),
            ('drawn', 'Draws Penalties', 1, 0, 'PP minutes a game'), ('disc', 'Discipline', -1, 0, 'PK minutes a game')],
    'soccer': [('sot', 'Shot Volume', 1, 1, 'shots on target a match'), ('sot_al', 'Shot Suppression', -1, 1, 'shots on target allowed a match'),
               ('fin', 'Finishing', 1, 1, 'goals a shot on target'), ('keep', 'Shot Stopping', 1, 1, 'saves a shot on target faced')],
}
BADGES['cbb'] = [b for b in BADGES['nba'] if b[0] != 'bench']
N0_FLOOR = PR.N0_FLOOR


# ---------------------------------------------------------------- events: per game, each side's {stat: (num, den)}
def bb_side(me, op, P):
    two = lambda f: (f['fgm'] - f['fg3m'], f['fga'] - f['fg3a'])
    return {'efg': (me['fgm'] + 0.5 * me['fg3m'], me['fga']), '3p': (me['fg3m'], me['fg3a']),
            'orb': (me['orb'], me['orb'] + op['drb']), 'drb': (op['orb'], op['orb'] + me['drb']),
            'tov': (me['tov'], P), 'tovf': (op['tov'], P), 'ftr': (me['fta'], me['fga']), 'ft': (me['ftm'], me['fta']),
            'rim': (me['blk'], two(op)[1]), 'ast': (me['ast'], me['fgm']), '3pd': (op['fg3m'], op['fg3a']), '2pd': two(op)}


def poss(f):
    return f['fga'] - f['orb'] + f['tov'] + 0.44 * f['fta']


def nba_team(lines):
    s = np.zeros(len(SR.NBA_COLS))
    for ln in lines:
        s += np.array(ln[1:], float)
    d = dict(zip(SR.NBA_COLS, s))
    f = {'fgm': d['fgm'], 'fga': d['fga'], 'fg3m': d['fg3m'], 'fg3a': d['fg3a'], 'ftm': d['ftm'], 'fta': d['fta'], 'orb': d['oreb'],
         'drb': d['dreb'], 'ast': d['ast'], 'stl': d['stl'], 'blk': d['blk'], 'tov': d['tov']}
    mi, pm = SR.NBA_COLS.index('min') + 1, SR.NBA_COLS.index('pm') + 1
    bench = sorted(lines, key=lambda l: -float(l[mi]))[5:]
    f['bpm'], f['bmin'] = sum(float(l[pm]) for l in bench), sum(float(l[mi]) for l in bench)
    return f


def ev_nba(box=None, hist=None):
    box = box if box is not None else json.load(gzip.open(os.path.join(C, 'nba_box_hist.json.gz')))
    hist = hist if hist is not None else {str(g['id']): g for g in json.load(gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz')))['games']}
    ev = []
    for gid, tm in box.items():
        g = hist.get(gid)
        if not g or g['h'] not in tm or g['a'] not in tm:
            continue
        f = {s: nba_team(tm[g[s]]) for s in ('h', 'a')}
        if f['h']['fga'] < 50 or f['a']['fga'] < 50:
            continue
        P = 0.5 * (poss(f['h']) + poss(f['a']))
        sd = {}
        for s, o in (('h', 'a'), ('a', 'h')):
            sd[s] = bb_side(f[s], f[o], P)
            if f[s]['bmin'] > 0:
                sd[s]['bench'] = (f[s]['bpm'], f[s]['bmin'] / 48)
        ev.append(dict(t=SR.when(g['tip']), S=g['S'], h=g['h'], a=g['a'], gid=gid, sh=sd['h'], sa=sd['a']))
    return ev


def ev_cbb(years=None):
    """Barttorvik box list: date, min, t1, t2, then 15 a side: fgm fga 3pm 3pa ftm fta orb drb trb ast stl blk tov pf pts"""
    import ast as A
    import csv
    ev, idx, seen = [], collections.defaultdict(list), set()
    for y in years or range(2015, 2028):
        p = os.path.join(C, f'cbb_gs{y}.csv')
        if not os.path.exists(p):
            continue
        for r in csv.reader(open(p, encoding='utf-8', errors='replace')):
            if len(r) < 30:
                continue
            try:
                b = A.literal_eval(r[29])
            except (ValueError, SyntaxError):
                continue
            m = f'{y}:{r[24]}'
            if m in seen:
                continue
            seen.add(m)
            mo, dd, yy = b[0].split('/')
            d = datetime.datetime(int(yy) + (2000 if len(yy) == 2 else 0), int(mo), int(dd))
            try:
                v1, v2 = [float(v) for v in b[4:19]], [float(v) for v in b[19:34]]
            except (TypeError, ValueError):
                continue
            if v1[1] < 30 or v2[1] < 30:
                continue
            F = lambda v: {'fgm': v[0], 'fga': v[1], 'fg3m': v[2], 'fg3a': v[3], 'ftm': v[4], 'fta': v[5], 'orb': v[6], 'drb': v[7],
                           'ast': v[9], 'stl': v[10], 'blk': v[11], 'tov': v[12]}
            f1, f2 = F(v1), F(v2)
            P = 0.5 * (poss(f1) + poss(f2))
            ev.append(dict(t=d, S=y, h=b[2], a=b[3], gid=m, sh=bb_side(f1, f2, P), sa=bb_side(f2, f1, P)))
            idx[(d.date(), tuple(sorted((v1[14], v2[14]))))].append((m, v1[14], v2[14]))
    return ev, idx


def ev_nfl(years=None):
    import csv
    tg = collections.defaultdict(dict)
    for y in years or range(2014, 2027):
        p = os.path.join(C, f'nfl_team{y}.csv')
        if os.path.exists(p):
            for r in csv.DictReader(open(p)):
                tg[r['game_id']][r['team']] = r
    F = lambda r, k: float(r.get(k) or 0)
    sched = {r['id']: r for r in json.load(gzip.open(SR.WF.format('nfl')))}
    giv = lambda r: F(r, 'passing_interceptions') + F(r, 'sack_fumbles_lost') + F(r, 'rushing_fumbles_lost') + F(r, 'receiving_fumbles_lost')
    ev = []
    for gid, tm in tg.items():
        y, wk, aw, hm = gid.split('_')
        if hm not in tm or aw not in tm:
            continue
        r0 = sched.get(gid)
        dt = SR.when(r0['date']) if r0 else datetime.datetime(int(y), 9, 1) + datetime.timedelta(days=7 * int(wk))
        sides = []
        for me, op in ((tm[hm], tm[aw]), (tm[aw], tm[hm])):
            db, ca = F(me, 'attempts') + F(me, 'sacks_suffered'), F(me, 'carries')
            odb, oca = F(op, 'attempts') + F(op, 'sacks_suffered'), F(op, 'carries')
            rn = F(me, 'punt_returns') + F(me, 'kickoff_returns')
            sides.append({'pass_o': (F(me, 'passing_epa'), db), 'run_o': (F(me, 'rushing_epa'), ca),
                          'pass_d': (F(op, 'passing_epa'), odb), 'run_d': (F(op, 'rushing_epa'), oca),
                          'rush': (F(op, 'sacks_suffered'), odb), 'prot': (F(me, 'sacks_suffered'), db),
                          'secure': (giv(me), db + ca), 'take': (giv(op), odb + oca),
                          'expl': (F(me, 'passing_20') + F(me, 'rushing_20'), db + ca), 'kick': (F(me, 'fg_made'), F(me, 'fg_att')),
                          'ret': (F(me, 'punt_return_yards') + F(me, 'kickoff_return_yards'), rn)})
        ev.append(dict(t=dt, S=int(y) + 1, h=hm, a=aw, gid=gid, sh=sides[0], sa=sides[1]))
    return ev


def cfb_sides(b):
    num = lambda s: float(str(s).replace(',', '') or 0) if s not in (None, '', '--') else 0.0
    ma = lambda s: SR.made_att(str(s).replace('/', '-')) if s else None
    sides = []
    for me, op in ((b['home'], b['away']), (b['away'], b['home'])):
        pa, oa = (num(x.get('completionAttempts', '0/0').split('/')[1]) for x in (me, op))
        ra, ora = num(me.get('rushingAttempts')), num(op.get('rushingAttempts'))
        s = {'pass_o': (num(me.get('netPassingYards')), pa), 'run_o': (num(me.get('rushingYards')), ra),
             'pass_d': (num(op.get('netPassingYards')), oa), 'run_d': (num(op.get('rushingYards')), ora),
             'rush': (num(me.get('defensive.SACKS')), oa), 'havoc': (num(me.get('defensive.TFL')), oa + ora),
             'secure': (num(me.get('turnovers')), pa + ra), 'take': (num(op.get('turnovers')), oa + ora),
             'ret': (num(me.get('kickReturns.YDS')) + num(me.get('puntReturns.YDS')), num(me.get('kickReturns.NO')) + num(me.get('puntReturns.NO')))}
        try:
            s['disc'] = (num(me['totalPenaltiesYards'].split('-')[1]), pa + ra + oa + ora)
        except (KeyError, IndexError):
            pass
        for k, v in (('3d', SR.made_att(me.get('thirdDownEff'))), ('3d_al', SR.made_att(op.get('thirdDownEff'))), ('kick', ma(me.get('kicking.FG')))):
            if v:
                s[k] = v
        if 'defensive.SACKS' not in me:
            s.pop('rush'), s.pop('havoc')
        sides.append(s)
    return sides, min(pa + ra, oa + ora)


def ev_cfb(box=None, wf=None):
    box = box if box is not None else json.load(open(os.path.join(C, 'cfb_box.json')))
    wf = wf if wf is not None else json.load(gzip.open(SR.WF.format('cfb')))
    ev = []
    for r in wf:
        b = box.get(str(r['id']))
        if not b or 'home' not in b or 'away' not in b:
            continue
        try:
            sides, n = cfb_sides(b)
        except (ValueError, IndexError, AttributeError):
            continue
        if n < 30:
            continue
        ev.append(dict(t=SR.when(r['date']), S=r['S'], h=r['home'], a=r['away'], gid=str(r['id']), sh=sides[0], sa=sides[1]))
    return ev


def nhl_sides(x):
    # x: [sva xGF, xGF, GF, 5v5 xGF, 5v5 xGA, PP xGF, PK xGA, PP min, PK min]
    out = []
    for me, op in ((x['h'], x['a']), (x['a'], x['h'])):
        out.append({'x5f': (me[3], 1.0), 'x5a': (me[4], 1.0), 'pp': (me[5], me[7]), 'pk': (me[6], me[8]),
                    'fin': (me[2] - me[1], 1.0), 'gk': (op[1] - op[2], 1.0), 'drawn': (me[7], 1.0), 'disc': (me[8], 1.0)})
    return out


def ev_nhl(games=None):
    ev = []
    for g in games if games is not None else json.load(gzip.open(os.path.join(HERE, 'nhl_games_hist.json.gz'))):
        x = g.get('x')
        if not x or g.get('hs') is None:
            continue
        sh, sa = nhl_sides(x)
        ev.append(dict(t=SR.when(g['day']), S=g['S'], h=g['h'], a=g['a'], gid=str(g['id']), sh=sh, sa=sa))
    return ev


def soccer_sides(hs, as_, hst, ast):
    return ({'sot': (hst, 1.0), 'sot_al': (ast, 1.0), 'fin': (hs, hst), 'keep': (ast - as_, ast)},
            {'sot': (ast, 1.0), 'sot_al': (hst, 1.0), 'fin': (as_, ast), 'keep': (hst - hs, hst)})


def ev_soccer():
    hist = {r['id']: r for r in json.load(gzip.open(os.path.join(HERE, 'soccer_games_hist.json.gz')))}
    ev = []
    for r in json.load(gzip.open(SR.WF.format('soccer'))):
        g = hist.get(r['id']) or {}
        sh = sa = None
        if g.get('hst') is not None and g.get('ast') is not None:
            sh, sa = soccer_sides(r['hs'], r['as'], g['hst'], g['ast'])
        ev.append(dict(t=SR.when(r['day']), S=r['S'], h=r['h'], a=r['a'], gid=r['id'], sh=sh, sa=sa))
    return ev


# ---------------------------------------------------------------- tests
def own_trait(ev, pre, stats, held0):
    """midpoint shrunk value vs the rest of the season's raw rate, per team-season with 8+ games"""
    g = collections.defaultdict(list)
    for e in ev:
        for s, k in (('h', 'sh'), ('a', 'sa')):
            if e.get(k):
                g[(e['S'], e[s])].append((e['gid'], s, e[k]))
    out = {}
    for st in stats:
        part = {'tune': ([], []), 'held': ([], [])}
        for (S, _), gs in g.items():
            gs = [x for x in gs if st in x[2] and x[2][st][1] > 0]
            if len(gs) < 8:
                continue
            k = len(gs) // 2
            v = pre.get(gs[k][0], {}).get(gs[k][1], {}).get(st)
            n, d = sum(x[2][st][0] for x in gs[k:]), sum(x[2][st][1] for x in gs[k:])
            if v is None or d <= 0:
                continue
            p = part['held' if S >= held0 else 'tune']
            p[0].append(v)
            p[1].append(n / d)
        o = {}
        for nm, (a, b) in part.items():
            if len(a) < 20:
                o[nm] = None
                continue
            r = float(np.corrcoef(a, b)[0, 1])
            o[nm] = [round(r, 3), round(r * math.sqrt((len(a) - 2) / max(1e-9, 1 - r * r)), 2), len(a)]
        o['pass'] = bool(all(o[nm] and o[nm][0] >= .15 and o[nm][1] >= 2 for nm in ('tune', 'held')))
        out[st] = o
    return out


def season_end(ev, pre_fn, stats):
    """each team-season's last pre-game value (z within season, oriented later) -> {(S, team): {stat: value}}"""
    last = {}
    for e in ev:
        for s in ('h', 'a'):
            last[(e['S'], e[s])] = e['gid'], s
    return {k: {st: pre_fn(gid, s, st) for st in stats} for k, (gid, s) in last.items()}


def cuts_from(vals, orient):
    """pooled within-season z percentiles (good direction) -> tier cut z's, plus each season's mean/sd"""
    by = collections.defaultdict(list)
    for (S, _), v in vals.items():
        if v is not None:
            by[S].append(v)
    zs = []
    for S, xs in by.items():
        if len(xs) < 10:
            continue
        m, s = float(np.mean(xs)), float(np.std(xs)) or 1.0
        zs += [orient * (x - m) / s for x in xs]
    out = {t: round(float(np.percentile(zs, p)), 3) for p, t in TIERS}
    out['q'] = [round(float(np.percentile(zs, p)), 3) for p in range(1, 100)]    # z at each percentile, for the display
    return out


def research(sp):
    idx = None
    if sp == 'cbb':
        ev, idx = ev_cbb()
    else:
        ev = {'nba': ev_nba, 'nfl': ev_nfl, 'cfb': ev_cfb, 'nhl': ev_nhl, 'soccer': ev_soccer}[sp]()
    ev.sort(key=lambda e: e['t'])
    B = BADGES[sp]
    stats = [b[0] for b in B]
    rel = PR.reliability(ev, stats)
    n0 = {st: max(N0_FLOOR[sp], min(round(rel[st]['n50']), 40)) if st in rel else N0_FLOOR[sp] for st in stats}
    pre = {}
    for v in sorted(set(n0.values())):     # one roll per distinct n0
        ss = [st for st in stats if n0[st] == v]
        p = SR.run_roll(ev, v, ss)
        for gid, d in p.items():
            q = pre.setdefault(gid, {'h': {}, 'a': {}})
            for s in ('h', 'a'):
                q[s].update(d[s])
    held0 = min(y for y in range(1990, 2100) if y not in SR.TUNE[sp] and y > min(SR.TUNE[sp]))
    own = own_trait(ev, pre, stats, held0)
    end = season_end(ev, lambda gid, s, st: pre[gid][s].get(st), stats)
    cuts = {b[0]: cuts_from({k: v[b[0]] for k, v in end.items()}, b[2]) for b in B}
    rows = PR.cbb_rows(pre, idx) if sp == 'cbb' else PR.rows_from_wf(sp, pre)
    SR.zs(rows, stats)
    rating = {}
    for k, nm, ori, tested, _ in B:
        if not tested:
            continue
        x = PR.mterm(rows, lambda z, k=k, ori=ori: ori * z[k] if z.get(k) is not None else None)
        rating[k] = SR.score(rows, x, False, SR.TUNE[sp], 1)
    for k, nm, ori, tested, _ in B:
        o = rating.get(k)
        print(f"{sp:7}{nm:22} rel {rel.get(k, {}).get('season_r')} n0 {n0[k]:3}  own {own[k]}  " +
              (f"tune {o['tune']} held {o['held']} seHeld {o['seHeld']} model {o.get('model')}" if o else 'rating: tested before'), flush=True)
    return {'n0': n0, 'reliability': rel, 'own': own, 'cuts': cuts, 'rating': rating, 'held_from': held0,
            'names': {b[0]: [b[1], b[2], b[4]] for b in B}}


def main_research(only):
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
    for sp in res:
        res[sp]['shown'] = [k for k in res[sp]['own'] if res[sp]['own'][k]['pass']]
        res[sp]['in_rating'] = [k for k in res[sp]['rating'] if res[sp]['rating'][k].get('pass')]
        print(sp, 'shown', res[sp]['shown'], 'rating pass', res[sp]['in_rating'],
              'best q', min([o.get('q', 1) for o in res[sp]['rating'].values()] or [1]))
    json.dump({'asof': datetime.date.today().isoformat(), 'tests': len(tests), 'sports': res}, open(OUT, 'w'), indent=1)
    cuts = {sp: {'n0': res[sp]['n0'], 'cuts': {k: res[sp]['cuts'][k] for k in res[sp]['shown']},
                 'names': {k: res[sp]['names'][k] for k in res[sp]['shown']}} for sp in res}
    json.dump({'asof': datetime.date.today().isoformat(), 'sports': cuts}, open(CUTS, 'w'), indent=1)


if __name__ == '__main__':
    if sys.argv[1:2] == ['research']:
        main_research(sys.argv[2:] or ['nba', 'cbb', 'nfl', 'cfb', 'nhl', 'soccer'])
    elif sys.argv[1:2] == ['build']:
        import team_badges_build as TB
        TB.build(sys.argv[2])
