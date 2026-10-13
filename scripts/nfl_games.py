#!/usr/bin/env python3
"""NFL game projections for the NFL ARKBOARD (data/nfl_games.json), and the model behind them (data/nfl_games_fit.json).

    python3 scripts/nfl_games.py          # this week's projections (stdlib only; run by the cfb board job)
    python3 scripts/nfl_games.py --fit    # walk-forward backtest 2012-2025 against the closing line, refit (numpy)

Data: nflverse (nfldata games.csv: scores, closing spread and total, starting QBs, rest, roof; stats_player_week:
EPA by player and game). Every feature is known before kickoff.

Margin (home minus away, points) is a linear model on:
    elo     Elo difference (538's football Elo: K 20, margin multiplier, 1/3 regression to the mean each offseason)
    epa     net EPA a play (offense minus defense allowed), opponent-adjusted, exponentially weighted with a
            half-life in games, carried across seasons at a fraction (both tuned in the backtest)
    qb      the starting QB against the team's recent QB play: his EPA a play (shrunk toward a backup's level by
            his volume) minus the team's weighted QB EPA a play, so a backup starting moves the line
    rest    rest days, home minus away (capped at 7 each way: byes, short weeks)
    home    1 at a home site, 0 neutral
Total: points for and against, exponentially weighted (same half-life), plus a dome flag.
Win probability and cover chances: normal around the margin with the backtest's residual SD.
The backtest refits each season on the seasons before it and scores that season (2012-2025), against the closing
line (games.csv spread_line, the home side's expected margin) on margin error, and on ATS record where the model and
the line disagree.
"""
import csv
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
FIT = os.path.join(ROOT, 'data', 'nfl_games_fit.json')
OUT = os.path.join(ROOT, 'data', 'nfl_games.json')
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
FIRST = 2009                       # EPA history starts here; ratings warm up for three seasons before scoring
FEATS = ['elo', 'epa', 'qb', 'rest', 'home']
TFEATS = ['pts', 'dome', 'one']
# team renames: one franchise, one rating
FRANCHISE = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA'}


def get(name, url, fresh=False):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if fresh or not os.path.exists(p):
        req = urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net arkboard'})
        with urllib.request.urlopen(req, timeout=120) as r, open(p + '.tmp', 'wb') as f:
            f.write(r.read())
        os.replace(p + '.tmp', p)
    return p


def rows(p):
    with open(p, newline='', encoding='utf-8') as f:
        yield from csv.DictReader(f)


def num(x, d=0.0):
    try:
        return float(x) if x not in (None, '', 'NA') else d
    except ValueError:
        return d


def team(t):
    return FRANCHISE.get(t, t)


