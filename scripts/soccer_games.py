#!/usr/bin/env python3
"""Soccer game projections for the SOCCER ARKBOARD (data/soccer_games.json), and the model behind them
(data/soccer_games_fit.json).

    python3 scripts/soccer_games.py           # upcoming matches, power rankings, league and European cup odds (numpy)
    python3 scripts/soccer_games.py --hist    # join ESPN, football-data.co.uk and Understat into scripts/soccer_games_hist.json.gz
    python3 scripts/soccer_games.py --fit     # tune, walk-forward backtest against the closing 1X2 price, refit

Data: ESPN (every match since 2005 in 37 competitions: the big five leagues, their second tiers, the twelve other
European leagues with clubs in the UEFA cups, the UEFA cups and their qualifying rounds, MLS and the domestic
cups), football-data.co.uk (shots and the closing 1X2 and over/under prices in 16 of those leagues), Understat
(expected goals for every big-five match since 2014-15).

The ratings: every club has an attack and a defence (log goals a match), relative to its league, and every league a
strength, shared by its clubs in every cross-league match (the European cups, the domestic cups between tiers) and
carried with a club when it moves up or down. Expected goals for the home side:
    log lambda_h = m + env + home + (s[L_h] + a_h) - (s[L_a] + d_a)
where env is the league's goal environment (the two leagues' mean in a cross-league match), home the competition's
home edge (none at a neutral venue), s the league strength (cancels in a league match). After each match every
term moves by its learning rate times the Poisson score (goals - expected), so every opponent counts at its own
strength; clubs are pulled part of the way back to their league's mean each summer and learn faster in a season's
first matches and after a move. The same ratings on Understat's expected goals (big five) blend into attack and
defence at a tuned weight. Win, draw and loss: Dixon-Coles (a Poisson score matrix with the low scores corrected
by rho). Each input and setting stays only if it lowers walk-forward log loss on 2013-22 and 2023-27 doesn't
disagree (see fit()).
"""
import datetime as dt
import gzip
import json
import math
import os
import random
import re
import sys
import unicodedata
from collections import defaultdict, Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D

ROOT = os.path.dirname(HERE)
HIST = os.path.join(HERE, 'soccer_games_hist.json.gz')     # outside data/: Hugo would load it on every build
NAMES = os.path.join(HERE, 'data', 'soccer_teams.json.gz')
FIT = os.path.join(ROOT, 'data', 'soccer_games_fit.json')
OUT = os.path.join(ROOT, 'data', 'soccer_games.json')
WF = os.path.join(HERE, 'data', 'games_wf', 'soccer.json.gz')
FIRST_YEAR = 2005
SCORE_FROM, TUNE, HOLD_FROM = 2013, (2013, 2022), 2023
SCORED = set(D.BIG5) | {'uefa.champions', 'uefa.europa', 'uefa.europa.conf'}
M0 = math.log(1.35)
SUBS = {'x': ('hx', 'ax'), 'm': ('mh', 'ma'), 's': ('hsg', 'asg')}
# tuned on 2013-22 (fit() rewrites data/soccer_games_fit.json; these are its starting point and the live fallback)
P0 = {'k': 0.02592, 'kl': 0.00346, 'ke': 2e-05, 'kh': 0.0012, 'car': 1.0, 'boost': 1.5, 'nb': 9, 'rho': -0.04,
      'prom': 0.0, 'cup': 0.36, 'kx': 0.1106, 'carx': 1.0, 'wx': 0.108, 'km': 0.128, 'carm': 1.0, 'wm': 1.0,
      'ks': 0.03, 'cars': 1.0, 'ws': 0.0, 'rest': 0.0, 'sp': 1.0}


