#!/usr/bin/env python3
"""NHL game projections for the NHL ARKBOARD (data/nhl_games.json), and the model behind them (data/nhl_games_fit.json).

    python3 scripts/nhl_games.py           # today's and tomorrow's projections, power rankings, season odds (numpy)
    python3 scripts/nhl_games.py --hist    # freeze past seasons into scripts/nhl_games_hist.json.gz (from the caches)
    python3 scripts/nhl_games.py --fit     # tune, walk-forward backtest 2016-2026 against the closing line, refit
    python3 scripts/nhl_games.py --lineups # freeze past seasons' dressed skaters into scripts/data/nhl_lineups.json.gz

Data: the NHL's stats API (scores, last period, goalie and skater game logs), MoneyPuck (each team's expected goals a game, all
situations and by strength, score- and venue-adjusted), ESPN (every listed book's moneyline and total, 2019-20 on),
Daily Faceoff (tonight's starting goalies, confirmed or likely). Every input is known before puck drop, except that
the backtest uses the goalie who actually started (an upper bound: the close sometimes sets before the starter is
confirmed).

Goal margin (home minus away) and the home team's chance to win are linear in:
    elo     Elo difference (538's hockey Elo: margin multiplier, autocorrelation correction, K tuned, part of the way
            back to the mean each offseason)
    xg      expected-goal rating: each team's attack and defence in score- and venue-adjusted xG a game, fit jointly
            (exponentially weighted ridge: half-life in days tuned, carried into the next season at a fraction), so
            every opponent counts at its own strength
    g       the same rating on actual goals (finishing and goaltending the xG model doesn't see)
    mkt     market rating: each team's logit win chance against an average team as earlier closing moneylines priced
            it (never the game's own line), the same weighting
    gk      the starting goalies: goals saved above expected a game (MoneyPuck xG against his share of the game, minus
            goals allowed), shrunk toward a new goalie's level, carried across seasons at a fraction, home minus away
    rest    days of rest (0-3) home minus away, and back-to-backs
    rv      lineup value: the skaters each team dressed in its previous game this season, each at his projected
            impact (HPM from the NHL WAR run's previous season, scripts/nhl_players.py: data through last season only)
            times his usual ice time last season, newcomers at replacement; home minus away, 0 until both teams have
            played. A bottom-up roster rating beside the team-level ones, after HockeyStats.com's game model
            (TopDownHockey: player impacts summed over the lineup); 2012-26 skater logs frozen in
            scripts/data/nhl_lineups.json.gz
    home    1 at a home rink
Candidate inputs enter only when they lower walk-forward log loss on 2016-23 (clustered t <= -1.5) and 2024-26
doesn't disagree (see fit()). Win chance: logistic on the inputs. Total goals: both attacks against both defences on
xG and goals, the market total rating from earlier closing totals, and the two goalies, weighted by regression.
Puck line and overtime chances: logistic on the model margin and total, fit to results.
"""
import datetime as dt
import gzip
import json
import math
import os
import random
import re
import sys
import urllib.request
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nhl_data as D
import names as NM

ROOT = os.path.dirname(HERE)
HIST = os.path.join(HERE, 'nhl_games_hist.json.gz')      # outside data/: Hugo would load it on every build
FIT = os.path.join(ROOT, 'data', 'nhl_games_fit.json')
OUT = os.path.join(ROOT, 'data', 'nhl_games.json')
WF = os.path.join(HERE, 'data', 'games_wf', 'nhl.json.gz')
LINEUPS = os.path.join(HERE, 'data', 'nhl_lineups.json.gz')
WARD = os.path.join(ROOT, 'static', 'data', 'nhl-war')
FIRST = 2011                     # 2010-11: ratings warm up five seasons before scoring
SCORE_FROM, FIRST_TEST, TUNE, HOLD_FROM = 2016, 2021, (2021, 2023), 2024
TEAMS = sorted(D.TEAMS)
TI = {t: i for i, t in enumerate(TEAMS)}
NT = len(TEAMS)
DIV = {'Atlantic': ['BOS', 'BUF', 'DET', 'FLA', 'MTL', 'OTT', 'TBL', 'TOR'],
       'Metropolitan': ['CAR', 'CBJ', 'NJD', 'NYI', 'NYR', 'PHI', 'PIT', 'WSH'],
       'Central': ['CHI', 'COL', 'DAL', 'MIN', 'NSH', 'STL', 'UTA', 'WPG'],
       'Pacific': ['ANA', 'CGY', 'EDM', 'LAK', 'SEA', 'SJS', 'VAN', 'VGK']}
CONF = {'East': ['Atlantic', 'Metropolitan'], 'West': ['Central', 'Pacific']}
DIV_OF = {t: d for d, ts in DIV.items() for t in ts}
CONF_OF = {t: c for c, ds in CONF.items() for d in ds for t in DIV[d]}
FEATS = ['elo', 'xg', 'g', 'mkt', 'gk', 'rest', 'b2b', 'home']
CANDS = ['x5', 'st', 'rv']       # 5-on-5 xG rating; special teams (power-play xG for, penalty-kill xG against); lineup value
TFEATS = ['xgT', 'gT', 'mtot', 'gkT', 'one']
P0 = {'K': 6.0, 'reg': 0.3, 'hl': 60.0, 'car': 0.5, 'ghl': 45.0, 'gcar': 0.5, 'mhl': 40.0, 'mcar': 0.4,
      'gk_car': 0.6, 'gk_k': 25.0, 'gk_0': -0.1, 'pen': 4.0}


