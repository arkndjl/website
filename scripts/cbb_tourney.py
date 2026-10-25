#!/usr/bin/env python3
"""NCAA tournament odds for the College Basketball ARKBOARD: who makes the field, at what seed, and how far each team
goes, from the CBB game model (scripts/cbb_games.py) and a committee model fit on the 2014-26 fields.

    python3 scripts/cbb_tourney_hist.py     # the fields, seeds, regions and conference tournaments (ESPN)
    python3 scripts/cbb_tourney.py --fit    # walk the game model, fit the committee, backtest -> data/cbb_tourney_fit.json
    (live: cbb_games_live.py calls sim() after its regular-season sims; the odds land in data/cbb_games.json 'power')

The chain, simulated a few thousand times from today:
  1. the rest of the regular season (cbb_games_live's sims: each team's true strength drawn once around its rating,
     every game normal around its margin)
  2. conference tournaments: the top N of each conference by its simulated conference record (N from last season's
     tournament), single elimination, byes to the top seeds, neutral floor; the winner takes the automatic bid
     (a conference with no tournament: the regular-season champion)
  3. selection: the at-large bids go to the best committee scores among the rest, each score drawn with logistic noise
     (a logit fit on the 2015-26 fields: our power rating, wins above bubble, Quadrant 1 wins; held out by season)
  4. seeding: an S-curve from a second fit (seed line on the same resume), normal noise, four teams a line, the last
     four at-large teams and the four lowest automatic bids in the First Four, regions serpentine down the S-curve
  5. the bracket, every game from the game model's neutral-floor margin around the simulated true strengths
Once the bracket is out (ESPN lists the First Four and first round with seeds) step 1-4 give way to the real field.
Teams in their D-I transition years (not D-I in each of the last four seasons) can't be selected.
Nothing here reads the market: odds are model-only (betting content lives in Predictions).
"""
import gzip
import json
import math
import os
import pickle
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np

import cbb_games as C

HIST = os.path.join(C.HERE, 'data', 'cbb_tourney_hist.json')
FIT = os.path.join(C.ROOT, 'data', 'cbb_tourney_fit.json')
FIRST = 2015                                  # first season scored (the walk's coefficients need a season before)
SEASONS = [s for s in range(FIRST, C.LAST + 1) if s != 2020]
NCAA_NOTE = re.compile(r"men's basketball championship", re.I)
REGION = re.compile(r'(East|West|South|Midwest|Southeast|Southwest)\s+Region', re.I)
ORDER = [1, 16, 8, 9, 5, 12, 4, 13, 6, 11, 3, 14, 7, 10, 2, 15]     # a region's bracket, top to bottom
ROUNDS = ['r32', 's16', 'e8', 'f4', 'final', 'champ']                 # won a first-round game ... won it all
BUBBLE = 45                                   # wins above bubble: against the 45th-rated team's chances


def ncdf(x):
    """standard normal cdf, vectorized (Abramowitz-Stegun 7.1.26, error < 1.5e-7)"""
    x = np.asarray(x, float)
    z = np.abs(x) / math.sqrt(2)
    t = 1 / (1 + 0.3275911 * z)
    y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-z * z)
    return 0.5 * (1 + np.sign(x) * y)


def ll(p, y, eps=1e-4):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired_t(a, b):
    d = np.asarray(a) - np.asarray(b)
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0


# ---------------------------------------------------------------- the history walk
def selection_day(h):
    """the Monday after Selection Sunday: the cut that sees every conference final"""
    d = datetime.strptime(C.et_date(h['ncaa'][0]['date']), '%Y-%m-%d').date()
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return (d + timedelta(days=1)).isoformat()


def walk():
    """the game model's walk with the shipped params: each game's inputs, and every team's rating parts the morning of
    Feb 1, Mar 1 and the Monday after Selection Sunday. Cached in scripts/.cache/cbb/games/tourney_walk.pkl"""
    p = os.path.join(C.CACHE, 'tourney_walk.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    TH = json.load(open(HIST))
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    W = C.Walk(F['params'], tprior, btname)
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    rows, snaps = [], {}
    for s in sorted(by_s):
        gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))
        teams = sorted(d1s[s])
        cuts = {'feb1': f'{s}-02-01', 'mar1': f'{s}-03-01'}
        if str(s) in TH:
            cuts['sel'] = selection_day(TH[str(s)])

        def snap(R, c):
            snaps[(s, c)] = {'date': cuts[c], 'net': {t: float(R.net(t)) for t in teams}, 'T': {t: float(R.T[R.i(t)]) for t in teams},
                             'tau': float(R.tau), 'elo': {t: float(W.elo[t]) for t in teams}, 'ng': {t: R.ng[t] for t in teams}}

        def collect(g, x, tx, R):
            d = C.et_date(g['date'])
            for c, cd in cuts.items():
                if d >= cd and (s, c) not in snaps:
                    snap(R, c)
            if g.get('hs') is None:
                return
            rows.append((g['season'], g['id'], {f: x[f] for f in F['feats']}, g['home'] != C.X and g['away'] != C.X and 'hb' in g))
        C.season_walk(W, s, gs, d1s[s], avs.get(s), collect)
        print('walk', s, len(rows), flush=True)
    out = (rows, snaps, {s: sorted(v) for s, v in d1s.items()})
    os.makedirs(C.CACHE, exist_ok=True)
    pickle.dump(out, open(p, 'wb'))
    return out


def gm_snaps(games, cuts, d1s):
    """the long-memory margin rating (the game model's 'gm' input, scripts/control_ratings.py) of every D-I team the
    morning of each cut: probe games with no result (each team at home to a reference team) read it off the walk"""
    import control_ratings as CR
    probes, ref = [], {}
    for (s, c), cd in cuts.items():
        ts = sorted(d1s[s])
        ref[s] = ts[0]
        for t in ts[1:]:
            probes.append({'id': f'probe|{s}|{c}|{t}', 'date': cd + 'T00:00Z', 'season': s, 'home': t, 'away': ts[0], 'neutral': True})
    done = [g for g in games if g.get('hs') is not None]
    feat, _ = CR.ratings(CR.cbb_gl(done + probes), CR.margin_control(done), **CR.CBB_FIT)
    out = defaultdict(dict)
    for k, v in feat.items():
        if k.startswith('probe|'):
            _, s, c, t = k.split('|')
            out[(int(s), c)][t] = v
    for (s, c) in cuts:
        out[(s, c)][ref[s]] = 0.0
    return dict(out)


def coefs(rows, feats, margin):
    """the game model's weights fit on each season's earlier seasons (as its walk-forward does); margin: id -> result"""
    rows = [r for r in rows if r[1] in margin]
    S = np.array([r[0] for r in rows]); d1 = np.array([r[3] for r in rows])
    Xm = np.array([[r[2][f] for f in feats] for r in rows]); y = np.array([margin[r[1]] for r in rows], float)
    out = {}
    for s in SEASONS:
        k = (S < s) & d1 & ((S > C.FIRST) | (s == C.FIRST + 1))
        out[s] = dict(zip(feats, (float(v) for v in np.linalg.lstsq(Xm[k], y[k], rcond=None)[0])))
    return out


