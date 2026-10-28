#!/usr/bin/env python3
"""Tennis ratings (the TENNIS ARKBOARD's ARK Ranking and match chances): one pass over every ATP and WTA singles
match since 2005 (scripts/tennis_data.py), all levels.

Two parts, blended in log-odds:
  - Elo on wins (FiveThirtyEight's tennis form): every player starts at START; K = KC / (matches + KO) ** KS, so a
    newcomer moves fast and a veteran slowly. One overall rating and one per surface (hard, clay, grass), each with
    its own match count; a match's surface chance blends the two (SW = the surface share).
  - Points: opponent-adjusted serve and return strength from the serve statistics (points won on serve), a Kalman
    filter per player in log-odds (variance V0 at the start, drifting back up by Q a day off court, each match's
    points counted at PHI of their binomial information since points within a match are not independent). A match
    chance comes from both players' serve-point chances through the game / tiebreak / set / match Markov chain
    (best of 3 or 5).
Match chances add context terms beside the ratings (CTX: rest, age, head-to-head, matches in the last 30 days, the
market's memory of the player's recent closes). The rating parameters are tuned on tour-level main draws 2012-22; the
blend weights are a logistic regression on the last WIN seasons, and every score (2012+, held out 2023+, against the
feed's no-vig close 2025+) is walk-forward, each season from weights fit on the seasons before it.

    python3 scripts/tennis_model.py --fit     # tune, walk-forward scores, the close -> data/tennis_fit.json
    python3 scripts/tennis_model.py           # build data/tennis.json (ARK Ranking, metrics, matches) with the fit params
"""
import datetime as dt
import gzip
import json
import math
import os
import sys
import time
import urllib.parse
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

FIT = os.path.join(ROOT, 'data', 'tennis_fit.json')
SURFS = ('H', 'C', 'G')
TOUR_LV = ('G', 'M', 'A', 'F', 'O')          # scored: tour-level main draws (team events left out)
RDAY = {'Q1': -3, 'Q2': -2, 'Q3': -1, 'Q4': -1, 'R128': 0, 'R64': 1, 'R32': 2, 'R16': 4, 'RR': 3, 'QF': 5, 'SF': 6,
        'BR': 6, 'F': 7}

DEFAULT = {'START': 1500.0, 'KC': 250.0, 'KO': 5.0, 'KS': 0.4, 'SW': 0.5, 'RET': 0.5,
           'V0': 0.10, 'Q': 0.00010, 'PHI': 0.35, 'MU_LR': 0.002,
           'KG': 0.0, 'GSW': 0.3, 'KLV_S': 1.0, 'KLV_G': 1.0,
           'A': 1.0, 'B': 0.0, 'C': 0.0, 'G': 0.0, 'CR': 0.0, 'CA': 0.0, 'CH': 0.0, 'CN': 0.0, 'CM': 0.0}
# match-context terms beside the ratings (Oct 28 2026; held out 2023-26 log loss t -6.2 by tournament, 4/4 seasons, 11/11
# tuning years left out), each player A minus player B: CR rest (log of days since the last match, capped at 60), CA age
# ((age - 26) / 5: Elo lags a young player's rise and an old player's fall), CH head-to-head lead ((wins - losses) /
# (meetings + 4)), CN matches in the last 30 days / 5 (match play and form). CM market memory: the mean of the player's
# last 8 closing lines minus the model's chance (logits, 120 days, shrunk by 3) from the feed's no-vig closes (2025+);
# it predicts the open-to-close move beside the model (2026 held out t 5.8) and lifts held-out pick CLV
CTX = ('CR', 'CA', 'CH', 'CN', 'CM')
WIN = 3                  # blend weights fit on the last WIN seasons (a 3-season window beat the expanding 2012+ fit 9/9
                         # seasons 2018-26 walk forward: favourites have run a little less sure in recent seasons)


