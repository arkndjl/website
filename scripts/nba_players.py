#!/usr/bin/env python3
"""NBA player projections for Predictions: each player's points, rebounds and assists (and PRA) in tonight's game,
with a full distribution so an over/under prices (data/nba_players.json, static/data/nba-players.json), and the
model behind them (data/nba_players_fit.json).

    python3 scripts/nba_players.py --pull 2021 2026   # box-score stat lines from ESPN into scripts/nba_pbox_hist.json.gz
    python3 scripts/nba_players.py --fit              # walk-forward backtest 2022-26 (tune 2022-23, held out 2024-26)
    python3 scripts/nba_players.py                    # today's and tomorrow's projections (stdlib; runs in the NBA build)
"""
import datetime as dt
import gzip
import json
import math
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_espn as E  # noqa: E402

ROOT = E.ROOT
HERE_ = os.path.dirname(os.path.abspath(__file__))
PCACHE = os.path.join(ROOT, 'scripts', '.cache', 'nba', 'pbox')
PHIST = os.path.join(ROOT, 'scripts', 'nba_pbox_hist.json.gz')
FIT = os.path.join(ROOT, 'data', 'nba_players_fit.json')
STATS = ('pts', 'reb', 'ast', 'fg3', 'stl', 'blk', 'tov')


def _n(s):
    try:
        return float(str(s).split('-')[0])
    except (TypeError, ValueError):
        return 0.0


def pbox(gid, fresh=False):
    """{team: [[espn id, name, pos, starter, min, pts, reb, ast, fg3m, stl, blk, tov, fga, fta], ...]} for one game
    (players with minutes only), or None when ESPN has no player lines"""
    fn = os.path.join(PCACHE, gid + '.json')
    if not fresh and os.path.exists(fn):
        return json.load(open(fn))
    j = E.get(f'{E.SITE}/summary?event={gid}')
    if j is None or 'boxscore' not in j:
        return None
    out = {}
    for t in j['boxscore'].get('players', []):
        ab = E.team(t['team']['abbreviation'])
        rows = []
        for st in t.get('statistics', [])[:1]:
            keys = st.get('keys') or []
            for p in st.get('athletes', []):
                d = dict(zip(keys, p.get('stats', [])))
                mn = _n(d.get('minutes'))
                if not mn:
                    continue
                a = p.get('athlete', {})
                fg = str(d.get('fieldGoalsMade-fieldGoalsAttempted', '0-0')).split('-')
                ft = str(d.get('freeThrowsMade-freeThrowsAttempted', '0-0')).split('-')
                rows.append([a.get('id'), a.get('displayName'), (a.get('position') or {}).get('abbreviation'),
                             1 if p.get('starter') else 0, mn, _n(d.get('points')), _n(d.get('rebounds')),
                             _n(d.get('assists')), _n(d.get('threePointFieldGoalsMade-threePointFieldGoalsAttempted')),
                             _n(d.get('steals')), _n(d.get('blocks')), _n(d.get('turnovers')),
                             _n(fg[-1] if len(fg) == 2 else 0), _n(ft[-1] if len(ft) == 2 else 0)])
        out[ab] = rows
    if not out or all(not r for r in out.values()):
        return None
    E.save(fn, out)
    return out


def pull(lo, hi):
    """box-score stat lines for every final game of seasons lo..hi in the game model's history, frozen to PHIST"""
    import nba_games as N
    games, _ = N.load_hist()
    ids = [g['id'] for g in games if lo <= g['S'] <= hi]
    try:
        with gzip.open(PHIST, 'rt') as f:
            have = json.load(f)
    except (OSError, ValueError):
        have = {}
    todo = [i for i in ids if i not in have]
    print(len(ids), 'games,', len(todo), 'to pull', flush=True)
    done = 0
    with ThreadPoolExecutor(12) as ex:
        for gid, b in zip(todo, ex.map(pbox, todo)):
            if b:
                have[gid] = b
            done += 1
            if done % 500 == 0:
                print(done, flush=True)
    with gzip.open(PHIST, 'wt') as f:
        json.dump(have, f, separators=(',', ':'))
    print(len(have), 'games frozen', flush=True)


