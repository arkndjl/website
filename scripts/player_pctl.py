#!/usr/bin/env python3
"""20th / 50th / 80th percentile projections for the NFL, NBA and NHL ARKBOARDs: each player's value (NFL WAR, NBA VORX,
NHL WAR) and box-score stats, rest of season and full season (to date + rest of season).

    python3 scripts/player_pctl.py --frames nhl     # backtest frames from game logs (NHL stats API), scripts/.cache/pctl
    python3 scripts/player_pctl.py --fit nba        # fit, then the leave-one-season-out calibration test
                                                    #   -> data/pctl_fit_<sport>.json, scripts/data/pctl_hist_<sport>.json.gz
    python3 scripts/player_pctl.py nba              # this season's projections -> static/data/pctl-<sport>.json (stdlib)

Model, the same for every sport and stat. Rest of season = rate x exposure (NBA minutes, NHL ice time, NFL games):
  exposure  expected = team games left x games share x exposure a game, each to date blended with last season (A, B
            games of it); its error is drawn from what happened to players in the same spot in the other seasons (u =
            actual / expected), by how much of the season is left, games just missed in a row, and role
  rate      prior = his last three seasons (Marcel 1 / .7 / .5) shrunk toward his group's rate with K exposure, K fit;
            spread of true rates around the prior and noise per unit of exposure fit on season-level errors
            (e^2 = a m^2 + b + phi m / e for counting stats, tau^2 + sigma^2 / e for value), then updated with the season
            to date (normal-normal); NBA VORX uses XPM (proj)'s prior and fit (scripts/nba_proj.py) on .030 (XPM + 1.4) MP / 48
  outcome   counting stats: gamma with variance phi x mean around rate x exposure; value: normal, sigma^2 x exposure
2,000 draws a player give the 20th, 50th and 80th percentiles. The test: every season held out in turn, are 20% / 50% /
80% of held-out outcomes below p20 / p50 / p80, overall and by how much of the season was left. Only what passes is
published. NBA and NHL value have no history to date inside a season (season-level sources), so their test runs from
the prior with the in-season exposure; the to-date update is the same conjugate step whose spread the season-level fit
already tests across minutes.
"""
import gzip
import json
import math
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'pctl')
FIT = os.path.join(ROOT, 'data', 'pctl_fit_{}.json')
HIST = os.path.join(HERE, 'data', 'pctl_hist_{}.json.gz')
OUT = os.path.join(ROOT, 'static', 'data', 'pctl-{}.json')
QS = (0.2, 0.5, 0.8)
NDRAW = 2000
MARCEL = (1.0, 0.7, 0.5)

# targets: key, label, kind, groups (None: all), decimals shown
SPEC = {
    'nba': {'unit': 'min', 'cps': (5, 10, 20, 35, 50, 65), 'A': 10.0, 'B': 5.0, 'gs_new': 0.7,
            'role': {'G': 20, 'F': 20, 'C': 20},
            'targets': [('vorx', 'VORX', 'xpm', None, 1), ('pts', 'PTS', 'count', None, 0), ('reb', 'REB', 'count', None, 0),
                        ('ast', 'AST', 'count', None, 0), ('fg3', '3PM', 'count', None, 0), ('stl', 'STL', 'count', None, 0),
                        ('blk', 'BLK', 'count', None, 0)]},
    'nhl': {'unit': 'toi', 'cps': (5, 10, 20, 35, 50, 65), 'A': 10.0, 'B': 5.0, 'gs_new': 0.7,
            'role': {'F': 14, 'D': 18, 'G': 50},
            'targets': [('war', 'WAR', 'value', None, 1), ('g', 'G', 'count', {'F', 'D'}, 0), ('a', 'A', 'count', {'F', 'D'}, 0),
                        ('pts', 'PTS', 'count', {'F', 'D'}, 0), ('sog', 'SOG', 'count', {'F', 'D'}, 0)]},
    'nfl': {'unit': 'sn', 'cps': (3, 5, 7, 9, 11, 13, 15), 'A': 4.0, 'B': 3.0, 'gs_new': 0.7,
            'role': None,
            'targets': [('war', 'WAR', 'value', None, 1), ('pass', 'pass yds', 'count', {'QB'}, 0),
                        ('ptd', 'pass TD', 'count', {'QB'}, 0), ('pint', 'INT', 'count', {'QB'}, 0),
                        ('rush', 'rush yds', 'count', {'RB'}, 0), ('rtd', 'rush TD', 'count', {'RB'}, 0),
                        ('recs', 'rec', 'count', {'RB', 'WR', 'TE'}, 0), ('rec', 'rec yds', 'count', {'RB', 'WR', 'TE'}, 0),
                        ('retd', 'rec TD', 'count', {'WR', 'TE'}, 0), ('ppr', 'PPR', 'count', {'QB', 'RB', 'WR', 'TE'}, 0),
                        ('sack', 'sacks', 'count', {'DL', 'LB'}, 1),
                        ('tkl', 'tackles', 'count', {'DL', 'LB', 'DB'}, 0), ('int', 'INT', 'count', {'DB'}, 0)]},
}
STEP = {('nfl', 'sack'): 0.5}                          # stats counted in halves
SKIP = {'nba': {2020}, 'nhl': {2020}, 'nfl': set()}     # seasons cut short without warning: never scored


# ---------------------------------------------------------------- frames
def _snap(cur, tg, last, tm_of, S):
    out = {}
    for pid, c in cur.items():
        tm = tm_of[pid]
        out[pid] = {'tm': tm, 'grp': c['grp'], 'n': c['n'], 'tg': tg[tm], 'g': c['g'], 'e': round(c['e'], 2),
                    'miss': tg[tm] - last[pid], 'x': {k: v for k, v in c['x'].items()}}
    return out


def _walk(games, lines_of, nteams_half, cps):
    """games in order; lines_of(game) -> [(pid, team, name, grp, e, {stat: n})]. Snapshots after cp x nteams/2 games."""
    tg, last, tm_of = defaultdict(int), {}, {}
    cur = {}
    snaps, marks = {}, {int(round(c * nteams_half)): c for c in cps}
    for i, g in enumerate(games):
        teams = set()
        for pid, t, name, grp, e, x in lines_of(g):
            teams.add(t)
            c = cur.setdefault(pid, {'g': 0, 'e': 0.0, 'x': defaultdict(float), 'n': name, 'grp': grp})
            c['g'] += 1; c['e'] += e
            for k, v in x.items():
                c['x'][k] += v
            tm_of[pid] = t
            last[pid] = tg[t] + 1
        for t in g['teams']:
            tg[t] += 1
        if i + 1 in marks:
            snaps[str(marks[i + 1])] = _snap(cur, tg, last, tm_of, None)
    return snaps, _snap(cur, tg, last, tm_of, None), dict(tg)


def frames_nba():
    import nba_games as N
    import nba_players as P
    games, _ = N.load_hist()
    with gzip.open(P.PHIST, 'rt') as f:
        box = json.load(f)
    out = {}
    for S in sorted({g['S'] for g in games if g['S'] >= 2019}):
        gs = [dict(g, teams=(g['h'], g['a'])) for g in games if g['S'] == S and g.get('t') == 2 and g['id'] in box]
        def lines(g):
            for t, rows in box[g['id']].items():
                for r in rows:
                    if r[4] <= 0: continue
                    yield (r[0], t, r[1], P.POS.get(r[2], 'F'), r[4],
                           {'pts': r[5], 'reb': r[6], 'ast': r[7], 'fg3': r[8], 'stl': r[9], 'blk': r[10]})
        cp, end, tl = _walk(gs, lines, 15.0, SPEC['nba']['cps'])
        out[S] = {'cp': cp, 'end': end, 'tlen': tl}
        print('nba', S, len(gs), len(end), flush=True)
    return out