def sig(x):
    return 1.0 / (1.0 + math.exp(-x)) if x > -40 else 0.0


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def ymd(d):
    return dt.date(d // 10000, d // 100 % 100, d % 100)


DAY0 = dt.date(2000, 1, 1)


def dnum(d, rd=''):
    return (ymd(d) - DAY0).days + RDAY.get(rd, 2)


# ---------------------------------------------------------------- Markov chain: serve-point chances -> match chance
def p_game(p):
    q = 1 - p
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * p * p / (1 - 2 * p * q)


def p_tiebreak(pa, pb, first=7):
    """A serves the first point, then two each; first to `first` by two"""
    from functools import lru_cache as _c

    @_c(None)
    def f(a, b):
        if a >= first and a - b >= 2: return 1.0
        if b >= first and b - a >= 2: return 0.0
        if a >= first - 1 and b >= first - 1 and a == b:
            # deuce-like: from level, the next two points are one serve each (A, B or B, A): win both / split
            pa2 = pa * (1 - pb)                  # A wins both (one on A's serve, one on B's)
            pb2 = (1 - pa) * pb
            return pa2 / (pa2 + pb2) if pa2 + pb2 > 0 else 0.5
        n = a + b
        a_serves = (n % 4 == 0) or (n % 4 == 3)
        w = pa if a_serves else 1 - pb
        return w * f(a + 1, b) + (1 - w) * f(a, b + 1)
    return f(0, 0)


@lru_cache(maxsize=None)
def p_set_first(pa, pb):
    """P(A wins a set) with A serving first"""
    ga, gb = p_game(pa), p_game(pb)
    tb = p_tiebreak(pa, pb)

    @lru_cache(None)
    def f(a, b):
        if a >= 6 and a - b >= 2: return 1.0
        if b >= 6 and b - a >= 2: return 0.0
        if a == 6 and b == 6: return tb if (a + b) % 2 == 0 else 1 - p_tiebreak(pb, pa)
        a_serves = (a + b) % 2 == 0
        w = ga if a_serves else 1 - gb
        return w * f(a + 1, b) + (1 - w) * f(a, b + 1)
    return f(0, 0)


@lru_cache(maxsize=None)
def p_match_pts(pa, pb, bo=3):
    """P(A wins the match) from A's and B's serve-point chances (rounded by the caller), sets independent, serving
    first or second equally likely"""
    s = 0.5 * (p_set_first(pa, pb) + 1 - p_set_first(pb, pa))
    need = 2 if bo == 3 else 3
    return p_sets(s, need)


def p_sets(s, need):
    """first to `need` sets, each won with chance s"""
    tot = 0.0
    for k in range(need):          # opponent wins k sets
        tot += math.comb(need - 1 + k, k) * s ** need * (1 - s) ** k
    return tot


def set_from_match3(p):
    """the per-set chance s that gives a best-of-3 chance p (inverts p = s^2 (3 - 2s))"""
    lo, hi = 0.0, 1.0
    for _ in range(40):
        m = (lo + hi) / 2
        if m * m * (3 - 2 * m) < p: lo = m
        else: hi = m
    return (lo + hi) / 2


def bo5(p3):
    return p_sets(set_from_match3(p3), 3)


def rnd(p, g=0.004):
    return round(min(max(p, 0.30), 0.90) / g) * g


# ---------------------------------------------------------------- score parsing
def games(score):
    """(games won by the winner, by the loser, retired?) from a score like '6-3 6-7(5) 7-6(10-8) RET'"""
    w = l = 0
    ret = False
    for tok in str(score).split():
        t = tok.upper()
        if t in ('RET', 'RET.', 'DEF', 'ABD', 'W/O', 'UNP'): ret = True; continue
        a = t.split('(')[0].replace('[', '').replace(']', '')
        if '-' not in a: continue
        x, y = a.split('-', 1)
        try:
            w += int(x); l += int(y)
        except ValueError:
            continue
    return w, l, ret


# ---------------------------------------------------------------- the pass
@lru_cache(None)
def _bios():
    import tennis_data as T
    try:
        with gzip.open(T.PLAYERS, 'rt') as fh:
            return json.load(fh)
    except OSError:
        return {}


def bios():
    return _bios()


class Model:
    """one pass's state; also keeps each player's peak and 90-day-old rating for the ranking table"""
    def __init__(self, P=None):
        self.P = dict(DEFAULT, **(P or {}))
        self.elo = {}          # pid -> [overall, n, {surf: [r, n]}]
        self.pt = {}           # pid -> [s, vs, r, vr, last day]
        self.mu = {}           # (tour, surf) -> league log-odds of a serve point
        self.last = {}         # pid -> last match day number
        self.nm = {}           # pid -> matches (all levels)
        self.peak = {}         # pid -> (best overall Elo after 20+ matches, its date)
        self.gr = {}           # pid -> [games rating (log-odds of a game), n, {surf: [r, n]}]
        self.days = {}         # pid -> last 16 match days (rest, matches in 30 days)
        self.h2h = {}          # (a, b) -> a's wins over b
        self.mres = {}         # pid -> last 8 (day, close minus model in logits, the player's side)
        self.born = {}         # pid -> birth day number, from the bios
        self.set_bios()

    def set_bios(self, players=None):
        if players is None:
            players = bios()
        for pid, b in players.items():
            d = b.get('dob')
            if d and 19000000 < int(d) < 21000000:
                try:
                    self.born[pid] = (ymd(int(d)) - DAY0).days
                except ValueError:
                    pass

    def ctx(self, a, b, day):
        """the match-context terms (CTX order), A minus B"""
        def one(p):
            ds = self.days.get(p, [])
            rest = min(max(day - ds[-1], 0), 60) if ds else 60
            n30 = sum(1 for x in ds if 0 <= day - x <= 30)
            age = (day - self.born[p]) / 365.25 if p in self.born else 26.0
            mr = [z for d_, z in self.mres.get(p, []) if day - d_ <= 120]
            return math.log1p(rest), (age - 26) / 5, n30 / 5, sum(mr) / (len(mr) + 3)
        fa, fb = one(a), one(b)
        wa, wb = self.h2h.get((a, b), 0), self.h2h.get((b, a), 0)
        return [fa[0] - fb[0], fa[1] - fb[1], (wa - wb) / (wa + wb + 4), fa[2] - fb[2], fa[3] - fb[3]]

    # Elo
    def _e(self, pid):
        e = self.elo.get(pid)
        if e is None:
            e = self.elo[pid] = [self.P['START'], 0, {s: [self.P['START'], 0] for s in SURFS}]
        return e

    def elo_p(self, a, b, sf):
        ea, eb = self._e(a), self._e(b)
        w = self.P['SW']
        ra = (1 - w) * ea[0] + w * ea[2][sf][0]
        rb = (1 - w) * eb[0] + w * eb[2][sf][0]
        return 1 / (1 + 10 ** ((rb - ra) / 400))

    def _k(self, n):
        return self.P['KC'] / (n + self.P['KO']) ** self.P['KS']

    def elo_update(self, w, l, sf, mult=1.0):
        ew, el = self._e(w), self._e(l)
        for get in (lambda e: e, lambda e: e[2][sf]):
            a, b = get(ew), get(el)
            p = 1 / (1 + 10 ** ((b[0] - a[0]) / 400))
            a0, b0 = a[0], b[0]
            a[0] = a0 + mult * self._k(a[1]) * (1 - p)
            b[0] = b0 - mult * self._k(b[1]) * (1 - p)
            a[1] += 1; b[1] += 1

    # games won (log-odds of winning a game against the opponent)
    def _g(self, pid):
        g = self.gr.get(pid)
        if g is None:
            g = self.gr[pid] = [0.0, 0, {s: [0.0, 0] for s in SURFS}]
        return g

    def games_x(self, a, b, sf):
        ga, gb = self._g(a), self._g(b)
        w = self.P['GSW']
        return (1 - w) * (ga[0] - gb[0]) + w * (ga[2][sf][0] - gb[2][sf][0])

    def games_update(self, w, l, sf, gw, gl):
        if gw + gl < 6 or not self.P['KG']: return
        share = gw / (gw + gl)
        gW, gL = self._g(w), self._g(l)
        for get in (lambda g: g, lambda g: g[2][sf]):
            a, b = get(gW), get(gL)
            e = sig(a[0] - b[0])
            k = self.P['KG'] / (min(a[1], b[1]) + 5) ** 0.4
            a[0] += k * (share - e); b[0] -= k * (share - e)
            a[1] += 1; b[1] += 1

    # points
    def _pt(self, pid, day):
        x = self.pt.get(pid)
        if x is None:
            x = self.pt[pid] = [0.0, self.P['V0'], 0.0, self.P['V0'], day]
        else:
            gap = max(0, day - x[4])
            if gap:
                x[1] = min(self.P['V0'], x[1] + self.P['Q'] * gap)
                x[3] = min(self.P['V0'], x[3] + self.P['Q'] * gap)
                x[4] = day
        return x

    def mu_of(self, tour, sf):
        return self.mu.get((tour, sf), 0.60 if tour == 'atp' else 0.25)

    def serve_p(self, a, b, tour, sf, day):
        """A's chance of winning a point on serve against B"""
        xa, xb = self._pt(a, day), self._pt(b, day)
        return sig(self.mu_of(tour, sf) + xa[0] - xb[2])

    def pt_update(self, srv, ret, won, n, tour, sf, day):
        if n <= 0: return
        xs, xr = self._pt(srv, day), self._pt(ret, day)
        m = self.mu_of(tour, sf)
        p = sig(m + xs[0] - xr[2])
        info = self.P['PHI'] * n * p * (1 - p)
        if info <= 0: return
        resid = (won - n * p) / (n * p * (1 - p))       # log-odds residual
        tot = xs[1] + xr[3] + 1 / info
        gs, gr = xs[1] / tot, xr[3] / tot
        xs[0] += gs * resid
        xr[2] -= gr * resid
        xs[1] *= (1 - gs)
        xr[3] *= (1 - gr)
        self.mu[(tour, sf)] = m + self.P['MU_LR'] * resid * min(1.0, n / 80)

    def pts_p(self, a, b, tour, sf, day, bo):
        pa = self.serve_p(a, b, tour, sf, day)
        pb = self.serve_p(b, a, tour, sf, day)
        return p_match_pts(rnd(pa), rnd(pb), bo)

    def predict(self, a, b, tour, sf, day, bo=3, match=True):
        """P(A beats B): (blend, elo part, points part, games part, context terms). match=False leaves the context
        terms out (a rating against a reference player, the ARK Ranking)"""
        pe = self.elo_p(a, b, sf)
        if bo == 5: pe = bo5(pe)
        pp = self.pts_p(a, b, tour, sf, day, bo)
        gx = self.games_x(a, b, sf)
        z = self.P['A'] * logit(pe) + self.P['B'] * logit(pp) + self.P['G'] * gx * (1.25 if bo == 5 else 1.0)
        cx = self.ctx(a, b, day) if match else [0.0] * len(CTX)
        z += sum(self.P[k] * v for k, v in zip(CTX, cx))
        return sig(z), pe, pp, gx, cx

    def update(self, r):
        d, tour, lv, sf, rd, bo, tid, w, l, score, ws, ls = r[:12]
        day = dnum(d, rd)
        gw, gl, ret = games(score)
        if len(r) > 14 and r[14] and 0 < r[14] < 1:
            # market memory: the close against the ratings alone (no context terms), before this match's update
            pe = self.elo_p(w, l, sf)
            if bo == 5: pe = bo5(pe)
            zb = self.P['A'] * logit(pe) + self.P['B'] * logit(self.pts_p(w, l, tour, sf, day, bo)) + \
                self.P['G'] * self.games_x(w, l, sf) * (1.25 if bo == 5 else 1.0)
            z = logit(r[14]) - zb
            for p, v in ((w, z), (l, -z)):
                q = self.mres.setdefault(p, [])
                q.append((day, v))
                del q[:-8]
        for p in (w, l):
            q = self.days.setdefault(p, [])
            q.append(day)
            del q[:-16]
        self.h2h[(w, l)] = self.h2h.get((w, l), 0) + 1
        mult = (self.P['RET'] if ret else 1.0) * (self.P['KLV_S'] if lv == 'S' else self.P['KLV_G'] if lv == 'G' else 1.0)
        self.elo_update(w, l, sf, mult)
        if not ret: self.games_update(w, l, sf, gw, gl)
        if ws and ls:
            self.pt_update(w, l, ws[2] + ws[3], ws[0], tour, sf, day)
            self.pt_update(l, w, ls[2] + ls[3], ls[0], tour, sf, day)
        for p in (w, l):
            self.last[p] = day
            self.nm[p] = self.nm.get(p, 0) + 1
            e = self.elo[p]
            if e[1] >= 20 and e[0] > self.peak.get(p, (0, 0))[0]: self.peak[p] = (e[0], d)


def run(rows, P=None, score=None, until=None):
    """one pass; score(r) -> True records (row, blend, elo, points) for that match before updating"""
    m = Model(P)
    out = []
    for r in rows:
        if until and r[0] > until: break
        if score and score(r):
            day = dnum(r[0], r[4])
            # randomise the side so the blend's intercept means nothing (A = winner on even ids)
            pb, pe, pp, gx, cx = m.predict(r[7], r[8], r[1], r[3], day, r[5])
            out.append((r, pe, pp, gx, cx))
        m.update(r)
    return m, out


def scored(r, y0, y1):
    return y0 <= r[0] // 10000 <= y1 and r[2] in TOUR_LV and not r[4].startswith('Q') and not games(r[9])[2]


def ll(ps):
    return -sum(math.log(max(p, 1e-9)) for p in ps) / max(1, len(ps))


NAMES = ('A', 'B', 'G') + CTX
ALL = tuple(range(len(NAMES)))


def feats(x):
    """a recorded match's blend inputs, winner's side: logit Elo, logit points, games rating (x1.25 best of 5), then
    the context terms"""
    r, pe, pp, gx, cx = x
    return [logit(pe), logit(pp), gx * (1.25 if r[5] == 5 else 1.0)] + list(cx)


def blend_p(P, x):
    return sig(sum(P.get(k, 0.0) * f for k, f in zip(NAMES, feats(x))))


def fit_blend(rec, use=(0, 1, 2)):
    """logistic regression of win on the blend inputs (no intercept: each match twice, flipped), by Newton; a small
    ridge keeps a term with no data (market memory before 2025) at 0. Returns every NAMES weight (unused inputs 0)."""
    import numpy as np
    F = np.array([[feats(x)[i] for i in use] for x in rec])
    X = np.vstack([F, -F])
    y = np.r_[np.ones(len(F)), np.zeros(len(F))]
    w = np.zeros(len(use)); w[0] = 1.0
    for _ in range(30):
        p = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (y - p)
        H = (X * (p * (1 - p))[:, None]).T @ X
        w = w + np.linalg.solve(H + 1e-3 * np.eye(len(use)), g - 1e-3 * w)
    out = {k: 0.0 for k in NAMES}
    for j, i in enumerate(use): out[NAMES[i]] = float(w[j])
    return out


def window(rec, d1):
    """recorded matches in the WIN seasons before date d1 (yyyymmdd)"""
    return [x for x in rec if d1 - WIN * 10000 <= x[0][0] < d1]


def wf_probs(rec, P):
    """walk-forward blend chances: each season's matches from weights fit on the WIN seasons before it (the
    rating parameters stay P's)"""
    W = {}
    out = []
    for x in rec:
        y = x[0][0] // 10000
        if y not in W:
            win = window(rec, y * 10000)
            W[y] = dict(P, **fit_blend(win, ALL)) if len(win) > 1000 else P
        out.append(blend_p(W[y], x))
    return out


def blend_ll(rec, W):
    return ll([blend_p(W, x) for x in rec])


def evaluate(rows, P, y0, y1):
    _, rec = run(rows, P, score=lambda r: scored(r, y0, y1), until=(y1 + 1) * 10000)
    return rec


def fit(rows):
    """coordinate search on the tuning seasons (2012-22), starting from the last fit: Elo schedule (points off), then
    the points filter, then the games rating, each scored by the refit blend; held-out seasons only report"""
    log = []
    P = dict(DEFAULT)
    try:
        P.update(json.load(open(FIT)).get('params', {}))
    except (OSError, ValueError):
        pass
    tune = (2012, 2022)

    def stage(name, grid, use):
        for k, vals in grid.items():
            res = []
            for v in vals:
                Q = dict(P, **{k: v})
                rec = evaluate(rows, Q, *tune)
                W = fit_blend(rec, use) if len(use) > 1 else {'A': 1.0, 'B': 0.0, 'G': 0.0}
                s = blend_ll(rec, dict(Q, **W))
                res.append((s, v))
                log.append({'stage': name, 'param': k, 'value': v, 'll': round(s, 5), 'n': len(rec), **{w: round(x, 3) for w, x in W.items()}})
                print(f'{name} {k}={v}: {s:.5f}', flush=True)
            P[k] = min(res)[1]
    stage('elo', {'KC': [250, 300, 350], 'KO': [5, 10, 20], 'KS': [0.35, 0.4, 0.45], 'SW': [0.2, 0.3, 0.4], 'RET': [0.5, 1.0]}, (0,))
    stage('points', {'PHI': [0.35, 0.5, 0.7], 'V0': [0.03, 0.05, 0.10], 'Q': [0.0001, 0.0003, 0.001]}, (0, 1))
    stage('games', {'KG': [1.0, 1.5, 2.0, 3.0], 'GSW': [0.0, 0.3, 0.5]}, (0, 1, 2))
    # the blend weights live: the last WIN seasons up to the last match (walk-forward scores in score_all)
    _, rec = run(rows, P, score=lambda r: scored(r, 2000, 2100))
    last = max(x[0][0] for x in rec)
    P.update(fit_blend(window(rec, last + 1), ALL))
    out = {'params': P, 'log': log,
           'failed': ['K by level (ITF x0.7 / x1.2, Grand Slam x1.2): tune .58621 / .58600 / .58601 vs .58601, held no change',
                      'Oct 28 2026, each beside the rest (held 2023-26 log loss x1e4, t by tournament): surface-specific '
                      'serve/return filter -0.1 (t -0.1), court speed (event ace rate) x ratings -0.7, Slam/Masters x '
                      'ratings +1.4, recent form (EW result minus chance) +0.9, lefty +0.1, previous match length +0.7, '
                      'retired in the last 30 days 0.0, layoff 90+ days 0.0 once rest is in, in-event game share -0.3, '
                      'ranking -2.7 (t -3.3 but 7/11 tuning years), over-30 age once age is in 0.0',
                      'Oct 28 2026: gave a walkover (withdrew injured) in the last 14 / 30 / 60 days, A minus B: held '
                      '+0.2 / +0.6 / +0.0 (t 0.2 / 0.7 / 0.1); walkover givers won 57.2% vs 57.5% expected (scripts/tennis_wo_research.py)'],
           'fit_at': dt.date.today().isoformat()}
    out.update(score_all(rows, P))
    json.dump(out, open(FIT, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'log'}, indent=1))