def team_rating(net, T, tau, elo, gm, teams, coef):
    """points against an average D-I team on a neutral floor, from the game model's weights: efficiency (its own and,
    with no ESPN forecast for a game not yet scheduled, BPI's fallback to it), Elo, long-memory margin"""
    P0 = tau + 2 * float(np.mean([T[t] for t in teams]))
    mn = float(np.mean([net[t] for t in teams])); me = float(np.mean([elo[t] for t in teams]))
    mg = float(np.mean([gm.get(t, 0.0) for t in teams]))
    ce = coef.get('eff', 0.0) + coef.get('bpi', 0.0)
    return {t: ce * (net[t] - mn) * P0 / 100 + coef.get('elo', 0.0) * (elo[t] - me) / 25 + coef.get('gm', 0.0) * (gm.get(t, 0.0) - mg)
            for t in teams}


def home_edge(coef, conf_game, h):
    return coef.get('home', 3.0) + coef.get('bpi', 0.0) * C.BPI_HOME + coef.get('confh', 0.0) * conf_game + coef.get('alt', 0.0) * (h in C.ALT)


# quadrant cut lines on rank (the NCAA's NET quadrants): Q1 / Q2 upper bounds by site, from the team's side
Q1 = {'home': 30, 'neutral': 50, 'away': 75}
Q2 = {'home': 75, 'neutral': 100, 'away': 135}


class Season:
    """one season's teams, conferences, schedule and ratings at a cut, with the resume parts the committee reads"""

    def __init__(self, teams, conf, rating, rank, games, sd, coef, eligible):
        self.teams = teams
        self.ti = {t: i for i, t in enumerate(teams)}
        self.n = len(teams)
        self.conf = conf
        self.r = np.array([rating[t] for t in teams])
        self.rank = rank
        self.sd, self.coef = sd, coef
        self.elig = np.array([t in eligible for t in teams])
        order = np.sort(self.r)[::-1]
        self.rb = float(order[BUBBLE - 1])
        self.games = games

    def game_parts(self, g):
        """(home index, away index, home edge, p bubble wins at home's spot, p bubble wins at away's spot, home Q1 game,
        away Q1 game, home loss is Q3/4, away loss is Q3/4)"""
        h, a = self.ti[g['home']], self.ti[g['away']]
        he = 0.0 if g['neutral'] else home_edge(self.coef, 1.0 if g.get('conf') else 0.0, g['home'])
        sh, sa = ('neutral', 'neutral') if g['neutral'] else ('home', 'away')
        ph = float(ncdf((self.rb - self.r[a] + he) / self.sd))
        pa = float(ncdf((self.rb - self.r[h] - he) / self.sd))
        rh, ra = self.rank[g['home']], self.rank[g['away']]
        return h, a, he, ph, pa, ra <= Q1[sh], rh <= Q1[sa], ra > Q2[sh], rh > Q2[sa]

    def resume(self, played):
        """wins, wins above bubble, Q1 wins, Q3/Q4 losses from finished D-I games"""
        W, wab, q1, bad = np.zeros(self.n), np.zeros(self.n), np.zeros(self.n), np.zeros(self.n)
        for g in played:
            h, a, he, ph, pa, q1h, q1a, bh, ba = self.game_parts(g)
            hw = g['hs'] > g['as']
            W[h] += hw; W[a] += not hw
            wab[h] += hw - ph; wab[a] += (not hw) - pa
            q1[h] += hw and q1h; q1[a] += (not hw) and q1a
            bad[h] += (not hw) and bh; bad[a] += hw and ba
        return W, wab, q1, bad


FEATS = ['r', 'wab', 'q1', 'bad']


def xmat(parts, feats, M):
    """committee inputs standardized with the fit's means and sds M"""
    return np.stack([(parts[f] - M[f][0]) / M[f][1] for f in feats], -1)


def logit_fit(X, y, ridge=0.5):
    X1 = np.concatenate([np.ones((len(X), 1)), X], 1)
    b = np.zeros(X1.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X1 @ b))
        Wt = p * (1 - p)
        H = X1.T @ (X1 * Wt[:, None]) + ridge * np.diag([0] + [1] * X.shape[1])
        g = X1.T @ (y - p) - ridge * np.concatenate([[0], b[1:]])
        step = np.linalg.solve(H, g)
        b += step
        if np.abs(step).max() < 1e-8:
            break
    return b


def logit_p(X, b):
    return 1 / (1 + np.exp(-(b[0] + X @ b[1:])))


# ---------------------------------------------------------------- the simulation
def ko(seeds, strength, sd, rng, bye=-1):
    """single elimination over seeded entrants. seeds (nsim, N): team indices best first. Byes to the top seeds.
    Returns (champion (nsim,), per-sim list of (winner, loser) index arrays by round)"""
    nsim, N = seeds.shape
    B = 1
    while B < N:
        B *= 2
    pos = [1]
    while len(pos) < B:
        m = 2 * len(pos) + 1
        pos = [x for p in pos for x in (p, m - p)]
    slots = np.full((nsim, B), bye, int)
    for j, sd_ in enumerate(pos):
        if sd_ <= N:
            slots[:, j] = seeds[:, sd_ - 1]
    games = []
    rows = np.arange(nsim)[:, None]
    while slots.shape[1] > 1:
        a, b = slots[:, 0::2], slots[:, 1::2]
        real = (a != bye) & (b != bye)
        sa = strength[rows, np.where(a == bye, 0, a)]; sb = strength[rows, np.where(b == bye, 0, b)]
        aw = ncdf((sa - sb) / sd) > rng.random(a.shape)
        win = np.where(b == bye, a, np.where(a == bye, b, np.where(aw, a, b)))
        lose = np.where(real, np.where(aw, b, a), bye)
        games.append((win, lose, real))
        slots = win
    return slots[:, 0], games


def bracket_slots(field_z, field_al, rng=None):
    """one sim's S-curve -> 64 bracket slots (team, First Four partner or -1) and each team's seed line.
    field_z: {team index: committee seed score, higher better}; field_al: the at-large ones"""
    ts = sorted(field_z, key=lambda t: -field_z[t])
    al = [t for t in ts if t in field_al]
    au = [t for t in ts if t not in field_al]
    ff = al[-4:] + au[-4:]
    pairs = [(ff[0], ff[1]), (ff[2], ff[3]), (ff[4], ff[5]), (ff[6], ff[7])]
    inff = set(ff)
    ent = [(field_z[t], t, -1) for t in ts if t not in inff] + [(max(field_z[a], field_z[b]), a, b) for a, b in pairs]
    ent.sort(key=lambda e: -e[0])
    reg = [[None] * 16 for _ in range(4)]
    seed = {}
    for i, (_, a, b) in enumerate(ent[:64]):
        line, j = i // 4, i % 4
        r = j if line % 2 == 0 else 3 - j
        reg[r][line] = (a, b)
        seed[a] = line + 1
        if b != -1:
            seed[b] = line + 1
    slots = []
    for r in (0, 3, 1, 2):                     # semifinals: region 0 v 3, 1 v 2
        for sd_ in ORDER:
            slots.append(reg[r][sd_ - 1])
    return slots, seed