def frames_nhl():
    import nhl_data as D
    out = {}
    for S in range(2011, D.current_season()):
        gm = [g for g in D.games(S) if g['type'] == 2 and g.get('final')]
        sk, gk = defaultdict(list), defaultdict(list)
        for r in D._logs('skater', S, 2, False):
            sk[r[0]].append(r)
        for r in D._logs('goalie', S, 2, False):
            gk[r[0]].append(r)
        gs = [dict(g, teams=(g['h'], g['a'])) for g in gm if g['id'] in sk]
        def lines(g):
            for r in sk[g['id']]:
                toi = (r[5] or 0) / 60
                if toi <= 0: continue
                yield (str(r[1]), D.team(r[3]), r[2], 'D' if r[4] == 'D' else 'F', toi,
                       {'g': r[6], 'a': r[7], 'pts': r[6] + r[7], 'sog': r[8]})
            for r in gk[g['id']]:
                toi = (r[5] or 0) / 60
                if toi <= 0: continue
                yield (str(r[1]), D.team(r[3]), r[2], 'G', toi, {})
        nt = len({t for g in gs for t in g['teams']})
        cp, end, tl = _walk(gs, lines, nt / 2, SPEC['nhl']['cps'])
        out[S] = {'cp': cp, 'end': end, 'tlen': tl}
        print('nhl', S, len(gs), len(end), flush=True)
    return out


NFL_KEEP = ('pass', 'ptd', 'pint', 'rush', 'rtd', 'recs', 'rec', 'retd', 'sack', 'tkl', 'int')
# PPR: 1 per 25 passing yards, 4 a passing TD, -2 an INT or fumble lost, 1 per 10 rushing or receiving yards, 6 a TD,
# 2 a two-point conversion, 1 a catch (scripts/nfl_fantasy.py SCORING)
PPR = {'pass': .04, 'ptd': 4, 'pint': -2, 'rush': .1, 'rtd': 6, 'recs': 1, 'rec': .1, 'retd': 6, 'fl': -2, 'tp': 2, 'sttd': 6}


def ppr(st):
    return round(max(0.0, sum(w * st.get(k, 0) for k, w in PPR.items())), 2)



def nfl_board(y, thru=None):
    import nfl_war as W
    out, _, _ = W.board(y, thru=thru)
    return {p['id']: {'n': p['n'], 'tm': p['t'], 'grp': p['_g'], 'g': p['g'], 'sn': p['sn'], 'war': p['war'],
                      'x': dict({k: p['_st'].get(k, 0) for k in NFL_KEEP}, ppr=ppr(p['_st']))} for p in out}


def nfl_team_games(y, thru=None):
    import nfl_war as W
    tg = defaultdict(int)
    for g in W.rows(W.get('games.csv', W.GAMES)):
        if g['season'] == str(y) and g['game_type'] == 'REG' and (int(g['week']) < thru if thru else g['home_score'] not in ('', 'NA')):
            tg[g['home_team']] += 1; tg[g['away_team']] += 1
    return dict(tg)


NFL_CP0 = 2016                     # first season with in-season checkpoints (the earlier ones are prior history only)


def frames_nfl(years=range(2013, 2026)):
    out = {}
    for y in years:
        fn = os.path.join(CACHE, f'nfl_{y}.json')
        if os.path.exists(fn):
            raw = json.load(open(fn))
        else:
            raw = {'end': nfl_board(y)}
            for w in SPEC['nfl']['cps'] if y >= NFL_CP0 else ():
                raw[str(w)] = nfl_board(y, w)
            os.makedirs(CACHE, exist_ok=True)
            json.dump(raw, open(fn, 'w'))
        tl = nfl_team_games(y)
        conv = lambda d, tg, prev: {pid: {'tm': p['tm'], 'grp': p['grp'], 'n': p['n'], 'tg': tg.get(p['tm'], 0), 'g': p['g'],
                                          'e': p['sn'], 'sn': p['sn'],
                                          'miss': max(0, (tg.get(p['tm'], 0) - prev[1].get(p['tm'], 0)) - (p['g'] - prev[0].get(pid, {}).get('g', 0))),
                                          'x': dict(p['x'], war=p['war'])} for pid, p in d.items()}
        cp, prev = {}, ({}, {})
        for w in SPEC['nfl']['cps']:
            if str(w) not in raw or y < NFL_CP0: continue       # prior-only seasons keep the season total
            tg = nfl_team_games(y, w)
            d = _nfl_raw(raw[str(w)])
            cp[str(w)] = conv(d, tg, prev)
            prev = (d, tg)
        out[y] = {'cp': cp, 'end': conv(_nfl_raw(raw['end']), tl, ({}, {})), 'tlen': tl}
        print('nfl', y, len(out[y]['end']), flush=True)
    return out


def _nfl_raw(d):
    """the cache's rows (lists, from the first pull) or dicts"""
    out = {}
    for pid, p in d.items():
        if isinstance(p, list):
            n, t, pos, g_, gp, sn, war, st = p
            p = {'n': n, 'tm': t, 'grp': g_, 'g': gp, 'sn': sn, 'war': war, 'x': st}
        out[pid] = p
    return out


def frames(sport):
    fn = os.path.join(CACHE, f'frames_{sport}.json.gz')
    if os.path.exists(fn) and '--refresh' not in sys.argv:
        with gzip.open(fn, 'rt') as f:
            return {int(k): v for k, v in json.load(f).items()}
    out = {'nba': frames_nba, 'nhl': frames_nhl, 'nfl': frames_nfl}[sport]()
    os.makedirs(CACHE, exist_ok=True)
    with gzip.open(fn, 'wt') as f:
        json.dump(out, f, separators=(',', ':'))
    return out


def season_values(sport, S):
    """{pid: (value, exposure, grp)} from the boards' season files (NBA: by ESPN id via the name matcher; NHL: NHL id)"""
    if sport == 'nhl':
        fn = os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{S}.json')
        if not os.path.exists(fn): return {}
        return {p['id']: (p['war'], p['toi'], p['grp']) for p in json.load(open(fn))['players'] if p.get('war') is not None}
    return {}


# ---------------------------------------------------------------- the model
class Rate:
    """prior rate (Marcel + shrink K toward the group's rate) and its spread, one target"""
    def __init__(self, kind, K=None, mu=None, var=None):
        self.kind, self.K, self.mu, self.var = kind, K, mu or {}, var or {}

    def prior(self, hist, grp):
        """hist: [(x, e)] newest first (None for a season without him). -> (m0, vet)"""
        num = den = 0.0
        for w, h in zip(MARCEL, hist):
            if h and h[1] > 0:
                num += w * h[0]; den += w * h[1]
        mu = self.mu.get(grp + ':v', 0.0)
        if den <= 0:
            return self.mu.get(grp + ':n', mu), False
        return (num + self.K * mu) / (den + self.K), True

    def v0(self, m0, grp, vet):
        p = self.var.get(f"{grp}:{'v' if vet else 'n'}") or self.var.get('all:' + ('v' if vet else 'n'))
        if self.kind == 'count':
            return max(p[0] * m0 * m0 + p[1], 1e-12), p[2]
        return max(p[0], 1e-12), p[1]

    def post(self, m0, grp, vet, x_td, e_td):
        V0, phi = self.v0(m0, grp, vet)
        if e_td <= 0:
            return m0, V0, phi
        if self.kind == 'count':
            Vd = phi * max(m0, 0.2 * self.mu.get(grp + ':v', m0) or 1e-6) / e_td
        else:
            Vd = phi / e_td
        r = x_td / e_td
        return (m0 * Vd + r * V0) / (V0 + Vd), V0 * Vd / (V0 + Vd), phi