# ---------------------------------------------------------------- names and joins
def nkey(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    drop = {'fc', 'cf', 'afc', 'sc', 'ac', 'as', 'ss', 'us', 'sv', 'vfl', 'vfb', 'tsg', 'fsv', 'rcd', 'ud', 'cd', 'sd',
            'rc', 'real', 'club', 'de', 'calcio', 'the', 'and', 'united', 'city', 'town', 'hotspur', 'olympique', 'stade',
            '1', '1899', '04', '05', '09', '1846', '1860', '1907', '1910', '1913', '1919', 'bc', 'ogc', 'hsc', 'sco', 'losc'}
    return ' '.join(w for w in s.split() if w not in drop)


def name_sim(x, y):
    a, b = set(nkey(x).split()), set(nkey(y).split())
    if not a or not b:
        return 0.0
    if nkey(x) == nkey(y):
        return 1.0
    j = len(a & b) / len(a | b)
    pre = any(u[:4] == v[:4] for u in a for v in b if len(u) >= 4 and len(v) >= 4)
    return max(j, 0.5 if pre else 0.0)


def join_side(espn, other, day_key, score_key, name_keys, tol=2):
    """map another source's team names to ESPN ids by voting over matches that agree on day (+-tol) and score, then
    join each row to its ESPN match; returns {espn match id: other row}"""
    by_day = defaultdict(list)
    for e in espn:
        by_day[e['day']].append(e)
    votes = defaultdict(Counter)
    for o in other:
        d0 = dt.date.fromisoformat(o[day_key])
        sc = score_key(o)
        for k in range(-tol, tol + 1):
            for e in by_day.get((d0 + dt.timedelta(days=k)).isoformat(), []):
                if (e.get('hs'), e.get('as')) == sc and sc[0] is not None:
                    w = 1.0 + name_sim(o[name_keys[0]], e['hn']) + name_sim(o[name_keys[1]], e['an'])
                    votes[o[name_keys[0]]][e['h']] += w
                    votes[o[name_keys[1]]][e['a']] += w
    nm = {n: c.most_common(1)[0][0] for n, c in votes.items() if c}
    idx = defaultdict(list)
    for e in espn:
        idx[(e['h'], e['a'])].append(e)
    out = {}
    for o in other:
        h, a = nm.get(o[name_keys[0]]), nm.get(o[name_keys[1]])
        if not h or not a:
            continue
        d0 = dt.date.fromisoformat(o[day_key])
        best = None
        for e in idx.get((h, a), []):
            dd = abs((dt.date.fromisoformat(e['day']) - d0).days)
            if dd <= 3 and (best is None or dd < best[0]):
                best = (dd, e)
        if best:
            out[best[1]['id']] = o
    return out, nm


# ---------------------------------------------------------------- history
PRIORITY = {lg: i for i, lg in enumerate(D.LEAGUES)}


def all_espn(y0, y1, fresh=False):
    rows = []
    for y in range(y0, y1 + 1):
        for lg in D.LEAGUES:
            rows += D.espn_year(lg, y, fresh=fresh and y >= y1 - 1)
    seen, out = {}, []
    for r in sorted(rows, key=lambda r: PRIORITY[r['lg']]):
        k = (r['day'], r['h'], r['a'])
        if k in seen:
            continue
        seen[k] = 1
        out.append(r)
    out.sort(key=lambda r: (r['t'] or r['day'], r['id']))
    return out


def attach(rows, fresh=False):
    """football-data prices and shots, Understat xG, on each ESPN row (by league season)"""
    by = defaultdict(list)
    for r in rows:
        if r.get('hs') is not None:
            by[(r['lg'], D.season_of(r['day'], r['lg']))].append(r)
    n_fd = n_us = 0
    for (lg, S), es in sorted(by.items()):
        if lg in D.FD_DIV:
            fd = [o for o in D.fd_season(lg, S, fresh=fresh) if o['hs'] is not None]
            j, _ = join_side(es, fd, 'day', lambda o: (o['hs'], o['as']), ('h', 'a'))
            em = {e['id']: e for e in es}
            for mid, o in j.items():
                e = em[mid]
                for k in ('pc', 'ac', 'po', 'ao', 'bo', 'b365', 'ouc', 'ouac', 'ouo', 'oua', 'oubb', 'hst', 'ast', 'hsh', 'ash', 'hr', 'ar'):
                    if o.get(k) is not None:
                        e[k] = o[k]
            n_fd += len(j)
        if lg in D.US_LG and S >= 2015:
            us = D.us_league(lg, S, fresh=fresh) or {}
            ms = [dict(m, day=m['t'][:10], hg=int(m['hg']), ag=int(m['ag'])) for m in us.get('matches', []) if m['res']]
            j, _ = join_side(es, ms, 'day', lambda o: (o['hg'], o['ag']), ('h', 'a'))
            em = {e['id']: e for e in es}
            for mid, o in j.items():
                em[mid]['hx'], em[mid]['ax'] = round(float(o['hx']), 3), round(float(o['ax']), 3)
                em[mid]['us'] = o['id']
            n_us += len(j)
    print('joined', n_fd, 'football-data rows,', n_us, 'Understat rows', flush=True)
    return rows


KEEP = {'id', 'lg', 't', 'day', 'h', 'a', 'hs', 'as', 'st', 'neu', 'leg', 'ser', 'hp', 'ap', 'hw', 'pc', 'ac', 'po', 'ao',
        'bo', 'ouc', 'ouac', 'ouo', 'oua', 'hst', 'ast', 'hx', 'ax', 'us', 'hr', 'ar'}


def make_hist():
    last = dt.date.today().year
    rows = [r for r in all_espn(FIRST_YEAR, last) if r.get('hs') is not None]
    # finished seasons only: the current one is rebuilt live
    cur = D.current_season()
    rows = [r for r in rows if D.season_of(r['day'], r['lg']) < cur or r['lg'] in D.CAL and int(r['day'][:4]) < last]
    attach(rows)
    names = {}
    for r in rows:
        names[r['h']] = [r['hn'], r['hab']]; names[r['a']] = [r['an'], r['aab']]
    rows = [{k: v for k, v in r.items() if k in KEEP} for r in rows]
    for r in rows:
        r['t'] = (r.get('t') or '')[11:16]
        if r['lg'] not in D.EURO:
            r.pop('ser', None)
    D.save(HIST, rows)
    D.save(NAMES, names)
    print('wrote', HIST, len(rows))


def load_rows(live=True, fresh=False):
    """frozen history plus this season so far (and its fixtures) from ESPN"""
    rows = D.load(HIST)
    if not live:
        return rows
    have = {r['id'] for r in rows}
    y = dt.date.today().year
    new = [r for r in all_espn(y - 1, y + 1, fresh=fresh) if r['id'] not in have]
    keys = {(r['day'], r['h'], r['a']) for r in rows}
    new = [r for r in new if (r['day'], r['h'], r['a']) not in keys]
    attach([r for r in new if r.get('hs') is not None], fresh=fresh)
    return rows + new


# ---------------------------------------------------------------- probabilities
FAC = [math.factorial(i) for i in range(12)]
GMAX = 11


def pois(l):
    e = math.exp(-l)
    return [e * l ** i / FAC[i] for i in range(GMAX)]


def score_matrix(lh, la, rho):
    ph, pa = pois(lh), pois(la)
    M = np.outer(ph, pa)
    # Dixon-Coles low-score correction
    M[0, 0] *= max(1e-6, 1 - lh * la * rho)
    M[0, 1] *= max(1e-6, 1 + lh * rho)
    M[1, 0] *= max(1e-6, 1 + la * rho)
    M[1, 1] *= max(1e-6, 1 - rho)
    return M / M.sum()


def wdl(lh, la, rho):
    """home win, draw, away win (closed form for the Dixon-Coles adjustment: fast in the backtest loop)"""
    ph, pa = pois(lh), pois(la)
    c00, c01, c10, c11 = 1 - lh * la * rho, 1 + lh * rho, 1 + la * rho, 1 - rho
    pd = sum(ph[i] * pa[i] for i in range(GMAX))
    cpa = 0.0
    pw = 0.0
    for i in range(GMAX):
        pw += ph[i] * cpa
        cpa += pa[i]
    # P(home > away) = sum_i ph[i] * P(away < i): cpa before adding pa[i] is P(away < i)
    pl = 1 - pd - pw
    # corrections: (0,0),(1,1) are draws; (1,0) home win; (0,1) away win
    pd += ph[0] * pa[0] * (c00 - 1) + ph[1] * pa[1] * (c11 - 1)
    pw += ph[1] * pa[0] * (c10 - 1)
    pl += ph[0] * pa[1] * (c01 - 1)
    t = pw + pd + pl
    return pw / t, pd / t, pl / t


def novig(o):
    if not o:
        return None
    iv = [1 / x for x in o]
    s = sum(iv)
    return [x / s for x in iv] if 1.0 <= s <= 1.15 else None


def close_probs(r):
    for k in ('pc', 'ac', 'po', 'bo', 'ao'):
        p = novig(r.get(k))
        if p:
            return p
    return None


def open_probs(r):
    """earliest price football-data keeps: from 2019-20 the PS/Avg columns are opening-ish (a few days out)"""
    if r.get('pc'):
        return novig(r.get('po')) or novig(r.get('ao'))
    return None


_GRID = None


def add_market(rows, rho=-0.04):
    """goals a match implied by the closing 1X2 price (no-vig), for the market side rating: the Poisson pair whose
    Dixon-Coles win and loss chances sit nearest the price (a 0.05-goal grid)"""
    global _GRID
    if _GRID is None:
        ls = np.arange(0.15, 4.01, 0.05)
        gh, ga = np.meshgrid(ls, ls, indexing='ij')
        W = np.zeros(gh.shape); L = np.zeros(gh.shape)
        for i in range(len(ls)):
            for j in range(len(ls)):
                W[i, j], _, L[i, j] = wdl(ls[i], ls[j], rho)
        _GRID = (gh.ravel(), ga.ravel(), W.ravel(), L.ravel())
    gh, ga, W, L = _GRID
    for r in rows:
        if r.get('hst') is not None and r.get('ast') is not None:
            r['hsg'], r['asg'] = 0.3 * r['hst'], 0.3 * r['ast']        # shots on target in goals (~30% go in)
    todo = [(r, p) for r in rows if r.get('mh') is None for p in [close_probs(r)] if p]
    for i in range(0, len(todo), 2000):
        ch = todo[i:i + 2000]
        pw = np.array([p[0] for _, p in ch])[:, None]; pl = np.array([p[2] for _, p in ch])[:, None]
        k = np.argmin((W[None, :] - pw) ** 2 + (L[None, :] - pl) ** 2, axis=1)
        for (r, _), kk in zip(ch, k):
            r['mh'], r['ma'] = round(float(gh[kk]), 3), round(float(ga[kk]), 3)
    return rows


# ---------------------------------------------------------------- the rating engine
def ex(x):
    return math.exp(min(2.5, max(-4.0, x)))


class Ratings:
    def __init__(self, P):
        self.P = P
        self.a = defaultdict(float); self.d = defaultdict(float)           # goals: attack, defence (log, vs league)
        # side ratings on other match measures, relative to the league: 'x' Understat xG, 'm' the market (goals
        # implied by each earlier match's closing 1X2 price)
        self.sub = {k: {'a': defaultdict(float), 'd': defaultdict(float), 'has': set(), 'env': defaultdict(float),
                        'hfa': defaultdict(lambda: 0.25)} for k in SUBS}
        self.s = defaultdict(float)                                         # league strength
        self.env = defaultdict(float)                                       # league goal environment
        self.hfa = defaultdict(lambda: 0.25)
        self.lg = {}                                                        # club -> league now
        self.n = defaultdict(int)                                           # matches since season start / move
        self.season = {}                                                    # club -> season its n counts in
        self.members = defaultdict(set)                                     # (league, season) -> clubs
        self.home_lg = {}                                                   # (club, season) -> domestic league
        self.rolled = set()
        self.last = {}

    # -- league membership: the domestic league a club plays most of a season's league matches in
    def set_membership(self, rows):
        c = defaultdict(Counter)
        for r in rows:
            if r['lg'] in D.EURO or r['lg'] in D.CUPS:
                continue
            S = D.season_of(r['day'], r['lg'])
            c[(r['h'], S)][r['lg']] += 1
            c[(r['a'], S)][r['lg']] += 1
        self.home_lg = {k: v.most_common(1)[0][0] for k, v in c.items()}
        for (t, S), lg in self.home_lg.items():
            self.members[(lg, S)].add(t)

    def league_of(self, t, day):
        """the club's league this season (else last season's, else the season after's; else 'x' = unlisted)"""
        for lg_cal in (False, True):
            S = D.season_of(day, 'usa.1' if lg_cal else '')
            for s2 in (S, S - 1, S + 1):
                v = self.home_lg.get((t, s2))
                if v and (v in D.CAL) == lg_cal:
                    return v
        return 'x'

    def abs_att(self, t):
        L = self.lg.get(t, 'x')
        return self.s[L] + self.a[t] + self.env[L] / 2

    def abs_def(self, t):
        L = self.lg.get(t, 'x')
        return self.s[L] + self.d[t] - self.env[L] / 2

    def move(self, t, L):
        """club t now plays in league L: carry its absolute strength across"""
        old = self.lg.get(t)
        if old == L:
            return
        if old is None:
            # first sighting: a new club starts at its league's mean, a little below if it came up from lower down
            self.a[t] = self.d[t] = -self.P['prom'] if L in D.BIG5 else 0.0
        else:
            A, Dd = self.abs_att(t), self.abs_def(t)
            self.a[t] = A - self.s[L] - self.env[L] / 2
            self.d[t] = Dd - self.s[L] + self.env[L] / 2
            # side ratings are relative to the league: a club that moves starts them again from its goal ratings
            for e in self.sub.values():
                e['has'].discard(t)
        self.lg[t] = L
        self.n[t] = 0

    def rollover(self, L, S):
        """summer before season S in league L: pull clubs part way back to the mean, recentre the league"""
        if (L, S) in self.rolled:
            return
        self.rolled.add((L, S))
        mem = [t for t in self.members.get((L, S - 1), ()) if self.lg.get(t) == L]
        if len(mem) >= 6:
            ma = sum(self.a[t] for t in mem) / len(mem)
            md = sum(self.d[t] for t in mem) / len(mem)
            for t in [t for t, l in self.lg.items() if l == L]:
                self.a[t] -= ma; self.d[t] -= md
            self.s[L] += (ma + md) / 2
            self.env[L] += ma - md
            for e in self.sub.values():
                mx = [t for t in mem if t in e['has']]
                if len(mx) >= 6:
                    ma = sum(e['a'][t] for t in mx) / len(mx); md = sum(e['d'][t] for t in mx) / len(mx)
                    for t in mx:
                        e['a'][t] -= ma; e['d'][t] -= md
                    e['env'][L] += ma - md
        car = self.P['car']
        for t, l in self.lg.items():
            if l == L:
                self.a[t] *= car; self.d[t] *= car
                for k, e in self.sub.items():
                    c = self.P['car' + k]
                    e['a'][t] *= c; e['d'][t] *= c
                self.n[t] = 0

    def prep(self, r):
        """before a match: make sure both clubs sit in their league for this season (rollovers, promotions)"""
        for t in (r['h'], r['a']):
            L = self.league_of(t, r['day'])
            S = D.season_of(r['day'], L)
            if self.season.get(t) != S:
                self.rollover(L, S)
                self.season[t] = S
                self.n[t] = 0
            self.move(t, L)

    def eff(self, t):
        """attack and defence used to predict: goals ratings blended with xG ratings where the club has them"""
        A, Dd, wt = 0.0, 0.0, 0.0
        for k, e in self.sub.items():
            w = self.P['w' + k]
            if w > 0 and t in e['has']:
                A += w * e['a'][t]; Dd += w * e['d'][t]; wt += w
        if wt == 0:
            return self.a[t], self.d[t]
        g = max(0.0, 1 - wt)
        return (g * self.a[t] + A) / (g + wt), (g * self.d[t] + Dd) / (g + wt)

    def comp_home(self, r):
        if r.get('neu'):
            return 0.0
        return self.hfa['E' if r['lg'] in D.EURO else ('C' if r['lg'] in D.CUPS else r['lg'])]

    def lambdas(self, r):
        h, a = r['h'], r['a']
        Lh, La = self.lg.get(h, 'x'), self.lg.get(a, 'x')
        ah, dh = self.eff(h)
        aa, da = self.eff(a)
        if Lh == La:
            env, sh, sa = self.env[Lh], 0.0, 0.0
        else:
            env, sh, sa = (self.env[Lh] + self.env[La]) / 2, self.s[Lh], self.s[La]
        hm = self.comp_home(r)
        rs = 0.0
        if self.P.get('rest'):
            rs = self.P['rest'] * (self.rest(h, r['day']) - self.rest(a, r['day']))
        x = M0 + env + hm + sh + ah - sa - da + rs
        y = M0 + env + sa + aa - sh - dh - rs
        sp = self.P.get('sp', 1.0)                  # spread: the ratings' gap stretched (the blend shrinks it)
        m, g = (x + y) / 2, (x - y) / 2 * sp
        return ex(m + g), ex(m - g)

    def rest(self, t, day):
        """days since the club's last match, capped at 7 (a full week off) and floored at 2"""
        l = self.last.get(t)
        if not l:
            return 7.0
        return float(min(7, max(2, (dt.date.fromisoformat(day) - dt.date.fromisoformat(l)).days)))

    def update(self, r):
        P = self.P
        h, a = r['h'], r['a']
        Lh, La = self.lg.get(h, 'x'), self.lg.get(a, 'x')
        cross = Lh != La
        if cross:
            env, sh, sa = (self.env[Lh] + self.env[La]) / 2, self.s[Lh], self.s[La]
        else:
            env, sh, sa = self.env[Lh], 0.0, 0.0
        hm = self.comp_home(r)
        span = 4 / 3 if r['st'] in ('AET', 'PEN') else 1.0
        lh = span * ex(M0 + env + hm + sh + self.a[h] - sa - self.d[a])
        la = span * ex(M0 + env + sa + self.a[a] - sh - self.d[h])
        gh, ga = min(r['hs'], 6), min(r['as'], 6)
        rh, ra = gh - lh, ga - la
        w = P['cup'] if r['lg'] in D.CUPS else 1.0
        kh_ = P['k'] * w * (1 + P['boost'] * max(0.0, 1 - self.n[h] / P['nb']))
        ka_ = P['k'] * w * (1 + P['boost'] * max(0.0, 1 - self.n[a] / P['nb']))
        self.a[h] += kh_ * rh; self.d[h] -= kh_ * ra
        self.a[a] += ka_ * ra; self.d[a] -= ka_ * rh
        if cross:
            self.s[Lh] += P['kl'] * w * (rh - ra)
            self.s[La] += P['kl'] * w * (ra - rh)
        else:
            self.env[Lh] += P['ke'] * (rh + ra)
        if hm:
            key = 'E' if r['lg'] in D.EURO else ('C' if r['lg'] in D.CUPS else r['lg'])
            self.hfa[key] += P['kh'] * (rh - ra)
        # side ratings (league matches only: Understat xG in the big five, market goals wherever there's a price)
        if not cross:
            bh = 1 + P['boost'] * max(0.0, 1 - self.n[h] / P['nb'])
            ba = 1 + P['boost'] * max(0.0, 1 - self.n[a] / P['nb'])
            for k, (oh, oa) in SUBS.items():
                if r.get(oh) is None:
                    continue
                e = self.sub[k]
                for t in (h, a):
                    if t not in e['has']:
                        e['has'].add(t)
                        e['a'][t], e['d'][t] = self.a[t], self.d[t]
                lhx = ex(M0 + e['env'][Lh] + e['hfa'][Lh] + e['a'][h] - e['d'][a])
                lax = ex(M0 + e['env'][Lh] + e['a'][a] - e['d'][h])
                xh, xa = r[oh] - lhx, r[oa] - lax
                kx = P['k' + k]
                e['a'][h] += kx * bh * xh; e['d'][h] -= kx * bh * xa
                e['a'][a] += kx * ba * xa; e['d'][a] -= kx * ba * xh
                e['env'][Lh] += P['ke'] * (xh + xa)
                e['hfa'][Lh] += P['kh'] * (xh - xa)
        self.n[h] += 1; self.n[a] += 1
        self.last[h] = self.last[a] = r['day']


def run(rows, P, score=None, keep=None):
    """walk forward through rows (finished matches in time order); score(r, lh, la) called before each update of a
    row with lg in SCORED from SCORE_FROM; keep: optional callback after the update"""
    R = Ratings(P)
    R.set_membership(rows)
    for r in rows:
        if r.get('hs') is None:
            continue
        R.prep(r)
        if score is not None and r['lg'] in SCORED and r['st'] == 'FT':
            S = D.season_of(r['day'], r['lg'])
            if S >= SCORE_FROM:
                lh, la = R.lambdas(r)
                score(r, S, lh, la, R)
        R.update(r)
        if keep:
            keep(r, R)
    return R


def evaluate(rows, P, lo=TUNE[0], hi=TUNE[1], comps=None):
    ll = defaultdict(float); n = defaultdict(int)
    rho = P['rho']

    def score(r, S, lh, la, R):
        if not (lo <= S <= hi):
            return
        if comps and r['lg'] not in comps:
            return
        pw, pd, pl = wdl(lh, la, rho)
        y = pw if r['hs'] > r['as'] else pd if r['hs'] == r['as'] else pl
        g = 'euro' if r['lg'] in D.EURO else 'dom'
        ll[g] += -math.log(max(y, 1e-9)); n[g] += 1
    run(rows, P, score)
    tot = sum(ll.values()) / max(1, sum(n.values()))
    return tot, {g: round(ll[g] / n[g], 5) for g in n}, dict(n)


# ---------------------------------------------------------------- fit
def params():
    try:
        return dict(P0, **json.load(open(FIT))['params'])
    except (OSError, KeyError, ValueError):
        return dict(P0)


def tune(rows, P, keys, rounds=2):
    best = evaluate(rows, P)[0]
    for _ in range(rounds):
        moved = False
        for k in keys:
            for f in ((-0.04, 0.04) if k in ('rho', 'prom', 'rest') else (-0.5, 0.5) if k == 'boost' else (0.7, 1.4)):
                while True:
                    Q = dict(P)
                    Q[k] = P[k] + f if k in ('rho', 'prom', 'rest', 'boost') else P[k] * f
                    if k.startswith('car') or k.startswith('w'):
                        Q[k] = min(Q[k], 1.0)
                    v = evaluate(rows, Q)[0]
                    if v < best - 1e-5:
                        best, P, moved = v, Q, True
                        print(' ', k, round(Q[k], 5), round(v, 5), flush=True)
                    else:
                        break
        if not moved:
            break
    return P, best


def walk(rows, P):
    """every scored match's pre-match chances, the closing price and the result (2013 on)"""
    out = []
    rho = P['rho']

    def score(r, S, lh, la, R):
        pw, pd, pl = wdl(lh, la, rho)
        M = score_matrix(lh, la, rho)
        tot = np.add.outer(np.arange(GMAX), np.arange(GMAX))
        o = {'id': r['id'], 'S': S, 'day': r['day'], 'lg': r['lg'], 'h': r['h'], 'a': r['a'], 'hs': r['hs'], 'as': r['as'],
             'p': [round(pw, 4), round(pd, 4), round(pl, 4)], 'l': [round(lh, 3), round(la, 3)],
             'o25': round(float(M[tot > 2.5].sum()), 4)}
        c = close_probs(r)
        if c:
            o['c'] = [round(x, 4) for x in c]
        op = open_probs(r)
        if op:
            o['o'] = [round(x, 4) for x in op]
        for k in ('pc', 'po', 'ac', 'ao', 'ouc', 'ouac', 'ouo', 'oua'):
            if r.get(k):
                o[k] = r[k]
        out.append(o)
    run(rows, P, score)
    return out


def ll_of(p, y):
    return -math.log(max(1e-9, p[y]))


def res(o):
    return 0 if o['hs'] > o['as'] else 1 if o['hs'] == o['as'] else 2


def cl_t(diff, keys):
    """t on the mean of diff, clustered by key (match day)"""
    g = defaultdict(float)
    for d, k in zip(diff, keys):
        g[k] += d
    v = list(g.values())
    n = len(diff)
    if n < 2 or len(v) < 2:
        return None
    m = sum(diff) / n
    # cluster-robust se of the mean: sqrt(sum_g (sum_i (d_i - m))^2) / n
    gs = defaultdict(float)
    for d, k in zip(diff, keys):
        gs[k] += d - m
    se = math.sqrt(sum(x * x for x in gs.values())) / n
    return round(m / se, 2) if se > 0 else None


def season_sd(rows, P):
    """rating error for the season sims: at each checkpoint in a big-five season (0, 25, 50, 75% of its matches
    played) every club's ratings are frozen; against the rest of its fixtures, its mean goal-margin miss (actual minus
    the frozen ratings' margin) has variance = rating error^2 + game noise / games left. Returns the error sd in goals
    a match by checkpoint (2013 on)"""
    by = defaultdict(list)
    for r in rows:
        if r['lg'] in D.BIG5 and r.get('hs') is not None and D.season_of(r['day'], r['lg']) >= SCORE_FROM:
            by[(r['lg'], D.season_of(r['day'], r['lg']))].append(r['day'])
    cps = {}
    for k, days in by.items():
        days.sort()
        for cp in (0.0, 0.25, 0.5, 0.75):
            cps.setdefault(days[int(cp * (len(days) - 1))], []).append((k, cp))
    snap = {}
    acc = defaultdict(lambda: defaultdict(list))

    def score(r, S, lh, la, R):
        if r['lg'] not in D.BIG5:
            return
        for (k, cp) in cps.get(r['day'], []):
            if k == (r['lg'], S) and (k, cp) not in snap:
                snap[(k, cp)] = (dict(R.a), dict(R.d), {t: R.eff(t) for t in R.lg if R.lg[t] == r['lg']},
                                 R.env[r['lg']], R.hfa[r['lg']])
        for cp in (0.0, 0.25, 0.5, 0.75):
            sn = snap.get(((r['lg'], S), cp))
            if not sn:
                continue
            e = sn[2]
            if r['h'] not in e or r['a'] not in e:
                continue
            fl = ex(M0 + sn[3] + sn[4] + e[r['h']][0] - e[r['a']][1])
            fa = ex(M0 + sn[3] + e[r['a']][0] - e[r['h']][1])
            miss = (r['hs'] - r['as']) - (fl - fa)
            acc[cp][((r['lg'], S), r['h'])].append(miss)
            acc[cp][((r['lg'], S), r['a'])].append(-miss)
    run(rows, P, score)
    out = {}
    for cp, d in acc.items():
        num = den = 0
        for m in d.values():
            if len(m) >= 6:
                mu = sum(m) / len(m)
                num += mu * mu - 1.75 / len(m)      # a match's goal margin has sd ~1.32 around its expectation
                den += 1
        out[str(cp)] = round(math.sqrt(max(0.0, num / max(1, den))), 3)
    return out


def ratings_history(rows, P):
    """every club's rating at the end of each season it played (its last match): goals a match against that
    season's average big-five club at a neutral ground, with attack and defence (scripts/data/soccer_team_ratings.json.gz,
    for the soccer prospects board and anything else that needs club strength by season)"""
    last = {}

    def keep(r, R):
        for t in (r['h'], r['a']):
            L = R.lg.get(t, 'x')
            if r['lg'] in D.EURO or r['lg'] in D.CUPS:
                S = D.season_of(r['day'], L)
            else:
                S = D.season_of(r['day'], r['lg'])
            a, d = R.eff(t)
            last[(t, S)] = (L, R.s[L] + a + R.env[L] / 2, R.s[L] + d - R.env[L] / 2)
    run(rows, P, keep=keep)
    out = defaultdict(dict)
    for S in sorted({k[1] for k in last}):
        big = [v for (t, s), v in last.items() if s == S and v[0] in D.BIG5]
        if not big:
            continue
        AB = sum(v[1] for v in big) / len(big); DB = sum(v[2] for v in big) / len(big)
        mu = math.exp(M0 + AB - DB)
        for (t, s), (L, A, Dd) in last.items():
            if s == S:
                lf, la = math.exp(M0 + A - DB), math.exp(M0 + AB - Dd)
                out[str(S)][t] = [L, round(lf - la, 3), round(lf - mu, 3), round(mu - la, 3)]
    D.save(os.path.join(HERE, 'data', 'soccer_team_ratings.json.gz'),
           {'note': 'season (end year) -> ESPN club id -> [league, rating, off, def]: goals a match vs that season\'s '
                    'average big-five club, neutral ground, at the club\'s last match of the season',
            'seasons': out})


def fit():
    rows = add_market(D.load(HIST))
    P = params()
    print('tune', flush=True)
    P, best = tune(rows, P, ['wm', 'km', 'wx', 'kx', 'k', 'kl', 'kh', 'rho', 'boost', 'nb', 'cup'])
    tests = []

    def test(name, Q, kept, note=''):
        a, ga, na = evaluate(rows, Q)
        b, gb, nb = evaluate(rows, Q, lo=HOLD_FROM, hi=2100)
        tests.append({'name': name, 'tune': round(a, 5), 'hold': round(b, 5), 'tuneBy': ga, 'holdBy': gb, 'kept': kept, 'note': note})
        print(name, round(a, 5), round(b, 5), flush=True)
    test('goals ratings only', dict(P, wx=0.0, wm=0.0), False, 'every club: attack and defence on goals')
    test('+ Understat xG ratings', dict(P, wm=0.0), False, 'big five: xG a match, blended into attack and defence')
    test('+ market ratings (final model)', P, True, "earlier matches' closing 1X2 prices as goals; never the match's own")
    for nm, Q, note in (('+ rest days', dict(P, rest=0.01), 'days since the last match, 2 to 7, home minus away'),
                        ('+ rest days (other sign)', dict(P, rest=-0.01), ''),
                        ('+ shots on target', dict(P, ws=0.05), "football-data's shots on target as goals (30% conversion)"),
                        ('no early-season boost', dict(P, boost=0.0), 'learning rate x (1 + boost) in a season\'s first matches'),
                        ('summer regression 0.85', dict(P, car=0.85, carx=0.85, carm=0.85), 'pull 15% back to the league mean each summer'),
                        ('spread x1.05', dict(P, sp=1.05), "the gap between the sides' expected goals stretched 5% (held out better, tuning worse)")):
        test(nm, Q, False, note)
    wf = walk(rows, P)
    D.save(WF, wf)
    # vs the close, big five league matches with a price
    vs = {}
    for per, lo, hi in (('tune', TUNE[0], TUNE[1]), ('hold', HOLD_FROM, 2100)):
        xs = [o for o in wf if lo <= o['S'] <= hi and o['lg'] in D.BIG5 and o.get('c')]
        dm = [ll_of(o['p'], res(o)) for o in xs]
        dc = [ll_of(o['c'], res(o)) for o in xs]
        vs[per] = {'n': len(xs), 'model': round(sum(dm) / len(xs), 5), 'close': round(sum(dc) / len(xs), 5),
                   't': cl_t([a - b for a, b in zip(dm, dc)], [o['day'] for o in xs]),
                   'byLeague': {lg: {'n': len(ys), 'model': round(sum(ll_of(o['p'], res(o)) for o in ys) / len(ys), 4),
                                     'close': round(sum(ll_of(o['c'], res(o)) for o in ys) / len(ys), 4)}
                                for lg in D.BIG5 for ys in [[o for o in xs if o['lg'] == lg]] if ys}}
    euro = {}
    for lg in ('uefa.champions', 'uefa.europa', 'uefa.europa.conf'):
        for per, lo, hi in (('tune', TUNE[0], TUNE[1]), ('hold', HOLD_FROM, 2100)):
            xs = [o for o in wf if lo <= o['S'] <= hi and o['lg'] == lg]
            if xs:
                euro.setdefault(lg, {})[per] = {'n': len(xs), 'model': round(sum(ll_of(o['p'], res(o)) for o in xs) / len(xs), 4),
                                                'base': round(sum(ll_of([0.45, 0.26, 0.29], res(o)) for o in xs) / len(xs), 4)}
    # calibration, held-out seasons
    cal = []
    xs = [o for o in wf if o['S'] >= HOLD_FROM]
    for lo in [i / 10 for i in range(10)]:
        ys = [o for o in xs if lo <= o['p'][0] < lo + 0.1]
        if len(ys) >= 30:
            cal.append({'bin': lo, 'n': len(ys), 'p': round(sum(o['p'][0] for o in ys) / len(ys), 3),
                        'won': round(sum(res(o) == 0 for o in ys) / len(ys), 3),
                        'pD': round(sum(o['p'][1] for o in ys) / len(ys), 3), 'drew': round(sum(res(o) == 1 for o in ys) / len(ys), 3)})
    sd = season_sd(rows, P)
    ratings_history(rows, P)
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'params': P, 'tune': list(TUNE),
           'holdFrom': HOLD_FROM, 'tests': tests, 'vsClose': vs, 'euro': euro, 'calibration': cal, 'seasonSd': sd,
           'n': {'matches': len(rows), 'scored': len(wf)}}
    json.dump(out, open(FIT, 'w'), indent=1, allow_nan=False)
    print(json.dumps({k: out[k] for k in ('vsClose', 'euro', 'seasonSd')}, indent=1))


