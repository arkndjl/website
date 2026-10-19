#!/usr/bin/env python3
"""College basketball game projections for the College Basketball ARKBOARD (data/cbb_games.json), the model behind them
(data/cbb_games_fit.json) and its picks (data/cbb_picks.json, scripts/cbb_picks.py).

    python3 scripts/cbb_games.py --fit     # walk-forward backtest 2016-2026 against the closing line, tune, select inputs
    python3 scripts/cbb_games.py           # today's and tomorrow's games, power ratings, season odds (run by cbb-board)

The same design as the football models (scripts/cfb_model.mjs, scripts/nfl_games.py): a rating core, market ratings
from earlier closing lines, availability, a player-based preseason prior, candidate inputs kept only on out-of-sample
evidence, win probability calibrated to results, everything judged against the closing line on held-out seasons.

Margin (home minus away, points) is a linear model, fit on the seasons before the one it scores, on:
    eff     opponent-adjusted efficiency: each team's offense and defense in points per 100 possessions, solved each day
            from this season's games (a ridge regression on both teams' points a possession, home court and the league
            average, recent games weighted up) and pulled toward the preseason prior; times the game's expected
            possessions (tempo solved the same way)
    elo     Elo difference (K, margin multiplier, part carried over each summer: tuned)
    mkt     market rating: each team's points against an average team as EARLIER games' closing spreads priced it
            (never the game's own line), part carried over each summer
    home    1 at a true home game, 0 neutral
    + candidates kept only when they cut 2016-20 error at t <= -1.5 (CANDS; data/cbb_games_fit.json 'select')
Preseason prior (the efficiency solve's starting point): last season's final rating and the roster, by player from
Barttorvik's lines: returning minutes and BPM x minutes, incoming transfers' BPM x minutes, freshmen by recruiting rank
(On3, 247); weights fit on the seasons before (scripts/data/cbb_team_prior.json; live rosters from scripts/cbb_prior.json.gz).
Total: the efficiency total (both offenses against both defenses, times possessions) and the market total rating.
Win probability: normal around the margin with sd fit to results on the training seasons.
Data: ESPN (schedule, scores, every book's lines, scripts/cbb_games_hist.py), Barttorvik (possessions; per-game
player minutes for availability; player seasons for the prior).
"""
import gzip
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')        # one thread: the daily 780-team solves run 4x faster than with BLAS threads
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'cbb', 'games')
HIST = os.path.join(HERE, 'data', 'cbb_games_hist.json.gz')
TPRIOR = os.path.join(HERE, 'data', 'cbb_team_prior.json')
STATE = os.path.join(HERE, 'data', 'cbb_games_state.json')
FIT = os.path.join(ROOT, 'data', 'cbb_games_fit.json')
OUT = os.path.join(ROOT, 'data', 'cbb_games.json')
BTLOG = os.path.join(HERE, '.cache', 'cbb', 'games_bt')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
FIRST, SCORE0, TUNE_END, LAST = 2014, 2016, 2020, 2026
BASE = ['eff', 'elo', 'mkt', 'home']
CANDS = ['inj', 'rest', 'confh', 'alt', 'early', 'tourn', 'form', 'mkteff']
TFEATS = ['efft', 'tmkt', 'one']
PRIOR_F = ['one', 'last', 'lastret', 'ret', 'retmin', 'tr', 'trmin', 'fr']
X = 'X'                                   # every non-D-I opponent, one rating
# home courts a mile up or close (feet): Air Force, Colorado, Colorado St., Denver, Wyoming, Utah, Utah St., BYU,
# Utah Valley, Utah Tech, Southern Utah, Weber St., New Mexico, Northern Arizona, Montana St., Idaho St., Nevada, UNLV?
# (UNLV 2,000 ft, left out), Northern Colorado, Grand Canyon (1,100, left out)
ALT = {'2005', '38', '36', '2172', '2751', '254', '328', '252', '3084', '3101', '253', '2692', '167', '2464', '147', '304', '2440', '2458'}


def et_date(iso):
    return (datetime.fromisoformat(iso.replace('Z', '+00:00')) - timedelta(hours=5)).strftime('%Y-%m-%d')


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ---------------------------------------------------------------- data
def load_hist():
    return json.load(gzip.open(HIST))


def bt_map(games, prior_rows=None):
    """ESPN team id -> Barttorvik name (the possessions join carries both)"""
    m = defaultdict(lambda: defaultdict(int))
    for g in games:
        if 'hb' in g:
            m[g['home']][g['hb']] += 1; m[g['away']][g['ab']] += 1
    out = {t: max(c, key=c.get) for t, c in m.items()}
    return out


def d1_set(games):
    """D-I teams: the ones Barttorvik rates (non-D-I games have no Barttorvik row)"""
    c = defaultdict(int)
    for g in games:
        if 'hb' in g:
            c[g['home']] += 1; c[g['away']] += 1
    return {t for t, n in c.items() if n >= 3}


