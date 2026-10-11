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


def load_qb_teams(last):
    for y in range(FIRST, last + 1):
        for r in rows(os.path.join(CACHE, f'stats_player_week_{y}.csv')):
            if r['position'] == 'QB' and r.get('game_id'):
                _QTEAM[(r['game_id'], r['player_id'])] = team(r['team'])


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
        r = {'id': g['game_id'], 'week': int(g['week']), 'date': g['gameday'], 'time': g['gametime'], 'day': g['weekday'][:3],
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
    try:
        old = json.load(open(OUT))
        if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in res.items() if k != 'asof'})):
            return print('nfl games: no change')
    except (OSError, ValueError):
        pass
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(f'nfl games: {last} week {week}, {len(res["games"])} games; model ATS this season {w}-{len(graded) - w - p}-{p}')


if __name__ == '__main__':
    fit() if '--fit' in sys.argv else build()
