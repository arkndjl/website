#!/usr/bin/env python3
"""NFL game projections for the NFL ARKBOARD (data/nfl_games.json), and the model behind them (data/nfl_games_fit.json).

    python3 scripts/nfl_games.py          # this week's projections (stdlib only; run by the cfb board job)
    python3 scripts/nfl_games.py --fit    # walk-forward backtest 2012-2025 against the closing line, refit (numpy)

Data: nflverse (nfldata games.csv: scores, closing spread and total, starting QBs, rest, roof; stats_player_week:
EPA by player and game; injuries: game status reports, 2016 on), ESPN's injury report, Rotoballer's NFL news. Every feature is known before kickoff.

Margin (home minus away, points) is a linear model on:
    elo     Elo difference (538's football Elo: K 20, margin multiplier, 1/3 regression to the mean each offseason)
    (epa    net EPA a play, opponent-adjusted: dropped Oct 21 2026 by the shared harness (scripts/harness.py,
            data/model_ledger.json): the margin is better without it on 2015-20 (t +.75) and 2021-25 (t +.10) once Elo,
            the QB term and the market rating are in. The EPA ratings stay in the total)
    qb      the starting QB against the team's recent QB play: his EPA a play (shrunk toward a backup's level by
            his volume) minus the team's weighted QB EPA a play, so a backup starting moves the line
    rest    rest days, home minus away (capped at 7 each way: byes, short weeks)
    home    1 at a home site, 0 neutral
    inj     injuries, away minus home: each non-QB on the game status report at his WAR a game (nfl_war.py, to that
            week) x 36 points a win x his chance to miss by status (2016-25 reports against snap counts). This week's
            reports merge the league's report, ESPN's and Rotoballer's news, latest item first; a questionable QB
            starts at his chance to play, his backup in for the rest. A questionable non-QB on the league's report is
            priced by how he practised on the last day (PRACTICE_Q, Nov 1 2026)
            Tested Oct 2026 and not kept: returning players (missed the team's last game, active again, at WAR a game x
            P(plays)), all of them or only those listed out or doubtful the week before: walk-forward MAE worse in
            2017-20 (t +1.6, +1.1), better in 2021-25 (t -1.2, -1.3), so no consistent gain
Tested Oct 18 2026 and not kept (scripts/nfl_games_research.py, data/nfl_games_research.json): every input the college
model uses or tried, as ratings from nflverse play-by-play (scripts/nfl_pbp.py), each added to this model's walk-forward:
success rate (all, win prob 10-90%), EPA without garbage time, early-down success and EPA, EPA a dropback, 3rd-down
rate, red-zone success and points a trip, explosiveness, 20+ yard plays, stuff rate, line yards, field position,
CPOE (team and starting QB), special teams EPA (kicking, kickoffs and punts), 4th-down go rate and pass rate over
expected, head coach career cover margin, first-year coach (and x Elo), wind x Elo, recent form, last season's WAR of
the active roster (flat or fading), a QB prior by draft slot, injuries split fresh/continuing or by unit, OL and DB
injury clusters; totals: pace, success, explosiveness, red zone, field position, pass rate. None gained on 2015-20 at
t <= -1.5 with 2021-25 agreeing (the best, 3rd-down rate, flipped sign between the two). Win probability's sd is
already calibrated (fit to wins 12.75 vs 12.9; sd scaled by the total: no gain). The market rating and Elo carry
what these measure. Also not kept (Oct 18): the visitor's travel distance and time zones, a west-coast visitor at a
1pm Eastern kickoff, a warm or dome visitor in the cold, Denver at home, byes and short weeks beyond rest days, the
referee's career home result over the line (margin) and total over the line (totals: better 2015-20, worse 2021-25).
Opening lines, line movement and news timestamps have no history in nflverse, so they can't be tested
Player projections (Oct 18, after PR #253): the projected lineup (each non-QB's WAR a game x his chance to play from
nfl_fantasy.py's availability table, home minus away), the same against who played the team's last game, and that in
place of the injury term all fail (2015-20 t -0.3, +2.2, +1.8). The fantasy point projections themselves are built
from this model's implied team totals, so they can't feed it back
Provisional values (Oct 21, scripts/nfl_inj_prov_research.py, data/nfl_inj_prov_research.json): listed players with
little or no WAR shrunk toward their draft slot's WAR a game instead of replacement (2017-20 t +0.9, 2021-25 +0.3), and
each listed player's cost net of 25/50/100% of the next man up's value (+0.3/+0.7/+1.3) all fail: kept at replacement
Also not kept (Oct 18, scripts/nfl_splits_research.py, data/nfl_splits_research.json): situational splits and coach
traits, each opponent-adjusted and shrunk by a prior of 2, 6 or 12 games: 3rd-down conversion over the league's rate
from the same distance (all, short 1-3, medium 4-6 over expected and raw, long 7+), 4th-down conversion (raw and over
expected), 3rd and 4th downs together, goal-to-go conversion, two-minute offense EPA, no-huddle rate, penalty yards,
2-point tries a touchdown; the kicker (field goals and extra points over the league's make rate by distance, range on
50+ tries) alone, x an expected close game and x wind or cold; 4th-down conversion x the coach's aggressiveness.
None gained on 2015-20 at t <= -1.5 (3rd-down conversion over expected fit a negative weight: teams that convert
more than their distances predict regress, and EPA already counts the conversions). Kicker x wind/cold helped
2021-25 only (t -2.0; 2015-20 +0.6)
Also not kept (Oct 19, scripts/nfl_season_backtest.py, data/nfl_season_backtest.json): ridge team ratings (weighted
least squares on margins, capped or not, decayed by week and season, a prior of 2-32 games), joining the features or
replacing Elo: best on 2015-20 (replace, half-life 12 weeks) MAE 9.951 vs 9.965, t -0.4; 2021-25 10.039 vs 10.060,
t -0.7. Blending with the close (w x model + (1 - w) x line, report only): w .30 best on 2015-20 (MAE 9.808 vs the
close's 9.847, t -1.6; win log loss .6117 vs .6139, t -1.6) but worse on 2021-25 (9.793 vs 9.762, t +1.5; .6128 vs
.6107, t +1.7), where the best w is 0
Roster moves (Oct 21 2026, scripts/nfl_roster.py, scripts/nfl_offseason_research.py, data/nfl_offseason_research.json):
the ratings open each season from last season's team (Elo a third to the mean, EPA at .7, market at .4; the QB term
already reads a new starter). Added on top, at a fixed share outside the fit: .25 x each team's offseason moves in
projected WAR (week-1 roster minus last season's players; free agency, trades, cuts, the draft class; QBs out) x 36/17
points, fading 0.5 ** (games played / 8). Walk-forward MAE 2015-20 -0.012 (t -1.58), 2021-25 -0.009 (t -1.33); weeks
1-4 -0.015 / -0.003 (t -0.7 / -0.1). Not kept: the same as a refit input (worse: the history starts in 2014), the
rookies alone, the kept roster's aging and regression, the roster's projection against last season's WAR, QBs in the
sums, the QB term weighted up early in the season (all t > -1.5 on 2015-20)
QB aging (Oct 30 2026, scripts/nfl_aging_research.py): the starter's EPA a play moved by a walk-forward age line
(about -.004 a year, centred 28) at the summer, or as its own input, flat or fading; worse on 2015-20 (t +1.2 / +1.4),
better only on 2021-25 (t -2.1). Not kept.
Total: points for and against, exponentially weighted (same half-life), plus a dome flag.
Win probability and cover chances: normal around the margin with the backtest's residual SD.
Season odds: the rest of the regular season simulated (each team's rating shifted once a sim by its uncertainty,
rating_sd), seeds by the NFL's tiebreakers (League; checked against every season's real field, 2002-25), then the
playoffs.
The backtest refits each season on the seasons before it and scores that season (2012-2025), against the closing
line (games.csv spread_line, the home side's expected margin) on margin error, and on ATS record where the model and
the line disagree.
"""
import csv
import json
import math
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM   # noqa: E402  the shared player-name key (scripts/names.py)
import cover as CV   # noqa: E402  cover and over chances as the line leaves them

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
FIT = os.path.join(ROOT, 'data', 'nfl_games_fit.json')
OUT = os.path.join(ROOT, 'data', 'nfl_games.json')
INJ_OUT = os.path.join(ROOT, 'data', 'nfl_injuries.json')     # this week's statuses, for the fantasy projections
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
FIRST = 2009                       # EPA history starts here; ratings warm up for three seasons before scoring
FEATS = ['elo', 'qb', 'rest', 'home', 'inj', 'mkt']
LK_QB, LK_INJ = 0.45, 1.36           # the qb and inj terms' points a unit (fit Oct 2026), for the lineup gap      # epa out Oct 21 2026 (harness re-score)
TFEATS = ['pts', 'dome', 'one', 'epa', 'tmkt']
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
    def __init__(self, hl=6.0, carry=0.5, qb_n0=250.0, qb_repl=-0.12, elo_k=20.0, mk=0.2, mrev=0.4, tk=0.4, trev=0.0,
                 lk=0.0, lk_mkt=0.0, lk_parts='both', inj=None):
        self.a = 0.5 ** (1 / hl)         # weight decay a game
        # lineup-adjusted ratings: each side's lineup gap that game in points (the QB who started against the team's
        # recent QB play, and the injury report's cost; LK_QB, LK_INJ) taken off the result before Elo updates (lk)
        # and allowed in the closing spread before the market rating updates (lk_mkt). inj: game id -> injury costs
        self.lk, self.lk_mkt, self.inj = lk, lk_mkt, inj or {}
        self.lq, self.li = (LK_QB if lk_parts != 'inj' else 0.0), (LK_INJ if lk_parts != 'qb' else 0.0)
        self._gap = {}
        self.carry, self.n0, self.repl, self.k = carry, qb_n0, qb_repl, elo_k
        # market ratings: each team's points against an average team as the closing spreads have priced it, and its
        # scoring environment as the closing totals have, nudged toward each earlier game's line (never the game's own)
        self.mk, self.mrev, self.tk, self.trev = mk, mrev, tk, trev
        self.mkt = defaultdict(float)
        self.tm = defaultdict(float)
        self.tlg = 44.0
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
        for t in list(self.mkt):
            self.mkt[t] *= self.mrev
        for t in list(self.tm):
            self.tm[t] *= self.trev
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
             'rest': rest(g['home_rest']) - rest(g['away_rest']), 'home': home, 'inj': 0.0,
             'mkt': self.mkt[h] - self.mkt[a]}
        if self.lk or self.lk_mkt:
            r = self.inj.get(g['game_id']) or (0.0, 0.0, 0.0, 0.0)
            self._gap[g['game_id']] = (self.lq * 38 * qadj(h, g['home_qb_id']) - self.li * (r[0] + r[1]),
                                       self.lq * 38 * qadj(a, g['away_qb_id']) - self.li * (r[2] + r[3]))
        P = self.lgpts
        pts = (self.rate(self.pf, h, P) + self.rate(self.pa, a, P) + self.rate(self.pf, a, P) + self.rate(self.pa, h, P)) / 2
        both = lambda t: self.rate(self.off, t, L) + self.rate(self.dfn, t, L)     # EPA a play for and against
        tx = {'pts': pts, 'dome': 1.0 if g['roof'] in ('dome', 'closed') else 0.0, 'one': 1.0,
              'epa': (both(h) + both(a) - 4 * L) * 62, 'tmkt': self.tlg + self.tm[h] + self.tm[a]}
        return x, tx

    def market(self, g):
        """Fold a game's lines into the market ratings once it kicks off (or, for later weeks' projections, as listed now)."""
        h, a = team(g['home_team']), team(g['away_team'])
        line, tl = num(g['spread_line'], None), num(g['total_line'], None)
        if line is not None:
            gp = self._gap.get(g['game_id'], (0.0, 0.0))
            e = line - (self.mkt[h] - self.mkt[a] + (0 if g['location'] == 'Neutral' else 1.8) + self.lk_mkt * (gp[0] - gp[1]))
            self.mkt[h] += self.mk * e; self.mkt[a] -= self.mk * e
        if tl is not None:
            e = tl - (self.tlg + self.tm[h] + self.tm[a])
            self.tm[h] += self.tk * e; self.tm[a] += self.tk * e; self.tlg += 0.01 * e

    def update(self, g, box, qbs):
        self.market(g)
        if g['home_score'] in ('', 'NA'):
            return
        h, a = team(g['home_team']), team(g['away_team'])
        hs, as_ = num(g['home_score']), num(g['away_score'])
        # Elo, 538's margin multiplier; home field 48 Elo at a home site
        hfa = 0 if g['location'] == 'Neutral' else 48
        gp = self._gap.pop(g['game_id'], (0.0, 0.0))
        d = self.elo[h] + hfa - self.elo[a] + 25 * self.lk * (gp[0] - gp[1])
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


