#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL Potential Breakout ("next up" tab): breakout odds and contextual workload scaling for WR, TE and RB
(static/data/next-up/nfl.json). Model and held-out tests: scripts/nfl_breakout_research.py -> data/nfl_breakout_fit.json.

    python3 scripts/nfl_breakout.py            # build from nflverse (scripts/.cache/nfl) + the fit; stdlib only

Workload (u): WR/TE = share of the team's targets in the games he played; RB = share of the team's carries + targets.
Efficiency (x): yards per opportunity (WR/TE receiving yards a target; RB scrimmage yards a carry or target).
QB, OL and defense are not scaled (their workload is the snap count; it does not move the way a target share does).

Feature columns live here so the research fit and the live board build them the same way."""
import csv
import gzip
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
FIT = os.path.join(ROOT, 'data', 'nfl_breakout_fit.json')
OUT = os.path.join(ROOT, 'static', 'data', 'next-up', 'nfl.json')
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
FRANCHISE = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA'}
POS = ('WR', 'TE', 'RB')
SNAP0 = 2013                                        # snap counts start here
XMEAN = {'WR': 7.9, 'TE': 7.3, 'RB': 4.6}           # league yards per opportunity
UREF = {'WR': 20.0, 'TE': 15.0, 'RB': 25.0}         # a starter's share: "low volume" is measured below it
KREL = {'WR': 60.0, 'TE': 60.0, 'RB': 100.0}        # opportunities at which a rate is half signal
SNAPMEAN = {'WR': 0.55, 'TE': 0.5, 'RB': 0.35}
NOPICK = 270
UMAX = {'WR': 35.0, 'TE': 30.0, 'RB': 47.0}         # the largest season shares on record: a tier past it is dimmed
TIERS = (5.0, 10.0, 15.0)                           # share points over the current workload
SUM = ('tg', 'ca', 'rc', 'wy', 'ry', 'ay', 'yac', 'wtd', 'rtd', 'ppr', 'ttg', 'tca')


def num(x):
    try:
        return float(x) if x not in (None, '', 'NA') else 0.0
    except ValueError:
        return 0.0


def get(name, url, fresh=False):
    """the cached nflverse file (the names scripts/nfl_fantasy.py uses, so one CI cache serves both)"""
    p = os.path.join(CACHE, name)
    if fresh or not os.path.exists(p):
        try:
            from nfl_pbp import download
            os.makedirs(CACHE, exist_ok=True)
            download(url, p)
        except Exception as e:  # noqa: BLE001
            print(f'nfl breakout: no {name} ({e})')
    return p if os.path.exists(p) and os.path.getsize(p) > 1000 else None


def load_players(fresh=False):
    info, pfr = {}, {}
    p = get('players.csv', f'{REL}/players/players.csv', fresh)
    for r in (csv.DictReader(open(p, newline='', encoding='utf-8')) if p else ()):
        g = r['gsis_id']
        if not g:
            continue
        info[g] = {'n': r['display_name'], 'birth': r['birth_date'], 'ht': num(r['height']), 'wt': num(r['weight']),
                   'pick': int(num(r['draft_pick'])), 'rookie': int(num(r['rookie_season'])), 'img': r['headshot'],
                   'otc': r.get('otc_id') or '', 'team': r.get('latest_team') or '', 'last': int(num(r.get('last_season')))}
        if r['pfr_id']:
            pfr[r['pfr_id']] = g
    return info, pfr


def age_on(birth, y):
    try:
        b = dt.date.fromisoformat(birth)
    except (TypeError, ValueError):
        return None
    return (dt.date(y, 9, 1) - b).days / 365.25


def agg(games):
    """one stat line from a list of a player's games"""
    o = {k: sum(g[k] for g in games) for k in SUM}
    o['g'] = len(games)
    sn = [g['snap'] for g in games if g['snap'] is not None]
    o['snap'] = sum(sn) / len(sn) if sn else None
    return o