# ---------------------------------------------------------------- odds
def implied(ml):
    ml = float(ml)
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def american(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def consensus(rows, when='close'):
    """median no-vig home win chance and total across ESPN's books (live and lopsided rows dropped: a book's two
    moneylines must sum to a 0-10% hold)"""
    ps, ts, mh, ma = [], [], [], []
    for r in rows or []:
        if 'live' in (r.get('book') or '').lower():
            continue
        c = r.get(when) or {}
        h, a = c.get('mlH'), c.get('mlA')
        if when == 'close' and (h is None or a is None):
            h, a = r.get('mlH'), r.get('mlA')
        if h not in (None, 0) and a not in (None, 0):
            try:
                ih, ia = implied(h), implied(a)
            except (TypeError, ValueError):
                ih = ia = 0
            if 1.0 <= ih + ia <= 1.10:
                ps.append(ih / (ih + ia)); mh.append(float(h)); ma.append(float(a))
        t = c.get('total') if c.get('total') is not None or when != 'close' else r.get('total')
        if t is None and when == 'close':
            t = r.get('total')
        if t:
            try:
                t = float(t)
                if 3.5 <= t <= 9.5:
                    ts.append(t)
            except (TypeError, ValueError):
                pass
    p = median(ps)
    return {'p': None if p is None else round(p, 4), 't': median(ts),
            'ml': [median(mh), median(ma)] if mh else None} if (ps or ts) else None


# ---------------------------------------------------------------- history
def season_rows(S, mp, fresh=False, odds=True):
    """season S's games in start order with xG, goalie lines and the closing consensus"""
    gs = D.games(S, fresh=fresh)
    gl = defaultdict(lambda: defaultdict(list))
    for gid, pid, nm, t, st, toi, sa, ga in D.goalie_logs(S, fresh=fresh):
        gl[gid][t].append([pid, nm, st, toi, sa, ga])
    od = D.odds_for(gs, fresh=fresh) if odds and S >= 2020 else {}
    out = []
    for g in gs:
        r = {'id': g['id'], 'S': S, 'day': g['day'], 't': g['et'], 'po': int(g['type'] == 3), 'h': g['h'], 'a': g['a'],
             'hs': g['hs'], 'as': g['as'], 'per': g['per'], 'final': g['final']}
        x = mp.get(g['id'])
        if x and g['h'] in x and g['a'] in x:
            def line(t):
                s = x[t]
                al, e5, pp, pk = s.get('all', {}), s.get('5on5', {}), s.get('5on4', {}), s.get('4on5', {})
                return [round(al.get('scoreVenueAdjustedxGoalsFor', 0), 3), round(al.get('xGoalsFor', 0), 3),
                        al.get('goalsFor', 0), round(e5.get('xGoalsFor', 0), 3), round(e5.get('xGoalsAgainst', 0), 3),
                        round(pp.get('xGoalsFor', 0), 3), round(pk.get('xGoalsAgainst', 0), 3),
                        round(pp.get('iceTime', 0) / 60, 1), round(pk.get('iceTime', 0) / 60, 1)]
            r['x'] = {'h': line(g['h']), 'a': line(g['a'])}
        if g['id'] in gl:
            r['gl'] = {'h': gl[g['id']].get(g['h'], []), 'a': gl[g['id']].get(g['a'], [])}
        c = consensus(od.get(g['id']))
        if c:
            o = consensus(od.get(g['id']), 'open')
            r['c'] = c
            if o and o.get('p') is not None:
                r['o'] = o
        out.append(r)
    return out


def make_hist():
    mp = D.moneypuck_teams()
    last = D.current_season() - 1
    rows = []
    for S in range(FIRST, last + 1):
        rs = [r for r in season_rows(S, mp) if r['final']]
        print(S, len(rs), 'games', sum(1 for r in rs if 'x' in r), 'xG', sum(1 for r in rs if 'c' in r), 'lined', flush=True)
        rows += rs
    D.save(HIST, rows)
    print('wrote', HIST, len(rows))


def load_hist():
    return D.load(HIST)


# ---------------------------------------------------------------- rating engines
class EWR:
    """exponentially weighted ridge regression, updated one observation at a time (normal equations decayed)"""
    def __init__(self, k, pen):
        self.A = np.zeros((k, k)); self.b = np.zeros(k); self.P = np.diag(pen); self.th = np.zeros(k); self.dirty = False

    def decay(self, f):
        self.A *= f; self.b *= f; self.dirty = True

    def add(self, idx, val, y, w=1.0):
        v = np.zeros(len(self.b)); v[idx] = val
        self.A += w * np.outer(v, v); self.b += w * v * y; self.dirty = True

    def theta(self):
        if self.dirty:
            self.th = np.linalg.solve(self.A + self.P, self.b); self.dirty = False
        return self.th


class OD:
    """attack and defence in a per-game count (xG or goals): y(att) = mu + hfa x home + o[att] - d[def]"""
    def __init__(self, hl, carry, pen):
        self.hl, self.carry = hl, carry
        pens = [pen] * (2 * NT) + [0.05, 1e-3]
        self.e = EWR(2 * NT + 2, pens)
        self.HF, self.MU = 2 * NT, 2 * NT + 1

    def step(self, days):
        if days > 0:
            self.e.decay(0.5 ** (days / self.hl))

    def season(self):
        self.e.decay(self.carry)

    def add(self, h, a, yh, ya, home=1.0):
        i, j = TI[h], TI[a]
        self.e.add([i, NT + j, self.HF, self.MU], [1, -1, home, 1], yh)
        self.e.add([j, NT + i, self.MU], [1, -1, 1], ya)

    def strength(self, t):
        th = self.e.theta()
        return th[TI[t]] + th[NT + TI[t]]

    def parts(self, t):
        th = self.e.theta()
        return th[TI[t]], th[NT + TI[t]]

    def net(self, h, a):
        return self.strength(h) - self.strength(a)

    def total(self, h, a, home=1.0):
        th = self.e.theta()
        i, j = TI[h], TI[a]
        return 2 * th[self.MU] + home * th[self.HF] + th[i] - th[NT + j] + th[j] - th[NT + i]


class MKT:
    """market ratings from earlier closing lines: logit(no-vig home chance) = hfa + r[h] - r[a]; totals: t[h] + t[a] + mu"""
    def __init__(self, hl, carry, pen):
        self.hl, self.carry = hl, carry
        self.r = EWR(NT + 1, [pen] * NT + [0.05])
        self.t = EWR(NT + 1, [pen * 4] * NT + [1e-3])

    def step(self, days):
        if days > 0:
            f = 0.5 ** (days / self.hl); self.r.decay(f); self.t.decay(f)

    def season(self):
        self.r.decay(self.carry); self.t.decay(self.carry)

    def add(self, h, a, p, tot, home=1.0):
        i, j = TI[h], TI[a]
        if p is not None and 0.02 < p < 0.98:
            self.r.add([i, j, NT], [1, -1, home], math.log(p / (1 - p)))
        if tot:
            self.t.add([i, j, NT], [1, 1, 1], tot)

    def rating(self, t):
        return self.r.theta()[TI[t]]

    def total(self, h, a):
        th = self.t.theta()
        return th[TI[h]] + th[TI[a]] + th[NT] if self.t.A[NT, NT] > 0 else 0.0


class Elo:
    def __init__(self, K, reg):
        self.K, self.reg, self.r = K, reg, defaultdict(lambda: 1505.0)

    def season(self):
        for t in list(self.r):
            self.r[t] = 1505 + (1 - self.reg) * (self.r[t] - 1505)

    def add(self, h, a, hs, as_, home=1.0):
        d = self.r[h] + 50 * home - self.r[a]
        e = 1 / (1 + 10 ** (-d / 400))
        gd = abs(hs - as_)
        w = 1.0 if hs > as_ else 0.0
        mult = (0.6686 * math.log(gd) + 0.8048) if gd > 0 else 1.0
        dw = d if w else -d
        ac = 2.05 / (dw * 0.001 + 2.05)
        ch = self.K * mult * ac * (w - e)
        self.r[h] += ch; self.r[a] -= ch


class Goalies:
    """each goalie's goals saved above expected a game: xG against at his share of the game minus goals he allowed"""
    def __init__(self, carry, k, g0):
        self.carry, self.k, self.g0 = carry, k, g0
        self.n = defaultdict(float); self.d = defaultdict(float); self.name = {}; self.team = {}
        self.starts = defaultdict(lambda: defaultdict(float))     # team -> goalie -> recent starts (decayed)
        self.last = {}                                           # goalie -> day of his last game

    def season(self):
        for p in self.n:
            self.n[p] *= self.carry; self.d[p] *= self.carry
        for t in self.starts:
            for p in self.starts[t]:
                self.starts[t][p] *= 0.3

    def rating(self, p):
        return (self.n[p] + self.k * self.g0) / (self.d[p] + self.k)

    def add(self, t, lines, xga, day):
        tot = sum(l[3] for l in lines) or 1
        for pid, nm, st, toi, sa, ga in lines:
            sh = toi / tot
            if sh <= 0:
                continue
            self.n[pid] += sh * xga - ga; self.d[pid] += sh
            self.name[pid] = nm; self.team[pid] = t; self.last[pid] = day
            if st:
                for q in self.starts[t]:
                    self.starts[t][q] *= 0.97
                self.starts[t][pid] += 1

    def starter(self, lines):
        st = [l for l in lines if l[2]]
        return (st or sorted(lines, key=lambda l: -l[3]) or [[None]])[0][0]

    def depth(self, t):
        """the team's goalies by recent starts (decayed), only those whose last game was for this team"""
        s = self.starts.get(t, {})
        return sorted([p for p in s if self.team.get(p) == t and s[p] > 0.05], key=lambda p: -s[p])

    def expected(self, t):
        """the team's goalie rating at its usual start shares"""
        s = self.starts.get(t, {})
        ps = self.depth(t)[:3]
        w = sum(s[p] for p in ps)
        return sum(s[p] * self.rating(p) for p in ps) / w if w else self.g0


# ---------------------------------------------------------------- lineups
_LN = {}      # season -> {gameId: {team: ['<player id><F|D>' for each skater dressed]}}
_LV = {}      # season -> (prior-season players, replacement HPM, usual TOI by group)


def make_lineups():
    """freeze every completed season's dressed skaters (stats-API skater game logs, ice time > 0)"""
    out = {}
    for S in range(2012, D.current_season()):      # 2012 on: the season sims' backtest walks from there
        out[str(S)] = lineups_from_logs(D.skater_logs(S))
        print(S, len(out[str(S)]), 'games', flush=True)
    D.save(LINEUPS, out)
    print('wrote', LINEUPS)


def lineups_from_logs(logs):
    by = defaultdict(lambda: defaultdict(list))
    for gid, pid, nm, t, pos, toi, *_ in logs:
        if toi and toi > 0:
            by[str(gid)][t].append(f"{pid}{'D' if pos == 'D' else 'F'}")
    return {g: dict(v) for g, v in by.items()}


def set_lineups(S, ln):
    _LN[S] = ln


def _lineups(S):
    if S not in _LN:
        try:
            _LN.update({int(k): v for k, v in D.load(LINEUPS).items() if int(k) not in _LN})
        except OSError:
            pass
        _LN.setdefault(S, {})
    return _LN[S]


def _war(S):
    """season S's lineup pricing from the WAR run's season S-1 file: projected HPM (goals a 60 over average), usual
    ice time a game, replacement HPM for newcomers"""
    if S not in _LV:
        try:
            d = json.load(open(os.path.join(WARD, f'{S - 1}.json')))
        except OSError:
            _LV[S] = None
            return None
        ps = {p['id']: p for p in d['players'] if p['grp'] in ('F', 'D')}
        reg = [p for p in ps.values() if p['gp'] >= 20]
        avg = {g: sum(p['toi'] * 60 / p['gp'] for p in reg if p['grp'] == g) / max(1, sum(p['grp'] == g for p in reg))
               for g in ('F', 'D')}
        _LV[S] = (ps, d['repl'], avg)
    return _LV[S]


def lineup_value(S, gid, t):
    """goals a 60 the team's dressed skaters add at their projected rates and usual ice time; None without data"""
    ids = _lineups(S).get(str(gid), {}).get(t)
    w = _war(S)
    if not ids or w is None:
        return None
    ps, repl, avg = w
    v = 0.0
    for x in ids:                                   # '<player id><F|D>'
        p, g = ps.get(x[:-1]), x[-1]
        if p:
            v += p['hpm'] * min(p['toi'] * 60 / p['gp'] if p['gp'] else avg[g], 1800) / 3600
        else:                                       # newcomer: replacement level at his position's usual ice time
            v += repl.get(g, 0.0) * avg[g] / 3600
    return v


# ---------------------------------------------------------------- the walk
def _days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


class Model:
    def __init__(self, P):
        self.P = P
        self.elo = Elo(P['K'], P['reg'])
        self.xg = OD(P['hl'], P['car'], P['pen'])
        self.gl = OD(P['ghl'], P['gcar'], P['pen'])
        self.x5 = OD(P['hl'], P['car'], P['pen'])
        self.st = OD(P['hl'], P['car'], P['pen'] * 2)
        self.mk = MKT(P['mhl'], P['mcar'], P['pen'])
        self.gk = Goalies(P['gk_car'], P['gk_k'], P['gk_0'])
        self.day, self.S = None, None
        self.lastday = {}
        self.lv = {}                                             # team -> its last lineup's value, this season
        self.W = defaultdict(int); self.L = defaultdict(int); self.OTL = defaultdict(int)

    def advance(self, day, S):
        if self.S is not None and S != self.S:
            for e in (self.xg, self.gl, self.x5, self.st, self.mk, self.elo, self.gk):
                e.season()
            self.W.clear(); self.L.clear(); self.OTL.clear(); self.lv.clear()
        if self.day is not None and day > self.day:
            n = _days(self.day, day)
            for e in (self.xg, self.gl, self.x5, self.st, self.mk):
                e.step(n)
        self.day, self.S = day, S

    def rest(self, t, day):
        if t not in self.lastday:
            return 3
        return max(0, min(3, _days(self.lastday[t], day) - 1))

    def feats(self, g, gh=None, ga=None, home=1.0):
        """inputs for game g; gh, ga: the starting goalies (default: the ones who started)"""
        h, a = g['h'], g['a']
        if gh is None and 'gl' in g:
            gh, ga = self.gk.starter(g['gl']['h']), self.gk.starter(g['gl']['a'])
        rgh = self.gk.rating(gh) if gh else self.gk.expected(h)
        rga = self.gk.rating(ga) if ga else self.gk.expected(a)
        rh, ra = self.rest(h, g['day']), self.rest(a, g['day'])
        rv = self.lv[h] - self.lv[a] if h in self.lv and a in self.lv else 0.0
        f = {'elo': (self.elo.r[h] - self.elo.r[a]) / 100, 'xg': self.xg.net(h, a), 'g': self.gl.net(h, a),
             'x5': self.x5.net(h, a), 'st': self.st.net(h, a), 'mkt': self.mk.rating(h) - self.mk.rating(a),
             'gk': rgh - rga, 'gkd': (rgh - self.gk.expected(h)) - (rga - self.gk.expected(a)),
             'bk': self._backup(a, ga) - self._backup(h, gh), 'rv': rv, 'rest': rh - ra, 'b2b': int(rh == 0) - int(ra == 0), 'home': home,
             'xgT': self.xg.total(h, a, home), 'gT': self.gl.total(h, a, home), 'mtot': self.mk.total(h, a),
             'gkT': -(rgh + rga), 'one': 1.0}
        return f

    def lineup(self, t):
        """the team's last lineup value against the league's average one (0 before it has played)"""
        if t not in self.lv:
            return 0.0
        return self.lv[t] - sum(self.lv.values()) / len(self.lv)

    def _backup(self, t, p):
        d = self.gk.depth(t)
        return int(bool(p) and bool(d) and p != d[0])

    def update(self, g):
        h, a = g['h'], g['a']
        if g.get('hs') is None:
            return
        self.elo.add(h, a, g['hs'], g['as'])
        x = g.get('x')
        if x:
            xh, xa = x['h'], x['a']
            self.xg.add(h, a, xh[0], xa[0])
            self.gl.add(h, a, xh[2], xa[2])
            self.x5.add(h, a, xh[3], xa[3])
            # special teams: power-play xG for and penalty-kill xG against, per 60 of each
            pph = xh[5] / max(xh[7], 1) * 60 if xh[7] > 1 else None
            ppa = xa[5] / max(xa[7], 1) * 60 if xa[7] > 1 else None
            if pph is not None and ppa is not None:
                self.st.add(h, a, pph, ppa)
            if 'gl' in g:
                self.gk.add(h, g['gl']['h'], xa[1], g['day'])
                self.gk.add(a, g['gl']['a'], xh[1], g['day'])
        c = g.get('c')
        if c:
            self.mk.add(h, a, c.get('p'), c.get('t'))
        self.lastday[h] = self.lastday[a] = g['day']
        for t in (h, a):
            v = lineup_value(g['S'], g['id'], t)
            if v is not None:
                self.lv[t] = v
        hw = g['hs'] > g['as']
        ot = (g.get('per') or 3) > 3
        if not g.get('po'):
            w, l = (h, a) if hw else (a, h)
            self.W[w] += 1
            (self.OTL if ot else self.L)[l] += 1


def walk(games, P, upcoming=(), starters=None):
    """every final game's pre-game inputs, in order; then upcoming games' inputs from the final state"""
    m = Model(P)
    rows = []
    for g in games:
        m.advance(g['day'], g['S'])
        if g['S'] >= SCORE_FROM and g.get('hs') is not None:
            f = m.feats(g)
            rows.append((g, f))
        m.update(g)
    up = []
    for g in upcoming:
        m.advance(g['day'], g['S'])
        st = (starters or {}).get(g['id'], {})
        up.append((g, m.feats(g, st.get('h'), st.get('a'), 0.0 if g.get('neutral') else 1.0)))
    return m, rows, up


# ---------------------------------------------------------------- fitting
def logit_fit(X, y, ridge=1e-3, w=None, iters=30):
    b = np.zeros(X.shape[1])
    w = np.ones(len(y)) if w is None else w
    R = ridge * np.eye(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ b)))
        W = w * p * (1 - p) + 1e-9
        g = X.T @ (w * (y - p)) - R @ b
        H = (X * W[:, None]).T @ X + R
        st = np.linalg.solve(H, g)
        b += st
        if np.abs(st).max() < 1e-8:
            break
    return b