# ---------------------------------------------------------------- model
POS = {'PG': 'G', 'SG': 'G', 'G': 'G', 'SF': 'F', 'PF': 'F', 'F': 'F', 'C': 'C', 'FC': 'C', 'GF': 'F'}
PSTATS = ('pts', 'reb', 'ast')
IDX = {'min': 4, 'pts': 5, 'reb': 6, 'ast': 7, 'fg3': 8, 'stl': 9, 'blk': 10, 'tov': 11}
# the inputs of each stat's line (each one is the player's base line, minutes x rate, times a factor; see feats())
FEATS = ('base', 'long', 'savg', 'fill', 'use', 'pace', 'opp', 'home', 'rest', 'n2', 'imp', 'eS', 'eB', 'eL')
# candidates tested as one: the season's first games, when last season's tail (rest, tanking, injuries) misleads
GROUPS = {'early': ('eS', 'eB', 'eL')}
EARLY = 5.0


class Rates:
    """per-minute rates and minutes, by player, walked in tip order next to the game model's own state (nba_games.Model:
    role minutes, rosters, missed streaks, ratings), which it leaves untouched"""
    def __init__(self, hl=20.0, k0=75.0, carry=0.6, mhl=6.0, ohl=15.0):
        self.a = 0.5 ** (1 / hl)                           # rates: decay a game played
        self.ma = 0.5 ** (1 / mhl)                         # long minutes: decay a game played
        self.oa = 0.5 ** (1 / ohl)                         # opponents' stats allowed: decay a team game
        self.k0, self.carry = k0, carry
        self.r = defaultdict(lambda: defaultdict(float))   # pid -> stat -> weighted total; 'min' weighted minutes
        self.mL = {}                                       # pid -> [weighted minutes, weight]
        self.pos = {}
        self.lg = defaultdict(lambda: [0.0, 0.0])          # (pos, stat) -> [stat, minutes] league, running
        self.allow = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))   # team -> stat -> [allowed/48 over league, weight]
        self.season = None

    def new_season(self, S):
        for d in self.r.values():
            for k in d:
                d[k] *= self.carry
        for v in self.mL.values():
            v[0] *= 0.5; v[1] *= 0.5
        for d in self.allow.values():
            for v in d.values():
                v[0] *= 0.3; v[1] *= 0.3
        self.season = S

    def lgrate(self, pos, s):
        v = self.lg[(pos, s)]
        return v[0] / v[1] if v[1] else 0.0

    def rate(self, pid, s):
        """per minute, shrunk toward the position's league rate with k0 minutes"""
        d = self.r.get(pid)
        pos = self.pos.get(pid, 'F')
        lr = self.lgrate(pos, s)
        if not d:
            return lr
        return (d[s] + self.k0 * lr) / (d['min'] + self.k0)

    def long_min(self, pid):
        v = self.mL.get(pid)
        return v[0] / v[1] if v and v[1] else None

    def opp(self, t, s):
        v = self.allow[t][s]
        return v[0] / (v[1] + 3.0)

    def update(self, box, teams):
        """box: {team: rows}; teams: (home, away)"""
        h, a = teams
        for t, o in ((h, a), (a, h)):
            rows = box.get(t) or []
            tot = sum(r[4] for r in rows)
            if tot < 200:
                continue
            exp = defaultdict(float)
            got = defaultdict(float)
            for r in rows:
                pid, mn = r[0], r[4]
                if r[2]:
                    self.pos[pid] = POS.get(r[2], 'F')
                pos = self.pos.get(pid, 'F')
                for s in PSTATS + ('fg3',):
                    exp[s] += self.lgrate(pos, s) * mn
                    got[s] += r[IDX[s]]
                d = self.r[pid]
                for s in STATS:
                    d[s] = d[s] * self.a + r[IDX[s]]
                d['min'] = d['min'] * self.a + mn
                v = self.mL.setdefault(pid, [0.0, 0.0])
                v[0] = v[0] * self.ma + mn; v[1] = v[1] * self.ma + 1
                for s in STATS:
                    lv = self.lg[(pos, s)]
                    lv[0] = lv[0] * 0.9995 + r[IDX[s]]; lv[1] = lv[1] * 0.9995 + mn
            # what the opponent allowed, per 48 team minutes, over what the league's rates expected of these minutes
            for s in PSTATS + ('fg3',):
                if exp[s] > 0:
                    v = self.allow[o][s]
                    v[0] = v[0] * self.oa + (got[s] / exp[s] - 1); v[1] = v[1] * self.oa + 1


