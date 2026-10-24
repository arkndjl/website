#!/usr/bin/env python3
"""Rank odds for every power ranking, and ARK's ranking scored against the polls.

    python3 scripts/rank_odds.py --fit       # measure each sport's rating sd -> data/rank_sd.json (numpy)
    python3 scripts/rank_odds.py --record    # ARK vs AP and Coaches on the games after each poll -> data/rank_record.json
    python3 scripts/rank_odds.py --apply     # add the rank odds to today's data/*_games.json and data/cfb_rank.json

Rank odds: a team's rating is an estimate. Each simulated draw adds a normal error to every team's rating (sd from
data/rank_sd.json at the share of the season the team has left) and ranks the draws. A team's 80% rank range is the
10th to 90th percentile of its simulated rank; P(#1), P(top 4) and P(top 25) are the shares of draws. No model
refit: the ratings are the game models' own. The builders call add() (stdlib) when they write the power table;
scripts/cfb_rank.mjs carries the JS port.

The rating sd, nba_season_sd.json style (PR #338): at checkpoints in each regular season (0, 20, ... 80% of games
played), every team's rating is read back from the game model's walk-forward margins over the next days (ridge on
team and home terms; scripts/data/games_wf), then its mean residual over the rest of the regular season. That mean's
variance = sigma^2 x T/(T-1) + game noise / games left, and sigma^2 = a + b x share of the season left is fit by
likelihood, each season from the seasons before it (half-life 3 seasons), the live a, b through the last season,
floored at the smallest sd measured at any checkpoint (CBB's fit puts a at 0, which would claim near-certain ranks in
March; its 80%-of-season checkpoint measures 1.4).
The NBA keeps its own measurement from the season-sim rating (data/nba_season_sd.json), which this method lands near
(3.1 open / 2.4 end against 3.7 / 2.9; the ridge read-back smooths the rating a little).

The record: for each AP and Coaches release, every game until the next release with at least one team in that
poll. The poll's call is the higher-ranked team (a ranked team over an unranked one); ARK's is the team with the
higher rating in the game model's walk-forward margin, home edge taken out (fresher than a weekly poll: it moves
with every game, which is ARK's real edge but worth knowing). Pairwise accuracy = share of those games the call
won; Kendall tau = (concordant - discordant) / pairs over the same games = 2 x accuracy - 1. The ARK-minus-poll gap
carries a t clustered by poll week."""
import json
import math
import os
import random
import sys
import gzip
import datetime as dt
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SD = os.path.join(ROOT, 'data', 'rank_sd.json')
REC = os.path.join(ROOT, 'data', 'rank_record.json')
WF = os.path.join(HERE, 'data', 'games_wf', '{}.json.gz')
WINDOW = {'nfl': 21, 'cbb': 14, 'cfb': 21, 'nba': 10}     # days of margins a checkpoint rating is read back from
SIMS = 4000
TOPS = {'nba': (1, 4), 'nhl': (1, 4), 'soccer': (1, 4, 10), 'nfl': (1, 4), 'cbb': (1, 4, 25), 'cfb': (1, 4, 25)}


# ---------------------------------------------------------------- rank odds (stdlib; the builders call this)
def sd_of(sport, share):
    """the rating sd with a share of the season left, from data/rank_sd.json (None: not measured)"""
    try:
        p = json.load(open(SD))[sport]
    except (OSError, KeyError, ValueError):
        return None
    return max(p.get('floor', 0.0), math.sqrt(max(0.05, p['a'] + p['b'] * max(0.0, min(1.0, share)))))


def add(rows, sport, share, key='rating', seed=7):
    """rows: the power table (dicts with `key`); share: a number, or a function row -> share of its season left.
    Adds rkLo, rkHi (80% range of the simulated rank) and p1 / p4 / p25 to each row, in place."""
    fs = share if callable(share) else (lambda r: share)
    sds = [sd_of(sport, fs(r)) for r in rows]
    if not rows or any(s is None for s in sds):
        return rows
    tops = [k for k in TOPS[sport] if k < len(rows)]
    rng = random.Random(seed)
    n = len(rows)
    ranks = [[] for _ in rows]
    hit = [Counter() for _ in rows]
    R = [float(r[key]) for r in rows]
    for _ in range(SIMS):
        d = sorted(range(n), key=lambda i: -(R[i] + rng.gauss(0.0, sds[i])))
        for k, i in enumerate(d, 1):
            ranks[i].append(k)
            for t in tops:
                if k <= t:
                    hit[i][t] += 1
    for r, rk, h, s in zip(rows, ranks, hit, sds):
        rk.sort()
        r['rkLo'], r['rkHi'] = rk[int(0.1 * SIMS)], rk[int(0.9 * SIMS) - 1]
        for t in tops:
            r[f'p{t}'] = round(h[t] / SIMS, 3)
        r['rsd'] = round(s, 2)
    return rows