# ---------------------------------------------------------------- live: ratings, matches, tables, sims
SIMS = 10000
REL = {'eng.1': (3, 0), 'esp.1': (3, 0), 'ita.1': (3, 0), 'ger.1': (2, 1), 'fra.1': (2, 1)}   # auto, playoff spots
UEFA = ['uefa.champions', 'uefa.europa', 'uefa.europa.conf']
GPM = 1.4                                           # goals a side a match: margin error -> log-rate shift


def american(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def rate_sd(share):
    try:
        import rank_odds
        v = rank_odds.sd_of('soccer', share)
        if v:
            return v
    except Exception:
        pass
    return math.sqrt(0.09 + 0.054 * share)


class Live:
    """the ratings at today's date, and what the sims and tables need from them"""
    def __init__(self, P, rows):
        self.P = P
        self.rows = rows
        self.R = run(rows, P)
        self.names = D.load(NAMES) if os.path.exists(NAMES) else {}
        for r in rows:
            if r.get('hn'):
                self.names[r['h']] = [r['hn'], r.get('hab')]
            if r.get('an'):
                self.names[r['a']] = [r['an'], r.get('aab')]

    def lam(self, r):
        self.R.prep(r)
        return self.R.lambdas(r)

    def absr(self, t):
        R = self.R
        L = R.lg.get(t, 'x')
        a, d = R.eff(t)
        return R.s[L] + a + R.env[L] / 2, R.s[L] + d - R.env[L] / 2

    def base(self, S):
        """the average big-five club this season: its attack and defence"""
        ts = [t for lg in D.BIG5 for t in self.R.members.get((lg, S), ())]
        ab = [self.absr(t) for t in ts]
        return sum(x[0] for x in ab) / len(ab), sum(x[1] for x in ab) / len(ab)


def table(rows):
    """league table so far: club -> [played, won, drawn, lost, gf, ga, pts]"""
    T = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0])
    for r in rows:
        if r.get('hs') is None:
            continue
        h, a = T[r['h']], T[r['a']]
        for x, gf, ga in ((h, r['hs'], r['as']), (a, r['as'], r['hs'])):
            x[0] += 1; x[4] += gf; x[5] += ga
            if gf > ga:
                x[1] += 1; x[6] += 3
            elif gf == ga:
                x[2] += 1; x[6] += 1
            else:
                x[3] += 1
    return T


