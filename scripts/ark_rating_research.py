#!/usr/bin/env python3
"""ARK Ranking upgrade research (Oct 26 2026): new long-memory team ratings tested on the game models.

    python3 scripts/ark_rating_research.py nfl     # writes data/ark_rating_research.json (numpy)

NFL: game control (the time-weighted home win chance from score and clock alone, Phi(lead / (13.5 sqrt(share left))),
regulation only, nflverse play-by-play) and its margin twin, each as a ridge Massey rating with home field, last
season's final rating carried as the prior (carry x rating, worth lam games). The same idea shipped in CFB and CBB
(scripts/control_ratings.py); NFL never had it. Every rating is known before kickoff (solved on earlier weeks only).
Scored as nfl_games_research.py scores candidates: the live inputs plus one, walk-forward OLS (fit on earlier
seasons), margin MAE paired per game, 2015-20 tunes, 2021-25 held out. Keep at tune t <= -1.5 and held t < 0.
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ark_rating_research.json')


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def nfl_control(y, P, N, sd=13.5):
    """game_id -> home control (0-1) over regulation, from the play-by-play score timeline."""
    P.season(y)                                   # makes sure the raw file is cached
    rd = csv.reader(gzip.open(P.RAW.format(y=y), 'rt'))
    h = next(rd); I = {k: i for i, k in enumerate(h)}
    tl = defaultdict(list)
    for r in rd:
        q, s = r[I['qtr']], r[I['game_seconds_remaining']]
        if q in ('', 'NA') or int(q) > 4 or s in ('', 'NA'):
            continue
        hs, as_ = r[I['total_home_score']], r[I['total_away_score']]
        if hs in ('', 'NA') or as_ in ('', 'NA'):
            continue
        tl[r[I['game_id']]].append((3600 - float(s), float(hs) - float(as_)))
    out = {}
    for g, pts in tl.items():
        pts.sort()
        acc, prev_t, lead = 0.0, 0.0, 0.0
        for t, l in pts + [(3600.0, None)]:
            t = min(max(t, prev_t), 3600.0)
            if t > prev_t:      # the lead held from prev_t to t: integrate Phi over the stretch (midpoint, 30 s steps)
                n = max(1, int((t - prev_t) / 30))
                for k in range(n):
                    m = prev_t + (k + 0.5) * (t - prev_t) / n
                    left = max(1.0 - m / 3600, 1e-3)
                    acc += phi(lead / (sd * math.sqrt(left))) * (t - prev_t) / n
            prev_t = t
            if l is not None:
                lead = l
        out[g] = min(max(acc / 3600, 0.01), 0.99)
    return out


def massey(games, val, lam, carry, ridge_home=10.0):
    """game_id -> home minus away rating before kickoff. games in date order with 'season','week','home','away',
    'id'; val[id] = home outcome (probit control or margin) for played games. Solved once a week on the season's
    earlier games, prior = carry x last season's final rating worth lam games."""
    import numpy as np
    out = {}
    by = defaultdict(list)
    for g in games:
        by[(g['season'], g['week'])].append(g)
    prior = defaultdict(float)
    season, played, cur = None, [], {}
    for key in sorted(by):
        s = key[0]
        if s != season:
            if season is not None:
                prior = defaultdict(float, {t: carry * v for t, v in cur.items()})
            season, played = s, []
            cur = dict(prior)
        teams = sorted({t for g in played for t in (g['home'], g['away'])} | set(prior))
        if played:
            ix = {t: i for i, t in enumerate(teams)}
            n = len(teams)
            M = np.zeros((n + 1, n + 1)); b = np.zeros(n + 1)
            for t, i in ix.items():
                M[i, i] += lam; b[i] += lam * prior.get(t, 0.0)
            M[n, n] += ridge_home
            for g in played:
                v = np.zeros(n + 1); v[ix[g['home']]] = 1; v[ix[g['away']]] = -1; v[n] = 0 if g.get('neutral') else 1
                M += np.outer(v, v); b += v * val[g['id']]
            sol = np.linalg.solve(M, b)
            cur = {t: sol[i] for t, i in ix.items()}
        for g in by[key]:
            out[g['id']] = cur.get(g['home'], prior.get(g['home'], 0.0)) - cur.get(g['away'], prior.get(g['away'], 0.0))
        played += [g for g in by[key] if g['id'] in val]
    return out