def bt_logs(season):
    """Barttorvik per-game player rows: team -> [(date, {pid: (min, gbpm)})] in date order"""
    p = os.path.join(BTLOG, f'{season}.json.gz')
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        os.makedirs(BTLOG, exist_ok=True)
        subprocess.run(['curl', '-s', '-m', '300', '-A', UA, f'https://barttorvik.com/{season}_all_advgames.json.gz', '-o', p], check=False)
    try:
        rows = json.load(gzip.open(p))
    except Exception:
        return {}
    by = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        try:
            d = str(r[0]); d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
            if (r[8] or 0) > 0:
                by[r[47]][d][r[51]] = (float(r[8]), float(r[44] or 0))
        except (IndexError, TypeError, ValueError):
            continue
    return {t: sorted(v.items()) for t, v in by.items()}


def avail(logs, repl=-3.0, n0=150.0):
    """value of the rotation players who sat out the team's last game, per 100 possessions against a replacement:
    (BPM to date, shrunk to -1 by n0 minutes, minus repl) x his minutes a team game / 40. Rotation: 12+ minutes when he
    plays and in 60% of the team's games, 3+ games in. Keyed (team, date of the game it applies to); 'next' = after the last."""
    out = {}
    for t, gl in logs.items():
        st = {}            # pid -> [games, minutes, gbpm x minutes]
        for k in range(len(gl) + 1):
            v = 0.0
            if k >= 3:
                last = gl[k - 1][1]
                for pid, (g, mn, bm) in st.items():
                    if pid in last or g < 0.6 * k or mn / g < 12:
                        continue
                    bpm = (bm + -1.0 * n0) / (mn + n0)
                    v += max(0.0, bpm - repl) * (mn / k) / 40
            out[(t, gl[k][0] if k < len(gl) else 'next')] = round(v, 3)
            if k < len(gl):
                for pid, (mn, gb) in gl[k][1].items():
                    s = st.setdefault(pid, [0, 0.0, 0.0])
                    s[0] += 1; s[1] += mn; s[2] += gb * mn
    return out


def team_prior_hist():
    """scripts/data/cbb_team_prior.json from the board's Barttorvik research seasons (one row per player season):
    season -> Barttorvik team -> roster features (see PRIOR_F)"""
    import csv
    src = '/mnt/project-files/cbb/backtest/research_seasons.csv'
    by = defaultdict(dict)                     # year -> pid -> row
    for r in csv.DictReader(open(src)):
        by[int(r['year'])][r['pid']] = r
    out = {}
    for y in range(FIRST, LAST + 1):
        T = defaultdict(lambda: {'ret': 0.0, 'retmin': 0.0, 'tr': 0.0, 'trmin': 0.0, 'fr': 0.0})
        for pid, r in by[y].items():
            f = T[r['team']]
            p = by[y - 1].get(pid)
            if p and p['min_per']:
                share = float(p['min_per']) / 100
                v = share * float(p['bpm'] or 0)
                if p['team'] == r['team']:
                    f['ret'] += v; f['retmin'] += share / 5
                else:
                    f['tr'] += v; f['trmin'] += share / 5
            elif r['yr'] == 'Fr':
                f['fr'] += recruit_pts(r.get('on3rk'), r.get('rk247'))
        out[y] = {t: {k: round(v, 3) for k, v in f.items()} for t, f in T.items()}
    return out


def recruit_pts(*ranks):
    rk = [float(x) for x in ranks if x not in (None, '', 'nan') and float(x) > 0]
    return max(0.0, math.log(300 / min(rk))) if rk else 0.0


def team_prior_live(season, espn_bt=None):
    """the same features for the coming season from the board's frozen prior (scripts/cbb_prior.json.gz: each 2026-27
    player's ESPN team, Barttorvik team and past lines). Returns ({Barttorvik team: features}, {ESPN id: Barttorvik team},
    {ESPN id: board conference})"""
    import re
    d = json.load(gzip.open(os.path.join(HERE, 'cbb_prior.json.gz')))
    K = {k: i for i, k in enumerate(d['keep'])}
    ci = {k: i for i, k in enumerate(d['cols'])}
    T = defaultdict(lambda: {'ret': 0.0, 'retmin': 0.0, 'tr': 0.0, 'trmin': 0.0, 'fr': 0.0})
    bt, conf = {}, {}
    for row, c in zip(d['rows'], d['careers']):
        m = re.search(r'/(\d+)\.png', row[ci['logo']] or '')
        if not m:
            continue
        conf[m[1]] = row[ci['conf']]
        team = c.get('bt') or (espn_bt or {}).get(m[1])      # the board leaves a few schools unmatched; the games join knows them
        if not team:
            continue
        bt[m[1]] = team
        f = T[team]
        prev = [s for s in c['seasons'] if s[K['year']] == season - 1]
        if prev and prev[0][K['min_per']]:
            s = prev[0]; share = s[K['min_per']] / 100; v = share * (s[K['bpm']] or 0)
            if s[K['team']] == team:
                f['ret'] += v; f['retmin'] += share / 5
            else:
                f['tr'] += v; f['trmin'] += share / 5
        elif row[ci['cls']] == 'Fr' and c.get('rec'):
            f['fr'] += recruit_pts(c['rec'].get('on3rk'), c['rec'].get('rk247'))
    return {t: {k: round(v, 3) for k, v in f.items()} for t, f in T.items()}, bt, conf