def sim_matches(L, fx, teams, rng, n, share):
    """goals for every fixture in every sim (n x fixtures), each club's strength drawn once a sim"""
    if not fx:
        return np.zeros((n, 0), int), np.zeros((n, 0), int)
    ix = {t: i for i, t in enumerate(teams)}
    dl = rng.normal(0.0, rate_sd(share), (n, len(teams)))
    lh = np.array([L.lam(r)[0] for r in fx]); la = np.array([L.lam(r)[1] for r in fx])
    hi = np.array([ix[r['h']] for r in fx]); ai = np.array([ix[r['a']] for r in fx])
    sh = (dl[:, hi] - dl[:, ai]) / (2 * GPM)
    return rng.poisson(lh[None, :] * np.exp(sh)), rng.poisson(la[None, :] * np.exp(-sh))


def rank_sim(teams, T0, fx, gh, ga, rng):
    """final positions (n x clubs, 0 = top) and points: points, goal difference, goals scored, then a coin flip"""
    n = gh.shape[0]
    ix = {t: i for i, t in enumerate(teams)}
    pts = np.tile(np.array([T0[t][6] for t in teams], float), (n, 1))
    gd = np.tile(np.array([T0[t][4] - T0[t][5] for t in teams], float), (n, 1))
    gf = np.tile(np.array([T0[t][4] for t in teams], float), (n, 1))
    for j, r in enumerate(fx):
        h, a = ix[r['h']], ix[r['a']]
        x, y = gh[:, j], ga[:, j]
        pts[:, h] += np.where(x > y, 3, np.where(x == y, 1, 0)); pts[:, a] += np.where(y > x, 3, np.where(x == y, 1, 0))
        gd[:, h] += x - y; gd[:, a] += y - x; gf[:, h] += x; gf[:, a] += y
    key = pts * 1e6 + (gd + 500) * 1e3 + gf + rng.random(pts.shape)
    order = np.argsort(-key, axis=1)
    pos = np.empty_like(order)
    rows_ = np.arange(n)[:, None]
    pos[rows_, order] = np.arange(len(teams))[None, :]
    return pos, pts, gd