def finish(o, pos):
    """workload, efficiency and profile rates on an aggregated line"""
    rb = pos == 'RB'
    o['n'] = o['ca'] + o['tg'] if rb else o['tg']
    den = o['tca'] + o['ttg'] if rb else o['ttg']
    o['u'] = 100.0 * o['n'] / den if den else 0.0
    o['x'] = ((o['ry'] + o['wy']) if rb else o['wy']) / o['n'] if o['n'] else XMEAN[pos]
    o['vol'] = den / o['g'] if o['g'] else 0.0                     # the team's targets (RB: plays) a game
    o['adot'] = o['ay'] / o['tg'] if o['tg'] else 0.0
    o['rcv'] = o['tg'] / (o['ca'] + o['tg']) if o['ca'] + o['tg'] else 0.0
    o['yacs'] = min(1.5, max(0.0, o['yac'] / o['wy'])) if o['wy'] > 0 else 0.5
    o['cr'] = o['rc'] / o['tg'] if o['tg'] else 0.6
    o['ppg'] = o['ppr'] / o['g'] if o['g'] else 0.0
    return o


def load(first, last, info, pfr, fresh_last=False):
    """P[(gsis, season)] = season line (with 'games', in week order) for every WR, TE and RB, REG only"""
    P = {}
    for y in range(first, last + 1):
        cur = fresh_last and y == last
        sp = get(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv', cur)
        if not sp:
            continue
        tt = defaultdict(lambda: [0.0, 0.0])
        rows = defaultdict(list)
        for r in csv.DictReader(open(sp, newline='', encoding='utf-8')):
            if r['season_type'] != 'REG' or not r.get('game_id'):
                continue
            t = FRANCHISE.get(r['team'], r['team'])
            tg, ca = num(r['targets']), num(r['carries'])
            k = (r['game_id'], t)
            tt[k][0] += tg
            tt[k][1] += ca
            pos = r['position']
            if pos not in POS:
                continue
            rows[r['player_id']].append({
                'gid': r['game_id'], 'wk': int(r['week']), 'tm': t, 'pos': pos, 'tg': tg, 'ca': ca,
                'rc': num(r['receptions']), 'wy': num(r['receiving_yards']), 'ry': num(r['rushing_yards']),
                'ay': num(r['receiving_air_yards']), 'yac': num(r['receiving_yards_after_catch']),
                'wtd': num(r['receiving_tds']), 'rtd': num(r['rushing_tds']), 'ppr': num(r['fantasy_points_ppr']),
                'snap': None})
        snap = {}
        if y >= SNAP0:
            p = get(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv', cur)
            for r in (csv.DictReader(open(p, newline='', encoding='utf-8')) if p else ()):
                g = pfr.get(r['pfr_player_id'])
                if g and r['game_type'] == 'REG':
                    snap[(r['game_id'], g)] = num(r['offense_pct'])
        for pid, gs in rows.items():
            gs.sort(key=lambda g: g['wk'])
            for g in gs:
                g['ttg'], g['tca'] = tt[(g['gid'], g['tm'])]
                g['snap'] = snap.get((g['gid'], pid))
            pos = gs[-1]['pos']
            o = finish(agg(gs), pos)
            tms = defaultdict(int)
            for g in gs:
                tms[g['tm']] += 1
            i = info.get(pid) or {}
            o.update({'pid': pid, 'y': y, 'pos': pos, 'tm': gs[-1]['tm'], 'tm0': max(tms, key=tms.get), 'games': gs,
                      'age': age_on(i.get('birth'), y), 'exp': max(0, y - i['rookie']) if i.get('rookie') else 3,
                      'pick': i.get('pick') or NOPICK, 'ht': i.get('ht') or 0.0, 'wt': i.get('wt') or 0.0})
            if o['age'] is None:
                o['age'] = 23.0 + o['exp']
            P[(pid, y)] = o
    return P


def part(o, games):
    """a slice of a season (a half, the last five games) as its own line"""
    s = finish(agg(games), o['pos'])
    for k in ('pid', 'y', 'pos', 'tm', 'age', 'exp', 'pick', 'ht', 'wt'):
        s[k] = o[k]
    return s


def history(P, pid, y):
    """the player's seasons before y, oldest first (three back)"""
    return [P[(pid, s)] for s in range(y - 3, y) if (pid, s) in P]


# ---------- workload scaling ----------
BASE = ['x0', 'x0*r0', 'r0', 'age', 'age2', 'u0', 'xprev', 'hasprev', 'half', 'half*x0']
BLOCKS = {
    'role': ['adot', 'rcv', 'snap'],
    'frame': ['ht', 'bmi'],
    'profile': ['yacs', 'cr'],
    'past usage history': ['own', 'xprevc'],
    'age': ['agec'],
    'low-volume rates': ['x0c', 'x0c_lowu'],
    'draft capital': ['lnpick', 'lnpick_early'],
}
MINN = {'WR': 20, 'TE': 15, 'RB': 30}               # opportunities for a line to count (pairs, history)


def columns():
    return BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in tr], []) for tr in BLOCKS.values()], [])