def sig(z):
    return 1 / (1 + np.exp(-z))


def design(rows, feats):
    return np.array([[f[k] for k in feats] for g, f in rows], float)


def arrays(rows):
    S = np.array([g['S'] for g, f in rows])
    y = np.array([g['hs'] > g['as'] for g, f in rows], float)
    m = np.array([g['hs'] - g['as'] for g, f in rows], float)
    tot = np.array([g['hs'] + g['as'] for g, f in rows], float)
    pc = np.array([(g.get('c') or {}).get('p') if (g.get('c') or {}).get('p') is not None else np.nan for g, f in rows], float)
    tc = np.array([(g.get('c') or {}).get('t') or np.nan for g, f in rows], float)
    day = np.array([g['day'] for g, f in rows])
    return S, y, m, tot, pc, tc, day


def walk_logit(X, y, S, first, train=None):
    p = np.full(len(y), np.nan)
    ok = np.ones(len(y), bool) if train is None else train
    for s in range(first, int(S.max()) + 1):
        tr, te = (S < s) & ok, S == s
        if te.any() and tr.sum() > 200:
            p[te] = sig(X[te] @ logit_fit(X[tr], y[tr]))
    return p


def walk_ols(X, y, S, first, train=None):
    import harness as H
    return H.walk_ols(X, y, S, first, train=train)