def team_rows(m, R, g, t, o, status, reported, pace_rel, imp_rel):
    """every rostered player's inputs for team t tonight: {pid: (P(play), mins, {stat: {feat: value}})}"""
    import nba_games as N
    ros = []
    for p in m.roster(t):
        mS, w = m.role[p]
        if w <= 0:
            continue
        mS = mS / w
        pr = N.play_prob(m.P, (status or {}).get(p), m.streak[p], reported)
        ros.append((p, mS, pr))
    if not ros:
        return {}
    A = sum(mS * pr for _, mS, pr in ros)
    fill = 240.0 / min(max(A, 150.0), 330.0) - 1.0
    tot = {s: sum(mS * R.rate(p, s) for p, mS, _ in ros) or 1.0 for s in PSTATS}
    gone = {s: sum(mS * R.rate(p, s) * (1 - pr) for p, mS, pr in ros) for s in PSTATS}
    home = 0.0 if g.get('n') else (1.0 if t == g['h'] else -1.0)
    rest = m.sched(g, t, g['h'])[0]
    n2m = (getattr(m, 'b2b', None) or {}).get('M', {}) if t in getattr(m, 'night2', ()) else {}
    out = {}
    for p, mS, pr in ros:
        # night two of a back-to-back by age and role (the game model's b2b minutes factors) in place of one flat 'rest'
        n2 = n2m.get(N.b2b_group(m.ages.get(p, 0), mS), 1.0) - 1.0 if n2m else 0.0
        mL = R.long_min(p) or mS
        fx = {}
        for s in PSTATS:
            r = R.rate(p, s)
            b = mS * r
            mine = mS * r * (1 - pr)
            use = (gone[s] - mine) / tot[s]
            fx[s] = {'base': b, 'long': mL * r, 'fill': b * fill, 'use': b * use, 'pace': b * pace_rel,
                     'opp': b * R.opp(o, s), 'home': b * home, 'rest': b * (1.0 if rest == 0 else 0.0),
                     'n2': b * n2, 'imp': b * imp_rel}
        fx['min'] = {'base': mS, 'long': mL, 'fill': mS * fill, 'use': 0.0, 'pace': 0.0, 'opp': 0.0,
                     'home': mS * home, 'rest': mS * (1.0 if rest == 0 else 0.0), 'n2': mS * n2, 'imp': 0.0}
        out[p] = (pr, mS, fx)
    return out


SAVG_K = 0.0


def add_savg(fx, cur, prv, k=SAVG_K):
    """his season average to date, with last season's average counted as k games (his base line in its place when
    he has no last season); cur, prv: [games, min, pts, reb, ast] or None"""
    for i, s in enumerate(('min',) + PSTATS, start=1):
        pa = prv[i] / prv[0] if prv and prv[0] >= 5 else fx[s]['base']
        n = cur[0] if cur else 0
        fx[s]['savg'] = ((cur[i] if cur else 0.0) + k * pa) / (n + k) if n + k > 0 else pa
        e = max(0.0, 1 - n / EARLY)
        fx[s]['eS'], fx[s]['eB'], fx[s]['eL'] = fx[s]['savg'] * e, fx[s]['base'] * e, fx[s]['long'] * e


def game_rows(m, R, g):
    """(pid, team, P(play), role minutes, feats by stat) for both teams, before tip; m has had m.feats(g) called"""
    h, a = g['h'], g['a']
    P = m.lgp[0] / m.lgp[1]
    pace = P + m.rate(m.pace, h) + m.rate(m.pace, a)
    pace_rel = pace / P - 1.0
    rows = []
    T, L = g.get('T'), g.get('L')
    for t, o in ((h, a), (a, h)):
        st, rep = m.status_for(g, t)
        imp_rel = 0.0
        if T and L is not None:
            # the market's implied points for t (L: home margin, positive = home favored) over t's usual
            implied = (T + L) / 2 if t == h else (T - L) / 2
            imp_rel = implied / (m.tlg / 2 + m.tm[t]) - 1.0 if m.tlg else 0.0
        for p, v in team_rows(m, R, g, t, o, st, rep, pace_rel, imp_rel).items():
            rows.append((p, t) + v)
    return rows