def nfl():
    import numpy as np
    import nfl_games as N
    import nfl_pbp as P
    last = 2025
    F = json.load(open(N.FIT)); params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, params)
    ctl = {}
    for y in range(N.FIRST, last + 1):
        ctl.update(nfl_control(y, P, N)); print('control', y, len(ctl), flush=True)
    G = []
    for g in games:
        G.append({'id': g['game_id'], 'season': int(g['season']), 'week': int(g['week']), 'home': N.team(g['home_team']),
                  'away': N.team(g['away_team']), 'neutral': g['location'] == 'Neutral'})
    played = [g for g in games if g['home_score'] not in ('', 'NA')]
    probit = lambda c: math.sqrt(2) * _erfinv(2 * c - 1)
    vgc = {g['game_id']: probit(ctl[g['game_id']]) for g in played if g['game_id'] in ctl}
    vgm = {g['game_id']: max(-28.0, min(28.0, N.num(g['result']))) for g in played}
    print('control games', len(vgc), 'of', len(played), flush=True)
    D = []
    for g, x, tx in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        r = inj.get(g['game_id'])
        x = dict(x)
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D.append((g, x))
    S = np.array([int(g['season']) for g, _ in D]); y = np.array([N.num(g['result']) for g, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D]); ok = ~np.isnan(line)
    A = (S >= 2015) & (S <= 2020) & ok; B = (S >= 2021) & ok
    win = np.where(y > 0, 1.0, np.where(y < 0, 0.0, 0.5))

    def wf(cols):
        X = np.column_stack(cols)
        pred = np.full(len(y), np.nan)
        for s in range(2013, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        return pred

    base = [np.array([x.get(f, 0.0) for _, x in D]) for f in N.FEATS]
    p0 = wf(base); e0 = np.abs(p0 - y)
    sd = float(np.std((p0 - y)[A]))

    def ll(p):
        q = np.clip(0.5 * (1 + np.vectorize(math.erf)(p / sd / math.sqrt(2))), 1e-6, 1 - 1e-6)
        return -(win * np.log(q) + (1 - win) * np.log(1 - q))
    l0 = ll(p0)

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return [round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)]

    res = {'base': {'feats': N.FEATS, 'mae1520': round(float(e0[A].mean()), 3), 'mae2125': round(float(e0[B].mean()), 3),
                    'line1520': round(float(np.abs(line[A] - y[A]).mean()), 3), 'line2125': round(float(np.abs(line[B] - y[B]).mean()), 3)},
           'cand': {}}
    for name, val in (('gc', vgc), ('gm', vgm)):
        for lam in (2.0, 4.0, 8.0):
            for carry in (0.5, 0.8, 1.0):
                r = massey(G, val, lam, carry)
                col = np.array([r.get(g['game_id'], 0.0) for g, _ in D])
                p1 = wf(base + [col]); e1 = np.abs(p1 - y); l1 = ll(p1)
                k = f'{name} lam{lam:g} carry{carry:g}'
                res['cand'][k] = {'mae1520': cmp(e1, e0, A), 'mae2125': cmp(e1, e0, B), 'll1520': cmp(l1, l0, A), 'll2125': cmp(l1, l0, B)}
                print(k, res['cand'][k], flush=True)
    tune = min(res['cand'], key=lambda k: res['cand'][k]['mae1520'][1])
    res['pickedOnTune'] = tune
    res['pass'] = res['cand'][tune]['mae1520'][1] <= -1.5 and res['cand'][tune]['mae2125'][1] < 0
    return res