def _games_left(sport):
    """share-of-season functions for each data file"""
    if sport == 'nba':
        return lambda d: (lambda r: d.get('left', 0) / 1230)
    if sport == 'nfl':
        return lambda d: (lambda r: d.get('left', 0) / 272)
    if sport == 'cbb':
        return lambda d: (lambda r: 1 - min(1.0, (r.get('g') or 0) / 31))

    def cfb(d):
        def f(r):
            w, l = (int(x) for x in (r.get('rec') or '0-0').split('-')[:2])
            return 1 - min(1.0, (w + l) / 12)
        return f
    return cfb


def apply():
    for sport, path, rows, key in (('nba', 'nba_games.json', 'power', 'rating'), ('nfl', 'nfl_games.json', 'power', 'rating'),
                                   ('cbb', 'cbb_games.json', 'power', 'rating'), ('cfb', 'cfb_rank.json', 'teams', 'score')):
        p = os.path.join(ROOT, 'data', path)
        d = json.load(open(p))
        add(d[rows], sport, _games_left(sport)(d), key)
        with open(p, 'w') as f:                       # each builder's own format
            if sport in ('nfl', 'cfb'):
                f.write(json.dumps(d, indent=1, ensure_ascii=sport == 'nfl') + ('\n' if sport == 'cfb' else ''))
            else:
                json.dump(d, f, separators=(',', ':'))
        r0 = d[rows][0]
        print(sport, r0.get('t') or r0.get('team'), {k: r0.get(k) for k in ('rkLo', 'rkHi', 'p1', 'p4', 'p25', 'rsd')})


# ---------------------------------------------------------------- the rating sd (numpy)
def _day(s):
    return dt.date.fromisoformat(s[:10])


def checkpoints(sport):
    import numpy as np
    G = [g for g in json.load(gzip.open(WF.format(sport))) if not g.get('po') and g.get('m') is not None
         and g.get('res') is not None and not g.get('fcs')]
    by = defaultdict(list)
    for g in G:
        by[g['S']].append(g)
    rows = []
    for S, gs in sorted(by.items()):
        if S == 2020 and sport in ('nba', 'cbb'):
            continue
        gs.sort(key=lambda g: g['date'])
        N = len(gs)
        teams = sorted({g['home'] for g in gs} | {g['away'] for g in gs})
        ix = {t: i for i, t in enumerate(teams)}
        T = len(teams)
        tot = Counter([g['home'] for g in gs] + [g['away'] for g in gs])
        gn = float(np.var([g['res'] - g['m'] for g in gs]))
        for f in (0, .2, .4, .6, .8):
            i0 = int(f * N)
            d0 = _day(gs[i0]['date'])
            win = [g for g in gs[i0:] if (_day(g['date']) - d0).days < WINDOW[sport]]
            X = np.zeros((len(win), T + 1))
            y = np.array([g['m'] for g in win], float)
            for j, g in enumerate(win):
                X[j, ix[g['home']]], X[j, ix[g['away']]] = 1, -1
                X[j, T] = 0 if g.get('neutral') else 1
            b = np.linalg.solve(X.T @ X + 0.3 * np.diag([1.0] * T + [0.0]), X.T @ y)
            hca, r = b[T], b[:T] - b[:T].mean()
            seen = Counter([g['home'] for g in win] + [g['away'] for g in win])
            res = defaultdict(list)
            for g in gs[i0:]:
                e = g['res'] - (r[ix[g['home']]] - r[ix[g['away']]] + (0 if g.get('neutral') else hca))
                res[g['home']].append(e)
                res[g['away']].append(-e)
            for t, v in res.items():
                if len(v) >= 3 and seen[t] >= 2:
                    rows.append((S, f, float(np.mean(v)), len(v), len(v) / tot[t], gn, T))
    return np.array(rows)