def walk(games, box, qbs, params, collect=True, inj=None):
    m = Model(inj=inj, **params)
    out = []
    for g in games:
        x, tx = m.feats(g)
        if collect:
            out.append((g, x, tx))
        m.update(g, box, qbs)
    return m, out


# ---------------------------------------------------------------- injuries
PTS_PER_WIN = 36.0    # season point differential a win is worth (so a player's WAR a game x 36 = points a game)
INJ_FIRST = 2016      # nflverse game status reports and snap counts start here
GONE = {'Injured Reserve', 'Physically Unable to Perform', 'Non Football Injury', 'Suspended', 'Out (season)'}


# a questionable non-QB's chance to play by his last practice that week (nflverse game status reports x snap counts,
# 2016-25; Nov 1 2026 sweep, scripts/sweep_nov01/nfl_practice.py): (practice, played the team's last game) -> P(plays).
# Fit on 2016-20, held 2021-25 player Brier .2080 vs .2202 for the flat .75/.5 (t -5.8); game model MAE better in both
# periods (2017-20 -.010, t -1.25; 2021-25 -.004, t -0.7), and the change also predicts result minus the close (b 2.3, t 1.6;
# 3.7, t 2.5): the close prices practice news only in part. Pooled 2016-25 rates
PRACTICE_Q = {('dnp', True): 0.48, ('limited', True): 0.76, ('full', True): 0.90,
              ('dnp', False): 0.23, ('limited', False): 0.55, ('full', False): 0.70}


def practice_of(s):
    """'dnp', 'limited', 'full' or None from the report's practice_status"""
    s = (s or '').strip().lower()
    return 'full' if s.startswith('full') else 'limited' if s.startswith('limited') else 'dnp' if s.startswith('did not') else None


def play_prob(status, recent=True, practice=None):
    """Chance a listed player plays. Out 0; doubtful .02, questionable .75 for a player who played the team's last
    game and .5 for one who didn't (2016-25 game status reports against snap counts: 1.6%, 75% and 51%), or by his last
    practice when the league's report gives it (PRACTICE_Q: did not participate .48, limited .76, full .90); probable .95
    (news only: the league dropped the designation in 2016); last week's designation before this week's report, CARRY.
    Players on IR, PUP or suspended are off the roster: the team's ratings already carry the games without them, as in
    the weekly reports, which don't list them."""
    if status in (None, '', 'Active'):
        return 1.0
    if status.endswith(' (last week)'):
        return CARRY.get(status[:-12], 1.0)
    if status == 'Out':
        return 0.0
    if status == 'Doubtful':
        return 0.02
    if status == 'Questionable':
        q = PRACTICE_Q.get((practice, bool(recent)))
        if q is not None:
            return q
        return 0.75 if recent else 0.5
    if status == 'Probable':
        return 0.95
    return 1.0


def player_value(prev, cur):
    """WAR a game: last season at half weight plus this season to date, shrunk with three replacement-level games."""
    return (0.5 * prev[0] + cur[0]) / (0.5 * prev[1] + cur[1] + 3)