def nfl_fpi():
    """NFL: ESPN's FPI game forecast (scripts/nfl_fpi.py, home margin) stacked on the live inputs, the way CFB FPI and
    CBB BPI shipped (PR #354). Games with an FPI margin only (2015 on); walk-forward OLS trains on earlier seasons
    from 2015, so 2016-20 tunes and 2021-25 is held out. FPI never beats the close in any season (no hindsight)."""
    import numpy as np
    import nfl_games as N
    last = 2025
    fpi = json.load(gzip.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'public_ratings', 'nfl_fpi.json.gz')))
    F = json.load(open(N.FIT)); params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, params)
    D = []
    for g, x, tx in data:
        r = fpi.get(g['game_id'])
        if g['home_score'] in ('', 'NA') or not r or r.get('pd') is None or int(g['season']) < 2015:
            continue
        x = dict(x); ri = inj.get(g['game_id'])
        if ri:
            x['inj'] = (ri[2] + ri[3]) - (ri[0] + ri[1])
        x['fpi'] = r['pd']
        D.append((g, x))
    S = np.array([int(g['season']) for g, _ in D]); y = np.array([N.num(g['result']) for g, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D]); ok = ~np.isnan(line)
    A = (S >= 2016) & (S <= 2020) & ok; B = (S >= 2021) & ok
    win = np.where(y > 0, 1.0, np.where(y < 0, 0.0, 0.5))

    def wf(feats):
        X = np.array([[x.get(f, 0.0) for f in feats] for _, x in D]); pred = np.full(len(y), np.nan)
        for s in range(2016, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        return pred, dict(zip(feats, np.linalg.lstsq(X, y, rcond=None)[0]))
    p0, _ = wf(N.FEATS); p1, b1 = wf(N.FEATS + ['fpi'])
    sd = float(np.std((p0 - y)[A]))

    def ll(p):
        q = np.clip(0.5 * (1 + np.vectorize(math.erf)(p / sd / math.sqrt(2))), 1e-6, 1 - 1e-6)
        return -(win * np.log(q) + (1 - win) * np.log(1 - q))

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return [round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)]
    e0, e1 = np.abs(p0 - y), np.abs(p1 - y)
    res = {'games': len(D), 'coef': {k: round(float(v), 3) for k, v in b1.items()},
           'mae': {'base1620': round(float(e0[A].mean()), 3), 'fpi1620': round(float(e1[A].mean()), 3),
                   'base2125': round(float(e0[B].mean()), 3), 'fpi2125': round(float(e1[B].mean()), 3),
                   'close2125': round(float(np.abs(line[B] - y[B]).mean()), 3)},
           'mae1620': cmp(e1, e0, A), 'mae2125': cmp(e1, e0, B), 'll1620': cmp(ll(p1), ll(p0), A), 'll2125': cmp(ll(p1), ll(p0), B)}
    res['bySeason']={int(s):round(float((e1-e0)[(S==s)&ok].mean()),3) for s in range(2016,2026)}
    res['pass'] = res['mae1620'][1] <= -1.5 and res['mae2125'][1] < 0
    return res


def nhl():
    """NHL: a second, long-memory xG rating (and goals twin) beside the live 120-day one. The live tune grid stops at
    a 120-day half-life and .7 carry, so a multi-season memory (what game control added in CFB and CBB) was never
    tried. Scored with nhl_games.evidence: add-one walk-forward win log loss, t clustered by day; non-market inputs
    on every game (2017-23 tunes, 2024-26 held out), and on lined games only."""
    import nhl_games as N
    F = json.load(open(N.FIT)); P = F['params']; feats = F['feats']
    hist = N.load_hist()
    VAR = {'xgL1': ('xg', 365, 0.9), 'xgL2': ('xg', 730, 1.0), 'xgL3': ('xg', 240, 0.85), 'gL1': ('g', 365, 0.9), 'gL2': ('g', 730, 1.0)}

    class M(N.Model):
        def __init__(self, P):
            super().__init__(P)
            self.LM = {k: N.OD(hl, car, P['pen']) for k, (_, hl, car) in VAR.items()}

        def advance(self, day, S):
            if self.S is not None and S != self.S:
                for e in self.LM.values():
                    e.season()
            if self.day is not None and day > self.day:
                n = N._days(self.day, day)
                for e in self.LM.values():
                    e.step(n)
            super().advance(day, S)

        def feats(self, g, *a, **k):
            f = super().feats(g, *a, **k)
            for key, e in self.LM.items():
                f[key] = e.net(g['h'], g['a'])
            return f

        def update(self, g):
            x = g.get('x')
            if g.get('hs') is not None and x:
                for key, (src, _, _) in VAR.items():
                    i = 0 if src == 'xg' else 2
                    self.LM[key].add(g['h'], g['a'], x['h'][i], x['a'][i])
            super().update(g)
    N.Model = M
    _, rows, _ = N.walk(hist, P)
    nm = [k for k in feats if k != 'mkt']
    res = {'feats': feats,
           'all': N.evidence(rows, nm, list(VAR), lined_only=False, first=N.SCORE_FROM + 1, tune_s=(N.SCORE_FROM + 1, N.TUNE[1])),
           'lined': N.evidence(rows, feats, list(VAR))}
    return res


def _erfinv(x):
    a = 0.147; ln = math.log(1 - x * x); t = 2 / (math.pi * a) + ln / 2
    return math.copysign(math.sqrt(math.sqrt(t * t - ln / a) - t), x)


if __name__ == '__main__':
    sport = sys.argv[1] if len(sys.argv) > 1 else 'nfl'
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    out[sport] = {'nfl': nfl, 'nhl': nhl, 'nfl_fpi': nfl_fpi}[sport]()
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(out[sport], default=str)[:1500])