def fit_sport(sport):
    import numpy as np
    R = checkpoints(sport)
    Sx, ck, A, n, sh, gn, T = (R[:, i] for i in range(7))

    def nll_rows(s2):
        v = np.maximum(s2, 0.05) * T / (T - 1) + gn / n
        return 0.5 * (np.log(2 * np.pi * v) + A ** 2 / v)

    grid = [(a, b) for a in np.arange(0, 30.01, 0.5) for b in np.arange(0, 60.01, 0.5)]
    L = np.array([nll_rows(a + b * sh) for a, b in grid])          # grid x rows

    def wfit(s_, hl=3):
        w = np.where(Sx < s_, 0.5 ** ((s_ - 1 - Sx) / hl), 0.0)
        return grid[int(np.argmin(L @ w))]
    seasons = sorted(set(Sx.astype(int).tolist()))
    walk, base, nn, ab = 0.0, 0.0, 0, {}
    for s_ in seasons[1:]:
        k = Sx == s_
        a, b = wfit(s_)
        ab[s_] = [float(a), float(b)]
        prev = Sx < s_
        c = float(np.mean((A ** 2 - gn / n)[prev]))                  # one sd for the whole season, same past seasons
        walk += float(nll_rows(a + b * sh)[k].sum())
        base += float(nll_rows(np.full(len(A), c))[k].sum())
        nn += int(k.sum())
    a, b = wfit(seasons[-1] + 1)
    msd = {str(c_): round(float(math.sqrt(max(0.0, np.mean((A ** 2 - gn / n)[ck == c_]) * (T[0] - 1) / T[0]))), 2)
           for c_ in (0, .2, .4, .6, .8)}
    return {'a': float(a), 'b': float(b), 'halfLife': 3, 'seasons': [seasons[0], seasons[-1]], 'n': int(len(A)),
            'sdOpen': round(math.sqrt(a + b), 2), 'sdEnd': round(math.sqrt(max(a, 0.05)), 2), 'byCheckpoint': msd,
            'floor': min(msd.values()),
            'walk': {'seasons': seasons[1:], 'nll': round(walk / max(nn, 1), 4), 'nllFlat': round(base / max(nn, 1), 4), 'ab': ab}}


def fit():
    out = {}
    for s in ('nfl', 'cbb', 'cfb', 'nba'):
        out[s] = fit_sport(s)
        print(s, {k: out[s][k] for k in ('a', 'b', 'sdOpen', 'sdEnd', 'n')}, out[s]['walk']['nll'], out[s]['walk']['nllFlat'], flush=True)
    nba = json.load(open(os.path.join(ROOT, 'data', 'nba_season_sd.json')))
    out['nba'] = {'a': nba['a'], 'b': nba['b'], 'sdOpen': nba['sdOpen'], 'sdEnd': nba['sdEnd'], 'floor': out['nba']['floor'], 'src': 'data/nba_season_sd.json',
                  'readBack': {k: out['nba'][k] for k in ('a', 'b', 'sdOpen', 'sdEnd', 'byCheckpoint', 'walk')}}
    out['note'] = 'rating sd^2 = a + b x share of the season left (scripts/rank_odds.py --fit)'
    for sp in ('nhl', 'soccer'):               # measured by scripts/nhl_games.py, scripts/soccer_games.py: kept as written
        try:
            out[sp] = json.load(open(SD))[sp]
        except (OSError, KeyError, ValueError):
            pass
    with open(SD, 'w') as f:
        json.dump(out, f, indent=1)