# ---------------------------------------------------------------- ratings
class Ratings:
    """one season's ratings, walked a date at a time"""

    def __init__(self, teams, prior, P):
        self.P = P
        self.teams = list(teams) + [X]
        self.ix = {t: i for i, t in enumerate(self.teams)}
        n = self.n = len(self.teams)
        self.pO = np.array([prior.get(t, {}).get('O', -10.0 if t == X else -2.0) for t in self.teams])
        self.pD = np.array([prior.get(t, {}).get('D', -10.0 if t == X else -2.0) for t in self.teams])
        self.pT = np.array([prior.get(t, {}).get('T', 0.0) for t in self.teams])
        m = 2 * n + 2
        # the data side of both normal equations, decayed a day at a time (recent games weighted up) and grown by each
        # date's games; solve() adds the prior
        self.A, self.b, self.TA, self.Tb = np.zeros((m, m)), np.zeros(m), np.zeros((n + 1, n + 1)), np.zeros(n + 1)
        self.day = None
        self.nobs = 0
        self.O, self.D, self.T = self.pO.copy(), self.pD.copy(), self.pT.copy()
        self.mu, self.h, self.tau = P['mu0'], P['h0'], P['tau0']
        self.ng = defaultdict(int)

    def i(self, t):
        return self.ix.get(t, self.ix[X])

    def decay(self, day):
        if self.day is not None and self.P['hl'] and day > self.day:
            f = 0.5 ** ((day - self.day) / self.P['hl'])
            self.A *= f; self.b *= f; self.TA *= f; self.Tb *= f
        self.day = day

    def add(self, g, day):
        self.decay(day)
        n = self.n
        h, a = self.i(g['home']), self.i(g['away'])
        poss = g.get('poss') or (g['hs'] + g['as']) / 2.06
        loc = 0.0 if g['neutral'] else 1.0
        for off, dfn, pts, l in ((h, a, g['hs'], loc), (a, h, g['as'], -loc)):
            y = 100 * pts / poss
            idx = (off, n + dfn, 2 * n, 2 * n + 1)
            val = (1.0, -1.0, 1.0, l)
            for p in range(4):
                for q in range(4):
                    self.A[idx[p], idx[q]] += val[p] * val[q]
                self.b[idx[p]] += val[p] * y
        if g.get('poss'):
            for p in (h, a, n):
                for q in (h, a, n):
                    self.TA[p, q] += 1
                self.Tb[p] += poss
        self.nobs += 1
        self.ng[g['home']] += 1; self.ng[g['away']] += 1

    def solve(self, day):
        P, n = self.P, self.n
        lam = P['lam']
        if not self.nobs:
            return
        self.decay(day)
        m = 2 * n + 2
        pri = np.concatenate([self.pO, self.pD, [P['mu0'], P['h0']]])
        prec = np.concatenate([np.full(2 * n, lam), [0.01, 0.5]])
        prec[self.ix[X]] = prec[n + self.ix[X]] = 0.5
        s = np.linalg.solve(self.A + np.diag(prec), self.b + prec * pri)
        self.O, self.D, self.mu, self.h = s[:n], s[n:2 * n], s[2 * n], s[2 * n + 1]
        prec = np.concatenate([np.full(n, lam), [0.01]])
        s = np.linalg.solve(self.TA + np.diag(prec), self.Tb + prec * np.concatenate([self.pT, [P['tau0']]]))
        self.T, self.tau = s[:n], s[n]

    def net(self, t):
        k = self.i(t)
        return self.O[k] + self.D[k]

    def poss(self, h, a):
        return self.tau + self.T[self.i(h)] + self.T[self.i(a)]

    def game(self, h, a):
        H, A = self.i(h), self.i(a)
        P = self.poss(h, a)
        eh, ea = self.mu + self.O[H] - self.D[A], self.mu + self.O[A] - self.D[H]
        return (eh - ea) * P / 100, (eh + ea) * P / 100, P