def league_odds(L, lg, S, rng, n=SIMS):
    rs = [r for r in L.rows if r['lg'] == lg and D.season_of(r['day'], lg) == S]
    played = [r for r in rs if r.get('hs') is not None]
    fx = [r for r in rs if r.get('hs') is None and r['st'] not in ('abandoned', 'canceled', 'cancelled')]
    teams = sorted({r['h'] for r in rs} | {r['a'] for r in rs})
    T0 = table(played)
    share = len(fx) / max(1, len(rs))
    gh, ga = sim_matches(L, fx, teams, rng, n, share)
    pos, pts, gd = rank_sim(teams, T0, fx, gh, ga, rng)
    auto, po = REL[lg]
    nt = len(teams)
    out = {}
    for i, t in enumerate(teams):
        p = pos[:, i]
        x = T0[t]
        out[t] = {'rec': f'{x[1]}-{x[2]}-{x[3]}', 'pts': x[6], 'gp': x[0], 'gd': x[4] - x[5], 'gf': x[4],
                  'xpts': round(float(pts[:, i].mean()), 1), 'xgd': round(float(gd[:, i].mean()), 1),
                  'title': round(float((p == 0).mean()), 4), 'top4': round(float((p < 4).mean()), 4),
                  'rel': round(float((p >= nt - auto).mean()), 4),
                  'relpo': round(float((p == nt - auto - 1).mean()), 4) if po else None,
                  'pos': round(float(p.mean()) + 1, 1)}
    return out, len(fx), len(rs), teams