def load(last, fresh=False):
    """Games FIRST..last (regular season and playoffs) in kickoff order, and per-game team EPA and QB lines."""
    games = [g for g in rows(get('games.csv', GAMES, fresh)) if FIRST <= int(g['season']) <= last]
    games.sort(key=lambda g: (g['gameday'], g['gametime'], g['game_id']))
    box = defaultdict(lambda: {'epa': 0.0, 'plays': 0.0})       # (game_id, team) -> offense EPA and plays
    qbs = defaultdict(lambda: {'epa': 0.0, 'plays': 0.0})       # (game_id, gsis) -> QB EPA and plays
    for y in range(FIRST, last + 1):
        for r in rows(get(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv', fresh and y == last)):
            gid = r.get('game_id')
            if not gid:
                continue
            e = num(r['passing_epa']) + num(r['rushing_epa'])
            n = num(r['attempts']) + num(r['sacks_suffered']) + num(r['carries'])
            b = box[(gid, team(r['team']))]
            b['epa'] += e; b['plays'] += n
            if r['position'] == 'QB':
                q = qbs[(gid, r['player_id'])]
                q['epa'] += e; q['plays'] += n
    return games, box, qbs


class Model:
    """Walks games in order and keeps every rating; feats(g) before a game, update(g) after it."""
    def __init__(self, hl=6.0, carry=0.5, qb_n0=250.0, qb_repl=-0.12, elo_k=20.0):
        self.a = 0.5 ** (1 / hl)         # weight decay a game
        self.carry, self.n0, self.repl, self.k = carry, qb_n0, qb_repl, elo_k
        self.elo = defaultdict(lambda: 1505.0)
        self.off = defaultdict(lambda: [0.0, 0.0])    # weighted EPA, weight (offense, opponent-adjusted)
        self.dfn = defaultdict(lambda: [0.0, 0.0])    # EPA allowed
        self.pf = defaultdict(lambda: [0.0, 0.0])     # points for, points against (weighted sums), weight
        self.pa = defaultdict(lambda: [0.0, 0.0])
        self.qbt = defaultdict(lambda: [0.0, 0.0])    # team's QB EPA a play, weighted
        self.qb = defaultdict(lambda: [0.0, 0.0])     # each QB's career EPA and plays, recent seasons weighted
        self.season = None
        self.lg = [0.0, 0.0]                           # league EPA a play (running)
        self.lgpts = 21.5

    def new_season(self, s):
        for t in list(self.elo):
            self.elo[t] = 1505 + (self.elo[t] - 1505) * 2 / 3
        for d in (self.off, self.dfn, self.pf, self.pa, self.qbt):
            for t in d:
                d[t][0] *= self.carry; d[t][1] *= self.carry
        for q in self.qb.values():
            q[0] *= 0.7; q[1] *= 0.7
        self.season = s

    def rate(self, d, t, prior=0.0, w0=2.0):
        v, w = d[t]
        return (v + prior * w0) / (w + w0)

    def lgepa(self):
        return self.lg[0] / self.lg[1] if self.lg[1] else 0.0

    def qbval(self, gsis):
        v, n = self.qb[gsis]
        return (v + self.repl * self.n0) / (n + self.n0)

    def feats(self, g):
        s = int(g['season'])
        if s != self.season:
            self.new_season(s)
        h, a = team(g['home_team']), team(g['away_team'])
        L = self.lgepa()
        net = lambda t: self.rate(self.off, t, L) - self.rate(self.dfn, t, L)
        qadj = lambda t, q: (self.qbval(q) - self.rate(self.qbt, t, self.repl)) if q else 0.0
        rest = lambda x: max(-7, min(7, num(x, 7) - 7))
        home = 0.0 if g['location'] == 'Neutral' else 1.0
        x = {'elo': (self.elo[h] - self.elo[a]) / 25, 'epa': (net(h) - net(a)) * 62,
             'qb': (qadj(h, g['home_qb_id']) - qadj(a, g['away_qb_id'])) * 38,
             'rest': rest(g['home_rest']) - rest(g['away_rest']), 'home': home}
        P = self.lgpts
        pts = (self.rate(self.pf, h, P) + self.rate(self.pa, a, P) + self.rate(self.pf, a, P) + self.rate(self.pa, h, P)) / 2
        tx = {'pts': pts, 'dome': 1.0 if g['roof'] in ('dome', 'closed') else 0.0, 'one': 1.0}
        return x, tx

    def update(self, g, box, qbs):
        if g['home_score'] in ('', 'NA'):
            return
        h, a = team(g['home_team']), team(g['away_team'])
        hs, as_ = num(g['home_score']), num(g['away_score'])
        # Elo, 538's margin multiplier; home field 48 Elo at a home site
        hfa = 0 if g['location'] == 'Neutral' else 48
        d = self.elo[h] + hfa - self.elo[a]
        ph = 1 / (1 + 10 ** (-d / 400))
        mov = abs(hs - as_)
        w = 1.0 if hs > as_ else 0.0 if hs < as_ else 0.5
        mult = math.log(mov + 1) * 2.2 / ((d if w == 1 else -d if w == 0 else 0) * 0.001 + 2.2)
        sh = self.k * mult * (w - ph)
        self.elo[h] += sh; self.elo[a] -= sh
        L = self.lgepa()
        for t, o, sc, oc in ((h, a, hs, as_), (a, h, as_, hs)):
            b = box.get((g['game_id'], t)); bo = box.get((g['game_id'], o))
            for dd, val in ((self.pf, sc), (self.pa, oc)):
                dd[t][0] = dd[t][0] * self.a + val; dd[t][1] = dd[t][1] * self.a + 1
            if b and b['plays'] > 20:
                e = b['epa'] / b['plays']
                # opponent adjustment: credit the offense against the defense it faced
                adj_o = e - (self.rate(self.dfn, o, L) - L)
                self.off[t][0] = self.off[t][0] * self.a + adj_o; self.off[t][1] = self.off[t][1] * self.a + 1
            if bo and bo['plays'] > 20:
                e = bo['epa'] / bo['plays']
                adj_d = e - (self.rate(self.off, o, L) - L)
                self.dfn[t][0] = self.dfn[t][0] * self.a + adj_d; self.dfn[t][1] = self.dfn[t][1] * self.a + 1
            if b and b['plays'] > 20:
                self.lg[0] = self.lg[0] * 0.999 + b['epa']; self.lg[1] = self.lg[1] * 0.999 + b['plays']
            self.lgpts = self.lgpts * 0.995 + sc * 0.005
            # the QB(s) who played: career line, and the team's QB EPA a play
            qid = g['home_qb_id'] if t == h else g['away_qb_id']
            tq = [0.0, 0.0]
            for key, q in ((k, v) for k, v in qbs_for(qbs, g['game_id'], t)):
                self.qb[key][0] += q['epa']; self.qb[key][1] += q['plays']
                tq[0] += q['epa']; tq[1] += q['plays']
            if tq[1] > 10:
                self.qbt[t][0] = self.qbt[t][0] * self.a + tq[0] / tq[1]; self.qbt[t][1] = self.qbt[t][1] * self.a + 1


_QIDX = {}


def index_qbs(qbs, games):
    """(game, team) -> [(gsis, line)]: which team a QB played for is read off the stats file's team."""
    _QIDX.clear()
    for (gid, gsis), q in qbs.items():
        _QIDX.setdefault(gid, []).append((gsis, q))


def qbs_for(qbs, gid, t):
    return [(k, q) for k, q in _QIDX.get(gid, []) if _QTEAM.get((gid, k)) == t]


_QTEAM = {}
_QNAME = {}


def load_qb_teams(last):
    for y in range(FIRST, last + 1):
        for r in rows(os.path.join(CACHE, f'stats_player_week_{y}.csv')):
            if r['position'] == 'QB' and r.get('game_id'):
                _QTEAM[(r['game_id'], r['player_id'])] = team(r['team'])
                _QNAME[r['player_id']] = r['player_display_name']


def walk(games, box, qbs, params, collect=True):
    m = Model(**params)
    out = []
    for g in games:
        x, tx = m.feats(g)
        if collect:
            out.append((g, x, tx))
        m.update(g, box, qbs)
    return m, out


# ---------------------------------------------------------------- fit
def fit():
    import numpy as np
    last = 2025
    games, box, qbs = load(last)
    index_qbs(qbs, games); load_qb_teams(last)
    played = lambda g: g['home_score'] not in ('', 'NA')

    def run(params):
        _, data = walk(games, box, qbs, params)
        D = [(g, x, tx) for g, x, tx in data if played(g) and int(g['season']) >= 2012]
        X = np.array([[x[f] for f in FEATS] for _, x, _ in D]); y = np.array([num(g['result']) for g, _, _ in D])
        TX = np.array([[tx[f] for f in TFEATS] for _, _, tx in D]); ty = np.array([num(g['total']) for g, _, _ in D])
        S = np.array([int(g['season']) for g, _, _ in D])
        line = np.array([num(g['spread_line'], np.nan) for g, _, _ in D]); tline = np.array([num(g['total_line'], np.nan) for g, _, _ in D])
        pred = np.full(len(y), np.nan); tpred = np.full(len(y), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
            tb = np.linalg.lstsq(TX[tr], ty[tr], rcond=None)[0]; tpred[te] = TX[te] @ tb
        return D, X, y, TX, ty, S, line, tline, pred, tpred

    # tune the rating memory on 2015-2020 out-of-sample error, keep 2021-25 clean for the report
    grid = []
    for hl in (4, 6, 8, 12):
        for carry in (0.3, 0.5, 0.7):
            p = {'hl': hl, 'carry': carry}
            D, X, y, TX, ty, S, line, tline, pred, tpred = run(p)
            k = (S >= 2015) & (S <= 2020)
            grid.append((float(np.mean(np.abs(pred[k] - y[k]))), p))
            print('grid', p, round(grid[-1][0], 3))
    grid.sort(key=lambda z: z[0])
    best = grid[0][1]
    D, X, y, TX, ty, S, line, tline, pred, tpred = run(best)
    ok = ~np.isnan(line) & ~np.isnan(pred)
    sd = float(np.std((pred - y)[ok]))

    def block(k):
        k = k & ok
        e = pred[k] - line[k]; r = y[k] - line[k]
        res = {'games': int(k.sum()), 'maeModel': round(float(np.mean(np.abs(pred[k] - y[k]))), 2),
               'maeLine': round(float(np.mean(np.abs(line[k] - y[k]))), 2),
               'rModelVsLine': round(float(np.corrcoef(pred[k], line[k])[0, 1]), 3),
               # does the model's disagreement with the line predict the result's? (slope of result-line on model-line)
               'edgeSlope': round(float(np.polyfit(e, r, 1)[0]), 3)}
        for th in (1, 2, 3):
            pick = np.abs(e) >= th
            win = np.sign(e[pick]) == np.sign(r[pick]); push = r[pick] == 0
            n = int(pick.sum() - push.sum())
            res[f'ats{th}'] = {'n': n, 'pct': round(float(win[~push].mean()), 3) if n else None}
        kt = k & ~np.isnan(tline)
        res['totalMaeModel'] = round(float(np.mean(np.abs(tpred[kt] - ty[kt]))), 2)
        res['totalMaeLine'] = round(float(np.mean(np.abs(tline[kt] - ty[kt]))), 2)
        return res

    test = {'2015-20 (tuning)': block((S >= 2015) & (S <= 2020)), '2021-25 (held out)': block(S >= 2021),
            'all 2015-25': block(S >= 2015)}
    # blending with the line: what share of the model's edge holds up out of sample (2015-25)
    b = np.linalg.lstsq(X[S >= 2012], y[S >= 2012], rcond=None)[0]
    tb = np.linalg.lstsq(TX, ty, rcond=None)[0]
    # per-feature t (whole sample)
    res = y - X @ b; s2 = res @ res / (len(y) - len(b)); cov = s2 * np.linalg.inv(X.T @ X)
    out = {'params': best, 'coef': {f: round(float(v), 4) for f, v in zip(FEATS, b)},
           't': {f: round(float(v / math.sqrt(cov[i, i])), 1) for i, (f, v) in enumerate(zip(FEATS, b))},
           'tcoef': {f: round(float(v), 4) for f, v in zip(TFEATS, tb)},
           'sd': round(sd, 2), 'tsd': round(float(np.std(tpred[~np.isnan(tpred)] - ty[~np.isnan(tpred)])), 2),
           'test': test, 'grid': [[round(e, 3), p] for e, p in grid]}
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'grid'}, indent=1))