def collect(params=None, lo=2020, savg_k=None):
    """walk every game; rows for each rostered player before tip, with what he did (or None: he sat).
    returns list of dicts (season, gid, pid, team, pr, mS, fx, y, base)"""
    import nba_games as N
    import nba_games_fit as F
    games, names = N.load_hist()
    with gzip.open(PHIST, 'rt') as f:
        box = json.load(f)
    fit = json.load(open(os.path.join(ROOT, 'data', 'nba_games_fit.json')))
    m = N.Model(names, fit['P'], inj=F.load_inj(), **{k: v for k, v in fit['params'].items()})
    R = Rates(**(params or {}))
    seas = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0]))   # S -> pid -> [gp, min, pts, reb, ast]
    out = []
    for g in games:
        if g['S'] < 2019:
            continue
        m.feats(g)
        if g['S'] != R.season:
            R.new_season(g['S'])
        b = box.get(g['id'])
        if b and g['S'] >= lo and g.get('fin'):
            played = {r[0]: r for t in b for r in b[t]}
            for pid, t, pr, mS, fx in game_rows(m, R, g):
                cur, prv = seas[g['S']].get(pid), seas[g['S'] - 1].get(pid)
                ref = cur if cur and cur[0] >= 1 else (prv if prv and prv[0] >= 5 else None)
                naive = None if not ref else [ref[i] / ref[0] for i in (1, 2, 3, 4)]
                add_savg(fx, cur, prv, SAVG_K if savg_k is None else savg_k)
                r = played.get(pid)
                y = None if not r else [r[4], r[5], r[6], r[7]]
                out.append({'S': g['S'], 'g': g['id'], 'p': pid, 't': t, 'pr': pr, 'mS': mS, 'fx': fx, 'y': y,
                            'nv': naive, 'gp': cur[0] if cur else 0, 'po': 1 if g['t'] == 3 else 0})
        if b and g.get('fin'):
            R.update(b, (g['h'], g['a']))
            for t in b:
                for r in b[t]:
                    a = seas[g['S']][r[0]]
                    a[0] += 1; a[1] += r[4]; a[2] += r[5]; a[3] += r[6]; a[4] += r[7]
        m.update(g)
    return out


# ---------------------------------------------------------------- distribution
def nb_over(mu, var, line):
    """P(X > line) for a count with mean mu and variance var: negative binomial (Poisson when var <= mu)"""
    k = math.floor(line)
    if mu <= 0:
        return 0.0
    if var <= mu * 1.0001:
        pm, c = math.exp(-mu), 0.0
        for x in range(k + 1):
            c += pm
            pm *= mu / (x + 1)
        return max(0.0, 1 - c)
    r = mu * mu / (var - mu)
    q = mu / var                                    # success prob in the (r, q) parametrization
    pm = q ** r
    c = 0.0
    for x in range(k + 1):
        c += pm
        pm *= (x + r) / (x + 1) * (1 - q)
    return max(0.0, 1 - c)


def var_of(V, s, mu):
    a, b = V[s]
    return max(mu * 1.0001, a * mu + b * mu * mu)


SEL_T = -1.5
TUNE, HOLD = (2021, 2022, 2023), (2024, 2025, 2026)