def own_slope(hist, a):
    """the player's own workload -> efficiency slope across his seasons, shrunk toward 0"""
    h = [o for o in hist + [a] if o['n'] >= MINN[a['pos']]]
    if len(h) < 2:
        return 0.0
    W = [o['n'] / 100.0 for o in h]
    sw = sum(W)
    mu = sum(w * o['u'] for w, o in zip(W, h)) / sw
    mx = sum(w * o['x'] for w, o in zip(W, h)) / sw
    sxy = sum(w * (o['u'] - mu) * (o['x'] - mx) for w, o in zip(W, h))
    sxx = sum(w * (o['u'] - mu) ** 2 for w, o in zip(W, h))
    return sxy / (sxx + 30.0)


def frame(a):
    pos = a['pos']
    ht = a['ht'] or {'WR': 73, 'TE': 77, 'RB': 71}[pos]
    wt = a['wt'] or {'WR': 200, 'TE': 250, 'RB': 215}[pos]
    return ht, 703.0 * wt / ht ** 2


def features(a, hist, dU, half=0.0):
    pos = a['pos']
    x0, r0, age = a['x'], a['n'] / (a['n'] + KREL[pos]), a['age']
    prev = [o for o in hist if o['n'] >= MINN[pos]]
    xprev = prev[-1]['x'] if prev else x0
    lowu = max(0.0, UREF[pos] - a['u']) / 10.0
    ht, bmi = frame(a)
    lp = math.log(a['pick'])
    v = {'x0': x0, 'x0*r0': x0 * r0, 'r0': r0, 'age': age, 'age2': age * age, 'u0': a['u'], 'xprev': xprev,
         'hasprev': 1.0 if prev else 0.0, 'half': half, 'half*x0': half * x0, 'dU': dU,
         'adot': a['adot'], 'rcv': a['rcv'], 'snap': a['snap'] if a['snap'] is not None else SNAPMEAN[pos],
         'ht': ht, 'bmi': bmi, 'yacs': a['yacs'], 'cr': a['cr'], 'own': own_slope(hist, a), 'xprevc': xprev - x0,
         'agec': age - 26, 'x0c': (x0 - XMEAN[pos]) * r0, 'x0c_lowu': (x0 - XMEAN[pos]) * r0 * lowu,
         'lnpick': lp, 'lnpick_early': lp * (a['exp'] <= 2)}
    for tr in BLOCKS.values():
        for k in tr:
            v['dU*' + k] = dU * v[k]
    return [v[c] for c in columns()]


