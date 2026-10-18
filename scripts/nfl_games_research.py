#!/usr/bin/env python3
"""Candidate inputs for the NFL game model, tested the way the college model's were (scripts/cfb_model.mjs CAND).

    python3 scripts/nfl_games_research.py      # writes data/nfl_games_research.json (numpy; ~3 min with a warm cache)

Each candidate is a team rating built from nflverse play-by-play the same way nfl_games.py builds its EPA rating:
exponentially weighted by game (the live half-life and summer carry), opponent-adjusted (offense against the defense
it faced and the reverse), home minus away of offense minus defense allowed. Coach traits rate the offense only.
A candidate is added to the live model's inputs and the same walk-forward refit is scored (train on every season
before, score the season): margin MAE on 2015-20 picks, 2021-25 stays held out, both paired per game (t). Totals
candidates are scored the same way on totals. Forward selection keeps an input only if it gains on 2015-20 at
t <= -1.5 and the held-out 2021-25 agrees (t < 0); nothing else ships.
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N
import nfl_pbp as P

OUT = os.path.join(N.ROOT, 'data', 'nfl_games_research.json')

# ratio stats: (numerator, denominator) on the offense's row; the defense side is the same stat allowed
RATIO = {
    'sr':    ('s', 'n', 'success rate'),
    'srg':   ('sg', 'ng', 'success rate, win prob 10-90%'),
    'epag':  ('eg', 'ng', 'EPA a play, win prob 10-90% (no garbage time)'),
    'ed':    ('eds', 'edn', 'early-down success rate'),
    'ede':   ('ede', 'edn', 'early-down EPA a play'),
    'dbe':   ('dpe', 'dpn', 'EPA a dropback'),
    'td':    ('tdc', 'tdn', '3rd-down conversion rate'),
    'rzsr':  ('rzs', 'rzn', 'red-zone success rate'),
    'rz':    ('rzp', 'rzt', 'red-zone points a trip'),
    'xpl':   ('xpe', 's', 'explosiveness (EPA a successful play)'),
    'big':   ('big', 'n', '20+ yard play rate'),
    'stuff': ('stuff', 'run', 'stuff rate (runs for no gain or a loss)'),
    'line':  ('lyd', 'run', 'line yards a carry'),
    'fp':    ('fps', 'drv', 'starting field position (yards to goal)'),
    'cpoe':  ('cps', 'cpn', 'completion % over expected'),
}
# the offense's own choices and special teams: offense side only, not opponent-adjusted
OWN = {
    'aggr':  (lambda A: A['f4go'] - A['f4x'], lambda A: A['f4n'], "4th-down aggressiveness (go rate over expected)"),
    'proe':  (lambda A: A['pes'], lambda A: A['pen'], 'pass rate over expected (early downs, win prob 10-90%)'),
    'st':    (lambda A: A['stk'] + A['str'], lambda A: 1.0, 'special teams EPA a game (kicking + returns/coverage)'),
    'stk':   (lambda A: A['stk'], lambda A: 1.0, 'kicking EPA a game (field goals, extra points)'),
    'str':   (lambda A: A['str'], lambda A: 1.0, 'kickoff and punt EPA a game (both ways)'),
}


class Rater:
    """Weighted ratio of sums for one stat, offense and defense allowed, opponent-adjusted."""
    def __init__(self, num, den, a, carry, adjust=True):
        self.num, self.den, self.a, self.carry, self.adjust = num, den, a, carry, adjust
        self.o = defaultdict(lambda: [0.0, 0.0]); self.d = defaultdict(lambda: [0.0, 0.0])
        self.lg = [0.0, 0.0]; self.games = 0.0

    def L(self):
        return self.lg[0] / self.lg[1] if self.lg[1] else 0.0

    def r(self, side, t):
        v, w = side[t]
        w0 = 2 * self.lg[1] / self.games if self.games else 1.0       # two average games of prior at the league rate
        return (v + self.L() * w0) / (w + w0)

    def new_season(self):
        for side in (self.o, self.d):
            for t in side:
                side[t][0] *= self.carry; side[t][1] *= self.carry

    def update(self, t, o, A, B):
        """t's offense row A, its opponent o's offense row B (what t allowed)."""
        L = self.L()
        ro, rd = self.r(self.d, o), self.r(self.o, o)      # opponent's ratings before the game
        for side, row, adj in ((self.o, A, ro), (self.d, B, rd)):
            n, d = self.num(row), self.den(row)
            if d <= 0:
                continue
            x = n / d - ((adj - L) if self.adjust else 0.0)
            side[t][0] = side[t][0] * self.a + x * d; side[t][1] = side[t][1] * self.a + d

    def league(self, A):
        n, d = self.num(A), self.den(A)
        if d > 0:
            self.lg[0] = self.lg[0] * 0.999 + n; self.lg[1] = self.lg[1] * 0.999 + d
            self.games = self.games * 0.999 + 1

    def net(self, t):
        return self.r(self.o, t) - (self.r(self.d, t) if self.adjust else 0.0)

    def both(self, t):
        return self.r(self.o, t) + self.r(self.d, t) - 2 * self.L()


def candidates(games, TG, params):
    """game_id -> {candidate: home minus away}, and totals candidates, every value known before kickoff."""
    a = 0.5 ** (1 / params['hl']); carry = params['carry']
    R = {k: Rater(lambda A, n=n: A[n], lambda A, d=d: A[d], a, carry) for k, (n, d, _) in RATIO.items()}
    R.update({k: Rater(n, d, a, carry, adjust=False) for k, (n, d, _) in OWN.items()})
    R['pace'] = Rater(lambda A: A['n'], lambda A: 1.0, a, carry, adjust=False)
    fast = Rater(lambda A: A['e'], lambda A: A['n'], 0.5 ** (1 / 3), 0.0)          # recent form, half-life 3 games
    slow = Rater(lambda A: A['e'], lambda A: A['n'], a, carry)
    coach = defaultdict(lambda: [0.0, 0])          # coach -> sum of (result - line) from his side, games
    first = {}                                     # (coach, team) -> first season together
    out, tout = {}, {}
    season = None
    for g in games:
        s = int(g['season'])
        if s != season:
            for r in list(R.values()) + [fast, slow]:
                r.new_season()
            season = s
        h, aw = N.team(g['home_team']), N.team(g['away_team'])
        x = {k: r.net(h) - r.net(aw) for k, r in R.items() if k != 'pace'}
        x['form'] = (fast.net(h) - slow.net(h)) - (fast.net(aw) - slow.net(aw))
        cv = lambda c: coach[c][0] / (coach[c][1] + 100)
        x['cats'] = cv(g['home_coach']) - cv(g['away_coach'])
        nw = lambda c, t: 1.0 if first.setdefault((c, t), s) == s else 0.0
        x['newc'] = nw(g['home_coach'], h) - nw(g['away_coach'], aw)
        wind = N.num(g.get('wind'), 0.0) if g['roof'] in ('outdoors', 'open') else 0.0
        x['wind'] = max(0.0, wind - 10) / 10
        out[g['game_id']] = x
        tout[g['game_id']] = {'pace': R['pace'].both(h) + R['pace'].both(aw), 'srT': R['sr'].both(h) + R['sr'].both(aw),
                              'xplT': R['xpl'].both(h) + R['xpl'].both(aw), 'rzT': R['rz'].both(h) + R['rz'].both(aw),
                              'proeT': R['proe'].r(R['proe'].o, h) + R['proe'].r(R['proe'].o, aw),
                              'fpT': R['fp'].both(h) + R['fp'].both(aw), 'bigT': R['big'].both(h) + R['big'].both(aw)}
        if g['home_score'] in ('', 'NA'):
            continue
        A, B = TG.get((g['game_id'], h)), TG.get((g['game_id'], aw))
        if A and B:
            for r in list(R.values()) + [fast, slow]:
                r.league(A); r.league(B)
                r.update(h, aw, A, B); r.update(aw, h, B, A)
        line = N.num(g['spread_line'], None)
        if line is not None:
            m = N.num(g['result'])
            coach[g['home_coach']][0] += m - line; coach[g['home_coach']][1] += 1
            coach[g['away_coach']][0] += line - m; coach[g['away_coach']][1] += 1
    return out, tout


def roster_war(games):
    """game_id -> (home, away): last season's WAR (nfl_war.py) of the players on the team's active roster that week.
    Carries offseason moves, trades and IR the ratings haven't seen yet. WAR starts in 2016, so 2017 on."""
    import nfl_war as W
    out = {}
    for y in range(2017, 2026):
        prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
        ros = defaultdict(float)
        for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv')):
            if r['status'] in ('ACT', 'INA') and r['gsis_id']:
                ros[(N.team(r['team']), int(r['week']))] += prev.get(r['gsis_id'], (0.0, 0))[0]
        for g in games:
            if int(g['season']) == y:
                w = int(g['week'])
                out[g['game_id']] = (ros.get((N.team(g['home_team']), w), 0.0), ros.get((N.team(g['away_team']), w), 0.0))
        print('roster war', y, flush=True)
    return out