def score(rows, feats):
    S, y, m, tot, pc, tc, day = arrays(rows)
    X = design(rows, feats)
    p = walk_logit(X, y, S, FIRST_TEST, ~np.isnan(pc))
    return p, S, y, day


def tune(hist, start=None):
    """coordinate search over the rating hyperparameters on 2016-23 log loss (the held-out seasons never seen)"""
    import harness as H
    P = dict(start or P0)
    grid = {'K': [4, 6, 9], 'reg': [0.2, 0.35, 0.5], 'hl': [30, 60, 120], 'car': [0.3, 0.5, 0.7],
            'ghl': [30, 60, 120], 'gcar': [0.3, 0.5, 0.7], 'mhl': [20, 40, 80], 'mcar': [0.2, 0.4, 0.7],
            'gk_car': [0.4, 0.6, 0.8], 'gk_k': [10, 25, 50], 'gk_0': [-0.25, -0.1, 0.0], 'pen': [1.0, 4.0, 12.0]}

    mk_keys = ('mhl', 'mcar')

    def loss(P, key=None):
        """market memory: the full model on the lined seasons (2021-23); everything else: the model without the market
        rating on every game 2017-23 (seven seasons, so the memories aren't fit to three)"""
        _, rows, _ = walk(hist, P)
        S, y, m, tot, pc, tc, day = arrays(rows)
        if key in mk_keys:
            p = walk_logit(design(rows, FEATS), y, S, FIRST_TEST, ~np.isnan(pc))
            ok = (S >= TUNE[0]) & (S <= TUNE[1]) & ~np.isnan(pc)
        else:
            p = walk_logit(design(rows, [k for k in FEATS if k != 'mkt']), y, S, SCORE_FROM + 1)
            ok = (S >= SCORE_FROM + 1) & (S <= TUNE[1])
        return float(H.logloss(p[ok], y[ok]).mean())
    best = None
    for k, vals in grid.items():
        cur = loss(P, k)
        for v in vals:
            if v == P[k]:
                continue
            Q = dict(P); Q[k] = v
            l = loss(Q, k)
            if l < cur - 1e-5:
                cur, P = l, Q
        best = cur
        print(k, P[k], round(cur, 5), flush=True)
    return P, best


def evidence(rows, feats, cands=(), lined_only=True, first=FIRST_TEST, tune_s=TUNE):
    """drop-one for kept inputs, add-one for candidates: walk-forward log loss on win, t clustered by day (positive t =
    the input helps). lined_only: train and score on games with a closing line (the market rating's seasons)"""
    import harness as H
    S, y, m, tot, pc, tc, day = arrays(rows)
    ok = ~np.isnan(pc) if lined_only else np.ones(len(y), bool)
    tune_m = (S >= tune_s[0]) & (S <= tune_s[1]) & ok
    held_m = (S >= HOLD_FROM) & ok

    def wl(fs):
        return walk_logit(design(rows, fs), y, S, first, ok)
    lb = H.logloss(wl(feats), y)
    out = {}
    for k in list(feats) + list(cands):
        fs = [f for f in feats if f != k] if k in feats else list(feats) + [k]
        l = H.logloss(wl(fs), y)
        a, b = (l, lb) if k in feats else (lb, l)
        rt = H.paired(b[tune_m], a[tune_m], day[tune_m]); rh = H.paired(b[held_m], a[held_m], day[held_m])
        out[k] = {'kept': k in feats, 'tTune': round(-rt['t'], 2), 'tHeld': round(-rh['t'], 2),
                  'dTune': round(-rt['d'] * 1000, 3), 'dHeld': round(-rh['d'] * 1000, 3),
                  'split': f'{tune_s[0]}-{tune_s[1] % 100:02d} / {HOLD_FROM}-26' + (' lined' if lined_only else '')}
        print(k, out[k], flush=True)
    return out