# ---------------------------------------------------------------- board
def kick(g):
    """Kickoff in UTC (games.csv lists Eastern time)."""
    import datetime
    from zoneinfo import ZoneInfo
    try:
        t = datetime.datetime.strptime(g['gameday'] + ' ' + g['gametime'], '%Y-%m-%d %H:%M').replace(tzinfo=ZoneInfo('America/New_York'))
    except ValueError:
        return ''
    return t.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def build():
    import datetime
    F = json.load(open(FIT))
    games_all = list(rows(get('games.csv', GAMES, fresh=True)))
    done = [g for g in games_all if g['home_score'] not in ('', 'NA')]
    last = max(int(g['season']) for g in done)
    games, box, qbs = load(last, fresh=True)
    index_qbs(qbs, games); load_qb_teams(last)
    m = Model(**F['params'])
    upcoming = [g for g in games if int(g['season']) == last and g['home_score'] in ('', 'NA')]
    if not upcoming:
        return print('nfl games: no games left this season')
    week = min(int(g['week']) for g in upcoming if g['game_type'] == 'REG') if any(g['game_type'] == 'REG' for g in upcoming) else int(upcoming[0]['week'])
    nxt = [g for g in upcoming if int(g['week']) == week]
    qbinfo = resolve_qbs(games, last, week)
    proj = {}
    played_w = []
    for g in games:
        x, tx = m.feats(g)
        if g in nxt or (int(g['season']) == last):
            proj[g['game_id']] = (x, tx)
        m.update(g, box, qbs)
    b, tb, sd, tsd = F['coef'], F['tcoef'], F['sd'], F['tsd']
    out = []
    for g in [g for g in games if int(g['season']) == last and int(g['week']) <= week]:
        x, tx = proj[g['game_id']]
        parts = {f: round(b[f] * x[f], 1) for f in FEATS}
        mar = sum(b[f] * x[f] for f in FEATS)
        tot = sum(tb[f] * tx[f] for f in TFEATS)
        line = num(g['spread_line'], None); tl = num(g['total_line'], None)
        r = {'id': g['game_id'], 'espn': g['espn'], 'kick': kick(g), 'week': int(g['week']), 'date': g['gameday'], 'time': g['gametime'], 'day': g['weekday'][:3],
             'home': g['home_team'], 'away': g['away_team'], 'neutral': g['location'] == 'Neutral',
             'stadium': g['stadium'], 'roof': g['roof'], 'div': g['div_game'] == '1',
             'hqb': g['home_qb_name'], 'aqb': g['away_qb_name'],
             'margin': round(mar, 1), 'pHome': round(phi(mar / sd), 3), 'total': round(tot, 1),
             'hs': round((tot + mar) / 2, 1), 'as': round((tot - mar) / 2, 1), 'parts': parts,
             'elo': {'home': round(m.elo[team(g['home_team'])]), 'away': round(m.elo[team(g['away_team'])])},
             'line': line, 'tline': tl, 'ml': {'home': g['home_moneyline'], 'away': g['away_moneyline']}}
        if line is not None:
            e = mar - line
            r['edge'] = round(e, 1)
            r['cover'] = round(phi(abs(e) / sd), 3)     # model's side covers the line
            r['side'] = 'home' if e > 0 else 'away' if e < 0 else ''
        if tl is not None:
            r['over'] = round(phi((tot - tl) / tsd), 3)
        if g['home_score'] not in ('', 'NA'):
            r['final'] = {'home': int(num(g['home_score'])), 'away': int(num(g['away_score']))}
        out.append(r)
    # record and Elo now, for the cards
    rec = defaultdict(lambda: [0, 0, 0])
    for g in done:
        if int(g['season']) != last or g['game_type'] != 'REG':
            continue
        h, a, rr = g['home_team'], g['away_team'], num(g['result'])
        rec[h][0 if rr > 0 else 1 if rr < 0 else 2] += 1; rec[a][0 if rr < 0 else 1 if rr > 0 else 2] += 1
    # this season so far: how the model has done against the line (graded games)
    graded = [r for r in out if 'final' in r and r.get('edge') not in (None, 0)]
    w = sum(1 for r in graded if (r['final']['home'] - r['final']['away'] - r['line']) * r['edge'] > 0)
    p = sum(1 for r in graded if r['final']['home'] - r['final']['away'] == r['line'])
    res = {'season': last, 'week': week, 'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'games': [r for r in out if r['week'] == week], 'past': [r for r in out if r['week'] < week or 'final' in r],
           'rec': {t: '-'.join(map(str, v[:2])) + (f'-{v[2]}' if v[2] else '') for t, v in rec.items()},
           'elo': {t: round(v) for t, v in sorted(m.elo.items(), key=lambda z: -z[1])},
           'ats': {'w': w, 'l': len(graded) - w - p, 'p': p},
           'sd': sd, 'test': F['test'], 'coef': F['coef']}
    res.update(season_views(m, F, games, last, week, rec, qbinfo))
    try:
        old = json.load(open(OUT))
        if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in res.items() if k != 'asof'})):
            return print('nfl games: no change')
    except (OSError, ValueError):
        pass
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(f'nfl games: {last} week {week}, {len(res["games"])} games; model ATS this season {w}-{len(graded) - w - p}-{p}')