def injury_history(games, years, live=None):
    """game_id -> [home fresh, home continuing, away fresh, away continuing] injury cost in points (non-QBs; the QB
    term already has the starter). Fresh: the player played the team's last game, so its ratings don't yet carry
    the loss; continuing: he missed it too. Each player's value is his WAR a game to that week (nfl_war.py's model,
    no look-ahead), costed at 1 - P(plays) by his status on the game status report."""
    import nfl_war as W
    cp = os.path.join(CACHE, 'inj_hist_v2.json')      # v2: questionable by last practice (Nov 1 2026)
    try:
        cache = json.load(open(cp))
    except (OSError, ValueError):
        cache = {}
    for y in years:
        if str(y) in cache and y != live:
            continue
        maps = W.gsis_map(y)
        prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
        top = max([int(g['week']) for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')] + [1])
        led = {w: W.war_ledger(y, thru=w, maps=maps) for w in range(1, min(top + 1, 19) + 1)}
        rep = defaultdict(list)
        for r in rows(get(f'injuries_{y}.csv', f'{REL}/injuries/injuries_{y}.csv')):
            if r['report_status'] and r['position'] != 'QB':
                rep[(team(r['team']), int(r['week']))].append((r['gsis_id'], r['report_status'], practice_of(r['practice_status'])))
        sg = [g for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')]
        last_wk = {}
        out = {}
        for g in sg:
            w = int(g['week'])
            row = []
            for side in ('home', 'away'):
                t = team(g[f'{side}_team'])
                pw = last_wk.get(t)
                fresh = cont = 0.0
                for gsis, stt, prac in rep.get((t, w), []):
                    L = led[min(w, 19, top + 1)]
                    v = player_value(prev.get(gsis, (0.0, 0)), L.get(gsis, (0.0, 0)))
                    if pw is None or pw >= 18 or w > 18:
                        played = True
                    else:
                        played = led[pw + 1].get(gsis, (0, 0))[1] > led[pw].get(gsis, (0, 0))[1]
                    c = (1 - play_prob(stt, played, prac)) * max(v, 0.0) * PTS_PER_WIN
                    if played:
                        fresh += c
                    else:
                        cont += c
                row += [round(fresh, 3), round(cont, 3)]
                last_wk[t] = w
            out[g['game_id']] = row
        cache[str(y)] = out
        if y != live:
            json.dump(cache, open(cp, 'w'))
        print('injuries', y, len(out))
    return {gid: v for y in years for gid, v in cache[str(y)].items()}


# live reports: the league's game status report (nflverse, posted Wednesday to Friday), ESPN's injury report and
# Rotoballer's player news; for each player the latest dated item wins
TEAMS = {'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills',
         'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns',
         'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
         'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars', 'KC': 'Kansas City Chiefs',
         'LV': 'Las Vegas Raiders', 'LAC': 'Los Angeles Chargers', 'LA': 'Los Angeles Rams', 'MIA': 'Miami Dolphins',
         'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
         'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers', 'SF': 'San Francisco 49ers',
         'SEA': 'Seattle Seahawks', 'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'}
BY_FULL = {v: k for k, v in TEAMS.items()}
BY_MASCOT = {v.split()[-1].lower(): k for k, v in TEAMS.items()}
ESPN_STATUS = {'Out': 'Out', 'Doubtful': 'Doubtful', 'Questionable': 'Questionable', 'Day-To-Day': 'Questionable',
               'Probable': 'Probable', 'Active': 'Active', 'Injured Reserve': 'Injured Reserve', 'Suspension': 'Suspended',
               'Suspended': 'Suspended', 'Physically Unable to Perform': 'Physically Unable to Perform',
               'Reserve-Ret': 'Suspended', 'Non Football Injury': 'Non Football Injury'}
RB_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'


def status_of(text):
    """A status from one clause of news (the CFB board's reading, with probable kept apart from active): the most
    serious reading wins; None = not availability news."""
    import re
    t = (text or '').lower()
    if re.search(r"season-ending|out for (the )?(rest of the |remainder of the )?(season|year)|(rest|remainder) of the (season|year)|miss the (rest|remainder)|torn acl|achilles|placed on (injured reserve|ir)\b|lands on ir|to ir\b|career-ending", t):
        return 'Out (season)'
    if re.search(r"doubtful|unlikely to play", t):
        return 'Doubtful'
    if re.search(r"\bruled out|\bwill miss|\bto miss|\bmiss(es)? time|\bwon't play|\bwill not play|\bnot expected to play|\bis out\b|\bout\b(?! of)|\bsidelined|\binactive|healthy scratch|\bwill sit|\bnot dress|\bout for a (week|month)", t):
        return 'Out'
    if re.search(r"questionable|game-time decision|day-to-day|uncertain to play|status (is )?uncertain|limited in practice|week-to-week", t):
        return 'Questionable'
    if re.search(r"probable|optimistic|hopeful|expected to play|on track to (play|return)|trending toward playing|should play|full practice|practiced fully", t):
        return 'Probable'
    if re.search(r"\bcleared|will play|good to go|returns? to (action|the lineup)|back in the lineup|set to return|will return|will start|making his return|off (the )?injury report|activated|(that|now) he's healthy|(is|fully|now) healthy\b(?! scratch)|back to full health", t):
        return 'Active'
    return None


def fetch_rotoballer(pages=8):
    """Rotoballer's NFL news (15 items a page, newest first): headline, time, team (from the card's team color)."""
    import re
    items, seen = [], set()
    for pg in range(1, pages + 1):
        u = 'https://www.rotoballer.com/player-news?sport=nfl' if pg == 1 else f'https://www.rotoballer.com/player-news/page/{pg}?sport=nfl'
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': RB_UA}), timeout=30) as r:
                h = r.read().decode('utf-8', 'replace')
        except Exception:
            break
        fresh = 0
        for c in h.split('<div class="rb-news-card')[1:]:
            m = re.search(r'title="Permanent Link to ([^"]+)"', c); ts = re.search(r'data-ts="(\d+)"', c)
            if not m or not ts or (m.group(1) + ts.group(1)) in seen:
                continue
            seen.add(m.group(1) + ts.group(1)); fresh += 1
            title = re.sub(r'&#0?39;|&#8217;', "'", m.group(1)).replace('&amp;', '&')
            tm = re.search(r'teamLogo (\w+?)bg', c)
            i = c.find("class='post-time'")
            body = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c[i:] if i > 0 else '')).replace('&#039;', "'").replace('&amp;', '&')
            body = re.sub(r'^[^A-Z]*?ET\s*', '', body.split("class='newsByline'")[0]).strip()
            items.append({'title': title, 'ts': int(ts.group(1)), 'team': BY_MASCOT.get(tm.group(1)) if tm else None, 'body': body[:700]})
        if not fresh:
            break
    return items


def modified(url):
    """The Last-Modified time of a download (epoch seconds), 0 if the server doesn't say."""
    import email.utils
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'arkndjl.net arkboard'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return email.utils.parsedate_to_datetime(r.headers['Last-Modified']).timestamp()
    except Exception:
        return 0.0


# last week's designation, carried into a week whose report isn't out yet: what became of each Q, D and O on the
# next week's report, 2021-25 (scripts/nfl_inj_carry.py): cleared or listed with no designation (plays), questionable
# again (plays at the questionable rate), doubtful, out. Players moved to a reserve list are left out: the roster has them.
CARRY = {'Questionable': 0.84, 'Doubtful': 0.55, 'Out': 0.38}
LATE = 26 * 3600      # news this close to kickoff (Saturday's activations, gameday inactives) beats the final report


def live_injuries(last, week, games):
    """This week's statuses: team -> {gsis: {name, pos, status, src, ts}}, and the sources' counts. Every status is
    for this week's game:
      the league's report  this week's practice and game status report (nflverse, Monday to Friday). Once a team's
                           report is out, a player not on it, practicing in full, or left without a designation on
                           the final report is cleared; the report's designation beats earlier news.
      news                 ESPN's injury report and Rotoballer's news, dated after the team's last kickoff (older
                           items are about an earlier game). A designation ESPN carries over from last week counts
                           as last week's (CARRY) until this week's report replaces it; ESPN's return date past
                           this week's game, or Rotoballer's news, is this week's.
      reserve lists        a player on IR, PUP or another reserve list (the roster or the report says so) stays off
                           whatever the news, and is never cleared."""
    import datetime
    import re
    ros, by_name, by_espn = {}, defaultdict(list), {}
    try:
        try:
            rp = get(f'roster_{last}.csv', f'{REL}/rosters/roster_{last}.csv', fresh=True)
        except Exception as e:                   # the last good pull: statuses move daily, the roster less
            print('nfl games: roster refresh failed, using the cached pull:', e)
            rp = get(f'roster_{last}.csv', f'{REL}/rosters/roster_{last}.csv')
        for r in rows(rp):
            if r['gsis_id']:
                ros[r['gsis_id']] = r
                by_name[_norm(r['full_name'])].append(r['gsis_id'])
                if r.get('espn_id'):
                    by_espn[r['espn_id']] = r['gsis_id']
    except Exception as e:
        print('nfl games: roster unavailable:', e)
    n = Counter()

    def epoch(s):
        try:
            return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
        except (ValueError, AttributeError):
            return 0.0
    # each team's last kickoff (news from before it is about an earlier game) and this week's
    lastko, ko = {}, {}
    for g in games:
        if int(g['season']) != last:
            continue
        k = epoch(kick(g))
        for side in ('home', 'away'):
            t = team(g[f'{side}_team'])
            if g['home_score'] not in ('', 'NA'):
                lastko[t] = max(lastko.get(t, 0), k)
            elif int(g['week']) == week:
                ko[t] = k
    news = defaultdict(dict)
    team_m = {}

    def put(t, gsis, name, pos, stt, ts, src, firm):
        if not stt or (stt not in GONE and ts <= lastko.get(t, 0)):
            return
        cur = news[t].get(gsis)
        if cur is None or ts >= cur['ts']:
            news[t][gsis] = {'name': name, 'pos': pos, 'status': stt, 'src': src, 'ts': ts, 'firm': firm or stt in GONE}
    try:
        req = urllib.request.Request('https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries', headers={'User-Agent': 'arkndjl.net arkboard'})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
        for tt in j.get('injuries', []):
            t = BY_FULL.get(tt.get('displayName'))
            for i in tt.get('injuries', []):
                a = i.get('athlete', {})
                eid = re.search(r'/id/(\d+)', json.dumps(a.get('links', [])))
                gsis = by_espn.get(eid.group(1)) if eid else None
                if not gsis:
                    ids = [x for x in by_name.get(_norm(a.get('displayName')), []) if ros[x]['team'] == t]
                    gsis = ids[0] if len(ids) == 1 else None
                if not gsis and t:                   # a spelling that fits on his team (Mike / Michael, a typo)
                    if t not in team_m:
                        team_m[t] = NM.Matcher([r for r in ros.values() if r['team'] == t], name='full_name', team=None, pos='position')
                    hit, _ = team_m[t].find(a.get('displayName'), pos=(a.get('position') or {}).get('abbreviation'))
                    gsis = hit['gsis_id'] if hit else None
                if t and gsis:
                    stt = ESPN_STATUS.get(i.get('status'), 'Active')
                    back = epoch(((i.get('details') or {}).get('returnDate') or '') + 'T23:59:59Z')
                    firm = stt not in CARRY or bool(ko.get(t) and back > ko[t] + 86400)
                    put(t, gsis, a.get('displayName'), (a.get('position') or {}).get('abbreviation', ''), stt,
                        epoch(i.get('date')), 'espn', firm)
                    n['espn'] += 1
    except Exception as e:
        print('nfl games: ESPN injuries unavailable:', e)
    try:
        for it in fetch_rotoballer():
            clauses = [c for c in re.split(r',\s*|\s+and\s+|;\s*', it['title'])]
            sts = [status_of(c) for c in clauses]
            for k in range(len(sts) - 2, -1, -1):
                if not sts[k]:
                    sts[k] = sts[k + 1]
            if not any(sts):
                first = re.split(r'(?<=[.!?])\s', it['body'], maxsplit=1)[0]
                clauses, sts = [it['title']], [status_of(first)]
            for c, stt in zip(clauses, sts):
                if not stt:
                    continue
                words = _norm(c).split()
                for L_ in (3, 2):
                    hit = None
                    for k in range(len(words) - L_ + 1):
                        ids = by_name.get(_norm(' '.join(words[k:k + L_])), [])
                        ids = [x for x in ids if not it['team'] or ros[x]['team'] == it['team']]
                        if len(ids) == 1:
                            hit = ids[0]; break
                    if hit:
                        r = ros[hit]
                        put(team(r['team']), hit, r['full_name'], r['position'], stt, float(it['ts']), 'rotoballer', True)
                        n['rotoballer'] += 1
                        break
    except Exception as e:
        print('nfl games: Rotoballer news unavailable:', e)
    # the league's report for this week's games
    rep, asof = defaultdict(dict), 0.0
    url = f'{REL}/injuries/injuries_{last}.csv'
    try:
        for r in rows(get(f'injuries_{last}.csv', url, fresh=True)):
            if int(r['week']) == week and r.get('game_type', 'REG') == 'REG' and r['gsis_id']:
                rep[team(r['team'])][r['gsis_id']] = r
        asof = modified(url) or time.time() - 86400
    except Exception as e:
        print('nfl games: game status report unavailable:', e)
    out = defaultdict(dict)
    for t in set(news) | set(rep):
        R = rep.get(t, {})
        final = any(r['report_status'] for r in R.values())
        for gsis in set(news[t]) | set(R):
            v, L = news[t].get(gsis), R.get(gsis)
            fresh = bool(v and v['firm'] and v['ts'] > asof)      # newer than the report
            r = ros.get(gsis, {})
            off = r.get('status') == 'RES' and not (v and v['src'] == 'rotoballer' and v['status'] == 'Active')
            if v and v['status'] in GONE:
                e = v
            elif off:
                e = {'status': 'Physically Unable to Perform' if r.get('status_description_abbr') == 'R04' else 'Injured Reserve', 'src': 'roster', 'ts': 0.0}
            elif L and L['report_status']:
                late = v and v['firm'] and v['ts'] > max(asof, ko.get(t, 0) - LATE)
                e = v if late else {'status': L['report_status'], 'src': 'league', 'ts': asof,
                                    'prac': practice_of(L.get('practice_status'))}
            elif R and (final or not L or L['practice_status'].startswith('Full')):
                e = v if fresh else {'status': 'Active', 'src': 'league', 'ts': asof}
            else:
                e = v
            if not e:
                continue
            e = dict(e)
            if not e.get('firm', True) and e['status'] in CARRY:
                e['status'] += ' (last week)'
            e['name'] = e.get('name') or (L or {}).get('full_name') or r.get('full_name', gsis)
            e['pos'] = e.get('pos') or (L or {}).get('position') or r.get('position', '')
            e.pop('firm', None)
            out[t][gsis] = e
    n['league'] = sum(len(R) for R in rep.values())
    return out, dict(n)


def injury_costs(last, week, games, coef):
    """This week's injury cost by team, in points (non-QBs at 1 - P(plays) x WAR a game x 36 x the backtest's
    weight), the players behind it, and every QB's status for the starter call."""
    import nfl_war as W
    rep, n = live_injuries(last, week, games)
    import datetime
    with open(INJ_OUT, 'w') as f:
        f.write(json.dumps({'season': last, 'week': week, 'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')})[:-1] + ', "teams": {\n'
                + ',\n'.join(json.dumps(t) + ': ' + json.dumps({g: [p['status'], p['src']] for g, p in sorted(ps.items())})
                              for t, ps in sorted(rep.items())) + '\n}}\n')
    maps = W.gsis_map(last)
    prev = W.war_ledger(last - 1, maps=W.gsis_map(last - 1))
    cur = W.war_ledger(last, maps=maps)
    played = [g for g in games if int(g['season']) == last and g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    lastw = {}
    for g in played:
        for side in ('home', 'away'):
            lastw[team(g[f'{side}_team'])] = max(lastw.get(team(g[f'{side}_team']), 0), int(g['week']))
    before = {}
    cost, who, qbst = {}, {}, {}
    carry = defaultdict(list)          # team -> [(status, points a game at full value)] for the later weeks (hazard)
    for t, ps in rep.items():
        c, lst = 0.0, []
        for gsis, p in ps.items():
            if p['pos'] == 'QB':
                qbst[gsis] = p['status']              # by id: two QBs can share a name
                qbst.setdefault(_norm(p['name']), p['status'])
                continue
            if p['status'] in GONE or p['status'] == 'Active':
                continue
            pw = lastw.get(t)
            if pw:
                if pw not in before:
                    before[pw] = W.war_ledger(last, thru=pw, maps=maps)
                rec_ = cur.get(gsis, (0, 0))[1] > before[pw].get(gsis, (0, 0))[1]
            else:
                rec_ = True
            miss = 1 - play_prob(p['status'], rec_, p.get('prac'))
            v = max(player_value(prev.get(gsis, (0.0, 0)), cur.get(gsis, (0.0, 0))), 0.0)
            raw = miss * v * PTS_PER_WIN
            if v > 0:
                carry[t].append((p['status'], v * PTS_PER_WIN))
            pts = raw * coef        # the listed points carry the fitted weight; the model input does not (the fit
            c += raw                # multiplies by it, as in training: weighting both counted it twice, Oct 21 2026)
            if miss > 0:
                lst.append({'name': p['name'], 'pos': p['pos'], 'status': p['status'], 'miss': round(miss, 2), 'pts': round(pts, 1)})
        cost[t] = c
        who[t] = sorted([x for x in lst if x['pts'] >= 0.1], key=lambda x: -x['pts'])[:5]
    print('nfl games: injury reports', n)
    return cost, who, qbst, n, dict(carry)


# ---------------------------------------------------------------- fit
def fit():
    import numpy as np
    last = 2025
    games, box, qbs = load(last)
    index_qbs(qbs, games); load_qb_teams(last)
    played = lambda g: g['home_score'] not in ('', 'NA')

    inj = injury_history(games, range(INJ_FIRST, last + 1))

    def run(params, feats=FEATS, tfeats=TFEATS):
        _, data = walk(games, box, qbs, params)
        for g, x, _ in data:
            r = inj.get(g['game_id'])
            if r:
                x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D = [(g, x, tx) for g, x, tx in data if played(g) and int(g['season']) >= 2012]
        X = np.array([[x[f] for f in feats] for _, x, _ in D]); y = np.array([num(g['result']) for g, _, _ in D])
        TX = np.array([[tx[f] for f in tfeats] for _, _, tx in D]); ty = np.array([num(g['total']) for g, _, _ in D])
        S = np.array([int(g['season']) for g, _, _ in D])
        line = np.array([num(g['spread_line'], np.nan) for g, _, _ in D]); tline = np.array([num(g['total_line'], np.nan) for g, _, _ in D])
        pred = np.full(len(y), np.nan); tpred = np.full(len(y), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
            tb = np.linalg.lstsq(TX[tr], ty[tr], rcond=None)[0]; tpred[te] = TX[te] @ tb
        return D, X, y, TX, ty, S, line, tline, pred, tpred

    # tune the rating memory on 2015-2020 out-of-sample error, keep 2021-25 clean for the report. The QB prior
    # (qb_n0 100 plays) and the market-rating steps (spreads mk .2, kept .4 over the summer; totals tk .4, reset
    # each summer) were picked the same way, on 2015-20, in the Oct 2026 accuracy pass
    grid = []
    for hl in (4, 6, 8, 12):
        for carry in (0.3, 0.5, 0.7):
            p = {'hl': hl, 'carry': carry, 'qb_n0': 100.0, 'mk': 0.2, 'mrev': 0.4, 'tk': 0.4, 'trev': 0.0}
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
    # injuries: the same walk-forward with and without the injury term, on the seasons with reports to train on
    p0 = run(best, [f for f in FEATS if f != 'inj'])[8]

    def cmp(k, pr):
        k = k & ok & ~np.isnan(pr)
        e = pr[k] - line[k]; r = y[k] - line[k]; pick = (np.abs(e) >= 1) & (r != 0)
        return {'games': int(k.sum()), 'mae': round(float(np.mean(np.abs(pr[k] - y[k]))), 3),
                'ats1': round(float((np.sign(e[pick]) == np.sign(r[pick])).mean()), 3)}
    inj_test = {lab: {'with': cmp(k, pred), 'without': cmp(k, p0), 'line': round(float(np.mean(np.abs(line[k & ok] - y[k & ok]))), 3)}
                for lab, k in (('2017-25', S >= 2017), ('2021-25', S >= 2021))}
    # market ratings: the same walk-forward without them (margins without 'mkt', totals on points alone)
    _, _, _, _, _, _, _, _, m0, t0 = run(best, [f for f in FEATS if f != 'mkt'], ['pts', 'dome', 'one'])
    tmae = lambda k, pr: round(float(np.mean(np.abs(pr[k] - ty[k]))), 3)
    mkt_test = {}
    for lab, k in (('2015-20 (tuning)', (S >= 2015) & (S <= 2020)), ('2021-25 (held out)', S >= 2021)):
        kt = k & ok & ~np.isnan(tline)
        mkt_test[lab] = {'with': cmp(k, pred), 'without': cmp(k, m0), 'line': round(float(np.mean(np.abs(line[k & ok] - y[k & ok]))), 3),
                         'totalWith': tmae(kt, tpred), 'totalWithout': tmae(kt, t0), 'totalLine': tmae(kt, tline)}
    # blending with the line: what share of the model's edge holds up out of sample (2015-25)
    b = np.linalg.lstsq(X[S >= 2012], y[S >= 2012], rcond=None)[0]
    tb = np.linalg.lstsq(TX, ty, rcond=None)[0]
    # per-feature t (whole sample)
    res = y - X @ b; s2 = res @ res / (len(y) - len(b)); cov = s2 * np.linalg.inv(X.T @ X)
    out = {'params': best, 'coef': {f: round(float(v), 4) for f, v in zip(FEATS, b)},
           't': {f: round(float(v / math.sqrt(cov[i, i])), 1) for i, (f, v) in enumerate(zip(FEATS, b))},
           'tcoef': {f: round(float(v), 4) for f, v in zip(TFEATS, tb)},
           'sd': round(sd, 2), 'tsd': round(float(np.std(tpred[~np.isnan(tpred)] - ty[~np.isnan(tpred)])), 2),
           'test': test, 'injTest': inj_test, 'mktTest': mkt_test, 'grid': [[round(e, 3), p] for e, p in grid]}
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
    icost, iwho, qbst, isrc, icarry = injury_costs(last, week, games, F['coef'].get('inj', 0.0))
    qbinfo = resolve_qbs(games, last, week, qbst)
    hist = injury_history(games, [last], live=last)
    proj = {}
    played_w = []
    for g in games:
        x, tx = m.feats(g)
        if g in nxt or (int(g['season']) == last):
            proj[g['game_id']] = (x, tx)
        m.update(g, box, qbs)
    b, tb, sd, tsd = F['coef'], F['tcoef'], F['sd'], F['tsd']
    # the offseason roster prior (scripts/nfl_roster.py): free agency, trades, cuts and the draft class in WAR, fading
    # as the team plays; a failure leaves it out
    try:
        import nfl_roster as NR
        moves = NR.live(last)
    except Exception as e:      # noqa: BLE001
        print('nfl roster prior: failed', repr(e)); NR, moves = None, {}
    gp = defaultdict(int)
    for g in games:
        if int(g['season']) == last and g['game_id'] in proj:
            h, a = team(g['home_team']), team(g['away_team'])
            proj[g['game_id']][0]['roster'] = NR.points(moves, h, gp[h]) - NR.points(moves, a, gp[a]) if moves else 0.0
            if g['home_score'] not in ('', 'NA'):
                gp[h] += 1; gp[a] += 1
    # injuries: the league's reports for games played, this week's reports and news for this week's games; a
    # questionable or probable QB starts with his chance to play, his backup with the rest
    for gid, (x, _) in proj.items():
        r = hist.get(gid)
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
    qa = lambda t, q: (m.qbval(q) - m.rate(m.qbt, t, m.repl)) if q else 0.0
    for g in nxt:
        x = proj[g['game_id']][0]
        h, a = team(g['home_team']), team(g['away_team'])
        x['inj'] = icost.get(a, 0.0) - icost.get(h, 0.0)
        mix = lambda t, q: qbinfo[t]['pNow'] * qa(t, q) + (1 - qbinfo[t]['pNow']) * qa(t, qbinfo[t]['alt'][0]) if t in qbinfo and qbinfo[t]['alt'][0] else qa(t, q)
        x['qb'] = (mix(h, g['home_qb_id']) - mix(a, g['away_qb_id'])) * 38
    # Novig's main lines at its asks first (Noah, Oct 27 2026: "switch everything to Novig"); ESPN's DraftKings where Novig has none
    try:
        import novig
        NV = novig.prices('nfl')
    except Exception as e:
        print('novig:', e); NV = {}
    out = []
    for g in [g for g in games if int(g['season']) == last and int(g['week']) <= week]:
        px = NV.get(str(g['espn'])) if g['home_score'] in ('', 'NA') else None
        if px:
            g = {**g, 'spread_line': px.get('L', g['spread_line']), 'total_line': px.get('T', g['total_line']),
                 'home_moneyline': str(px['mlH']) if px.get('mlH') is not None else g['home_moneyline'],
                 'away_moneyline': str(px['mlA']) if px.get('mlA') is not None else g['away_moneyline']}
        x, tx = proj[g['game_id']]
        parts = {f: round(b[f] * x[f], 1) for f in FEATS}
        parts['roster'] = round(x.get('roster', 0.0), 1)
        mar = sum(b[f] * x[f] for f in FEATS) + x.get('roster', 0.0)
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
        if g['game_id'] in {q['game_id'] for q in nxt}:
            r['inj'] = {'home': iwho.get(team(g['home_team']), []), 'away': iwho.get(team(g['away_team']), [])}
            for side in ('home', 'away'):
                i = qbinfo.get(team(g[f'{side}_team']))
                if i and i['pNow'] < 1 and i['alt'][0]:
                    r[f'{side[0]}qbP'] = {'p': round(i['pNow'], 2), 'status': i['statusNow'], 'alt': i['alt'][1]}
        if line is not None:
            e = mar - line
            r['edge'] = round(e, 1)
            cv = CV.chance('nfl', 'spread', e)          # model's side covers the line, as the line leaves it (cover.py)
            r['cover'] = round(cv if cv is not None else phi(abs(e) / sd), 3)
            r['side'] = 'home' if e > 0 else 'away' if e < 0 else ''
        if tl is not None:
            ov = CV.chance('nfl', 'total', tot - tl)
            r['over'] = round(ov if ov is not None else phi((tot - tl) / tsd), 3)
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
           'sd': sd, 'test': F['test'], 'coef': F['coef'], 'injSrc': isrc, 'injTest': F.get('injTest')}
    res.update(season_views(m, F, games, last, week, rec, qbinfo, {t: b.get('inj', 0.0) * c for t, c in icost.items()},
                            {t: NR.points(moves, t, gp[t]) for t in moves} if moves else None,
                            {t: [(st, b.get('inj', 0.0) * v) for st, v in ps] for t, ps in icarry.items()}))
    # picks: the college board's upset and favorite rules on this model (scripts/nfl_picks.py); a failure never holds up
    # the projections
    try:
        import nfl_picks
        nfl_picks.live(out, [g for g in games if int(g['season']) == last], sd, last, week)
    except Exception as e:      # noqa: BLE001
        print('nfl picks: failed', repr(e))
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


class League:
    """One regular season's schedule, and the standings and playoff seeds from a set of results under the NFL's
    tiebreaking procedures (a tie counts half a win; win percentage throughout, so a cancelled game drops out):

      division, 2 or more clubs  head-to-head, division record, common games, conference record, strength of victory,
                                 strength of schedule, then a coin flip
      wild card (and seeding     the division tiebreak first, so only each division's top remaining club is in it; then
      the division winners)      head-to-head (two clubs, if they played; three or more, only a sweep: one club beat
                                 or lost to each of the others), conference record, common games (minimum 4),
                                 strength of victory, strength of schedule, a coin flip
    Whenever a step drops some clubs but leaves more than one, the rest start over at the first step (two clubs left
    use the two-club order); once a club wins a tie, the others start over for the next place. The net-points steps
    before the coin flip aren't modelled (a tie that deep is rare)."""
    def __init__(self, sched, nwc=3):
        self.T = sorted(DIV_OF)
        ix = {t: i for i, t in enumerate(self.T)}
        self.g = [(ix[team(h)], ix[team(a)]) for h, a in sched]
        self.div = [DIV_OF[t] for t in self.T]
        self.conf = [d[:3] for d in self.div]
        self.tg = [[] for _ in self.T]              # team -> [(game, opponent, 1 if home)]
        self.pair = defaultdict(list)                # (team, opponent) -> [(game, 1 if home)]
        for k, (h, a) in enumerate(self.g):
            self.tg[h].append((k, a, 1)); self.tg[a].append((k, h, 0))
            self.pair[(h, a)].append((k, 1)); self.pair[(a, h)].append((k, 0))
        self.opps = [set(o for _, o, _ in tg) for tg in self.tg]
        self.divs = {c: [[ix[t] for t in ts] for d, ts in DIVS.items() if d.startswith(c)] for c in ('AFC', 'NFC')}
        self.nwc = nwc

    def seeds(self, res, rng):
        """res: each game's home result (1 win, 0 loss, .5 tie, None not played). -> ({'AFC': [seeds], 'NFC': ...},
        wins a team, tie as half)."""
        n = len(self.T)
        W, G = [0.0] * n, [0] * n
        for (h, a), r in zip(self.g, res):
            if r is not None:
                W[h] += r; W[a] += 1 - r; G[h] += 1; G[a] += 1
        pct = [W[i] / G[i] if G[i] else 0.0 for i in range(n)]
        tg, pair, div, conf, opps = self.tg, self.pair, self.div, self.conf, self.opps

        def rec(t, keep):          # win pct in t's games against opponents that pass keep
            w = m = 0
            for k, o, hm in tg[t]:
                r = res[k]
                if r is not None and keep(o):
                    w += r if hm else 1 - r; m += 1
            return w, m

        def h2h(S):
            v = {}
            for t in S:
                w = m = 0
                for o in S:
                    for k, hm in pair.get((t, o), ()):
                        r = res[k]
                        if r is not None:
                            w += r if hm else 1 - r; m += 1
                if not m:
                    return None
                v[t] = w / m
            return v

        def sweep(S):
            for t in S:
                beat = lost = True
                for o in S:
                    if o == t:
                        continue
                    gs = [(res[k] if hm else 1 - res[k]) for k, hm in pair.get((t, o), ()) if res[k] is not None]
                    if not gs:
                        beat = lost = False; break
                    beat = beat and min(gs) == 1; lost = lost and max(gs) == 0
                if beat:
                    return {o: 1.0 if o == t else 0.0 for o in S}
                if lost:
                    return {o: 0.0 if o == t else 1.0 for o in S}
            return None

        def frac(w, m):
            return w / m if m else 0.0

        def divrec(S):
            return {t: frac(*rec(t, lambda o, d=div[t]: div[o] == d)) for t in S}

        def confrec(S):
            return {t: frac(*rec(t, lambda o, c=conf[t]: conf[o] == c)) for t in S}

        def common(S, least=0):
            C = set.intersection(*(opps[t] for t in S))
            v = {}
            for t in S:
                w, m = rec(t, C.__contains__)
                if m < max(least, 1):
                    return None
                v[t] = w / m
            return v

        def common4(S):
            return common(S, 4)

        def sov(S):
            v = {}
            for t in S:
                w = m = 0
                for k, o, hm in tg[t]:
                    r = res[k]
                    if r is not None and (r if hm else 1 - r) == 1:
                        w += W[o]; m += G[o]
                v[t] = frac(w, m)
            return v

        def sos(S):
            v = {}
            for t in S:
                w = m = 0
                for k, o, hm in tg[t]:
                    if res[k] is not None:
                        w += W[o]; m += G[o]
                v[t] = frac(w, m)
            return v

        def settle(S, steps):      # apply steps until one drops clubs: (clubs left, True) or (S, False) if none did
            for f in steps:
                v = f(S)
                if v is None:
                    continue
                top = max(v.values())
                keep = [t for t in S if v[t] >= top - 1e-9]
                if len(keep) < len(S):
                    return keep, True
            return S, False

        def div_best(S):
            while len(S) > 1:
                S, moved = settle(S, (h2h, divrec, common, confrec, sov, sos))
                if not moved:
                    return rng.choice(sorted(S))
            return S[0]

        dorder = {}

        def divrank(t):
            d = div[t]
            if d not in dorder:
                o = rank([i for i in range(n) if div[i] == d], 4, div_best)
                dorder[d] = {x: i for i, x in enumerate(o)}
            return dorder[d][t]

        def wc_best(S):
            while len(S) > 1:
                top = {}
                for t in S:                     # each division's highest-ranked club
                    if div[t] not in top or divrank(t) < divrank(top[div[t]]):
                        top[div[t]] = t
                S = sorted(top.values())
                if len(S) == 1:
                    break
                S, moved = settle(S, (h2h if len(S) == 2 else sweep, confrec, common4, sov, sos))
                if not moved:
                    return rng.choice(S)
            return S[0]

        def rank(S, k, best):
            srt = sorted(S, key=lambda t: -pct[t])
            out, i = [], 0
            while i < len(srt) and len(out) < k:
                j = i
                while j < len(srt) and pct[srt[j]] > pct[srt[i]] - 1e-9:
                    j += 1
                grp = srt[i:j]
                while grp and len(out) < k:
                    t = grp[0] if len(grp) == 1 else best(list(grp))
                    out.append(t); grp.remove(t)
                i = j
            return out

        T = self.T
        out = {}
        for c, ds in self.divs.items():
            winners = [rank(ts, 1, div_best)[0] for ts in ds]
            wset = set(winners)
            seeds = rank(winners, 4, wc_best) + rank([t for ts in ds for t in ts if t not in wset], self.nwc, wc_best)
            out[c] = [T[t] for t in seeds]
        return out, dict(zip(T, W))


    def draft_order(self, res, exits, rng):
        """The draft order (worst first) from a full season's results and each playoff club's exit round (1 wild card,
        2 divisional, 3 conference, 4 Super Bowl loser, 5 champion): clubs out of the playoffs by win pct, then the
        playoff clubs by the round they went out in, each group by win pct. Ties: strength of schedule (lower picks
        first), then a coin flip (the division and conference steps the NFL applies before that are rare enough to
        leave out)."""
        n = len(self.T)
        W, G = [0.0] * n, [0] * n
        for (h, a), r in zip(self.g, res):
            if r is not None:
                W[h] += r; W[a] += 1 - r; G[h] += 1; G[a] += 1
        pct = [W[i] / G[i] if G[i] else 0.0 for i in range(n)]
        sos = []
        for t in range(n):
            w = sum(W[o] for _, o, _ in self.tg[t]); g = sum(G[o] for _, o, _ in self.tg[t])
            sos.append(w / g if g else 0.5)
        key = {i: (exits.get(self.T[i], 0), round(pct[i], 9), round(sos[i], 9), rng.random()) for i in range(n)}
        return [self.T[i] for i in sorted(range(n), key=key.get)]


def season_results(games, season):
    """A season's regular-season schedule and results (home side: 1 win, 0 loss, .5 tie, None not played yet)."""
    sg = [g for g in games if int(g['season']) == season and g['game_type'] == 'REG']
    res = [None if g['home_score'] in ('', 'NA') else
           (1.0 if num(g['result']) > 0 else 0.0 if num(g['result']) < 0 else 0.5) for g in sg]
    return sg, res


# the seeds that came out of a known season (nfl.com), and every 7-team-format season's wild-card round from games.csv
KNOWN_SEEDS = {2023: {'AFC': ['BAL', 'BUF', 'KC', 'HOU', 'CLE', 'MIA', 'PIT'], 'NFC': ['SF', 'DAL', 'DET', 'TB', 'PHI', 'LA', 'GB']},
               2024: {'AFC': ['KC', 'BUF', 'BAL', 'HOU', 'LAC', 'PIT', 'DEN'], 'NFC': ['DET', 'PHI', 'TB', 'LA', 'MIN', 'WAS', 'GB']}}


def check_tiebreaks(games, seasons=range(2015, 2026)):
    """The tiebreak code on each finished season's actual results against the real playoff field: the known seeds
    above, and for every season the wild-card round (home side the better seed, seeds summing to 9) and the
    teams with a bye."""
    import random
    bad = []
    for y in seasons:
        sg, res = season_results(games, y)
        nwc = 3 if y >= 2020 else 2
        lg = League([(g['home_team'], g['away_team']) for g in sg], nwc)
        seeds, _ = lg.seeds([r for r in res], random.Random(1))
        # cancelled games (2022 BUF-CIN) have no result and drop out of the percentages
        wc = [g for g in games if int(g['season']) == y and g['game_type'] == 'WC']
        for c, s in seeds.items():
            sn = {t: i + 1 for i, t in enumerate(s)}
            if y in KNOWN_SEEDS and KNOWN_SEEDS[y][c] != s:
                bad.append((y, c, s, KNOWN_SEEDS[y][c]))
            field = set(s)
            ingames = {team(g[f'{x}_team']) for g in wc for x in ('home', 'away')} & set(t for d, ts in DIVS.items() if d.startswith(c) for t in ts)
            byes = field - ingames
            for g in wc:
                h, a = team(g['home_team']), team(g['away_team'])
                if h in sn and a in sn and (sn[h] > sn[a] or sn[h] + sn[a] != 9):
                    bad.append((y, c, 'wc game', h, a, sn[h], sn[a]))
            if len(byes) != (1 if nwc == 3 else 2) or byes != set(s[:len(byes)]) or not ingames <= field:
                bad.append((y, c, 'field', s, sorted(ingames)))
        print(y, {c: ' '.join(s) for c, s in seeds.items()})
    print('tiebreak check:', 'all match' if not bad else bad)
    return bad
GROUPS = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR/TE', 'TE': 'WR/TE', 'OL': 'OL', 'EDGE': 'DL', 'DL': 'DL', 'LB': 'LB', 'CB': 'DB', 'S': 'DB'}
SIMS = 10000
RATING_SD = 5.0      # uncertainty in a team's true rating before week 1, points (drawn once a simulated season)


def rating_sd(left):
    """The rating uncertainty with a share `left` of the regular season still to play: RATING_SD x sqrt(left).
    Backtest (scripts/nfl_season_backtest.py, data/nfl_season_backtest.json simTest): 2015-25, walk-forward ratings,
    the rest of the season simulated with the tiebreakers, scored on making the playoffs, winning the division and
    final wins (log loss). Before weeks 1, 5, 9 and 13, 5 x sqrt(left) beat the old fixed 2.5 on 2015-20 (2.768 vs
    2.802 a team and checkpoint, t -2.4 over team-seasons) and on 2021-25 (3.065 vs 3.115, t -2.8). With weeks 15 and
    17 added, no steeper decay (sd0 4-6 x left^p, p .5-1.5, floors 0-1) beat it on 2015-20 (best 5.5 x left^.75:
    2.2198 vs 2.2197, t +0.1; 2021-25 2.606 vs 2.600, t +2.7); a fixed 4.5 did better on 2021-25 (2.580, t -2.9)
    but not on 2015-20 (2.222, t +0.8)"""
    return RATING_SD * math.sqrt(max(0.0, left))


OUT_STATUS = {'Out', 'Injured Reserve', 'Doubtful', 'Suspended', 'Physically Unable to Perform', 'Non Football Injury', 'Out (season)'}


def _norm(n):
    """a player's name key, shared by every sport (scripts/names.py)"""
    return NM.key(n)


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


def resolve_qbs(games, last, week, status=None):
    """Who starts at QB for each team: this week, and for the rest of the season. Rewrites the listed QB on every
    unplayed game to match (games.csv carries the last known starter forward, so an injured starter stays listed).

      QB1          the top QB on the team's depth chart (nflverse's ESPN depth charts; an injured starter keeps the
                   spot), else the QB with the most starts this season
      this week    the first QB down the depth chart whom ESPN's injury report doesn't have out (out, doubtful, IR,
                   suspended); without a depth chart, QB1 unless out, then the listed QB or the latest healthy fill-in
      later weeks  QB1, unless he's on IR (then this week's starter)
    """
    status = status or {}
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
    st = lambda name, gsis=None: status.get(gsis) or status.get(_norm(name), 'Active')
    out = lambda name, gsis=None: st(name, gsis) in OUT_STATUS
    info = {}
    for t in DIV_OF:
        ss = sorted(starts.get(t, []))
        cnt = defaultdict(lambda: [0, 0, ''])
        for wk, gsis, name in ss:
            c = cnt[gsis]; c[0] += 1; c[1] = wk; c[2] = name
        qb1 = max(cnt, key=lambda k: (cnt[k][0], cnt[k][1])) if cnt else nxt.get(t, ('', ''))[0]
        listed = nxt.get(t, ('', ''))
        if len(ss) >= 2 and ss[-1][1] == ss[-2][1] == listed[0] and listed[0] != qb1 and not out(listed[1], listed[0]):
            qb1 = listed[0]                                  # benched: the new man has started twice running
        name1 = cnt[qb1][2] if qb1 in cnt else listed[1]
        dc = [q for q in depth.get(t, []) if q[0]]
        if dc:
            qb1, name1 = dc[0]
        now = (qb1, name1)
        healthy = [q for q in dc if not out(q[1], q[0])]
        if out(name1, qb1) and healthy:
            now = healthy[0]
        elif out(name1, qb1):
            if listed[0] and listed[0] != qb1 and not out(listed[1], listed[0]):
                now = listed
            else:
                alts = {gsis: (wk, name) for wk, gsis, name in ss if gsis != qb1 and not out(name, gsis)}
                if alts:
                    k = max(alts, key=lambda k: (alts[k][0], plays.get((t, k), 0)))
                    now = (k, alts[k][1])
                else:
                    pool = [(n, gsis) for (tt, gsis), n in plays.items() if tt == t and gsis != qb1 and not out(_QNAME.get(gsis, ''), gsis)]
                    if pool:
                        k = max(pool)[1]
                        now = (k, _QNAME.get(k, k))
        later = now if st(name1, qb1) in GONE else (qb1, name1)
        # a questionable or probable starter: his chance to play (a QB listed questionable has started 59% of the time
        # since 2016), with the next healthy QB down the chart in for the rest
        p = 0.6 if st(now[1], now[0]) == 'Questionable' else play_prob(st(now[1], now[0]))
        alt = next((q for q in dc if q[0] != now[0] and not out(q[1], q[0])), ('', ''))
        info[t] = {'qb1': (qb1, name1), 'now': now, 'later': later, 'status': st(name1, qb1),
                   'statusNow': st(now[1], now[0]), 'pNow': p, 'alt': alt}
    for g in games:
        if int(g['season']) == last and g['home_score'] in ('', 'NA'):
            for side in ('home', 'away'):
                i = info.get(team(g[f'{side}_team']))
                if i:
                    q = i['now'] if int(g['week']) == week else i['later']
                    g[f'{side}_qb_id'], g[f'{side}_qb_name'] = q
    return info


HAZ = os.path.join(ROOT, 'data', 'nfl_inj_hazard.json')


def miss_later(table, status, j):
    """P(a player listed `status` this week misses his team's j-th game after this week's), from the hazard table
    (scripts/nfl_inj_hazard.py: league reports and weekly rosters 2016-25). Last week's designation, before this
    week's report, counts one game further on."""
    lw = status.endswith(' (last week)')
    st, j = (status[:-12], j + 1) if lw else (status, j)
    t = table.get(st)
    if not t or j < 1:
        return 0.0
    v = t['any']
    return v[min(j, len(v)) - 1]


def season_views(m, F, games, last, week, rec, qbinfo, inj=None, roster=None, carry=None):
    """Power rankings, QB values, team WAR and a simulated rest of the season (playoff, division, seed, title odds).
    carry: team -> [(status, points a game)] for this week's listed non-QBs, carried into the later weeks by the hazard
    table (data/nfl_inj_hazard.json), as is a listed QB1 (out: this week's starter in his place)."""
    import random
    b = F['coef']
    L = m.lgepa()
    starter = {t: i['now'] for t, i in qbinfo.items()}          # this week's starter (resolve_qbs)
    later = {t: i['later'] for t, i in qbinfo.items()}          # the rest of the season
    teams = sorted(DIV_OF)

    def qpts(gsis):            # points a game over a replacement-level QB
        return b['qb'] * (m.qbval(gsis) - m.repl) * 38

    inj = inj or {}
    roster = roster or {}      # the offseason roster prior's points now (it fades as games are played; held there)
    qa = lambda t, q: (m.qbval(q) - m.rate(m.qbt, t, m.repl)) if q else 0.0

    def rating(t, who=starter):   # neutral-field points against an average team, with a given starter
        q = who.get(t, ('', ''))[0]
        if who is starter and t in qbinfo and qbinfo[t]['alt'][0]:     # this week: a questionable QB at his chance to play
            p = qbinfo[t]['pNow']
            a = p * qa(t, q) + (1 - p) * qa(t, qbinfo[t]['alt'][0])
        else:
            a = qa(t, q)
        return (b['elo'] * (m.elo[t] - 1505) / 25 + b.get('epa', 0.0) * (m.rate(m.off, t, L) - m.rate(m.dfn, t, L)) * 62 + b['qb'] * a * 38
                + b.get('mkt', 0.0) * m.mkt[t] + roster.get(t, 0.0))
    # this week: the starter and the week's injury reports
    R = {t: rating(t) - inj.get(t, 0.0) for t in teams}
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

    # simulate the rest of the regular season and the playoffs: games played count as they finished, the seeds come
    # from the NFL's tiebreakers (League)
    sd = F['sd']
    sg, res0 = season_results(games, last)
    lg = League([(g['home_team'], g['away_team']) for g in sg])
    left = [(k, g) for k, (g, r) in enumerate(zip(sg, res0)) if r is None]
    rsd = rating_sd(len(left) / max(1, len(sg)))
    hfa = b['home']
    rest = lambda x: max(-7, min(7, num(x, 7) - 7))
    # this week's games with this week's starters and reports; later games with each team's QB1 (unless he's on IR),
    # each listed player at his chance to still be out that many games on (miss_later; scripts/nfl_inj_hazard.py)
    try:
        haz = json.load(open(HAZ))['table'] if carry is not None else {}
    except (OSError, ValueError, KeyError):
        haz = {}
    gw = defaultdict(list)
    for _, g in left:
        for side in ('home', 'away'):
            gw[team(g[f'{side}_team'])].append(int(g['week']))

    def carried(g, t):
        if not haz:
            return RL[t]
        gk = int(g['week'])
        j = sum(1 for x in gw[t] if week <= x < gk)     # t's games between this week's and this one
        i = qbinfo.get(t)
        q1, stt = (i['qb1'][0], i['status']) if i else ('', 'Active')
        out_q = (i['now'][0] if i['now'][0] != q1 else i['alt'][0]) if i else ''
        d = 0.0
        if haz and q1 and out_q and stt not in GONE and stt != 'Active':
            p = (1 - play_prob(stt)) if j == 0 else miss_later(haz, stt, j)
            d = b['qb'] * p * (qa(t, out_q) - qa(t, q1)) * 38
        if j == 0:
            return RL[t] - inj.get(t, 0.0) + d
        return RL[t] - sum(miss_later(haz, st_, j) * v for st_, v in (carry or {}).get(t, ())) + d
    rr = lambda g, t: R[t] if int(g['week']) == week else carried(g, t)
    mus = [(k, team(g['home_team']), team(g['away_team']),
            rr(g, team(g['home_team'])) - rr(g, team(g['away_team'])) + (hfa if g['location'] != 'Neutral' else 0)
            + b['rest'] * (rest(g['home_rest']) - rest(g['away_rest']))) for k, g in left]
    keys = ('playoff', 'div', 'seed1', 'conf', 'sb')
    cnt = {t: dict.fromkeys(keys, 0) for t in teams}
    wsum = dict.fromkeys(teams, 0.0)
    slot = dict.fromkeys(teams, 0.0)      # draft slot, summed over the sims (the mock draft's order: draft_slots)
    top = dict.fromkeys(teams, 0)         # sims with a top-5 pick
    rng = random.Random(7)
    drng = random.Random(11)              # the draft order's coin flips, apart from the game draws
    t0 = time.time()
    for _ in range(SIMS):
        shock = {t: rng.gauss(0, rsd) for t in teams}
        res = list(res0)
        for k, h, a, mu in mus:
            res[k] = 1.0 if rng.gauss(mu + shock[h] - shock[a], sd) > 0 else 0.0
        field, w = lg.seeds(res, rng)
        for t in teams:
            wsum[t] += w[t]
        champs, exits = [], {}
        for conf in ('AFC', 'NFC'):
            seeds = field[conf]
            for t in seeds[:4]:
                cnt[t]['div'] += 1
            for t in seeds:
                cnt[t]['playoff'] += 1
            cnt[seeds[0]]['seed1'] += 1
            seed = {t: i for i, t in enumerate(seeds)}

            def play(h, a, rd, neutral=False):
                mu = RL[h] - RL[a] + shock[h] - shock[a] + (0 if neutral else hfa)
                w = h if rng.gauss(mu, sd) > 0 else a
                exits[a if w == h else h] = rd
                return w
            alive = [seeds[0]] + [play(seeds[i], seeds[7 - i], 1) for i in (1, 2, 3)]
            rd = 2
            while len(alive) > 1:
                alive.sort(key=lambda t: seed[t])
                alive = [play(alive[i], alive[-1 - i], rd) for i in range(len(alive) // 2)]
                rd += 1
            cnt[alive[0]]['conf'] += 1
            champs.append(alive[0])
        sbw = (lambda h, a: h if rng.gauss(RL[h] - RL[a] + shock[h] - shock[a], sd) > 0 else a)(*champs)
        cnt[sbw]['sb'] += 1
        exits[champs[0] if sbw == champs[1] else champs[1]] = 4
        exits[sbw] = 5
        for i, t in enumerate(lg.draft_order(res, exits, drng)):
            slot[t] += i + 1
            top[t] += i < 5
    print(f'nfl games: {SIMS} season sims in {time.time() - t0:.1f}s (rating sd {rsd:.2f})')

    power = []
    for t in teams:
        q = starter.get(t, ('', ''))
        power.append({'t': t, 'dv': DIV_OF[t], 'rating': round(R[t], 1), 'elo': round(m.elo[t]),
                      'off': round(m.rate(m.off, t, L) - L, 3), 'dfn': round(m.rate(m.dfn, t, L) - L, 3),
                      'qb': q[1], 'qbPts': round(qpts(q[0]), 1) if q[0] else None,
                      'inj': round(inj.get(t, 0.0), 1) if inj.get(t, 0.0) >= 0.1 else None,
                      'qb1': qbinfo[t]['qb1'][1] if qbinfo[t]['qb1'][0] != q[0] else None, 'qb1Status': qbinfo[t]['status'], 'rec': '-'.join(map(str, rec[t][:2])) + (f'-{rec[t][2]}' if rec[t][2] else '') if t in rec else '0-0',
                      'war': round(tw[t]['total'], 1) if t in tw else None,
                      'wars': {k: round(v, 1) for k, v in tw[t].items() if k != 'total'} if t in tw else {},
                      'wins': round(wsum[t] / SIMS, 1), **{k: round(cnt[t][k] / SIMS, 3) for k in keys},
                      'xSlot': round(slot[t] / SIMS, 2), 'pTop5': round(top[t] / SIMS, 3)})
    power.sort(key=lambda r: -r['rating'])
    for i, r in enumerate(power):
        r['rk'] = i + 1
    import rank_odds                  # 80% rank range and P(#1 / top 4) from the measured rating sd
    rank_odds.add(power, 'nfl', len(left) / max(1, len(sg)))

    # team breakdowns for the power rankings' dropdowns (scripts/team_detail.py, display only): this week's rating split
    # into its inputs, and the schedule with each game left at the season sims' margin
    try:
        import team_detail
        comps = {}
        for t in teams:
            q = starter.get(t, ('', ''))[0]
            if t in qbinfo and qbinfo[t]['alt'][0]:
                p = qbinfo[t]['pNow']; a = p * qa(t, q) + (1 - p) * qa(t, qbinfo[t]['alt'][0])
            else:
                a = qa(t, q)
            comps[t] = {'elo': b['elo'] * (m.elo[t] - 1505) / 25, 'eff': b.get('epa', 0.0) * (m.rate(m.off, t, L) - m.rate(m.dfn, t, L)) * 62,
                        'qb': b['qb'] * a * 38, 'mkt': b.get('mkt', 0.0) * m.mkt[t], 'roster': roster.get(t, 0.0), 'inj': -inj.get(t, 0.0)}
        parts = team_detail.center(comps, R, rest='inj')
        mu_of = {k: mu for k, _, _, mu in mus}
        sch = []
        for k, (g, r) in enumerate(zip(sg, res0)):
            h, a_ = team(g['home_team']), team(g['away_team'])
            row = {'d': int(g['week']), 'h': h, 'a': a_, 'n': g['location'] == 'Neutral'}
            if r is None:
                mu = mu_of.get(k)
                row.update(m=mu, p=None if mu is None else float(phi(mu / sd)))
            else:
                row.update(hs=int(num(g['home_score'])), **{'as': int(num(g['away_score']))})
            sch.append(row)
        S = team_detail.schedules(sch, teams)
        team_detail.save('nfl', {t: {'parts': parts[t], 'sch': S[t]} for t in teams})
    except Exception as e:            # the dropdowns keep the last file rather than stop the build
        print('team breakdowns failed:', repr(e), flush=True)

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
    try:                # headshots from the WAR board (scripts/photos.py)
        import photos
        photos.attach('nfl', qbt, name='n', team='t')
        for q in qbt: q.pop('logo', None)
    except Exception as e:
        print('QB photos skipped', e)
    return {'power': power, 'qbs': qbt, 'sims': SIMS, 'ratingSd': round(rsd, 2), 'left': len(left)}


def qbs_items():
    for gid, lst in _QIDX.items():
        for gsis, q in lst:
            yield (gid, gsis), q


if __name__ == '__main__':
    fit() if '--fit' in sys.argv else build()