CORE = ('home', 'xg')
EXTRA = ['bk', 'gkd']             # backup goalie starting; tonight's goalie against the team's usual


def passes(e):
    return e['tTune'] >= 1.5 and e['tHeld'] > -1.0


def calib_bins(p, y):
    out = []
    q = np.maximum(p, 1 - p); won = np.where(p >= 0.5, y, 1 - y)
    for lo in np.arange(0.5, 0.95, 0.05):
        sel = (q >= lo) & (q < lo + 0.05)
        if sel.sum() >= 20:
            out.append({'bin': round(float(lo), 2), 'n': int(sel.sum()), 'model': round(float(q[sel].mean()), 3),
                        'won': round(float(won[sel].mean()), 3)})
    return out


def season_sd(rows, coefs, feats):
    """rating error at the start of a season, in logit units: per team-season mean residual (result minus model) over
    the whole season, its variance net of game noise"""
    S, y, m, tot, pc, tc, day = arrays(rows)
    z = design(rows, feats) @ coefs
    p = sig(z)
    res = defaultdict(list)
    for (g, f), yi, pi in zip(rows, y, p):
        if g['po'] or g['S'] < SCORE_FROM + 1:
            continue
        # residual in logit units: (y - p) / (p (1 - p)) is unbiased for the logit error, noisy; use the score scale
        res[(g['S'], g['h'])].append((yi - pi, pi * (1 - pi)))
        res[(g['S'], g['a'])].append((-(yi - pi), pi * (1 - pi)))
    est, noise = [], []
    for k, v in res.items():
        if len(v) < 40:
            continue
        num = sum(a for a, b in v); den = sum(b for a, b in v)
        est.append(num / den); noise.append(1 / den)
    est, noise = np.array(est), np.array(noise)
    return float(math.sqrt(max(0.01, est.var() - noise.mean())))


def fit():
    import harness as H
    hist = load_hist()
    print('games', len(hist), flush=True)
    if '--notune' in sys.argv and os.path.exists(FIT):
        P = json.load(open(FIT))['params']
    else:
        P, _ = tune(hist)
        P, _ = tune(hist, P)              # a second pass from the first pass's settings
    m, rows, _ = walk(hist, P)
    # non-market inputs on the long record (2017-23 tuning, every game); then the market rating on the lined seasons
    nm = [k for k in FEATS if k != 'mkt']
    ev = evidence(rows, nm, CANDS + EXTRA, lined_only=False, first=SCORE_FROM + 1, tune_s=(SCORE_FROM + 1, TUNE[1]))
    feats = [k for k in nm if k in CORE or passes(ev[k])] + [k for k in CANDS + EXTRA if passes(ev[k])]
    ev.update(evidence(rows, feats, ['mkt']))
    if passes(ev['mkt']):
        feats.append('mkt')
    print('kept', feats, flush=True)
    S, y, mg, tot, pc, tc, day = arrays(rows)
    X = design(rows, feats)
    lined = ~np.isnan(pc)
    # with the market rating in, weights come from the lined seasons only (2019-20 on: the other inputs carry less
    # once it's there); without it, from every season
    trn = lined if 'mkt' in feats else np.ones(len(y), bool)
    p = walk_logit(X, y, S, SCORE_FROM + 1, trn)
    mhat = walk_ols(X, mg, S, SCORE_FROM + 1, trn)
    TX = design(rows, TFEATS)
    lined_t = ~np.isnan(tc)
    That = walk_ols(TX, tot, S, FIRST_TEST, lined_t)
    # puck line and overtime: logistic on the model margin and total (walk-forward too)
    Z = np.column_stack([np.ones(len(y)), np.nan_to_num(mhat), np.nan_to_num(That)])
    ph2 = walk_logit(Z, (mg >= 2).astype(float), S, FIRST_TEST + 1, lined_t)
    pa2 = walk_logit(Z, (mg <= -2).astype(float), S, FIRST_TEST + 1, lined_t)
    per = np.array([(g.get('per') or 3) > 3 for g, f in rows], float)
    Zo = np.column_stack([np.ones(len(y)), np.nan_to_num(mhat) ** 2, np.nan_to_num(That)])
    pot = walk_logit(Zo, per, S, FIRST_TEST + 1, lined_t)

    def block(mask, label):
        ok = mask & ~np.isnan(p)
        lm = ok & ~np.isnan(pc)
        lt = ok & lined_t & ~np.isnan(That)
        d = {'games': int(ok.sum()), 'logLossModel': round(float(H.logloss(p[ok], y[ok]).mean()), 4),
             'brierModel': round(float(H.brier(p[ok], y[ok]).mean()), 4),
             'lined': int(lm.sum())}
        if lm.sum():
            pr = H.paired(H.logloss(p[lm], y[lm]), H.logloss(pc[lm], y[lm]), day[lm])
            d.update({'logLossLinedModel': round(float(H.logloss(p[lm], y[lm]).mean()), 4),
                      'logLossMarket': round(float(H.logloss(pc[lm], y[lm]).mean()), 4), 'tVsMarket': round(pr['t'], 2),
                      'rModelVsMarket': round(float(np.corrcoef(p[lm], pc[lm])[0, 1]), 3)})
            # favourite by the model, against the market's favourite: how often each is right
            pick = np.where(p[lm] >= 0.5, y[lm], 1 - y[lm]); mk = np.where(pc[lm] >= 0.5, y[lm], 1 - y[lm])
            d.update({'hitModel': round(float(pick.mean()), 3), 'hitMarket': round(float(mk.mean()), 3)})
        if lt.sum():
            d.update({'totalGames': int(lt.sum()), 'totalMaeModel': round(float(np.abs(That[lt] - tot[lt]).mean()), 3),
                      'totalMaeLine': round(float(np.abs(tc[lt] - tot[lt]).mean()), 3)})
        okm = ok & ~np.isnan(mhat)
        d['maeMargin'] = round(float(np.abs(mhat[okm] - mg[okm]).mean()), 3)
        print(label, d, flush=True)
        return d
    test = {f'{TUNE[0]}-{TUNE[1] % 100:02d} (tuning)': block((S >= TUNE[0]) & (S <= TUNE[1]), 'tune'),
            f'{HOLD_FROM}-{int(S.max()) % 100:02d} (held out)': block(S >= HOLD_FROM, 'held')}
    # final weights: every scored season
    L = trn
    cw = logit_fit(X[L], y[L])
    mw = np.linalg.lstsq(X[L], mg[L], rcond=None)[0]
    tw = np.linalg.lstsq(TX[lined_t], tot[lined_t], rcond=None)[0]
    Zf = np.column_stack([np.ones(len(y)), X @ mw, TX @ tw])
    Lt = lined_t
    c2h = logit_fit(Zf[Lt], (mg[Lt] >= 2).astype(float)); c2a = logit_fit(Zf[Lt], (mg[Lt] <= -2).astype(float))
    Zof = np.column_stack([np.ones(len(y)), (X @ mw) ** 2, TX @ tw])
    cot = logit_fit(Zof[Lt], per[Lt])
    sd0 = season_sd(rows, cw, feats)
    held = S >= HOLD_FROM
    fitd = {'updated': dt.date.today().isoformat(), 'params': P, 'feats': feats, 'tfeats': TFEATS,
            'coef': {k: round(float(v), 4) for k, v in zip(feats, cw)},
            'mcoef': {k: round(float(v), 4) for k, v in zip(feats, mw)},
            'tcoef': {k: round(float(v), 4) for k, v in zip(TFEATS, tw)},
            'pl': {'home2': [round(float(v), 4) for v in c2h], 'away2': [round(float(v), 4) for v in c2a]},
            'ot': [round(float(v), 4) for v in cot],
            'sdMargin': round(float(np.nanstd(mg - mhat)), 3), 'sdTotal': round(float(np.nanstd(tot - That)), 3),
            'seasonSd': round(sd0, 3), 'evidence': ev, 'test': test,
            'calib': calib_bins(p[held & ~np.isnan(p)], y[held & ~np.isnan(p)]),
            'plCheck': {'home2Model': round(float(np.nanmean(ph2[held])), 3), 'home2': round(float((mg[held] >= 2).mean()), 3),
                        'away2Model': round(float(np.nanmean(pa2[held])), 3), 'away2': round(float((mg[held] <= -2).mean()), 3),
                        'otModel': round(float(np.nanmean(pot[held])), 3), 'ot': round(float(per[held].mean()), 3)}}
    json.dump(fitd, open(FIT, 'w'), indent=1)
    # walk-forward rows for the picks system (scripts/games_picks.py): model chance, margin, total, closing consensus
    wf = []
    for i, (g, f) in enumerate(rows):
        if np.isnan(p[i]):
            continue
        wf.append({'id': g['id'], 'S': g['S'], 'day': g['day'], 'h': g['h'], 'a': g['a'], 'hs': g['hs'], 'as': g['as'],
                   'per': g.get('per'), 'po': g['po'], 'p': round(float(p[i]), 4), 'm': round(float(mhat[i]), 3),
                   'T': None if np.isnan(That[i]) else round(float(That[i]), 3),
                   'c': g.get('c'), 'o': g.get('o')})
    D.save(WF, wf)
    print('wrote', FIT, WF, len(wf))


