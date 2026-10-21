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
            games and carried across seasons at a fraction, times the matchup's expected pace
    mkt     market rating: each team's points against an average team as earlier closing spreads priced it (never the
            game's own line)
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
ratings on a much shorter half-life (thl, tuned on 2015-21 totals), and a market total rating from earlier closing
totals, weighted by regression. scripts/nba_games_research.py has what else was tried.
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
TFEATS = ['pts', 'tmkt', 'po', 'one']
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


def values(S, names, n0=600.0, rook=-2.0, w2=0.5, age=0):
    """each player's value for season S: XPM of the two seasons before, minutes-weighted (the older at w2), shrunk
    toward rook with n0 minutes; nobody known = rook. age: plus the aging curve's change at his age this season,
    scaled by how much of the prior is last season's own minutes (last-season minutes / (minutes + n0))"""
    cv = aging_curve(S) if age else None
    out = {}
    for pid, nm in names.items():
        a, b = lookup(S - 1, nm), lookup(S - 2, nm)
        num = rook * n0; den = n0
        if a:
            num += a[0] * a[1]; den += a[1]
        if b:
            num += b[0] * b[1] * w2; den += b[1] * w2
        out[pid] = num / den
        if cv and a and a[3]:
            out[pid] += cv(a[3] + 1) * a[1] / (a[1] + n0)
    return out


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
                 rkc=0, age=0, inj=None):
        self.a = 0.5 ** (1 / hl)
        self.ra = 0.5 ** (1 / rhl)                      # role minutes: decay a game played
        self.ba = 0.5 ** (1 / (bhl or hl))              # lineup baseline: decay a team game
        self.carry, self.k, self.mk, self.mrev, self.tk, self.hca = carry, elo_k, mk, mrev, tk, hca
        self.names, self.P, self.n0, self.rook = names, P, n0, rook
        self.elo_keep, self.pk, self.pkeep = elo_keep, pk, pkeep
        self.rk, self.ypk, self.rkw = rk, ypk, rkw     # rookies on opening rosters; young players' prior by draft slot
        self.rkc, self.age = rkc, age                   # rookies' college BPM; veterans' aging curve
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
        for d in [self.base] + [d for st in self.sets for d in st[:3]]:
            for t in d:
                d[t][0] *= self.carry; d[t][1] *= self.carry
        for t in list(self.mkt):
            self.mkt[t] *= self.mrev
        for t in list(self.tm):
            self.tm[t] = 0.0
        for p in self.role.values():
            p[0] *= 0.5; p[1] *= 0.5
        self.val = values(S, self.names, self.n0, self.rook, age=self.age)
        if self.rk or self.ypk:
            self.draft_priors(S)
        for p, t in opening_rosters(S, self.names).items():
            self.set_team(p, t)
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

    def v(self, pid):
        return self.val.get(pid, self.rook)

    def set_team(self, p, t):
        old = self.team.get(p)
        if old != t:
            if old:
                self.members[old].discard(p)
            self.team[p] = t
            self.members[t].add(p)

    def roster(self, t):
        return [p for p in self.members[t] if p in self.role]

    def lineup(self, t, status=None, reported=False):
        """tonight's expected lineup value (points per 100 over average, summed over 240 minutes)"""
        status = status or {}
        exp = []
        for p in self.roster(t):
            m, w = self.role[p]
            if w <= 0:
                continue
            R = m / w
            st = status.get(p)
            pr = play_prob(self.P, st, self.streak[p], reported)
            exp.append((p, R * pr))
        tot = sum(e for _, e in exp)
        sc = 240.0 / tot if tot > 240 else 1.0
        V = sum(self.v(p) * e * sc for p, e in exp) / 48
        if tot < 240:
            V += REPL * (240 - tot) / 48
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
        sh, rh = self.status_for(g, h)
        sa, ra = self.status_for(g, a)
        Vh, Va = self.lineup(h, sh, rh), self.lineup(a, sa, ra)
        Bh, Ba = self.rate(self.base, h, 1.0), self.rate(self.base, a, 1.0)
        home = 0.0 if g['n'] else 1.0
        arena = h if not g['n'] else h                   # neutral sites: distance to the listed home team's city
        restH, kmH, tzH, n4H = self.sched(g, h, arena)
        restA, kmA, tzA, n4A = self.sched(g, a, arena)
        x = {'elo': (self.elo[h] - self.elo[a]) / 28, 'eff': (net(h) - net(a)) * pace / 100,
             'mkt': self.mkt[h] - self.mkt[a], 'lin': (Vh - Bh) - (Va - Ba), 'rest': restH - restA,
             'b2b': (1.0 if restH == 0 else 0.0) - (1.0 if restA == 0 else 0.0), 'home': home,
             # candidates (tested in fit, kept only on out-of-sample evidence)
             'roster': Vh - Va, 'trav': (kmA - kmH) / 1000, 'tz': abs(tzA) - abs(tzH),
             'alt': home * (1.0 if ARENA[h][3] > 1000 else 0.0), 'n4': n4H - n4A,
             'b2bRoad': (1.0 if restA == 0 and kmA > 0 else 0.0) - (1.0 if restH == 0 and kmH > 0 else 0.0),
             'po': home * (1.0 if g['t'] == 3 else 0.0), 'early': (self.elo[h] - self.elo[a]) / 28 * max(0.0, 1 - self.gp(h, a) / 20),
             'eloPo': (self.elo[h] - self.elo[a]) / 28 * (1.0 if g['t'] == 3 else 0.0),
             'pelo': self.pelo[h] - self.pelo[a],
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
              'ptsM': (2 * L + both(h) + both(a)) * tpM / 100, 'thome': home}
        self._ctx = (Vh, Va, pace)
        return x, tx

    def gp(self, h, a):
        return min(self.ngp[h], self.ngp[a])

    def market(self, g):
        h, a = g['h'], g['a']
        L, T = g.get('L'), g.get('T')
        if L is not None:
            e = L - (self.mkt[h] - self.mkt[a] + (0 if g['n'] else 2.4))
            self.mkt[h] += self.mk * e; self.mkt[a] -= self.mk * e
        if T:
            # the league level follows every closing total; teams carry only their gap to it (so a new season,
            # which resets the team gaps, starts at the league's current scoring level)
            if g['t'] != 3:                             # playoff totals run lower: the level is the regular season's
                self.tlg += 0.02 * (T - self.tlg)
            e = T - (self.tlg + self.tm[h] + self.tm[a])
            self.tm[h] += self.tk * e; self.tm[a] += self.tk * e

    def update(self, g):
        self.market(g)
        for t, ar in ((g['h'], g['h']), (g['a'], g['h'])):    # schedule first: a projected slate feeds the next day's rest
            self.last[t] = (tipdt(g), ar)
            self.recent[t] = [x for x in self.recent[t] if (tipdt(g) - x).total_seconds() < 4 * 86400] + [tipdt(g)]
        if not g.get('fin'):
            return
        h, a, hs, as_ = g['h'], g['a'], g['hs'], g['as']
        # Elo (538's NBA: home court 100, margin multiplier)
        hfa = 0 if g['n'] else 100
        d = self.elo[h] + hfa - self.elo[a]
        ph = 1 / (1 + 10 ** (-d / 400))
        mov = abs(hs - as_)
        wd = d if hs > as_ else -d
        mult = (mov + 3) ** 0.8 / (7.5 + 0.006 * wd)
        sh = self.k * mult * ((1.0 if hs > as_ else 0.0) - ph)
        self.elo[h] += sh; self.elo[a] -= sh
        if self.pk:
            e = (hs - as_) - (self.pelo[h] - self.pelo[a] + (0 if g['n'] else self.hca))
            self.pelo[h] += self.pk * e; self.pelo[a] -= self.pk * e
        self.ngp[h] += 1; self.ngp[a] += 1
        poss = g.get('poss')
        L = self.lg[0] / self.lg[1]
        if poss and poss > 60:
            hc = 0 if g['n'] else self.hca / 2
            P = self.lgp[0] / self.lgp[1]
            for off, dfn, pc, k in self.sets:
                for t, o, sc, oc, s in ((h, a, hs, as_, 1), (a, h, as_, hs, -1)):
                    ort, drt = 100 * sc / poss, 100 * oc / poss
                    adj_o = ort - L - self.rate(dfn, o) - s * hc
                    adj_d = drt - L - self.rate(off, o) + s * hc
                    off[t][0] = off[t][0] * k + adj_o; off[t][1] = off[t][1] * k + 1
                    dfn[t][0] = dfn[t][0] * k + adj_d; dfn[t][1] = dfn[t][1] * k + 1
                    adj_p = poss - P - self.rate(pc, o)
                    pc[t][0] = pc[t][0] * k + adj_p; pc[t][1] = pc[t][1] * k + 1
            if g['t'] != 3:
                self.lg[0] = self.lg[0] * 0.998 + 100 * (hs + as_) / (2 * poss); self.lg[1] = self.lg[1] * 0.998 + 1
                self.lgp[0] = self.lgp[0] * 0.998 + poss; self.lgp[1] = self.lgp[1] * 0.998 + 1
        # lineups: minutes played, the value actually on the floor, who missed
        pl = g.get('pl') or {}
        for t in (h, a):
            rows = pl.get(t) or []
            if not rows:
                continue
            tot = sum(m for _, m in rows) or 240.0
            on = set()
            Vp = 0.0
            for pid, m in rows:
                if m <= 0:
                    continue
                on.add(pid)
                Vp += self.v(pid) * m * 240.0 / tot / 48
                r = self.role.setdefault(pid, [0.0, 0.0])
                r[0] = r[0] * self.ra + m; r[1] = r[1] * self.ra + 1
                self.set_team(pid, t)
                self.streak[pid] = 0
            for p in self.roster(t):
                if p not in on:
                    self.streak[p] += 1
            b = self.base[t]
            b[0] = b[0] * self.ba + Vp; b[1] = b[1] * self.ba + 1


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