def fit(write=True):
    import numpy as np
    rows = collect()
    D = [r for r in rows if r['y'] and r['nv'] and r['mS'] >= 10 and not r['po']]
    S = np.array([r['S'] for r in D])
    Y = {s: np.array([r['y'][i] for r in D]) for i, s in enumerate(('min',) + PSTATS)}
    NV = {s: np.array([r['nv'][i] for r in D]) for i, s in enumerate(('min',) + PSTATS)}
    X = {s: {f: np.array([r['fx'][s][f] for r in D]) for f in FEATS} for s in ('min',) + PSTATS}
    tune, hold = np.isin(S, TUNE), np.isin(S, HOLD)

    def wf(s, feats):
        A = np.column_stack([X[s][f] for f in feats])
        pred = np.full(len(S), np.nan)
        for yr in sorted(set(S)):
            tr, te = S < yr, S == yr
            if tr.sum() < 1000:
                continue
            pred[te] = A[te] @ np.linalg.lstsq(A[tr], Y[s][tr], rcond=None)[0]
        return pred

    def pt(e1, e0):
        d = e1 - e0
        return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))

    rep = {'n': {'tune': int(tune.sum()), 'hold': int(hold.sum())}, 'stats': {}}
    preds = {}
    for s in ('min',) + PSTATS:
        feats = ['base', 'long', 'savg']
        cur = wf(s, feats)
        log = []
        cands = [f for f in FEATS if not any(f in g for g in GROUPS.values())] + list(GROUPS)
        for f in cands:
            if f in feats or (s == 'min' and f in ('use', 'pace', 'opp', 'imp')):
                continue
            add = list(GROUPS.get(f, (f,)))
            new = wf(s, feats + add)
            e0, e1 = (Y[s] - cur) ** 2, (Y[s] - new) ** 2
            tt, th = pt(e1[tune], e0[tune]), pt(e1[hold], e0[hold])
            keep = tt <= SEL_T and th <= 0
            log.append({'feat': f, 't_tune': round(tt, 2), 't_hold': round(th, 2), 'keep': keep})
            print(s, f, round(tt, 2), round(th, 2), keep, flush=True)
            if keep:
                feats += add; cur = new
        A = np.column_stack([X[s][f] for f in feats])
        coef = np.linalg.lstsq(A[S <= max(HOLD)], Y[s][S <= max(HOLD)], rcond=None)[0]
        preds[s] = cur
        rep['stats'][s] = {'feats': feats, 'coef': [round(float(c), 4) for c in coef], 'select': log}
    preds['pra'] = preds['pts'] + preds['reb'] + preds['ast']
    Y['pra'] = Y['pts'] + Y['reb'] + Y['ast']
    NV['pra'] = NV['pts'] + NV['reb'] + NV['ast']
    # accuracy against the naive season average (to date; last season's before his first game)
    for s in ('min',) + PSTATS + ('pra',):
        ok = ~np.isnan(preds[s])
        acc = {}
        for nm, msk in (('tune', tune & ok), ('hold', hold & ok)):
            em, en = np.abs(Y[s][msk] - preds[s][msk]), np.abs(Y[s][msk] - NV[s][msk])
            acc[nm] = {'mae': round(float(em.mean()), 3), 'naive': round(float(en.mean()), 3),
                       'rmse': round(float(np.sqrt(((Y[s][msk] - preds[s][msk]) ** 2).mean())), 3),
                       'naiveRmse': round(float(np.sqrt(((Y[s][msk] - NV[s][msk]) ** 2).mean())), 3),
                       't': round(pt(em, en), 1)}
        rep['stats'].setdefault(s, {})['acc'] = acc
        print(s, acc, flush=True)
    # spread: variance = a mu + b mu^2, fit on the tuning seasons' residuals; checked on held-out over/unders
    V = {}
    for s in PSTATS + ('pra',):
        msk = tune & ~np.isnan(preds[s]) & (preds[s] > 0)
        mu = preds[s][msk]
        e2 = (Y[s][msk] - mu) ** 2
        ab = np.linalg.lstsq(np.column_stack([mu, mu * mu]), e2, rcond=None)[0]
        V[s] = [float(ab[0]), float(ab[1])]
    cal = {}
    for s in PSTATS + ('pra',):
        msk = hold & ~np.isnan(preds[s]) & (preds[s] > 0)
        mu, y, nv = preds[s][msk], Y[s][msk], NV[s][msk]
        line = np.floor(nv) + 0.5                       # a stand-in prop line: his season average, on the half point
        p = np.array([nb_over(a, var_of(V, s, a), L) for a, L in zip(mu, line)])
        o = (y > line).astype(float)
        bins = []
        for lo_, hi_ in ((0, .3), (.3, .4), (.4, .45), (.45, .5), (.5, .55), (.55, .6), (.6, .7), (.7, 1.01)):
            b = (p >= lo_) & (p < hi_)
            if b.sum() >= 50:
                bins.append({'p': round(float(p[b].mean()), 3), 'hit': round(float(o[b].mean()), 3), 'n': int(b.sum())})
        # coverage of the 10-90 band
        lo10 = np.array([q_at(a, var_of(V, s, a), .1) for a in mu]); hi90 = np.array([q_at(a, var_of(V, s, a), .9) for a in mu])
        cal[s] = {'brier': round(float(((p - o) ** 2).mean()), 4), 'brier50': round(float(((0.5 - o) ** 2).mean()), 4),
                  'bins': bins, 'in80': round(float(((y >= lo10) & (y <= hi90)).mean()), 3), 'var': [round(x, 4) for x in V[s]]}
        print(s, cal[s], flush=True)
    rep['calib'] = cal
    rep['var'] = {s: [round(x, 4) for x in V[s]] for s in V}
    if write:
        with open(FIT, 'w') as f:
            json.dump(rep, f, indent=1)
    return rep