# ---------------------------------------------------------------- live
def starters_df(day):
    """Daily Faceoff's starting goalies for a date: {(home, away): {'h': (name, strength), 'a': ...}}"""
    try:
        req = urllib.request.Request(f'https://www.dailyfaceoff.com/starting-goalies/{day}', headers={'User-Agent': D.UA})
        h = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        data = json.loads(m.group(1))['props']['pageProps'].get('data') or []
    except Exception as e:
        print('daily faceoff:', e, file=sys.stderr)
        return {}
    out = {}
    for r in data:
        hh, aa = D.team(r.get('homeTeamAbbreviation')), D.team(r.get('awayTeamAbbreviation'))
        out[(hh, aa)] = {'h': (r.get('homeGoalieName'), r.get('homeNewsStrengthName')),
                         'a': (r.get('awayGoalieName'), r.get('awayNewsStrengthName'))}
    return out


def pick_starter(m, t, df, day):
    """tonight's goalie: Daily Faceoff's (confirmed or likely) matched to the team's goalies, else the team's usual
    starter, or his partner on the second night of a back-to-back if the partner has started a share of games"""
    depth = m.gk.depth(t)
    if df and df[0]:
        pool = [{'name': nm, 'pid': p, 'team': m.gk.team.get(p)} for p, nm in m.gk.name.items()]
        hit, _ = NM.Matcher(pool, pos=None).find(df[0], team=t, cross_team='variant')
        if hit is not None:
            return hit['pid'], (df[1] or 'listed').lower()
        if hit is not None:
            return hit['id'], (df[1] or 'listed').lower()
        return None, 'new'
    if not depth:
        return None, 'unknown'
    if m.rest(t, day) == 0 and len(depth) > 1:
        return depth[1], 'projected (back-to-back)'
    return depth[0], 'projected'


def project(f, fit):
    z = sum(fit['coef'][k] * f[k] for k in fit['feats'])
    mm = sum(fit['mcoef'][k] * f[k] for k in fit['feats'])
    T = sum(fit['tcoef'][k] * f[k] for k in fit['tfeats'])
    p = float(sig(z))
    c2h, c2a = fit['pl']['home2'], fit['pl']['away2']
    p2h = float(sig(c2h[0] + c2h[1] * mm + c2h[2] * T)); p2a = float(sig(c2a[0] + c2a[1] * mm + c2a[2] * T))
    pot = float(sig(fit['ot'][0] + fit['ot'][1] * mm * mm + fit['ot'][2] * T))
    return p, mm, T, p2h, p2a, pot


def comps(m, t):
    """a team's rating inputs against an average team"""
    return {'elo': (m.elo.r[t] - 1505) / 100, 'xg': m.xg.strength(t), 'g': m.gl.strength(t), 'x5': m.x5.strength(t),
            'st': m.st.strength(t), 'mkt': m.mk.rating(t), 'gk': m.gk.expected(t), 'rv': m.lineup(t)}


def team_logit(m, fit, t):
    """a team's strength on the win-chance scale against an average team, neutral ice, usual goalie"""
    c = fit['coef']
    comp = comps(m, t)
    return {k: comp[k] for k in comp if k in c}, sum(c[k] * comp[k] for k in comp if k in c)


def team_margin(m, fit, t):
    c = fit['mcoef']
    comp = comps(m, t)
    return sum(c[k] * comp[k] for k in comp if k in c)


SIMBT = os.path.join(ROOT, 'data', 'nhl_sim_backtest.json')


def sim_knobs(fit):
    """(shrink, sd) for the season sims: the pooled best of scripts/nhl_sim_backtest.py, else no shrink and the
    game model's season sd"""
    try:
        a, sd = json.load(open(SIMBT))['pooledBest']
        return float(a), float(sd)
    except (OSError, KeyError, ValueError, TypeError):
        return 0.0, fit['seasonSd']