# ---------------------------------------------------------------- season views
DIVS = {'AFC East': ['BUF', 'MIA', 'NE', 'NYJ'], 'AFC North': ['BAL', 'CIN', 'CLE', 'PIT'],
        'AFC South': ['HOU', 'IND', 'JAX', 'TEN'], 'AFC West': ['DEN', 'KC', 'LV', 'LAC'],
        'NFC East': ['DAL', 'NYG', 'PHI', 'WAS'], 'NFC North': ['CHI', 'DET', 'GB', 'MIN'],
        'NFC South': ['ATL', 'CAR', 'NO', 'TB'], 'NFC West': ['ARI', 'LA', 'SF', 'SEA']}
DIV_OF = {t: d for d, ts in DIVS.items() for t in ts}
GROUPS = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR/TE', 'TE': 'WR/TE', 'OL': 'OL', 'EDGE': 'DL', 'DL': 'DL', 'LB': 'LB', 'CB': 'DB', 'S': 'DB'}
SIMS = 10000
RATING_SD = 2.5      # uncertainty in a team's true rating, points (drawn once a simulated season)


OUT_STATUS = {'Out', 'Injured Reserve', 'Doubtful', 'Suspended', 'Physically Unable to Perform', 'Non Football Injury'}


def _norm(n):
    import re
    n = re.sub(r'[^a-z ]', '', (n or '').lower().replace('-', ' '))
    return ' '.join(w for w in n.split() if w not in ('jr', 'sr', 'ii', 'iii', 'iv', 'v'))