def score_all(rows, P):
    """tuning, held-out and closing-line scores, by tour. Every chance is walk-forward: blend weights fit on the WIN
    seasons before the match's season (the rating parameters are tuned on 2012-22); ll_ratings drops the context terms"""
    import numpy as np
    _, rec = run(rows, P, score=lambda r: scored(r, 2012 - WIN, 2100))
    pw = wf_probs(rec, P)
    W0 = {}
    p0 = []
    for x in rec:
        y = x[0][0] // 10000
        if y not in W0:
            win = window(rec, y * 10000)
            W0[y] = fit_blend(win, (0, 1, 2)) if len(win) > 1000 else P
        p0.append(blend_p(W0[y], x))
    keep = [i for i, x in enumerate(rec) if x[0][0] // 10000 >= 2012]
    PW = {id(rec[i]): pw[i] for i in keep}
    P0 = {id(rec[i]): p0[i] for i in keep}
    rec = [rec[i] for i in keep]
    res = {}
    for name, (y0, y1) in (('tune', (2012, 2022)), ('held', (2023, 2100))):
        for tour in ('atp', 'wta', 'all'):
            sub = [x for x in rec if y0 <= x[0][0] // 10000 <= y1 and (tour == 'all' or x[0][1] == tour)]
            pb = [PW[id(x)] for x in sub]
            res.setdefault(name, {})[tour] = {
                'n': len(sub), 'll': round(ll(pb), 5), 'll_ratings': round(ll([P0[id(x)] for x in sub]), 5),
                'll_elo': round(ll([x[1] for x in sub]), 5),
                'll_points': round(ll([x[2] for x in sub]), 5), 'acc': round(sum(p > 0.5 for p in pb) / max(1, len(sub)), 4)}
            # ranking baseline: log rank ratio, logistic slope fit on the same rows (in-sample: the best ranks can do)
    # against the close (2025+): same matches, the feed's no-vig closing probability for the winner
    close = [x for x in rec if x[0][14] is not None and 0 < x[0][14] < 1]
    cl = {}
    for tour in ('atp', 'wta', 'all'):
        sub = [x for x in close if tour == 'all' or x[0][1] == tour]
        pm = [PW[id(x)] for x in sub]
        pc = [x[0][14] for x in sub]
        po = [x[0][15] for x in sub if x[0][15]]
        # paired difference in log loss, t stat
        d = [math.log(c) - math.log(m) for m, c in zip(pm, pc)]
        mean = sum(d) / max(1, len(d))
        sd = (sum((x - mean) ** 2 for x in d) / max(1, len(d) - 1)) ** 0.5
        # does the model add to the close? logistic of win on (logit close, logit model - logit close)
        cl[tour] = {'n': len(sub), 'll_model': round(ll(pm), 5), 'll_close': round(ll(pc), 5),
                    'll_open': round(ll([x[0][15] for x in sub if x[0][15]]), 5) if po else None,
                    'gap': round(mean, 5), 't': round(mean / (sd / max(1, len(d)) ** 0.5), 2) if sd else None,
                    'acc_model': round(sum(p > 0.5 for p in pm) / max(1, len(pm)), 4),
                    'acc_close': round(sum(p > 0.5 for p in pc) / max(1, len(pc)), 4)}
    # does the model know anything the close doesn't? logistic of the result on logit(close) and the model's
    # difference from it (coefficient ~0 = nothing to add), each match both ways round
    import numpy as np
    if close:
        F = np.array([[logit(x[0][14]), logit(PW[id(x)]) - logit(x[0][14])] for x in close])
        X = np.vstack([F, -F]); y = np.r_[np.ones(len(F)), np.zeros(len(F))]
        w = np.array([1.0, 0.0])
        for _ in range(30):
            p_ = 1 / (1 + np.exp(-(X @ w)))
            H = (X * (p_ * (1 - p_))[:, None]).T @ X
            w = w + np.linalg.solve(H + 1e-9 * np.eye(2), X.T @ (y - p_))
        se = np.sqrt(np.diag(np.linalg.inv(H)) * 2)          # each match counted twice
        cl['add'] = {'close': round(float(w[0]), 3), 'model_minus_close': round(float(w[1]), 3), 't': round(float(w[1] / se[1]), 2)}
    res['close'] = cl
    # calibration of the held-out blend in ten bins (favourite side)
    held = [x for x in rec if x[0][0] // 10000 >= 2023]
    bins = [[0, 0.0, 0] for _ in range(5)]
    for x in held:
        p = PW[id(x)]
        fav, won = (p, 1) if p >= 0.5 else (1 - p, 0)
        i = min(4, int((fav - 0.5) * 10))
        bins[i][0] += 1; bins[i][1] += fav; bins[i][2] += won
    res['calib'] = [{'bin': f'{50 + 10 * i}-{60 + 10 * i}%', 'n': b[0], 'pred': round(b[1] / b[0], 3) if b[0] else None,
                     'won': round(b[2] / b[0], 3) if b[0] else None} for i, b in enumerate(bins)]
    return res


# ---------------------------------------------------------------- build (data/tennis.json)
OUT = os.path.join(ROOT, 'data', 'tennis.json')
FACES = os.path.join(HERE, 'data', 'tennis_faces.json.gz')
HS = 'https://a.espncdn.com/i/headshots/tennis/players/full/{}.png'
TOP = 200
LVN = {'G': 'Grand Slam', 'M': 'Masters 1000', 'F': 'Finals', 'A': 'ATP 250 / 500', 'O': 'Olympics', 'D': 'team event',
       'C': 'Challenger', 'Q': 'qualifying', 'S': 'ITF'}


def surface_mix(rows, tour, since):
    """each surface's share of the tour's main-draw matches in the last 52 weeks"""
    c = {s: 0 for s in SURFS}
    for r in rows:
        if r[0] >= since and r[1] == tour and r[2] in TOUR_LV and not r[4].startswith('Q'): c[r[3]] += 1
    t = sum(c.values()) or 1
    return {s: round(v / t, 3) for s, v in c.items()}


def raw52(rows, since):
    """last-52-week serve and return counting stats (every match with statistics: tour, Challenger, qualifying)"""
    out = {}
    for r in rows:
        if r[0] < since: continue
        for me, op, mine, theirs, won in ((r[7], r[8], r[10], r[11], 1), (r[8], r[7], r[11], r[10], 0)):
            x = out.setdefault(me, {'w': 0, 'l': 0, 'tw': 0, 'tl': 0, 'st': [0] * 9, 'rt': [0] * 9, 'gw': 0, 'gl': 0, 'm': 0})
            x['w' if won else 'l'] += 1
            if r[2] in TOUR_LV or r[2] == 'D': x['tw' if won else 'tl'] += 1
            gw, gl, _ = games(r[9])
            x['gw'] += gw if won else gl
            x['gl'] += gl if won else gw
            if mine and theirs:
                x['m'] += 1
                for i in range(9):
                    x['st'][i] += mine[i] or 0
                    x['rt'][i] += theirs[i] or 0
    return out


def rate(a, b):
    return round(100 * a / b, 1) if b else None


def faces(ids, wds=()):
    """headshots: whether ESPN has one, per ESPN id (HEAD request), and for the players it lacks the Wikidata
    portrait (P18, a Wikimedia Commons file name), both cached 30 days. Returns (espn id -> bool, Q id -> file)."""
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    try:
        with gzip.open(FACES, 'rt') as fh: F = json.load(fh)
    except (OSError, ValueError):
        F = {}
    today = dt.date.today().isoformat()
    lim = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    todo = [str(i) for i in ids if i and (str(i) not in F or F[str(i)][1] < lim)]

    def one(i):
        try:
            req = urllib.request.Request(HS.format(i), method='HEAD', headers={'User-Agent': 'arkboard (arkndjl.net)'})
            with urllib.request.urlopen(req, timeout=20) as r:
                return i, r.status == 200
        except Exception:  # noqa: BLE001
            return i, False
    with ThreadPoolExecutor(12) as ex:
        for i, ok in ex.map(one, todo): F[i] = [ok, today]
    wtodo = [q for q in wds if q and ('wd:' + q not in F or F['wd:' + q][1] < lim)]
    for k in range(0, len(wtodo), 50):
        part = wtodo[k:k + 50]
        url = 'https://www.wikidata.org/w/api.php?action=wbgetentities&props=claims&format=json&ids=' + '|'.join(part)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'arkboard/1.0 (https://arkndjl.net; tennis headshots)'})
            with urllib.request.urlopen(req, timeout=30) as r:
                ent = json.load(r).get('entities', {})
        except Exception as e:  # noqa: BLE001
            print('wikidata portraits skipped:', e)
            break
        for q in part:
            cl = ent.get(q, {}).get('claims', {}).get('P18', [])
            f = ''
            for c in cl:
                try:
                    f = c['mainsnak']['datavalue']['value']; break
                except (KeyError, TypeError):
                    continue
            F['wd:' + q] = [f, today]
        time.sleep(1)
    with gzip.open(FACES, 'wt') as fh: json.dump(F, fh, separators=(',', ':'), sort_keys=True)
    return ({k: v[0] for k, v in F.items() if not k.startswith('wd:')},
            {k[3:]: v[0] for k, v in F.items() if k.startswith('wd:') and v[0]})


RATINGS = os.path.join(HERE, 'data', 'tennis_ratings.json.gz')


def export_ratings(m, players, tday):
    """every player with a match in the last year, any level: today's ratings (the tennis prospects board reads these)"""
    out = {'asof': dt.date.today().isoformat(), 'about': 'scripts/tennis_model.py: elo = overall Elo (start 1500, K = KC / (n + KO) ^ KS '
           'over every level), eH/eC/eG surface Elo, n = matches, g = games rating (log-odds of a game), s / r = serve / return '
           'strength in log-odds of a serve point over the tour average (Kalman, sd in su / ru), rank / pts official',
           'params': {k: v for k, v in m.P.items()}, 'players': {}}
    for pid, d in m.last.items():
        if tday - d > 365 or pid.startswith('REF'): continue
        e, g, x, b = m.elo[pid], m._g(pid), m._pt(pid, tday), players.get(pid, {})
        out['players'][pid] = {'n': b.get('n'), 'nat': b.get('nat'), 'dob': b.get('dob'), 'espn': b.get('espn'),
                               'rank': b.get('rank'), 'pts': b.get('pts'), 'elo': round(e[0], 1), 'n_m': e[1],
                               'eH': round(e[2]['H'][0], 1), 'eC': round(e[2]['C'][0], 1), 'eG': round(e[2]['G'][0], 1),
                               'g': round(g[0], 4), 's': round(x[0], 4), 'r': round(x[2], 4),
                               'su': round(x[1] ** 0.5, 4), 'ru': round(x[3] ** 0.5, 4),
                               'last': (DAY0 + dt.timedelta(days=d)).isoformat()}
    with gzip.open(RATINGS, 'wt') as fh: json.dump(out, fh, separators=(',', ':'))
    print(f"ratings: {len(out['players'])} active players -> {os.path.relpath(RATINGS, ROOT)}")


def fair(p):
    """American odds without the vig"""
    p = min(max(p, 0.01), 0.99)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def build(rows, players, tn):
    import tennis_data as T
    fitp = {}
    try:
        fitp = json.load(open(FIT))
    except (OSError, ValueError):
        pass
    P = dict(DEFAULT, **fitp.get('params', {}))
    today = dt.date.today()
    tday = (today - DAY0).days
    recent_from = int((today - dt.timedelta(days=10)).strftime('%Y%m%d'))
    since = int((today - dt.timedelta(days=364)).strftime('%Y%m%d'))
    snap_day = int((today - dt.timedelta(days=91)).strftime('%Y%m%d'))
    m = Model(P)
    recent, old = [], None
    for r in rows:
        if old is None and r[0] > snap_day:
            old = {k: v[0] for k, v in m.elo.items()}          # overall Elo 13 weeks ago
        if r[0] >= recent_from and r[2] != 'S':
            day = dnum(r[0], r[4])
            recent.append((r, m.predict(r[7], r[8], r[1], r[3], day, r[5])[0]))
        m.update(r)
    old = old or {}
    export_ratings(m, players, tday)
    raw = raw52(rows, since)
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'tours': {}}
    shown = set()
    allrk = {}
    for tour in ('atp', 'wta'):
        t0 = tour[0]
        act = [p for p, d in m.last.items() if p[0] == t0 and tday - d <= 183 and m.nm.get(p, 0) >= 15]
        mix = surface_mix(rows, tour, since)
        # the reference opponent: the average of the top 50 by overall Elo
        top50 = sorted(act, key=lambda p: -m.elo[p][0])[:50]
        ref = 'REF' + tour
        m.elo[ref] = [sum(m.elo[p][0] for p in top50) / 50, 999, {s: [sum(m.elo[p][2][s][0] for p in top50) / 50, 999] for s in SURFS}]
        m.pt[ref] = [sum(m._pt(p, tday)[0] for p in top50) / 50, 0.0, sum(m._pt(p, tday)[2] for p in top50) / 50, 0.0, tday]
        rowsout = []
        mu = m.mu_of(tour, 'H')
        for p in act:
            e = m.elo[p]
            pv = {s: m.predict(p, ref, tour, s, tday, 3, match=False)[0] for s in SURFS}
            ark = sum(mix[s] * pv[s] for s in SURFS)
            x = m._pt(p, tday)
            b = players.get(p, {})
            rw = raw.get(p, {})
            st, rt = rw.get('st', [0] * 9), rw.get('rt', [0] * 9)
            # st / rt: [svpt, 1stIn, 1stWon, 2ndWon, SvGms, bpSaved, bpFaced, ace, df] on serve / the opponents' on serve
            spw = rate(st[2] + st[3], st[0])
            rpw = rate(rt[0] - rt[2] - rt[3], rt[0])
            hold = rate(st[4] - (st[6] - st[5]), st[4])
            brk = rate(rt[6] - rt[5], rt[4])
            bps = rate(st[5], st[6])
            bpc = rate(rt[6] - rt[5], rt[6])
            age = None
            if b.get('dob'):
                try:
                    age = round((today - ymd(int(b['dob']))).days / 365.25, 1)
                except ValueError:
                    pass
            rowsout.append({
                'id': p, 'n': b.get('n', p), 'nat': b.get('nat') or '', 'espn': b.get('espn'), 'age': age,
                'hand': b.get('hand'), 'ht': b.get('ht'), 'rank': b.get('rank'), 'pts': b.get('pts'),
                'ark': round(ark, 4), 'pH': round(pv['H'], 4), 'pC': round(pv['C'], 4), 'pG': round(pv['G'], 4),
                'elo': round(e[0]), 'eH': round(e[2]['H'][0]), 'eC': round(e[2]['C'][0]), 'eG': round(e[2]['G'][0]),
                'd90': round(e[0] - old[p]) if p in old else None,
                'peak': round(m.peak[p][0]) if p in m.peak else None, 'peakd': m.peak[p][1] if p in m.peak else None,
                '_s': x[0], '_r': x[2],
                'unc': round((x[1] + x[3]) ** 0.5, 3),
                'w': rw.get('w', 0), 'l': rw.get('l', 0), 'tw': rw.get('tw', 0), 'tl': rw.get('tl', 0),
                'gwp': rate(rw.get('gw', 0), rw.get('gw', 0) + rw.get('gl', 0)), 'sm': rw.get('m', 0),
                'spw': spw, 'rpw': rpw, 'hold': hold, 'brk': brk,
                'dr': round((rpw / (100 - spw)), 2) if spw and rpw and spw < 100 else None,
                'ace': rate(st[7], st[0]), 'df': rate(st[8], st[0]), 'fin': rate(st[1], st[0]),
                'fw': rate(st[2], st[1]), 'sw': rate(st[3], st[0] - st[1]),
                'bps': bps, 'bpc': bpc,
                # pressure over expected: break points saved above the player's own serve-point rate, converted
                # above their own return-point rate (pp)
                'bpsx': round(bps - spw, 1) if bps is not None and spw is not None and st[6] >= 20 else None,
                'bpcx': round(bpc - rpw, 1) if bpc is not None and rpw is not None and rt[6] >= 20 else None,
                'last': (DAY0 + dt.timedelta(days=m.last[p])).isoformat(), 'nm': m.nm.get(p, 0)})
        rowsout.sort(key=lambda r: -r['ark'])
        for i, r in enumerate(rowsout): r['rk'] = i + 1
        # serve / return against the average top-100 player (the ratings' level is only fixed up to a constant)
        t100 = rowsout[:100]
        sb, rb = sum(r['_s'] for r in t100) / len(t100), sum(r['_r'] for r in t100) / len(t100)
        base = sig(mu + sb - rb)
        for r in rowsout:
            sv, rv = sig(mu + r.pop('_s') - rb), sig(mu + sb - r.pop('_r'))
            r['spwp'] = round(100 * (sv - base), 1)
            r['rpwp'] = round(100 * (base - rv), 1)
            r['xhold'] = round(100 * p_game(sv), 1)
            r['xbrk'] = round(100 * (1 - p_game(rv)), 1)
        for s in SURFS:
            for i, r in enumerate(sorted(rowsout, key=lambda r: -r['p' + s])): r['rk' + s] = i + 1
        keep = rowsout[:TOP]
        allrk.update({r['id']: r['rk'] for r in rowsout})
        shown |= {r['id'] for r in keep}
        out['tours'][tour] = {'mix': mix, 'ref': {'elo': round(m.elo[ref][0]), 'n': 50}, 'mu': round(sig(mu), 4), 'players': keep,
                              'active': len(rowsout)}
    # matches: ESPN's draws for the next three days and the last few days' results
    comps, eid, kind = T.load_espn()
    rk = allrk
    games_ = []
    pre = {}
    for r, pb in recent: pre[(r[1], frozenset((r[7], r[8])))] = (r[7], pb)
    for c in comps:
        if not c.get('date'): continue
        try:
            when = dt.datetime.fromisoformat(c['date'].replace('Z', '+00:00'))
        except ValueError:
            continue
        age_h = (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600
        if age_h > 72 or age_h < -96: continue
        a, b = c['players']
        pa_, pb_ = eid.get(a[0]), eid.get(b[0])
        if not pa_ or not pb_: continue
        lv, sf = kind.get(c['tid'], ('A', 'H'))
        rd = T.espn_round(c['rd'])
        bo = 5 if (lv == 'G' and c['tour'] == 'atp' and not rd.startswith('Q')) else 3
        if c['done']:
            k = pre.get((c['tour'], frozenset((pa_, pb_))))
            if not k: continue
            p = k[1] if k[0] == pa_ else 1 - k[1]
        else:
            p = m.predict(pa_, pb_, c['tour'], sf, max(tday, (when.date() - DAY0).days), bo)[0]
        sc = None
        if c['done'] or c['state'] == 'in':
            sc = ' '.join(f'{x}-{y}' for x, y in zip(a[5], b[5]))
        side = []
        for (e_, n_, code, alt, won, sets, order), pid in ((a, pa_), (b, pb_)):
            pl = players.get(pid, {})
            shown.add(pid)
            side.append({'id': pid, 'n': pl.get('n') or n_, 'nat': pl.get('nat') or T.iso2(code, alt), 'espn': pl.get('espn'),
                         'rk': rk.get(pid), 'rank': pl.get('rank'), 'won': won})
        games_.append({'id': c['id'], 'tour': c['tour'], 'ev': c['tn'], 'lv': lv, 'sf': sf, 'rd': rd, 'bo': bo, 'tip': when.strftime('%Y-%m-%dT%H:%M:%SZ'),
                       'state': c['state'], 'detail': c.get('detail', ''), 'court': c.get('court', ''), 'p': round(p, 4),
                       'fair': [fair(p), fair(1 - p)], 'sc': sc, 'a': side[0], 'b': side[1]})
    # Novig's moneyline beside the model on matches still to play (scripts/novig.py; the archive odds_snap keeps is
    # where tennis closing lines, and so any tennis pick rule, must come from)
    try:
        import novig
        nvg = novig.h2h('tennis')
    except Exception as ex:  # noqa: BLE001
        print('novig tennis skipped:', ex)
        nvg = []
    for g in games_:
        if g['state'] == 'pre' and nvg:
            nv = novig.h2h_price(nvg, g['a']['n'], g['b']['n'], lg=g['tour'].upper())
            if nv: g['nv'] = nv
    games_.sort(key=lambda g: (g['state'] != 'in', g['state'] == 'post', g['tip'] if g['state'] != 'post' else '~' + g['tip']))
    # main draws first; qualifying only while there's room (60 cards upcoming, 48 results)
    up = [g for g in games_ if g['state'] != 'post']
    main = [g for g in up if not g['rd'].startswith('Q')]
    out['matches'] = (main + [g for g in up if g['rd'].startswith('Q')])[:60]
    out['matches'].sort(key=lambda g: (g['state'] != 'in', g['tip']))
    done = sorted([g for g in games_ if g['state'] == 'post'], key=lambda g: g['tip'], reverse=True)
    done = [g for g in done if not g['rd'].startswith('Q')] + [g for g in done if g['rd'].startswith('Q')]
    out['results'] = sorted(done[:48], key=lambda g: g['tip'], reverse=True)
    # model card
    out['model'] = {k: fitp.get(k) for k in ('held', 'close', 'calib', 'tune') if k in fitp}
    out['model']['params'] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in P.items()}
    # headshots (ESPN) and flags
    ok = faces({players.get(p, {}).get('espn') for p in shown} - {None})[0]
    nophoto = [p for p in shown if not (players.get(p, {}).get('espn') and ok.get(str(players[p]['espn'])))]
    ok, wd = faces(set(), [players.get(p, {}).get('wd') for p in nophoto])

    def photo(o, pid):
        e = o.get('espn')
        o['ph'] = e if e and ok.get(str(e)) else None
        q = players.get(pid, {}).get('wd')
        o['wph'] = urllib.parse.quote(wd[q].replace(' ', '_')) if (not o['ph'] and q in wd) else None
    for t in out['tours'].values():
        for r in t['players']: photo(r, r['id'])
    for g in out['matches'] + out['results']:
        for s_ in ('a', 'b'): photo(g[s_], g[s_]['id'])
    try:
        import soccer_faces
        soccer_faces.fetch_flags({r['nat'] for t in out['tours'].values() for r in t['players']} |
                                 {g[s_]['nat'] for g in out['matches'] + out['results'] for s_ in 'ab'})
    except Exception as e:  # noqa: BLE001
        print('flags skipped:', e)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
    print(f"tennis.json: {sum(len(t['players']) for t in out['tours'].values())} players, {len(out['matches'])} matches, "
          f"{len(out['results'])} results")


if __name__ == '__main__':
    import tennis_data as T
    rows, players, tn = T.load()
    if '--fit' in sys.argv:
        fit(rows)
    else:
        build(rows, players, tn)