def simulate(m, fit, remaining, pts, sims=10000, share=1.0, seed=11):
    """rest of the regular season, then the playoffs (division top three + two wild cards a conference; 2-2-1-1-1)"""
    rng = random.Random(seed)
    c = fit['coef']
    base = {t: team_logit(m, fit, t)[1] for t in TEAMS}
    # how sure the sims are, tuned on the season outcomes themselves (scripts/nhl_sim_backtest.py, walk-forward
    # Brier of playoffs, division and Cup from checkpoints 2017-26): logits pulled toward the mean by shrink x share
    # of the season left, and a season-level rating error sd x sqrt(share left)
    a, sd = sim_knobs(fit)
    mz = sum(base.values()) / len(base)
    base = {t: mz + (1 - a * share) * (z - mz) for t, z in base.items()}
    sd = sd * math.sqrt(max(share, 0.04))
    hc = c.get('home', 0.0)
    otc = fit['ot']
    cnt = {t: defaultdict(float) for t in TEAMS}
    wins_sum = defaultdict(float)
    pts_sum = defaultdict(float)
    lot = defaultdict(lambda: defaultdict(float))
    for _ in range(sims):
        R = {t: base[t] + rng.gauss(0, sd) for t in TEAMS}
        P = dict(pts)
        for g in remaining:
            z = R[g['h']] - R[g['a']] + hc * (0.0 if g.get('neutral') else 1.0)
            ph = 1 / (1 + math.exp(-z))
            hw = rng.random() < ph
            mm = z * 1.6
            pot = 1 / (1 + math.exp(-(otc[0] + otc[1] * mm * mm + otc[2] * 6.0)))
            ot = rng.random() < pot
            w, l = (g['h'], g['a']) if hw else (g['a'], g['h'])
            P[w] += 2
            if ot:
                P[l] += 1
        for t in TEAMS:
            pts_sum[t] += P[t]
        order = {t: P[t] + rng.random() * 0.01 for t in TEAMS}
        po = []
        bracket = {}
        for cf, ds in CONF.items():
            tops = {d: sorted(DIV[d], key=lambda t: -order[t])[:3] for d in ds}
            rest_ = sorted([t for d in ds for t in DIV[d] if t not in tops[d]], key=lambda t: -order[t])
            wc = rest_[:2]
            dw = sorted([tops[d][0] for d in ds], key=lambda t: -order[t])
            # the better division winner meets the second wild card
            best_div = DIV_OF[dw[0]]
            sides = []
            for d in ds:
                opp = wc[1] if DIV_OF[tops[d][0]] == best_div else wc[0]
                sides.append([(tops[d][0], opp), (tops[d][1], tops[d][2])])
            bracket[cf] = sides
            po += [t for d in ds for t in tops[d]] + wc
            for t in tops[ds[0]] + tops[ds[1]]:
                cnt[t]['div'] += 0
            for d in ds:
                cnt[tops[d][0]]['divw'] += 1
        for t in po:
            cnt[t]['playoff'] += 1
        pres = max(TEAMS, key=lambda t: order[t])
        cnt[pres]['pres'] += 1

        def series(a, b):
            hi, lo = (a, b) if order[a] >= order[b] else (b, a)
            w = {hi: 0, lo: 0}
            for k in range(7):
                home = hi if k in (0, 1, 4, 6) else lo
                away = lo if home == hi else hi
                z = R[home] - R[away] + hc
                win = home if rng.random() < 1 / (1 + math.exp(-z)) else away
                w[win] += 1
                if w[win] == 4:
                    return win
            return hi
        champs = {}
        for cf, sides in bracket.items():
            r2 = []
            for side in sides:
                w1 = series(*side[0]); w2 = series(*side[1])
                cnt[w1]['r2'] += 1; cnt[w2]['r2'] += 1
                r2.append(series(w1, w2))
            for t in r2:
                cnt[t]['cf'] += 1
            champs[cf] = series(r2[0], r2[1])
            cnt[champs[cf]]['final'] += 1
        cup = series(champs['East'], champs['West'])
        cnt[cup]['cup'] += 1
        # draft lottery pool: the 16 non-playoff teams by points, fewest first
        nonpo = sorted([t for t in TEAMS if t not in po], key=lambda t: order[t])
        for i, t in enumerate(nonpo):
            lot[t][i + 1] += 1
    out = {}
    for t in TEAMS:
        out[t] = {k: round(v / sims, 4) for k, v in cnt[t].items()}
        out[t]['pts'] = round(pts_sum[t] / sims, 1)
        out[t]['lottery'] = {str(k): round(v / sims, 4) for k, v in sorted(lot[t].items())}
    return out


def injuries():
    """{team: [{name, status, war (WAR a full season: this season and the two before, weighted 1, .5, .25 by games)}]}
    from ESPN's NHL injury list, best players first. Shown on the cards; not a model input (no injury history to test
    it on, and the market prices the night's scratches)"""
    import names as NM
    d = D.get('https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries')
    if not d:
        return {}
    W = os.path.join(ROOT, 'static', 'data', 'nhl-war')
    seasons = sorted(int(f[:4]) for f in os.listdir(W) if f[:4].isdigit())[::-1][:3]
    acc = {}
    for y, w in zip(seasons, (1.0, 0.5, 0.25)):
        for p in json.load(open(os.path.join(W, f'{y}.json')))['players']:
            a = acc.setdefault(p['id'], {'n': p['n'], 'tm': p['tm'], 'num': 0.0, 'gp': 0.0})
            if y == seasons[0]:
                a['tm'] = p['tm']
            a['num'] += w * (p.get('war') or 0); a['gp'] += w * (p.get('gp') or 0)
    M = NM.Matcher(list(acc.values()), name='n', team='tm', pos=None)
    out = {}
    for t in d.get('injuries') or []:
        for i in t.get('injuries') or []:
            nm = (i.get('athlete') or {}).get('displayName')
            tm = D.team(((i.get('athlete') or {}).get('team') or {}).get('abbreviation') or '')
            if not nm:
                continue
            p, _ = M.find(nm, team=tm or None)
            tm = tm or (p['tm'] if p else None)
            if tm not in TEAMS:
                continue
            war = round(82 * p['num'] / p['gp'], 1) if p and p['gp'] >= 5 else None
            out.setdefault(tm, []).append({'name': nm, 'status': i.get('status') or '', 'war': war})
    for v in out.values():
        v.sort(key=lambda r: -(r['war'] if r['war'] is not None else -9))
    return out