def espn_qb_status():
    """QB injury statuses from ESPN's public injury report: normalized name -> status ('Out', 'Questionable', ...)."""
    try:
        req = urllib.request.Request('https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries', headers={'User-Agent': 'arkndjl.net arkboard'})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
    except Exception as e:      # the board still builds on nflverse's listed starters
        print('nfl games: ESPN injuries unavailable:', e)
        return {}
    return {_norm(i['athlete']['displayName']): i['status'] for t in j.get('injuries', []) for i in t.get('injuries', [])
            if (i.get('athlete', {}).get('position') or {}).get('abbreviation') == 'QB'}


def qb_depth(last):
    """Each team's QBs in depth-chart order from the latest snapshot of nflverse's ESPN depth charts: team -> [(gsis, name)]."""
    try:
        p = get(f'depth_charts_{last}.csv', f'{REL}/depth_charts/depth_charts_{last}.csv', fresh=True)
    except Exception as e:
        print('nfl games: depth charts unavailable:', e)
        return {}
    latest, qbs = '', []
    for r in rows(p):
        if r.get('pos_abb') == 'QB':
            if r['dt'] > latest:
                latest, qbs = r['dt'], []
            if r['dt'] == latest:
                qbs.append(r)
    dc = defaultdict(list)
    for r in sorted(qbs, key=lambda r: int(num(r['pos_rank'], 9))):
        k = (r['gsis_id'], r['player_name'])
        if k not in dc[team(r['team'])]:
            dc[team(r['team'])].append(k)
    return dc