def q_at(mu, var, q):
    """the q quantile of the count (smallest x with P(X <= x) >= q)"""
    x = 0
    while x < 200 and 1 - nb_over(mu, var, x) < q:
        x += 1
    return x


# ---------------------------------------------------------------- daily build
OUT = os.path.join(ROOT, 'data', 'nba_players.json')            # read by Hugo (and by props_snap.py)
PROPS = os.path.join(HERE_, 'data', 'props')
NAMES = {'pts': 'points', 'reb': 'rebounds', 'ast': 'assists', 'pra': 'points + rebounds + assists'}


def project(F, fx):
    """mean line if he plays, by stat (PRA = the sum), and its spread (sd)"""
    out = {}
    for s in ('min',) + PSTATS:
        st = F['stats'][s]
        out[s] = max(0.0, sum(c * fx[s][f] for c, f in zip(st['coef'], st['feats'])))
    out['pra'] = out['pts'] + out['reb'] + out['ast']
    sd = {s: math.sqrt(var_of(F['var'], s, out[s])) for s in PSTATS + ('pra',) if out[s] > 0}
    return out, sd


def latest_props():
    """{(game id, athlete id, stat): last snapshot row} from scripts/data/props (this month and last)"""
    out = {}
    if not os.path.isdir(PROPS):
        return out
    for fn in sorted(os.listdir(PROPS))[-2:]:
        for ln in open(os.path.join(PROPS, fn)):
            try:
                r = json.loads(ln)
                out[(r['id'], r['a'], r['s'])] = r
            except (ValueError, KeyError):
                continue
    return out


def no_vig(oO, oU):
    """the over's no-vig chance from two American prices"""
    imp = lambda o: 100 / (o + 100) if o > 0 else -o / (-o + 100)
    if oO is None or oU is None:
        return None
    a, b = imp(oO), imp(oU)
    return a / (a + b)