def qb_cpoe(games, last):
    """game_id -> starting QB CPOE features: the starter's career CPOE (recent seasons weighted, shrunk 150
    attempts toward a backup's -3) home minus away, and the same over the team's recent QB CPOE."""
    import csv
    per = defaultdict(lambda: [0.0, 0.0])
    for y in range(N.FIRST, last + 1):
        rd = csv.reader(gzip.open(P.RAW.format(y=y), 'rt'))
        h = next(rd); I = {k: i for i, k in enumerate(h)}
        for r in rd:
            c = r[I['cpoe']]
            if c not in ('', 'NA') and r[I['passer_player_id']] not in ('', 'NA'):
                q = per[(r[I['game_id']], r[I['passer_player_id']], N.team(r[I['posteam']]))]
                q[0] += float(c); q[1] += 1
    byg = defaultdict(list)
    for (gid, q, t), v in per.items():
        byg[gid].append((q, t, v))
    car = defaultdict(lambda: [0.0, 0.0]); tq = defaultdict(lambda: [0.0, 0.0]); a = 0.5 ** (1 / 12)
    val = lambda q: (car[q][0] - 3 * 150) / (car[q][1] + 150) if q else -3.0
    trate = lambda t: (tq[t][0] - 3 * 2) / (tq[t][1] + 2)
    out, season = {}, None
    for g in games:
        s = int(g['season'])
        if s != season:
            for v in car.values():
                v[0] *= 0.7; v[1] *= 0.7
            for v in tq.values():
                v[0] *= 0.7; v[1] *= 0.7
            season = s
        h, aw = N.team(g['home_team']), N.team(g['away_team'])
        hq, aq = g['home_qb_id'], g['away_qb_id']
        out[g['game_id']] = {'qbcLvl': val(hq) - val(aq), 'qbcAdj': (val(hq) - trate(h)) - (val(aq) - trate(aw))}
        for q, t, (cs, cn) in byg.get(g['game_id'], []):
            car[q][0] += cs; car[q][1] += cn
        for t in (h, aw):
            lst = [v for q, tt, v in byg.get(g['game_id'], []) if tt == t]
            n = sum(v[1] for v in lst)
            if n >= 10:
                tq[t][0] = tq[t][0] * a + sum(v[0] for v in lst) / n; tq[t][1] = tq[t][1] * a + 1
    return out