def resolve_qbs(games, last, week):
    """Who starts at QB for each team: this week, and for the rest of the season. Rewrites the listed QB on every
    unplayed game to match (games.csv carries the last known starter forward, so an injured starter stays listed).

      QB1          the top QB on the team's depth chart (nflverse's ESPN depth charts; an injured starter keeps the
                   spot), else the QB with the most starts this season
      this week    the first QB down the depth chart whom ESPN's injury report doesn't have out (out, doubtful, IR,
                   suspended); without a depth chart, QB1 unless out, then the listed QB or the latest healthy fill-in
      later weeks  QB1, unless he's on IR (then this week's starter)
    """
    status = espn_qb_status()
    depth = qb_depth(last)
    played = [g for g in games if int(g['season']) == last and g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    starts = defaultdict(list)           # team -> [(week, gsis, name)]
    for g in played:
        for side in ('home', 'away'):
            if g[f'{side}_qb_id']:
                starts[team(g[f'{side}_team'])].append((int(g['week']), g[f'{side}_qb_id'], g[f'{side}_qb_name']))
    plays = defaultdict(float)
    for (gid, gsis), q in qbs_items():
        if gid.startswith(f'{last}_'):
            plays[(_QTEAM.get((gid, gsis), ''), gsis)] += q['plays']
    nxt = {}
    for g in games:
        if int(g['season']) == last and int(g['week']) == week and g['home_score'] in ('', 'NA'):
            for side in ('home', 'away'):
                nxt[team(g[f'{side}_team'])] = (g[f'{side}_qb_id'], g[f'{side}_qb_name'])
    st = lambda name: status.get(_norm(name), 'Active')
    out = lambda name: st(name) in OUT_STATUS
    info = {}
    for t in DIV_OF:
        ss = sorted(starts.get(t, []))
        cnt = defaultdict(lambda: [0, 0, ''])
        for wk, gsis, name in ss:
            c = cnt[gsis]; c[0] += 1; c[1] = wk; c[2] = name
        qb1 = max(cnt, key=lambda k: (cnt[k][0], cnt[k][1])) if cnt else nxt.get(t, ('', ''))[0]
        listed = nxt.get(t, ('', ''))
        if len(ss) >= 2 and ss[-1][1] == ss[-2][1] == listed[0] and listed[0] != qb1 and not out(listed[1]):
            qb1 = listed[0]                                  # benched: the new man has started twice running
        name1 = cnt[qb1][2] if qb1 in cnt else listed[1]
        dc = [q for q in depth.get(t, []) if q[0]]
        if dc:
            qb1, name1 = dc[0]
        now = (qb1, name1)
        healthy = [q for q in dc if not out(q[1])]
        if out(name1) and healthy:
            now = healthy[0]
        elif out(name1):
            if listed[0] and listed[0] != qb1 and not out(listed[1]):
                now = listed
            else:
                alts = {gsis: (wk, name) for wk, gsis, name in ss if gsis != qb1 and not out(name)}
                if alts:
                    k = max(alts, key=lambda k: (alts[k][0], plays.get((t, k), 0)))
                    now = (k, alts[k][1])
                else:
                    pool = [(n, gsis) for (tt, gsis), n in plays.items() if tt == t and gsis != qb1 and not out(_QNAME.get(gsis, ''))]
                    if pool:
                        k = max(pool)[1]
                        now = (k, _QNAME.get(k, k))
        later = now if st(name1) in ('Injured Reserve', 'Physically Unable to Perform', 'Non Football Injury') else (qb1, name1)
        info[t] = {'qb1': (qb1, name1), 'now': now, 'later': later, 'status': st(name1),
                   'statusNow': st(now[1])}
    for g in games:
        if int(g['season']) == last and g['home_score'] in ('', 'NA'):
            for side in ('home', 'away'):
                i = info.get(team(g[f'{side}_team']))
                if i:
                    q = i['now'] if int(g['week']) == week else i['later']
                    g[f'{side}_qb_id'], g[f'{side}_qb_name'] = q
    return info


def season_views(m, F, games, last, week, rec, qbinfo):
    """Power rankings, QB values, team WAR and a simulated rest of the season (playoff, division, seed, title odds)."""
    import random
    b = F['coef']
    L = m.lgepa()
    starter = {t: i['now'] for t, i in qbinfo.items()}          # this week's starter (resolve_qbs)
    later = {t: i['later'] for t, i in qbinfo.items()}          # the rest of the season
    teams = sorted(DIV_OF)

    def qpts(gsis):            # points a game over a replacement-level QB
        return b['qb'] * (m.qbval(gsis) - m.repl) * 38

    def rating(t, who=starter):   # neutral-field points against an average team, with a given starter
        q = who.get(t, ('', ''))[0]
        qa = (m.qbval(q) - m.rate(m.qbt, t, m.repl)) if q else 0.0
        return (b['elo'] * (m.elo[t] - 1505) / 25 + b['epa'] * (m.rate(m.off, t, L) - m.rate(m.dfn, t, L)) * 62 + b['qb'] * qa * 38)
    R = {t: rating(t) for t in teams}
    RL = {t: rating(t, later) for t in teams}
    avg = sum(RL.values()) / len(RL)
    R = {t: v - avg for t, v in R.items()}
    RL = {t: v - avg for t, v in RL.items()}

    # team WAR from the leaderboard (built first in the board job)
    tw = defaultdict(lambda: defaultdict(float))
    try:
        for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))['players']:
            tw[p['t']][GROUPS.get(p['pos'], 'other')] += p['war']
            tw[p['t']]['total'] += p['war']
    except (OSError, ValueError, KeyError):
        pass

    # simulate the rest of the regular season and the playoffs
    sd = F['sd']
    wins0 = {t: 0.0 for t in teams}
    for t, v in rec.items():
        if team(t) in wins0:
            wins0[team(t)] = v[0] + 0.5 * v[2]
    left = [g for g in games if int(g['season']) == last and g['game_type'] == 'REG' and g['home_score'] in ('', 'NA')]
    hfa = b['home']
    rest = lambda x: max(-7, min(7, num(x, 7) - 7))
    # this week's games with this week's starters, later games with each team's QB1 (unless he's on IR)
    rr = lambda g, t: (R if int(g['week']) == week else RL)[t]
    mus = [(team(g['home_team']), team(g['away_team']),
            rr(g, team(g['home_team'])) - rr(g, team(g['away_team'])) + (hfa if g['location'] != 'Neutral' else 0)
            + b['rest'] * (rest(g['home_rest']) - rest(g['away_rest']))) for g in left]
    keys = ('playoff', 'div', 'seed1', 'conf', 'sb')
    cnt = {t: dict.fromkeys(keys, 0) for t in teams}
    wsum = dict.fromkeys(teams, 0.0)
    rng = random.Random(7)
    for _ in range(SIMS):
        shock = {t: rng.gauss(0, RATING_SD) for t in teams}
        w = dict(wins0)
        for h, a, mu in mus:
            if rng.gauss(mu + shock[h] - shock[a], sd) > 0:
                w[h] += 1
            else:
                w[a] += 1
        for t in teams:
            wsum[t] += w[t]
        tb = {t: w[t] + rng.random() * 1e-3 + R[t] * 1e-5 for t in teams}   # ties: a coin flip, nudged by rating
        champs = []
        for conf in ('AFC', 'NFC'):
            divw = [max(ts, key=lambda t: tb[t]) for d, ts in DIVS.items() if d.startswith(conf)]
            wc = sorted([t for d, ts in DIVS.items() if d.startswith(conf) for t in ts if t not in divw], key=lambda t: -tb[t])[:3]
            seeds = sorted(divw, key=lambda t: -tb[t]) + wc
            for t in divw:
                cnt[t]['div'] += 1
            for t in seeds:
                cnt[t]['playoff'] += 1
            cnt[seeds[0]]['seed1'] += 1
            seed = {t: i for i, t in enumerate(seeds)}

            def play(h, a, neutral=False):
                mu = RL[h] - RL[a] + shock[h] - shock[a] + (0 if neutral else hfa)
                return h if rng.gauss(mu, sd) > 0 else a
            alive = [seeds[0]] + [play(seeds[i], seeds[7 - i]) for i in (1, 2, 3)]
            while len(alive) > 1:
                alive.sort(key=lambda t: seed[t])
                alive = [play(alive[i], alive[-1 - i]) for i in range(len(alive) // 2)]
            cnt[alive[0]]['conf'] += 1
            champs.append(alive[0])
        cnt[(lambda h, a: h if rng.gauss(RL[h] - RL[a] + shock[h] - shock[a], sd) > 0 else a)(*champs)]['sb'] += 1

    power = []
    for t in teams:
        q = starter.get(t, ('', ''))
        power.append({'t': t, 'dv': DIV_OF[t], 'rating': round(R[t], 1), 'elo': round(m.elo[t]),
                      'off': round(m.rate(m.off, t, L) - L, 3), 'dfn': round(m.rate(m.dfn, t, L) - L, 3),
                      'qb': q[1], 'qbPts': round(qpts(q[0]), 1) if q[0] else None,
                      'qb1': qbinfo[t]['qb1'][1] if qbinfo[t]['qb1'][0] != q[0] else None, 'qb1Status': qbinfo[t]['status'], 'rec': '-'.join(map(str, rec[t][:2])) + (f'-{rec[t][2]}' if rec[t][2] else '') if t in rec else '0-0',
                      'war': round(tw[t]['total'], 1) if t in tw else None,
                      'wars': {k: round(v, 1) for k, v in tw[t].items() if k != 'total'} if t in tw else {},
                      'wins': round(wsum[t] / SIMS, 1), **{k: round(cnt[t][k] / SIMS, 3) for k in keys}})
    power.sort(key=lambda r: -r['rating'])
    for i, r in enumerate(power):
        r['rk'] = i + 1

    # QB table: everyone with 60+ plays this season, valued on his weighted career line
    seen = defaultdict(lambda: [0.0, 0.0, set()])
    for (gid, gsis), q in qbs_items():
        if gid.startswith(f'{last}_'):
            s_ = seen[gsis]; s_[0] += q['epa']; s_[1] += q['plays']; s_[2].add(_QTEAM.get((gid, gsis), ''))
    st_ids = {v[0] for v in starter.values()}
    qb1_ids = {i['qb1'][0]: i for i in qbinfo.values()}
    for gsis in st_ids | set(qb1_ids):
        seen[gsis]
    qbt = []
    for gsis, (e, n, tms) in seen.items():
        if n < 60 and gsis not in st_ids and gsis not in qb1_ids:
            continue
        i = qb1_ids.get(gsis)
        role = 'starter' if i else 'fill-in' if gsis in st_ids else 'backup'
        if not tms:
            tms = {t for t, ii in qbinfo.items() if gsis in (ii['qb1'][0], ii['now'][0])}
        nm = _QNAME.get(gsis) or next((ii['qb1'][1] if ii['qb1'][0] == gsis else ii['now'][1] for ii in qbinfo.values() if gsis in (ii['qb1'][0], ii['now'][0])), gsis)
        qbt.append({'n': nm, 't': '/'.join(sorted(x for x in tms if x)), 'plays': int(n),
                    'epa': round(e / n, 3) if n else None, 'val': round(m.qbval(gsis), 3), 'pts': round(qpts(gsis), 1),
                    'starter': gsis in st_ids, 'role': role, 'status': i['status'] if i and i['status'] != 'Active' else None})
    qbt.sort(key=lambda r: -r['pts'])
    return {'power': power, 'qbs': qbt, 'sims': SIMS, 'ratingSd': RATING_SD, 'left': len(left)}


def qbs_items():
    for gid, lst in _QIDX.items():
        for gsis, q in lst:
            yield (gid, gsis), q


if __name__ == '__main__':
    fit() if '--fit' in sys.argv else build()