def play_bracket(slots, strength, sd, rng, reach, done=None):
    """slots: (nsim, 64, 2) team / First Four partner (-1 none). Adds to reach[k] (n_teams,) for each round won.
    done: [(winner, loser)] games already played, which keep their result"""
    nsim = slots.shape[0]
    rows = np.arange(nsim)[:, None]

    def force(x, y, xw):
        for w, l in done or ():
            xw = np.where((x == w) & (y == l), True, np.where((x == l) & (y == w), False, xw))
        return xw
    a, b = slots[:, :, 0], slots[:, :, 1]
    has = b >= 0
    sa = strength[rows, a]; sb = strength[rows, np.where(has, b, 0)]
    aw = force(a, b, ncdf((sa - sb) / sd) > rng.random(a.shape))
    cur = np.where(has & ~aw, b, a)
    for k in range(6):
        x, y = cur[:, 0::2], cur[:, 1::2]
        xw = force(x, y, ncdf((strength[rows, x] - strength[rows, y]) / sd) > rng.random(x.shape))
        cur = np.where(xw, x, y)
        np.add.at(reach[ROUNDS[k]], cur.ravel(), 1)


def actual_bracket(ncaa_games, seeds_regions, f4_pairs=None, rating=None):
    """the real bracket from the tournament's games: [(team, First Four partner or None)] x 64 in slot order.
    seeds_regions: {team: (seed, region)}. f4_pairs: [(region, region), (region, region)] semifinal pairings
    (default: the regions ranked by their 1 seed's rating, best v worst)"""
    by = defaultdict(list)
    for t, (sd_, rg) in seeds_regions.items():
        by[(rg, sd_)].append(t)
    regions = sorted({rg for rg, _ in by})
    if len(regions) != 4:
        return None
    if not f4_pairs:
        ones = sorted(regions, key=lambda rg: -max((rating or {}).get(t, 0.0) for t in by[(rg, 1)]) if by.get((rg, 1)) else 0)
        f4_pairs = [(ones[0], ones[3]), (ones[1], ones[2])]
    slots = []
    for p in f4_pairs:
        for rg in p:
            for sd_ in ORDER:
                ts = by.get((rg, sd_), [])
                if not ts:
                    return None
                slots.append((ts[0], ts[1] if len(ts) > 1 else None))
    return slots


def run(SS, played, left, ctinfo, n_at, model, nsim, rng, tsd, actual=None, chunk=500, done=None):
    """simulate from a cut: SS (Season at the cut), played (finished D-I games), left (regular-season games to go),
    ctinfo {conference: {'n': entrants (0: regular-season champion), 'elim': teams already out, 'champ': known
    winner}}, n_at at-large bids, model (the committee fit), tsd (n,) each team's strength sd. actual: the real
    bracket's 64 slots (field set) -> skip 2-4, done its games already played (winner, loser) indexes. Returns per-team arrays: bid, auto, seed counts (n, 16), reach"""
    n, sd = SS.n, SS.sd
    W0, wab0, q10, bad0 = SS.resume(played)
    cw0, cl0 = np.zeros(n), np.zeros(n)
    for g in played:
        if g.get('conf') and not g.get('ct'):
            h, a = SS.ti[g['home']], SS.ti[g['away']]
            w = g['hs'] > g['as']
            cw0[h] += w; cl0[h] += not w; cw0[a] += not w; cl0[a] += w
    gp = [SS.game_parts(g) for g in left]
    ng_ = len(gp)
    out = {'bid': np.zeros(n), 'auto': np.zeros(n), 'seed': np.zeros((n, 16)), **{k: np.zeros(n) for k in ROUNDS}}
    if ng_:
        hi = np.array([x[0] for x in gp]); ai = np.array([x[1] for x in gp])
        he, ph, pa = (np.array([x[k] for x in gp]) for k in (2, 3, 4))
        q1h, q1a, bh, ba = (np.array([x[k] for x in gp], float) for k in (5, 6, 7, 8))
        cf = np.array([1.0 if g.get('conf') else 0.0 for g in left])
        Ih = np.zeros((ng_, n), np.float32); Ia = np.zeros((ng_, n), np.float32)
        Ih[np.arange(ng_), hi] = 1; Ia[np.arange(ng_), ai] = 1
    cid = [SS.conf.get(t) for t in SS.teams]
    members = {c: np.array([i for i, x in enumerate(cid) if x == c and SS.elig[i]], int) for c in ctinfo}
    act_field = None
    if actual:
        act_field = sorted({x for sl in actual for x in sl if x is not None})
        A = np.array([[SS.ti[a], SS.ti[b] if b is not None else -1] for a, b in actual])
    for c0 in range(0, nsim, chunk):
        k = min(chunk, nsim - c0)
        rows = np.arange(k)[:, None]
        shock = rng.normal(0, 1, (k, n)) * tsd
        true = SS.r[None, :] + shock
        if actual:
            slots = np.repeat(A[None], k, 0)
            out['bid'][[SS.ti[t] for t in act_field]] += k
            play_bracket(slots, true, sd, rng, out, done)
            continue
        W, wab, q1, bad = (np.repeat(v[None], k, 0) for v in (W0, wab0, q10, bad0))
        cw, cl = np.repeat(cw0[None], k, 0), np.repeat(cl0[None], k, 0)
        if ng_:
            m = SS.r[hi] - SS.r[ai] + he + shock[:, hi] - shock[:, ai]
            hw = ((m + rng.normal(0, sd, m.shape)) > 0).astype(np.float32)
            lw = 1 - hw
            W += hw @ Ih + lw @ Ia
            wab += (hw - ph) @ Ih + (lw - pa) @ Ia
            q1 += (hw * q1h) @ Ih + (lw * q1a) @ Ia
            bad += (lw * bh) @ Ih + (hw * ba) @ Ia
            cw += (hw * cf) @ Ih + (lw * cf) @ Ia
            cl += (lw * cf) @ Ih + (hw * cf) @ Ia
        pct = cw - cl + 1e-3 * true + 1e-4 * rng.random((k, n))
        auto = np.zeros((k, n), bool)
        for c, info in ctinfo.items():
            mem = members[c]
            if info.get('champ') is not None:
                auto[:, SS.ti[info['champ']]] = True
                continue
            mem = np.array([i for i in mem if SS.teams[i] not in info.get('elim', ())], int)
            if not len(mem):
                continue
            order = mem[np.argsort(-pct[:, mem], 1)]
            N = min(len(mem), info['n'] - len(info.get('elim', ()))) if info['n'] else 0
            if N <= 1:
                auto[np.arange(k), order[:, 0]] = True
                continue
            champ, games = ko(order[:, :N], true, sd, rng)
            auto[np.arange(k), champ] = True
            for win, lose, real in games:
                si, wi, li = np.nonzero(real)[0], win[real], lose[real]
                if not len(wi):
                    continue
                rs = np.repeat(np.arange(k)[:, None], win.shape[1], 1)[real]
                np.add.at(W, (rs, wi), 1)
                np.add.at(wab, (rs, wi), 1 - ncdf((SS.rb - SS.r[li]) / sd))
                np.add.at(wab, (rs, li), -ncdf((SS.rb - SS.r[wi]) / sd))
                rk = np.array([SS.rank[t] for t in SS.teams])
                np.add.at(q1, (rs, wi), (rk[li] <= Q1['neutral']).astype(float))
                np.add.at(bad, (rs, li), (rk[wi] > Q2['neutral']).astype(float))
        parts = {'r': true if model.get('seen', 'true') == 'true' else np.repeat(SS.r[None], k, 0), 'wab': wab, 'q1': q1, 'bad': bad,
                 'auto': auto.astype(float)}
        sc = model['sel']
        score = sc['b'][0] + xmat(parts, sc['feats'], sc['M']) @ np.array(sc['b'][1:])
        u = rng.random((k, n))
        score = score + np.log(u / (1 - u))
        score[auto | ~SS.elig[None, :]] = -np.inf
        top = np.argpartition(-score, n_at - 1, 1)[:, :n_at]
        at = np.zeros((k, n), bool)
        at[rows, top] = True
        field = auto | at
        sm = model['seed']
        z = -(sm['b'][0] + xmat(parts, sm['feats'], sm['M']) @ np.array(sm['b'][1:])) + sm['sigma'] * rng.normal(0, 1, (k, n))
        slots = np.zeros((k, 64, 2), int)
        for j in range(k):
            fi = np.nonzero(field[j])[0]
            sl, seed = bracket_slots({int(t): float(z[j, t]) for t in fi}, set(np.nonzero(at[j])[0].tolist()))
            slots[j] = sl
            for t, line in seed.items():
                out['seed'][t, line - 1] += 1
        out['bid'] += field.sum(0); out['auto'] += auto.sum(0)
        play_bracket(slots, true, sd, rng, out)
    for kk in out:
        out[kk] = out[kk] / nsim
    return out