UNIT = {'T': 'ol', 'G': 'ol', 'C': 'ol', 'OL': 'ol', 'OT': 'ol', 'OG': 'ol', 'RB': 'sk', 'FB': 'sk', 'WR': 'sk', 'TE': 'sk',
        'DE': 'fr', 'DT': 'fr', 'NT': 'fr', 'DL': 'fr', 'LB': 'fr', 'OLB': 'fr', 'ILB': 'fr', 'MLB': 'fr',
        'CB': 'db', 'S': 'db', 'SS': 'db', 'FS': 'db', 'DB': 'db'}


def injury_units(games, years):
    """game_id -> {unit: away minus home cost}, the live injury cost (nfl_games.injury_history) split by unit, plus
    the count of linemen and of defensive backs with a cost of half a point or more (clusters)."""
    import nfl_war as W
    out = {}
    for y in years:
        maps = W.gsis_map(y)
        prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
        top = max([int(g['week']) for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')] + [1])
        led = {w: W.war_ledger(y, thru=w, maps=maps) for w in range(1, min(top + 1, 19) + 1)}
        rep = defaultdict(list)
        for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
            if r['report_status'] and r['position'] != 'QB':
                rep[(N.team(r['team']), int(r['week']))].append((r['gsis_id'], r['report_status'], UNIT.get(r['position'], 'x')))
        last_wk = {}
        for g in [g for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')]:
            w = int(g['week']); o = defaultdict(float)
            for side, sg in (('home', -1), ('away', 1)):
                t = N.team(g[f'{side}_team']); pw = last_wk.get(t)
                for gsis, stt, u in rep.get((t, w), []):
                    L = led[min(w, 19, top + 1)]
                    v = N.player_value(prev.get(gsis, (0.0, 0)), L.get(gsis, (0.0, 0)))
                    played = True if (pw is None or pw >= 18 or w > 18) else led[pw + 1].get(gsis, (0, 0))[1] > led[pw].get(gsis, (0, 0))[1]
                    c = (1 - N.play_prob(stt, played)) * max(v, 0.0) * N.PTS_PER_WIN
                    o['i_' + u] += sg * c
                    if u in ('ol', 'db') and c >= 0.5:
                        o['n_' + u] += sg
                last_wk[t] = w
            out[g['game_id']] = dict(o)
        print('injury units', y, flush=True)
    return out


def main():
    import numpy as np
    last = 2025
    F = json.load(open(N.FIT))
    params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    TG = {}
    for y in range(N.FIRST, last + 1):
        TG.update(P.season(y))
    _, data = N.walk(games, box, qbs, params)
    cand, tcand = candidates(games, TG, params)
    rw = roster_war(games)
    qc = qb_cpoe(games, last)
    iu = injury_units(games, range(N.INJ_FIRST, last + 1))
    gp = defaultdict(int); gpl = {}
    for g in games:
        h, aw = N.team(g['home_team']), N.team(g['away_team'])
        k = int(g['season'])
        gpl[g['game_id']] = (gp[(k, h)] + gp[(k, aw)]) / 2
        if g['home_score'] not in ('', 'NA'):
            gp[(k, h)] += 1; gp[(k, aw)] += 1
    D = []
    for g, x, tx in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        r = inj.get(g['game_id'])
        x = dict(x); x.update(cand[g['game_id']])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1]); x['injf'] = r[2] - r[0]; x['injc'] = r[3] - r[1]
        else:
            x['injf'] = x['injc'] = 0.0
        x['wxc'] = x['wind'] * x['elo']
        x['newcElo'] = (1.0 if x['newc'] else 0.0) * x['elo']
        rh, ra = rw.get(g['game_id'], (0.0, 0.0))
        x['retF'] = rh - ra; x['retE'] = (rh - ra) * 0.5 ** (gpl[g['game_id']] / 4)
        x.update(qc[g['game_id']])
        u = iu.get(g['game_id'], {})
        for k in ('i_ol', 'i_sk', 'i_fr', 'i_db', 'i_x', 'n_ol', 'n_db'):
            x[k] = u.get(k, 0.0)
        tx = dict(tx); tx.update(tcand[g['game_id']])
        D.append((g, x, tx))
    S = np.array([int(g['season']) for g, _, _ in D])
    y = np.array([N.num(g['result']) for g, _, _ in D]); ty = np.array([N.num(g['total']) for g, _, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _, _ in D])
    ok = ~np.isnan(line)
    A = (S >= 2015) & (S <= 2020) & ok; B = (S >= 2021) & ok

    def wf(feats, tot=False):
        X = np.array([[(tx if tot else x)[f] for f in feats] for _, x, tx in D]); yy = ty if tot else y
        pred = np.full(len(yy), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], yy[tr], rcond=None)[0]; pred[te] = X[te] @ b
        b = np.linalg.lstsq(X, yy, rcond=None)[0]
        return np.abs(pred - yy), pred, dict(zip(feats, b))

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)

    def ats(pred, k):
        e = pred[k] - line[k]; r = y[k] - line[k]; pick = (np.abs(e) >= 1) & (r != 0)
        return round(float((np.sign(e[pick]) == np.sign(r[pick])).mean()), 3)

    base = list(N.FEATS)
    e0, p0, _ = wf(base)
    res = {'base': {'feats': base, 'mae1520': round(float(e0[A].mean()), 3), 'mae2125': round(float(e0[B].mean()), 3),
                    'line1520': round(float(np.abs(line[A] - y[A]).mean()), 3), 'line2125': round(float(np.abs(line[B] - y[B]).mean()), 3),
                    'ats2125': ats(p0, B)}}
    names = {k: v[2] for k, v in RATIO.items()}
    names.update({k: v[2] for k, v in OWN.items()})
    names.update({'form': 'recent form (net EPA, last ~3 games over the rating)', 'cats': 'head coach career cover margin (shrunk 100 games)',
                  'newc': 'first-year head coach with the team', 'newcElo': 'first-year head coach x Elo gap',
                  'wxc': 'wind over 10 mph x Elo gap (margin squeeze)', 'injf': 'injuries, fresh (played last game) only',
                  'injc': 'injuries, continuing (also missed last game) only',
                  'retF': "last season's WAR of this week's active roster", 'retE': "roster WAR, fading as games are played (half-life 4)",
                  'qbcLvl': 'starting QB career CPOE (shrunk)', 'qbcAdj': "starting QB CPOE over the team's recent QB CPOE",
                  'n_ol': 'linemen out (cost .5+ pts), cluster count', 'n_db': 'defensive backs out (cost .5+ pts), cluster count'})
    pool = [k for k in names if k not in ('injf', 'injc')]
    alone = {}
    for k in pool:
        e1, p1, b = wf(base + [k])
        alone[k] = {'name': names[k], 'd1520': cmp(e1, e0, A), 'd2125': cmp(e1, e0, B), 'coef': round(float(b[k]), 4), 'ats2125': ats(p1, B)}
        print(k, alone[k], flush=True)
    # the injury split: fresh and continuing as two inputs in place of one
    e1, p1, b = wf([f for f in base if f != 'inj'] + ['injf', 'injc'])
    alone['injSplit'] = {'name': 'injuries split fresh / continuing', 'd1520': cmp(e1, e0, A), 'd2125': cmp(e1, e0, B),
                         'coef': {'injf': round(float(b['injf']), 3), 'injc': round(float(b['injc']), 3)}}
    print('injSplit', alone['injSplit'])
    units = ['i_ol', 'i_sk', 'i_fr', 'i_db', 'i_x']
    e1, p1, b = wf([f for f in base if f != 'inj'] + units)
    alone['injUnits'] = {'name': 'injuries by unit (OL, skill, front, DB, other) in place of one term', 'd1520': cmp(e1, e0, A),
                         'd2125': cmp(e1, e0, B), 'coef': {k: round(float(b[k]), 3) for k in units}}
    print('injUnits', alone['injUnits'], flush=True)
    # a draft-capital prior for QBs without much NFL history (top-12 picks a full step above a backup's -.12 EPA a
    # play, the rest of round 1 .6 of it, round 2 .25), in place of the one replacement-level prior for everyone
    import csv
    pick = {r['gsis_id']: int(r['pick']) for r in csv.DictReader(open(N.get('draft_picks.csv', f'{N.REL}/draft_picks/draft_picks.csv')))
            if r['position'] == 'QB' and r['gsis_id'] not in ('', 'NA')}
    ids = [g['game_id'] for g, _, _ in D]

    class Drafted(N.Model):
        bonus = 0.0
        def qbval(self, gsis):
            v, n = self.qb[gsis]; p_ = pick.get(gsis)
            pr = self.repl + (self.bonus * (1.0 if p_ <= 12 else 0.6 if p_ <= 32 else 0.25 if p_ <= 64 else 0.0) if p_ else 0.0)
            return (v + pr * self.n0) / (n + self.n0)
    alone['qbDraft'] = {'name': 'QB prior by draft slot (bonus over a backup, EPA a play)'}
    for bonus in (0.03, 0.06, 0.12):
        Drafted.bonus = bonus
        m = Drafted(**params); qx = {}
        for g in games:
            qx[g['game_id']] = m.feats(g)[0]['qb']; m.update(g, box, qbs)
        saved = [x['qb'] for _, x, _ in D]
        for (g, x, _), gid in zip(D, ids):
            x['qb'] = qx[gid]
        e1, _, _ = wf(base)
        for (g, x, _), v in zip(D, saved):
            x['qb'] = v
        alone['qbDraft'][str(bonus)] = {'d1520': cmp(e1, e0, A), 'd2125': cmp(e1, e0, B)}
    print('qbDraft', alone['qbDraft'], flush=True)
    # forward selection on 2015-20
    chosen, cur = [], e0
    steps = []
    while True:
        best = None
        for k in pool:
            if k in chosen:
                continue
            e1, _, _ = wf(base + chosen + [k])
            d, t = cmp(e1, cur, A)
            if t <= -1.5 and (best is None or d < best[1]):
                best = (k, d, t, e1)
        if not best:
            break
        k, d, t, e1 = best
        steps.append({'add': k, 'd1520': [round(d, 4), t], 'd2125': cmp(e1, cur, B)})
        print('step', steps[-1], flush=True)
        chosen.append(k); cur = e1
    # totals
    tbase = list(N.TFEATS)
    te0, _, _ = wf(tbase, tot=True)
    tline = np.array([N.num(g['total_line'], np.nan) for g, _, _ in D]); tok = ~np.isnan(tline)
    TA, TB = A & tok, B & tok
    talone = {}
    for k in ['pace', 'srT', 'xplT', 'rzT', 'proeT', 'fpT', 'bigT']:
        te1, _, b = wf(tbase + [k], tot=True)
        talone[k] = {'d1520': cmp(te1, te0, TA), 'd2125': cmp(te1, te0, TB), 'coef': round(float(b[k]), 4)}
        print('total', k, talone[k], flush=True)
    # win probability: normal around the margin with sd fit to margins (live), against sd fit to win/loss outcomes
    # (the college model's calibration fix), and sd growing with the projected total
    from math import erf, sqrt, log
    _, tpred, _ = wf(tbase, tot=True)
    win = np.where(y > 0, 1.0, np.where(y < 0, 0.0, 0.5))
    def ll(k, sdv):
        p = 0.5 * (1 + np.vectorize(erf)(p0[k] / (sdv[k] if np.ndim(sdv) else sdv) / sqrt(2)))
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return -(win[k] * np.log(p) + (1 - win[k]) * np.log(1 - p))
    sd0 = float(np.std((p0 - y)[A]))
    grid = [(float(ll(A, v).mean()), v) for v in np.arange(10.0, 16.01, 0.25)]
    sdw = min(grid)[1]
    kk = [(float(ll(A, c * np.sqrt(np.maximum(tpred, 20))).mean()), c) for c in np.arange(1.5, 2.6, 0.02)]
    ck = min(kk)[1]
    d1 = ll(B, sdw) - ll(B, F['sd']); d2 = ll(B, ck * np.sqrt(np.maximum(tpred, 20))) - ll(B, F['sd'])
    tstat = lambda d: round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)
    res['winProb'] = {'sdLive': F['sd'], 'sdMargins1520': round(sd0, 2), 'sdWinFit1520': round(float(sdw), 2),
                      'll2125Live': round(float(ll(B, F['sd']).mean()), 4), 'll2125WinFit': round(float(ll(B, sdw).mean()), 4), 'tWinFit': tstat(d1),
                      'sdPerSqrtTotal': round(float(ck), 3), 'll2125TotalScaled': round(float(ll(B, ck * np.sqrt(np.maximum(tpred, 20))).mean()), 4), 'tTotalScaled': tstat(d2)}
    print('winProb', res['winProb'], flush=True)
    res.update({'alone': alone, 'steps': steps, 'chosen': chosen, 'totals': {'base1520': round(float(te0[TA].mean()), 3),
                'base2125': round(float(te0[TB].mean()), 3), 'alone': talone}})
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