# --- UEFA: league phase, then the knockout bracket
def tie(L, hi, lo, rng, n, dl, ix, venue_rows):
    """two-legged ties, n sims: lo hosts leg 1, hi (better league-phase rank) leg 2; extra time at hi, then
    penalties as a coin flip. hi, lo: arrays of club indices (n). Returns the winner index array"""
    lam = venue_rows
    lh1, la1 = lam(lo, hi)              # leg 1: lo at home
    lh2, la2 = lam(hi, lo)              # leg 2: hi at home
    s1 = (dl[np.arange(n), lo] - dl[np.arange(n), hi]) / (2 * GPM)
    g_lo = rng.poisson(lh1 * np.exp(s1)) + rng.poisson(la2 * np.exp(s1))
    g_hi = rng.poisson(la1 * np.exp(-s1)) + rng.poisson(lh2 * np.exp(-s1))
    lvl = g_lo == g_hi
    e_hi = rng.poisson(lh2 * np.exp(-s1) / 3); e_lo = rng.poisson(la2 * np.exp(s1) / 3)
    pen = rng.random(n) < 0.5
    hi_wins = (g_hi > g_lo) | (lvl & ((e_hi > e_lo) | ((e_hi == e_lo) & pen)))
    return np.where(hi_wins, hi, lo)