def predict(fit, a, hist, dU):
    """next-season efficiency at dU more share points: the held-out-tested rate model (sample shrink, age, last
    season) at his own share, plus the share's own effect on efficiency. That effect is the slope from share changes
    forced by teammates leaving the lineup (research: causal()), used only when it clears t 2; the raw slope on a
    share change is selection (players who get better earn the work) and is never used here."""
    sc = fit['scaling'][a['pos']]
    f = sc['tier_fit']
    x = dict(zip(columns(), features(a, hist, 0.0)))
    return f['b0'] + sum(b * x[c] for b, c in zip(f['b'], f['cols'])) + sc['causal']['use'] * dU


# ---------- breakout odds ----------
# the quality bar L: PPR points a game of a clearly good player with a real role, the 79th (RB, WR) and 81st (TE)
# percentile of 2010-25 seasons with 8+ games and 60+ / 40+ / 25+ opportunities, shrunk as below (also the fantasy
# starter line, scripts/nfl_fantasy.py BO_LINE)
LINE = {'RB': 12.0, 'WR': 12.0, 'TE': 9.0}
REP = {'RB': 4.0, 'WR': 4.0, 'TE': 2.5}             # a depth player's PPR points a game
K_SHR, G_NEXT = 4.0, 8
CAREER = 14                                         # seasons back that count as his career to date
BO_MIN_G, BO_MIN_N = 4, 15
BO_CANDS = ('age curve', 'experience and draft', 'low-volume efficiency', 'old room', 'TD luck', 'projection gap',
            'role trend', 'snap role', 'workload scaling', 'vacated work')
LIVE_OFF = ('vacated work',)                        # needs next season's rosters: tested, never served
BO_LABEL = {'age curve': 'age', 'experience and draft': 'draft', 'low-volume efficiency': 'low-vol eff',
            'old room': 'old room', 'TD luck': 'TD luck', 'projection gap': 'proj gap', 'role trend': 'role up',
            'snap role': 'snaps', 'workload scaling': 'scales', 'vacated work': 'open work'}


def eligible(P, a):
    """not broken out yet: under the bar (shrunk) this season and in every season before it, real role or not"""
    ln = LINE[a['pos']]
    return shr(a) < ln and not any(shr(o) >= ln for o in (P.get((a['pid'], s)) for s in range(a['y'] - CAREER, a['y'])) if o)


def broke_out(a, b):
    """b = the next season: at or over the bar (shrunk) with a real role"""
    return bool(b and b['g'] >= G_NEXT and shr(b) >= LINE[a['pos']])


def best(P, a):
    """his best shrunk PPR points a game so far, this season included"""
    return max(shr(o) for o in (P.get((a['pid'], s)) for s in range(a['y'] - CAREER, a['y'] + 1)) if o)


def shr(a):
    return (a['ppr'] + REP[a['pos']] * K_SHR) / (a['g'] + K_SHR)


def marcel(hist, a):
    """3-season PPR points a game, weights 5/4/3 by games, shrunk to a depth player's with 6 games"""
    num_ = den = 0.0
    for o in hist + [a]:
        w = {0: 5, 1: 4, 2: 3}.get(a['y'] - o['y'])
        if w:
            num_ += w * o['ppr']
            den += w * o['g']
    return (num_ + REP[a['pos']] * 30) / (den + 30)


def xtd(fit, a):
    c = fit['xtd'][a['pos']]
    return c[0] * a['tg'] + c[1] * a['wy'] + c[2] * a['ca'] + c[3] * a['ry']


def room(P, y):
    """per player: share of his team's position-group opportunities held by teammates 28 or older (RB 27),
    and (research only) by teammates not on the team next season"""
    grp = defaultdict(list)
    for (pid, s), o in P.items():
        if s == y:
            grp[(o['tm'], 'RB' if o['pos'] == 'RB' else 'REC')].append(o)
    old, vac = {}, {}
    for (tm, g), L in grp.items():
        tot = sum(o['n'] for o in L) or 1.0
        for o in L:
            cut = 27 if g == 'RB' else 28
            old[o['pid']] = sum(q['n'] for q in L if q is not o and q['age'] >= cut) / tot
            gone = 0.0
            for q in L:
                nx = P.get((q['pid'], y + 1))
                if q is not o and (nx is None or nx['tm0'] != tm):
                    gone += q['n']
            vac[o['pid']] = gone / tot
    return old, vac