class Walk:
    """every season in order: ratings, Elo, market ratings; feats() before a date's games, then they're added"""

    def __init__(self, P, tprior, btname, coefs=None):
        self.P, self.tprior, self.btname = P, tprior, btname
        self.elo = defaultdict(lambda: 1500.0)
        self.mkt, self.tm = defaultdict(float), defaultdict(float)
        self.tlg = 140.0
        self.final = {}                 # season -> team -> {O, D, T, net}
        self.pcoef = coefs or {}        # season -> prior coefficients
        self.prior_rows = []            # (season, team, features, target) for the prior regression

    def prior_feats(self, s, t, last):
        bt = self.btname.get(t)
        f = (self.tprior.get(str(s)) or self.tprior.get(s) or {}).get(bt) or {}
        L = last.get(t)
        ln = L['net'] if L else -8.0
        return {'one': 1.0, 'last': ln, 'lastret': ln * f.get('retmin', 0.0), 'ret': f.get('ret', 0.0), 'retmin': f.get('retmin', 0.0),
                'tr': f.get('tr', 0.0), 'trmin': f.get('trmin', 0.0), 'fr': f.get('fr', 0.0)}

    def prior_coef(self, s):
        if s in self.pcoef:
            return self.pcoef[s]
        R = [r for r in self.prior_rows if r[0] < s]
        if len({r[0] for r in R}) < 1:
            c = {k: 0.0 for k in PRIOR_F}; c['last'] = 0.6; c['one'] = -1.0
        else:
            Xp = np.array([[r[2][k] for k in PRIOR_F] for r in R]); y = np.array([r[3] for r in R])
            A = Xp.T @ Xp + np.diag([0.0] + [5.0] * (len(PRIOR_F) - 1))
            c = dict(zip(PRIOR_F, np.linalg.solve(A, Xp.T @ y)))
        self.pcoef[s] = c
        return c

    def season_prior(self, s, teams):
        last = self.final.get(s - 1, {})
        c = self.prior_coef(s)
        out, feats = {}, {}
        keep = self.P['split']
        for t in teams:
            f = self.prior_feats(s, t, last); feats[t] = f
            pn = sum(c[k] * f[k] for k in PRIOR_F)
            L = last.get(t)
            if L:
                d = pn - keep * (L['O'] + L['D'])
                out[t] = {'O': keep * L['O'] + d / 2, 'D': keep * L['D'] + d / 2, 'T': L['T'] * self.P['tcarry'], 'net': pn}
            else:
                out[t] = {'O': pn / 2, 'D': pn / 2, 'T': 0.0, 'net': pn}
        return out, feats

    def new_season(self, s):
        P = self.P
        for t in list(self.elo):
            self.elo[t] = 1500 + (self.elo[t] - 1500) * P['ecarry']
        for t in list(self.mkt):
            self.mkt[t] *= P['mrev']
        for t in list(self.tm):
            self.tm[t] = 0.0

    def market(self, g):
        L = -g['spread'] if g.get('spread') is not None else None
        h, a = g['home'], g['away']
        if L is not None:
            e = L - (self.mkt[h] - self.mkt[a] + (0 if g['neutral'] else 3.0))
            self.mkt[h] += self.P['mk'] * e; self.mkt[a] -= self.P['mk'] * e
        if g.get('total'):
            e = g['total'] - (self.tlg + self.tm[h] + self.tm[a])
            self.tm[h] += self.P['tk'] * e; self.tm[a] += self.P['tk'] * e; self.tlg += 0.005 * e

    def elo_update(self, g):
        h, a = g['home'], g['away']
        hfa = 0 if g['neutral'] else self.P['ehfa']
        d = self.elo[h] - self.elo[a] + hfa
        exp = 1 / (1 + 10 ** (-d / 400))
        m = g['hs'] - g['as']
        res = 1.0 if m > 0 else 0.0
        mult = math.log(abs(m) + 1) * 2.2 / ((d if m > 0 else -d) * 0.001 + 2.2)
        k = self.P['K'] * mult * (res - exp)
        self.elo[h] += k; self.elo[a] -= k


