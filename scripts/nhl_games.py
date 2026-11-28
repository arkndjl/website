#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL game projections for the NHL ARKBOARD (data/nhl_games.json), and the model behind them (data/nhl_games_fit.json).

    python3 scripts/nhl_games.py           # today's and tomorrow's projections, power rankings, season odds (numpy)
    python3 scripts/nhl_games.py --hist    # freeze past seasons into scripts/nhl_games_hist.json.gz (from the caches)
    python3 scripts/nhl_games.py --fit     # tune, walk-forward backtest 2016-2026 against the closing line, refit
    python3 scripts/nhl_games.py --lineups # freeze past seasons' dressed skaters into scripts/data/nhl_lineups.json.gz
    python3 scripts/nhl_games.py --goalies # tonight's starting goalies from Daily Faceoff into the board (no rebuild)
    python3 scripts/nhl_games.py --test    # synthetic playoffs (series state, seeds, bracket marks) and the hist extension

Data: the NHL's stats API (scores, last period, goalie and skater game logs), MoneyPuck (each team's expected goals a game, all
situations and by strength, score- and venue-adjusted), ESPN (every listed book's moneyline and total, 2019-20 on),
Daily Faceoff (tonight's starting goalies, confirmed or likely). Every input is known before puck drop. The backtest
and the fit never see who started: each side's goalie inputs are its goalies' ratings at their start chances before
starter news (Goalies.pstart); live, a goalie Daily Faceoff names takes his own rating (until Nov 5 2026 history used
the goalie who went on to start).

Goal margin (home minus away) and the home team's chance to win are linear in:
    elo     Elo difference (538's hockey Elo: margin multiplier, autocorrelation correction, K tuned, part of the way
            back to the mean each offseason)
    xg      expected-goal rating: each team's attack and defence in score- and venue-adjusted xG a game, fit jointly
            (exponentially weighted ridge: half-life in days tuned, carried into the next season at a fraction), so
            every opponent counts at its own strength
    g       the same rating on actual goals (finishing and goaltending the xG model doesn't see)
    mkt     market rating: each team's logit win chance against an average team as earlier closing moneylines priced
            it (never the game's own line), the same weighting
    gk      the goalies (named starter live, else start-chance weighted): goals saved above expected a game (MoneyPuck xG against his share of the game, minus
            goals allowed), shrunk toward a new goalie's level, carried across seasons at a fraction, home minus away
    rest    days of rest (0-3) home minus away, and back-to-backs
    rv      lineup value: the skaters each team dressed in its previous game this season, each at his projected
            impact (HPM from the NHL WAR run's previous season, scripts/nhl_players.py: data through last season only)
            times his usual ice time last season, newcomers at replacement; home minus away, 0 until both teams have
            played. Each skater's HPM is moved by an age line (age_line(): season rate minus projected HPM on age,
            fit on the seasons before; ~-.024 goals a 60 a year from 27, so young players are priced up and old ones
            down: Oct 30 2026, lined tune t 2.2 / held 2.7, every game 2.6 / 3.0, 8 of 10 seasons; the draft grade
            adds nothing on top, scripts/fv_games_research.py). A past season's HPM carries the weights known when
            that season ended (scripts/data/nhl_hpm_nested.json.gz, nhl_players.py nested(): with weights fit on
            every season the held-out gain read 1.75 mil, with these 1.24). A bottom-up roster rating beside the team-level ones, after HockeyStats.com's game model
            (TopDownHockey: player impacts summed over the lineup); 2012-26 skater logs frozen in
            scripts/data/nhl_lineups.json.gz
    home    1 at a home rink
Candidate inputs enter only when they lower walk-forward log loss on 2016-23 (clustered t <= -1.5) and 2024-26
doesn't disagree (see fit()). Win chance: logistic on the inputs. Total goals: both attacks against both defences on
xG and goals, the market total rating from earlier closing totals, and the two goalies, weighted by regression.
Puck line and overtime chances: logistic on the model margin and total, fit to results.
"""
import datetime as dt
import json
import math
import os
import random
import re
import sys
import time
import urllib.request
from collections import defaultdict
from zoneinfo import ZoneInfo

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
# the starting goalie before starter news (Goalies.pstart, Nov 5 2026 leak fix: fit on 2016-23 starts, grid over share
# power .5-3, last starter -.5..1, back-to-back -3..-1). History games and live games with no Daily Faceoff name take the
# start-chance-weighted rating, never the goalie who went on to start (the backtest used to: 66% of team-games the usual
# starter, 48% the projected one on back-to-backs)
GK_LAST, GK_B2B = 0.5, -2.5
P0 = {'K': 6.0, 'reg': 0.3, 'hl': 60.0, 'car': 0.5, 'ghl': 45.0, 'gcar': 0.5, 'mhl': 40.0, 'mcar': 0.4,
      'gk_car': 0.6, 'gk_k': 25.0, 'gk_0': -0.1, 'pen': 4.0}
# data/nhl_games_fit.json runs hl 60 (tune() picked 120): re-picking the settings each season on the seasons before it
# beat the fixed ones held out 2024-26 (scripts/wf_retune.py, Nov 23 2026: -.00065 log loss, t by month -2.85, 18/27)


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
    attach_gx(out, recent=S >= D.current_season())
    return out


def attach_gx(rows, recent=False):
    """each goalie's own xG faced, from MoneyPuck's goalie logs: r['gx'] = {'h': {playerId: xG}, 'a': ...}"""
    pids = {l[0] for r in rows for s in ('h', 'a') for l in (r.get('gl') or {}).get(s, [])}
    mg = D.moneypuck_goalie_games(pids, recent=pids if recent else ())
    for r in rows:
        x = mg.get(r['id'])
        if x and 'gl' in r:
            r['gx'] = {s: {str(l[0]): x[l[0]][0] for l in r['gl'][s] if l[0] in x} for s in ('h', 'a')}
    return rows


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


def ensure_hist(hist, S, pull=None, save=True):
    """the frozen history through season S - 1. After the Aug 1 rollover (nhl_data.current_season) the season just
    finished is in neither the frozen file nor the live pull; each missing completed season is pulled (season_rows,
    final games only), added and saved, the same as --hist would. pull: season -> rows (the --test cases). A failed
    pull is logged and the build goes on without that season"""
    have = {r['S'] for r in hist}
    last = max(have) if have else FIRST - 1
    miss = [s for s in range(max(last + 1, FIRST), S) if s not in have]
    if not miss:
        return hist
    print(f'nhl hist: ends {last}, current season {S}: adding {miss}', flush=True)
    if pull is None:
        mp = D.moneypuck_teams()
        pull = lambda s: season_rows(s, mp)
    add = []
    for s in miss:
        try:
            rs = [r for r in pull(s) if r['final']]
        except Exception as e:
            print(f'nhl hist: {s} not pulled: {e!r}', file=sys.stderr, flush=True)
            break
        if not rs:
            print(f'nhl hist: {s} has no final games', file=sys.stderr, flush=True)
            break
        print(f'nhl hist: {s}', len(rs), 'games', sum(1 for r in rs if 'c' in r), 'lined', flush=True)
        add += rs
    if not add:
        return hist
    hist = hist + add
    if save:
        D.save(HIST, hist)
        print('nhl hist: wrote', HIST, len(hist), flush=True)
        try:      # the same seasons' dressed lineups (the lineup-value input), as --lineups would
            ln = D.load(LINEUPS)
            for s in sorted({r['S'] for r in add}):
                if str(s) not in ln:
                    ln[str(s)] = lineups_from_logs(D.skater_logs(s))
                    _LN.pop(s, None)
                    print(f'nhl lineups: {s}', len(ln[str(s)]), 'games', flush=True)
            D.save(LINEUPS, ln)
        except Exception as e:
            print('nhl lineups not extended:', repr(e), file=sys.stderr, flush=True)
    return hist


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
        self.lastst = {}                                         # team -> the goalie who started its last game

    def season(self):
        for p in self.n:
            self.n[p] *= self.carry; self.d[p] *= self.carry
        for t in self.starts:
            for p in self.starts[t]:
                self.starts[t][p] *= 0.3

    def rating(self, p):
        return (self.n[p] + self.k * self.g0) / (self.d[p] + self.k)

    def add(self, t, lines, xga, day, gx=None):
        """gx: {playerId: xG he faced} (MoneyPuck goalie logs: shots with him in net). Without it, his share of the
        team's xG against, which counts empty-net shots the goals-against line doesn't (+.15 a team-game, Nov 2 2026)"""
        tot = sum(l[3] for l in lines) or 1
        gx = gx or {}
        for pid, nm, st, toi, sa, ga in lines:
            sh = toi / tot
            if sh <= 0:
                continue
            x = gx.get(str(pid))
            self.n[pid] += (sh * xga if x is None else x) - ga; self.d[pid] += sh
            self.name[pid] = nm; self.team[pid] = t; self.last[pid] = day
            if st:
                for q in self.starts[t]:
                    self.starts[t][q] *= 0.97
                self.starts[t][pid] += 1
                self.lastst[t] = pid

    def starter(self, lines):
        st = [l for l in lines if l[2]]
        return (st or sorted(lines, key=lambda l: -l[3]) or [[None]])[0][0]

    def depth(self, t):
        """the team's goalies by recent starts (decayed), only those whose last game was for this team"""
        s = self.starts.get(t, {})
        return sorted([p for p in s if self.team.get(p) == t and s[p] > 0.05], key=lambda p: -s[p])

    def pstart(self, t, b2b=False, out=()):
        """each goalie's chance to start the team's next game from what is known before it (no starter news): recent
        start shares, the last game's starter x e^GK_LAST, x e^GK_B2B more on the second night of a back-to-back
        (multinomial fit on 2016-23 starts: held 2024-26 log loss .774 -> .736 a team-game). out: goalies ruled out"""
        s = self.starts.get(t, {})
        ps = [p for p in self.depth(t) if p not in out][:3]
        w = [s[p] * math.exp((GK_LAST + (GK_B2B if b2b else 0.0)) * (p == self.lastst.get(t))) for p in ps]
        W = sum(w)
        return [(p, x / W) for p, x in zip(ps, w)] if W else []

    def projected(self, t, b2b=False, out=()):
        """(rating, chance the usual starter starts): the team's goalie rating over pstart (g0 with no goalies)"""
        pr = self.pstart(t, b2b, out)
        if not pr:
            return self.g0, 1.0
        d = self.depth(t)
        return sum(q * self.rating(p) for p, q in pr), sum(q for p, q in pr if d and p == d[0])

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


_WF = {}
NESTED = os.path.join(HERE, 'data', 'nhl_hpm_nested.json.gz')
_NEST = []


def _nested():
    """past seasons' skaters with HPM on the weights known when each season ended (scripts/nhl_players.py nested())"""
    if not _NEST:
        try:
            _NEST.append(D.load(NESTED))
        except OSError:
            _NEST.append({})
    return _NEST[0]


def _war_file(S):
    """the WAR run's season S skaters by id, and its replacement levels; (None, None) without the file. A season in
    the nested store is read from there: its HPM carries weights fit on the seasons up to it, so a past game's
    lineup value never sees later seasons (the season files are all on the latest fit)"""
    if S not in _WF:
        n = _nested().get(str(S))
        if n:
            _WF[S] = ({i: dict(zip(('grp', 'age', 'gp', 'toi', 'hpm', 'go', 'gd'), v), id=i) for i, v in n['p'].items()},
                      n['repl'])
            return _WF[S]
        try:
            d = json.load(open(os.path.join(WARD, f'{S}.json')))
            _WF[S] = ({p['id']: p for p in d['players'] if p['grp'] in ('F', 'D')}, d['repl'])
        except OSError:
            _WF[S] = (None, None)
    return _WF[S]


AGE0, AGE_LO, AGE_HI = 27, 18, 36


def age_line(S):
    """(intercept, slope) moving a returning skater's projected HPM by his age: TOI-weighted fit of season s's rate
    (go + gd a 60) minus the s-1 file's HPM on age (as listed in the s-1 file, clipped 18-36, centred at 27), seasons
    2010..S-1 only, net of the overall mean so the average skater keeps his value"""
    X, y, w = [], [], []
    for s in range(2010, S):
        a, b = _war_file(s)[0], _war_file(s - 1)[0]
        if not a or not b:
            continue
        for i, p in a.items():
            q = b.get(i)
            if q and p['toi'] >= 60:
                X.append(min(max(q['age'] or AGE0, AGE_LO), AGE_HI) - AGE0)
                y.append((p['go'] + p['gd']) / p['toi'] * 60 - q['hpm'])
                w.append(p['toi'])
    if len(y) < 500:
        return 0.0, 0.0
    X, y, w = np.array(X), np.array(y), np.array(w, float)
    A = np.column_stack([np.ones(len(X)), X])
    b = np.linalg.solve(A.T @ (A * w[:, None]) + 1e-6 * np.eye(2), A.T @ (w * y))
    return float(b[0] - np.average(y, weights=w)), float(b[1])


def _war(S):
    """season S's lineup pricing from the WAR run's season S-1 file: projected HPM (goals a 60 over average) moved
    by the age line, usual ice time a game, replacement HPM for newcomers"""
    if S not in _LV:
        f, repl = _war_file(S - 1)
        if f is None:
            _LV[S] = None
            return None
        a0, a1 = age_line(S)
        ps = {i: dict(p, hpm=p['hpm'] + a0 + a1 * (min(max(p['age'] or AGE0, AGE_LO), AGE_HI) - AGE0))
              for i, p in f.items()}
        reg = [p for p in ps.values() if p['gp'] >= 20]
        avg = {g: sum(p['toi'] * 60 / p['gp'] for p in reg if p['grp'] == g) / max(1, sum(p['grp'] == g for p in reg))
               for g in ('F', 'D')}
        _LV[S] = (ps, repl, avg)
    return _LV[S]


def lineup_value(S, gid, t):
    """goals a 60 the team's dressed skaters add at their projected rates and usual ice time; None without data"""
    return ids_value(S, _lineups(S).get(str(gid), {}).get(t))


def skater_value(S, x):
    """one skater's goals a 60 at his projected rate and usual ice time ('<player id><F|D>'); None without data"""
    w = _war(S)
    if w is None:
        return None
    ps, repl, avg = w
    p, g = ps.get(x[:-1]), x[-1]
    if p:
        return p['hpm'] * min(p['toi'] * 60 / p['gp'] if p['gp'] else avg[g], 1800) / 3600
    return repl.get(g, 0.0) * avg[g] / 3600          # newcomer: replacement level at his position's usual ice time


def ids_value(S, ids):
    if not ids or _war(S) is None:
        return None
    return sum(skater_value(S, x) for x in ids)


def moved_lineup(S, ids, dep, arr):
    """the last lineup after moves (Nov 1 2026): skaters now with another club out, skaters acquired since in, the
    same count of forwards and defencemen (the lowest-valued scratched for an arrival, a replacement-level call-up
    for a departure without one)"""
    keep = [x for x in ids if x[:-1] not in dep]
    keep += [x for x in arr if x not in keep]
    out = []
    for g in ('F', 'D'):
        n = sum(1 for x in ids if x[-1] == g)
        mine = sorted([x for x in keep if x[-1] == g], key=lambda x: -(skater_value(S, x) or 0.0))[:n]
        out += mine + [f'repl{i}{g}' for i in range(n - len(mine))]
    return out


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
        self.ln = {}                                             # team -> its last lineup ('<id><F|D>'), this season
        self.moves = None    # (S, team, game) -> (ids gone to another club, ids acquired since): trades, claims
        self.W = defaultdict(int); self.L = defaultdict(int); self.OTL = defaultdict(int)
        self.RW = defaultdict(int)                               # regulation wins: the first standings tiebreak

    def advance(self, day, S):
        if self.S is not None and S != self.S:
            for e in (self.xg, self.gl, self.x5, self.st, self.mk, self.elo, self.gk):
                e.season()
            self.W.clear(); self.L.clear(); self.OTL.clear(); self.RW.clear(); self.lv.clear(); self.ln.clear()
        if self.day is not None and day > self.day:
            n = _days(self.day, day)
            for e in (self.xg, self.gl, self.x5, self.st, self.mk):
                e.step(n)
        self.day, self.S = day, S

    def rest(self, t, day):
        if t not in self.lastday:
            return 3
        return max(0, min(3, _days(self.lastday[t], day) - 1))

    def feats(self, g, gh=None, ga=None, home=1.0, out=None):
        """inputs for game g; gh, ga: tonight's named starting goalies (Daily Faceoff, live only). Without a name (every
        history game: who started isn't known at bet time) the side takes its start-chance-weighted rating
        (Goalies.projected). out: {team: goalie ids ruled out} (live injuries)"""
        h, a = g['h'], g['a']
        rh, ra = self.rest(h, g['day']), self.rest(a, g['day'])
        out = out or {}

        def side(t, p, r):
            d = self.gk.depth(t)
            if p:
                return self.gk.rating(p), int(bool(d) and p != d[0])
            v, p0 = self.gk.projected(t, r == 0, out.get(t, ()))
            return v, 1.0 - p0
        rgh, bkh = side(h, gh, rh)
        rga, bka = side(a, ga, ra)
        rv = self.lv_now(h, g) - self.lv_now(a, g) if h in self.lv and a in self.lv else 0.0
        f = {'elo': (self.elo.r[h] - self.elo.r[a]) / 100, 'xg': self.xg.net(h, a), 'g': self.gl.net(h, a),
             'x5': self.x5.net(h, a), 'st': self.st.net(h, a), 'mkt': self.mk.rating(h) - self.mk.rating(a),
             'gk': rgh - rga, 'gkd': (rgh - self.gk.expected(h)) - (rga - self.gk.expected(a)),
             'bk': bka - bkh, 'rv': rv, 'rest': rh - ra, 'b2b': int(rh == 0) - int(ra == 0), 'home': home,
             'xgT': self.xg.total(h, a, home), 'gT': self.gl.total(h, a, home), 'mtot': self.mk.total(h, a),
             'gkT': -(rgh + rga), 'one': 1.0, 'rgh': rgh, 'rga': rga}
        return f

    def lv_now(self, t, g=None):
        """the team's last lineup's value, after any moves since (self.moves)"""
        if self.moves is None or t not in self.ln:
            return self.lv[t]
        dep, arr = self.moves(self.S, t, g, self.ln[t])
        if not dep and not arr:
            return self.lv[t]
        v = ids_value(self.S, moved_lineup(self.S, self.ln[t], dep, arr))
        return self.lv[t] if v is None else v

    def lineup(self, t):
        """the team's last lineup value against the league's average one (0 before it has played)"""
        if t not in self.lv:
            return 0.0
        return self.lv_now(t) - sum(self.lv_now(u) for u in self.lv) / len(self.lv)

    def update(self, g):
        h, a = g['h'], g['a']
        if g.get('hs') is None:
            return
        self.elo.add(h, a, g['hs'], g['as'])
        x = g.get('x')
        if x:
            xh, xa = x['h'], x['a']
            # the xG rating: all situations, power-play xG weighted by ppw (1 = as counted; scripts/nhl_ppw_research.py)
            w = 1.0 - self.P.get('ppw', 1.0)
            self.xg.add(h, a, xh[0] - w * xh[5], xa[0] - w * xa[5])
            self.gl.add(h, a, xh[2], xa[2])
            self.x5.add(h, a, xh[3], xa[3])
            # special teams: power-play xG for and penalty-kill xG against, per 60 of each
            pph = xh[5] / max(xh[7], 1) * 60 if xh[7] > 1 else None
            ppa = xa[5] / max(xa[7], 1) * 60 if xa[7] > 1 else None
            if pph is not None and ppa is not None:
                self.st.add(h, a, pph, ppa)
            if 'gl' in g:
                gx = g.get('gx') or {}
                self.gk.add(h, g['gl']['h'], xa[1], g['day'], gx.get('h'))
                self.gk.add(a, g['gl']['a'], xh[1], g['day'], gx.get('a'))
        c = g.get('c')
        if c:
            self.mk.add(h, a, c.get('p'), c.get('t'))
        self.lastday[h] = self.lastday[a] = g['day']
        for t in (h, a):
            v = lineup_value(g['S'], g['id'], t)
            if v is not None:
                self.lv[t] = v
                self.ln[t] = _lineups(g['S']).get(str(g['id']), {}).get(t)
        hw = g['hs'] > g['as']
        ot = (g.get('per') or 3) > 3
        if not g.get('po'):
            w, l = (h, a) if hw else (a, h)
            self.W[w] += 1
            if not ot:
                self.RW[w] += 1
            (self.OTL if ot else self.L)[l] += 1


DEP_DAYS = 3


def hist_moves(games):
    """the backtest's moves (Nov 1 2026): for club t's game, skaters in its last lineup who don't dress and next
    dress for another club (gone), and skaters who dress for it whose previous game was for another club (acquired).
    Built from the frozen lineups; the trade itself is known before the game, the dressed list a little later, so
    this is a hair kinder than live, which reads the clubs' rosters"""
    day = {str(g['id']): g['day'] for g in games}
    seq = defaultdict(list)                    # (S, pid) -> [(day, gid, team)]
    for S in sorted({g['S'] for g in games}):
        for gid, by in _lineups(S).items():
            if gid not in day:
                continue
            for t, ids in by.items():
                for x in ids:
                    seq[(S, x[:-1])].append((day[gid], gid, t, x))
    for v in seq.values():
        v.sort()
    idx = {k: {gid: i for i, (_, gid, _, _) in enumerate(v)} for k, v in seq.items()}

    def moves(S, t, g, last=None):
        if g is None:
            return set(), []
        gid = str(g['id'])
        now = set(x[:-1] for x in _lineups(S).get(gid, {}).get(t, []))
        dep = set()
        for x in (last or []):
            p = x[:-1]
            if p in now:
                continue
            v = seq.get((S, p), [])
            nxt = [e for e in v if e[0] >= g['day'] and e[1] != gid]
            # gone only if he dresses for the new club within DEP_DAYS: a scratched or injured skater traded weeks
            # later was still on the roster on game day (Nov 4 2026 audit: 370 of 1,150 cases were 10+ days early;
            # walk-forward log loss held 2024-26 .66784 -> .66781, tune 2021-23 .65150 -> .65147)
            if nxt and nxt[0][2] != t and _days(g['day'], nxt[0][0]) <= DEP_DAYS:
                dep.add(p)
        arr = []
        for x in _lineups(S).get(gid, {}).get(t, []):
            k = (S, x[:-1]); i = idx.get(k, {}).get(gid)
            if i and seq[k][i - 1][2] != t:
                arr.append(x)
        return dep, arr
    return moves


def live_moves(S, games):
    """this season's moves for the board: every club's NHL roster now (api-web), against the lineups dressed so far.
    Gone: a skater in the club's last lineup who is on another club's roster now. Acquired: a skater on the club's
    roster whose last game this season, in the last 30 days, was for another club"""
    now = {}
    for t in TEAMS:
        j = D.get(f'{D.WEB}/roster/{t}/current') or {}
        for grp, gc in (('forwards', 'F'), ('defensemen', 'D')):
            for p in j.get(grp) or []:
                now[str(p['id'])] = (t, gc)
    if len(now) < 500:
        raise RuntimeError(f'rosters: {len(now)} skaters')
    day = {str(g['id']): g['day'] for g in games if g['S'] == S}
    last = {}
    for gid, by in _lineups(S).items():
        d = day.get(gid)
        if d is None:
            continue
        for t, ids in by.items():
            for x in ids:
                if x[:-1] not in last or d >= last[x[:-1]][0]:
                    last[x[:-1]] = (d, t, x)
    cut = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    arr = defaultdict(list)
    for p, (d, t0, x) in last.items():
        if p in now and now[p][0] != t0 and d >= cut:
            arr[now[p][0]].append(p + now[p][1])
    n = sum(len(v) for v in arr.values())
    print('nhl moves: skaters on a new club since their last game', n, flush=True)

    def moves(S_, t, g, ln=None):
        dep = {x[:-1] for x in (ln or []) if x[:-1] in now and now[x[:-1]][0] != t}
        return dep, arr.get(t, [])
    return moves


def walk(games, P, upcoming=(), starters=None, moves=None, up_moves=None):
    """every final game's pre-game inputs, in order; then upcoming games' inputs from the final state. moves: the
    backtest's hist_moves callable for every game; up_moves: live_moves, for the upcoming games only (None: the
    last lineup as dressed)"""
    m = Model(P)
    m.moves = moves
    rows = []
    for g in games:
        m.advance(g['day'], g['S'])
        if g['S'] >= SCORE_FROM and g.get('hs') is not None:
            f = m.feats(g)
            rows.append((g, f))
        m.update(g)
    up = []
    if up_moves is not None:
        m.moves = up_moves
    last0 = dict(m.lastday)
    for g in upcoming:
        m.advance(g['day'], g['S'])
        st = (starters or {}).get(g['id'], {})
        g = dict(g, rest={'home': m.rest(g['h'], g['day']), 'away': m.rest(g['a'], g['day'])})
        up.append((g, m.feats(g, st.get('h'), st.get('a'), 0.0 if g.get('neutral') else 1.0, st.get('out'))))
        m.lastday[g['h']] = m.lastday[g['a']] = g['day']    # tomorrow's rest counts tonight's unplayed game
    m.lastday = last0
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
    m, rows, _ = walk(hist, P, moves=hist_moves(hist))     # lineups after trades (Nov 1 2026)
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
    # the season sims' winner given overtime: regular-season OT games, home win on the walk-forward model logit
    po_ = np.array([g['po'] for g, f in rows], bool)
    om = (per == 1) & ~po_ & ~np.isnan(p)
    zo = np.log(p[om] / (1 - p[om]))
    cow = logit_fit(np.column_stack([np.ones(om.sum()), zo]), y[om])
    sd0 = season_sd(rows, cw, feats)
    held = S >= HOLD_FROM
    fitd = {'updated': dt.date.today().isoformat(), 'params': P, 'feats': feats, 'tfeats': TFEATS,
            'coef': {k: round(float(v), 4) for k, v in zip(feats, cw)},
            'mcoef': {k: round(float(v), 4) for k, v in zip(feats, mw)},
            'tcoef': {k: round(float(v), 4) for k, v in zip(TFEATS, tw)},
            'pl': {'home2': [round(float(v), 4) for v in c2h], 'away2': [round(float(v), 4) for v in c2a]},
            'ot': [round(float(v), 4) for v in cot], 'otWin': [round(float(v), 4) for v in cow], 'otWinGames': int(om.sum()),
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


def roster_goalies(t, _c={}):
    """the club's goalies on its NHL roster now (api-web roster): [{'name', 'pid', 'team'}]; a call-up the model has
    never seen in net is found here"""
    if t not in _c:
        r = D.get(f'https://api-web.nhle.com/v1/roster/{t}/current') or {}
        _c[t] = [{'name': f"{(g.get('firstName') or {}).get('default', '')} {(g.get('lastName') or {}).get('default', '')}".strip(),
                  'pid': g.get('id'), 'team': t} for g in r.get('goalies') or [] if g.get('id')]
    return _c[t]


def out_names(inj, t):
    """name keys of the team's goalies on ESPN's injury list (any status but day-to-day)"""
    return {NM.key(i['name']) for i in (inj or {}).get(t, []) if 'day' not in (i.get('status') or '').lower()}


def out_ids(m, t, inj):
    """the team's rated goalies on ESPN's injury list (out_names), by id"""
    out = out_names(inj, t)
    return {p for p in m.gk.depth(t) if NM.key(m.gk.name.get(p) or '') in out}


def pick_starter(m, t, df, day, inj=None):
    """tonight's goalie: Daily Faceoff's (confirmed or likely) matched to the goalies the model has rated, else to the
    club's NHL roster (a call-up with no NHL games rates as a new goalie, not as the usual starter); with no Daily
    Faceoff name, the team's usual healthy starter, or his partner on the second night of a back-to-back"""
    if df and df[0]:
        pool = [{'name': nm, 'pid': p, 'team': m.gk.team.get(p)} for p, nm in m.gk.name.items()]
        hit, _ = NM.Matcher(pool, pos=None).find(df[0], team=t, cross_team='variant')
        if hit is None:
            hit, _ = NM.Matcher(roster_goalies(t), pos=None).find(df[0], team=t, cross_team='none')
            if hit is not None:
                m.gk.name.setdefault(hit['pid'], hit['name'])
        if hit is not None:
            return hit['pid'], (df[1] or 'listed').lower()
        print(f'nhl goalie: no match for {df[0]} ({t})', file=sys.stderr)
    out = out_names(inj, t)
    depth = [p for p in m.gk.depth(t) if NM.key(m.gk.name.get(p) or '') not in out]
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


def win_given_ot(ph, z, pot, ot, ow):
    """the home side's chance given whether the game goes to overtime: overtime and shootouts are nearer a coin flip
    (fit['otWin']: logit P(home wins | OT) = a + b x model logit, b ~ .36), regulation takes the rest so the chance
    over both stays ph. Without it, the same chance either way (favourites then won 59% of sim OTs, 53% real).
    Works on floats or numpy arrays"""
    if not ow:
        return ph
    if isinstance(ot, np.ndarray):
        po = 1 / (1 + np.exp(-(ow[0] + ow[1] * z)))
        return np.where(ot, po, np.clip((ph - pot * po) / np.maximum(1 - pot, 1e-6), 0.005, 0.995))
    po = 1 / (1 + math.exp(-(ow[0] + ow[1] * z)))
    return po if ot else min(0.995, max(0.005, (ph - pot * po) / max(1 - pot, 1e-6)))


def conf_seeds(order, cf):
    """a conference's eight seeds by the standings order: [A1, A2, A3, B1, B2, B3, WC1, WC2], A = the better division
    winner's division (the tally's slots)"""
    ds = CONF[cf]
    tops = {d: sorted(DIV[d], key=lambda t: -order[t])[:3] for d in ds}
    rest_ = sorted([t for d in ds for t in DIV[d] if t not in tops[d]], key=lambda t: -order[t])
    da, db = sorted(ds, key=lambda d: -order[tops[d][0]])
    return tops[da] + tops[db] + rest_[:2]


def conf_sides(sd):
    """the first round from the eight seeds, by bracket side: the better division winner meets the second wild card"""
    return [[(sd[0], sd[7]), (sd[1], sd[2])], [(sd[3], sd[6]), (sd[4], sd[5])]]


def series_state(games):
    """the playoffs so far from the season's playoff rows (scheduled ones included): {frozenset((a, b)): {'hi': the
    game-1 home side (home ice: games 1, 2, 5, 7), 'w': {team: wins}, 'rd': round from the game id (season, 03, 0,
    round, series, game), 'won': the side with four wins or None}}. Two teams meet once a postseason"""
    st = {}
    for g in sorted((g for g in games if g.get('po')), key=lambda g: (g.get('t') or g.get('start') or g['day'], g['id'])):
        s = st.setdefault(frozenset((g['h'], g['a'])), {'hi': g['h'], 'w': {g['h']: 0, g['a']: 0}, 'won': None,
                                                         'rd': (int(g['id']) // 100) % 10 or None})
        if g.get('final') and g.get('hs') is not None and g.get('as') is not None and g['hs'] != g['as']:
            s['w'][g['h'] if g['hs'] > g['as'] else g['a']] += 1
    for s in st.values():
        s['won'] = next((t for t, v in s['w'].items() if v >= 4), None)
    return st


def actual_seeds(st, order):
    """{conference: the eight seeds} from the real first-round pairs, for each conference whose four are set: a pair's
    side is the division of its home-ice team; in a side the division winner's pair is the one with the better team by
    the standings, the other is 2 v 3 (home ice = 2); the better division winner's opponent is the second wild card"""
    out = {}
    for cf, ds in CONF.items():
        ps = [s for s in st.values() if s['rd'] == 1 and CONF_OF.get(s['hi']) == cf]
        side = {d: [s for s in ps if DIV_OF[s['hi']] == d] for d in ds}
        if len(ps) != 4 or any(len(v) != 2 for v in side.values()):
            continue
        lo = lambda s: next(t for t in s['w'] if t != s['hi'])
        top = {d: sorted(v, key=lambda s: -order[s['hi']]) for d, v in side.items()}
        da, db = sorted(ds, key=lambda d: -order[top[d][0]['hi']])
        A, B = top[da], top[db]
        out[cf] = [A[0]['hi'], A[1]['hi'], lo(A[1]), B[0]['hi'], B[1]['hi'], lo(B[1]), lo(B[0]), lo(A[0])]
    return out


def standings_tb(reg):
    """the NHL's tiebreaks after points and regulation wins, from the season's final regular-season games: regulation
    plus overtime wins, wins, goal differential, goals for; -> {team: rank / 32 in [0, 1)}, used once no games are left"""
    k = {t: [0, 0, 0, 0] for t in TEAMS}
    for g in reg:
        if not g.get('final') or g.get('hs') is None or g['hs'] == g['as'] or g['h'] not in k or g['a'] not in k:
            continue
        w, l = (g['h'], g['a']) if g['hs'] > g['as'] else (g['a'], g['h'])
        k[w][1] += 1
        if (g.get('per') or 3) < 5:
            k[w][0] += 1
        for t, f, a in ((g['h'], g['hs'], g['as']), (g['a'], g['as'], g['hs'])):
            k[t][2] += f - a; k[t][3] += f
    rk = sorted(TEAMS, key=lambda t: k[t])
    return {t: i / NT for i, t in enumerate(rk)}


def simulate(m, fit, remaining, pts, sims=10000, share=1.0, seed=11, rw=None, tally=None, ps=None, tb=None,
             base=None, knobs=None):
    """rest of the regular season, then the playoffs (division top three + two wild cards a conference; 2-2-1-1-1).
    rw: regulation wins so far; points ties break on regulation wins (the NHL's first tiebreak), then tb (standings_tb,
    once the regular season is over), then at random.
    ps: series_state() of the real playoffs: a decided series keeps its winner, one under way is played on from its
    game count with its own home ice; once a conference's first round is set its seeds are the real ones.
    tally: a bracket.Tally over the conferences' eight slots (the better division winner, its division's 2 and 3, the
    other winner, its 2 and 3, wild cards 1 and 2), filled in place. base / knobs: team logits and (shrink, sd) in
    place of the model's (the --test cases)"""
    rw = rw or {}
    ps = ps or {}
    tb = tb or {}
    rng = random.Random(seed)
    c = fit['coef']
    base = dict(base) if base is not None else {t: team_logit(m, fit, t)[1] for t in TEAMS}
    # how sure the sims are, tuned on the season outcomes themselves (scripts/nhl_sim_backtest.py, walk-forward
    # Brier of playoffs, division and Cup from checkpoints 2017-26): logits pulled toward the mean by shrink x share
    # of the season left, and a season-level rating error sd x sqrt(share left)
    a, sd = knobs if knobs is not None else sim_knobs(fit)
    mz = sum(base.values()) / len(base)
    base = {t: mz + (1 - a * share) * (z - mz) for t, z in base.items()}
    sd = sd * math.sqrt(max(share, 0.04))
    hc = c.get('home', 0.0)
    otc = fit['ot']
    cnt = {t: defaultdict(float) for t in TEAMS}
    pts_sum = defaultdict(float)
    lot = defaultdict(lambda: defaultdict(float))
    order0 = {t: pts[t] + rw.get(t, 0) / 1000 + tb.get(t, 0.0) * 1e-4 for t in TEAMS}
    real = actual_seeds(ps, order0) if ps else {}      # a set first round means the regular season is over
    for _ in range(sims):
        R = {t: base[t] + rng.gauss(0, sd) for t in TEAMS}
        P = dict(pts)
        RW = {t: rw.get(t, 0) for t in TEAMS}
        for g in remaining:
            z = R[g['h']] - R[g['a']] + hc * (0.0 if g.get('neutral') else 1.0)
            ph = 1 / (1 + math.exp(-z))
            mm = z * 1.6
            pot = 1 / (1 + math.exp(-(otc[0] + otc[1] * mm * mm + otc[2] * 6.0)))
            ot = rng.random() < pot
            hw = rng.random() < win_given_ot(ph, z, pot, ot, fit.get('otWin'))
            w, l = (g['h'], g['a']) if hw else (g['a'], g['h'])
            P[w] += 2
            if ot:
                P[l] += 1
            else:
                RW[w] += 1
        for t in TEAMS:
            pts_sum[t] += P[t]
        order = {t: P[t] + RW[t] / 1000 + tb.get(t, 0.0) * 1e-4 + rng.random() * 1e-7 for t in TEAMS}
        po = []
        bracket = {}
        for cf in CONF:
            sl = real.get(cf) or conf_seeds(order, cf)
            bracket[cf] = conf_sides(sl)
            if tally is not None:
                tally.seeds(cf, sl)
                for t in sl:
                    tally.reached(t, 'playoff')
            po += sl
            cnt[sl[0]]['divw'] += 1
            cnt[sl[3]]['divw'] += 1
        for t in po:
            cnt[t]['playoff'] += 1
        pres = max(TEAMS, key=lambda t: order[t])
        cnt[pres]['pres'] += 1

        def series(a, b):
            s = ps.get(frozenset((a, b)))
            if s and s['won']:
                return s['won']
            if s:                                        # under way: its own home ice and games so far
                hi = s['hi']
                lo = b if hi == a else a
                w = {hi: s['w'][hi], lo: s['w'][lo]}
            else:
                hi, lo = (a, b) if order[a] >= order[b] else (b, a)
                w = {hi: 0, lo: 0}
            for k in range(w[hi] + w[lo], 7):
                home = hi if k in (0, 1, 4, 6) else lo
                away = lo if home == hi else hi
                z = R[home] - R[away] + hc
                win = home if rng.random() < 1 / (1 + math.exp(-z)) else away
                w[win] += 1
                if w[win] == 4:
                    return win
            return hi
        champs = {}
        if tally is not None:
            tally.season()
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


def nhl_bracket(BK, tal, sims, ps=None):
    """data/brackets/nhl.json: slot odds per conference (the better division winner v the second wild card, the other
    winner v the first, 2 v 3 in each division; fixed bracket) and the projected bracket. ps (series_state): a series
    with a game played carries each side's wins ('g'), a decided one 'done': 1 and its real winner"""
    import datetime
    proj, _, sd = tal.project()
    odds = {t: {k: sims[t].get(k, 0.0) for k in ('playoff', 'r2', 'cf', 'final', 'cup', 'divw')} for t in sims}
    secs, champ = [], {}
    ps = ps or {}

    def game(a, b, *x):                      # BK.game with the real series marked
        gm = BK.game(a, b, *x)
        s = ps.get(frozenset((a, b))) if a and b else None
        if s and sum(s['w'].values()):
            gm['a']['g'], gm['b']['g'] = s['w'][a], s['w'][b]
            if s['won']:
                gm['w'], gm['done'] = s['won'], 1
        return gm
    # slots: A = the better division winner's division, B the other; shown in the bracket by the team's division (M1, A2)
    labels = ['A1', 'A2', 'A3', 'B1', 'B2', 'B3', 'WC1', 'WC2']
    for cf in CONF:
        sl = [r['t'] for r in proj[cf]]
        seed = {t: (DIV_OF[t][0] + labels[i][1] if i < 6 else labels[i]) for i, t in enumerate(sl)}
        r1 = [game(sl[0], sl[7], seed, odds, 'playoff', 'r2'), game(sl[1], sl[2], seed, odds, 'playoff', 'r2'),
              game(sl[3], sl[6], seed, odds, 'playoff', 'r2'), game(sl[4], sl[5], seed, odds, 'playoff', 'r2')]
        r2 = [game(r1[0]['w'], r1[1]['w'], seed, odds, 'r2', 'cf'), game(r1[2]['w'], r1[3]['w'], seed, odds, 'r2', 'cf')]
        cg = game(r2[0]['w'], r2[1]['w'], seed, odds, 'cf', 'final')
        champ[cf] = cg['w']
        secs.append({'name': cf, 'rounds': [{'name': 'First round', 'games': r1}, {'name': 'Second round', 'games': r2},
                                           {'name': 'Conf final', 'games': [cg]}]})
    cfs = list(CONF)
    fg = game(champ[cfs[0]], champ[cfs[1]], {}, odds, 'final', 'cup')
    secs.append({'name': 'Stanley Cup Final', 'rounds': [{'name': 'Final', 'games': [fg]}], 'champ': {'t': fg['w'], 'p': odds[fg['w']]['cup']}})
    for g in tal.groups:
        for i, r in enumerate(proj[g]):
            r['lab'] = labels[i]
            if r['t'] and i < 6:
                r['div'] = DIV_OF[r['t']]
    pay = BK.payload(datetime.date.today().isoformat(), tal.n, tal, proj, odds, sd, secs,
                     [['playoff', 'Playoff'], ['r2', 'Round 2'], ['cf', 'Conf final'], ['final', 'Final'], ['cup', 'Cup']],
                     {t: {'n': t, 'a': t, 'logo': f'/img/nhl/{t.lower()}.png'} for t in sims}, labels=labels)
    BK.save('nhl', pay)


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
            ts = 0.0
            try:
                ts = dt.datetime.fromisoformat((i.get('date') or '').replace('Z', '+00:00')).timestamp()
            except ValueError:
                pass
            out.setdefault(tm, []).append({'name': nm, 'status': i.get('status') or '', 'war': war, 'ts': ts, 'p': p})
    # RotoWire's injury news (scripts/rotowire.py), the last 3 days: newer than ESPN's entry, its status stands
    # (Active takes him off); a player ESPN doesn't list is added
    try:
        import rotowire as RW
        RW.refresh('hockey')
        st_map = {'Out (season)': 'Out', 'Out': 'Out', 'Doubtful': 'Doubtful', 'Questionable': 'Day-To-Day',
                  'Probable': 'Day-To-Day', 'Active': 'Active'}
        for it in RW.items('hockey', since=time.time() - 3 * 86400):
            st = st_map.get(RW.item_status(it)) or ('Injured Reserve' if re.search(r'\b(ir|injured reserve)\b', it['head'].lower()) else None)
            tm = D.team(it['abbr'])
            if not st or tm not in TEAMS:
                continue
            p, _ = M.find(it['player'], team=tm)
            lst = out.setdefault(tm, [])
            cur = next((r for r in lst if NM.same(r['name'], it['player'])), None)
            if cur and cur['ts'] >= it['ts']:
                continue
            if cur:
                lst.remove(cur)
            if st != 'Active':
                war = round(82 * p['num'] / p['gp'], 1) if p and p['gp'] >= 5 else None
                lst.append({'name': it['player'], 'status': st, 'war': war, 'ts': it['ts'], 'p': p})
        # out for weeks or the season by his RotoWire injury card (scripts/rotowire_history.py), when no one lists him
        for v in RW.long_term('hockey'):
            tm = D.team(v['abbr'])
            if tm not in TEAMS or any(NM.same(r['name'], v['player']) for r in out.get(tm, [])):
                continue
            p, _ = M.find(v['player'], team=tm)
            war = round(82 * p['num'] / p['gp'], 1) if p and p['gp'] >= 5 else None
            c = (v['status'] or '').upper()
            st = 'Out (season)' if v['season'] else 'LTIR' if 'LTIR' in c else 'Injured Reserve' if c.startswith('IR') else 'Out'
            out.setdefault(tm, []).append({'name': v['player'], 'status': st, 'war': war, 'ts': 0, 'p': p})
    except Exception as e:  # noqa: BLE001
        print('nhl games: RotoWire news unavailable:', e)
    for v in out.values():
        for r in v:
            r.pop('ts', None); r.pop('p', None)
        v.sort(key=lambda r: -(r['war'] if r['war'] is not None else -9))
    return out


def build():
    fit = json.load(open(FIT))
    P = fit['params']
    S = D.current_season()
    hist = ensure_hist(load_hist(), S)       # the season just finished, after the Aug 1 rollover
    mp = D.moneypuck_teams()
    cur = season_rows(S, mp, fresh=True)
    try:   # this season's dressed lineups (the lineup-value input)
        set_lineups(S, lineups_from_logs(D.skater_logs(S, fresh=True)))
    except Exception as e:
        print('lineups:', e, file=sys.stderr)
    today = dt.datetime.now(ZoneInfo('America/New_York')).date()      # the NHL's slate day (was fixed UTC-5: an hour behind in EDT)
    finals = [g for g in cur if g['final'] and g['hs'] is not None]
    # the next two dates with games, from the NHL's schedule (start times, neutral sites, live state)
    sched = D.schedule(today.isoformat())
    days = sorted({g['day'] for g in sched if g['day'] >= today.isoformat()})[:2]
    up = [dict(g, S=S, po=int(g['type'] == 3)) for g in sched if g['day'] in days]
    done_ids = {g['id'] for g in finals}
    m0, _, _ = walk(hist + finals, P)
    try:
        inj = injuries()
    except Exception as e:
        print('injuries:', e, file=sys.stderr); inj = {}
    starters, gsrc, shown = {}, {}, {}
    for d in days:
        df = starters_df(d)
        for g in up:
            if g['day'] != d:
                continue
            s = df.get((g['h'], g['a']), {})
            gh, sh = pick_starter(m0, g['h'], s.get('h'), d, inj)
            ga, sa = pick_starter(m0, g['a'], s.get('a'), d, inj)
            shown[g['id']] = {'h': gh, 'a': ga}
            # the model takes a goalie only when Daily Faceoff names him; a projected side is priced at its start
            # chances (Goalies.pstart), as every history game is
            named = lambda x, src: x if not src.startswith('projected') and src != 'unknown' else None
            starters[g['id']] = {'h': named(gh, sh), 'a': named(ga, sa), 'out': {t: out_ids(m0, t, inj) for t in (g['h'], g['a'])}}
            gsrc[g['id']] = {'h': sh, 'a': sa}
        for g in up:          # the second date's back-to-backs: tonight's games aren't final yet
            if g['day'] == d:
                m0.lastday[g['h']] = m0.lastday[g['a']] = d
    pending = [g for g in up if g['id'] not in done_ids]
    try:   # trades and claims since each club's last game (its NHL roster now)
        mv = live_moves(S, finals)
    except Exception as e:
        print('nhl moves:', e, file=sys.stderr); mv = None
    m, _, ups = walk(hist + finals, P, pending, starters, up_moves=mv)
    # market lines for the board (ESPN's current consensus)
    emap = D.espn_map([{'id': g['id'], 'day': g['day'], 'h': g['h'], 'a': g['a']} for g in up], fresh_after=today - dt.timedelta(days=1))
    # Polymarket US's main lines after its fee first (Novig only where Polymarket has no game); ESPN's DraftKings for the rest
    try:
        import polymarket
        NV = polymarket.book('nhl')
    except Exception as e:
        print('polymarket:', e); NV = {}
    games = []
    for g, f in ups:
        p, mm, T, p2h, p2a, pot = project(f, fit)
        lh = (T + mm) / 2; la = (T - mm) / 2
        st = shown.get(g['id'], {})
        eid = emap.get(g['id'])
        c = consensus(D.espn_odds(eid, fresh=True)) if eid else None
        px = NV.get(str(eid)) if eid else None
        if px and px.get('mlH') is not None and px.get('mlA') is not None:
            qh, qa = implied(px['mlH']), implied(px['mlA'])
            c = {**(c or {}), 't': px.get('T') if px.get('T') is not None else (c or {}).get('t'), 'ml': [px['mlH'], px['mlA']], 'p': qh / (qh + qa)}
        row = {'id': g['id'], 'espn': eid, 'tip': g['start'], 'day': g['day'], 'home': g['h'], 'away': g['a'],
               'neutral': g.get('neutral', False), 'po': bool(g.get('po')), 'pHome': round(p, 3),
               'margin': round(mm, 2), 'total': round(T, 2), 'hs': round(max(lh, 0.3), 1), 'as': round(max(la, 0.3), 1),
               'pl': {'home2': round(p2h, 3), 'away2': round(p2a, 3)}, 'pOT': round(pot, 3), 'x': [round(mm, 4), round(T, 4)],
               'fair': {'home': american(p), 'away': american(1 - p)},
               'parts': {k: round(fit['coef'][k] * f[k], 3) for k in fit['feats']},
               'elo': {'home': round(m.elo.r[g['h']]), 'away': round(m.elo.r[g['a']])},
               'rest': g['rest'],
               'goalie': {s: {'name': (m.gk.name.get(st.get(s[0])) or m0.gk.name.get(st.get(s[0]))) if st.get(s[0]) else None,
                              'id': st.get(s[0]),
                              'gsax': round(m.gk.rating(st.get(s[0])), 2) if st.get(s[0]) else None,
                              'r': round(f['rg' + s[0]], 4),     # the rating the total used (refresh_goalies swaps from it)
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
    import bracket as BK                  # seed odds and the projected bracket (scripts/bracket.py)
    tal = BK.Tally({cf: 8 for cf in CONF}, ['playoff'])
    ps = series_state(cur)                # the real playoffs so far (decided series fixed, open ones played on)
    sims = simulate(m, fit, left, pts, share=share, rw=dict(m.RW), tally=tal, ps=ps,
                    tb=None if left else standings_tb(reg))
    if ps:
        print('nhl playoffs:', sum(1 for x in ps.values() if x['won']), 'series decided,',
              sum(1 for x in ps.values() if not x['won'] and sum(x['w'].values())), 'under way', flush=True)
    try:
        nhl_bracket(BK, tal, sims, ps)
    except Exception as e:            # the bracket keeps its last file rather than stop the build
        print('nhl bracket failed:', repr(e), flush=True)
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
                      'pres': sims[t].get('pres', 0.0), 'lottery': sims[t]['lottery'],
                      # display only: WAR a full season of the players on the injury list (replacement-level and below count 0)
                      'warOut': round(sum(max(i.get('war') or 0.0, 0.0) for i in inj.get(t, [])), 1)})
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
        try:      # team badges (scripts/team_badges.py): last season's and this season's MoneyPuck lines
            import team_badges_build as TB
            TB.write('nhl', TB.nhl([g for g in hist if g.get('S') == S - 1], finals, S))
        except Exception as e:
            print('team badges failed:', repr(e), file=sys.stderr)
        team_detail.save('nhl', TD)
    except Exception as e:            # the dropdowns keep the last file rather than stop the build
        print('team breakdowns failed:', repr(e), file=sys.stderr)
    rec = {t: f'{m.W[t]}-{m.L[t]}-{m.OTL[t]}' for t in TEAMS}
    out = {'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'days': days, 'games': games, 'rec': rec, 'coef': fit['coef'], 'test': fit['test'], 'calib': fit['calib'],
           'power': power, 'sims': 10000, 'left': len(left), 'seasonSd': fit['seasonSd'],
           'simKnobs': dict(zip(('shrink', 'sd'), sim_knobs(fit))),
           'goalies': goalie_table(m, S),
           # every goalie in net for a current club in the last 400 days: id -> [name, team, rating], for --goalies
           'gkAll': {str(p): [m.gk.name.get(p), m.gk.team.get(p), round(m.gk.rating(p), 4)] for p, d in m.gk.last.items()
                     if m.gk.team.get(p) in TEAMS and _days(d, today.isoformat()) <= 400},
           'gk0': P['gk_0']}
    try:                                       # ARK Ranking movement over the week (scripts/rank_moves.py)
        import rank_moves
        try:
            _old = json.load(open(OUT))
        except (OSError, ValueError):
            _old = None
        rank_moves.apply(out, power, _old, lambda r: r['t'], lambda r: r['rating'], sport='nhl')
    except Exception as e:
        print('rank moves failed:', repr(e), file=sys.stderr)
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


def refresh_goalies():
    """re-read Daily Faceoff for the board's games that haven't started and swap in tonight's goalies without the full
    build (python3 scripts/nhl_games.py --goalies, run every 30 minutes on game days by .github/workflows/nhl-goalies.yml).
    The goalies enter only the total (gkT): T moves by the gkT weight times the change in -(home + away rating), and
    the puck-line and overtime chances follow from the new total; the win chance and margin don't use the goalie."""
    fit = json.load(open(FIT))
    out = json.load(open(OUT))
    tw = fit['tcoef'].get('gkT', 0.0)
    gk0 = out.get('gk0', fit['params']['gk_0'])
    pool = [{'name': v[0], 'pid': int(k), 'team': v[1], 'r': v[2]} for k, v in (out.get('gkAll') or {}).items() if v[0]]
    M = NM.Matcher(pool, pos=None)
    now = dt.datetime.now(dt.timezone.utc)
    dfs, changed = {}, []
    for g in out['games']:
        if g.get('final') or 'x' not in g or dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00')) <= now:
            continue
        if g['day'] not in dfs:
            dfs[g['day']] = starters_df(g['day'])
        s = dfs[g['day']].get((g['home'], g['away']), {})
        dr = 0.0
        for side, k, t in (('home', 'h', g['home']), ('away', 'a', g['away'])):
            df, cur = s.get(k), g['goalie'][side]
            if not df or not df[0]:
                continue
            src = (df[1] or 'listed').lower()
            hit, _ = M.find(df[0], team=t, cross_team='variant')
            if hit is None:
                hit, _ = NM.Matcher(roster_goalies(t), pos=None).find(df[0], team=t, cross_team='none')
                if hit is not None:
                    hit = dict(hit, r=gk0)
            if hit is None:
                print(f'nhl goalie: no match for {df[0]} ({t})', file=sys.stderr)
                continue
            if hit['pid'] == cur.get('id') and src == cur.get('src'):
                continue
            r0 = cur.get('r')
            if r0 is None:
                continue
            dr += hit['r'] - r0
            changed.append(f"{g['day']} {g['away']}@{g['home']} {side}: {cur.get('name')} ({cur.get('src')}) -> {hit['name']} ({src})")
            g['goalie'][side] = {'name': hit['name'], 'id': hit['pid'], 'gsax': round(hit['r'], 2), 'r': round(hit['r'], 4), 'src': src}
        if dr:
            mm, T = g['x'][0], g['x'][1] - tw * dr
            c2h, c2a = fit['pl']['home2'], fit['pl']['away2']
            p2h = float(sig(c2h[0] + c2h[1] * mm + c2h[2] * T)); p2a = float(sig(c2a[0] + c2a[1] * mm + c2a[2] * T))
            pot = float(sig(fit['ot'][0] + fit['ot'][1] * mm * mm + fit['ot'][2] * T))
            lh = (T + mm) / 2; la = (T - mm) / 2
            g.update(x=[mm, round(T, 4)], total=round(T, 2), hs=round(max(lh, 0.3), 1), **{'as': round(max(la, 0.3), 1)},
                     pl={'home2': round(p2h, 3), 'away2': round(p2a, 3)}, pOT=round(pot, 3))
    for c in changed:
        print(c)
    if changed:
        out['gasof'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        json.dump(out, open(OUT, 'w'), indent=None, separators=(',', ':'))
    print('nhl goalies:', len(changed), 'changed')


# ---------------------------------------------------------------- tests
def _test():
    """synthetic seasons, no pulls: the playoff sims on the real series state (mid-series, after round 1, after the
    Cup final), the seeds read back from the first-round pairs, the bracket's marks, the hist extension"""
    import bracket as BK
    S = 2027
    rng = random.Random(3)
    pts = {t: 70 + i for i, t in enumerate(sorted(TEAMS, key=lambda t: rng.random()))}     # every team its own total
    order = {t: float(p) for t, p in pts.items()}
    fit = {'coef': {'home': 0.0}, 'ot': [-1.6, 0.0, 0.0], 'otWin': None, 'seasonSd': 0.0}
    base = {t: 0.0 for t in TEAMS}
    seeds = {cf: conf_seeds(order, cf) for cf in CONF}
    gid = iter(range(1, 10 ** 6))

    def games(a, b, res, rd, n=7, played=None):
        """series a (home ice) v b: res = winners of the games played in order, the rest scheduled"""
        out = []
        for k in range(n):
            h, aw = (a, b) if k in (0, 1, 4, 6) else (b, a)
            done = k < len(res)
            out.append({'id': (S - 1) * 10 ** 6 + 30000 + rd * 100 + 10 + k + 1, 'S': S, 'po': 1, 'day': f'2027-05-{k + 1:02d}',
                        't': f'2027-0{3 + rd}-{k + 1:02d}T19:00', 'h': h, 'a': aw, 'final': done,
                        'hs': (1 if res[k] == h else 0) + 1 if done else None, 'as': (1 if res[k] == aw else 0) + 1 if done else None,
                        'per': 3})
        return out

    def run(ps, sims=4000):
        return simulate(None, fit, [], pts, sims=sims, share=0.0, base=base, knobs=(0.0, 0.0), ps=ps,
                        tally=BK.Tally({cf: 8 for cf in CONF}, ['playoff']))

    def r1(cf):
        return [p for side in conf_sides(seeds[cf]) for p in side]

    # the seeds come back from the real first-round pairs, even with every team's points read the same way
    rows = [g for cf in CONF for a, b in r1(cf) for g in games(a, b, [], 1)]
    st = series_state(rows)
    assert actual_seeds(st, order) == seeds, (actual_seeds(st, order), seeds)
    assert all(x['rd'] == 1 and not x['won'] and x['hi'] in seeds[CONF_OF[x['hi']]][:6] for x in st.values())

    # mid-series: East A1 up 3-1 on WC2, A2 v A3 swept 4-0 by A3, the rest 0-0
    e = seeds['East']
    rows = [g for g in rows if frozenset((g['h'], g['a'])) not in (frozenset(e[0:8:7]), frozenset(e[1:3]))]
    rows += games(e[0], e[7], [e[0], e[7], e[0], e[0]], 1) + games(e[1], e[2], [e[2]] * 4, 1)
    st = series_state(rows)
    x = st[frozenset((e[0], e[7]))]
    assert x['w'] == {e[0]: 3, e[7]: 1} and x['won'] is None and x['hi'] == e[0]
    assert st[frozenset((e[1], e[2]))]['won'] == e[2]
    o = run(st)
    assert o[e[1]].get('r2', 0) == 0 and o[e[2]]['r2'] == 1, (o[e[1]], o[e[2]])
    assert abs(o[e[0]]['r2'] - 0.875) < 0.03, o[e[0]]          # even teams: the leader loses only by dropping three
    assert abs(o[e[3]]['r2'] - 0.5) < 0.04
    assert all(o[t]['playoff'] == 1 for cf in CONF for t in seeds[cf])
    assert all(o[t].get('playoff', 0) == 0 and o[t].get('cup', 0) == 0 for t in TEAMS if t not in e + seeds['West'])
    assert abs(sum(o[t].get('cup', 0) for t in TEAMS) - 1) < 1e-3

    # a series played on from its count keeps its own home ice: home side certain to win at home, sure to lose away
    hb = {t: 0.0 for t in TEAMS}
    fit2 = dict(fit, coef={'home': 40.0})
    x = {frozenset((e[0], e[7])): {'hi': e[0], 'w': {e[0]: 2, e[7]: 2}, 'won': None, 'rd': 1}}
    o = simulate(None, fit2, [], pts, sims=200, share=0.0, base=hb, knobs=(0.0, 0.0), ps=x)
    assert o[e[0]]['r2'] == 1.0, o[e[0]]                   # games 5 and 7 at A1, 6 at WC2: A1 wins 4-3
    x = {frozenset((e[0], e[7])): {'hi': e[7], 'w': {e[0]: 2, e[7]: 2}, 'won': None, 'rd': 1}}
    o = simulate(None, fit2, [], pts, sims=200, share=0.0, base=hb, knobs=(0.0, 0.0), ps=x)
    assert o[e[7]]['r2'] == 1.0, o[e[7]]

    # after round 1: every first-round series decided, the second round not started
    rows, win1 = [], {}
    for cf in CONF:
        for i, (a, b) in enumerate(r1(cf)):
            w = a if i % 2 == 0 else b
            win1[frozenset((a, b))] = w
            rows += games(a, b, [w] * 4, 1, n=4)
    st = series_state(rows)
    o = run(st)
    for k, w in win1.items():
        l = next(t for t in k if t != w)
        assert o[w]['r2'] == 1 and o[l].get('r2', 0) == 0 and o[l].get('cup', 0) == 0, (w, l, o[w], o[l])
    assert all(0 < o[w]['cf'] < 1 for w in win1.values())

    # after the Cup final: every round decided, champion 1, everyone else 0
    def sides_winners(cf):
        sd = conf_sides(seeds[cf])
        return [[win1[frozenset(p)] for p in side] for side in sd]
    champ = {}
    for cf in CONF:
        r2w = []
        for a, b in sides_winners(cf):
            rows += games(a, b, [b] * 4, 2, n=4)
            r2w.append(b)
        rows += games(r2w[0], r2w[1], [r2w[0]] * 4, 3, n=4)
        champ[cf] = r2w[0]
    rows += games(champ['East'], champ['West'], [champ['West']] * 4, 4, n=4)
    st = series_state(rows)
    o = run(st, sims=500)
    cup = champ['West']
    assert o[cup]['cup'] == 1 and all(o[t].get('cup', 0) == 0 for t in TEAMS if t != cup)
    assert o[champ['East']]['final'] == 1 and all(o[t].get('final', 0) == 0 for t in TEAMS if t not in champ.values())

    # the bracket file marks the decided series with the winner and each side's wins
    tal = BK.Tally({cf: 8 for cf in CONF}, ['playoff'])
    o = simulate(None, fit, [], pts, sims=200, share=0.0, base=base, knobs=(0.0, 0.0), ps=st, tally=tal)
    got = {}
    save0 = BK.save
    BK.save = lambda sport, pay: got.setdefault(sport, pay)
    try:
        nhl_bracket(BK, tal, o, st)
    finally:
        BK.save = save0
    pay = got['nhl']
    fg = pay['sections'][-1]['rounds'][0]['games'][0]
    assert fg['done'] == 1 and fg['w'] == cup and {fg['a']['g'], fg['b']['g']} == {4, 0}, fg
    assert pay['sections'][-1]['champ'] == {'t': cup, 'p': 1.0}
    gs = [g for sec in pay['sections'] for r in sec['rounds'] for g in r['games']]
    assert len(gs) == 15 and all(g.get('done') == 1 for g in gs)

    # hist: a file that ends two seasons back gets the season just finished, finals only; a full file is left alone
    h = [{'S': 2025, 'final': True}]
    pulled = []
    h2 = ensure_hist(h, 2027, pull=lambda s: pulled.append(s) or [{'S': s, 'final': True}, {'S': s, 'final': False}], save=False)
    assert pulled == [2026] and [r['S'] for r in h2] == [2025, 2026], h2
    assert ensure_hist(h2, 2027, pull=lambda s: 1 / 0, save=False) is h2
    assert ensure_hist(h, 2027, pull=lambda s: 1 / 0, save=False) == h          # a failed pull: the build goes on
    print('nhl_games playoffs + hist ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        _test()
    elif '--hist-goalies' in sys.argv:      # add the goalies' own xG faced to the frozen seasons (no other refetch)
        D.save(HIST, attach_gx(load_hist()))
    elif '--hist' in sys.argv:
        make_hist()
        make_lineups()
    elif '--lineups' in sys.argv:
        make_lineups()
    elif '--fit' in sys.argv:
        fit()
    elif '--goalies' in sys.argv:
        refresh_goalies()
    else:
        build()