def final(L, x, y, rng, n, dl, lamn):
    lh, la = lamn(x, y)
    s = (dl[np.arange(n), x] - dl[np.arange(n), y]) / (2 * GPM)
    gx, gy = rng.poisson(lh * np.exp(s)), rng.poisson(la * np.exp(-s))
    ex_, ey = rng.poisson(lh * np.exp(s) / 3), rng.poisson(la * np.exp(-s) / 3)
    pen = rng.random(n) < 0.5
    return np.where((gx > gy) | ((gx == gy) & ((ex_ > ey) | ((ex_ == ey) & pen))), x, y)


def uefa_odds(L, lg, S, rng, n=SIMS):
    rs = [r for r in L.rows if r['lg'] == lg and D.season_of(r['day'], lg) == S]
    lp = [r for r in rs if (r.get('slug') or '').startswith('league') or r.get('slug') is None and not r.get('leg')]
    if not lp:
        return None
    teams = sorted({r['h'] for r in lp} | {r['a'] for r in lp})
    if len(teams) < 24:
        return None
    ix = {t: i for i, t in enumerate(teams)}
    played = [r for r in lp if r.get('hs') is not None]
    fx = [r for r in lp if r.get('hs') is None]
    T0 = table(played)
    share = len(fx) / max(1, len(lp))
    gh, ga = sim_matches(L, fx, teams, rng, n, share)
    pos, pts, gd = rank_sim(teams, T0, fx, gh, ga, rng)
    nt = len(teams)
    # the same strength draws in the knockouts (a fresh draw: the sims are independent of sim_matches' draws but
    # each club keeps one strength through its run)
    dl = rng.normal(0.0, rate_sd(share), (n, nt))
    # pairwise expected goals, club i at home to club j (UEFA home edge), and at a neutral final
    LH = np.zeros((nt, nt)); LA = np.zeros((nt, nt)); NH = np.zeros((nt, nt)); NA = np.zeros((nt, nt))
    for i, t in enumerate(teams):
        for j, u in enumerate(teams):
            if i != j:
                LH[i, j], LA[i, j] = L.lam({'h': t, 'a': u, 'lg': lg, 'day': dt.date.today().isoformat(), 'neu': 0})
                NH[i, j], NA[i, j] = L.lam({'h': t, 'a': u, 'lg': lg, 'day': dt.date.today().isoformat(), 'neu': 1})
    lam = lambda h, a: (LH[h, a], LA[h, a])
    lamn = lambda h, a: (NH[h, a], NA[h, a])
    seat = np.argsort(pos, axis=1)              # seat[s, k] = club finishing k-th (0-based)
    reach = {k: np.zeros(nt) for k in ('ko', 'top8', 'r16', 'qf', 'sf', 'fin', 'win')}
    ar = np.arange(n)
    pick = lambda a, b: np.where(rng.random(n) < 0.5, a, b)
    # knockout play-off: seeds 9-16 (one of each pair) against 17-24, pairs fixed by UEFA's bracket
    po_winner = {}
    for k, (p_hi, p_lo) in enumerate((((8, 9), (22, 23)), ((10, 11), (20, 21)), ((12, 13), (18, 19)), ((14, 15), (16, 17)))):
        h1, h2 = seat[:, p_hi[0]], seat[:, p_hi[1]]
        l1, l2 = seat[:, p_lo[0]], seat[:, p_lo[1]]
        sw = rng.random(n) < 0.5
        a1, a2 = np.where(sw, l1, l2), np.where(sw, l2, l1)
        po_winner[k] = (tie(L, h1, a1, rng, n, dl, ix, lam), tie(L, h2, a2, rng, n, dl, ix, lam))
    # round of 16: seeds 1/2 v play-off winners from 15-18, 3/4 v 13-14/19-20, 5/6 v 11-12/21-22, 7/8 v 9-10/23-24
    halves = [[], []]
    for k, (s1, s2) in enumerate(((0, 1), (2, 3), (4, 5), (6, 7))):
        w1, w2 = po_winner[3 - k]
        sw = rng.random(n) < 0.5
        o1, o2 = np.where(sw, w1, w2), np.where(sw, w2, w1)
        halves[0].append(tie(L, seat[:, s1], o1, rng, n, dl, ix, lam))
        halves[1].append(tie(L, seat[:, s2], o2, rng, n, dl, ix, lam))
    rank_of = pos                                   # better rank hosts the second leg
    def ko(x, y):
        hi_ = np.where(rank_of[ar, x] < rank_of[ar, y], x, y); lo_ = np.where(rank_of[ar, x] < rank_of[ar, y], y, x)
        return tie(L, hi_, lo_, rng, n, dl, ix, lam)
    sf = []
    for hv in halves:
        q1, q2 = ko(hv[0], hv[3]), ko(hv[1], hv[2])     # 1/2 v 7/8, 3/4 v 5/6
        for q in (hv[0], hv[1], hv[2], hv[3]):
            np.add.at(reach['qf'], q, 1)
        np.add.at(reach['sf'], q1, 1); np.add.at(reach['sf'], q2, 1)
        sf.append(ko(q1, q2))
    for f in sf:
        np.add.at(reach['fin'], f, 1)
    np.add.at(reach['win'], final(L, sf[0], sf[1], rng, n, dl, lamn), 1)
    for k in range(24):
        np.add.at(reach['ko'], seat[:, k], 1)
    for k in range(8):
        np.add.at(reach['top8'], seat[:, k], 1)
    for w1, w2 in po_winner.values():
        np.add.at(reach['r16'], w1, 1); np.add.at(reach['r16'], w2, 1)
    reach['r16'] += reach['top8']
    out = {}
    for i, t in enumerate(teams):
        x = T0[t]
        out[t] = {'rec': f'{x[1]}-{x[2]}-{x[3]}', 'pts': x[6], 'gp': x[0], 'gd': x[4] - x[5],
                  'xpts': round(float(pts[:, i].mean()), 1), 'pos': round(float(pos[:, i].mean()) + 1, 1),
                  **{k: round(float(v[i] / n), 4) for k, v in reach.items()}}
    return {'teams': out, 'left': len(fx), 'games': len(lp)}


def logo(tid):
    p = os.path.join(ROOT, 'static', 'img', 'soccer', f'{tid}.png')
    if os.path.exists(p):
        return
    b = D.get(f'https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png', raw=True)
    if not b:
        return
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(b)).convert('RGBA')
        im.thumbnail((64, 64))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        im.save(p, optimize=True)
    except Exception:
        pass