def season_walk(W, s, games, d1, av, collect, live_prior=None, upto=None):
    """walk one season's games (sorted by date). collect(g, x, tx, R) is called for every game before its date is
    added. Returns the Ratings at the end."""
    P = W.P
    W.new_season(s)
    teams = sorted(d1)
    if live_prior is not None:
        pri, pfeats = live_prior
    else:
        pri, pfeats = W.season_prior(s, teams)
    R = Ratings(teams, pri, P)
    btn = W.btname
    av = av or {}
    by_day = defaultdict(list)
    for g in games:
        by_day[et_date(g['date'])].append(g)
    day0 = datetime(s - 1, 11, 1)
    lastday = {}                      # team -> ordinal of its last game
    resid = defaultdict(list)         # team -> recent (margin - eff expectation), own side
    for d in sorted(by_day):
        if upto and d > upto:
            break
        day = (datetime.strptime(d, '%Y-%m-%d') - day0).days
        R.solve(day)
        for g in by_day[d]:
            h, a = g['home'], g['away']
            m, tot, poss = R.game(h, a)
            home = 0.0 if g['neutral'] else 1.0
            ph, pa = pri.get(h, {}).get('net', -8.0), pri.get(a, {}).get('net', -8.0)
            ng = min(R.ng[h], R.ng[a])
            rest = lambda t: max(1, min(7, day - lastday[t])) if t in lastday else 7
            ih = av.get((btn.get(h), d), av.get((btn.get(h), 'next'), 0.0) if g.get('hs') is None else 0.0)
            ia = av.get((btn.get(a), d), av.get((btn.get(a), 'next'), 0.0) if g.get('hs') is None else 0.0)
            fr = lambda t: sum(resid[t][-5:]) / max(1, len(resid[t][-5:]))
            post = 1.0 if (g.get('stype') == 3 or 'tournament' in (g.get('note') or '').lower() or 'championship' in (g.get('note') or '').lower()) else 0.0
            x = {'eff': m, 'elo': (W.elo[h] - W.elo[a]) / 25, 'mkt': W.mkt[h] - W.mkt[a], 'home': home,
                 'inj': (ia - ih) * poss / 100, 'rest': rest(h) - rest(a), 'confh': home * (1.0 if g.get('conf') else 0.0),
                 'alt': home * (1.0 if h in ALT else 0.0), 'early': (ph - pa) * poss / 100 * max(0.0, 1 - ng / 10),
                 'tourn': post * m, 'form': fr(h) - fr(a), 'mkteff': (W.mkt[h] - W.mkt[a]) * max(0.0, 1 - ng / 10)}
            tx = {'efft': tot, 'tmkt': W.tlg + W.tm[h] + W.tm[a], 'one': 1.0}
            collect(g, x, tx, R)
        for g in by_day[d]:
            W.market(g)
            if g.get('hs') is None:
                continue
            m, _, _ = R.game(g['home'], g['away'])
            hc = (R.h * 2) * R.poss(g['home'], g['away']) / 100 if not g['neutral'] else 0.0
            r = (g['hs'] - g['as']) - (m + hc)
            resid[g['home']].append(r); resid[g['away']].append(-r)
            W.elo_update(g)
            R.add(g, day)
            lastday[g['home']] = lastday[g['away']] = day
    if not upto:
        R.solve((datetime(s, 4, 10) - day0).days)
        W.final[s] = {t: {'O': float(R.O[R.ix[t]]), 'D': float(R.D[R.ix[t]]), 'T': float(R.T[R.ix[t]]),
                          'net': float(R.O[R.ix[t]] + R.D[R.ix[t]])} for t in teams}
        for t in teams:
            if t in pfeats and R.ng[t] >= 15:
                W.prior_rows.append((s, t, pfeats[t], W.final[s][t]['net']))
    return R, pri, pfeats


DEFAULT = {'hl': 45.0, 'lam': 4.0, 'mu0': 103.0, 'h0': 1.4, 'tau0': 68.0, 'split': 0.5, 'tcarry': 0.6, 'ecarry': 0.6,
           'mrev': 0.0, 'mk': 0.15, 'tk': 0.2, 'K': 25.0, 'ehfa': 80.0}


def run_walk(P, games, tprior, btname, d1s, av_by_season, seasons=None):
    """the full history walk: rows of (game, x, tx) for every game with a result"""
    W = Walk(P, tprior, btname)
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    out = []
    for s in sorted(by_s):
        if seasons and s not in seasons:
            continue
        gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))
        season_walk(W, s, gs, d1s[s], av_by_season.get(s), lambda g, x, tx, R: out.append((g, x, tx)) if g.get('hs') is not None else None)
    return W, out


# ---------------------------------------------------------------- fit
def load_all():
    games = load_hist()
    btname = bt_map(games)
    by = defaultdict(list)
    for g in games:
        by[g['season']].append(g)
    d1s = {s: d1_set(v) for s, v in by.items()}
    if not os.path.exists(TPRIOR):
        tp = team_prior_hist()
        with open(TPRIOR, 'w') as f:
            json.dump(tp, f, separators=(',', ':'))
    tprior = json.load(open(TPRIOR))
    avc = os.path.join(CACHE, 'avail.json.gz')
    if os.path.exists(avc):
        avs = {int(s): {tuple(k.split('|')): v for k, v in d.items()} for s, d in json.load(gzip.open(avc)).items()}
    else:
        avs = {}
        for s in sorted(by):
            avs[s] = avail(bt_logs(s))
            print('avail', s, len(avs[s]), flush=True)
        with gzip.open(avc, 'wt') as f:
            json.dump({s: {'|'.join(k): v for k, v in d.items()} for s, d in avs.items()}, f)
    return games, btname, d1s, tprior, avs


