#!/usr/bin/env python3
"""NBA game projections for the NBA ARKBOARD (data/nba_games.json), and the model behind them (data/nba_games_fit.json).

    python3 scripts/nba_games.py           # today's and tomorrow's projections, power rankings, season odds, picks (stdlib)
    python3 scripts/nba_games.py --hist    # freeze past seasons into scripts/nba_games_hist.json.gz (from the ESPN cache)
    python3 scripts/nba_games.py --fit     # walk-forward backtest 2015-2026 against the closing line, refit (numpy)
    python3 scripts/nba_games.py --draft   # add new NBA drafts to scripts/nba_draft.json (Basketball-Reference)

Data: ESPN (scores, box-score minutes, team counting stats, every listed book's spread, total and moneyline, the
injury report and rosters; scripts/nba_espn.py), the NBA's official injury reports 2019-20 on (scripts/nba_inj_hist.py,
for play chances by status), and the board's XPM (static/data/nba-xpm, scripts/nba_xpm.py) for player value. Every
input is known before tip.

Margin (home minus away, points) is a linear model on:
    elo     Elo difference in points (538's NBA Elo: K tuned, autocorrelation-corrected margin multiplier, 1/4 back
            to the mean each offseason)
    eff     net points per 100 possessions, opponent- and home-adjusted, exponentially weighted with a half-life in
            games and carried across seasons at a fraction, times the matchup's expected pace. Each opponent counts
            at the strength of the lineup it played that night (lk_opp; Elo the same)
    mkt     market rating: each team's points against an average team as earlier closing spreads priced it (never the
            game's own line), each spread net of half that game's expected lineup term (lk_mkt: the close already
            prices the night's injuries, so they don't move the team's rating)
    lin     lineup: tonight's expected lineup value against the lineups the ratings were built on. A player's value is
            his XPM from the two seasons before (minutes-weighted, shrunk toward a newcomer's level); tonight's
            minutes are his recent minutes when he plays x his chance to play (by injury status and the games he
            has missed in a row, measured on 2019-20 to 2025-26 reports), filled to 240 at replacement level; the
            baseline is the same value of the minutes actually played, weighted like the ratings
            Rookies drafted last summer count from opening night at their draft slot's rookie XPM and minutes
            (a + b ln(pick), fit on earlier drafts), until their own minutes take over
    roster  tonight's lineup value itself, home minus away (with rookies in, it earns its place)
    rest    days of rest (0-3) and back-to-backs, home minus away
    home    1 at a home arena, 0 neutral (the 2020 bubble, NBA Cup finals, international games)
Candidate inputs enter only when they cut walk-forward error on 2015-21 at t <= -1.5 and 2022-26 agrees (see fit()).
Total: expected pace x both offenses against both defenses, from the total's own copies of the pace and efficiency
ratings on a much shorter half-life (thl, tuned on 2015-21 totals), a market total rating from earlier closing
totals, and last season's market total rating (tpri: each team's final gap to the league's closing totals, a quarter
of it also carried into this season's rating, fading slowly as the team plays), weighted by regression. scripts/nba_games_research.py has what else was tried.
Win probability and cover chances: normal around the margin, with the sd fit to results.
"""
import datetime as dt
import gzip
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_espn as E
import names as NM

ROOT = os.path.dirname(HERE)
HIST = os.path.join(HERE, 'nba_games_hist.json.gz')     # outside data/: Hugo would load it on every build
FIT = os.path.join(ROOT, 'data', 'nba_games_fit.json')
OUT = os.path.join(ROOT, 'data', 'nba_games.json')
XPM = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
INJ_HIST = os.path.join(ROOT, 'scripts', '.cache', 'nba', 'inj_hist.json')
FIRST = 2013                      # 2012-13: XPM from 2010-11 on; ratings warm up two seasons before scoring
SCORE_FROM, HOLD_FROM = 2015, 2022
FEATS = ['elo', 'eff', 'mkt', 'lin', 'rest', 'b2b', 'home']
TFEATS = ['pts', 'tmkt', 'po', 'one', 'tpri', 'tlin']
NOT_BOOKS = ('Live',)             # in-game prices
REPL = -1.4                       # replacement-level XPM (VORX's, fit to NBA wins)

# arenas: latitude, longitude, Eastern offset hours, altitude m
ARENA = {'ATL': (33.757, -84.396, 0, 320), 'BOS': (42.366, -71.062, 0, 6), 'BKN': (40.683, -73.976, 0, 10),
         'CHA': (35.225, -80.839, 0, 230), 'CHI': (41.881, -87.674, -1, 180), 'CLE': (41.496, -81.688, 0, 200),
         'DAL': (32.790, -96.810, -1, 140), 'DEN': (39.749, -105.008, -2, 1609), 'DET': (42.341, -83.055, 0, 190),
         'GS': (37.768, -122.388, -3, 5), 'HOU': (29.751, -95.362, -1, 15), 'IND': (39.764, -86.156, 0, 220),
         'LAC': (33.945, -118.341, -3, 30), 'LAL': (34.043, -118.267, -3, 90), 'MEM': (35.138, -90.051, -1, 80),
         'MIA': (25.781, -80.188, 0, 2), 'MIL': (43.045, -87.917, -1, 190), 'MIN': (44.980, -93.276, -1, 260),
         'NO': (29.949, -90.082, -1, 2), 'NY': (40.751, -73.994, 0, 10), 'OKC': (35.463, -97.515, -1, 370),
         'ORL': (28.539, -81.384, 0, 30), 'PHI': (39.901, -75.172, 0, 10), 'PHX': (33.446, -112.071, -2, 340),
         'POR': (45.532, -122.667, -3, 15), 'SAC': (38.580, -121.500, -3, 9), 'SA': (29.427, -98.438, -1, 200),
         'TOR': (43.643, -79.379, 0, 80), 'UTAH': (40.768, -111.901, -2, 1288), 'WSH': (38.898, -77.021, 0, 20)}


def median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def lines(o):
    """consensus close: the median book. L = the home side's expected margin (ESPN's spread is the home handicap)."""
    if not o:
        return {}
    bk = [b for b in o if b.get('book') and not any(s in b['book'] for s in NOT_BOOKS) and b['book'] != 'Opening']
    sp = median([b['spread'] for b in bk if b.get('spread') is not None])
    op = [b for b in o if b.get('book') == 'Opening' and b.get('spread') is not None]
    opn = op[0]['spread'] if op else median([b['open']['spread'] for b in bk if b.get('open') and b['open'].get('spread') is not None])
    tot = median([b['total'] for b in bk if b.get('total')])
    ok = [b for b in bk if b.get('mlH') and b.get('mlA') and abs(b['mlH']) >= 100 and abs(b['mlA']) >= 100 and
          (sp is None or sp == 0 or (b['mlH'] < 0) == (sp < 0))]
    mlh, mla = median([b['mlH'] for b in ok]), median([b['mlA'] for b in ok])
    so = [b for b in bk if b.get('oH') and b.get('oA') and abs(b['oH']) >= 100]
    return {'L': None if sp is None else -sp, 'Lo': None if opn is None else -opn, 'T': tot,
            'mlH': mlh, 'mlA': mla, 'oH': median([b['oH'] for b in so]), 'oA': median([b['oA'] for b in so])}