# ---------------------------------------------------------------- the fit and backtest
SHOCK_A, SHOCK_K, SHOCK_B = 2.0, 8.0, 4.0     # cbb_games_live's season-sim strength sd


def eligible_set(s, d1s):
    """D-I in each of the four seasons before (as far back as the history goes): transition years can't be selected"""
    back = [y for y in range(s - 4, s) if y in d1s and y != 2020]
    return set.intersection(*[set(d1s[y]) for y in back]) & set(d1s[s]) if back else set(d1s[s])


def prepare():
    """every season's cuts as Season objects plus the facts: field, seeds, automatic bids, conference tournaments"""
    p = os.path.join(C.CACHE, 'tourney_prep.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    rows, snaps, d1s = walk()
    TH = json.load(open(HIST))
    F = json.load(open(C.FIT))
    games = C.load_hist()
    margin = {g['id']: g['hs'] - g['as'] for g in games if g.get('hs') is not None}
    co = coefs(rows, F['feats'], margin)
    cuts = {(s, c): snaps[(s, c)]['date'] for s in SEASONS for c in ('feb1', 'mar1', 'sel') if (s, c) in snaps}
    gm = gm_snaps(games, cuts, d1s)
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    out = {}
    for s in SEASONS:
        th = TH[str(s)]
        ctids = {g['id'] for g in th['conftourn']}
        conf = {t: c for t, c in th['conf'].items()}
        field = {t: (v['seed'], v.get('region')) for t, v in th['field'].items()}
        last = {}
        for g in th['conftourn']:
            last[g['ch']] = g
        auto = {c: (g['home'] if g['hs'] > g['as'] else g['away']) for c, g in last.items()}
        for t in field:                        # a conference with no tournament: its one team in the field
            c = conf.get(t)
            if c and c not in auto and sum(1 for u in field if conf.get(u) == c) == 1:
                auto[c] = t
        ents = defaultdict(set)
        for g in th['conftourn']:
            ents[g['ch']].update((g['home'], g['away']))
        elig = eligible_set(s, d1s) | set(field)
        sel = cuts[(s, 'sel')]
        gs = []
        for g in sorted(by_s[s], key=lambda g: (g['date'], g['id'])):
            if g.get('hs') is None or g.get('stype') == 3 or C.et_date(g['date']) >= sel:
                continue
            gs.append(dict(g, ct=g['id'] in ctids))
        S = {}
        for c in ('feb1', 'mar1', 'sel'):
            sn = snaps[(s, c)]
            teams = [t for t in sorted(d1s[s]) if t in sn['net']]
            rating = team_rating(sn['net'], sn['T'], sn['tau'], sn['elo'], gm[(s, c)], teams, co[s])
            rank = {t: i + 1 for i, t in enumerate(sorted(teams, key=lambda t: -rating[t]))}
            ts = set(teams)
            d1g = [g for g in gs if g['home'] in ts and g['away'] in ts]
            SS = Season(teams, conf, rating, rank, None, F['sd'], co[s], elig)
            played = [g for g in d1g if C.et_date(g['date']) < sn['date']]
            left = [g for g in d1g if C.et_date(g['date']) >= sn['date'] and not g['ct']]
            nreg = defaultdict(int); nleft = defaultdict(int)
            for g in d1g:
                for t in (g['home'], g['away']):
                    nreg[t] += 1
                    if C.et_date(g['date']) >= sn['date']:
                        nleft[t] += 1
            tsd = np.array([math.sqrt(SHOCK_A ** 2 * SHOCK_K / (SHOCK_K + sn['ng'][t]) + SHOCK_B ** 2 * nleft[t] / max(1, nreg[t])) for t in teams])
            elim = defaultdict(set)
            for g in played:
                if g['ct']:
                    elim[conf.get(g['home'])].add(g['away'] if g['hs'] > g['as'] else g['home'])
            ctinfo = {}
            for cc in auto:
                info = {'n': len(ents.get(cc, ())), 'elim': elim.get(cc, set())}
                if c == 'sel':
                    info['champ'] = auto[cc]
                ctinfo[cc] = info
            S[c] = {'SS': SS, 'played': played, 'left': left, 'tsd': tsd, 'ctinfo': ctinfo, 'date': sn['date']}
        out[s] = {'cuts': S, 'field': field, 'auto': auto, 'ncaa': th['ncaa'], 'coef': co[s], 'n_at': len(field) - len(auto)}
        print('prep', s, len(field), 'field', len(auto), 'auto', flush=True)
    res = (out, rows, margin)
    pickle.dump(res, open(p, 'wb'))
    return res


def sel_rows(P):
    """Selection Sunday resumes: one row per eligible D-I team, with the facts"""
    R = []
    for s, d in P.items():
        cu = d['cuts']['sel']
        SS = cu['SS']
        W, wab, q1, bad = SS.resume(cu['played'])
        autos = set(d['auto'].values())
        for i, t in enumerate(SS.teams):
            if not SS.elig[i]:
                continue
            fs = d['field'].get(t)
            R.append({'s': s, 't': t, 'r': SS.r[i], 'wab': wab[i], 'q1': q1[i], 'bad': bad[i], 'auto': float(t in autos),
                      'wab2': wab[i] ** 2, 'r2': SS.r[i] ** 2, 'bid': float(t in d['field']), 'seed': fs[0] if fs else None, 'rk': SS.rank[t]})
    return R


def moments(R, feats):
    return {f: (float(np.mean([r[f] for r in R])), float(np.std([r[f] for r in R]) or 1.0)) for f in feats}


def topk_p(score, k, ok, rng, n=4000):
    """P(selected) when the k best of score + logistic noise get in (ok: candidates)"""
    idx = np.nonzero(ok)[0]
    u = rng.random((n, len(idx)))
    z = score[idx][None, :] + np.log(u / (1 - u))
    top = np.argpartition(-z, k - 1, 1)[:, :k]
    c = np.zeros(len(idx))
    np.add.at(c, top.ravel(), 1)
    p = np.zeros(len(score)); p[idx] = c / n
    return p


def fit_selection(R, rng):
    """at-large: a logit on the resume among teams without an automatic bid, held out a season at a time; scored as the
    simulated top-k chance (the way the sims use it) and as the plain logit"""
    seasons = sorted({r['s'] for r in R})
    cand = [r for r in R if not r['auto']]
    sets = {'rating only': ['r'], 'WAB only': ['wab'], 'rating + WAB': ['r', 'wab'], 'rating + WAB + Q1 wins': ['r', 'wab', 'q1'],
            'rating + WAB + Q1 + Q3/4 losses': ['r', 'wab', 'q1', 'bad'], 'WAB + Q1 wins': ['wab', 'q1']}
    res = {}
    for name, fs in sets.items():
        lt, lk, ys, ss = [], [], [], []
        for s in seasons:
            tr = [r for r in cand if r['s'] != s]; te = [r for r in cand if r['s'] == s]
            M = moments(tr, fs)
            b = logit_fit(np.array([[(r[f] - M[f][0]) / M[f][1] for f in fs] for r in tr]), np.array([r['bid'] for r in tr]))
            X = np.array([[(r[f] - M[f][0]) / M[f][1] for f in fs] for r in te])
            sc = b[0] + X @ b[1:]
            k = int(sum(r['bid'] for r in te))
            lt += list(ll(topk_p(sc, k, np.ones(len(te), bool), rng), [r['bid'] for r in te]))
            lk += list(ll(logit_p(X, b), [r['bid'] for r in te]))
            ys += [r['bid'] for r in te]; ss += [s] * len(te)
        res[name] = {'feats': fs, 'llTopk': np.array(lt), 'llLogit': np.array(lk), 'season': np.array(ss)}
    base = res['rating only']['llTopk']
    best = min(res, key=lambda n: res[n]['llTopk'].mean())
    rep = {n: {'feats': v['feats'], 'llTopk': round(float(v['llTopk'].mean()), 4), 'llLogit': round(float(v['llLogit'].mean()), 4),
               'tVsRating': round(paired_t(v['llTopk'], base), 2),
               'seasonsWon': int(sum(v['llTopk'][v['season'] == s].sum() < base[v['season'] == s].sum() for s in seasons))}
           for n, v in res.items()}
    core = res['rating + WAB']['llTopk']
    for n, v in res.items():
        rep[n]['tVsCore'] = round(paired_t(v['llTopk'], core), 2)
    ok = [n for n in res if n == 'rating + WAB' or rep[n]['tVsCore'] <= -2]
    best = min(ok, key=lambda n: res[n]['llTopk'].mean())
    fs = res[best]['feats']
    M = moments(cand, fs)
    b = logit_fit(np.array([[(r[f] - M[f][0]) / M[f][1] for f in fs] for r in cand]), np.array([r['bid'] for r in cand]))
    return {'feats': fs, 'M': M, 'b': [float(x) for x in b], 'name': best, 'cands': len(cand), 'bids': int(sum(r['bid'] for r in cand)),
            'tests': rep, 'seasons': len(seasons)}


def fit_seeds(R, P, rng):
    """seed line on the resume among the field (OLS, held out by season), then the S-curve noise sigma by the held-out
    log loss of each team's real seed line under the simulated S-curve (four a line, the First Four rule)"""
    seasons = sorted({r['s'] for r in R})
    fld = [r for r in R if r['bid']]
    sets = {'rating only': ['r'], 'rating + WAB': ['r', 'wab'], 'rating + WAB + Q1 wins': ['r', 'wab', 'q1'],
            'rating + WAB + Q1 + auto': ['r', 'wab', 'q1', 'auto'], 'rating + WAB + Q1 + Q3/4 + auto': ['r', 'wab', 'q1', 'bad', 'auto'],
            'rating + WAB, quadratic': ['r', 'wab', 'r2', 'wab2'], 'rating + WAB + auto': ['r', 'wab', 'auto']}
    res = {}
    for name, fs in sets.items():
        pred = {}
        for s in seasons:
            tr = [r for r in fld if r['s'] != s]
            M = moments(tr, fs)
            X = np.array([[1.0] + [(r[f] - M[f][0]) / M[f][1] for f in fs] for r in tr])
            b = np.linalg.lstsq(X, np.array([r['seed'] for r in tr], float), rcond=None)[0]
            for r in fld:
                if r['s'] == s:
                    pred[(s, r['t'])] = float(b[0] + sum(b[j + 1] * (r[f] - M[f][0]) / M[f][1] for j, f in enumerate(fs)))
        res[name] = {'feats': fs, 'pred': pred}
    out = {}
    for name, v in res.items():
        best = None
        for sig in (0.5, 0.7, 0.8, 0.9, 1.0, 1.2):
            lls, err, hit, ss = [], [], [], []
            for s in seasons:
                rs = [r for r in fld if r['s'] == s]
                al = {r['t'] for r in rs if not r['auto']}
                cnt = defaultdict(lambda: np.zeros(16))
                g = np.random.default_rng(s)
                for _ in range(400):
                    z = {r['t']: -v['pred'][(s, r['t'])] + sig * g.normal() for r in rs}
                    _, seed = bracket_slots(z, al)
                    for t, line in seed.items():
                        cnt[t][line - 1] += 1
                for r in rs:
                    p = (cnt[r['t']] + 0.05) / (cnt[r['t']].sum() + 0.8)
                    lls.append(-math.log(p[r['seed'] - 1]))
                    err.append(abs(float((np.arange(1, 17) * p).sum()) - r['seed']))
                    hit.append(float(np.argmax(p) + 1 == r['seed']))
                    ss.append(s)
            m = float(np.mean(lls))
            if best is None or m < best['ll']:
                best = {'sigma': sig, 'll': m, 'lls': np.array(lls), 'mae': float(np.mean(err)), 'exact': float(np.mean(hit)), 'season': np.array(ss)}
        out[name] = dict(best, feats=v['feats'])
    base = out['rating only']['lls']
    rep = {n: {'feats': v['feats'], 'sigma': v['sigma'], 'logLoss': round(v['ll'], 4), 'meanAbsLineErr': round(v['mae'], 3), 'exactLine': round(v['exact'], 3),
               'tVsRating': round(paired_t(v['lls'], base), 2),
               'seasonsWon': int(sum(v['lls'][v['season'] == s].sum() < base[v['season'] == s].sum() for s in seasons))}
           for n, v in out.items()}
    # the simplest resume (rating + WAB) unless an addition beats it held out at paired t <= -2
    core = out['rating + WAB']['lls']
    for n, v in out.items():
        rep[n]['tVsCore'] = round(paired_t(v['lls'], core), 2)
    ok = [n for n in out if n == 'rating + WAB' or rep[n]['tVsCore'] <= -2]
    best = min(ok, key=lambda n: out[n]['ll'])
    fs = out[best]['feats']
    M = moments(fld, fs)
    X = np.array([[1.0] + [(r[f] - M[f][0]) / M[f][1] for f in fs] for r in fld])
    b = np.linalg.lstsq(X, np.array([r['seed'] for r in fld], float), rcond=None)[0]
    return {'feats': fs, 'M': M, 'b': [float(x) for x in b], 'sigma': out[best]['sigma'], 'name': best, 'tests': rep, 'teams': len(fld)}


def committee(R, sel_f, seed_f, sigma, skip=None):
    """the committee fit (at-large logit, seed-line OLS) on every season but skip"""
    tr = [r for r in R if r['s'] != skip]
    cand = [r for r in tr if not r['auto']]
    M = moments(cand, sel_f)
    b = logit_fit(np.array([[(r[f] - M[f][0]) / M[f][1] for f in sel_f] for r in cand]), np.array([r['bid'] for r in cand]))
    fld = [r for r in tr if r['bid']]
    M2 = moments(fld, seed_f)
    X = np.array([[1.0] + [(r[f] - M2[f][0]) / M2[f][1] for f in seed_f] for r in fld])
    b2 = np.linalg.lstsq(X, np.array([r['seed'] for r in fld], float), rcond=None)[0]
    return {'sel': {'feats': sel_f, 'M': M, 'b': [float(x) for x in b]}, 'seed': {'feats': seed_f, 'M': M2, 'b': [float(x) for x in b2], 'sigma': sigma}}


def wins_in(ncaa):
    """each team's main-bracket wins (First Four left out) and the semifinal region pairs"""
    w = defaultdict(int)
    for g in ncaa:
        if 'first four' in g['note'].lower():
            continue
        w[g['home'] if g['hs'] > g['as'] else g['away']] += 1
    return w


def f4_pairs(ncaa, field):
    semi = [g for g in ncaa if re.search(r'final four|national semifinal', g['note'], re.I)]
    pr = [(field[g['home']][1], field[g['away']][1]) for g in semi if g['home'] in field and g['away'] in field]
    return pr if len(pr) == 2 and len({x for p in pr for x in p}) == 4 else None


def fit():
    P, rows, margin = prepare()
    F = json.load(open(C.FIT))
    G = {g['id']: g for g in C.load_hist()}
    R = sel_rows(P)
    rng = np.random.default_rng(2027)
    sel = fit_selection(R, rng)
    seed = fit_seeds(R, P, rng)
    seasons = sorted(P)
    res = {'note': 'NCAA tournament model (scripts/cbb_tourney.py --fit). Every test holds out one season at a time: the '
                   'committee is fit on the other seasons, the game model on the seasons before. Log loss in nats.',
           'seasons': seasons, 'selection': {k: v for k, v in sel.items()}, 'seeding': {k: v for k, v in seed.items()}}
    # at-large picks: the deterministic top k of the held-out score against the real at-large teams
    hits = []
    for s in seasons:
        m = committee(R, sel['feats'], seed['feats'], seed['sigma'], skip=s)['sel']
        cand = [r for r in R if r['s'] == s and not r['auto']]
        sc = np.array([m['b'][0] + sum(m['b'][j + 1] * (r[f] - m['M'][f][0]) / m['M'][f][1] for j, f in enumerate(m['feats'])) for r in cand])
        k = int(sum(r['bid'] for r in cand))
        top = set(np.argsort(-sc)[:k])
        hits.append((s, sum(cand[i]['bid'] for i in top), k))
    res['selection']['atLargeHits'] = {str(s): f'{int(h)}/{k}' for s, h, k in hits}
    res['selection']['atLargeHitRate'] = round(sum(h for _, h, _ in hits) / sum(k for _, _, k in hits), 4)

    # tournament games: the game model's pregame chance against a seed-gap logit
    xr = {r[1]: r[2] for r in rows}
    T = []
    for s in seasons:
        fld = P[s]['field']
        cu = P[s]['cuts']['sel']
        SS = cu['SS']
        co = P[s]['coef']
        for g in P[s]['ncaa']:
            if g['id'] not in xr or g['home'] not in fld or g['away'] not in fld or g['home'] not in SS.ti or g['away'] not in SS.ti:
                continue
            x = xr[g['id']]
            m = sum(co[f] * x[f] for f in F['feats'])
            hgt, agt = SS.ti[g['home']], SS.ti[g['away']]
            sdx = math.sqrt(F['sd'] ** 2 + cu['tsd'][hgt] ** 2 + cu['tsd'][agt] ** 2)
            hg = G.get(g['id'], {})
            T.append({'s': s, 'y': float(g['hs'] > g['as']), 'pm': float(ncdf(m / F['sd'])), 'pr': float(ncdf((SS.r[hgt] - SS.r[agt]) / sdx)),
                      'ds': fld[g['away']][0] - fld[g['home']][0],
                      'pk': C.ml_prob(hg['mlh'], hg['mla']) if hg.get('mlh') and hg.get('mla') else None})
    ps = np.zeros(len(T))
    for s in seasons:
        tr = [t for t in T if t['s'] != s]
        X = np.array([[t['ds']] for t in tr]); y = np.array([t['y'] for t in tr])
        b = 0.0
        for _ in range(50):
            p = 1 / (1 + np.exp(-b * X[:, 0]))
            b += float(((y - p) * X[:, 0]).sum() / ((p * (1 - p) * X[:, 0] ** 2).sum()))
        for i, t in enumerate(T):
            if t['s'] == s:
                ps[i] = 1 / (1 + math.exp(-b * t['ds']))
    y = np.array([t['y'] for t in T])
    lm, lr, lsd = ll([t['pm'] for t in T], y), ll([t['pr'] for t in T], y), ll(ps, y)
    S = np.array([t['s'] for t in T])
    mk = np.array([t['pk'] is not None for t in T])
    res['games'] = {'n': len(T), 'llModel': round(float(lm.mean()), 4), 'llSimRating': round(float(lr.mean()), 4), 'llSeed': round(float(lsd.mean()), 4),
                    'tModelVsSeed': round(paired_t(lm, lsd), 2), 'tSimVsSeed': round(paired_t(lr, lsd), 2),
                    'seasonsModelWon': int(sum(lm[S == s].sum() < lsd[S == s].sum() for s in seasons)),
                    'seasonsSimWon': int(sum(lr[S == s].sum() < lsd[S == s].sum() for s in seasons)),
                    'accModel': round(float(((np.array([t['pm'] for t in T]) > .5) == y).mean()), 3),
                    'accSeed': round(float(((ps > .5) == y).mean()), 3)}
    internal = {'nLined': int(mk.sum()), 'llMarket': round(float(ll([t['pk'] for t in T if t['pk'] is not None], y[mk]).mean()), 4),
                'llModelLined': round(float(lm[mk].mean()), 4)}
    print('games', res['games'], internal, flush=True)

    # Selection Sunday, the real bracket: chance each team wins each round, against seed history
    rr, sr, keys = defaultdict(list), defaultdict(list), []
    seedfreq = {}
    for s in seasons:
        fld = P[s]['field']; w = wins_in(P[s]['ncaa'])
        seedfreq[s] = (fld, w)
    for s in seasons:
        fld, w = seedfreq[s]
        cu = P[s]['cuts']['sel']
        SS = cu['SS']
        slots = actual_bracket(P[s]['ncaa'], fld, f4_pairs(P[s]['ncaa'], fld))
        if not slots or any(t not in SS.ti for sl in slots for t in sl if t is not None):
            print('no bracket', s); continue
        o = run(SS, cu['played'], [], {}, 0, None, 4000, np.random.default_rng(s), cu['tsd'], actual=slots)
        base = defaultdict(lambda: np.zeros(6)); cnt = defaultdict(int)
        for s2 in seasons:
            if s2 == s:
                continue
            f2, w2 = seedfreq[s2]
            for t, (sd_, _) in f2.items():
                cnt[sd_] += 1
                for k in range(6):
                    base[sd_][k] += w2.get(t, 0) > k
        for t, (sd_, _) in fld.items():
            if t not in SS.ti:
                continue
            for k, rd in enumerate(ROUNDS):
                yk = float(w.get(t, 0) > k)
                rr[rd].append(float(ll([o[rd][SS.ti[t]]], [yk])[0])); sr[rd].append(float(ll([(base[sd_][k] + .5) / (cnt[sd_] + 1)], [yk])[0]))
    res['rounds'] = {rd: {'llModel': round(float(np.mean(rr[rd])), 4), 'llSeed': round(float(np.mean(sr[rd])), 4), 't': round(paired_t(rr[rd], sr[rd]), 2)}
                     for rd in ROUNDS}
    allm = np.concatenate([rr[r] for r in ROUNDS]); alls = np.concatenate([sr[r] for r in ROUNDS])
    res['rounds']['all'] = {'llModel': round(float(allm.mean()), 4), 'llSeed': round(float(alls.mean()), 4), 't': round(paired_t(allm, alls), 2)}
    print('rounds', res['rounds'], flush=True)

    # forecasts from Feb 1 and Mar 1: the whole chain, scored on every eligible team
    fc = {}
    configs = {'model': (sel['feats'], seed['feats'], seed['sigma']), 'rating-only committee': (['r'], ['r'], seed['tests']['rating only']['sigma'])}
    for cut in ('feb1', 'mar1'):
        rec = defaultdict(lambda: defaultdict(list))
        for s in seasons:
            cu = P[s]['cuts'][cut]
            SS = cu['SS']
            fld = P[s]['field']; w = wins_in(P[s]['ncaa'])
            for name, (sf, df, sg) in configs.items():
                mdl = committee(R, sf, df, sg, skip=s)
                o = run(SS, cu['played'], cu['left'], cu['ctinfo'], P[s]['n_at'], mdl, 2000, np.random.default_rng(s * 7 + len(name)), cu['tsd'])
                for i, t in enumerate(SS.teams):
                    if not SS.elig[i]:
                        continue
                    yb = float(t in fld)
                    pc = np.concatenate([o['seed'][i], [1 - o['bid'][i]]])
                    pc = (pc + 1e-4) / (pc.sum() + 17e-4)
                    cat = fld[t][0] - 1 if t in fld else 16
                    rec[name]['bid'] += [float(ll([o['bid'][i]], [yb])[0])]
                    rec[name]['seed'] += [-math.log(pc[cat])]
                    rec[name]['f4'] += [float(ll([o['f4'][i]], [float(w.get(t, 0) >= 4)])[0])]
                    rec[name]['champ'] += [float(ll([o['champ'][i]], [float(w.get(t, 0) >= 6)])[0])]
                    rec[name]['p'] += [o['bid'][i]]; rec[name]['y'] += [yb]; rec[name]['s'] += [s]
            print(cut, s, flush=True)
        # a naive line: the bid chance as a logit on the rating at the cut, fit on the other seasons
        # a naive line: the bid chance as a logit on the rating at the cut, fit on the other seasons
        nr = [(s, P[s]['cuts'][cut]['SS'].r[i], float(t in P[s]['field'])) for s in seasons
              for i, t in enumerate(P[s]['cuts'][cut]['SS'].teams) if P[s]['cuts'][cut]['SS'].elig[i]]
        for s in seasons:
            tr = np.array([(r_, y_) for s2, r_, y_ in nr if s2 != s]); te = np.array([(r_, y_) for s2, r_, y_ in nr if s2 == s])
            b = logit_fit(tr[:, :1], tr[:, 1], ridge=0.0)
            rec['naive rating logit']['bid'] += list(ll(logit_p(te[:, :1], b), te[:, 1]))
        out = {}
        for name, v in rec.items():
            out[name] = {k: round(float(np.mean(v[k])), 4) for k in ('bid', 'seed', 'f4', 'champ') if v[k]}
            if name != 'model':
                for k in ('bid', 'seed', 'f4', 'champ'):
                    if v[k]:
                        out[name]['tModelVs_' + k] = round(paired_t(rec['model'][k], v[k]), 2)
        p, yy = np.array(rec['model']['p']), np.array(rec['model']['y'])
        bins = [(0, .05), (.05, .25), (.25, .5), (.5, .75), (.75, .95), (.95, 1.01)]
        out['calibration'] = [{'bin': f'{a:.2f}-{min(b, 1):.2f}', 'n': int(((p >= a) & (p < b)).sum()), 'pred': round(float(p[(p >= a) & (p < b)].mean()), 3),
                               'real': round(float(yy[(p >= a) & (p < b)].mean()), 3)} for a, b in bins if ((p >= a) & (p < b)).any()]
        fc[cut] = out
        print(cut, out, flush=True)
    res['forecast'] = fc
    res['committee'] = committee(R, sel['feats'], seed['feats'], seed['sigma'])
    res['summary'] = summary(res)
    with open(FIT, 'w') as f:
        json.dump(C_finite(res), f, indent=1)
    with open(os.path.join(C.CACHE, 'tourney_internal.json'), 'w') as f:
        json.dump(internal, f)
    print('wrote', FIT)


def live(rows, d1, confs, net, T, tau, elo, ng, coef, sd, season, nsim=5000):
    """today's tournament odds for cbb_games_live: rows (this season's ESPN games), d1 (rated teams), confs (team ->
    board conference), the efficiency solve's net/T/tau, Elo, games played. Returns {team: odds} or {} with no fit"""
    if not os.path.exists(FIT):
        return {}
    import control_ratings as CR
    Fit = json.load(open(FIT))
    mdl = Fit['committee']
    teams = sorted(d1)
    ts = set(teams)
    H = json.load(gzip.open(CR.CBB_HIST, 'rt'))
    done = [g for g in rows if g.get('hs') is not None]
    fin = CR.ratings(CR.cbb_gl([dict(g, season=season) for g in done]) if done else [], CR.margin_control(done),
                     prev=H['final']['gm'].get(str(season - 1), {}), **CR.CBB_FIT)[1]
    gm = fin.get(season) or {t: CR.CBB_FIT['carry'] * v for t, v in H['final']['gm'].get(str(season - 1), {}).items()}
    rating = team_rating(net, T, tau, elo, gm, teams, coef)
    rank = {t: i + 1 for i, t in enumerate(sorted(teams, key=lambda t: -rating[t]))}
    hist = C.load_hist()
    d1s = {s: C.d1_set([g for g in hist if g['season'] == s]) for s in range(season - 4, season)}
    elig = eligible_set(season, {**{s: sorted(v) for s, v in d1s.items()}, season: teams})
    SS = Season(teams, confs, rating, rank, None, sd, coef, elig)
    ct = lambda g: bool(g.get('conf') and re.search(r'tournament|championship|playoff', g.get('note') or '', re.I)) and g.get('stype') != 3
    gs = [dict(g, ct=ct(g)) for g in rows if g['home'] in ts and g['away'] in ts and g.get('stype') != 3]
    played = [g for g in gs if g.get('hs') is not None]
    left = [g for g in gs if g.get('hs') is None and not g['ct']]
    nreg, nleft = defaultdict(int), defaultdict(int)
    for g in gs:
        for t in (g['home'], g['away']):
            nreg[t] += 1
            nleft[t] += g.get('hs') is None
    tsd = np.array([math.sqrt(SHOCK_A ** 2 * SHOCK_K / (SHOCK_K + ng.get(t, 0)) + SHOCK_B ** 2 * nleft[t] / max(1, nreg[t])) for t in teams])
    # conference tournaments: entrants from last season's (the share of each conference's teams that played in it)
    TH = json.load(open(HIST))
    last = TH.get(str(season - 1)) or TH[max(TH)]
    ent = defaultdict(set)
    for g in last['conftourn']:
        ent[g['ch']].update((g['home'], g['away']))
    size = defaultdict(int)
    for t, c in last['conf'].items():
        size[c] += 1
    members = defaultdict(list)
    for t in teams:
        if confs.get(t):
            members[confs[t]].append(t)
    elim = defaultdict(set)
    for g in played:
        if g['ct']:
            elim[confs.get(g['home'])].add(g['away'] if g['hs'] > g['as'] else g['home'])
    ctinfo = {}
    for c, mem in members.items():
        if len(mem) < 5:
            continue
        ids = defaultdict(int)
        for t in mem:
            if last['conf'].get(t):
                ids[last['conf'][t]] += 1
        e = max(ids, key=ids.get) if ids else None
        share = len(ent.get(e, ())) / size[e] if e and size[e] else 1.0
        n = int(round(share * len(mem)))
        alive = [t for t in mem if t not in elim[c] and SS.elig[SS.ti[t]]]
        info = {'n': n, 'elim': elim[c]}
        if elim[c] and len(alive) == 1:
            info['champ'] = alive[0]
        ctinfo[c] = info
    n_at = 68 - len(ctinfo)
    # the bracket, once ESPN lists it: seeds (curatedRank) and regions from the tournament's games
    tg = [g for g in rows if g.get('stype') == 3 and NCAA_NOTE.search(g.get('note') or '')]
    actual, fdone = None, None
    if tg:
        sr = {}
        for g in tg:
            m = REGION.search(g['note'])
            for k in ('home', 'away'):
                sdv = g.get(k[0] + 'ap')
                if sdv and m and g[k] in SS.ti:
                    sr[g[k]] = (sdv, m[1].title())
        slots = actual_bracket(tg, sr, None, rating) if len(sr) >= 64 else None
        if slots:
            actual = slots
            fdone = [(SS.ti[g['home']], SS.ti[g['away']]) if g['hs'] > g['as'] else (SS.ti[g['away']], SS.ti[g['home']])
                     for g in tg if g.get('hs') is not None and g['home'] in SS.ti and g['away'] in SS.ti]
    o = run(SS, played, left, ctinfo, n_at, mdl, nsim, np.random.default_rng(int(datetime.utcnow().strftime('%Y%m%d'))), tsd,
            actual=actual, done=fdone)
    out = {}
    for i, t in enumerate(teams):
        b = float(o['bid'][i])
        sc = o['seed'][i]
        out[t] = {'bid': round(b, 3), 'auto': round(float(o['auto'][i]), 3),
                  'seed': round(float((np.arange(1, 17) * sc).sum() / sc.sum()), 1) if sc.sum() > 0 else None,
                  **{k: round(float(o[k][i]), 3) for k in ('r32', 's16', 'e8', 'f4', 'final', 'champ')}}
        if actual:
            if t in sr:
                out[t]['seed'] = sr[t][0]
    meta = {'atLarge': n_at, 'autobids': len(ctinfo), 'bracket': bool(actual), 'sims': nsim}
    return out, meta


def summary(res):
    """the headline numbers the site's note reads (flat keys for the template)"""
    sd = res['seeding']['tests'][res['seeding']['name']]
    return {'atLargeHit': res['selection']['atLargeHitRate'], 'exactLine': sd['exactLine'], 'lineErr': sd['meanAbsLineErr'],
            'tBidMar1': res['forecast']['mar1']['rating-only committee']['tModelVs_bid'], 'tRounds': res['rounds']['all']['t'],
            'llGames': res['games']['llModel'], 'llGamesSeed': res['games']['llSeed']}


def C_finite(x):
    if isinstance(x, dict):
        return {str(k): C_finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [C_finite(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        x = x.item()
    return None if isinstance(x, float) and not math.isfinite(x) else x


if __name__ == '__main__':
    if '--walk' in sys.argv:
        walk()
    elif '--fit' in sys.argv:
        fit()