def build():
    fit = json.load(open(FIT))
    P = fit['params']
    hist = load_hist()
    S = D.current_season()
    mp = D.moneypuck_teams()
    cur = season_rows(S, mp, fresh=True)
    try:   # this season's dressed lineups (the lineup-value input)
        set_lineups(S, lineups_from_logs(D.skater_logs(S, fresh=True)))
    except Exception as e:
        print('lineups:', e, file=sys.stderr)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))).date()
    finals = [g for g in cur if g['final'] and g['hs'] is not None]
    # the next two dates with games, from the NHL's schedule (start times, neutral sites, live state)
    sched = D.schedule(today.isoformat())
    days = sorted({g['day'] for g in sched if g['day'] >= today.isoformat()})[:2]
    up = [dict(g, S=S, po=int(g['type'] == 3)) for g in sched if g['day'] in days]
    done_ids = {g['id'] for g in finals}
    m0, _, _ = walk(hist + finals, P)
    starters, gsrc = {}, {}
    for d in days:
        df = starters_df(d)
        for g in up:
            if g['day'] != d:
                continue
            s = df.get((g['h'], g['a']), {})
            gh, sh = pick_starter(m0, g['h'], s.get('h'), d)
            ga, sa = pick_starter(m0, g['a'], s.get('a'), d)
            starters[g['id']] = {'h': gh, 'a': ga}
            gsrc[g['id']] = {'h': sh, 'a': sa}
    pending = [g for g in up if g['id'] not in done_ids]
    m, _, ups = walk(hist + finals, P, pending, starters)
    # market lines for the board (ESPN's current consensus)
    emap = D.espn_map([{'id': g['id'], 'day': g['day'], 'h': g['h'], 'a': g['a']} for g in up], fresh_after=today - dt.timedelta(days=1))
    try:
        inj = injuries()
    except Exception as e:
        print('injuries:', e, file=sys.stderr); inj = {}
    # Novig's main lines at its asks first (Noah, Oct 27 2026: "switch everything to Novig"); ESPN's DraftKings where Novig has none
    try:
        import novig
        NV = novig.prices('nhl')
    except Exception as e:
        print('novig:', e); NV = {}
    games = []
    for g, f in ups:
        p, mm, T, p2h, p2a, pot = project(f, fit)
        lh = (T + mm) / 2; la = (T - mm) / 2
        st = starters.get(g['id'], {})
        eid = emap.get(g['id'])
        c = consensus(D.espn_odds(eid, fresh=True)) if eid else None
        px = NV.get(str(eid)) if eid else None
        if px and px.get('mlH') is not None and px.get('mlA') is not None:
            qh, qa = implied(px['mlH']), implied(px['mlA'])
            c = {**(c or {}), 't': px.get('T') if px.get('T') is not None else (c or {}).get('t'), 'ml': [px['mlH'], px['mlA']], 'p': qh / (qh + qa)}
        row = {'id': g['id'], 'espn': eid, 'tip': g['start'], 'day': g['day'], 'home': g['h'], 'away': g['a'],
               'neutral': g.get('neutral', False), 'po': bool(g.get('po')), 'pHome': round(p, 3),
               'margin': round(mm, 2), 'total': round(T, 2), 'hs': round(max(lh, 0.3), 1), 'as': round(max(la, 0.3), 1),
               'pl': {'home2': round(p2h, 3), 'away2': round(p2a, 3)}, 'pOT': round(pot, 3),
               'fair': {'home': american(p), 'away': american(1 - p)},
               'parts': {k: round(fit['coef'][k] * f[k], 3) for k in fit['feats']},
               'elo': {'home': round(m.elo.r[g['h']]), 'away': round(m.elo.r[g['a']])},
               'rest': {'home': m.rest(g['h'], g['day']), 'away': m.rest(g['a'], g['day'])},
               'goalie': {s: {'name': m.gk.name.get(st.get(s[0])) if st.get(s[0]) else None,
                              'gsax': round(m.gk.rating(st.get(s[0])), 2) if st.get(s[0]) else None,
                              'src': gsrc.get(g['id'], {}).get(s[0])} for s in ('home', 'away')},
               'inj': {'home': inj.get(g['h'], [])[:5], 'away': inj.get(g['a'], [])[:5]},
               'line': None, 'tline': None, 'ml': None}
        if c:
            row['tline'] = c.get('t')
            if c.get('ml'):
                row['ml'] = {'home': c['ml'][0], 'away': c['ml'][1]}
                row['pMkt'] = c.get('p')
        if g.get('state') in ('FINAL', 'OFF'):
            row['final'] = {'home': g.get('hs'), 'away': g.get('as')}
        games.append(row)
    # standings, power rankings and season odds
    reg = [g for g in cur if not g['po']]
    left = [g for g in reg if not g['final']]
    pts = {t: 2 * m.W[t] + m.OTL[t] for t in TEAMS}
    gp = {t: m.W[t] + m.L[t] + m.OTL[t] for t in TEAMS}
    share = len(left) / max(len(reg), 1)
    sims = simulate(m, fit, left, pts, share=share)
    power = []
    for t in TEAMS:
        comp, z = team_logit(m, fit, t)
        o, d = m.xg.parts(t)
        gid = m.gk.depth(t)
        power.append({'t': t, 'div': DIV_OF[t], 'conf': CONF_OF[t], 'logit': round(z, 4),
                      'rating': round(team_margin(m, fit, t), 3), 'elo': round(m.elo.r[t]),
                      'xgf': round(o, 2), 'xga': round(-d, 2), 'gnet': round(m.gl.strength(t), 2),
                      'mkt': round(m.mk.rating(t), 3), 'gk': round(m.gk.expected(t), 3),
                      'goalie': m.gk.name.get(gid[0]) if gid else None,
                      'rec': f'{m.W[t]}-{m.L[t]}-{m.OTL[t]}', 'gp': gp[t], 'pts': pts[t], 'xpts': sims[t]['pts'],
                      'playoff': sims[t].get('playoff', 0.0), 'divw': sims[t].get('divw', 0.0), 'r2': sims[t].get('r2', 0.0),
                      'cf': sims[t].get('cf', 0.0), 'final': sims[t].get('final', 0.0), 'cup': sims[t].get('cup', 0.0),
                      'pres': sims[t].get('pres', 0.0), 'lottery': sims[t]['lottery']})
    # win chance against an average team on neutral ice (the board's headline rating)
    mean_z = sum(r['logit'] for r in power) / len(power)
    for r in power:
        r['pWin'] = round(float(sig(r['logit'] - mean_z)), 3)
    power.sort(key=lambda r: -r['rating'])
    for i, r in enumerate(power, 1):
        r['rk'] = i
    try:
        import rank_odds
        rank_odds.add(power, 'nhl', share)
    except Exception as e:
        print('rank odds:', e, file=sys.stderr)
    # team breakdowns for the power rankings' dropdowns (scripts/team_detail.py, display only): the rating split into
    # its inputs (goals a game), and the schedule with each game left at the game model's strengths and home edge
    try:
        import team_detail
        mc, hc = fit['mcoef'], fit['coef'].get('home', 0.0)
        TD, base = {}, {}
        for t in TEAMS:
            comp, base[t] = team_logit(m, fit, t)
            full = comps(m, t)
            TD[t] = {'parts': [[k, round(mc[k] * v, 3)] for k, v in full.items() if k in mc]}
        sch = []
        for g in reg:
            row = {'d': g['day'], 'h': g['h'], 'a': g['a'], 'n': bool(g.get('neutral'))}
            if g['final']:
                row.update(hs=g['hs'], **{'as': g['as']})
            else:
                z = base[g['h']] - base[g['a']] + hc * (0.0 if g.get('neutral') else 1.0)
                row.update(p=float(sig(z)), m=z * 1.6)
            sch.append(row)
        for t, s in team_detail.schedules(sch, TEAMS).items():
            TD[t]['sch'] = s
        team_detail.save('nhl', TD)
    except Exception as e:            # the dropdowns keep the last file rather than stop the build
        print('team breakdowns failed:', repr(e), file=sys.stderr)
    rec = {t: f'{m.W[t]}-{m.L[t]}-{m.OTL[t]}' for t in TEAMS}
    out = {'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'days': days, 'games': games, 'rec': rec, 'coef': fit['coef'], 'test': fit['test'], 'calib': fit['calib'],
           'power': power, 'sims': 10000, 'left': len(left), 'seasonSd': fit['seasonSd'],
           'simKnobs': dict(zip(('shrink', 'sd'), sim_knobs(fit))),
           'goalies': goalie_table(m, S)}
    json.dump(out, open(OUT, 'w'), indent=None, separators=(',', ':'))
    print('wrote', OUT, len(games), 'games', len(left), 'left')


def goalie_table(m, S):
    """every goalie who has played for a current team: rating (GSAx a game, shrunk), team, recent start share"""
    rows = []
    for t in TEAMS:
        s = m.gk.starts.get(t, {})
        ps = m.gk.depth(t)
        tot = sum(s[p] for p in ps) or 1
        for p in ps[:4]:
            rows.append({'id': p, 'name': m.gk.name.get(p), 't': t, 'gsax': round(m.gk.rating(p), 3),
                         'share': round(s[p] / tot, 3), 'gp': round(m.gk.d[p], 1)})
    rows.sort(key=lambda r: -r['gsax'])
    try:   # headshots (ESPN ids from the NHL WAR run's map, scripts/faces.py)
        import faces
        faces.nhl_attach(rows, fresh=False, name='name', team='t')
    except Exception as e:
        print('goalie faces skipped:', e)
    return rows


if __name__ == '__main__':
    if '--hist' in sys.argv:
        make_hist()
        make_lineups()
    elif '--lineups' in sys.argv:
        make_lineups()
    elif '--fit' in sys.argv:
        fit()
    else:
        build()