def matrices(rows, feats, tfeats=TFEATS):
    D = [(g, x, tx) for g, x, tx in rows if g['season'] >= FIRST + 1]
    Xm = np.array([[x[f] for f in feats] for _, x, _ in D]); y = np.array([g['hs'] - g['as'] for g, _, _ in D], float)
    TX = np.array([[tx[f] for f in tfeats] for _, _, tx in D]); ty = np.array([g['hs'] + g['as'] for g, _, _ in D], float)
    S = np.array([g['season'] for g, _, _ in D])
    line = np.array([-g['spread'] if g.get('spread') is not None else np.nan for g, _, _ in D])
    tline = np.array([g['total'] if g.get('total') else np.nan for g, _, _ in D])
    d1 = np.array([g['home'] != X and g['away'] != X and 'hb' in g for g, _, _ in D])
    return D, Xm, y, TX, ty, S, line, tline, d1


def walk_pred(Xm, y, S, d1, first=SCORE0, ridge=0.0):
    """each season from the seasons before it (D-I games only in training)"""
    pred = np.full(len(y), np.nan)
    for s in range(first, LAST + 1):
        tr, te = (S < s) & d1, S == s
        if not te.any():
            continue
        A = Xm[tr].T @ Xm[tr] + ridge * np.eye(Xm.shape[1])
        pred[te] = Xm[te] @ np.linalg.solve(A, Xm[tr].T @ y[tr])
    return pred


def paired_t(a, b):
    d = a - b
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 else 0.0


def ml_prob(mlh, mla):
    """no-vig home win chance from both moneylines"""
    imp = lambda o: 100 / (o + 100) if o > 0 else -o / (-o + 100)
    a, b = imp(mlh), imp(mla)
    return a / (a + b)


