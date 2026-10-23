#!/usr/bin/env python3
"""Game-control ratings: how much of each game a team spent in control, opponent-adjusted, as a second rating next
to margin (team model idea 8, Oct 2026). Research and the live feature both come from here.

Control in one game: the time-weighted mean of the home side's win probability over regulation, from score and
clock alone (scripts/espn_control.py control(): Phi(lead / (sd x sqrt(share left))), sd fit to who won from each
state, no pregame prior), so a team that led all night gets near 1 however the margin ended, and garbage-time points
barely move it. Ratings: a ridge (Massey) fit of probit(control) on team and home columns, games before each date,
weighted by a half-life in days, shrunk toward last season's final rating x carry. Feature = home minus away, in
probit units.
  python3 scripts/control_ratings.py sd cfb|cbb|nba      # fit the score-state sd on the cache
  python3 scripts/control_ratings.py cfbhist [last]      # scripts/data/cfb_control_hist.json from the summary cache
  python3 scripts/control_ratings.py cfblive [season]    # the live CFB input (cfb-board workflow, after cfb_espn_pbp)
  python3 scripts/control_ratings.py cfbfeat <md.gz>     # research variants for scripts/cfb_control_backtest.mjs
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import espn_control as E

# score-state sd (points over a full game), fit by `sd` on who won from each state (2015-21 games)
SD = {'cfb': 16.0, 'cbb': 13.5, 'nba': 18.0}


def records(sport, seasons=None):
    out = {}
    d = os.path.join(E.CACHE, sport)
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        S = int(f[:4])
        if seasons and S not in seasons:
            continue
        out.update(E.load(sport, S))
    return out


def fit_sd(sport, lo=2015, hi=2021):
    """the sd that best predicts the final winner from (lead, share left), log loss over states every 60 s"""
    R = records(sport, range(lo, hi + 1))
    L, Y = [], []
    for r in R.values():
        f = r.get('fin') or [None, None]
        try:
            m = float(f[0]) - float(f[1])
        except (TypeError, ValueError):
            continue
        if m == 0:
            continue
        sc, i, lead = r['sc'], 0, 0
        for t in range(60, r['len'], 60):
            while i < len(sc) and sc[i][0] <= t:
                lead = sc[i][1] - sc[i][2]; i += 1
            L.append((lead, 1 - t / r['len'])); Y.append(1.0 if m > 0 else 0.0)
    L, Y = np.array(L, float), np.array(Y)
    best = None
    for sd in np.arange(6, 25.01, 0.5):
        z = L[:, 0] / (sd * np.sqrt(L[:, 1]))
        p = np.clip(0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2))), 1e-6, 1 - 1e-6)
        ll = float(-np.mean(Y * np.log(p) + (1 - Y) * np.log(1 - p)))
        if best is None or ll < best[0]:
            best = (ll, float(sd))
    return {'sd': best[1], 'logLoss': round(best[0], 4), 'states': len(Y), 'games': len(R)}


def probit(p, lo=0.02):
    p = min(1 - lo, max(lo, p))
    # Acklam-free: Newton on erf (enough here)
    z = 0.0
    for _ in range(30):
        f = 0.5 * (1 + math.erf(z / math.sqrt(2))) - p
        z -= f / (math.exp(-z * z / 2) / math.sqrt(2 * math.pi))
    return z


def game_control(sport, recs=None, sd=None, kind='free'):
    """{game id: home control in [0,1]}; kind 'free' (score and clock) or 'espn' (ESPN's own win probability)"""
    recs = recs if recs is not None else records(sport)
    sd = sd or SD[sport]
    out = {}
    for i, r in recs.items():
        c = E.control(r, sd) if kind == 'free' else E.control_espn(r)
        if c is not None:
            out[i] = c
    return out


def ratings(games, ctl, hl=None, carry=0.5, lam=3.0, form='probit', hca=True, minn=0):
    """games: [(id, date 'YYYY-MM-DD', season, home, away, neutral)] in date order. Returns {id: home minus away
    rating before the game} and the final ratings by season. Ridge on games before each date; weights
    0.5 ** (days ago / hl) (hl None: every game this season alike). minn: teams with fewer games than this in a
    season share one rating (college basketball's non-D-I opponents)"""
    y_of = (lambda c: probit(c)) if form == 'probit' else (lambda c: c - 0.5)
    feat, finals = {}, {}
    by_season = defaultdict(list)
    for g in games:
        by_season[g[2]].append(g)
    prev = {}
    for S in sorted(by_season):
        gs = sorted(by_season[S], key=lambda g: g[1])
        if minn:
            cnt = defaultdict(int)
            for g in gs:
                cnt[g[3]] += 1; cnt[g[4]] += 1
            pool = lambda t: t if cnt[t] >= minn else '_other'
            gs = [(g[0], g[1], g[2], pool(g[3]), pool(g[4]), g[5]) for g in gs]
        teams = sorted({t for g in gs for t in (g[3], g[4])})
        ix = {t: k for k, t in enumerate(teams)}
        n = len(teams) + 1                               # + home court
        A = np.zeros((n, n)); b = np.zeros(n)
        pri = np.array([carry * prev.get(t, 0.0) for t in teams] + [0.0])
        reg = np.full(n, lam); reg[-1] = 1e-3
        last_day = None
        r = pri.copy()
        k = 0
        while k < len(gs):
            day = gs[k][1]
            if last_day is not None and hl:
                dd = (np.datetime64(day) - np.datetime64(last_day)).astype(int)
                f = 0.5 ** (dd / hl)
                A *= f; b *= f
            last_day = day
            if A.any():
                M = A + np.diag(reg)
                r = np.linalg.solve(M, b + reg * pri)
            todays = []
            while k < len(gs) and gs[k][1] == day:
                todays.append(gs[k]); k += 1
            for gid, _, _, h, a, neu in todays:
                feat[gid] = float(r[ix[h]] - r[ix[a]])
            for gid, _, _, h, a, neu in todays:
                c = ctl.get(gid)
                if c is None:
                    continue
                x = np.zeros(n); x[ix[h]] = 1; x[ix[a]] = -1
                if hca and not neu:
                    x[-1] = 1
                A += np.outer(x, x); b += x * y_of(c)
        M = A + np.diag(reg)
        r = np.linalg.solve(M, b + reg * pri)
        finals[S] = {t: float(r[ix[t]]) for t in teams}
        finals[S]['_hca'] = float(r[-1])
        prev = finals[S]
    return feat, finals


CFB_GRID = {'all': dict(hl=None, carry=0.3, lam=3.0), 'all6': dict(hl=None, carry=0.6, lam=3.0),
            'hl42': dict(hl=42, carry=0.3, lam=3.0), 'hl42c6': dict(hl=42, carry=0.6, lam=3.0),
            'all8': dict(hl=None, carry=0.8, lam=3.0), 'all6l6': dict(hl=None, carry=0.6, lam=6.0),
            'all9': dict(hl=None, carry=0.9, lam=3.0), 'all10': dict(hl=None, carry=1.0, lam=3.0), 'all8l15': dict(hl=None, carry=0.8, lam=1.5),
            'all10l15': dict(hl=None, carry=1.0, lam=1.5), 'all10l6': dict(hl=None, carry=1.0, lam=6.0)}


def cfb_feat(md_path, out_path, espn=True):
    """pregame control-rating gaps by game id for every variant of CFB_GRID (and ESPN's win probability at the
    first), for scripts/cfb_control_backtest.mjs"""
    import gzip
    md = json.load(gzip.open(md_path, 'rt'))
    gl = [(str(g['id']), g['startDate'][:10], int(S), str(g['homeId']), str(g['awayId']), bool(g.get('neutralSite')))
          for S, gs in md['games'].items() for g in gs]
    gl.sort(key=lambda g: g[1])
    recs = records('cfb')
    ctl = game_control('cfb', recs)
    out = {'params': {}, 'variants': {}, 'n': len(ctl)}
    for k, p in CFB_GRID.items():
        out['params'][k] = p
        out['variants'][k] = {i: round(v, 4) for i, v in ratings(gl, ctl, **p)[0].items()}
    # the same rating on the final margin (capped at 28) in place of control: whether control itself carries the gain
    mctl = {}
    for i, r in recs.items():
        try:
            m = float(r['fin'][0]) - float(r['fin'][1])
        except (TypeError, ValueError, KeyError):
            continue
        mctl[i] = E.phi(max(-28.0, min(28.0, m)) / SD['cfb'])
    for k in ('all10l15', 'all8l15'):
        out['params']['mov_' + k] = {**CFB_GRID[k], 'kind': 'margin'}
        out['variants']['mov_' + k] = {i: round(v, 4) for i, v in ratings(gl, mctl, **CFB_GRID[k])[0].items()}
    if espn:
        out['params']['espn'] = {**CFB_GRID['all8'], 'kind': 'espn'}
        out['variants']['espn'] = {i: round(v, 4) for i, v in ratings(gl, game_control('cfb', recs, kind='espn'), **CFB_GRID['all8'])[0].items()}
    json.dump(out, open(out_path, 'w'))
    print(len(gl), 'games,', len(ctl), 'with control')


# ---- the live CFB input (scripts/cfb_model.mjs CAND.gc) -----------------------------------------------------------
# shipped setting (scripts/cfb_control_backtest.mjs, Oct 23 2026, picked on 2017-20 log loss): every game this season
# alike, last season's final rating carried whole as the prior, ridge 1.5 games
CFB_LIVE = dict(hl=None, carry=1.0, lam=1.5)
CFB_HIST = os.path.join(HERE, 'data', 'cfb_control_hist.json')
CFB_LIVE_OUT = os.path.join(HERE, '.cache', 'cfb', 'control_live.json')


def cfb_hist(last=2025):
    """the frozen history: every finished FBS-side game's control 2015-last, from the summary cache (committed, so the
    live job reads only this season's play-by-play)"""
    recs = records('cfb', range(2015, last + 1))
    out = {i: round(c, 4) for i, c in sorted(game_control('cfb', recs).items())}
    json.dump({'sd': SD['cfb'], 'seasons': [2015, last], 'control': out}, open(CFB_HIST, 'w'), separators=(',', ':'))
    print(len(out), 'games written to', CFB_HIST)


def pbp_record(d):
    """a slim play-by-play game (scripts/cfb_espn_pbp.py) as a score timeline"""
    sc, last = [], (0, 0)
    for dr in d.get('drives') or []:
        for p in dr.get('plays') or []:
            q, c, h, a = p.get('q'), E.clock(p.get('c') or ''), p.get('hs'), p.get('as')
            if not p.get('sc') or not q or c is None or h is None or a is None or q > 4 or (h, a) == last:
                continue
            sc.append([round((q - 1) * 900 + 900 - c), int(h), int(a)])
            last = (int(h), int(a))
    fin = {t.get('ha'): t.get('score') for t in d.get('teams') or []}
    return {'len': 3600, 'sc': sorted(sc), 'fin': [fin.get('home'), fin.get('away')]}


def cfb_live(season=None):
    """pregame control-rating gaps for every game 2015 on (this season's unplayed games included) and each team's
    rating now -> scripts/.cache/cfb/control_live.json (read by scripts/cfb_model.mjs)"""
    import datetime
    import gzip
    import cfb_espn_hist as Hh
    import cfb_espn_pbp as Pb
    now = datetime.date.today()
    season = season or (now.year if now.month >= 8 else now.year - 1)
    hist = json.load(open(CFB_HIST))
    ctl = dict(hist['control'])
    md = json.load(gzip.open(os.path.join(HERE, 'data', 'cfb_hist_md.json.gz'), 'rt'))
    gl = [(str(g['id']), g['startDate'][:10], int(S), str(g['homeId']), str(g['awayId']), bool(g.get('neutralSite')))
          for S, gs in md['games'].items() for g in gs]
    for S in range(max(md['seasons']) + 1, season + 1):
        p = os.path.join(Hh.DIR, f'games{S}.json')
        if not os.path.exists(p):
            continue
        for g in json.load(open(p)):
            gl.append((str(g['id']), g['date'][:10], S, str(g['h']), str(g['a']), bool(g.get('n'))))
            if g.get('done') and str(g['id']) not in ctl:
                d = Pb.load(str(g['id']))
                if d:
                    c = E.control(pbp_record(d), SD['cfb'])
                    if c is not None:
                        ctl[str(g['id'])] = c
    gl.sort(key=lambda g: g[1])
    feat, finals = ratings(gl, ctl, **CFB_LIVE)
    out = {'asof': now.isoformat(), 'season': season, 'params': CFB_LIVE, 'sd': SD['cfb'], 'games': len(ctl),
           'feat': {i: round(v, 4) for i, v in feat.items()},
           'team': {t: round(v, 4) for t, v in (finals.get(season) or {}).items() if t != '_hca'}}
    os.makedirs(os.path.dirname(CFB_LIVE_OUT), exist_ok=True)
    json.dump(out, open(CFB_LIVE_OUT, 'w'), separators=(',', ':'))
    print(len(feat), 'games,', len(ctl), 'with control,', len(out['team']), 'team ratings', season, '->', CFB_LIVE_OUT)


if __name__ == '__main__':
    if sys.argv[1] == 'sd':
        print(json.dumps(fit_sd(sys.argv[2])))
    elif sys.argv[1] == 'cfbhist':
        cfb_hist(int(sys.argv[2]) if len(sys.argv) > 2 else 2025)
    elif sys.argv[1] == 'cfblive':
        cfb_live(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif sys.argv[1] == 'cfbfeat':
        cfb_feat(sys.argv[2], os.path.join(HERE, '.cache', 'cfb', 'control_feat.json'))