def bo_feats(fit, a, hist, old, vac):
    pos = a['pos']
    s0 = shr(a)
    r0 = a['n'] / (a['n'] + KREL[pos])
    xs = (a['x'] - XMEAN[pos]) * r0
    lowu = max(0.0, UREF[pos] - a['u']) / 10.0
    rb, te = float(pos == 'RB'), float(pos == 'TE')
    last = part(a, a['games'][-5:])
    snap = a['snap'] if a['snap'] is not None else SNAPMEAN[pos]
    lsnap = last['snap'] if last['snap'] is not None else snap
    lp = math.log(a['pick'])
    age = a['age']
    ht, bmi = frame(a)
    return {'base': [s0, math.log(a['n']), rb, te, s0 * rb, s0 * te, a['u'] / UREF[pos]],
            'age curve': [age, age * age, age * s0],
            'experience and draft': [float(a['exp'] == 0), float(a['exp'] == 1), lp * (a['exp'] <= 2), lp],
            'low-volume efficiency': [xs * lowu, xs],
            'old room': [old],
            'TD luck': [(a['wtd'] + a['rtd'] - xtd(fit, a)) / a['g']],
            'projection gap': [marcel(hist, a) - s0],
            'role trend': [(last['u'] - a['u']) / UREF[pos], lsnap - snap],
            'snap role': [snap, snap * lowu],
            'workload scaling': [a['adot'] * lowu * (1 - rb), a['rcv'] * lowu * rb, a['yacs'] * lowu],
            'vacated work': [vac]}


# ---------- improvement sweep signals (prereg: project files next-up/prereg-nfl.md) ----------
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
SWEEP = ('draft development curve', 'position age curves', 'draft round steps', 'depth chart', 'depth contracts',
         'opportunity model', 'new head coach next season', 'head coach year one', 'QB change next season',
         'offense environment', 'in-season trend', 'snap trend', 'peak window', 'targets per snap')
SWEEP_RO = ('new head coach next season', 'QB change next season')      # next season's facts: never served in-season
SWEEP_LABEL = {'draft development curve': 'dev curve', 'position age curves': 'age', 'draft round steps': 'draft',
               'depth chart': 'depth', 'depth contracts': 'room opens', 'opportunity model': 'role ahead',
               'head coach year one': 'new coach', 'offense environment': 'offense', 'in-season trend': 'trending',
               'snap trend': 'snaps up', 'peak window': 'peak games', 'targets per snap': 'demand'}
TPS_MEAN = {'WR': 0.25, 'TE': 0.23, 'RB': 0.47}     # opportunities per snap-share of the team's, league mean


def team_context(fresh=False):
    """(team, season) -> head coach of the first and last game, most frequent starting QB and the share of games
    someone else started (nfldata games.csv, REG)"""
    p = get('games.csv', GAMES, fresh)
    T = defaultdict(list)
    for g in (csv.DictReader(open(p, newline='', encoding='utf-8')) if p else ()):
        if g['game_type'] != 'REG':
            continue
        done = g['home_score'] not in ('', 'NA')
        for side in ('home', 'away'):
            t = FRANCHISE.get(g[side + '_team'], g[side + '_team'])
            T[(t, int(g['season']))].append((int(g['week']), g[side + '_coach'], g[side + '_qb_id'] if done else ''))
    C = {}
    for k, L in T.items():
        L.sort()
        qb = defaultdict(int)
        for _, _, q in L:
            if q:
                qb[q] += 1
        played = [x for x in L if x[2]]
        main = max(qb, key=qb.get) if qb else ''
        C[k] = {'hc0': L[0][1], 'hc1': (played or L)[-1][1], 'qb': main,
                'qb_other': 1 - qb[main] / len(played) if played else 0.0}
    return C