def build(days_ahead=4):
    P = params()
    rows = load_rows(live=True)
    for r in rows:
        if len(r.get('t') or '') > 5:
            r['t'] = r['t'][11:16]
    rows.sort(key=lambda r: (r['day'], r.get('t') or '', r['id']))
    add_market(rows, P['rho'])
    L = Live(P, rows)
    R = L.R
    today = dt.date.today()
    S = D.current_season(today)
    rng = np.random.default_rng(int(today.strftime('%Y%m%d')))
    leagues, left, size = {}, {}, {}
    for lg in D.BIG5:
        o, nl, ng, teams = league_odds(L, lg, S, rng)
        leagues[lg] = o; left[lg] = nl; size[lg] = ng
    uefa = {lg: uefa_odds(L, lg, S, rng) for lg in UEFA}
    # power table: every big-five club and every UEFA league-phase club
    AB, DB = L.base(S)
    mu = math.exp(M0 + AB - DB)
    pw = []
    clubs = {t: lg for lg in D.BIG5 for t in leagues[lg]}
    for lg, u in uefa.items():
        for t in (u or {}).get('teams', {}):
            clubs.setdefault(t, R.lg.get(t, 'x'))
    for t, lg in clubs.items():
        A, Dd = L.absr(t)
        lf, la_ = math.exp(M0 + A - DB), math.exp(M0 + AB - Dd)
        w_, d_, l_ = wdl(lf, la_, P['rho'])
        row = {'id': t, 'n': (L.names.get(t) or ['?', '?'])[0], 'ab': (L.names.get(t) or ['?', '?'])[1], 'lg': lg,
               'rating': round(lf - la_, 3), 'off': round(lf - mu, 3), 'def': round(mu - la_, 3),
               'pW': round(w_, 3), 'pD': round(d_, 3), 'xpm': round(3 * w_ + d_, 2)}
        if lg in leagues:
            row.update({k: leagues[lg][t][k] for k in ('rec', 'pts', 'gp', 'gd', 'xpts', 'title', 'top4', 'rel')})
        for c, u in uefa.items():
            if u and t in u['teams']:
                row[D.SHORT[c].lower()] = u['teams'][t]['win']
        pw.append(row)
    pw.sort(key=lambda r: -r['rating'])
    for i, r in enumerate(pw, 1):
        r['rk'] = i
    try:
        import rank_odds
        rank_odds.add(pw, 'soccer', lambda r: (left.get(r['lg'], 0) / max(1, size.get(r['lg'], 380))) if r['lg'] in left else 0.6)
    except Exception as e:
        print('rank odds:', e)
    prk = {r['id']: r['rk'] for r in pw}
    # matches: the next days_ahead days in the big five and the UEFA cups, with DraftKings' line from ESPN
    games = []
    dk = {}
    for k in range(days_ahead):
        day = (today + dt.timedelta(days=k)).isoformat()
        for lg in D.BIG5 + UEFA:
            for e in D.espn_day(lg, day):
                dk[e['id']] = e
    for r in rows:
        if r['lg'] not in SCORED or not (today.isoformat() <= r['day'] <= (today + dt.timedelta(days=days_ahead - 1)).isoformat()):
            continue
        e = dk.get(r['id'], {})
        if r.get('hs') is not None and r['day'] < today.isoformat():
            continue
        lh, la = L.lam(r)
        pw_, pd_, pl_ = wdl(lh, la, P['rho'])
        M = score_matrix(lh, la, P['rho'])
        tot = np.add.outer(np.arange(GMAX), np.arange(GMAX))
        i0, j0 = np.unravel_index(np.argmax(M), M.shape)
        g = {'id': r['id'], 'lg': r['lg'], 'day': r['day'], 'tip': f"{r['day']}T{r.get('t') or '12:00'}:00Z",
             'h': r['h'], 'a': r['a'], 'hn': L.names.get(r['h'], ['?'])[0], 'an': L.names.get(r['a'], ['?'])[0],
             'hab': L.names.get(r['h'], ['?', '?'])[1], 'aab': L.names.get(r['a'], ['?', '?'])[1],
             'p': [round(pw_, 4), round(pd_, 4), round(pl_, 4)], 'fair': [american(pw_), american(pd_), american(pl_)],
             'l': [round(lh, 2), round(la, 2)], 'o25': round(float(M[tot > 2.5].sum()), 3),
             'btts': round(float(M[1:, 1:].sum()), 3), 'top': f'{i0}-{j0}', 'pTop': round(float(M[i0, j0]), 3),
             'hr': prk.get(r['h']), 'ar': prk.get(r['a']), 'neu': r.get('neu', 0)}
        if e.get('dk') and all(e['dk'].get(k) for k in ('h', 'd', 'a')):
            g['dk'] = e['dk']
        if e.get('venue'):
            g['venue'] = e['venue']
        if e.get('st') and e['st'] not in ('SCHED',) and e.get('hs') is not None:
            g['final'] = [e['hs'], e['as']]
        for c in ('h', 'a'):
            lgx = r['lg'] if r['lg'] in leagues else clubs.get(r[c])
            if lgx in leagues and r[c] in leagues[lgx]:
                g[c + 'rec'] = leagues[lgx][r[c]]['rec']
        games.append(g)
    games.sort(key=lambda g: (g['tip'], g['id']))
    for t in clubs:
        logo(t)
    hfa = {lg: round(math.exp(R.hfa[lg]) - 1, 3) for lg in D.BIG5}
    hfa['UEFA'] = round(math.exp(R.hfa['E']) - 1, 3)
    strength = {lg: round(R.s[lg], 3) for lg in D.LEAGUES if lg in R.s and lg not in D.EURO and lg not in D.CUPS}
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'season': S, 'sims': SIMS,
           'games': games, 'power': pw, 'leagues': {lg: {'name': D.NAME[lg], 'left': left[lg], 'games': size[lg],
                                                         'rel': REL[lg], 'teams': [dict(id=t, n=L.names.get(t, ['?'])[0], ab=L.names.get(t, ['?', '?'])[1], **v) for t, v in sorted(leagues[lg].items(), key=lambda kv: kv[1]['pos'])]}
                                                    for lg in D.BIG5},
           'uefa': {lg: (dict(name=D.NAME[lg], left=u['left'], games=u['games'],
                              teams=[dict(id=t, n=L.names.get(t, ['?'])[0], ab=L.names.get(t, ['?', '?'])[1], lg=clubs.get(t, 'x'), **v)
                                     for t, v in sorted(u['teams'].items(), key=lambda kv: kv[1]['pos'])]) if u else None)
                    for lg, u in uefa.items()},
           'home': hfa, 'leagueStrength': strength, 'baseGoals': round(mu, 3)}
    txt = json.dumps(out, separators=(',', ':'), allow_nan=False)
    open(OUT, 'w').write(txt)
    print('wrote', OUT, len(games), 'matches', len(pw), 'clubs', len(txt) // 1024, 'KB')


if __name__ == '__main__':
    if '--hist' in sys.argv:
        make_hist()
    elif '--fit' in sys.argv:
        fit()
    elif '--eval' in sys.argv:
        rows = D.load(HIST)
        print(evaluate(rows, P0))
    else:
        build()