def compact(g, b, o):
    """one game for the model: teams, scores, possessions, lines, minutes by player"""
    tip = g['tip'] if len(g['tip']) > 17 else g['tip'][:-1] + ':00Z'      # ESPN drops the seconds
    r = {'id': g['id'], 'tip': tip, 'S': g['season'], 't': g['type'], 'n': 1 if g['neutral'] else 0,
         'h': g['h'], 'a': g['a'], 'hs': g['hs'], 'as': g['as'], 'fin': 1 if g['final'] else 0}
    r.update(lines(o))
    if b:
        ps = []
        for t in (g['h'], g['a']):
            x = b['teams'].get(t) or {}
            try:
                ps.append(x['fg'][1] - x['oreb'] + x['tov'] + 0.44 * x['ft'][1])
            except (KeyError, TypeError):
                pass
        r['poss'] = round(sum(ps) / len(ps), 1) if len(ps) == 2 else None
        # team shooting (3PM, 3PA, FTM, FTA) for the luck-stripped efficiency ratings
        sh = {t: (b['teams'].get(t) or {}) for t in (g['h'], g['a'])}
        if all(x.get('fg3') and x.get('ft') for x in sh.values()):
            r['sh'] = {t: [*x['fg3'], *x['ft']] for t, x in sh.items()}
        # ESPN lost the player lines of some older games (every player 'coach's decision'): no lineup for those
        r['pl'] = {t: [[p[0], p[2]] for p in b['players'].get(t, []) if p[0]] for t in (g['h'], g['a'])
                   if sum(p[2] for p in b['players'].get(t, [])) > 150}
        r['nm'] = {p[0]: p[1] for t in (g['h'], g['a']) for p in b['players'].get(t, []) if p[0]}
    return r


def season_games(S, live=False):
    """compact games of season S from ESPN (cache first; live: today's slate and lines refetched)"""
    fresh = dt.date.today() - dt.timedelta(days=2) if live else None
    gs = E.games(S, fresh_after=fresh)
    det = E.details(gs)
    return [compact(g, *det[g['id']]) for g in gs]


def write_hist(lo, hi):
    out, names = [], {}
    for S in range(lo, hi + 1):
        for r in season_games(S):
            if not r['fin']:
                continue
            names.update(r.pop('nm', {}))
            out.append(r)
        print(S, sum(1 for r in out if r['S'] == S), 'games', flush=True)
    with gzip.open(HIST, 'wt') as f:
        json.dump({'games': out, 'names': names}, f, separators=(',', ':'))


def load_hist():
    with gzip.open(HIST, 'rt') as f:
        d = json.load(f)
    return d['games'], d['names']


# ---------------------------------------------------------------- player value
def norm(n):
    """a player's name key, shared by every sport (scripts/names.py): accents, punctuation, suffixes, aliases"""
    return NM.key(n)


_XP = {}


def xpm_season(S):
    """the board's file for season S: {name key: (xpm, minutes, first team)} (the most minutes on a name clash) and a
    matcher over the same rows for spellings that differ (Rondae Hollis Jefferson / Hollis-Jefferson, Omer Asik)"""
    if S not in _XP:
        fn = os.path.join(XPM, f'{S}.json')
        d, rows = {}, []
        if os.path.exists(fn):
            for p in json.load(open(fn))['players']:
                if p.get('xpm') is None or p.get('pr'):      # a prior stands in on the board until BPM exists
                    continue
                v = (p['xpm'], p['mp'], E.team(p['tm'].split('/')[0]), p.get('age'))
                rows.append({'n': p['n'], 'v': v})
                k = norm(p['n'])
                if k not in d or d[k][1] < v[1]:
                    d[k] = v
        _XP[S] = (d, NM.Matcher(rows, name='n', team=None, pos=None, sport='basketball'))
    return _XP[S]


def lookup(S, name):
    d, m = xpm_season(S)
    v = d.get(norm(name))
    if v: return v
    r, _ = m.find(name)                 # a spelling that fits, only when one player in the file has it
    return r['v'] if r else None


RET_MIN, RET_HEALTHY = 1000, 1000    # a lost season: under 1,000 minutes last season, 1,000+ in one of the three before


def returner(h, rl=RET_MIN):
    """h: a player's (xpm, minutes, ..., age) rows for the four seasons before, latest first (None = no line). A returner
    (missed most of last season, a full one in the three before): (rows for the prior, seasons lost, his last healthy
    row); else None"""
    if (h[0] and h[0][1] >= rl) or not any(r and r[1] >= RET_HEALTHY for r in h[1:]):
        return None
    good = [(k, r) for k, r in enumerate(h) if r and r[1] >= rl]
    return ([(h[0], 1.0)] if h[0] else []) + [(r, w) for (_, r), w in zip(good[:2], (1.0, 0.5))], good[0][0], good[0][1]


def shrunk(rows, n0, rook):
    num, den = rook * n0, n0
    for r, w in rows:
        if r:
            num += r[0] * r[1] * w; den += r[1] * w
    return num / den, (den - n0) / den


def ret_value(h, n0, rook, cv, disc, rl=RET_MIN):
    """a returner's prior: his last two healthy seasons stand in for the two before (last season's few minutes on top),
    plus the aging curve over each season since his last healthy one, plus the return discount"""
    rows, gap, last = returner(h, rl)
    v, share = shrunk(rows, n0, rook)
    if cv and last[3]:
        v += sum(cv(last[3] + j) for j in range(1, gap + 1)) * share
    return v + disc


_RD = {}


def returner_disc(S, n0=600.0, rook=-1.0, rl=RET_MIN):
    """the return discount: returners' XPM minus their prior (ret_value without it), weighted by return-season
    minutes, over return seasons before S (scripts/nba_returners_research.py: -.25 for 2013-21, -.13 after)"""
    if (S, n0, rook, rl) not in _RD:
        F = {}

        def f(y):
            if y not in F:
                fn = os.path.join(XPM, f'{y}.json')
                F[y] = {p['id']: (p['xpm'], p['mp'], None, p.get('age')) for p in json.load(open(fn))['players']
                        if p.get('xpm') is not None and not p.get('pr')} if os.path.exists(fn) else {}
            return F[y]
        num = den = 0.0
        for s in range(2013, S):
            cv = aging_curve(s)
            for pid, p in f(s).items():
                if p[1] < 100:
                    continue
                h = [f(s - k).get(pid) for k in range(1, 5)]
                if returner(h, rl):
                    num += (p[0] - ret_value(h, n0, rook, cv, 0.0, rl)) * p[1]; den += p[1]
        _RD[S, n0, rook, rl] = num / den if den >= 20000 else 0.0
    return _RD[S, n0, rook, rl]


def values(S, names, n0=600.0, rook=-2.0, w2=0.5, age=0, ret=0):
    """each player's value for season S: XPM of the two seasons before, minutes-weighted (the older at w2), shrunk
    toward rook with n0 minutes; nobody known = rook. age: plus the aging curve's change at his age this season,
    scaled by how much of the prior is last season's own minutes (last-season minutes / (minutes + n0)).
    ret: a player back from a lost season (under ret minutes last season) at ret_value: his healthy seasons, aged,
    less the return discount"""
    cv = aging_curve(S) if age else None
    cr, disc = (aging_curve(S), returner_disc(S, n0, rook, ret)) if ret else (None, 0.0)
    out = {}
    for pid, nm in names.items():
        a, b = lookup(S - 1, nm), lookup(S - 2, nm)
        if ret and not (a and a[1] >= ret):
            h = [a, b, lookup(S - 3, nm), lookup(S - 4, nm)]
            if returner(h, ret):
                out[pid] = ret_value(h, n0, rook, cr, disc, ret)
                continue
        num = rook * n0; den = n0
        if a:
            num += a[0] * a[1]; den += a[1]
        if b:
            num += b[0] * b[1] * w2; den += b[1] * w2
        out[pid] = num / den
        if cv and a and a[3]:
            out[pid] += cv(a[3] + 1) * a[1] / (a[1] + n0)
    return out


_AA = {}