def fit():
    t0 = time.time()
    games, btname, d1s, tprior, avs = load_all()
    print('loaded', len(games), f'{time.time() - t0:.0f}s', flush=True)

    def score(P, feats):
        W, rows = run_walk(P, games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = matrices(rows, feats)
        pred = walk_pred(Xm, y, S, d1)
        k = (S >= SCORE0) & (S <= TUNE_END) & d1 & ~np.isnan(pred)
        return float(np.mean(np.abs(pred[k] - y[k]))), W, rows

    # 1. rating memory, tuned on 2016-20 margin error with the base inputs, one knob at a time from the defaults
    #    (coordinate search, two passes); 2021-26 is never looked at here
    P = dict(DEFAULT)
    if '--keep-params' in sys.argv and os.path.exists(FIT):
        # reuse the last tuning (the grid is the slow part); everything after it reruns
        P = json.load(open(FIT))['params']
        log = json.load(open(FIT))['grid']
        W, rows = run_walk(P, games, tprior, btname, d1s, avs)
        return after_tune(P, W, rows, log)
    grid = {'hl': [0.0, 30.0, 45.0, 70.0], 'lam': [2.0, 4.0, 8.0], 'K': [15.0, 25.0, 40.0], 'ecarry': [0.4, 0.6, 0.8],
            'mk': [0.08, 0.15, 0.25], 'mrev': [0.0, 0.3], 'split': [0.3, 0.5, 0.7]}
    log = []
    best, _, _ = score(P, BASE)
    log.append([round(best, 4), dict(P)]); print('base', round(best, 4), flush=True)
    for rnd in range(2):
        changed = False
        for k, vals in grid.items():
            for v in vals:
                if v == P[k]:
                    continue
                Q = dict(P, **{k: v})
                e, _, _ = score(Q, BASE)
                log.append([round(e, 4), {k: v}]); print(rnd, k, v, round(e, 4), flush=True)
                if e < best - 1e-4:
                    best, P, changed = e, Q, True
        if not changed:
            break
    print('tuned', P, round(best, 4), f'{time.time() - t0:.0f}s', flush=True)
    W, rows = run_walk(P, games, tprior, btname, d1s, avs)
    return after_tune(P, W, rows, log)


def after_tune(P, W, rows, log):
    D, Xa, y, TX, ty, S, line, tline, d1 = matrices(rows, BASE + CANDS)
    col = {f: i for i, f in enumerate(BASE + CANDS)}
    tune = (S >= SCORE0) & (S <= TUNE_END) & d1
    held = (S > TUNE_END) & d1

    def pr(feats):
        return walk_pred(Xa[:, [col[f] for f in feats]], y, S, d1)

    # 2. candidates: forward selection on 2016-20 absolute error, a candidate kept only at paired t <= -1.5;
    #    2021-26 reported for each, never used to choose
    feats = list(BASE)
    base = pr(feats)
    cand_log = []
    while True:
        tries = []
        for c in CANDS:
            if c in feats:
                continue
            p = pr(feats + [c])
            e0, e1 = np.abs(base - y), np.abs(p - y)
            tries.append((paired_t(e1[tune], e0[tune]), c, p,
                          {'cand': c, 'with': feats + [c], 'tuneMae': round(float(e1[tune].mean()), 4), 'baseMae': round(float(e0[tune].mean()), 4),
                           't': round(paired_t(e1[tune], e0[tune]), 2), 'heldMae': round(float(e1[held].mean()), 4),
                           'heldBase': round(float(e0[held].mean()), 4), 'heldT': round(paired_t(e1[held], e0[held]), 2)}))
        if not tries:
            break
        tries.sort(key=lambda z: z[0])
        cand_log.extend(z[3] for z in tries)
        for z in tries:
            print('cand', z[3], flush=True)
        if tries[0][0] > -1.5:
            break
        feats.append(tries[0][1]); base = tries[0][2]
        print('kept', tries[0][1], flush=True)
    # each core input taken out, same test: one whose removal cuts 2016-20 error at t <= -1.5 is dropped (worst first,
    # then the rest re-tested), so the core earns its place the way a candidate does
    drop_log = []
    while True:
        tries = []
        for f in BASE:
            if f not in feats or f == 'eff':
                continue
            p = pr([z for z in feats if z != f])
            e0, e1 = np.abs(base - y), np.abs(p - y)
            tries.append((paired_t(e1[tune], e0[tune]), f, p, {'drop': f, 'without': [z for z in feats if z != f], 't': round(paired_t(e1[tune], e0[tune]), 2),
                                                               'heldT': round(paired_t(e1[held], e0[held]), 2)}))
        tries.sort(key=lambda z: z[0])
        drop_log.extend(z[3] for z in tries)
        if not tries or tries[0][0] > -1.5:
            break
        feats.remove(tries[0][1]); base = tries[0][2]
        print('dropped', tries[0][1], flush=True)
    pred = base
    return P, W, rows, log, feats, pred, cand_log, drop_log, (D, Xa, y, TX, ty, S, line, tline, d1, col)


def report():
    P, W, rows, log, feats, pred, cand_log, drop_log, M = fit()
    D, Xa, y, TX, ty, S, line, tline, d1, col = M
    Xm = Xa[:, [col[f] for f in feats]]
    tpred = walk_pred(TX, ty, S, d1)
    ok = ~np.isnan(pred) & d1
    tune = ok & (S <= TUNE_END); held = ok & (S > TUNE_END)
    mlh = np.array([g.get('mlh') or np.nan for g, _, _ in D]); mla = np.array([g.get('mla') or np.nan for g, _, _ in D])
    pm = np.array([ml_prob(a, b) if a == a and b == b else np.nan for a, b in zip(mlh, mla)])
    win = (y > 0).astype(float)

    # win probability: sd of a normal around the margin, by maximum likelihood on 2016-20 (and checked on 2021-26)
    def ll(p, k):
        p = np.clip(p, 1e-4, 1 - 1e-4)
        return float(-np.mean(win[k] * np.log(p[k]) + (1 - win[k]) * np.log(1 - p[k])))
    Phi = np.vectorize(phi)
    k = tune & (y != 0)
    sds = np.arange(9.0, 14.01, 0.1)
    sd = float(sds[np.argmin([ll(Phi(pred / s), k) for s in sds])])
    pw = Phi(pred / sd)
    # blend with the market's line (share of the model's edge that holds up), fit on 2016-20
    has = ~np.isnan(line)
    ws = np.arange(0, 1.01, 0.05)
    wb = float(ws[np.argmin([np.mean(np.abs(w * pred[tune & has] + (1 - w) * line[tune & has] - y[tune & has])) for w in ws])])

    def block(k):
        k = k & has
        e = pred[k] - line[k]; r = y[k] - line[k]
        res = {'games': int(k.sum()), 'maeModel': round(float(np.mean(np.abs(pred[k] - y[k]))), 3),
               'maeLine': round(float(np.mean(np.abs(line[k] - y[k]))), 3),
               'maeBlend': round(float(np.mean(np.abs(wb * pred[k] + (1 - wb) * line[k] - y[k]))), 3),
               'tVsLine': round(paired_t(np.abs(pred[k] - y[k]), np.abs(line[k] - y[k])), 2),
               'rModelVsLine': round(float(np.corrcoef(pred[k], line[k])[0, 1]), 3),
               'edgeSlope': round(float(np.polyfit(e, r, 1)[0]), 3)}
        for th in (1, 2, 3, 4):
            pick = (np.abs(e) >= th) & (r != 0)
            n = int(pick.sum())
            res[f'ats{th}'] = {'n': n, 'pct': round(float((np.sign(e[pick]) == np.sign(r[pick])).mean()), 3) if n else None}
        km = k & ~np.isnan(pm) & (y != 0)
        res['llModel'], res['llMarket'], res['mlGames'] = ll(pw, km), ll(pm, km), int(km.sum())
        res['llModel'] = round(res['llModel'], 4); res['llMarket'] = round(res['llMarket'], 4)
        kt = k & ~np.isnan(tline) & ~np.isnan(tpred)
        res['totalMaeModel'] = round(float(np.mean(np.abs(tpred[kt] - ty[kt]))), 3)
        res['totalMaeLine'] = round(float(np.mean(np.abs(tline[kt] - ty[kt]))), 3)
        return res

    test = {'2016-20 (tuning)': block(tune), '2021-26 (held out)': block(held), 'all 2016-26': block(ok)}
    by_season = {int(s): block(ok & (S == s)) for s in range(SCORE0, LAST + 1)}
    # calibration: model win chance in bins against how often the side won, held out
    cal = []
    kk = held & (y != 0)
    for lo in np.arange(0.5, 1.0, 0.05):
        fav = np.maximum(pw, 1 - pw)
        b = kk & (fav >= lo) & (fav < lo + 0.05)
        if b.sum():
            won = np.where(pw[b] >= 0.5, win[b], 1 - win[b])
            cal.append({'bin': round(float(lo), 2), 'n': int(b.sum()), 'model': round(float(fav[b].mean()), 3), 'won': round(float(won.mean()), 3)})
    # final weights on every D-I season
    tr = ok | ((S < SCORE0) & d1 & (S > FIRST))
    b = np.linalg.lstsq(Xm[tr], y[tr], rcond=None)[0]
    res = y[tr] - Xm[tr] @ b; cov = (res @ res / (tr.sum() - len(b))) * np.linalg.inv(Xm[tr].T @ Xm[tr])
    tb = np.linalg.lstsq(TX[tr], ty[tr], rcond=None)[0]
    tsd = float(np.std((tpred - ty)[ok & ~np.isnan(tpred)]))
    # the preseason prior: walk-forward fit (each season's weights from the seasons before) against the season's final rating
    pri = W.prior_rows
    pr_test = []
    for s in range(SCORE0, LAST + 1):
        c = W.pcoef.get(s)
        R = [r for r in pri if r[0] == s]
        if not c or not R:
            continue
        p = np.array([sum(c[k] * r[2][k] for k in PRIOR_F) for r in R]); t = np.array([r[3] for r in R])
        l = np.array([r[2]['last'] for r in R])
        pr_test.append({'season': s, 'teams': len(R), 'rPrior': round(float(np.corrcoef(p, t)[0, 1]), 3), 'rLast': round(float(np.corrcoef(l, t)[0, 1]), 3),
                        'maePrior': round(float(np.mean(np.abs(p - t))), 2)})
    pc = W.prior_coef(LAST + 1)
    out = {'params': P, 'feats': feats, 'coef': {f: round(float(v), 4) for f, v in zip(feats, b)},
           't': {f: round(float(v / math.sqrt(cov[i, i])), 1) for i, (f, v) in enumerate(zip(feats, b))},
           'tcoef': {f: round(float(v), 4) for f, v in zip(TFEATS, tb)}, 'sd': round(sd, 2), 'tsd': round(tsd, 2), 'blend': wb,
           'prior': {k: round(float(v), 4) for k, v in pc.items()}, 'priorTest': pr_test,
           'test': test, 'bySeason': by_season, 'calib': cal, 'select': cand_log, 'drop': drop_log,
           'grid': log, 'seasons': [SCORE0, LAST], 'tune': [SCORE0, TUNE_END]}
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    # the state the daily build starts the next season from
    st = {'elo': {t: round(v, 1) for t, v in W.elo.items()}, 'mkt': {t: round(v, 2) for t, v in W.mkt.items()}, 'tlg': round(W.tlg, 2),
          'final': {t: {k: round(v, 3) for k, v in r.items()} for t, r in W.final[LAST].items()}, 'season': LAST}
    with open(STATE, 'w') as f:
        json.dump(st, f, separators=(',', ':'))
    # walk-forward predictions for the picks backtest (scripts/cbb_picks.py --backtest)
    bt = [{'id': g['id'], 'S': int(s), 'm': round(float(m), 2), 'L': (None if np.isnan(l) else float(l)), 'res': int(r),
           'mlH': g.get('mlh'), 'mlA': g.get('mla'), 'open': (-g['open'] if g.get('open') is not None else None)}
          for (g, _, _), m, s, l, r, kk in zip(D, pred, S, line, y, ok) if kk]
    with gzip.open(os.path.join(CACHE, 'walk_pred.json.gz'), 'wt') as f:
        json.dump(bt, f)
    print(json.dumps({k: v for k, v in out.items() if k not in ('grid', 'select', 'bySeason')}, indent=1))


if __name__ == '__main__':
    if '--fit' in sys.argv:
        report()
    else:
        import cbb_games_live
        cbb_games_live.build()