def lsq(X, y):
    import numpy as np
    X, y = np.asarray(X, float), np.asarray(y, float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    return [max(0.0, float(v)) for v in b]


def fit_rate(kind, rows, Ks):
    """rows: (grp, hist, x, e) one per player-season with e > 0. Choose K (exposure-weighted squared error of the
    season's rate against the prior), then the spread by group and veteran / newcomer."""
    import numpy as np
    mu = {}
    by = defaultdict(lambda: [0.0, 0.0])
    for grp, hist, x, e in rows:
        vet = any(h and h[1] > 0 for h in hist)
        a = by[grp + (':v' if vet else ':n')]; a[0] += x; a[1] += e
    for k, (x, e) in by.items():
        mu[k] = x / e if e else 0.0
    best = None
    for K in Ks:
        R = Rate(kind, K, mu)
        err = wt = 0.0
        for grp, hist, x, e in rows:
            m0, vet = R.prior(hist, grp)
            if vet:
                err += e * (x / e - m0) ** 2; wt += e
        if best is None or err / wt < best[0]:
            best = (err / wt, K)
    R = Rate(kind, best[1], mu)
    groups = defaultdict(list)
    for grp, hist, x, e in rows:
        m0, vet = R.prior(hist, grp)
        tag = 'v' if vet else 'n'
        groups[f'{grp}:{tag}'].append((m0, x / e, e))
        groups[f'all:{tag}'].append((m0, x / e, e))
    var = {}
    for k, rs in groups.items():
        if len(rs) < 40: continue
        if kind == 'count':
            X = [(m * m, 1.0, max(m, 1e-6) / e) for m, r, e in rs]
            p = lsq(X, [(r - m) ** 2 for m, r, e in rs])
        else:
            p = lsq([(1.0, 1 / e) for m, r, e in rs], [(r - m) ** 2 for m, r, e in rs])
        var[k] = [round(v, 8) for v in p]
    R.var = var
    return R


def exposure(spec, tg, g, e, rem, hist_g, hist_tl, hist_e):
    """expected exposure the rest of the season, and the games share and exposure a game behind it"""
    A, B = spec['A'], spec['B']
    gs0 = min(1.0, hist_g / hist_tl) if hist_tl else spec['gs_new']
    gs = (g + A * gs0) / (tg + A) if tg + A > 0 else gs0
    if spec['unit'] == 'g':
        epg = 1.0
    else:
        epg0 = hist_e / hist_g if hist_g else (e / g if g else 0.0)
        epg = (e + B * epg0) / (g + B) if g + B > 0 else epg0
    return rem * gs * epg, gs, epg


def ubin(spec, frac, miss, grp, epg, sn=None):
    f = 0 if frac < 0.4 else 1 if frac < 0.75 else 2
    m = 0 if miss == 0 else 1 if miss <= 2 else 2
    if spec['role'] is None:
        r = 1 if (sn or 0) >= 30 else 0
    else:
        r = 1 if epg >= spec['role'].get(grp, 15) else 0
    return f'{f}{m}{r}'


def pool_of(pools, b):
    """u values for a bin, merged with neighbours when thin"""
    if len(pools.get(b, ())) >= 60:
        return pools[b]
    alt = [v for k, vs in pools.items() if k[0] == b[0] and k[2] == b[2] for v in vs]
    if len(alt) >= 60:
        return sorted(alt)
    return sorted(v for k, vs in pools.items() if k[0] == b[0] for v in vs)


def draws_u(pool, n, rng):
    """n stratified draws from a sorted pool"""
    m = len(pool)
    out = [pool[min(m - 1, int((i + rng.random()) / n * m))] for i in range(n)]
    rng.shuffle(out)
    return out


def gamma(rng, mean, var):
    if mean <= 0:
        return 0.0
    if var <= 1e-12:
        return mean
    k = mean * mean / var
    return rng.gammavariate(k, var / mean)


def simulate(kind, m1, V1, phi, Ehat, us, rng, x_td=0.0, e_td=0.0, season=False):
    """draws of the rest of season (or, season=True, of the whole season from the prior: e_td added to exposure)"""
    out = []
    for u in us:
        E = Ehat * u + (e_td if season else 0.0)
        if kind == 'xpm':
            if E <= 0:
                out.append(0.0); continue
            xpm = rng.gauss(m1, math.sqrt(V1 + phi / E))
            out.append(0.030 * (xpm + 1.4) * E / 48)
        elif kind == 'value':
            r = rng.gauss(m1, math.sqrt(V1))
            out.append(r * E + rng.gauss(0, math.sqrt(phi * max(E, 0.0))))
        else:
            r = gamma(rng, m1, V1)
            out.append(gamma(rng, r * E, phi * r * E))
    return out


def quant(xs, qs=QS):
    s = sorted(xs)
    n = len(s)
    return [s[min(n - 1, max(0, int(q * n)))] for q in qs]


def rnd(v, d, step=None):
    if step:
        return round(round(v / step) * step, 2) + 0.0
    return round(v, d) + 0.0 if d else round(v)


# ---------------------------------------------------------------- history and rows
def hist_tables(sport, F):
    """{S: {pid: {'g', 'e', 'tl', 'x': {...}, 'grp'}}} season totals (stats from frames, value from season files)"""
    H = {}
    for S, fr in F.items():
        H[S] = {}
        for pid, p in fr['end'].items():
            H[S][pid] = {'g': p['g'], 'e': p['e'], 'tl': fr['tlen'].get(p['tm'], 0), 'x': dict(p['x']), 'grp': p['grp']}
    if sport == 'nhl':
        for S in range(2009, max(F) + 2):
            for pid, (v, toi, grp) in season_values('nhl', S).items():
                H.setdefault(S, {}).setdefault(pid, {'g': 0, 'e': 0, 'tl': 0, 'x': {}, 'grp': grp})['x']['war'] = v
                H[S][pid]['xe_war'] = toi
    return H


def hist_of(H, S, pid, k, unit_key='e'):
    """[(x, e)] for seasons S-1, S-2, S-3 (newest first)"""
    out = []
    for s in (S - 1, S - 2, S - 3):
        h = H.get(s, {}).get(pid)
        if not h or k not in h['x']:
            out.append(None); continue
        e = h.get('xe_' + k, h['e'])
        out.append((h['x'][k], e) if e and e > 0 else None)
    return out


def last_season(H, S, pid):
    h = H.get(S - 1, {}).get(pid)
    if not h or not h['g']:
        return 0, 0, 0.0
    return h['g'], h['tl'], h['e']


# ---------------------------------------------------------------- fit + test
def fit(sport, only=None):
    """only: refit these targets and keep the rest of data/pctl_fit_<sport>.json"""
    import numpy as np
    spec = SPEC[sport]
    F = frames(sport)
    H = hist_tables(sport, F)
    seasons = sorted(s for s in F if s - 1 in F and s not in SKIP[sport])
    if sport == 'nba':
        X = _nba_xpm_tables(F)
    rep = {'sport': sport, 'seasons': [seasons[0], seasons[-1]], 'targets': {}}
    rng = random.Random(7)
    # exposure rows: every checkpoint, every player who has played
    ex = []
    for S in seasons:
        fr = F[S]
        for c, snap in fr['cp'].items():
            for pid, p in snap.items():
                tl = fr['tlen'].get(p['tm'], 0)
                rem = tl - p['tg']
                if rem <= 0 or p['g'] <= 0: continue
                end = fr['end'].get(pid)
                hg, htl, he = last_season(H, S, pid)
                Eh, gs, epg = exposure(spec, p['tg'], p['g'], p['e'], rem, hg, htl, he)
                if Eh <= 0: continue
                e_ros = (end['e'] - p['e']) if end else 0.0
                ex.append({'S': S, 'c': c, 'pid': pid, 'p': p, 'end': end, 'rem': rem, 'tl': tl, 'Eh': Eh, 'u': e_ros / Eh,
                           'b': ubin(spec, rem / tl, p['miss'], p['grp'], epg, p.get('sn', 0) / max(1, p['g']) if sport == 'nfl' else None)})
    print(sport, len(ex), 'exposure rows', flush=True)
    pools_by = {}
    for S in seasons:
        pools = defaultdict(list)
        for r in ex:
            if r['S'] != S:
                pools[r['b']].append(r['u'])
        pools_by[S] = {k: sorted(v) for k, v in pools.items()}
    allpools = defaultdict(list)
    for r in ex:
        allpools[r['b']].append(r['u'])
    us = np.array([r['u'] for r in ex])
    rep['exposure'] = {'rows': len(ex), 'uMedian': round(float(np.median(us)), 3), 'uMean': round(float(us.mean()), 3),
                       'bins': {k: len(v) for k, v in sorted(allpools.items())}}
    final = {'sport': sport, 'pools': {k: [round(x, 3) for x in _thin(sorted(v), 400)] for k, v in allpools.items()},
             'rates': {}, 'lam': {}, 'ship': {}}
    if only:
        old = json.load(open(FIT.format(sport)))
        final.update({a: old[a] for a in ('rates', 'lam', 'ship')})
        rep['targets'] = old['report']['targets']
    for k, label, kind, grps, dec in spec['targets']:
        if only and k not in only: continue
        res = _fit_target(sport, spec, F, H, seasons, ex, pools_by, k, kind, grps, dec, rng, X if sport == 'nba' else None)
        if res is None: continue
        rep['targets'][k] = res['report']
        final['rates'][k] = res['rate']
        final['lam'][k] = res['lam']
        final['ship'][k] = res['report']['pass']
        print(k, json.dumps({a: b for a, b in res['report'].items() if a not in ('bySeason',)}), flush=True)
    if sport == 'nfl' and final['ship'].get('ppr') and (not only or 'ppr' in only):
        rep['targets']['pprg'], final['lam']['pprg'] = _test_pprg(spec, H, seasons, ex, pools_by, rng)
        final['ship']['pprg'] = rep['targets']['pprg']['pass']
        print('pprg', json.dumps(rep['targets']['pprg']), flush=True)
    final['report'] = rep
    with open(FIT.format(sport), 'w') as f:
        json.dump(final, f, indent=1)
    _write_hist(sport, H, max(F))


def _test_pprg(spec, H, seasons, ex, pools_by, rng):
    """PPR a game from the PPR draws (games move with snaps): its own location and width per share of the season left,
    each season's chosen on the other seasons; the share of held-out outcomes below p20 / p50 / p80, full season and
    rest of season (a game or more played). -> (report, cal)"""
    import numpy as np
    grps = {'QB', 'RB', 'WR', 'TE'}
    rows_all = _rate_rows('nfl', H, seasons, 'ppr', grps, 'count')
    recs = []
    for S in seasons:
        R = fit_rate('count', [(g, h, x, e) for s, g, h, x, e in rows_all if s != S], KS_NFL)
        for r in ex:
            p, end = r['p'], r['end']
            if r['S'] != S or p['grp'] not in grps or not end or 'ppr' not in p['x']: continue
            hg, htl, he = last_season(H, S, r['pid'])
            _, gs, _ = exposure(spec, p['tg'], p['g'], p['e'], r['rem'], hg, htl, he)
            m0, vet = R.prior(hist_of(H, S, r['pid'], 'ppr'), p['grp'])
            m1, V1, phi = R.post(m0, p['grp'], vet, p['x']['ppr'], p['e'])
            u = np.array(draws_u(pool_of(pools_by[S], r['b']), ND, rng))
            gr = end['g'] - p['g']
            recs.append((S, r['rem'] / r['tl'], m1, V1, phi, r['Eh'] * u, r['rem'] * gs * u, p['x']['ppr'], p['g'],
                         end['x']['ppr'] / end['g'], (end['x']['ppr'] - p['x']['ppr']) / gr if gr >= 1 else np.nan))
    S_ = np.array([r[0] for r in recs]); fb = np.digitize([r[1] for r in recs], FBINS)
    E = np.vstack([r[5] for r in recs]); N = np.vstack([r[6] for r in recs])
    td, g = (np.array([r[i] for r in recs], float)[:, None] for i in (7, 8))
    ys, yr = (np.round(np.array([r[i] for r in recs], float), 1) for i in (9, 10))
    gen = _np_draws('count', [r[2] for r in recs], [r[3] for r in recs], [r[4] for r in recs], [1.0] * len(recs), E,
                    np.random.default_rng(13))
    locs, us = LOC['count'], sorted(set(S_.tolist()))
    tab = {}                                        # (loc, lam) -> season x bin x span x [3 hits, n]
    for li, loc in enumerate(locs):
        x = gen(loc)
        ss = (td + x) / (g + N)
        rs = np.where(N >= 1, x / np.maximum(N, 1), np.nan)
        for span, (sims, y) in enumerate(((ss, ys), (rs, yr))):
            qv = np.nanquantile(sims, QS, axis=1)
            md, ok = qv[1], ~np.isnan(y)
            for lj, lam in enumerate(LAMS):
                pit = np.stack([(y < md + lam * (v - md)) * 1.0 for v in qv])
                t = tab.setdefault((li, lj), np.zeros((len(us), 3, 2, 4)))
                for si, S in enumerate(us):
                    for b in range(3):
                        m = (S_ == S) & (fb == b) & ok
                        t[si, b, span, :3] = pit[:, m].sum(1); t[si, b, span, 3] = m.sum()
    def err(t, i):
        return float((t[..., i].sum() / max(1, t[..., 3].sum()) - QS[i]) ** 2)
    def choose(sub):
        """sub(t) -> the rows scored; the low and high widths are free of each other (a ratio's tails differ)"""
        best = None
        for li in range(len(locs)):
            lo = min(range(len(LAMS)), key=lambda lj: err(sub(tab[(li, lj)]), 0))
            hi = min(range(len(LAMS)), key=lambda lj: err(sub(tab[(li, lj)]), 2))
            v = err(sub(tab[(li, lo)]), 0) + err(sub(tab[(li, 0)]), 1) + err(sub(tab[(li, hi)]), 2)
            if best is None or v < best[0]:
                best = (v, li, lo, hi)
        return best[1:]
    def pick(li, lo, hi, a):
        out = tab[(li, 0)][a].copy()
        out[..., 0] = tab[(li, lo)][a][..., 0]; out[..., 2] = tab[(li, hi)][a][..., 2]
        return out
    held = np.zeros((len(us), 3, 2, 4))
    cal = []                                        # by share left: [season, rest of season] x [loc, low width, high width]
    for b in range(3):
        cal.append([])
        for sp in range(2):
            for si in range(len(us)):
                held[si, b, sp] = pick(*choose(lambda t: np.delete(t[:, b, sp], si, axis=0)), (si, b, sp))
            li, lo, hi = choose(lambda t: t[:, b, sp])
            cal[b].append([locs[li], LAMS[lo], LAMS[hi]])
    hit = lambda t: [round(float(v), 3) for v in t[..., :3].sum(axis=tuple(range(t.ndim - 1))) / max(1, t[..., 3].sum())]
    rep = {'hits': hit(held[:, :, 0]), 'n': int(held[:, :, 0, 3].sum()), 'ros': hit(held[:, :, 1]), 'nRos': int(held[:, :, 1, 3].sum()),
           'byFrac': {name: hit(held[:, b, 0]) + [int(held[:, b, 0, 3].sum())] for b, name in enumerate(('late', 'mid', 'early'))},
           'bySeason': {int(S): hit(held[si, :, 0]) for si, S in enumerate(us)}, 'cal': cal}
    rep['pass'] = all(abs(a - q) <= 0.03 for hs in (rep['hits'], rep['ros']) for a, q in zip(hs, QS)) and \
        all(abs(v[i] - QS[i]) <= 0.05 for v in rep['byFrac'].values() for i in range(3))
    return rep, cal


def _thin(xs, n):
    if len(xs) <= n: return xs
    return [xs[int((i + 0.5) * len(xs) / n)] for i in range(n)]


def _rate_rows(sport, H, seasons, k, grps, kind, X=None):
    """season-level rows for the rate fit: (S, grp, hist, x, e)"""
    out = []
    for S in seasons:
        for pid, h in H.get(S, {}).items():
            if grps and h['grp'] not in grps: continue
            if k not in h['x']: continue
            e = h.get('xe_' + k, h['e'])
            if not e or e < 50: continue
            out.append((S, h['grp'], hist_of(H, S, pid, k), h['x'][k], e))
    return out


KS = {'count': (25, 50, 100, 200, 400, 800, 1600, 3200), 'value': (25, 50, 100, 200, 400, 800, 1600, 3200)}
KS_NFL = (50, 100, 200, 400, 800, 1600, 3200)


LOC = {'count': (0.86, 0.88, 0.9, 0.92, 0.94, 0.96, 0.98, 1.0, 1.02, 1.04, 1.06, 1.08, 1.1, 1.12, 1.14, 1.16),
       'value': (-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4)}
LAMS = (0.7, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.4, 1.5, 1.65, 1.8, 2.0)
FBINS = (0.4, 0.75)                 # share of the season left: late < .4 <= mid < .75 <= early
ND = 200


def _np_draws(kind, m1, V1, phi, w, E, rng):
    """numpy draws for many rows at once (rows x ND): what simulate() draws, as arrays; for value kinds the location
    grid moves the prior, so it returns a function of the shift"""
    import numpy as np
    m1, V1, phi, w = (np.asarray(a, float)[:, None] for a in (m1, V1, phi, w))
    if kind == 'count':
        m = np.maximum(m1, 1e-9)
        r = rng.gamma(m * m / np.maximum(V1, 1e-12), np.maximum(V1, 1e-12) / m, size=E.shape)
        mu = r * E
        y = np.where(mu > 0, rng.gamma(np.maximum(mu, 1e-12) / np.maximum(phi, 1e-9), np.maximum(phi, 1e-9)), 0.0)
        return lambda loc: y * loc
    zr, zn = rng.standard_normal(E.shape), rng.standard_normal(E.shape)
    if kind == 'xpm':
        Es = np.maximum(E, 1e-9)
        return lambda loc: np.where(E > 0, 0.030 * (m1 + w * loc + zr * np.sqrt(V1 + phi / Es) + 1.4) * E / 48, 0.0)
    return lambda loc: (m1 + w * loc + zr * np.sqrt(V1)) * E + zn * np.sqrt(phi * np.maximum(E, 0))


def _pit_rows(sims, md, yr, half, lam):
    import numpy as np
    Fm = (sims < (md + (yr - half - md) / lam)[:, None]).mean(1)
    Fp = (sims < (md + (yr + half - md) / lam)[:, None]).mean(1)
    gap = np.maximum(Fp - Fm, 1e-12)
    return np.stack([np.where(Fp > Fm, np.clip((tq - Fm) / gap, 0, 1), (Fm < tq) * 1.0) for tq in QS])


def _fit_target(sport, spec, F, H, seasons, ex, pools_by, k, kind, grps, dec, rng, X):
    import numpy as np
    nrng = np.random.default_rng(11)
    rows_all = _rate_rows(sport, H, seasons, k, grps, kind) if kind != 'xpm' else None
    Ks = KS_NFL if sport == 'nfl' else KS[kind] if kind != 'xpm' else None
    value_prior_only = kind in ('xpm', 'value') and sport in ('nba', 'nhl')
    recs = []         # (S, frac, y, pace, m1, V1, phi, w, E draws)
    for S in seasons:
        if kind == 'xpm':
            R = _xpm_fit([s for s in X['seasons'] if s != S], X)
        else:
            R = fit_rate(kind, [(g, h, x, e) for s, g, h, x, e in rows_all if s != S], Ks)
        pools = pools_by[S]
        for r in ex:
            if r['S'] != S: continue
            p = r['p']
            if grps and p['grp'] not in grps: continue
            w = 1.0
            if kind == 'xpm':
                xv = X['val'].get(S, {}).get(r['pid'])
                m0, vet = X['prior'][S].get(r['pid'], (None, None))
                if xv is None or m0 is None: continue
                V1, phi = R['vet' if vet else 'new']
                y, m1 = xv[0], m0
            elif value_prior_only:
                hs = H.get(S, {}).get(r['pid'])
                if not hs or k not in hs['x']: continue
                y = hs['x'][k]
                m0, vet = R.prior(hist_of(H, S, r['pid'], k), p['grp'])
                m1, V1, phi = R.post(m0, p['grp'], vet, 0.0, 0.0)
            else:
                if not r['end'] or k not in p['x']: continue
                y = r['end']['x'].get(k, 0) - p['x'][k]
                m0, vet = R.prior(hist_of(H, S, r['pid'], k), p['grp'])
                m1, V1, phi = R.post(m0, p['grp'], vet, p['x'][k], p['e'])
                if kind == 'value':
                    V0 = R.v0(m0, p['grp'], vet)[0]
                    w = V1 / V0                     # the prior's weight in the posterior mean
            u = np.array(draws_u(pool_of(pools, r['b']), ND, rng))
            E = r['Eh'] * u + (p['e'] if value_prior_only else 0.0)
            pace = p['x'][k] / max(1, p['tg']) * r['rem'] if k in p['x'] and not value_prior_only else np.nan
            recs.append((S, r['rem'] / r['tl'], y, pace, m1, V1, phi, w, E, p['grp'], r['pid']))
    if not recs:
        return None
    S_ = np.array([r[0] for r in recs]); f_ = np.array([r[1] for r in recs]); y_ = np.array([r[2] for r in recs], float)
    pace_ = np.array([r[3] for r in recs], float)
    E = np.vstack([r[8] for r in recs])
    gen = _np_draws(kind, [r[4] for r in recs], [r[5] for r in recs], [r[6] for r in recs], [r[7] for r in recs], E, nrng)
    if kind == 'count':
        locs = LOC['count']
    elif kind == 'xpm':
        locs = (-0.2, 0.0, 0.2, 0.4, 0.6, 0.8)
    else:                                           # value: shifts of the prior in units of its spread
        s0 = float(np.median(np.sqrt([r[5] / max(r[7], 1e-9) for r in recs])))
        locs = tuple(round(m * s0, 8) for m in (-0.6, -0.45, -0.3, -0.15, 0.0, 0.15, 0.3, 0.45, 0.6))
    neutral = locs.index(1.0 if kind == 'count' else 0.0)
    fb = np.digitize(f_, FBINS)                     # 0 late, 1 mid, 2 early
    us = sorted(set(S_.tolist()))
    step = STEP.get((sport, k))
    def rd(a):
        return np.round(a / step) * step if step else np.round(a, dec)
    yr = rd(y_)
    # tab[(loc, lam)]: per (season, frac bin) sums of mid-PIT at p20 / p50 / p80, and n
    tab, meds = {}, {}
    half = step / 2 if step else 0.5 * 10 ** -dec
    def pit_of(sims, md, lam):
        # randomized PIT on the shown (rounded) scale: F below the outcome and at it, the outcome's mass split
        # uniformly; a hit at tau = the chance the PIT falls under tau (an indicator for continuous outcomes)
        Fm = (sims < (md + (yr - half - md) / lam)[:, None]).mean(1)
        Fp = (sims < (md + (yr + half - md) / lam)[:, None]).mean(1)
        gap = np.maximum(Fp - Fm, 1e-12)
        return np.stack([np.where(Fp > Fm, np.clip((tq - Fm) / gap, 0, 1), (Fm < tq) * 1.0) for tq in QS])
    for li, loc in enumerate(locs):
        sims = gen(loc)
        md = np.median(sims, axis=1)
        meds[li] = md
        for lj, lam in enumerate(LAMS):
            pit = pit_of(sims, md, lam)
            t = np.zeros((len(us), 3, 4))
            for si, S in enumerate(us):
                for b in range(3):
                    m = (S_ == S) & (fb == b)
                    t[si, b, :3] = pit[:, m].sum(1); t[si, b, 3] = m.sum()
            tab[(li, lj)] = t
    def loss(t):
        h = t[..., :3].sum(axis=tuple(range(t.ndim - 1))) / max(1, t[..., 3].sum())
        return float(((h - np.array(QS)) ** 2).sum())
    keys = list(tab)
    # loc and width chosen per frac bin; each season's from the other seasons
    held = np.zeros((len(us), 3, 4)); choice = {}
    for si, S in enumerate(us):
        for b in range(3):
            best = min(keys, key=lambda kk: loss(np.delete(tab[kk][:, b], si, axis=0)))
            choice[(int(S), b)] = (locs[best[0]], LAMS[best[1]])
            held[si, b] = tab[best][si, b]
    final = {}
    for b in range(3):
        best = min(keys, key=lambda kk: loss(tab[kk][:, b]))
        final[b] = best
    hit = lambda t: [round(float(v), 3) for v in t[..., :3].sum(axis=tuple(range(t.ndim - 1))) / max(1, t[..., 3].sum())]
    tot = hit(held)
    # by group (position), on the held-out choices: the gate holds inside each group too
    G_ = np.array([r[9] for r in recs])
    hp = np.zeros((3, len(recs)))
    for li in sorted({locs.index(v[0]) for v in choice.values()}):
        sims = gen(locs[li]); md = np.median(sims, axis=1)
        for (S, b), (lv, lam) in choice.items():
            if locs.index(lv) != li: continue
            m = (S_ == S) & (fb == b)
            if m.any():
                hp[:, m] = _pit_rows(sims[m], md[m], yr[m], half, lam)
    byg = {}
    for g in sorted(set(G_.tolist())):
        m = G_ == g
        if m.sum() >= 300:
            byg[g] = [round(float(v), 3) for v in hp[:, m].mean(1)] + [int(m.sum())]
    byf = {name: hit(held[:, b]) + [int(held[:, b, 3].sum())] for b, name in enumerate(('late', 'mid', 'early')) if held[:, b, 3].sum()}
    bys = {int(S): hit(held[si]) for si, S in enumerate(us)}
    # players (not rows: a player's checkpoints move together) behind each season, for its tolerance
    npl = {int(S): max(1, len({r[10] for r in recs if r[0] == S})) for S in us}
    raw = hit(tab[(neutral, LAMS.index(1.0))])
    med = np.choose(fb, [meds[final[b][0]] for b in range(3)])
    mae = float(np.mean(np.abs(med - y_)))
    ok_p = ~np.isnan(pace_)
    ok = all(abs(a - b) <= 0.03 for a, b in zip(tot, QS)) and \
        all(abs(v[i] - QS[i]) <= 0.05 for v in byf.values() for i in range(3)) and \
        all(abs(v[i] - QS[i]) <= max(0.08, 2.5 * math.sqrt(QS[i] * (1 - QS[i]) / npl[S])) for S, v in bys.items() for i in range(3)) and \
        all(abs(v[i] - QS[i]) <= 0.06 for v in byg.values() for i in range(3))
    cal = [[locs[final[b][0]], LAMS[final[b][1]]] for b in range(3)]
    report = {'n': len(recs), 'hits': tot, 'raw': raw, 'byFrac': byf, 'bySeason': bys, 'byGroup': byg, 'cal': cal,
              'medMae': round(mae, 3), 'paceMae': round(float(np.mean(np.abs(pace_[ok_p] - y_[ok_p]))), 3) if ok_p.any() else None,
              'medMaeSame': round(float(np.mean(np.abs(med[ok_p] - y_[ok_p]))), 3) if ok_p.any() else None,
              'priorOnly': value_prior_only, 'pass': bool(ok)}
    if kind == 'xpm':
        rate = _xpm_fit(X['seasons'], X)
    else:
        Rf = fit_rate(kind, [(g, h, x, e) for s, g, h, x, e in rows_all], Ks)
        rate = {'kind': kind, 'K': Rf.K, 'mu': {a: round(b, 6) for a, b in Rf.mu.items()}, 'var': Rf.var}
    return {'report': report, 'rate': rate, 'lam': cal}


# ---------------------------------------------------------------- NBA: XPM (proj) model on the season files
def _nba_xpm_tables(F):
    """season VORX / XPM / MP by ESPN id (matched by name and team from bbref ids), the prior, vet flags"""
    import nba_xpm as XM
    import nba_proj as NP
    import names as NM
    val, prior, rows = {}, {}, {}
    seasons = []
    for S in range(2012, max(F) + 1):
        d = NP.load(S)
        if not d: continue
        pr, old = XM.prior_xpm(S), NP.past_mp(S)
        seasons.append(S)
        rows[S] = [(p['mp'], p['xpm'] - pr(p['id'])[0], old.get(p['id'], 0) >= NP.VET_MP) for p in d['players']
                   if not p.get('pr') and p['mp'] >= 50 and p.get('xpm') is not None]
        if S not in F: continue
        cand = [{'name': p['n'], 'team': p['tm'], 'pid': pid} for pid, p in F[S]['end'].items()]
        M = NM.Matcher(cand, sport='basketball')
        val[S], prior[S] = {}, {}
        for p in d['players']:
            if p.get('pr') or p.get('xpm') is None: continue
            hit = M.find(p['n'], team=p['tm'])
            row = hit[0] if isinstance(hit, tuple) else hit
            if not row: continue
            val[S][row['pid']] = (p['vorx'], p['mp'], p['xpm'])
            prior[S][row['pid']] = (pr(p['id'])[0], old.get(p['id'], 0) >= NP.VET_MP)
    return {'val': val, 'prior': prior, 'rows': rows, 'seasons': seasons}


def _xpm_fit(seasons, X):
    import nba_proj as NP
    out = {}
    for tag, vet in (('vet', True), ('new', False)):
        rs = [(m, e) for s in seasons for m, e, v in X['rows'][s] if v == vet]
        t2, s2 = NP.lsq(rs)
        out[tag] = (t2, s2)
    return out


def _write_hist(sport, H, top):
    """the last three finished seasons' totals, for the build (players' priors and last season's games and exposure)"""
    keep = {str(S): H[S] for S in range(top - 2, top + 1) if S in H}
    os.makedirs(os.path.dirname(HIST.format(sport)), exist_ok=True)
    with gzip.open(HIST.format(sport), 'wt') as f:
        json.dump(keep, f, separators=(',', ':'))


# ---------------------------------------------------------------- this season (stdlib)
def _cal(fit, k, frac):
    b = sum(frac >= x for x in FBINS)
    return fit['lam'][k][b]


def _qs(draws, loc, lam, kind, dec, step=None):
    if kind == 'count':
        draws = [v * loc for v in draws]
    q = quant(draws)
    return [rnd(q[1] + lam * (q[0] - q[1]), dec, step), rnd(q[1], dec, step), rnd(q[1] + lam * (q[2] - q[1]), dec, step)]


def per_game(draws, cal, us, gl, td, g):
    """PPR a game from the same draws: rest of season (draws with a game or more left to play) and full season; the
    games behind each draw scale with its snaps (u). -> (ros quantiles, {'pprg': season quantiles})"""
    (ls, los, his), (lr, lor, hir) = cal
    ros, ssn = [], []
    for x, u in zip(draws, us):
        n = gl * u
        if n >= 1:
            ros.append(x * lr / n)
        ssn.append((td + x * ls) / (g + n))
    def q(xs, lo, hi):
        if not xs: return None
        a, m, b = quant(xs)
        return [round(max(0.0, v), 1) for v in (m + lo * (a - m), m, m + hi * (b - m))]
    return q(ros, lor, hir), {'pprg': q(ssn, los, his)}


def _load_hist(sport):
    with gzip.open(HIST.format(sport), 'rt') as f:
        return {int(k): v for k, v in json.load(f).items()}


def project(sport, S, cur, tlen, value_td, X=None):
    """cur: {pid: {'tm', 'grp', 'n', 'tg', 'g', 'e', 'miss', 'x', 'sn'?}} the season to date; value_td: {pid: (value to
    date, rate input)}; -> rows for the page"""
    spec, fit = SPEC[sport], json.load(open(FIT.format(sport)))
    H = _load_hist(sport)
    pools = {b: v for b, v in fit['pools'].items()}
    targets = [t for t in spec['targets'] if fit['ship'].get(t[0])]
    out = []
    for pid, p in cur.items():
        tl = tlen.get(p['tm'], 82 if sport != 'nfl' else 17)
        rem = max(0, tl - p['tg'])
        if p['g'] <= 0:
            continue
        hg, htl, he = last_season(H, S, pid)
        Eh, gs, epg = exposure(spec, p['tg'], p['g'], p['e'], rem, hg, htl, he)
        frac = rem / tl if tl else 0.0
        b = ubin(spec, frac, p['miss'], p['grp'], epg, p.get('sn', 0) / max(1, p['g']) if sport == 'nfl' else None)
        rng = random.Random(f'{sport}{S}{pid}')
        us = draws_u(pool_of(pools, b), NDRAW // 2, rng) if rem > 0 else [0.0] * (NDRAW // 2)
        row = {'id': pid, 'n': p['n'], 'tm': p['tm'], 'pos': p.get('pos', p['grp']), 'g': p['g'], 'td': {}, 'ros': {}}
        for k, label, kind, grps, dec in targets:
            if grps and p['grp'] not in grps:
                continue
            loc, lam = _cal(fit, k, frac)
            Rp = fit['rates'][k]
            if kind == 'xpm':
                if pid not in value_td or X is None or pid not in X:
                    continue
                td, xpm_td, mp_td = value_td[pid]
                m0, vet = X[pid]
                t2, s2 = Rp['vet' if vet else 'new']
                m0 += loc
                V1 = 1 / (1 / t2 + mp_td / s2) if mp_td > 0 else t2
                m1 = V1 * (m0 / t2 + (xpm_td * mp_td / s2 if mp_td > 0 else 0.0))
                draws = simulate('xpm', m1, V1, s2, Eh, us, rng)
                q = _qs(draws, 1.0, lam, 'value', dec)
            else:
                R = Rate(kind, Rp['K'], Rp['mu'], Rp['var'])
                m0, vet = R.prior(hist_of(H, S, pid, k), p['grp'])
                if kind == 'value':
                    if pid not in value_td:
                        continue
                    td, e_td = value_td[pid]
                    m0 += loc                       # the prior's shift (rate units), from the fit
                    m1, V1, phi = R.post(m0, p['grp'], vet, td, e_td)
                    draws = simulate('value', m1, V1, phi, Eh, us, rng)
                    q = _qs(draws, 1.0, lam, 'value', dec)
                else:
                    td = p['x'].get(k, 0)
                    m1, V1, phi = R.post(m0, p['grp'], vet, td, p['e'])
                    draws = simulate('count', m1, V1, phi, Eh, us, rng)
                    q = _qs(draws, loc, lam, 'count', dec, STEP.get((sport, k)))
                    q = [max(0, v) for v in q]
                    if k == 'ppr' and fit['ship'].get('pprg'):
                        row['ros']['pprg'], row['ssn'] = per_game(draws, _cal(fit, 'pprg', frac), us, rem * gs, td, p['g'])
            row['td'][k] = rnd(td, dec)
            row['ros'][k] = q
        if row['ros']:
            out.append(row)
    return out, targets


DEF = {
    'nba': 'Rest of season = rate x minutes. Rate: his last three seasons blended with this one (VORX on XPM (proj)); '
           'minutes: games left x share played x minutes a game, with the misses seen in past seasons.',
    'nhl': 'Rest of season = rate x ice time. Rate: his last three seasons blended with this one; ice time: games left x '
           'share played x minutes a game, with the misses seen in past seasons.',
    'nfl': 'Rest of season = rate x snaps. Rate: his last three seasons blended with this one; snaps: games left x '
           'share played x snaps a game, with the misses seen in past seasons.',
}


def write(sport, S, rows, targets, meta):
    lead = targets[0][0]
    rows.sort(key=lambda r: -(r['td'].get(lead, 0) + (r['ros'].get(lead) or [0, -99])[1]))
    fit = json.load(open(FIT.format(sport)))
    rep = fit['report']
    tg = [{'k': k, 'l': l, 'd': d, 'hits': rep['targets'][k]['hits']} for k, l, _, _, d in targets]
    if fit['ship'].get('pprg'):
        i = [t['k'] for t in tg].index('ppr')
        tg.insert(i + 1, {'k': 'pprg', 'l': 'PPR/G', 'd': 1, 'hits': rep['targets']['pprg']['hits'], 'g': 1})
    held = sorted(int(x) for x in rep['targets'][targets[0][0]]['bySeason'])
    body = {'season': S, 'targets': tg, 'test': f'{held[0]}-{held[-1]}', 'def': DEF[sport], **meta, 'players': rows}
    fn = OUT.format(sport)
    old = None
    try:
        old = json.load(open(fn))
    except (OSError, ValueError):
        pass
    if old and {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in body.items() if k != 'asof'}:
        return print(sport, 'pctl: no change')
    import datetime as dt
    body['asof'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    with open(fn, 'w') as f:
        json.dump(body, f, separators=(',', ':'))
    print(sport, 'pctl:', len(rows), 'players;', ', '.join(f"{r['n']} {r['td'][lead]} + {r['ros'][lead]}" for r in rows[:3] if lead in r['ros']))


def tag(r, age, rookie):
    """filters on the page: age, rookie (1)"""
    if age is not None:
        r['age'] = age
    if rookie:
        r['r'] = 1


def nba_seen(S):
    """bbref ids on any earlier XPM board (a rookie is on the board for the first time and, undrafted, 27 or under;
    scripts/rookies.py)"""
    d = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
    return {p['id'] for f in os.listdir(d) if f.endswith('.json') and int(f[:-5]) < S
            for p in json.load(open(os.path.join(d, f)))['players']}


def nhl_prior_gp(S):
    """{NHL id: [games each earlier season]} for the Calder rule (scripts/rookies.py)"""
    d, gp = os.path.join(ROOT, 'static', 'data', 'nhl-war'), defaultdict(list)
    for f in sorted(os.listdir(d)):
        if f.endswith('.json') and int(f[:-5]) < S:
            for p in json.load(open(os.path.join(d, f)))['players']:
                gp[p['id']].append(p['gp'])
    return gp


def build_nba():
    import nba_games as N
    import nba_players as P
    import nba_xpm as XM
    import nba_proj as NP
    S = XM.current_season()
    gs = [g for g in N.season_games(S, live=True) if g.get('fin') and g.get('t') == 2]
    gs.sort(key=lambda g: g['tip'])
    box = {}
    for g in gs:
        b = P.pbox(g['id'], final=True)
        if b:
            box[g['id']] = b
    gs = [dict(g, teams=(g['h'], g['a'])) for g in gs if g['id'] in box]
    if not gs:
        return print('nba pctl: no games yet')
    def lines(g):
        for t, rows in box[g['id']].items():
            for r in rows:
                if r[4] <= 0: continue
                yield (r[0], t, r[1], P.POS.get(r[2], 'F'), r[4],
                       {'pts': r[5], 'reb': r[6], 'ast': r[7], 'fg3': r[8], 'stl': r[9], 'blk': r[10]})
    _, cur, tg = _walk(gs, lines, 15.0, ())
    site = NP.load(S) or {'players': []}
    prior, old = XM.prior_xpm(S), NP.past_mp(S)
    val, X = {}, {}
    for p in site['players']:
        if p.get('ph') and p.get('xpm') is not None and p['ph'] in cur:
            val[p['ph']] = (p['vorx'], p['xpm'], p['mp'])
            X[p['ph']] = (prior(p['id'])[0], old.get(p['id'], 0) >= NP.VET_MP)
            cur[p['ph']]['ph'] = p['ph']
            cur[p['ph']]['ref'] = (p['id'], p.get('age'))
    rows, targets = project('nba', S, cur, {t: 82 for t in tg}, val, X)
    seen = nba_seen(S)
    drafted = {bid for lst in json.load(open(os.path.join(HERE, 'nba_draft.json'))).values() for _, bid, _, _ in lst}
    for r in rows:
        r['ph'] = r['id']
        bid, age = cur[r['id']].get('ref', (None, None))
        tag(r, age, bid is not None and bid not in seen and (bid in drafted or (age or 0) <= 27))
    write('nba', S, rows, targets, {'games': max(tg.values())})


def build_nhl():
    import nhl_data as D
    S = D.current_season()
    gm = [g for g in D.games(S, fresh=True) if g['type'] == 2 and g.get('final')]
    sk, gk = defaultdict(list), defaultdict(list)
    sk_all = D._logs('skater', S, 2, True)
    for r in sk_all:
        sk[r[0]].append(r)
    for r in D._logs('goalie', S, 2, True):
        gk[r[0]].append(r)
    gs = [dict(g, teams=(g['h'], g['a'])) for g in gm if g['id'] in sk]
    if not gs:
        return print('nhl pctl: no games yet')
    def lines(g):
        for r in sk[g['id']]:
            toi = (r[5] or 0) / 60
            if toi > 0:
                yield (str(r[1]), D.team(r[3]), r[2], 'D' if r[4] == 'D' else 'F', toi,
                       {'g': r[6], 'a': r[7], 'pts': r[6] + r[7], 'sog': r[8]})
        for r in gk[g['id']]:
            toi = (r[5] or 0) / 60
            if toi > 0:
                yield (str(r[1]), D.team(r[3]), r[2], 'G', toi, {})
    _, cur, tg = _walk(gs, lines, 16.0, ())
    for r in sk_all:
        if str(r[1]) in cur:
            cur[str(r[1])]['pos'] = r[4]           # C, L, R, D
    site = json.load(open(os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{S}.json')))
    val = {}
    for p in site['players']:
        if p['id'] in cur and p.get('war') is not None:
            val[p['id']] = (p['war'], p['toi'])
            cur[p['id']]['ph'] = p.get('ph')
    rows, targets = project('nhl', S, cur, {t: 82 for t in tg}, val)
    age = {p['id']: p.get('age') for p in site['players']}
    gp = nhl_prior_gp(S)
    for r in rows:
        if cur[r['id']].get('ph'):
            r['ph'] = cur[r['id']]['ph']
        g, a = gp.get(r['id'], []), age.get(r['id'])
        tag(r, a, max(g, default=0) < 25 and sum(1 for x in g if x >= 6) < 2 and (a or 0) < 26)
    write('nhl', S, rows, targets, {'games': max(tg.values())})


def build_nfl():
    import nfl_war as W
    games = list(W.rows(W.get('games.csv', W.GAMES)))
    done = [g for g in games if g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    y = max(int(g['season']) for g in done)
    week = max(int(g['week']) for g in done if int(g['season']) == y)
    tlen = defaultdict(int)
    for g in games:
        if g['season'] == str(y) and g['game_type'] == 'REG':
            tlen[g['home_team']] += 1; tlen[g['away_team']] += 1
    now, prev = nfl_board(y), nfl_board(y, week - 1)
    tg, tgp = nfl_team_games(y), nfl_team_games(y, week - 1)
    site = {p['id']: p for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))['players']}
    cur, val = {}, {}
    for pid, p in now.items():
        cur[pid] = {'tm': p['tm'], 'grp': p['grp'], 'n': p['n'], 'tg': tg.get(p['tm'], 0), 'g': p['g'], 'e': p['sn'], 'sn': p['sn'],
                    'miss': max(0, (tg.get(p['tm'], 0) - tgp.get(p['tm'], 0)) - (p['g'] - prev.get(pid, {}).get('g', 0))),
                    'x': dict(p['x']), 'pos': site.get(pid, {}).get('pos', p['grp'])}
        val[pid] = (p['war'], p['sn'])
    rows, targets = project('nfl', y, cur, dict(tlen), val)
    for r in rows:
        q = site.get(r['id'], {})
        if q.get('ph'):
            r['ph'] = q['ph']
        tag(r, q.get('age'), q.get('rook'))
    write('nfl', y, rows, targets, {'week': week})


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--frames' in a:
        frames(a[a.index('--frames') + 1])
    elif '--fit' in a:
        i = a.index('--fit')
        fit(a[i + 1], [t for t in a[i + 2:] if not t.startswith('-')] or None)
    else:
        for sp in a:
            {'nba': build_nba, 'nhl': build_nhl, 'nfl': build_nfl}[sp]()