def arc_season(S):
    """LUMA ARC one-season board for season S (scripts/nba_arc.py): ({name key: (net, poss)}, matcher)"""
    if S not in _AA:
        import nba_arc
        rows = [{'n': r[0], 'v': (r[2], r[5])} for r in nba_arc.seasons().get(S, []) if r[2] is not None]
        d = {}
        for r in rows:
            k = norm(r['n'])
            if k not in d or d[k][1] < r['v'][1]:
                d[k] = r['v']
        _AA[S] = (d, NM.Matcher(rows, name='n', team=None, pos=None, sport='basketball'))
    return _AA[S]


def arc_lookup(S, name):
    d, m = arc_season(S)
    v = d.get(norm(name))
    if v: return v
    r, _ = m.find(name)
    return r['v'] if r else None


_LK = {}


def loki_season(S):
    """LUMA LOKI preseason (R1) projections for season S (research: scripts/.cache/nba/loki_r1.json, pulled from the
    LUMA API; the live season from the published release board): ({name key: net}, matcher)"""
    if S not in _LK:
        fn = os.path.join(ROOT, 'scripts', '.cache', 'nba', 'loki_r1.json')
        rows = [{'n': r['name'], 'v': r['net']} for r in (json.load(open(fn)).get(str(S), []) if os.path.exists(fn) else [])
                if r.get('net') is not None and r.get('name')]
        _LK[S] = ({norm(r['n']): r['v'] for r in rows}, NM.Matcher(rows, name='n', team=None, pos=None, sport='basketball'))
    return _LK[S]


def loki_blend(S, names, val, w, skip=()):
    """val with LOKI mixed in at weight w, put on the XPM prior's scale by matching the mean and sd of the players
    who have both (unweighted; no outcome in the map); players without a LOKI row keep val"""
    d, m = loki_season(S)
    lv = {}
    for pid, nm in names.items():
        if pid in skip or pid not in val:
            continue
        v = d.get(norm(nm))
        if v is None:
            r, _ = m.find(nm)
            v = r['v'] if r else None
        if v is not None:
            lv[pid] = v
    if len(lv) < 50:
        return val
    import statistics as st
    ks = list(lv)
    mx, sx = st.mean(lv[k] for k in ks), st.pstdev(lv[k] for k in ks)
    my, sy = st.mean(val[k] for k in ks), st.pstdev(val[k] for k in ks)
    out = dict(val)
    for k in ks:
        out[k] = (1 - w) * val[k] + w * (my + (lv[k] - mx) * sy / sx)
    return out


def arc_blend(S, names, val, w, n0=1250.0, rook=-1.5, skip=()):
    """val with ARC mixed in at weight w: the two seasons before (older at half weight), possession-weighted and
    shrunk toward rook with n0 possessions (~600 minutes), then put on the XPM prior's scale by matching the
    possession-weighted mean and sd of the players who have both (no outcome in the map). Players with no ARC
    line in either season, or in skip (returners), keep val."""
    av, wt = {}, {}
    for pid, nm in names.items():
        if pid in skip or pid not in val:
            continue
        a, b = arc_lookup(S - 1, nm), arc_lookup(S - 2, nm)
        if not a and not b:
            continue
        num, den = rook * n0, n0
        for r, k in ((a, 1.0), (b, 0.5)):
            if r:
                num += r[0] * r[1] * k; den += r[1] * k
        av[pid], wt[pid] = num / den, den - n0
    if len(av) < 50:
        return val
    ks = list(av)
    x = [av[k] for k in ks]; y = [val[k] for k in ks]; ww = [wt[k] for k in ks]
    W = sum(ww)
    mx = sum(a * b for a, b in zip(x, ww)) / W; my = sum(a * b for a, b in zip(y, ww)) / W
    sx = (sum((a - mx) ** 2 * b for a, b in zip(x, ww)) / W) ** 0.5
    sy = (sum((a - my) ** 2 * b for a, b in zip(y, ww)) / W) ** 0.5
    out = dict(val)
    for k in ks:
        out[k] = (1 - w) * val[k] + w * (my + (av[k] - mx) * sy / sx)
    return out


def od_values(S, names, src='xpm', n0=600.0, rook=(-0.5, -0.5)):
    """each player's offense and defense values for season S (two seasons before, older at half weight, shrunk to
    rook with n0 minutes): src 'xpm' = the board's oxpm/dxpm; 'arc' = LUMA ARC O/D (n0 x 2.08 possessions)"""
    rows = {}
    for k in (1, 2):
        if src == 'arc':
            import nba_arc
            d = {}
            for r in nba_arc.seasons().get(S - k, []):
                if r[3] is not None and (norm(r[0]) not in d or d[norm(r[0])][2] < r[5]):
                    d[norm(r[0])] = (r[3], r[4], r[5])
        else:
            fn = os.path.join(XPM, f'{S - k}.json')
            d = {}
            for p in (json.load(open(fn))['players'] if os.path.exists(fn) else []):
                if p.get('oxpm') is None or p.get('pr'):
                    continue
                if norm(p['n']) not in d or d[norm(p['n'])][2] < p['mp']:
                    d[norm(p['n'])] = (p['oxpm'], p['dxpm'], p['mp'])
        rows[k] = d
    nn = n0 * (2.08 if src == 'arc' else 1.0)
    vo, vd = {}, {}
    for pid, nm in names.items():
        key = norm(nm)
        no, nd, den = rook[0] * nn, rook[1] * nn, nn
        for k, w in ((1, 1.0), (2, 0.5)):
            r = rows[k].get(key)
            if r:
                no += r[0] * r[2] * w; nd += r[1] * r[2] * w; den += r[2] * w
        vo[pid], vd[pid] = no / den, nd / den
    return vo, vd


_AG = {}


def aging_curve(S):
    """XPM change from one season to the next by age (age in the later season), delta method: every player with
    minutes in both seasons, weighted by the harmonic mean of the two minutes, a quadratic in age (20-36, clipped),
    fit only on season pairs ending before S. Research: scripts/nba_prior_research.py"""
    if S in _AG:
        return _AG[S]
    xs, ds, ws = [], [], []
    for s in range(2011, S):
        a, b = (os.path.join(XPM, f'{y}.json') for y in (s - 1, s))
        if not (os.path.exists(a) and os.path.exists(b)):
            continue
        A = {p['id']: p for p in json.load(open(a))['players'] if p.get('xpm') is not None}
        for p in json.load(open(b))['players']:
            q = A.get(p['id'])
            if p.get('xpm') is not None and q and q.get('age') and q['mp'] > 0 and p['mp'] > 0:
                xs.append(min(max(q['age'] + 1, 20), 36) - 27); ds.append(p['xpm'] - q['xpm'])
                ws.append(2 / (1 / q['mp'] + 1 / p['mp']))
    if len(xs) < 500:
        _AG[S] = None
        return None
    # weighted least squares on [1, x, x^2], normal equations by hand (stdlib)
    m = [[sum(w * x ** (i + j) for x, w in zip(xs, ws)) for j in range(3)] for i in range(3)]
    r = [sum(w * d * x ** i for x, d, w in zip(xs, ds, ws)) for i in range(3)]
    for i in range(3):
        for k in range(i + 1, 3):
            f = m[k][i] / m[i][i]
            m[k] = [u - f * v for u, v in zip(m[k], m[i])]; r[k] -= f * r[i]
    c = [0.0] * 3
    for i in (2, 1, 0):
        c[i] = (r[i] - sum(m[i][j] * c[j] for j in range(i + 1, 3))) / m[i][i]
    _AG[S] = lambda ag: c[0] + c[1] * (min(max(ag, 20), 36) - 27) + c[2] * (min(max(ag, 20), 36) - 27) ** 2
    return _AG[S]


DRAFT = os.path.join(HERE, 'nba_draft.json')
ROOKIE_COLLEGE = os.path.join(HERE, 'nba_rookie_college.json')   # bbref id -> final college season Barttorvik BPM
DRAFT_CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nba', 'draft')