# ---------------------------------------------------------------- ARK vs the polls
def record_sport(sport):
    import numpy as np
    P = json.load(open(os.path.join(HERE, 'data', 'polls', f'{sport}.json')))
    G = [g for g in json.load(gzip.open(WF.format(sport))) if g.get('m') is not None and g.get('res') not in (None, 0)]
    # ESPN id -> the game files' name: CBB through the history file's ids, CFB through ESPN's location names
    names = dict(P['names'])
    if sport == 'cbb':
        H = {h['id']: h for h in json.load(gzip.open(os.path.join(HERE, 'data', 'cbb_games_hist.json.gz')))}
        for g in G:
            h = H.get(g['id'])
            if h:
                names[h['home']], names[h['away']] = g['home'], g['away']
    # the home edge in the model's margins, each season (ridge on team and home terms over the season's margins)
    hca = {}
    for S in {g['S'] for g in G}:
        gs = [g for g in G if g['S'] == S]
        teams = sorted({g['home'] for g in gs} | {g['away'] for g in gs})
        ix = {t: i for i, t in enumerate(teams)}
        X = np.zeros((len(gs), len(teams) + 1))
        for j, g in enumerate(gs):
            X[j, ix[g['home']]], X[j, ix[g['away']]] = 1, -1
            X[j, -1] = 0 if g.get('neutral') else 1
        b = np.linalg.lstsq(X, np.array([g['m'] for g in gs]), rcond=None)[0]
        hca[S] = float(b[-1])
    seasons = sorted({g['S'] for g in G})
    G.sort(key=lambda g: g['date'])
    out = {}
    for poll in ('ap', 'coaches'):
        rel = [r for r in P['releases'] if r['poll'] == poll and r['S'] in seasons and r['date']]
        rel.sort(key=lambda r: r['date'])
        rows = []
        for i, r in enumerate(rel):
            nxt = next((x['date'] for x in rel[i + 1:] if x['S'] == r['S'] and x['date'] > r['date']), None)
            rk = {names.get(x['id']): x['rk'] for x in r['ranks']}
            rk.pop(None, None)
            for g in G:
                if g['S'] != r['S'] or g['date'][:10] <= r['date'][:10] or (nxt and g['date'][:10] > nxt[:10]):
                    continue
                h, a = rk.get(g['home']), rk.get(g['away'])
                if h is None and a is None:
                    continue
                won = 1 if g['res'] > 0 else -1
                poll_h = 1 if a is None or (h is not None and h < a) else -1
                diff = g['m'] - (0 if g.get('neutral') else hca[g['S']])
                if diff == 0:
                    continue
                ark_h = 1 if diff > 0 else -1
                rows.append((r['S'], f"{r['S']}-{r['type']}-{r['week']}", int(ark_h == won), int(poll_h == won), int(h is not None and a is not None)))
        out[poll] = rows
    rec = {'seasons': seasons, 'polls': {}}
    for poll, rows in out.items():
        if not rows:
            continue
        by = defaultdict(list)
        for x in rows:
            by[x[0]].append(x)
        bs = []
        for S in sorted(by):
            q = by[S]
            bs.append(summ(q, S))
        rec['polls'][poll] = {'bySeason': bs, 'all': summ(rows, 'all'), 'bothRanked': summ([x for x in rows if x[4]], 'both')}
    return rec


def summ(q, label):
    import numpy as np
    ark = np.array([x[2] for x in q], float)
    pol = np.array([x[3] for x in q], float)
    d = ark - pol
    cl = defaultdict(float)
    for x, di in zip(q, d):
        cl[x[1]] += di
    G = len(cl)
    se = math.sqrt(G / max(G - 1, 1) * sum(v * v for v in cl.values())) / len(q) if len(q) else 0
    t = float(d.mean() / se) if se > 0 else 0.0
    return {'S': label, 'n': len(q), 'ark': round(float(ark.mean()), 3), 'poll': round(float(pol.mean()), 3),
            'tauArk': round(float(2 * ark.mean() - 1), 3), 'tauPoll': round(float(2 * pol.mean() - 1), 3),
            'gap': round(float(d.mean()), 3), 't': round(t, 2), 'weeks': G}


def record():
    out = {'note': 'ARK vs the polls on the games after each release (scripts/rank_odds.py --record); '
                   'accuracy = share of games the higher-ranked team won, tau = 2 x accuracy - 1'}
    for s in ('cbb',):                  # CFB's record lives in data/cfb_rank.json evidence.vsPolls (its full game list)
        out[s] = record_sport(s)
        for p, v in out[s]['polls'].items():
            print(s, p, v['all'], v['bothRanked'])
    with open(REC, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
    if '--record' in sys.argv:
        record()
    if '--apply' in sys.argv:
        apply()