def build():
    import nba_games as N
    import nba_games_build as B
    F = json.load(open(FIT))
    GF = json.load(open(N.FIT))
    now = dt.datetime.now(dt.timezone.utc)
    S = B.current_season()
    hist, names = N.load_hist()
    games = [g for g in hist if g['S'] >= 2019]
    cur = []
    for s_ in range(max(g['S'] for g in hist) + 1, S + 1):
        for r in N.season_games(s_, live=(s_ == S)):
            names.update(r.pop('nm', {}))
            if s_ < S and not r['fin']:
                continue
            (cur if s_ == S else games).append(r)
    if not cur:
        return print('nba players: no schedule yet for', S)
    games += [g for g in cur if g['fin']]
    upcoming = [g for g in cur if not g['fin']]
    with gzip.open(PHIST, 'rt') as f:
        box = json.load(f)
    need = [g['id'] for g in games if g['id'] not in box and g.get('fin')]
    with ThreadPoolExecutor(8) as ex:
        for gid, b in zip(need, ex.map(pbox, need)):
            if b:
                box[gid] = b
    ros = B.rosters()
    for t, ps in ros.items():
        names.update(ps)
    m = N.Model(names, GF['P'], **GF['params'])
    R = Rates()
    seas = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0]))
    pos = {}
    for g in games:
        m.feats(g)
        if g['S'] != R.season:
            R.new_season(g['S'])
        b = box.get(g['id'])
        if b:
            R.update(b, (g['h'], g['a']))
            for t in b:
                for r in b[t]:
                    a = seas[g['S']][r[0]]
                    a[0] += 1; a[1] += r[4]; a[2] += r[5]; a[3] += r[6]; a[4] += r[7]
                    pos[r[0]] = r[2]
        m.update(g)
    if m.season != S:
        m.new_season(S)
    if R.season != S:
        R.new_season(S)
    for t, ps in ros.items():
        for p in list(m.members[t]):
            if p not in ps:
                m.members[t].discard(p); m.team.pop(p, None)
        for p in ps:
            m.set_team(p, t)
    rep, rep_at = B.official_report(now.astimezone(B.ET))
    espn = B.espn_injuries()
    days = sorted({N.tipdt(g).astimezone(B.ET).date() for g in upcoming})
    slate = set(days[:2])
    today = now.astimezone(B.ET).date()
    props = latest_props()
    out = []
    for g in upcoming:
        d = N.tipdt(g).astimezone(B.ET).date()
        st = {}
        if d in slate:
            r_ = rep.get((g['a'], g['h'])) if d == today else None
            for t in (g['h'], g['a']):
                for p in m.roster(t):
                    k = N.norm(names.get(p, ''))
                    s_ = (r_ or {}).get(k) or espn.get(p)
                    if s_:
                        st[k] = s_
            m.inj[g['id']] = st
        m.feats(g)
        if d in slate:
            players = []
            for pid, t, pr, mS, fx in game_rows(m, R, g):
                if mS < 4 and pr < 0.5:
                    continue
                c, p_ = seas[S].get(pid), seas[S - 1].get(pid)
                add_savg(fx, c, p_)
                mu, sd = project(F, fx)
                if mu['min'] < 6:
                    continue
                k = N.norm(names.get(pid, ''))
                row = {'id': pid, 'n': names.get(pid, ''), 't': t, 'pos': pos.get(pid), 'st': st.get(k),
                       'pr': round(pr, 2), 'min': round(mu['min'], 1),
                       **{s: round(mu[s], 1) for s in PSTATS + ('pra',)},
                       'sd': {s: round(v, 2) for s, v in sd.items()},
                       'gp': c[0] if c else 0, 'avg': None if not c else {s: round(c[i] / c[0], 1) for i, s in ((2, 'pts'), (3, 'reb'), (4, 'ast'))}}
                # DraftKings' line where ESPN lists one (scripts/props_snap.py): our chance of the over
                lines = {}
                for s in PSTATS + ('pra',):
                    pp = props.get((g['id'], pid, s))
                    if pp and mu[s] > 0:
                        po = nb_over(mu[s], sd[s] ** 2, pp['L'])
                        lines[s] = {'L': pp['L'], 'oO': pp['oO'], 'oU': pp['oU'], 'pO': round(po, 3),
                                    'mkt': None if no_vig(pp['oO'], pp['oU']) is None else round(no_vig(pp['oO'], pp['oU']), 3)}
                if lines:
                    row['dk'] = lines
                players.append(row)
            players.sort(key=lambda r: -r['pra'])
            tip = N.tipdt(g).astimezone(B.ET)
            out.append({'id': g['id'], 'tip': g['tip'], 'day': tip.date().isoformat(), 'time': tip.strftime('%-I:%M %p'),
                        'h': g['h'], 'a': g['a'], 'T': g.get('T'), 'L': g.get('L'), 'players': players})
        m.update(g)
    res = {'season': S, 'asof': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'report': rep_at, 'games': out,
           'n': sum(len(g['players']) for g in out),
           'test': {s: F['stats'][s]['acc'] for s in ('min',) + PSTATS + ('pra',)},
           'calib': {s: {k: F['calib'][s][k] for k in ('brier', 'brier50', 'bins')} for s in F['calib']},
           'feats': {s: F['stats'][s]['feats'] for s in ('min',) + PSTATS}}
    with open(OUT, 'w') as f:
        json.dump(res, f, separators=(',', ':'))
    print('nba players:', len(out), 'games,', res['n'], 'players')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--pull':
        pull(int(a[1]), int(a[2]))
    elif a and a[0] == '--fit':
        fit()
    else:
        build()