def load_contracts(info, fresh=False):
    """gsis -> [(year signed, last season covered)] from OverTheCap history (nflverse contracts)"""
    p = get('historical_contracts.csv.gz', f'{REL}/contracts/historical_contracts.csv.gz', fresh)
    otc = {i['otc']: g for g, i in info.items() if i.get('otc')}
    K = defaultdict(list)
    if p:
        with gzip.open(p, 'rt', encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                g = otc.get(r['otc_id'])
                ys, n = int(num(r['year_signed'])), int(num(r['years']))
                if g and ys and n:
                    K[g].append((ys, ys + n - 1))
    return K


def expiring(K, pid, y):
    c = [k for k in K.get(pid, ()) if k[0] <= y]
    return bool(c) and max(c)[1] == y


def depth(P, y, K):
    """per player: depth rank in his team's group (RB; WR + TE) by opportunities a game, and what those ahead hold"""
    grp = defaultdict(list)
    for (pid, s), o in P.items():
        if s == y:
            grp[(o['tm'], o['pos'] == 'RB')].append(o)
    D = {}
    for (tm, rb), L in grp.items():
        tot = sum(o['n'] for o in L) or 1.0
        for o in L:
            ah = [q for q in L if q is not o and q['g'] >= 4 and q['n'] / q['g'] > o['n'] / o['g']]
            n = sum(q['n'] for q in ah)
            D[o['pid']] = {'rank': min(4, 1 + len(ah)), 'ahead': n / tot,
                           'ahead_age': n / tot * (sum(q['n'] * q['age'] for q in ah) / n - 27) if n else 0.0,
                           'ahead_exp': sum(q['n'] for q in ah if expiring(K, q['pid'], y)) / tot,
                           'ahead_old': sum(q['n'] for q in ah if q['age'] >= (28 if rb else 30)) / tot}
    return D


def offense(P, y):
    """team -> receiving yards a target and (RB) rushing yards a carry against the league that season"""
    T = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for (pid, s), o in P.items():
        if s == y:
            rb = o['pos'] == 'RB'
            for g in o['games']:
                t = T[g['tm']]
                t[0] += g['wy']
                t[1] += g['tg']
                t[2] += g['ry'] * rb
                t[3] += g['ca'] * rb
    lw = sum(t[0] for t in T.values()) / (sum(t[1] for t in T.values()) or 1)
    lr = sum(t[2] for t in T.values()) / (sum(t[3] for t in T.values()) or 1)
    return {tm: (t[0] / t[1] - lw if t[1] else 0.0, t[2] / t[3] - lr if t[3] else 0.0) for tm, t in T.items()}


def op_row(a, d):
    """inputs of the opportunity model (next-season share from the depth chart)"""
    pos = a['pos']
    snap = a['snap'] if a['snap'] is not None else SNAPMEAN[pos]
    return [a['u'] / UREF[pos], snap, d['rank'], d['ahead'], d['ahead_age'], a['age'], math.log(a['pick']),
            min(a['exp'], 4), part(a, a['games'][-5:])['u'] / UREF[pos], float(pos == 'RB'), float(pos == 'TE')]


def sweep_feats(a, d, C, off, op=None):
    """the prereg's A-tests; op = (b0, b) of the opportunity model when one is fit"""
    pos, y, tm = a['pos'], a['y'], a['tm']
    rb, te = float(pos == 'RB'), float(pos == 'TE')
    agec, lp, e4, early = a['age'] - 26, math.log(a['pick']), min(a['exp'], 4), float(a['exp'] <= 2)
    r1, r23 = float(a['pick'] <= 32), float(32 < a['pick'] <= 100)
    c0, c1, cp = C.get((tm, y)) or {}, C.get((tm, y + 1)) or {}, C.get((tm, y - 1)) or {}
    G = a['games']
    h = len(G) // 2
    trend = [0.0, 0.0, 0.0]
    if len(G) >= 4:
        f1, f2 = part(a, G[:h]), part(a, G[h:])
        sn = (f2['snap'] - f1['snap']) if f1['snap'] is not None and f2['snap'] is not None else 0.0
        trend = [f2['ppg'] - f1['ppg'], (f2['u'] - f1['u']) / UREF[pos], sn]
    sv = [g['snap'] for g in G]
    st = [0.0, 0.0]
    if a['snap'] is not None and all(v is not None for v in sv):
        if len(G) >= 6:
            st[0] = sum(sv[-4:]) / 4 - sum(sv[:4]) / 4
        if len(G) >= 3:
            st[1] = max(sum(sv[i:i + 3]) / 3 for i in range(len(G) - 2)) - a['snap']
    pk = max(sum(g['ppr'] for g in G[i:i + 3]) / 3 for i in range(len(G) - 2)) if len(G) >= 3 else a['ppg']
    tps = [0.0, 0.0]
    if a['snap']:
        den = sum((g['snap'] or 0.0) * ((g['tca'] + g['ttg']) if rb else g['ttg']) for g in G)
        if den > 0:
            v = (a['n'] / den * a['n'] + TPS_MEAN[pos] * 100) / (a['n'] + 100) - TPS_MEAN[pos]
            tps = [v, v * max(0.0, UREF[pos] - a['u']) / 10.0]
    o = off.get(tm, (0.0, 0.0))
    F = {'draft development curve': [agec * lp, e4, e4 * lp],
         'position age curves': [agec * rb, agec * te, agec * agec * rb, agec * agec * te],
         'draft round steps': [r1, r23, r1 * early, r23 * early],
         'depth chart': [d['rank'], d['ahead'], d['ahead_age']],
         'depth contracts': [d['ahead_exp'], d['ahead_old']],
         'new head coach next season': [float(bool(c1) and bool(c0) and c1['hc0'] != c0['hc1'])],
         'head coach year one': [float(bool(cp) and bool(c0) and cp['hc1'] != c0['hc1'])],
         'QB change next season': [float(bool(c1.get('qb')) and bool(c0.get('qb')) and c1['qb'] != c0['qb'])],
         'offense environment': [o[1] if rb else o[0], c0.get('qb_other', 0.0)],
         'in-season trend': trend, 'snap trend': st,
         'peak window': [pk / LINE[pos], float(sum(g['ppr'] >= 1.5 * LINE[pos] for g in G))],
         'targets per snap': tps}
    if op:
        x = op_row(a, d)
        u1 = op[0] + sum(b * v for b, v in zip(op[1], x))
        F['opportunity model'] = [u1 / UREF[pos], u1 / UREF[pos] - a['u'] / UREF[pos]]
    return F


# ---------- live board ----------
def build():
    fit = json.load(open(FIT))
    info, pfr = load_players(True)
    y = dt.date.today().year - (dt.date.today().month < 8)
    P = load(y - CAREER, y, info, pfr, fresh_last=True)
    if not any(s == y for _, s in P):
        y -= 1
    week = max(g['wk'] for (pid, s), o in P.items() if s == y for g in o['games'])
    old, _ = room(P, y)
    bo = fit['breakout']
    keep = [k for k in bo['keep'] if k not in LIVE_OFF]
    b0, b, mu = bo['fit']['b0'], bo['fit']['b'], bo['fit']['mu']
    du99 = {p: fit['scaling'][p]['du99'] for p in POS}
    live = {p: 'tier_fit' in fit['scaling'][p] for p in POS}
    rows = []
    for (pid, s), a in P.items():
        if s != y or a['g'] < BO_MIN_G or a['n'] < BO_MIN_N or not eligible(P, a):
            continue
        i = info.get(pid) or {}
        if i.get('last') and i['last'] < y:
            continue
        hist = history(P, pid, y)
        f = bo_feats(fit, a, hist, old.get(pid, 0.0), 0.0)
        x = f['base'] + sum([f[k] for k in keep], [])
        z = b0 + sum(bi * xi for bi, xi in zip(b, x))
        p = 1 / (1 + math.exp(-max(-30, min(30, z))))
        j = len(f['base'])
        push = []
        for k in keep:
            n = len(f[k])
            push.append((sum(b[j + q] * (x[j + q] - mu[j + q]) for q in range(n)), k))
            j += n
        push.sort(reverse=True)
        t = []
        for d in TIERS:
            if not live[a['pos']]:
                t.append(None)
                continue
            e = max(1.0, predict(fit, a, hist, d))
            t.append([round(e * (a['u'] + d) / 100.0 * a['vol'], 1), round(e, 2), int(d > du99[a['pos']] or a['u'] + d > UMAX[a['pos']])])
        img = i.get('img') or ''
        lo = f"/img/nfl/{a['tm'].lower()}.png"
        cur = age_on(i.get('birth'), y)
        rows.append({'id': pid, 'n': i.get('n') or pid, 'tm': a['tm'], 'pos': a['pos'],
                     'age': round(cur + (dt.date.today() - dt.date(y, 9, 1)).days / 365.25, 1) if cur else None,
                     'ph': img.replace('/f_auto,q_auto/', '/f_auto,q_auto,w_96/') if img.startswith('https://') else None,
                     'lo': lo if os.path.exists(os.path.join(ROOT, 'static', lo.lstrip('/'))) else None,
                     'p': round(p, 3), 'best': round(best(P, a), 1), 'u': round(a['u'], 1), 't': t,
                     'sig': [BO_LABEL[k] for v, k in push[:2] if v > 0.1]})
    rows.sort(key=lambda r: -r['p'])
    fin = bo['final']
    sw = fit.get('sweep') or {}
    sw = (f"; {len(sw['tests'])} more pre-registered signals, model forms and recalibrations tested, "
          f"{sum(t['pass'] for t in sw['tests'].values())} passed") if sw else ''
    sl = '; '.join(f"{p} {fit['scaling'][p]['causal']['use']:+.3f} (measured {fit['scaling'][p]['causal']['iv']:+.3f}, "
                   f"t {fit['scaling'][p]['causal']['t']})" for p in POS)
    about = (f"WR, TE, RB who have not broken out: no season so far, this one included, at the bar L = RB/WR "
             f"{LINE['WR']:g}, TE {LINE['TE']:g} PPR points a game shrunk to a depth player's by {K_SHR:g} games (L is the "
             f"{bo['L_pct']} of seasons with a real role); anyone at or over L is left out. QB, OL and defense are not "
             f"scaled. breakout: next season at or over L with {G_NEXT}+ games, for the first time; base {y} through week "
             f"{week}; odds "
             f"= logistic on shrunk PPR/G, ln opportunities, position, share + {', '.join(keep)} (each passes "
             f"leave-one-season-out {bo['seasons']}, final t {fin['t']}, {fin['won']}/{fin['seasons']} seasons{sw}). SHARE: WR/TE "
             f"share of team targets, RB share of team carries + targets. tiers: that many share points more; Y/OPP = "
             f"next-season yards per target (RB: per carry or target) from his rate shrunk for sample, age and last season, "
             f"plus yards per opportunity per added share point where teammates leaving the lineup forced the change: {sl}; "
             f"used when |t| >= 2. YDS/G = Y/OPP x share x the team's targets (RB: carries + targets) a game; tiers past "
             f"the 99th percentile of observed jumps or the largest share on record are beyond the data")
    out = {'sport': 'nfl', 'season': str(y), 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'base': f'{y} wk {week}', 'u': {'lab': 'SHARE', 'dec': 1},
           'tiers': [{'k': d, 'lab': f'+{d:g}'} for d in TIERS] if any(live.values()) else [],
           'stat': {'lab': 'YDS/G', 'eff': 'Y/OPP', 'dec': 1, 'edec': 2}, 'about': about, 'rows': rows[:400]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('nfl breakout:', len(out['rows']), 'rows, base', out['base'], '->', OUT)


if __name__ == '__main__':
    build()