def write_draft(lo=2009, hi=None):
    """every NBA draft lo..hi from Basketball-Reference: {year: [[pick, bbref id, name, team]]} -> scripts/nba_draft.json"""
    import re, time, urllib.request, html as H
    hi = hi or dt.date.today().year
    os.makedirs(DRAFT_CACHE, exist_ok=True)
    try:
        out = json.load(open(DRAFT))                 # years already in the file stay as they are
    except (OSError, ValueError):
        out = {}
    for y in range(lo, hi + 1):
        if str(y) in out:
            continue
        fn = os.path.join(DRAFT_CACHE, f'NBA_{y}.html')
        if not os.path.exists(fn) or os.path.getsize(fn) < 50000:
            try:
                req = urllib.request.Request(f'https://www.basketball-reference.com/draft/NBA_{y}.html', headers={'User-Agent': E.UA})
                open(fn, 'w').write(urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace'))
                time.sleep(4)
            except Exception as e:      # noqa: BLE001
                print(y, 'draft', e); continue
        rows = []
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', open(fn).read(), re.S):
            c = dict(re.findall(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', tr, re.S))
            pk = re.sub(r'<[^>]+>', '', c.get('pick_overall', ''))
            pid = re.search(r'/players/\w/(\w+)\.html', c.get('player', ''))
            if pk.isdigit() and pid:
                rows.append([int(pk), pid.group(1), H.unescape(re.sub(r'<[^>]+>', '', c['player'])),
                             E.team(re.sub(r'<[^>]+>', '', c.get('team_id', '')))])
        if rows:
            out[str(y)] = rows
    with open(DRAFT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('draft', {k: len(v) for k, v in out.items()})


_DR = {}


def draft():
    if not _DR:
        try:
            _DR.update({int(k): v for k, v in json.load(open(DRAFT)).items()})
        except (OSError, ValueError):
            pass
    return _DR


_PC = {}


def pick_curves(S):
    """rookie-season XPM and minutes a game by draft slot, a + b ln(pick), fit on the drafts whose rookie seasons
    came before season S (so a backtest season never sees its own rookies)"""
    if S in _PC:
        return _PC[S]
    xs, vs, ws, ms = [], [], [], []
    for d, rows in draft().items():
        if not (2010 <= d + 1 < S):
            continue
        fn = os.path.join(XPM, f'{d + 1}.json')
        if not os.path.exists(fn):
            continue
        by = {p['id']: p for p in json.load(open(fn))['players']}
        for pk, bid, _, _ in rows:
            p = by.get(bid)
            if p and p.get('xpm') is not None and p.get('g'):
                xs.append(math.log(pk)); vs.append(p['xpm']); ws.append(p['mp']); ms.append(p['mp'] / p['g'])

    def wls(x, y, w):
        sw = sum(w); mx = sum(a * c for a, c in zip(x, w)) / sw; my = sum(a * c for a, c in zip(y, w)) / sw
        b = sum(c * (a - mx) * (e - my) for a, e, c in zip(x, y, w)) / sum(c * (a - mx) ** 2 for a, c in zip(x, w))
        return my - b * mx, b
    if len(xs) < 30:
        _PC[S] = None
        return None
    va, vb = wls(xs, vs, ws)
    ma, mb = wls(xs, ms, [1.0] * len(xs))
    _PC[S] = (lambda pk: va + vb * math.log(pk), lambda pk: max(4.0, ma + mb * math.log(pk)), college_curve(S))
    return _PC[S]


_RC = {}
_NL = {}


def newcomer_level(S):
    """provisional XPM for a player with no NBA line in the two seasons before who wasn't drafted last summer (undrafted
    rookies, two-way and 10-day call-ups, players back from overseas): the minutes-weighted XPM such players posted in
    their first season back, over the seasons before S (2013 on)"""
    if S not in _NL:
        last = {d: {bid for _, bid, _, _ in rows} for d, rows in draft().items()}
        ids = {}
        for y in range(2010, S):
            fn = os.path.join(XPM, f'{y}.json')
            if os.path.exists(fn):
                ids[y] = {p['id']: p for p in json.load(open(fn))['players'] if p.get('xpm') is not None and not p.get('pr')}
        num = den = 0.0
        for y in range(2013, S):
            for b, p in ids.get(y, {}).items():
                if b in ids.get(y - 1, {}) or b in ids.get(y - 2, {}) or b in last.get(y - 1, ()):
                    continue
                num += p['xpm'] * p['mp']; den += p['mp']
        _NL[S] = num / den if den > 2000 else None
    return _NL[S]


def rookie_college():
    if not _RC:
        try:
            _RC.update(json.load(open(ROOKIE_COLLEGE)))
        except (OSError, ValueError):
            pass
    return _RC


def college_curve(S):
    """rookie-season XPM of drafted college players from slot and final college BPM, a + b ln(pick) + c BPM,
    minutes-weighted, fit on rookie classes before S (research: scripts/nba_prior_research.py)"""
    cb = rookie_college()
    rows = []
    for d, picks in draft().items():
        if not (2010 <= d + 1 < S):
            continue
        fn = os.path.join(XPM, f'{d + 1}.json')
        if not os.path.exists(fn):
            continue
        by = {p['id']: p for p in json.load(open(fn))['players']}
        for pk, bid, _, _ in picks:
            p = by.get(bid)
            if p and p.get('xpm') is not None and p.get('g') and bid in cb:
                rows.append((math.log(pk), cb[bid], p['xpm'], p['mp']))
    if len(rows) < 60:
        return None
    m = [[sum(r[3] * u * v for r in rows for u, v in [((1, r[0], r[1])[i], (1, r[0], r[1])[j])]) for j in range(3)] for i in range(3)]
    y = [sum(r[3] * r[2] * (1, r[0], r[1])[i] for r in rows) for i in range(3)]
    for i in range(3):
        for k in range(i + 1, 3):
            f = m[k][i] / m[i][i]
            m[k] = [u - f * v for u, v in zip(m[k], m[i])]; y[k] -= f * y[i]
    c = [0.0] * 3
    for i in (2, 1, 0):
        c[i] = (y[i] - sum(m[i][j] * c[j] for j in range(i + 1, 3))) / m[i][i]
    return lambda pk, bpm: c[0] + c[1] * math.log(pk) + c[2] * bpm


def opening_rosters(S, names):
    """opening-night rosters: each player's first team in season S's board file (rosters are set before the season)"""
    out = {}
    for pid, nm in names.items():
        v = lookup(S, nm)
        if v:
            out[pid] = v[2]
    return out


# ---------------------------------------------------------------- play chances
STATUSES = ('Out', 'Doubtful', 'Questionable', 'Probable', 'Available')


def bucket(streak):
    return 0 if streak <= 0 else 1 if streak == 1 else 2 if streak <= 4 else 3 if streak <= 14 else 4


def play_prob(P, status, streak, reported):
    """P(plays) by status (None = not on the report; reported = the game had a report) and games missed in a row"""
    k = (status if status else ('none' if reported else 'norep')) + str(bucket(streak))
    return P.get(k, P.get((status or 'none') + 'all', 0.9))


# second night of a back-to-back: rotation players by age (31+) and role (28+ minutes a game played)
B2B_OLD, B2B_STAR = 31, 28.0


def b2b_group(age, R):
    return ('old' if age >= B2B_OLD else 'yng') + ('Star' if R >= B2B_STAR else 'Role')


# ---------------------------------------------------------------- model
def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def tipdt(r):
    return dt.datetime.fromisoformat(r['tip'].replace('Z', '+00:00'))


class Model:
    """Walks games in tip order and keeps every rating; feats(g) before a game, update(g) after it."""
    def __init__(self, names, P, hl=20.0, carry=0.5, elo_k=20.0, mk=0.1, mrev=0.5, tk=0.2, rhl=10.0, bhl=None,
                 hca=2.4, n0=600.0, rook=-2.0, elo_keep=0.75, pk=0.0, pkeep=0.75, thl=None, rk=0, ypk=0, rkw=1.0,
                 rkc=0, age=0, nwc=0, fill=0, qrate=None, rs=0.0, b2b=None, cap=None, inj=None, prior=None, phl=10.0,
                 tcar=0.0, tphl=80.0, ret=0, retm=1.0, lk_own=0.0, lk_opp=0.0, lk_mkt=0.0, ik=0, ikr=None, ib=0,
                 lw3o=1.0, lw3d=1.0, lwft=1.0, lk3=600.0, lkft=300.0, lshl=82.0, ltot=1, lelo=0, arcw=0.0, tlin=None, lokiw=0.0):
        self.a = 0.5 ** (1 / hl)
        self.ra = 0.5 ** (1 / rhl)                      # role minutes: decay a game played
        self.ba = 0.5 ** (1 / (bhl or hl))              # lineup baseline: decay a team game
        self.carry, self.k, self.mk, self.mrev, self.tk, self.hca = carry, elo_k, mk, mrev, tk, hca
        self.names, self.P, self.n0, self.rook = names, P, n0, rook
        self.elo_keep, self.pk, self.pkeep = elo_keep, pk, pkeep
        self.rk, self.ypk, self.rkw = rk, ypk, rkw     # rookies on opening rosters; young players' prior by draft slot
        self.rkc, self.age = rkc, age                   # rookies' college BPM; veterans' aging curve
        self.nwc = nwc                                  # newcomers not drafted last summer at their own level (~-2): fails
                                                        # 2015-21 t +0.9 (nba_roster_research.py --newc, Oct 21 2026); off
        self.fill = fill                                # 1: minutes injuries take off go to replacement level, not the bench
                                                        # at their values: worse held out (t +1.3; nba_roster_research --fill)
        self.qrate = qrate                              # questionable players' play chance in place of the table's: .62 (the
                                                        # value-weighted rate, data/nba_news_fit.json) t -0.7 / -1.1: off
        self.rs = rs                                    # the report's part of the lineup scaled by 1 + rs: the close moves .89 per
                                                        # lineup point on status news, the model .71 (nba_news_fit.json), so
                                                        # x1.25: t -3.2 on 2015-21, -3.5 held out (nba_roster_research --scale)
        self.b2b = b2b                                  # second night of a back-to-back: {'P': {era+group: x play chance},
                                                        # 'M': {group: x minutes}} (nba_games_fit.measure_b2b; groups B2B_GROUP)
        self.cap = cap                                  # minutes caps back from a layoff: {missed-streak bucket: x role
                                                        # minutes}; 2015-21 t -0.7, held out worse (+1.8; nba_sched_research): off
        self.prior = prior or {}                        # season -> {team: the market's preseason win share}; 'mpri' fails
                                                        # (win lines: 2017-21 t -0.1, title odds +0.9; nba_market_prior.py)
        self.phl = phl                                  # its weight on a team's own games played g: phl / (phl + g)
        self.tcar = tcar                                # share of last season's market total gaps kept at the rollover
        self.tphl = tphl                                # 'tpri' (last season's final market total gaps) fades as tphl / (tphl + g)
        self.ret = ret                                  # back from a lost season (under ret minutes last season): his
                                                        # healthy seasons, aged, less the return discount (values)
        self.retm = retm                                # ... and his role minutes x retm at the rollover until he plays
        # lineup-adjusted ratings: each result enters the ratings net of who played. lk_own: share of a team's own
        # lineup gap that night (value played minus its baseline) taken off its result; lk_opp: share of the
        # opponent's gap credited (opponent strength at game time); lk_mkt: share of the expected lineup term the
        # market rating update allows the closing spread (the close prices tonight's injuries)
        self.lk_own, self.lk_opp, self.lk_mkt = lk_own, lk_opp, lk_mkt
        # in-season values (scripts/nba_inseason.py): after each game a player's value is his opening value with ik
        # minutes' weight (ikr for one with no NBA seasons behind him) blended with his box-score XPM to date
        self.ik, self.ikr = ik, (ikr if ikr is not None else ik)
        self.val0, self.bxs, self.known, self.icoef = {}, {}, set(), None
        self.lgb = None
        # ib: the lineup baseline at today's values (each player's decayed share of the team's minutes x his value
        # now), so a value that moves in season moves the baseline with it and 'lin' stays the lineup's gap
        self.ib = ib
        self.bm = defaultdict(lambda: defaultdict(float))
        # luck-stripped efficiency (team idea 6): a result enters the efficiency ratings with each side's threes and
        # free throws partly at expected rates. lw3o: weight on the made threes in a team's own offense rating (the rest
        # at its own 3P% to date, shrunk to the league's with lk3 attempts); lw3d: the same in the defense rating of the
        # team that allowed them; lwft: free throws at the shooters' FT% to date (lkft attempts). 1 = raw points.
        # ltot: the share of it in the total's copies; lelo: Elo on the stripped margin. Shooting carries a half-life of lshl games.
        self.lw3o, self.lw3d, self.lwft, self.lk3, self.lkft = lw3o, lw3d, lwft, lk3, lkft
        self.lsa, self.ltot, self.lelo = 0.5 ** (1 / lshl), ltot, lelo
        self.shot = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])   # team -> decayed 3PM, 3PA, FTM, FTA
        self.lgs = [0.36, 1.0, 0.77, 1.0]                # league 3P% and FT%, running
        # LUMA ARC (scripts/nba_arc.py) mixed into each player's opening value at weight arcw (arc_blend)
        self.arcw = arcw
        self.lokiw = lokiw                              # LUMA LOKI preseason projection mixed in at lokiw (loki_blend): FAILED,
                                                        # 2015-21 flat, gains only in LUMA's tuning seasons; off
        # totals lineup (candidate): each side's offense and defense lineup values against their own baselines;
        # tlin = 'xpm' or 'arc' (od_values source), None = off
        self.tlin = tlin
        self.valO, self.valD = {}, {}
        self.baseO = defaultdict(lambda: [0.0, 0.0]); self.baseD = defaultdict(lambda: [0.0, 0.0])
        self._lin = {}
        self.wl = {}
        self.tm0 = {}
        self.night2 = set()                             # teams on the second night tonight
        self.ages = {}                                  # pid -> age this season (last season's XPM file + 1)
        self.inj = inj or {}                            # game id -> {name key: status}
        self.elo = defaultdict(lambda: 1505.0)
        self.pelo = defaultdict(float)                  # points Elo: points over average, stepped on margin vs expected
        self.ngp = defaultdict(int)                     # team -> games this season
        self.off = defaultdict(lambda: [0.0, 0.0])      # pts/100 over league, opponent-adjusted (weighted sum, weight)
        self.dfn = defaultdict(lambda: [0.0, 0.0])      # pts/100 allowed over league
        self.pace = defaultdict(lambda: [0.0, 0.0])     # possessions over league
        # the total's copies of the three, on their own half-life (thl; None = the same ratings)
        self.sets = [(self.off, self.dfn, self.pace, self.a)]
        if thl:
            self.toff, self.tdfn, self.tpace = (defaultdict(lambda: [0.0, 0.0]) for _ in range(3))
            self.sets.append((self.toff, self.tdfn, self.tpace, 0.5 ** (1 / thl)))
        else:
            self.toff, self.tdfn, self.tpace = self.off, self.dfn, self.pace
        self.mkt = defaultdict(float)
        self.tm = defaultdict(float)
        self.tlg = 205.0
        self.lg = [110.0, 1.0]                          # league pts/100, running
        self.lgp = [96.0, 1.0]                          # league possessions a game
        self.role = {}                                  # pid -> [weighted minutes, weight] in games played
        self.team = {}                                  # pid -> current team
        self.members = defaultdict(set)                 # team -> pids
        self.streak = defaultdict(int)                  # pid -> team games missed in a row
        self.base = defaultdict(lambda: [0.0, 0.0])     # team -> lineup value actually played (weighted)
        self.last = {}                                  # team -> (tip datetime, arena team)
        self.recent = defaultdict(list)                 # team -> tips (for 3-in-4)
        self.val = {}
        self.season = None

    # -- season rollover
    def new_season(self, S):
        for t in list(self.elo):
            self.elo[t] = 1505 + (self.elo[t] - 1505) * self.elo_keep
        for t in list(self.pelo):
            self.pelo[t] *= self.pkeep
        self.ngp.clear()
        for d in [self.base, self.baseO, self.baseD] + [d for st in self.sets for d in st[:3]]:
            for t in d:
                d[t][0] *= self.carry; d[t][1] *= self.carry
        for bm in self.bm.values():
            for pid in bm:
                bm[pid] *= self.carry
        for v in self.shot.values():
            v[:] = [x * 0.5 for x in v]
        for t in list(self.mkt):
            self.mkt[t] *= self.mrev
        self.tm0 = dict(self.tm)                        # last season's final market total gaps, for 'tpri'
        for t in list(self.tm):
            self.tm[t] *= self.tcar
        self.wl = self.prior.get(S) or {}
        for p in self.role.values():
            p[0] *= 0.5; p[1] *= 0.5
        self.val = values(S, self.names, self.n0, self.rook, age=self.age, ret=self.ret)
        if self.tlin:
            self.valO, self.valD = od_values(S, self.names, self.tlin)
        if self.arcw:
            skip = {pid for pid, nm in self.names.items() if self.ret and returner([lookup(S - k, nm) for k in range(1, 5)], self.ret)}
            self.val = arc_blend(S, self.names, self.val, self.arcw, skip=skip)
        if self.lokiw:
            self.val = loki_blend(S, self.names, self.val, self.lokiw)
        if self.retm != 1.0:
            for pid, nm in self.names.items():
                r = self.role.get(pid)
                if r and returner([lookup(S - k, nm) for k in range(1, 5)], self.ret or RET_MIN):
                    r[0] *= self.retm
        if self.b2b:
            self.ages = {}
            for pid, nm in self.names.items():
                r = lookup(S - 1, nm)
                if r and r[3]:
                    self.ages[pid] = r[3] + 1
        if self.nwc:
            lv = newcomer_level(S)
            if lv is not None:
                for pid, nm in self.names.items():
                    if not lookup(S - 1, nm) and not lookup(S - 2, nm):
                        self.val[pid] = lv
        if self.rk or self.ypk:
            self.draft_priors(S)
        for p, t in opening_rosters(S, self.names).items():
            self.set_team(p, t)
        if self.ik:
            import nba_inseason as IS
            self.icoef = IS.coef(S)
            self.val0 = dict(self.val)
            self.bxs = {}
            self.known = {pid for pid, nm in self.names.items() if lookup(S - 1, nm) or lookup(S - 2, nm)}
            if self.lgb is not None:                    # last season's league line stands in at 50 team games' weight
                self.lgb = self.lgb * (50 * 240.0 * 2 / self.lgb[0])
        self.streak.clear()
        self.last.clear(); self.recent.clear()
        self.season = S

    def draft_priors(self, S):
        """rookies: drafted last summer, valued at their slot's rookie XPM and expected at its minutes until they
        play (rkw games' weight); rkc: a college player's XPM from his slot and final college BPM instead; second- and third-year players: shrunk toward their slot's value, not a newcomer's"""
        pc = pick_curves(S)
        if not pc:
            return
        vcur, mcur, ccur = pc
        cb = rookie_college() if self.rkc else {}
        idx = {}
        for pid, nm in self.names.items():
            k = norm(nm)
            idx[k] = None if k in idx else pid
        for d, rows in draft().items():
            age = S - 1 - d                              # 0 = this season's rookies
            if age < 0 or age > (2 if self.ypk else 0):
                continue
            for pk, bid, nm, _ in rows:
                pid = idx.get(norm(nm))
                if not pid:
                    continue
                pv = ccur(pk, cb[bid]) if ccur and bid in cb else vcur(pk)
                if age == 0 and self.rk:
                    self.val[pid] = pv
                    if pid not in self.role:
                        self.role[pid] = [mcur(pk) * self.rkw, self.rkw]
                elif age > 0 and self.ypk:
                    a, b = lookup(S - 1, nm), lookup(S - 2, nm)
                    num, den = pv * self.n0, self.n0
                    for r_, w_ in ((a, 1.0), (b, 0.5)):
                        if r_:
                            num += r_[0] * r_[1] * w_; den += r_[1] * w_
                    self.val[pid] = num / den

    def rate(self, d, t, w0=3.0):
        v, w = d[t]
        return v / (w + w0)

    def brate(self, t):
        if not self.ib:
            return self.rate(self.base, t, 1.0)
        return sum(self.v(p) * m for p, m in self.bm[t].items()) / 48 / (self.base[t][1] + 1.0)

    def v(self, pid):
        return self.val.get(pid, self.rook)

    def luck(self, t, sh):
        """team t's made threes and free throws over expected that night (points): (threes gap, free throws gap)"""
        m3, a3, mf, af = sh
        s = self.shot[t]
        x3 = (s[0] + self.lk3 * self.lgs[0] / self.lgs[1]) / (s[1] + self.lk3)
        xf = (s[2] + self.lkft * self.lgs[2] / self.lgs[3]) / (s[3] + self.lkft)
        return 3 * (m3 - a3 * x3), mf - af * xf

    def set_team(self, p, t):
        old = self.team.get(p)
        if old != t:
            if old:
                self.members[old].discard(p)
            self.team[p] = t
            self.members[t].add(p)

    def roster(self, t):
        return [p for p in self.members[t] if p in self.role]

    def lineup(self, t, status=None, reported=False, vals=None, repl=REPL):
        """tonight's expected lineup value (points per 100 over average, summed over 240 minutes); vals: another
        value table (offense / defense parts) with its own replacement level"""
        status = status or {}
        vf = (lambda p: vals.get(p, repl)) if vals is not None else self.v
        exp = []
        for p in self.roster(t):
            m, w = self.role[p]
            if w <= 0:
                continue
            R = m / w
            st = status.get(p)
            pr = self.qrate if self.qrate is not None and st == 'Questionable' else play_prob(self.P, st, self.streak[p], reported)
            if self.cap and self.streak[p] > 0:
                R *= self.cap.get(str(bucket(self.streak[p])), 1.0)
            if self.b2b and t in self.night2:
                g_ = b2b_group(self.ages.get(p, 0), R)
                if not st and self.streak[p] == 0:      # listed players' rest is on the report already
                    pr = min(1.0, pr * self.b2b['P'].get(('rep' if reported else 'norep') + g_, 1.0))
                R *= self.b2b['M'].get(g_, 1.0)
            exp.append((p, R * pr, R * (play_prob(self.P, None, self.streak[p], reported) if self.fill else pr)))
        tot = sum(e for _, e, _ in exp)
        th = sum(h for _, _, h in exp)            # fill: the same lineup with nobody on the report
        sc = 240.0 / (th if self.fill else tot) if (th if self.fill else tot) > 240 else 1.0
        exp = [(p, e) for p, e, _ in exp]
        V = sum(vf(p) * e * sc for p, e in exp) / 48
        if tot * sc < 240:
            V += repl * (240 - tot * sc) / 48
        return V

    def status_for(self, g, t):
        rep = self.inj.get(g['id'])
        if rep is None:
            return None, False
        st = {}
        for p in self.roster(t):
            s = rep.get(norm(self.names.get(p, '')))
            if s:
                st[p] = s
        return st, True

    def sched(self, g, t, arena):
        tip = tipdt(g)
        last = self.last.get(t)
        rest = 3 if not last else max(0, min(3, (tip.date() - last[0].date()).days - 1))
        km = hav(ARENA[last[1]], ARENA[arena]) if last else 0.0
        tz = (ARENA[arena][2] - ARENA[last[1]][2]) if last else 0
        n4 = sum(1 for x in self.recent[t] if (tip - x).total_seconds() < 3.5 * 86400)
        return rest, km, tz, n4

    def feats(self, g):
        if g['S'] != self.season:
            self.new_season(g['S'])
        h, a = g['h'], g['a']
        L = self.lg[0] / self.lg[1]
        P = self.lgp[0] / self.lgp[1]
        pace = P + self.rate(self.pace, h) + self.rate(self.pace, a)
        paceM = (P + self.rate(self.pace, h)) * (P + self.rate(self.pace, a)) / P
        net = lambda t: self.rate(self.off, t) - self.rate(self.dfn, t)
        self.night2 = {t for t in (h, a) if self.last.get(t) and self.sched(g, t, h)[0] == 0}
        sh, rh = self.status_for(g, h)
        sa, ra = self.status_for(g, a)
        Vh, Va = self.lineup(h, sh, rh), self.lineup(a, sa, ra)
        linst = (Vh - self.lineup(h, None, False)) - (Va - self.lineup(a, None, False))
        Bh, Ba = self.brate(h), self.brate(a)
        home = 0.0 if g['n'] else 1.0
        arena = h if not g['n'] else h                   # neutral sites: distance to the listed home team's city
        restH, kmH, tzH, n4H = self.sched(g, h, arena)
        restA, kmA, tzA, n4A = self.sched(g, a, arena)
        x = {'elo': (self.elo[h] - self.elo[a]) / 28, 'eff': (net(h) - net(a)) * pace / 100,
             'mkt': self.mkt[h] - self.mkt[a], 'lin': (Vh - Bh) - (Va - Ba) + self.rs * linst, 'rest': restH - restA,
             'b2b': (1.0 if restH == 0 else 0.0) - (1.0 if restA == 0 else 0.0), 'home': home,
             # candidates (tested in fit, kept only on out-of-sample evidence)
             'roster': Vh - Va,
             # the report's part of the lineup: tonight's statuses against the same roster with no report. Its own
             # weight fails 2015-21 (t -0.6; held out -1.4); a fixed scale on it (rs) passes
             'linst': linst, 'trav': (kmA - kmH) / 1000, 'tz': abs(tzA) - abs(tzH),
             'alt': home * (1.0 if ARENA[h][3] > 1000 else 0.0), 'n4': n4H - n4A,
             'b2bRoad': (1.0 if restA == 0 and kmA > 0 else 0.0) - (1.0 if restH == 0 and kmH > 0 else 0.0),
             'po': home * (1.0 if g['t'] == 3 else 0.0), 'early': (self.elo[h] - self.elo[a]) / 28 * max(0.0, 1 - self.gp(h, a) / 20),
             'eloPo': (self.elo[h] - self.elo[a]) / 28 * (1.0 if g['t'] == 3 else 0.0),
             'pelo': self.pelo[h] - self.pelo[a],
             # the market's preseason view: win share in points of margin (2.7 wins of 82 a point), fading as each team plays
             'mpri': self.mpri(h) - self.mpri(a), 'mpriF': self.mpri(h, 1) - self.mpri(a, 1),
             'effO': (self.rate(self.off, h) - self.rate(self.off, a)) * pace / 100,
             'effD': (self.rate(self.dfn, a) - self.rate(self.dfn, h)) * pace / 100,
             'effM': (net(h) - net(a)) * paceM / 100, 'gpn': float(self.gp(h, a)),
             # the roster early in a season, before the ratings have caught up with the summer's moves
             'rosterE': (Vh - Va) * max(0.0, 1 - self.gp(h, a) / 20), 'linE': ((Vh - Bh) - (Va - Ba)) * max(0.0, 1 - self.gp(h, a) / 20)}
        both = lambda t: self.rate(self.toff, t) + self.rate(self.tdfn, t)
        tp = P + self.rate(self.tpace, h) + self.rate(self.tpace, a)
        tpM = (P + self.rate(self.tpace, h)) * (P + self.rate(self.tpace, a)) / P
        tx = {'pts': (2 * L + both(h) + both(a)) * tp / 100, 'tmkt': self.tlg + self.tm[h] + self.tm[a],
              'po': 1.0 if g['t'] == 3 else 0.0, 'one': 1.0,
              # candidates: the possession model split (league level, pace at league efficiency, efficiency at
              # league pace), pace as a product of the two teams' paces, home court
              'tlg': 2 * L * P / 100, 'tpace': 2 * L * (tp - P) / 100, 'teff': (both(h) + both(a)) * P / 100,
              'ptsM': (2 * L + both(h) + both(a)) * tpM / 100, 'thome': home,
              # last season's closing totals, team by team (each team's final market total gap), fading as it plays
              'tpri': sum(self.tm0.get(t, 0.0) * self.tphl / (self.tphl + self.ngp[t]) for t in (h, a)),
              'tlin': 0.0, 'tlinst': 0.0}
        if self.tlin:
            g_ = {}
            for nm_, vals, bs, rp in (('O', self.valO, self.baseO, -0.7), ('D', self.valD, self.baseD, -0.7)):
                for t, st, rr in ((h, sh, rh), (a, sa, ra)):
                    now = self.lineup(t, st, rr, vals, rp)
                    g_[nm_ + t] = (now - bs[t][0] / (bs[t][1] + 1.0), now - self.lineup(t, None, False, vals, rp))
            tx['tlin'] = sum(g_['O' + t][0] - g_['D' + t][0] for t in (h, a)) * tp / 100
            tx['tlinst'] = sum(g_['O' + t][1] - g_['D' + t][1] for t in (h, a)) * tp / 100
        self._ctx = (Vh, Va, pace)
        self._lin[g['id']] = (x['lin'], pace)
        return x, tx

    def mpri(self, t, flat=0):
        w = self.wl.get(t)
        if w is None:
            return 0.0
        return (w - 0.5) * 82 / 2.7 * (1.0 if flat else self.phl / (self.phl + self.ngp[t]))

    def gp(self, h, a):
        return min(self.ngp[h], self.ngp[a])

    def market(self, g):
        h, a = g['h'], g['a']
        L, T = g.get('L'), g.get('T')
        if L is not None:
            e = L - (self.mkt[h] - self.mkt[a] + (0 if g['n'] else 2.4) + self.lk_mkt * self._lin.get(g['id'], (0.0,))[0])
            self.mkt[h] += self.mk * e; self.mkt[a] -= self.mk * e
        if T:
            # the league level follows every closing total; teams carry only their gap to it (so a new season,
            # which resets the team gaps, starts at the league's current scoring level)
            if g['t'] != 3:                             # playoff totals run lower: the level is the regular season's
                self.tlg += 0.02 * (T - self.tlg)
            e = T - (self.tlg + self.tm[h] + self.tm[a])
            self.tm[h] += self.tk * e; self.tm[a] += self.tk * e

    def update(self, g):
        self.night2 = set()                             # night two applies to this game's lineups only
        self.market(g)
        for t, ar in ((g['h'], g['h']), (g['a'], g['h'])):    # schedule first: a projected slate feeds the next day's rest
            self.last[t] = (tipdt(g), ar)
            self.recent[t] = [x for x in self.recent[t] if (tipdt(g) - x).total_seconds() < 4 * 86400] + [tipdt(g)]
        if not g.get('fin'):
            return
        h, a, hs, as_ = g['h'], g['a'], g['hs'], g['as']
        # the lineup each side actually played against its baseline (net points per 100), before anything updates
        pl = g.get('pl') or {}
        dev = {}
        for t in (h, a):
            rows = [(p, m) for p, m in (pl.get(t) or []) if m > 0]
            tot = sum(m for _, m in rows)
            dev[t] = (sum(self.v(p) * m for p, m in rows) * 240.0 / tot / 48 - self.brate(t)) if tot else 0.0
        lp = self._lin.pop(g['id'], (0.0, 100.0))[1] / 100
        shoot = g.get('sh') or {}
        lu = {t: self.luck(t, shoot[t]) if t in shoot and len(shoot) == 2 else (0.0, 0.0) for t in (h, a)}
        # points to take off a side's score: in its own offense rating (lo) and in its opponent's defense rating (ld)
        lo = {t: (1 - self.lw3o) * lu[t][0] + (1 - self.lwft) * lu[t][1] for t in (h, a)}
        ld = {t: (1 - self.lw3d) * lu[t][0] + (1 - self.lwft) * lu[t][1] for t in (h, a)}
        # Elo (538's NBA: home court 100, margin multiplier); with lineup adjustment each side's expectation is at
        # game-time strength (28 Elo points a point of margin)
        hfa = 0 if g['n'] else 100
        d = self.elo[h] + hfa - self.elo[a]
        if self.lelo:
            hs, as_ = hs - self.lelo * (lo[h] + ld[h]) / 2, as_ - self.lelo * (lo[a] + ld[a]) / 2
        mov = abs(hs - as_)
        for side, dd in ((1, d + 28 * lp * (self.lk_own * dev[h] - self.lk_opp * dev[a])),
                         (-1, d + 28 * lp * (self.lk_opp * dev[h] - self.lk_own * dev[a]))):
            ph = 1 / (1 + 10 ** (-dd / 400))
            wd = dd if hs > as_ else -dd
            mult = (mov + 3) ** 0.8 / (7.5 + 0.006 * wd)
            sh = self.k * mult * ((1.0 if hs > as_ else 0.0) - ph)
            if side == 1:
                self.elo[h] += sh
            else:
                self.elo[a] -= sh
        hs, as_ = g['hs'], g['as']
        if self.pk:
            e = (hs - as_) - (self.pelo[h] - self.pelo[a] + (0 if g['n'] else self.hca))
            self.pelo[h] += self.pk * e; self.pelo[a] -= self.pk * e
        self.ngp[h] += 1; self.ngp[a] += 1
        poss = g.get('poss')
        L = self.lg[0] / self.lg[1]
        if poss and poss > 60:
            hc = 0 if g['n'] else self.hca / 2
            P = self.lgp[0] / self.lgp[1]
            for i, (off, dfn, pc, k) in enumerate(self.sets):
                use = 1.0 if i == 0 else self.ltot
                for t, o, sc, oc, s in ((h, a, hs, as_, 1), (a, h, as_, hs, -1)):
                    ort = 100 * (sc - use * lo[t]) / poss
                    drt = 100 * (oc - use * ld[o]) / poss
                    # own gap off the result, opponent at game-time strength: half of each on offense, half on defense
                    jo, jt = self.lk_opp * dev[o] / 2, self.lk_own * dev[t] / 2
                    adj_o = ort - L - (self.rate(dfn, o) - jo) - s * hc - jt
                    adj_d = drt - L - (self.rate(off, o) + jo) + s * hc + jt
                    off[t][0] = off[t][0] * k + adj_o; off[t][1] = off[t][1] * k + 1
                    dfn[t][0] = dfn[t][0] * k + adj_d; dfn[t][1] = dfn[t][1] * k + 1
                    adj_p = poss - P - self.rate(pc, o)
                    pc[t][0] = pc[t][0] * k + adj_p; pc[t][1] = pc[t][1] * k + 1
            if g['t'] != 3:
                self.lg[0] = self.lg[0] * 0.998 + 100 * (hs + as_) / (2 * poss); self.lg[1] = self.lg[1] * 0.998 + 1
                self.lgp[0] = self.lgp[0] * 0.998 + poss; self.lgp[1] = self.lgp[1] * 0.998 + 1
        if len(shoot) == 2:
            for t in (h, a):
                m3, a3, mf, af = shoot[t]
                v = self.shot[t]
                v[:] = [v[0] * self.lsa + m3, v[1] * self.lsa + a3, v[2] * self.lsa + mf, v[3] * self.lsa + af]
                if g['t'] != 3 and a3 and af:
                    self.lgs[0] = self.lgs[0] * 0.998 + m3 / a3; self.lgs[1] = self.lgs[1] * 0.998 + 1
                    self.lgs[2] = self.lgs[2] * 0.998 + mf / af; self.lgs[3] = self.lgs[3] * 0.998 + 1
        # lineups: minutes played, the value actually on the floor, who missed
        for t in (h, a):
            rows = pl.get(t) or []
            if not rows:
                continue
            tot = sum(m for _, m in rows) or 240.0
            on = set()
            Vp = 0.0
            VO = VD = 0.0
            for pid, m in rows:
                if m <= 0:
                    continue
                on.add(pid)
                Vp += self.v(pid) * m * 240.0 / tot / 48
                if self.tlin:
                    VO += self.valO.get(pid, -0.7) * m * 240.0 / tot / 48
                    VD += self.valD.get(pid, -0.7) * m * 240.0 / tot / 48
                r = self.role.setdefault(pid, [0.0, 0.0])
                r[0] = r[0] * self.ra + m; r[1] = r[1] * self.ra + 1
                self.set_team(pid, t)
                self.streak[pid] = 0
            for p in self.roster(t):
                if p not in on:
                    self.streak[p] += 1
            b = self.base[t]
            b[0] = b[0] * self.ba + Vp; b[1] = b[1] * self.ba + 1
            if self.tlin:
                for bb, vv in ((self.baseO[t], VO), (self.baseD[t], VD)):
                    bb[0] = bb[0] * self.ba + vv; bb[1] = bb[1] * self.ba + 1
            if self.ib:
                bm = self.bm[t]
                for pid in list(bm):
                    bm[pid] *= self.ba
                    if bm[pid] < 0.05:
                        del bm[pid]
                for pid, m in rows:
                    if m > 0:
                        bm[pid] += m * 240.0 / tot
        if self.ik and g.get('bx'):
            self.in_season(g['bx'])

    def in_season(self, bx):
        """this game's box lines into each player's line to date, then his value: the opening value with ik (ikr)
        minutes' weight, blended with his box XPM to date"""
        import numpy as np
        import nba_inseason as IS
        rows = [r for t in bx.values() for r in t]
        tot = np.sum([r[1:] for r in rows], 0) if rows else None
        if tot is None:
            return
        self.lgb = tot.astype(float) if self.lgb is None else self.lgb + tot
        if self.icoef is None:
            return
        for r in rows:
            pid = r[0]
            if not pid:
                continue
            v = self.bxs.get(pid)
            v = self.bxs[pid] = (v + np.array(r[1:], float)) if v is not None else np.array(r[1:], float)
            k = self.ik if pid in self.known else self.ikr
            pr = self.val0.get(pid, self.rook)
            self.val[pid] = (pr * k + IS.box_xpm(v, self.icoef, self.lgb) * v[0]) / (k + v[0])


def walk(games, names, P, params, inj=None, collect=True):
    m = Model(names, P, inj=inj, **params)
    out = []
    for g in games:
        x, tx = m.feats(g)
        if collect:
            out.append((g, x, tx))
        m.update(g)
    return m, out


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--hist':
        write_hist(int(a[1]) if len(a) > 1 else FIRST, int(a[2]) if len(a) > 2 else 2026)
    elif a and a[0] == '--draft':
        write_draft()
    elif a and a[0] == '--fit':
        import nba_games_fit
        nba_games_fit.fit()
    else:
        import nba_games_build
        nba_games_build.build()
