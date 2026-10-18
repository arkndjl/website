#!/usr/bin/env python3
"""NFL fantasy projections for the NFL ARKBOARD (static/data/nfl-fantasy.json, data/nfl_fantasy.json), and the
model behind them (data/nfl_fantasy_fit.json).

    python3 scripts/nfl_fantasy.py          # this week's and rest-of-season projections (stdlib only; cfb board job)
    python3 scripts/nfl_fantasy.py --fit    # walk-forward backtest 2016-2025, refit (numpy)

Data: nflverse (stats_player_week: box score lines; play_by_play: red-zone usage; snap_counts: snap share;
weekly rosters and injury reports: availability; players: ids, draft slot; nfldata games.csv: schedule, lines).

What gets projected is the stat line, not the points, so one projection scores in any format:
    QB/RB/WR/TE  passing yards, passing TDs, INTs, rushing yards and TDs, receptions, receiving yards and TDs,
                 fumbles lost, two-point conversions, return TDs
    K            field goals made by distance (0-39, 40-49, 50+), extra points
    DST          sacks, INTs, fumble recoveries, defensive and return TDs, safeties, blocked kicks, points allowed
Standard scoring: 1 point per 25 passing yards, 4 a passing TD, -2 an INT or fumble lost, 1 per 10 rushing or
receiving yards, 6 a TD, 2 a two-point conversion; half PPR adds 0.5 a catch, PPR 1. Kickers 3/4/5 by distance
and 1 an extra point (no miss penalty). Defenses 1 a sack, 2 a takeaway, safety or blocked kick, 6 a TD, and
10/7/4/1/0/-1/-4 for 0/1-6/7-13/14-20/21-27/28-34/35+ points allowed. The same in all three formats.

Each stat (per player, per game he plays) is a linear model, by position, on what's known before kickoff:
    usage       exponentially weighted per-game rates over the games he played (half-life in games, carried
                across seasons at a fraction; both tuned in the backtest), shrunk toward zero by k0 pseudo-games:
                dropbacks, carries, targets, air yards, snap share. (Red-zone carries and targets were tried and
                added nothing out of sample over these, RMSE within .002, so they're out.)
    production  the same weighted rates of every stat above
    draft       draft slot, counted only while his own history is thin (a rookie's first games)
    game        the team's implied points this game (the market's spread and total when listed, else the NFL game
                model) over its recent scoring, times the player's rate of that stat: a good matchup scales a line
    defense     the opponent's fantasy points allowed to the position (weighted) over the league's, times his rate
    teammates   the team's left-over work: its dropbacks, carries and targets a game over what the players it has
                are expected to take (each rostered player's rate times his chance to play, from the injury report
                and roster status), times his rate. A starter out moves his work to the rest of the room.
    recent role his snaps, targets, air yards, carries and dropbacks on a 1.5-game half-life, against the long
                memory: a role that changed last week shows up before the production does
    talent      his WAR a game to date (nfl_war.py), draft slot at full weight and age, each as a level or times his
                rates. College FV can't be tested here (past grades start with the 2019 college season), so draft slot
                stands in for it.
    return      his first game back after missing one of his team's games, or two or more: lines run under the rates
                (2016-25, QBs with a role who had missed games scored about 3 points a game under the projection
                without this input), and questionable and playing (RB, WR). EXTRA has which position keeps which.
(Opportunity times regressed efficiency as a structural line, e.g. routes x targets per route x yards per target,
was tried and added nothing over the linear rates, RMSE within .001.)
Weekly and rest-of-season points are the stat lines times P(he plays), from an availability table fit on
2016-25 by status (healthy, questionable, doubtful, out, reserve or not on a roster, or back on the report from a
reserve list), whether he played his team's last game, and how many weeks ahead the game is. Rest of season sums
every remaining game on his team's schedule (byes drop out), each with its own game-model environment.

The backtest refits each season on the seasons before it (2013 on, the snap-count era) and scores that season
(2016-25) against the season-to-date points a game (last season's in week 1), on each week's fantasy-relevant
pool (the top 32 QBs, 64 RBs, 96 WRs, 32 TEs, 32 Ks and DSTs by that baseline) in the games they played.
Ratings memory is tuned on 2016-20 RMSE (a projection is a mean, and squared error is what a mean minimizes);
2021-25 is held out for the report. Each input group is scored by leaving it out and refitting.
Rest of season is tested from weeks 4, 8 and 12 of 2021-25 against points a game so far times the games a
healthy starter plays.

Breakouts (see BO_LINE): for players below the starter line, the walk-forward logistic odds of a starter's PPR points
over the next four games, from the projection, points at a starter's workload (efficiency per route, carry, target
and dropback, each regressed to the position by its split-half stability), the role's trend, the team's left-over
work, draft slot and experience; each position keeps the inputs that lower 2016-20 log loss. "If starter" points
weight the projection and starter-workload points by how well each called past promotions (small role, then a
starter's snaps).
"""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as G  # noqa: E402
import nfl_war as NW  # noqa: E402

ROOT, CACHE, REL = G.ROOT, G.CACHE, G.REL
FIT = os.path.join(ROOT, 'data', 'nfl_fantasy_fit.json')
OUT = os.path.join(ROOT, 'data', 'nfl_fantasy.json')                  # season, week, counts, backtest: read by Hugo
PLAYERS = os.path.join(ROOT, 'static', 'data', 'nfl-fantasy.json')    # every projection: fetched by the page
FIRST = 2009          # box scores and play-by-play start here; ratings warm up before anything is scored
SNAP0 = 2013          # snap counts start in 2013: rows from here train the model
TEST0, HOLD0 = 2016, 2021
SKILL = ('QB', 'RB', 'WR', 'TE')
COMPS = ['py', 'ptd', 'pint', 'ry', 'rtd', 'rc', 'wy', 'wtd', 'fl', 'tp', 'std']
USAGE = ['pa', 'ca', 'tg', 'ay', 'snap', 'fp']
PROJ = {'QB': ['py', 'ptd', 'pint', 'ry', 'rtd', 'fl', 'tp'],
        'RB': ['ry', 'rtd', 'rc', 'wy', 'wtd', 'fl', 'tp', 'std'],
        'WR': ['rc', 'wy', 'wtd', 'ry', 'rtd', 'fl', 'tp', 'std'],
        'TE': ['rc', 'wy', 'wtd', 'ry', 'rtd', 'fl', 'tp', 'std']}
USE = {'QB': ['pa', 'py', 'ptd', 'pint', 'ca', 'ry', 'rtd', 'snap', 'fl', 'tp', 'fp'],
       'RB': ['ca', 'ry', 'rtd', 'tg', 'rc', 'wy', 'wtd', 'snap', 'fl', 'tp', 'fp'],
       'WR': ['tg', 'rc', 'wy', 'wtd', 'ay', 'ca', 'ry', 'rtd', 'snap', 'fl', 'tp', 'std', 'fp'],
       'TE': ['tg', 'rc', 'wy', 'wtd', 'ay', 'ca', 'ry', 'rtd', 'snap', 'fl', 'tp', 'std', 'fp']}
KCOMP = ['fgs', 'fg4', 'fg5', 'xp']
KKEYS = KCOMP + ['fga', 'xpa']
DCOMP = ['sk', 'int', 'fr', 'dtd', 'sf', 'bk']
DKEYS = DCOMP + ['pa', 'osk', 'oint', 'ofl']     # o*: what the team's offense gives up (sacks, INTs, fumbles lost)
SCORING = {
    'std':  {'py': .04, 'ptd': 4, 'pint': -2, 'ry': .1, 'rtd': 6, 'rc': 0, 'wy': .1, 'wtd': 6, 'fl': -2, 'tp': 2, 'std': 6},
    'half': {'rc': .5}, 'ppr': {'rc': 1},
    'k': {'fgs': 3, 'fg4': 4, 'fg5': 5, 'xp': 1},
    'dst': {'sk': 1, 'int': 2, 'fr': 2, 'dtd': 6, 'sf': 2, 'bk': 2},
}
PA_TIERS = [(0, 0, 10), (1, 6, 7), (7, 13, 4), (14, 20, 1), (21, 27, 0), (28, 34, -1), (35, 99, -4)]
# fantasy-relevant pools for the backtest: top N at the position by the baseline (season-to-date points a game)
POOL = {'QB': 32, 'RB': 64, 'WR': 96, 'TE': 32, 'K': 32, 'DST': 32}
RIDGE = 1e-3
# opportunity and efficiency: each efficiency is (numerator, denominator); regressed to the position's mean by a
# stability constant k in opportunities (weight n / (n + k)), measured by split halves (see stability())
EFF = {'tprr': ('tg', 'routes'), 'cr': ('rc', 'tg'), 'ypt': ('wy', 'tg'), 'tdt': ('wtd', 'tg'),
       'ypc': ('ry', 'ca'), 'tdc': ('rtd', 'ca'), 'ypd': ('py', 'pa'), 'tdd': ('ptd', 'pa'), 'intd': ('pint', 'pa')}
STAB0 = {'tprr': 150.0, 'cr': 60.0, 'ypt': 80.0, 'tdt': 150.0, 'ypc': 250.0, 'tdc': 300.0, 'ypd': 300.0, 'tdd': 500.0, 'intd': 800.0,
         # measured on 2013-20 by stability() (fit writes the current values to the fit file)
         'QB.ypc': 75.9, 'QB.tdc': 88.9, 'QB.ypd': 446.1, 'QB.tdd': 435.4, 'QB.intd': 1368.4,
         'RB.tprr': 39.9, 'RB.cr': 199.8, 'RB.ypt': 255.8, 'RB.tdt': 148.5, 'RB.ypc': 275.3, 'RB.tdc': 317.3,
         'WR.tprr': 97.8, 'WR.cr': 71.4, 'WR.ypt': 158.2, 'WR.tdt': 334.0,
         'TE.tprr': 32.4, 'TE.cr': 101.5, 'TE.ypt': 85.8, 'TE.tdt': 327.3}
# a starter's workload, as shares of the team's dropbacks (routes for receivers), carries and targets
STARTER = {'QB': (1.0, 0.0, 0.0), 'RB': (0.0, 0.55, 0.12), 'WR': (0.9, 0.0, 0.0), 'TE': (0.8, 0.0, 0.0)}
# context: a short memory of each player's role (snaps, targets, carries, dropbacks) next to the long one, and the
# team's work left over when teammates are out (see Walk.vacated)
FAST_HL = 1.5
FASTK = {'QB': ['pa', 'ca', 'snap'], 'RB': ['ca', 'tg', 'snap'], 'WR': ['tg', 'ay', 'snap'], 'TE': ['tg', 'ay', 'snap']}
VOL = {'py': 'pa', 'ptd': 'pa', 'pint': 'pa', 'ry': 'ca', 'rtd': 'ca', 'rc': 'tg', 'wy': 'tg', 'wtd': 'tg'}
VOL_POS = {'QB': 'pa', 'RB': 'ca', 'WR': 'tg', 'TE': 'tg'}
P0 = {'ok': .95, 'ok-': .45, 'q': .75, 'q-': .6, 'd': .02, 'd-': .02, 'out': 0.0, 'out-': 0.0, 'res': .08, 'res-': .08,
      'rq': .55, 'rq-': .55}
# talent and return inputs, each position keeping those that lower its 2016-20 RMSE (forward selection, .002 a step):
#   war    WAR a game to date (nfl_war.py's model, last season at half weight, shrunk by three replacement games), as a
#          level and times his rate of the stat
#   draft  draft slot times his rate (the draft input above fades as his own games pile up; this one doesn't)
#   age    age on Sept 1 less 26, and its square (clipped to -4..8), times his rate
#   back   first game back after missing one of his team's games, or two or more, as a level and times his rate
#   q      questionable on this week's report and playing, as a level and times his rate
# Tried and not kept: a change of starting QB (his efficiency against the team's recent passing) for receivers (no
# position cleared the bar); a 40-game career memory (QB), points at a starter's workload as a talent rating (TE) and
# the position room's left-over work beside the team's (RB) cleared it, but together they were worth .003 of pooled
# held-out RMSE and each needs its own memory in the walk.
EXTRA = {'QB': ('war', 'draft', 'age', 'back'), 'RB': ('war', 'age', 'back', 'q'), 'WR': ('war', 'draft', 'age', 'q'),
         'TE': ('war', 'draft')}
EXTRA_NAMES = {'war': ['_war', '_war_x'], 'draft': ['_draft_x'], 'age': ['_age', '_age2'],
               'back': ['_back1_x', '_back2_x', '_back1', '_back2'], 'q': ['_q_x', '_q']}
AGE0 = 26


def weights(fmt):
    w = dict(SCORING['std']); w.update(SCORING.get(fmt, {}))
    return w


def pts(v, fmt='half'):
    w = weights(fmt)
    return sum(w[k] * v.get(k, 0.0) for k in w)


def kpts(v):
    return sum(SCORING['k'][k] * v.get(k, 0.0) for k in KCOMP)


def pa_points(pa):
    for lo, hi, p in PA_TIERS:
        if lo <= pa <= hi:
            return p
    return -4


def pa_expect(mu, sd):
    """Expected points-allowed tier points, the opponent's score ~ normal(mu, sd) rounded, floored at 0."""
    out, prev = 0.0, 0.0
    for lo, hi, p in PA_TIERS:
        c = G.phi((hi + 0.5 - mu) / sd) if hi < 99 else 1.0
        out += p * (c - prev); prev = c
    return out


def dpts(v, mu=None, sd=None):
    base = sum(SCORING['dst'][k] * v.get(k, 0.0) for k in DCOMP)
    if mu is not None:
        return base + pa_expect(mu, sd)
    return base + pa_points(v.get('pa', 0.0))


num = G.num
team = G.team


# ---------------------------------------------------------------- data
def opt(name, url, fresh=False):
    try:
        return G.get(name, url, fresh)
    except Exception as e:  # noqa: BLE001 (a missing season file is a gap, not a failure)
        print(f'nfl fantasy: no {name} ({e})')
        return None


def load_players(fresh=False):
    info, pfr = {}, {}
    p = opt('players.csv', f'{REL}/players/players.csv', fresh)
    if p:
        for r in G.rows(p):
            g = r['gsis_id']
            if not g:
                continue
            pk = int(num(r['draft_pick'])) if r['draft_pick'] not in ('', 'NA') else 0
            info[g] = {'n': r['display_name'], 'pos': r['position'], 'birth': r['birth_date'], 'pick': pk,
                       'rookie': r['rookie_season'], 'img': r['headshot'], 'col': r['college_name']}
            if r['pfr_id']:
                pfr[r['pfr_id']] = g
    return info, pfr


def load(first, last, fresh=False):
    """Every REG game first..last in kickoff order, and what each team's players did in it."""
    info, pfr = load_players(fresh)
    games = [g for g in G.rows(G.get('games.csv', G.GAMES, fresh)) if first <= int(g['season']) <= last and g['game_type'] == 'REG']
    games.sort(key=lambda g: (g['gameday'], g['gametime'], g['game_id']))
    box = defaultdict(dict)          # (gid, team) -> {gsis: (pos, vals)}
    dst = defaultdict(lambda: defaultdict(float))
    status, inj = {}, {}
    for y in range(first, last + 1):
        cur = fresh and y == last
        sp = opt(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv', cur)
        for r in (G.rows(sp) if sp else ()):
            gid = r.get('game_id')
            if r['season_type'] != 'REG' or not gid:
                continue
            t, pos, pid = team(r['team']), r['position'], r['player_id']
            d = dst[(gid, t)]
            d['sk'] += num(r['def_sacks']); d['int'] += num(r['def_interceptions']); d['fr'] += num(r['fumble_recovery_opp'])
            d['dtd'] += num(r['def_tds']) + num(r['special_teams_tds']); d['sf'] += num(r['def_safeties'])
            d['bk'] += num(r['def_fg_blocks']) + num(r['def_punt_blocks']) + num(r['def_pat_blocks'])
            d['osk'] += num(r['sacks_suffered']); d['oint'] += num(r['passing_interceptions'])
            d['ofl'] += num(r['sack_fumbles_lost']) + num(r['rushing_fumbles_lost']) + num(r['receiving_fumbles_lost'])
            if pos == 'FB':
                pos = 'RB'
            if pos == 'K':
                if num(r['fg_att']) + num(r['pat_att']) <= 0:
                    continue
                v = {'fgs': num(r['fg_made_0_19']) + num(r['fg_made_20_29']) + num(r['fg_made_30_39']),
                     'fg4': num(r['fg_made_40_49']), 'fg5': num(r['fg_made_50_59']) + num(r['fg_made_60_']),
                     'xp': num(r['pat_made']), 'fga': num(r['fg_att']), 'xpa': num(r['pat_att'])}
                box[(gid, t)][pid] = ('K', v)
                continue
            if pos not in SKILL:
                continue
            v = {'py': num(r['passing_yards']), 'ptd': num(r['passing_tds']), 'pint': num(r['passing_interceptions']),
                 'ry': num(r['rushing_yards']), 'rtd': num(r['rushing_tds']), 'rc': num(r['receptions']),
                 'wy': num(r['receiving_yards']), 'wtd': num(r['receiving_tds']),
                 'fl': num(r['sack_fumbles_lost']) + num(r['rushing_fumbles_lost']) + num(r['receiving_fumbles_lost']),
                 'tp': num(r['passing_2pt_conversions']) + num(r['rushing_2pt_conversions']) + num(r['receiving_2pt_conversions']),
                 'std': num(r['special_teams_tds']),
                 'pa': num(r['attempts']) + num(r['sacks_suffered']), 'ca': num(r['carries']), 'tg': num(r['targets']),
                 'ay': num(r['receiving_air_yards'])}
            box[(gid, t)][pid] = (pos, v)
        # snaps: share of the team's offensive plays; a skill player who took offensive snaps played even with no stat
        if y >= SNAP0:
            p = opt(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv', cur)
            plays = defaultdict(float); sn = []
            for r in (G.rows(p) if p else ()):
                if r['game_type'] != 'REG':
                    continue
                o = num(r['offense_snaps']); t = team(r['team'])
                plays[(r['game_id'], t)] = max(plays[(r['game_id'], t)], o)
                if o > 0 and r['position'] in ('QB', 'RB', 'FB', 'WR', 'TE'):
                    sn.append((r['game_id'], t, pfr.get(r['pfr_player_id']), 'RB' if r['position'] == 'FB' else r['position'], o))
            for gid, t, g, pos, o in sn:
                if not g:
                    continue
                b = box[(gid, t)]
                if g not in b:
                    b[g] = (pos, {})
                b[g][1]['snap'] = o / plays[(gid, t)] if plays[(gid, t)] else 0.0
        if y >= TEST0 - 1:
            p = opt(f'roster_weekly_{y}.csv', f'{REL}/weekly_rosters/roster_weekly_{y}.csv', cur)
            for r in (G.rows(p) if p else ()):
                if r['gsis_id']:
                    status[(y, int(r['week']), r['gsis_id'])] = (r['status'], team(r['team']), r['position'])
            p = opt(f'injuries_{y}.csv', f'{REL}/injuries/injuries_{y}.csv', cur)
            for r in (G.rows(p) if p else ()):
                if r.get('gsis_id') and r.get('game_type', 'REG') == 'REG':
                    # practicing with no game status counts only for a player on a reserve list (see av_class)
                    inj[(y, int(r['week']), r['gsis_id'])] = r['report_status'] or 'Practice'
    return games, box, dst, status, inj, info


# ---------------------------------------------------------------- the walk
class Walk:
    """Walks REG games in order, keeping every player's and team's weighted rates: read them before a game,
    update() after it."""
    def __init__(self, hl=5.0, carry=0.5, k0=2.0, thl=8.0, info=None, stab=None):
        self.a, self.carry, self.k0 = 0.5 ** (1 / hl), carry, k0
        self.stab = dict(STAB0, **(stab or {}))
        self.tv = defaultdict(lambda: [36.0 * 2, 26.0 * 2, 33.0 * 2, 2.0])   # team dropbacks, carries, targets a game
        self.lm = defaultdict(lambda: {m: [0.0, 0.0] for m in EFF})           # pos -> efficiency -> league num, den
        self.ta = 0.5 ** (1 / thl)
        self.a2 = 0.5 ** (1 / FAST_HL)
        self.lastg, self.tlast = {}, {}                            # gsis / team -> (season, week) of the last game
        self.p = {}                                               # gsis -> {'S': sums, 'W': weight, 's', 'pos', 't'}
        self.tp = defaultdict(lambda: [22.0 * 2, 2.0])            # team points scored (weighted sum, weight)
        self.d = defaultdict(lambda: {k: 0.0 for k in DKEYS})      # team defense and offense-allowed rates
        self.dw = defaultdict(float)
        self.allow = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))   # team -> pos -> half-PPR points allowed
        self.lgpos = defaultdict(lambda: [0.0, 0.0])
        self.lg = {k: [0.0, 0.0] for k in DKEYS}
        self.info = info or {}
        self.season = None
        self.sea = defaultdict(dict)       # id -> season -> [half points, games, standard, PPR] (the baseline)
        self.last3 = defaultdict(list)
        self.tdates = defaultdict(list)    # team -> (season, week) of each game it played

    def new_season(self, s):
        for t in self.tv:
            self.tv[t] = [x * 0.5 for x in self.tv[t][:3]] + [self.tv[t][3] * 0.5]
            self.tv[t] = [x + y for x, y in zip(self.tv[t], [36.0, 26.0, 33.0, 1.0])]
        for t in self.tp:
            v, w = self.tp[t]; self.tp[t] = [v * 0.5 + 22.0, w * 0.5 + 1]
        for t in self.d:
            for k in self.d[t]:
                self.d[t][k] *= 0.5
            self.dw[t] *= 0.5
        for t in self.allow:
            for pos in self.allow[t]:
                self.allow[t][pos][0] *= 0.5; self.allow[t][pos][1] *= 0.5
        self.last3.clear()
        self.season = s

    def state(self, gsis, s):
        st = self.p.get(gsis)
        if st is None:
            return None
        if st['s'] < s:
            f = self.carry ** (s - st['s'])
            for k in st['S']:
                st['S'][k] *= f
            st['W'] *= f; st['s'] = s
            for k in st['F']:
                st['F'][k] *= f
            st['WF'] *= f
        return st

    def rates(self, st):
        """Weighted per-game rates, shrunk toward zero by k0 games, and the share of weight that's his own."""
        W = st['W'] if st else 0.0
        den = W + self.k0
        S = st['S'] if st else {}
        return {k: S.get(k, 0.0) / den for k in COMPS + USAGE + KKEYS}, W / den

    def recent(self, st):
        """The role lately: snaps, targets, air yards, carries and dropbacks a game on a 1.5-game half-life."""
        if not st:
            return defaultdict(float)
        den = st['WF'] + self.k0
        return defaultdict(float, {k: x / den for k, x in st['F'].items()})

    def played_last(self, gsis, t):
        return gsis in self.lastg and self.lastg[gsis] == self.tlast.get(t)

    def missed(self, gsis, t, s):
        """His team's games this season since his last game (0 if he played the last one or it's week 1)."""
        lg = self.lastg.get(gsis)
        if lg is None:
            return 0
        n = 0
        for x in reversed(self.tdates.get(t, ())):
            if x[0] != s or x <= lg:
                break
            n += 1
        return n

    def vacated(self, t, members, pfun):
        """How much of the team's dropbacks, carries and targets nobody expected to play has been getting: the team's
        volume a game over the sum of each rostered player's rate times his chance to play (1 = all there, 1.3 = 30%
        more to go around). members: [(gsis, class)]."""
        D, C, T = self.team_vol(t)
        E = {'pa': 0.0, 'ca': 0.0, 'tg': 0.0}
        for gsis, cls in members:
            st = self.p.get(gsis)
            if not st or st['pos'] not in SKILL:
                continue
            den = st['W'] + self.k0
            pp = pfun(cls)
            for k in E:
                E[k] += pp * st['S'].get(k, 0.0) / den
        return {k: min(2.0, max(0.6, vol / E[k])) if E[k] > 1 else 1.0 for k, vol in (('pa', D), ('ca', C), ('tg', T))}

    def team_vol(self, t):
        D, C, T, w = self.tv[t]
        return D / w, C / w, T / w

    def eff(self, st, pos, m):
        """An efficiency regressed to the position's mean: (num + k x mean) / (den + k)."""
        n, d = EFF[m]
        ln, ld = self.lm[pos][m]
        mu = ln / ld if ld else 0.0
        k = self.stab.get(pos + '.' + m, self.stab[m])
        S = st['S'] if st else {}
        return (S.get(n, 0.0) + k * mu) / (S.get(d, 0.0) + k)

    def promoted(self, st, pos, t):
        """PPR points a game at a starter's workload (STARTER), at his efficiency per route, carry, target and dropback,
        each regressed to the position by its stability: what he'd score if the job were his."""
        D, C, T = self.team_vol(t)
        sd, sc, stg = STARTER[pos]
        e = lambda m: self.eff(st, pos, m)
        rec = lambda tg: tg * (e('cr') + 0.1 * e('ypt') + 6 * e('tdt'))
        if pos == 'QB':
            S, W = (st['S'], st['W']) if st else ({}, 0.0)
            rush = (0.1 * S.get('ry', 0.0) + 6 * S.get('rtd', 0.0)) / (W + self.k0)
            return D * (0.04 * e('ypd') + 4 * e('tdd') - 2 * e('intd')) + rush
        if pos == 'RB':
            return C * sc * (0.1 * e('ypc') + 6 * e('tdc')) + rec(T * stg)
        return rec(D * sd * e('tprr'))

    def team_pts(self, t):
        v, w = self.tp[t]
        return v / w

    def opp_factor(self, o, pos):
        v, w = self.allow[o][pos]; lv, lw = self.lgpos[pos]
        if lw <= 0:
            return 1.0
        lg = lv / lw
        return ((v + lg * 3) / (w + 3)) / lg if lg > 0 else 1.0

    def drate(self, t, k):
        lv, lw = self.lg[k]
        lg = lv / lw if lw else 0.0
        return (self.d[t][k] + lg * 2) / (self.dw[t] + 2)

    def credit(self, pid, s, half, std, ppr):
        q = self.sea[pid].setdefault(s, [0.0, 0, 0.0, 0.0])
        q[0] += half; q[1] += 1; q[2] += std; q[3] += ppr
        l3 = self.last3[pid]; l3.append(half); del l3[:-3]

    def update(self, g, box, dstbox):
        if g['home_score'] in ('', 'NA'):
            return
        s = int(g['season'])
        h, a = team(g['home_team']), team(g['away_team'])
        sc = {h: num(g['home_score']), a: num(g['away_score'])}
        for t, o in ((h, a), (a, h)):
            v, w = self.tp[t]; self.tp[t] = [v * self.ta + sc[t], w * self.ta + 1]
            vals = dst_line(dstbox.get((g['game_id'], t), {}), sc[o])
            dd = dstbox.get((g['game_id'], t), {})
            vals.update({'osk': dd.get('osk', 0.0), 'oint': dd.get('oint', 0.0), 'ofl': dd.get('ofl', 0.0)})
            for k in DKEYS:
                self.d[t][k] = self.d[t][k] * self.ta + vals[k]
                self.lg[k][0] = self.lg[k][0] * 0.998 + vals[k]; self.lg[k][1] = self.lg[k][1] * 0.998 + 1
            self.dw[t] = self.dw[t] * self.ta + 1
            dp = score('DST', vals)
            self.credit('D' + t, s, dp, dp, dp)
            # fantasy points this defense allowed, by position
            byp = defaultdict(float)
            for gsis, (pos, v) in box.get((g['game_id'], o), {}).items():
                if pos in SKILL:
                    byp[pos] += pts(v, 'half')
            for pos in SKILL:
                x = self.allow[t][pos]; x[0] = x[0] * self.ta + byp[pos]; x[1] = x[1] * self.ta + 1
                lp = self.lgpos[pos]; lp[0] = lp[0] * 0.998 + byp[pos]; lp[1] = lp[1] * 0.998 + 1
            self.tlast[t] = (s, int(g['week']))
            self.tdates[t].append((s, int(g['week'])))
            tb = box.get((g['game_id'], t), {})
            D = sum(v.get('pa', 0.0) for p_, v in tb.values() if p_ in SKILL)
            C = sum(v.get('ca', 0.0) for p_, v in tb.values() if p_ in SKILL)
            T = sum(v.get('tg', 0.0) for p_, v in tb.values() if p_ in SKILL)
            tv = self.tv[t]
            self.tv[t] = [tv[0] * self.ta + D, tv[1] * self.ta + C, tv[2] * self.ta + T, tv[3] * self.ta + 1]
            for gsis, (pos, v) in tb.items():
                st = self.state(gsis, s)
                if st is None:
                    st = self.p[gsis] = {'S': defaultdict(float), 'W': 0.0, 's': s, 'pos': pos, 't': t,
                                         'F': defaultdict(float), 'WF': 0.0}
                for k in st['S']:
                    st['S'][k] *= self.a
                st['W'] = st['W'] * self.a + 1
                for k in st['F']:
                    st['F'][k] *= self.a2
                st['WF'] = st['WF'] * self.a2 + 1
                for k in ('pa', 'ca', 'tg', 'ay', 'snap'):
                    st['F'][k] += v.get(k, 0.0)
                self.lastg[gsis] = (s, int(g['week']))
                if pos == 'K':
                    for k in KKEYS:
                        st['S'][k] += v.get(k, 0.0)
                    kp = kpts(v)
                    self.credit(gsis, s, kp, kp, kp)
                else:
                    fp = pts(v, 'half')
                    for k in COMPS + USAGE:
                        st['S'][k] += fp if k == 'fp' else v.get(k, 0.0)
                    rt = v.get('snap', 0.0) * D
                    st['S']['routes'] += rt; st['S']['tD'] += D; st['S']['tC'] += C; st['S']['tT'] += T
                    vv = dict(v, routes=rt)
                    lm = self.lm[pos]
                    for m, (n, d) in EFF.items():
                        if vv.get(d):
                            x = lm[m]; x[0] = x[0] * 0.9995 + vv.get(n, 0.0); x[1] = x[1] * 0.9995 + vv[d]
                    self.credit(gsis, s, fp, pts(v, 'std'), pts(v, 'ppr'))
                st['pos'], st['t'] = pos, t

    def baseline3(self, pid, s):
        """Season-to-date points a game (half PPR, standard, PPR); last season's before he's played this season."""
        q = self.sea.get(pid, {})
        for ss in (s, s - 1):
            if ss in q and q[ss][1]:
                n = q[ss][1]
                return (q[ss][0] / n, q[ss][2] / n, q[ss][3] / n)
        return None


def implied(last, fresh=False, walkforward=False, snaps_at=()):
    """Team points each game from the NFL game model (nfl_games.py). walkforward: a season's coefficients are fit on
    the seasons before it (2010 on, numpy), else the published fit. Also, at each (season, week) in snaps_at, the
    model's view of every remaining REG game that season from ratings as of that week (rest-of-season projections)."""
    F = json.load(open(G.FIT))
    allg, box, qbs = G.load(last, fresh)
    G.index_qbs(qbs, allg); G.load_qb_teams(last)
    m = G.Model(**F['params'])
    feats, snaps = {}, {}
    pending = sorted(set(snaps_at))
    reg = [g for g in allg if g['game_type'] == 'REG']

    def snap(ps, pw):
        if m.season != ps:
            m.new_season(ps)
        snaps[(ps, pw)] = {h['game_id']: m.feats(h) for h in reg if int(h['season']) == ps and int(h['week']) >= pw}
    for g in allg:
        s, w = int(g['season']), int(g['week'])
        while pending and (pending[0][0] < s or (pending[0][0] == s and pending[0][1] <= w and g['game_type'] == 'REG')):
            snap(*pending.pop(0))
        feats[g['game_id']] = m.feats(g)
        m.update(g, box, qbs)
    for ps, pw in pending:      # checkpoints past the last listed game (the build's coming week)
        snap(ps, pw)
    seas = {g['game_id']: int(g['season']) for g in allg}
    cf = defaultdict(lambda: (F['coef'], F['tcoef']))
    if walkforward:
        import numpy as np
        D = [g for g in allg if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2010]
        X = np.array([[feats[g['game_id']][0][f] for f in G.FEATS] for g in D]); y = np.array([num(g['result']) for g in D])
        TX = np.array([[feats[g['game_id']][1][f] for f in G.TFEATS] for g in D]); ty = np.array([num(g['total']) for g in D])
        S = np.array([int(g['season']) for g in D])
        for s in range(2011, last + 1):
            tr = S < s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; tb = np.linalg.lstsq(TX[tr], ty[tr], rcond=None)[0]
            cf[s] = ({f: float(v) for f, v in zip(G.FEATS, b)}, {f: float(v) for f, v in zip(G.TFEATS, tb)})

    def pair(s, x, tx):
        b, tb = cf[s]
        mar = sum(b[f] * x[f] for f in G.FEATS); tot = sum(tb[f] * tx[f] for f in G.TFEATS)
        return (tot + mar) / 2, (tot - mar) / 2
    model = {gid: pair(seas[gid], *xt) for gid, xt in feats.items()}
    snapv = {k: {gid: pair(k[0], *xt) for gid, xt in v.items()} for k, v in snaps.items()}
    return model, snapv


# ---------------------------------------------------------------- features
def dv(info, gsis):
    """Draft slot as a 0-1 prior: 1 for the first pick, 0 undrafted."""
    pk = (info.get(gsis) or {}).get('pick', 0)
    return max(0.0, 1 - math.log(pk) / math.log(262)) if pk else 0.0


def skill_x(e, wf, d, pos, c, r, o, vf=None, e2=None, x=None):
    f = (vf or {}).get(VOL.get(c, VOL_POS[pos]), 1.0) - 1
    e2 = e2 if e2 is not None else e
    return ([1.0, wf, d * (1 - wf)] + [e[k] for k in USE[pos]] + [(r - 1) * e[c], r - 1, (o - 1) * e[c]]
            + [f * e[c], f] + [e2[k] - e[k] for k in FASTK[pos]] + extra_x(e[c], d, pos, x or {}))


def extra_x(ec, d, pos, x):
    """The talent and return inputs (EXTRA) for a stat he takes at rate ec."""
    out = []
    for k in EXTRA[pos]:
        if k == 'war':
            v = x.get('war', 0.0); out += [v, v * ec]
        elif k == 'draft':
            out += [d * ec]
        elif k == 'age':
            ag = x.get('age', AGE0) - AGE0; out += [ag * ec, min(8, max(-4, ag)) ** 2 * ec]
        elif k == 'back':
            m = x.get('missed', 0); b1, b2 = float(m == 1), float(m >= 2); out += [b1 * ec, b2 * ec, b1, b2]
        elif k == 'q':
            q = x.get('q', 0.0); out += [q * ec, q]
    return out


def extras(W, info, wars, gsis, t, s, cls):
    """What extra_x reads for a player before his team's next game."""
    a = NW.age((info.get(gsis) or {}).get('birth'), s)
    return {'war': wars.get(gsis, 0.0), 'age': AGE0 if a is None else a, 'missed': W.missed(gsis, t, s),
            'q': 1.0 if cls in ('q', 'q-') else 0.0}


def war_now(s, w, maps=None, fresh=False):
    """{gsis: WAR a game} before week w of season s: last season at half weight plus this one to date, shrunk with
    three replacement games (the game model's injury value)."""
    prev = NW.war_ledger(s - 1, maps=NW.gsis_map(s - 1, fresh))
    cur = NW.war_ledger(s, thru=w, maps=maps or NW.gsis_map(s, fresh), fresh=fresh)
    return {g: G.player_value(prev.get(g, (0.0, 0)), cur.get(g, (0.0, 0))) for g in set(prev) | set(cur)}


def war_history(first, last):
    """{(season, week): {gsis: WAR a game before that week}} for every week of first..last (cached by season)."""
    cp = os.path.join(CACHE, 'war_weeks_v1.json')
    try:
        cache = json.load(open(cp))
    except (OSError, ValueError):
        cache = {}
    out = {}
    for y in range(first, last + 1):
        if str(y) not in cache:
            maps, prev = NW.gsis_map(y), NW.war_ledger(y - 1, maps=NW.gsis_map(y - 1))
            wk = {}
            for w in range(1, 19):
                cur = NW.war_ledger(y, thru=w, maps=maps)
                wk[str(w)] = {g: round(G.player_value(prev.get(g, (0.0, 0)), cur.get(g, (0.0, 0))), 5) for g in set(prev) | set(cur)}
            cache[str(y)] = wk
            json.dump(cache, open(cp, 'w'))
            print('war', y, flush=True)
        for w, v in cache[str(y)].items():
            out[(y, int(w))] = v
    return out


def skill_names(pos):
    return (['one', 'wf', '_draft'] + USE[pos] + ['_env', '_env0', '_opp', '_vac', '_vac0'] + ['_recent_' + k for k in FASTK[pos]]
            + [n for k in EXTRA[pos] for n in EXTRA_NAMES[k]])


def k_x(e, wf, r, imp, dome):
    return [1.0, wf, e['fgs'], e['fg4'], e['fg5'], e['xp'], e['fga'], e['xpa'], (r - 1) * e['xp'], (r - 1) * e['fga'], imp, dome]


def d_x(W, t, o, k, imp_opp):
    own = W.drate(t, k)
    opp = {'sk': W.drate(o, 'osk'), 'int': W.drate(o, 'oint'), 'fr': W.drate(o, 'ofl')}.get(k, 0.0)
    return [1.0, own, opp, imp_opp]


def env(W, t, imp):
    tp = W.team_pts(t)
    return max(0.5, min(2.0, imp / tp)) if tp > 0 else 1.0


def game_imp(g, model, market=True):
    """(home, away) implied points: the market's (spread and total) when listed, else the game model's."""
    h, a = model.get(g['game_id'], (22.0, 22.0))
    sl, tl = num(g['spread_line'], None), num(g['total_line'], None)
    if market and sl is not None and tl is not None and tl > 0:
        return (tl + sl) / 2, (tl - sl) / 2
    return h, a


def dot(x, b):
    return sum(p * q for p, q in zip(x, b))


def score(pos, v, fmt='half'):
    """Points from a stat line; for a defense, v carries 'pap' (expected points-allowed tier points) or 'pa'."""
    if pos == 'K':
        return kpts(v)
    if pos == 'DST':
        base = sum(SCORING['dst'][k] * v.get(k, 0.0) for k in DCOMP)
        return base + (v['pap'] if 'pap' in v else pa_points(v.get('pa', 0.0)))
    return pts(v, fmt)


def dst_line(dd, pa):
    y = {k: dd.get(k, 0.0) for k in DCOMP}; y['pa'] = pa
    return y


def project(W, info, coef, pos, gsis, t, s, games, imp_of, pa_sd, vac=None, ex=None):
    """The stat line in each of `games` (if he plays), from rates as of now: [(game, {stat: value})]. ex: extras() for
    the next game; later games drop the return and questionable inputs (he'd be back in rhythm, and the report is
    this week's)."""
    out = []
    if pos == 'DST':
        for g in games:
            home = team(g['home_team']) == t
            o = team(g['away_team']) if home else team(g['home_team'])
            ti, oi = imp_of(g, home)
            v = {c: max(0.0, dot(d_x(W, t, o, c, oi), coef[c])) for c in DCOMP}
            v['pap'] = pa_expect(oi, pa_sd)
            out.append((g, v))
        return out
    st = W.state(gsis, s)
    e, wf = W.rates(st)
    d = dv(info, gsis)
    e2 = W.recent(st)
    for k, g in enumerate(games):
        home = team(g['home_team']) == t
        o = team(g['away_team']) if home else team(g['home_team'])
        ti, oi = imp_of(g, home)
        r = env(W, t, ti)
        if pos == 'K':
            x = k_x(e, wf, r, ti, 1.0 if g['roof'] in ('dome', 'closed') else 0.0)
            v = {c: max(0.0, dot(x, coef[c])) for c in KCOMP}
        else:
            o_f = W.opp_factor(o, pos)
            vf = vac[min(k, len(vac) - 1)] if vac else None
            x = (ex or {}) if k == 0 else dict(ex or {}, missed=0, q=0.0)
            v = {c: max(0.0, dot(skill_x(e, wf, d, pos, c, r, o_f, vf, e2, x), coef[c])) for c in PROJ[pos]}
        out.append((g, v))
    return out


# ---------------------------------------------------------------- availability
AV_K = 18
AV_CLASSES = ('ok', 'q', 'd', 'out', 'res', 'rq')


def roster_status(status, s, w, gsis):
    """The latest roster entry before week w (up to three weeks back; week 1's own in week 1)."""
    for ww in ((1,) if w <= 1 else range(w - 1, max(0, w - 4), -1)):
        st = status.get((s, ww, gsis))
        if st:
            return st
    return None


def av_class(status, inj, s, w, gsis, played_last):
    """What a manager knows before week w: the injury report for week w, the roster status the week before, and
    whether he played his team's last game ('-' when he didn't). 'rq': on a reserve list (IR, PUP ...) last week but on
    this week's report as questionable or practicing with no game status, the usual sign he's due back (2016-25, any
    skill player: 53% of the questionable and 67% of the practicing played, against 0-3% for the rest of the list)."""
    rep = inj.get((s, w, gsis), '')
    st = roster_status(status, s, w, gsis)
    if rep == 'Out':
        c = 'out'
    elif rep == 'Doubtful':
        c = 'd'
    elif st is None or st[0] not in ('ACT', 'INA'):
        c = 'rq' if rep in ('Questionable', 'Practice') else 'res'
    elif rep == 'Questionable':
        c = 'q'
    else:
        c = 'ok'
    return c + ('' if played_last else '-')


def live_statuses(inj, status, s, w):
    """This week's statuses from the game projections (data/nfl_injuries.json: the league's report, ESPN and
    Rotoballer, scoped to this week's game) in place of the league's report alone: news after the report counts, a
    player cleared this week loses last week's tag, and one placed on a reserve list since last week's roster counts as
    out. Last week's designation carried into a week with no report yet adds nothing: whether he played last week
    already carries it."""
    try:
        d = json.load(open(G.INJ_OUT))
    except (OSError, ValueError):
        return
    if d.get('season') != s or d.get('week') != w:
        return
    for ps in d['teams'].values():
        for gsis, (st, _) in ps.items():
            if st in ('Out', 'Doubtful', 'Questionable'):
                inj[(s, w, gsis)] = st
            elif st in G.GONE and (roster_status(status, s, w, gsis) or ('ACT',))[0] in ('ACT', 'INA'):
                inj[(s, w, gsis)] = 'Out'
            elif st in ('Active', 'Probable'):
                if (roster_status(status, s, w, gsis) or ('ACT',))[0] in ('ACT', 'INA'):
                    inj.pop((s, w, gsis), None)
                else:
                    inj[(s, w, gsis)] = 'Practice'      # back on the report from a reserve list


def p_play(avail, cls, k):
    return avail[cls]['p'][min(k, AV_K - 1)]


# ---------------------------------------------------------------- fit
def roster_index(status):
    """(season, week, team) -> the skill players on that week's roster."""
    ix = defaultdict(list)
    for (s, w, gsis), (st, t, pos) in status.items():
        if pos in SKILL + ('FB',):
            ix[(s, w, t)].append(gsis)
    return ix


def members(W, ridx, status, inj, s, w, t):
    """Who the team has before week w, with what's known about each: [(gsis, availability class)]."""
    ww = 1 if w <= 1 else w - 1
    ids = ridx.get((s, ww, t)) or ridx.get((s, w, t)) or []
    return [(gsis, av_class(status, inj, s, w, gsis, w <= 1 or W.played_last(gsis, t))) for gsis in ids]


def breakout_x(W, info, gsis, st, pos, t, s, e, e2, vf, d):
    """What the breakout score reads, before a game: points at a starter's workload, the role's trend, the team's
    left-over work, years in the league and draft slot."""
    rk = num((info.get(gsis) or {}).get('rookie') or 0)
    return {'prom': W.promoted(st, pos, t), 'trend': e2['snap'] - e['snap'], 'snap': e['snap'],
            'vac': (vf or {}).get(VOL_POS[pos], 1.0) - 1, 'draft': d, 'yrs': min(6.0, s - rk) if rk else 3.0}


def breakout(W, info, m, gsis, pos, t, s, line, vf, vmed=None):
    """The board's breakout read for a player below the starter line: odds of a starter's points over his next four
    games, points a game if he gets the job, and why, in a few words. None for anyone else."""
    st = W.state(gsis, s)
    if not st:
        return None
    e, wf = W.rates(st)
    e2 = W.recent(st)
    proj = score(pos, line, 'ppr')
    b = breakout_x(W, info, gsis, st, pos, t, s, e, e2, vf, dv(info, gsis))
    q = W.baseline3(gsis, s)
    if not bo_candidate(pos, proj, q[2] if q else None, b['snap']):
        return None
    f = bo_feats(b, proj)
    p = bo_odds(m, f)
    if p < 0.05:
        return None
    j = m['job']
    why = []
    k = VOL_POS[pos]
    extra = (1 + b['vac']) / (vmed or {}).get(k, 1.0) - 1        # against a typical team this week
    if extra >= 0.15:
        why.append(f"teammates out: +{round(100 * extra)}% team {dict(pa='dropbacks', ca='carries', tg='targets')[k]} open vs typical")
    if b['trend'] >= 0.08:
        why.append(f"snap share {round(100 * e['snap'])}% -> {round(100 * e2['snap'])}%")
    if pos in ('QB', 'WR') and b['prom'] >= BO_LINE[pos]:
        why.append(f"{b['prom']:.1f} PPR/G at starter workload")
    if f['young'] and pos == 'WR':
        why.append('year 1-2')
    return {'p': round(p, 3), 'job': round(max(0.0, j[0] + j[1] * proj + j[2] * b['prom']), 1), 'why': why[:2]}


def vac_path(W, t, mem, avail, n):
    """The team's left-over work in each of its next n games: teammates out now come back on the odds in avail."""
    return [W.vacated(t, mem, lambda c, k=k: p_play(avail, c, k)) for k in range(min(max(n, 1), AV_K))]


def collect(games, box, dst, info, model, params, status=None, inj=None, wars=None):
    """Walk every game; one row per player-game played (2013 on): features before kickoff, the stat line after.
    Returns per position: season, week, id, X[stat], Y[stat], baselines (season-to-date points a game, three formats),
    last-3 average, and (defenses) the opponent's implied points. wars: war_history()."""
    W = Walk(info=info, **params)
    ridx = roster_index(status or {})
    R = defaultdict(lambda: {'s': [], 'w': [], 'id': [], 'X': defaultdict(list), 'Y': defaultdict(list), 'b': [], 'l3': [], 'oi': [], 'B': []})

    def add(pos, s, w, gsis, X, Y, oi=0.0):
        r = R[pos]
        r['s'].append(s); r['w'].append(w); r['id'].append(gsis); r['oi'].append(oi)
        for c, x in X.items():
            r['X'][c].append(x)
        for c, y in Y.items():
            r['Y'][c].append(y)
        b = W.baseline3(gsis, s)
        r['b'].append(b if b else (math.nan,) * 3)
        l3 = W.last3.get(gsis)
        r['l3'].append(sum(l3) / len(l3) if l3 else math.nan)
    for g in games:
        s, w = int(g['season']), int(g['week'])
        if s != W.season:
            W.new_season(s)
        if g['home_score'] in ('', 'NA'):
            continue
        hi, ai = game_imp(g, model)
        h, a = team(g['home_team']), team(g['away_team'])
        dome = 1.0 if g['roof'] in ('dome', 'closed') else 0.0
        sc = {h: num(g['home_score']), a: num(g['away_score'])}
        if s >= SNAP0:
            for t, o, imp, oimp in ((h, a, hi, ai), (a, h, ai, hi)):
                r = env(W, t, imp)
                vf = W.vacated(t, members(W, ridx, status, inj, s, w, t), P0.get) if status else None
                for gsis, (pos, v) in box.get((g['game_id'], t), {}).items():
                    st = W.state(gsis, s)
                    e, wf = W.rates(st)
                    if pos == 'K':
                        add('K', s, w, gsis, {c: k_x(e, wf, r, imp, dome) for c in KCOMP}, {c: v.get(c, 0.0) for c in KCOMP})
                        continue
                    o_f = W.opp_factor(o, pos); d = dv(info, gsis); e2 = W.recent(st)
                    cls = av_class(status, inj, s, w, gsis, w <= 1 or W.played_last(gsis, t)) if status else 'ok'
                    x = extras(W, info, (wars or {}).get((s, min(w, 18)), {}), gsis, t, s, cls)
                    add(pos, s, w, gsis, {c: skill_x(e, wf, d, pos, c, r, o_f, vf, e2, x) for c in PROJ[pos]}, dict({c: v.get(c, 0.0) for c in COMPS}, snapY=v.get('snap', 0.0)))
                    R[pos]['B'].append(breakout_x(W, info, gsis, st, pos, t, s, e, e2, vf, d))
                add('DST', s, w, 'D' + t, {k: d_x(W, t, o, k, oimp) for k in DCOMP}, dst_line(dst.get((g['game_id'], t), {}), sc[o]), oimp)
        W.update(g, box, dst)
    return R, W


def arrays(R):
    import numpy as np
    A = {}
    for pos, r in R.items():
        A[pos] = {'s': np.array(r['s']), 'w': np.array(r['w']), 'id': r['id'], 'oi': np.array(r['oi']),
                  'X': {c: np.array(x) for c, x in r['X'].items()}, 'Y': {c: np.array(y) for c, y in r['Y'].items()},
                  'b': np.array(r['b']), 'l3': np.array(r['l3']), 'B': r['B']}
    return A


def ridge(X, y, lam=RIDGE):
    import numpy as np
    A = X.T @ X
    D = np.diag(np.diag(A)) * lam; D[0, 0] = 0
    return np.linalg.solve(A + D + np.eye(len(A)) * 1e-9, X.T @ y)


def comps_of(pos):
    return KCOMP if pos == 'K' else DCOMP if pos == 'DST' else PROJ[pos]


def walk_forward(A, seasons, cols=None):
    """Refit each test season on the seasons before it (2013 on); predicted stat lines for the test seasons."""
    import numpy as np
    P = {}
    for pos, a in A.items():
        S = a['s']
        P[pos] = {c: np.full(len(S), np.nan) for c in comps_of(pos)}
        for s in seasons:
            tr, te = (S >= SNAP0) & (S < s), S == s
            if not te.any() or not tr.any():
                continue
            for c in comps_of(pos):
                X = a['X'][c] if cols is None or pos not in cols else a['X'][c][:, cols[pos]]
                b = ridge(X[tr], a['Y'][c][tr])
                P[pos][c][te] = np.clip(X[te] @ b, 0, None)
    return P


def points(pos, a, V, fmt, pa_sd=None, actual=False):
    """Points for every row from stat-line arrays V (predicted, or actual when actual=True)."""
    import numpy as np
    if pos == 'K':
        return sum(SCORING['k'][c] * V[c] for c in KCOMP)
    if pos == 'DST':
        base = sum(SCORING['dst'][c] * V[c] for c in DCOMP)
        if actual:
            return base + np.array([pa_points(x) for x in V['pa']])
        return base + np.array([pa_expect(mu, pa_sd) for mu in a['oi']])
    w = weights(fmt)
    return sum(w[c] * V[c] for c in V if c in w)


FMT_IX = {'half': 0, 'std': 1, 'ppr': 2}


def pool(a, seasons, n):
    """Indices of the fantasy-relevant rows: each week, the top n at the position by season-to-date points a game."""
    import numpy as np
    b = a['b'][:, 0]
    idx = np.where(np.isin(a['s'], list(seasons)) & ~np.isnan(b))[0]
    by = defaultdict(list)
    for i in idx:
        by[(a['s'][i], a['w'][i])].append(i)
    keep = []
    for k, ii in by.items():
        ii.sort(key=lambda i: -b[i]); keep += ii[:n]
    return np.array(sorted(keep), dtype=int)


def evaluate(A, P, seasons, fmt='half', pa_sd=None, only=None):
    """MAE and correlation of projected vs actual points on the fantasy-relevant pool: the model, season-to-date
    points a game (the baseline) and the last three games."""
    import numpy as np
    out = {}
    for pos, a in A.items():
        if only and pos not in only:
            continue
        k = pool(a, seasons, POOL[pos])
        k = k[~np.isnan(P[pos][comps_of(pos)[0]][k])]
        if not len(k):
            continue
        y = points(pos, a, a['Y'], fmt, actual=True)[k]
        p = points(pos, a, P[pos], fmt, pa_sd)[k]
        b = a['b'][k, 0 if pos in ('K', 'DST') else FMT_IX[fmt]]
        res = {'n': int(len(k)), 'mean': round(float(y.mean()), 2), 'bias': round(float((p - y).mean()), 2),
               'maeModel': round(float(np.mean(np.abs(p - y))), 3), 'maeBase': round(float(np.mean(np.abs(b - y))), 3),
               'rmseModel': round(float(np.sqrt(np.mean((p - y) ** 2))), 3), 'rmseBase': round(float(np.sqrt(np.mean((b - y) ** 2))), 3),
               'rModel': round(float(np.corrcoef(p, y)[0, 1]), 3), 'rBase': round(float(np.corrcoef(b, y)[0, 1]), 3)}
        l3 = a['l3'][k]; ok = ~np.isnan(l3)
        if pos not in ('DST',) and fmt == 'half' and ok.any():
            res['maeLast3'] = round(float(np.mean(np.abs(l3[ok] - y[ok]))), 3)
        res['gain'] = round(1 - res['maeModel'] / res['maeBase'], 3)
        out[pos] = res
    return out


def pooled(ev, keys=SKILL, stat='rmseModel'):
    """Pooled error over positions; RMSE by default, since a projection is an expected value (the mean), and squared
    error is what the mean minimizes (absolute error rewards the median, which for skewed points is lower)."""
    n = sum(ev[k]['n'] for k in keys if k in ev)
    if stat.startswith('rmse'):
        return math.sqrt(sum(ev[k][stat] ** 2 * ev[k]['n'] for k in keys if k in ev) / n)
    return sum(ev[k][stat] * ev[k]['n'] for k in keys if k in ev) / n


def fit():
    import numpy as np
    last = 2025
    games, box, dst, status, inj, info = load(FIRST, last)
    print('loaded', len(games), 'games')
    cps = [(s, w) for s in range(HOLD0, last + 1) for w in (4, 8, 12)]
    model, snapv = implied(last, walkforward=True, snaps_at=cps)
    wars = war_history(SNAP0, last)
    # tune the rating memory on 2016-20 out-of-sample RMSE (half PPR, skill positions); 2021-25 stays held out
    grid = []
    tune = list(range(TEST0, HOLD0))
    for hl in (3, 5, 8):
        for carry in (0.35, 0.6):
            for k0 in (1.0, 2.5):
                p = {'hl': hl, 'carry': carry, 'k0': k0}
                R, _ = collect(games, box, dst, info, model, p, status, inj, wars)
                A = arrays({k: v for k, v in R.items() if k in SKILL})
                err = pooled(evaluate(A, walk_forward(A, tune), tune))
                grid.append((err, p)); print('grid', p, round(err, 4), flush=True)
    grid.sort(key=lambda z: z[0])
    best = grid[0][1]
    R, W = collect(games, box, dst, info, model, best, status, inj, wars)
    A = arrays(R)
    seasons = list(range(TEST0, last + 1))
    P = walk_forward(A, seasons)
    # the opponent's score around his implied points (2013-15, before any test season)
    d = A['DST']; tr = d['s'] < TEST0
    pa_sd = float(np.std(d['Y']['pa'][tr] - d['oi'][tr]))
    hold = list(range(HOLD0, last + 1))
    test = {}
    for name, ss in (('2016-20 (tuning)', tune), ('2021-25 (held out)', hold)):
        test[name] = {f: evaluate(A, P, ss, f, pa_sd) for f in ('std', 'half', 'ppr')}
    # what each input adds out of sample: leave it out, refit, and see how much worse the RMSE gets (half PPR, skill
    # positions; positive = the input helps), on the tuning seasons and on the held-out ones
    groups = {'usage': ['pa', 'ca', 'tg', 'ay', 'snap'], 'game environment': ['_env', '_env0'],
              'opponent vs position': ['_opp'], 'draft slot': ['_draft'], 'teammates out': ['_vac', '_vac0'],
              'recent role': ['_recent_' + k for k in ('pa', 'ca', 'tg', 'ay', 'snap')],
              'production history': ['py', 'ptd', 'pint', 'ry', 'rtd', 'rc', 'wy', 'wtd', 'fl', 'tp', 'std', 'fp'],
              'talent: WAR a game': EXTRA_NAMES['war'], 'talent: draft slot, age': EXTRA_NAMES['draft'] + EXTRA_NAMES['age'],
              'return from missed games': EXTRA_NAMES['back'], 'questionable and playing': EXTRA_NAMES['q']}
    SA = {k: A[k] for k in SKILL}
    abl = {}
    for period, ss in (('2016-20', tune), ('2021-25', hold)):
        base_err = pooled(evaluate(SA, P, ss))
        for gname, keys in groups.items():
            cols = {pos: [i for i, nme in enumerate(skill_names(pos)) if nme not in keys] for pos in SKILL}
            err = pooled(evaluate(SA, walk_forward(SA, ss, cols), ss))
            abl.setdefault(gname, {})[period] = round(err - base_err, 4)
            print('without', gname, period, abl[gname][period], flush=True)
    # breakouts: projections for 2014-15 too, so the first test season's odds have two seasons to learn from
    PB = walk_forward(SA, [2014, 2015])
    for pos in SKILL:
        for c in P[pos]:
            m = np.isin(A[pos]['s'], [2014, 2015]); P[pos][c][m] = PB[pos][c][m]
    bo_test, bo_model = breakouts(SA, P)
    stab = stability(games, box, HOLD0 - 1)
    avail = fit_avail(games, box, status, inj, A)
    ros = ros_backtest(games, box, dst, info, model, snapv, best, A, avail, pa_sd, status, inj, cps, wars)
    # published coefficients: every season 2013-25
    coef = {}
    for pos, a in A.items():
        m = a['s'] >= SNAP0
        coef[pos] = {c: [round(float(v), 6) for v in ridge(a['X'][c][m], a['Y'][c][m])] for c in comps_of(pos)}
    out = {'params': best, 'paSd': round(pa_sd, 2), 'test': test, 'ablation': abl, 'ros': ros, 'pool': POOL,
           'breakout': {'test': bo_test, 'model': bo_model, 'line': BO_LINE, 'cut': BO_CUT}, 'stability': stab,
           'avail': avail, 'coef': coef, 'grid': [[round(e, 4), p] for e, p in grid],
           'features': {pos: skill_names(pos) for pos in SKILL}}
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k in ('params', 'paSd', 'ablation', 'ros')}, indent=1))
    print(json.dumps(test['2021-25 (held out)']['half'], indent=1))


def stability(games, box, last):
    """How fast each efficiency stabilizes, by position: split every player-season into odd and even games, correlate
    the halves across players with enough of the denominator in each, and turn the split-half reliability r at the
    typical half sample n into k = n (1 - r) / r, the opportunities at which half of what we see is signal
    (reliability n / (n + k)). Seasons up to last."""
    import numpy as np
    MIN = {'routes': 60.0, 'tg': 12.0, 'ca': 25.0, 'pa': 80.0}
    acc = defaultdict(lambda: [defaultdict(float), defaultdict(float)])   # (s, gsis, pos) -> [odd sums, even sums]
    gn = defaultdict(int)
    for g in games:
        if int(g['season']) > last or int(g['season']) < SNAP0 or g['home_score'] in ('', 'NA'):
            continue
        for t in (team(g['home_team']), team(g['away_team'])):
            tb = box.get((g['game_id'], t), {})
            D = sum(v.get('pa', 0.0) for p_, v in tb.values() if p_ in SKILL)
            for gsis, (pos, v) in tb.items():
                if pos not in SKILL:
                    continue
                key = (int(g['season']), gsis, pos)
                h = acc[key][gn[key] % 2]; gn[key] += 1
                for k in ('tg', 'rc', 'wy', 'wtd', 'ry', 'rtd', 'ca', 'py', 'ptd', 'pint', 'pa'):
                    h[k] += v.get(k, 0.0)
                h['routes'] += v.get('snap', 0.0) * D
    out = {}
    for pos in SKILL:
        for m, (n, d) in EFF.items():
            xs, ys, ns = [], [], []
            for (s, gsis, p_), (a, b) in acc.items():
                if p_ == pos and a[d] >= MIN[d] and b[d] >= MIN[d]:
                    xs.append(a[n] / a[d]); ys.append(b[n] / b[d]); ns.append((a[d] + b[d]) / 2)
            if len(xs) < 40:
                continue
            r = float(np.corrcoef(xs, ys)[0, 1])
            nh = float(np.median(ns))
            out[pos + '.' + m] = round(min(5000.0, nh * (1 - r) / r) if r > 0.02 else 5000.0, 1)
            print('stability', pos, m, 'r', round(r, 3), 'n', round(nh), 'k', out[pos + '.' + m], len(xs), flush=True)
    return out


# ---------------------------------------------------------------- breakouts
# A breakout: a player below the starter line (PPR points a game, about QB12 / RB24 / WR36 / TE12 in a 12-team
# league) who scores at it over his next four games. Candidates: projected and averaging under 85% of the line,
# with a role (5%+ of snaps). The score is the walk-forward logistic odds of that, from the inputs below; each
# position keeps only the inputs that lower out-of-sample log loss on 2016-20.
BO_LINE = {'QB': 18.0, 'RB': 12.0, 'WR': 12.0, 'TE': 9.0}
BO_KEYS = ['proj', 'prom', 'trend', 'vac', 'draft', 'young', 'snap']
PROMO = {'QB': (0.5, 0.9), 'RB': (0.4, 0.55), 'WR': (0.5, 0.75), 'TE': (0.45, 0.65)}   # small role, then a starter's snaps
BO_CUT = 0.2           # flagged at 20% odds or better (the base rate is 5-12%)


def bo_feats(b, proj):
    """Inputs to the breakout odds from breakout_x() and this week's projected PPR line."""
    return {'proj': proj, 'prom': b['prom'], 'trend': b['trend'], 'vac': b['vac'], 'draft': b['draft'],
            'young': 1.0 if b['yrs'] <= 1 else 0.0, 'snap': b['snap']}


def bo_candidate(pos, proj, ppg, snap):
    return proj < 0.85 * BO_LINE[pos] and (ppg is None or ppg != ppg or ppg < 0.85 * BO_LINE[pos]) and snap > 0.05


def bo_odds(m, f):
    z = m['w'][0] + sum(wk * (f[k] - mu) / sd for k, wk, mu, sd in zip(m['keys'], m['w'][1:], m['mu'], m['sd']))
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def logit_fit(X, y, lam=1.0):
    import numpy as np
    w = np.zeros(X.shape[1]); R = lam * np.diag(np.r_[0, np.ones(len(w) - 1)])
    for _ in range(40):
        pr = 1 / (1 + np.exp(-(X @ w)))
        H = (X * (pr * (1 - pr))[:, None]).T @ X + R + 1e-9 * np.eye(len(w))
        w -= np.linalg.solve(H, X.T @ (pr - y) + R @ w)
    return w


def breakouts(A, P):
    """The breakout score: rows, a walk-forward backtest (2016-20 picks the inputs, 2021-25 reports) and the
    published model."""
    import numpy as np
    out, model = {}, {}

    def auc(p, y):
        o = np.argsort(p); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1)
        n1 = y.sum(); n0 = len(y) - n1
        return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else math.nan
    for pos in SKILL:
        a = A[pos]
        s, w, ids = a['s'], a['w'], a['id']
        proj = points(pos, a, P[pos], 'ppr'); y = points(pos, a, a['Y'], 'ppr', actual=True)
        ppg = a['b'][:, 2]
        n = len(s)
        order = sorted(range(n), key=lambda i: (ids[i], s[i], w[i]))
        y4 = np.full(n, np.nan)
        for j, i in enumerate(order):
            fut = [k for k in order[j:j + 4] if ids[k] == ids[i] and s[k] == s[i]]
            if len(fut) >= 3:
                y4[i] = y[fut].mean()
        F_ = [bo_feats(b, pj) for b, pj in zip(a['B'], proj)]
        cand = np.array([not math.isnan(y4[i]) and not math.isnan(proj[i]) and bo_candidate(pos, proj[i], ppg[i], F_[i]['snap'])
                         for i in range(n)])
        ev = (y4 >= BO_LINE[pos]).astype(float)
        Xall = np.array([[f[k] for k in BO_KEYS] for f in F_])

        def wf(keys, seasons):
            """Walk-forward odds for the candidate rows of `seasons`, inputs `keys`."""
            ix = [BO_KEYS.index(k) for k in keys]
            pr = np.full(n, np.nan)
            for ss in seasons:
                tr, te = cand & (s < ss), cand & (s == ss)
                if not te.any():
                    continue
                X = Xall[:, ix]; mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
                Z = np.c_[np.ones(n), (X - mu) / sd]
                pr[te] = 1 / (1 + np.exp(-(Z[te] @ logit_fit(Z[tr], ev[tr]))))
            return pr

        def ll(pr, m):
            p_ = np.clip(pr[m], 1e-4, 1 - 1e-4)
            return float(-np.mean(ev[m] * np.log(p_) + (1 - ev[m]) * np.log(1 - p_)))
        tune, hold = list(range(TEST0, HOLD0)), list(range(HOLD0, int(s.max()) + 1))
        mt = cand & np.isin(s, tune)
        keys = list(BO_KEYS)
        best = ll(wf(keys, tune), mt)
        while len(keys) > 1:            # drop inputs while that lowers out-of-sample log loss (proj stays)
            trial = [(ll(wf([k for k in keys if k != d], tune), mt), d) for d in keys if d != 'proj']
            if not trial:
                break
            e_, d = min(trial)
            if e_ >= best:
                break
            best = e_; keys.remove(d)
            print('breakout', pos, 'drop', d, round(e_, 4), flush=True)
        res = {'keys': keys}
        for name, ss in (('2016-20', tune), ('2021-25', hold)):
            m = cand & np.isin(s, ss)
            pm, pb = wf(keys, ss), wf(['proj'], ss)
            f, u = m & (pm >= BO_CUT), m & (pm < BO_CUT)
            r = {'n': int(m.sum()), 'base': round(float(ev[m].mean()), 3), 'aucModel': round(auc(pm[m], ev[m]), 3),
                 'aucProj': round(auc(pb[m], ev[m]), 3), 'llModel': round(ll(pm, m), 4), 'llProj': round(ll(pb, m), 4),
                 'flagged': int(f.sum()), 'hitFlag': round(float(ev[f].mean()), 3) if f.any() else None,
                 'hitRest': round(float(ev[u].mean()), 3), 'odds': round(float(pm[f].mean()), 3) if f.any() else None}
            if f.any():
                r['riseFlag'] = round(float(np.nanmean(y4[f] - np.nan_to_num(ppg[f], nan=0.0))), 2)
                r['riseRest'] = round(float(np.nanmean(y4[u] - np.nan_to_num(ppg[u], nan=0.0))), 2)
                r['vsProjFlag'] = round(float(np.mean(y4[f] - proj[f])), 2)
                r['vsProjRest'] = round(float(np.mean(y4[u] - proj[u])), 2)
            res[name] = r
            print('breakout', pos, name, r, flush=True)
        # if he gets the job: among players in a small role (snaps under LOW) whose snaps over the next four games
        # reached a starter's (HIGH), how well each read called the points they then scored
        sy = a['Y']['snapY']; s4 = np.full(n, np.nan)
        for j, i in enumerate(order):
            fut = [k for k in order[j:j + 4] if ids[k] == ids[i] and s[k] == s[i]]
            if len(fut) >= 3:
                s4[i] = sy[fut].mean()
        snap = Xall[:, BO_KEYS.index('snap')]; prom = Xall[:, BO_KEYS.index('prom')]
        pm_ = (~np.isnan(y4)) & (snap > 0.05) & (snap < PROMO[pos][0]) & (s4 >= PROMO[pos][1]) & (s >= TEST0) & (w >= 3)
        # "if he gets the job": points a game then, from the projection and points at a starter's workload, weighted
        # by how well each called it before (least squares on the earlier seasons' promotions, walk-forward)
        pa_ = (~np.isnan(y4)) & ~np.isnan(proj) & (snap > 0.05) & (snap < PROMO[pos][0]) & (s4 >= PROMO[pos][1]) & (w >= 3)
        J = np.c_[np.ones(n), proj, prom]
        job = np.full(n, np.nan)
        for ss in range(TEST0, int(s.max()) + 1):
            tr, te = pa_ & (s < ss), pa_ & (s == ss)
            if tr.sum() > 20 and te.any():
                job[te] = J[te] @ np.linalg.lstsq(J[tr], y4[tr], rcond=None)[0]
        pm_ = pa_ & (s >= TEST0)
        if pm_.sum() > 20:
            cc = lambda x: round(float(np.corrcoef(x[pm_], y4[pm_])[0, 1]), 3)
            res['promoted'] = {'n': int(pm_.sum()), 'rProj': cc(proj), 'rStarter': cc(prom), 'rJob': cc(job),
                               'maeJob': round(float(np.mean(np.abs(job[pm_] - y4[pm_]))), 2),
                               'maeProj': round(float(np.mean(np.abs(proj[pm_] - y4[pm_]))), 2),
                               'mean': round(float(y4[pm_].mean()), 1), 'meanJob': round(float(job[pm_].mean()), 1),
                               'meanProj': round(float(proj[pm_].mean()), 1)}
            print('breakout', pos, 'promoted', res['promoted'], flush=True)
        jc = np.linalg.lstsq(J[pa_], y4[pa_], rcond=None)[0]
        out[pos] = res
        ix = [BO_KEYS.index(k) for k in keys]
        X = Xall[:, ix]; mu, sd = X[cand].mean(0), X[cand].std(0) + 1e-9
        wv = logit_fit(np.c_[np.ones(int(cand.sum())), (X[cand] - mu) / sd], ev[cand])
        model[pos] = {'keys': keys, 'mu': [round(float(x), 5) for x in mu], 'sd': [round(float(x), 5) for x in sd],
                      'w': [round(float(x), 5) for x in wv], 'job': [round(float(x), 4) for x in jc]}
    return out, model


def fit_avail(games, box, status, inj, A):
    """P(a fantasy-relevant player plays his team's game k games ahead), by what's known before the week (see
    av_class). Relevant: 6+ half-PPR points a game so far (last season's before his first game). Seasons 2016-25."""
    played = defaultdict(set)              # (season, gsis) -> weeks he played
    sched = defaultdict(dict)              # (season, team) -> week -> gid
    for g in games:
        s, w = int(g['season']), int(g['week'])
        for t in (team(g['home_team']), team(g['away_team'])):
            sched[(s, t)][w] = g['game_id']
            for gsis in box.get((g['game_id'], t), {}):
                played[(s, gsis)].add(w)
    first = {}                             # (season, gsis) -> first week he's relevant
    for pos in SKILL:
        a = A[pos]
        for s, w, gsis, b in zip(a['s'], a['w'], a['id'], a['b'][:, 0]):
            if s >= TEST0 and b >= 6:
                first[(int(s), gsis)] = min(int(w), first.get((int(s), gsis), 99))
    cnt = defaultdict(lambda: [0, 0])
    for (s, gsis), w0 in first.items():
        for w in range(w0 + 1, 19):
            st = roster_status(status, s, w, gsis)
            if not st or w not in sched[(s, st[1])] and not any(x >= w for x in sched[(s, st[1])]):
                continue
            t = st[1]
            prev = [x for x in sched[(s, t)] if x < w]
            c = av_class(status, inj, s, w, gsis, bool(prev) and max(prev) in played[(s, gsis)])
            k = 0
            for wk in range(w, 19):
                if wk in sched[(s, t)]:
                    x = cnt[(c, k)]; x[1] += 1; x[0] += wk in played[(s, gsis)]
                    k += 1
    out = {}
    for c in AV_CLASSES:
        for suf in ('', '-'):
            row, ns = [], []
            for k in range(AV_K):
                pl, n = cnt[(c + suf, k)]
                row.append(round((pl + 1) / (n + 2), 3) if n >= 20 else (row[-1] if row else 0.5)); ns.append(n)
            out[c + suf] = {'p': row, 'n': ns}
    for c in AV_CLASSES:        # a class seen too rarely to estimate borrows its twin (played last game or not)
        if sum(out[c]['n'][:3]) < 60:
            out[c]['p'] = out[c + '-']['p']
    return out


def ros_backtest(games, box, dst, info, model, snapv, params, A, avail, pa_sd, status, inj, cps, wars=None):
    """Rest-of-season points from weeks 4, 8 and 12 of 2021-25: the model (every remaining game with the game
    model's view as of that week, times availability) against season-to-date points a game times games left."""
    import numpy as np
    coefs = {}
    for pos, a in A.items():
        for s in {c[0] for c in cps}:
            m = (a['s'] >= SNAP0) & (a['s'] < s)
            coefs[(pos, s)] = {c: list(ridge(a['X'][c][m], a['Y'][c][m])) for c in comps_of(pos)}
    act = defaultdict(float)
    sched = defaultdict(list)
    for g in games:
        s, w = int(g['season']), int(g['week'])
        h, a = team(g['home_team']), team(g['away_team'])
        for t, o in ((h, a), (a, h)):
            sched[(s, t)].append(g)
            for gsis, (pos, v) in box.get((g['game_id'], t), {}).items():
                act[(s, gsis, w)] += score(pos, v, 'half')
            act[(s, 'D' + t, w)] += score('DST', dst_line(dst.get((g['game_id'], t), {}), num(g['home_score'] if o == h else g['away_score'])))
    res = defaultdict(lambda: {'m': [], 'b': [], 'ba': [], 'y': []})
    W = Walk(info=info, **params)
    todo = sorted(cps)
    for g in games + [None]:
        while todo and (g is None or todo[0] <= (int(g['season']), int(g['week']))):
            cs, cw = todo.pop(0)
            if cs != W.season:
                W.new_season(cs)
            ros_checkpoint(W, info, coefs, cs, cw, sched, snapv[(cs, cw)], avail, pa_sd, act, res, box, status, inj,
                           (wars or {}).get((cs, cw), {}))
        if g is None:
            break
        if int(g['season']) != W.season:
            W.new_season(int(g['season']))
        W.update(g, box, dst)
    out = {}
    rk = lambda z: np.argsort(np.argsort(-z))
    for pos, d in res.items():
        m, b, ba, y = np.array(d['m']), np.array(d['b']), np.array(d['ba']), np.array(d['y'])
        out[pos] = {'n': int(len(y)), 'maeModel': round(float(np.mean(np.abs(m - y))), 1), 'maeBase': round(float(np.mean(np.abs(b - y))), 1),
                    'maeBaseAvail': round(float(np.mean(np.abs(ba - y))), 1),
                    'rModel': round(float(np.corrcoef(m, y)[0, 1]), 3), 'rBase': round(float(np.corrcoef(b, y)[0, 1]), 3),
                    'rankModel': round(float(np.corrcoef(rk(m), rk(y))[0, 1]), 3), 'rankBase': round(float(np.corrcoef(rk(b), rk(y))[0, 1]), 3)}
        out[pos]['gain'] = round(1 - out[pos]['maeModel'] / out[pos]['maeBaseAvail'], 3)
    print('ros', json.dumps(out), flush=True)
    return out


def ros_checkpoint(W, info, coefs, s, w, sched, imp_model, avail, pa_sd, act, res, box, status, inj, wars):
    """One checkpoint: the top players at each position by points a game so far, projected rest of season vs actual."""
    cand = defaultdict(list)
    for gsis, st in W.p.items():
        q = W.sea.get(gsis, {}).get(s)
        if st['pos'] in SKILL + ('K',) and q and q[1]:
            cand[st['pos']].append((q[0] / q[1], gsis, st))
    for (ss, t) in sched:
        q = W.sea.get('D' + t, {}).get(s)
        if ss == s and q and q[1]:
            cand['DST'].append((q[0] / q[1], 'D' + t, None))

    def imp_of(g, home):
        h, a = imp_model.get(g['game_id'], (22.0, 22.0))
        return (h, a) if home else (a, h)
    ridx = roster_index(status)
    vacs = {}
    for pos, lst in cand.items():
        lst.sort(key=lambda z: -z[0])
        for b, gsis, st in lst[:POOL[pos]]:
            if pos == 'DST':
                t = gsis[1:]
            else:
                rs = roster_status(status, s, w, gsis)
                t = rs[1] if rs else st['t']
            left = [g for g in sched[(s, t)] if int(g['week']) >= w]
            y = sum(act.get((s, gsis, wk), 0.0) for wk in range(w, 19))
            m = 0.0
            if pos in SKILL and t not in vacs:
                vacs[t] = vac_path(W, t, members(W, ridx, status, inj, s, w, t), avail, len(left))
            cls = ex = None
            if pos != 'DST':
                prev = [g for g in sched[(s, t)] if int(g['week']) < w]
                cls = av_class(status, inj, s, w, gsis, bool(prev) and gsis in box.get((prev[-1]['game_id'], t), {}))
                ex = extras(W, info, wars, gsis, t, s, cls)
            pr = project(W, info, coefs[(pos, s)], pos, gsis, t, s, left, imp_of, pa_sd, vacs.get(t) if pos in SKILL else None, ex)
            if pos == 'DST':
                m = sum(score('DST', v) for _, v in pr)
            else:
                m = sum(score(pos, v, 'half') * p_play(avail, cls, k) for k, (_, v) in enumerate(pr))
            # the baselines: points a game so far times games left, and times the games a healthy starter plays
            healthy = len(left) if pos == 'DST' else sum(p_play(avail, 'ok', k) for k in range(len(left)))
            res[pos]['m'].append(m); res[pos]['b'].append(b * len(left)); res[pos]['ba'].append(b * healthy); res[pos]['y'].append(y)


# ---------------------------------------------------------------- board
def build():
    import datetime
    F = json.load(open(FIT))
    games_all = list(G.rows(G.get('games.csv', G.GAMES, fresh=True)))
    reg = [g for g in games_all if g['game_type'] == 'REG']
    done = [g for g in reg if g['home_score'] not in ('', 'NA')]
    last = max(int(g['season']) for g in done)
    left = [g for g in reg if int(g['season']) == last and g['home_score'] in ('', 'NA')]
    if not left:
        return print('nfl fantasy: regular season over')
    week = min(int(g['week']) for g in left)
    games, box, dst, status, inj, info = load(last - 4, last, fresh=True)
    live_statuses(inj, status, last, week)
    model, snapv = implied(last, fresh=False, snaps_at=[(last, week)])
    imp_model = snapv[(last, week)]
    wars = war_now(last, week)
    W = Walk(info=info, **F['params'])
    for g in games:
        if int(g['season']) != W.season:
            W.new_season(int(g['season']))
        W.update(g, box, dst)
    if W.season != last:
        W.new_season(last)
    coef, avail, pa_sd = F['coef'], F['avail'], F['paSd']
    bom = (F.get('breakout') or {}).get('model', {})
    sched = defaultdict(list)
    for g in games:
        if int(g['season']) == last:
            for t in (team(g['home_team']), team(g['away_team'])):
                sched[t].append(g)

    def imp_of(g, home):
        h, a = game_imp(g, imp_model, market=int(g['week']) == week)
        return (h, a) if home else (a, h)
    # who: everyone on a roster now (active, inactive or on a reserve list) at QB, RB, WR, TE or K
    latest = {}
    for (s, w, gsis), st in status.items():
        if s == last and w < week and (gsis not in latest or latest[gsis][0] < w):
            latest[gsis] = (w, st)
    players = []
    ridx = roster_index(status)
    vacs = {t: vac_path(W, t, members(W, ridx, status, inj, last, week, t), avail,
                        len([g for g in sched[t] if g['home_score'] in ('', 'NA')])) for t in sched}
    vmed = {k: sorted(v[0][k] for v in vacs.values())[len(vacs) // 2] for k in ('pa', 'ca', 'tg')} if vacs else {}

    def r2(v):
        return {k: round(x, 2) for k, x in v.items() if abs(x) >= 0.005}
    for gsis, (w0, (stat, t, rpos)) in latest.items():
        pos = 'RB' if rpos == 'FB' else rpos
        if pos not in SKILL + ('K',) or stat not in ('ACT', 'INA', 'RES', 'PUP', 'NFI', 'SUS'):
            continue
        st = W.p.get(gsis)
        if st is None and stat != 'ACT':
            continue
        tg = [g for g in sched[t] if g['home_score'] in ('', 'NA')]
        prev = [g for g in sched[t] if g['home_score'] not in ('', 'NA')]
        pl = bool(prev) and gsis in box.get((prev[-1]['game_id'], t), {})
        cls = av_class(status, inj, last, week, gsis, pl)
        if pos in SKILL and t not in vacs:
            vacs[t] = vac_path(W, t, members(W, ridx, status, inj, last, week, t), avail, len(tg))
        ex = extras(W, info, wars, gsis, t, last, cls) if pos in SKILL else None
        pr = project(W, info, coef[pos], pos, gsis, t, last, tg, imp_of, pa_sd, vacs.get(t) if pos in SKILL else None, ex)
        wk = [(g, v) for g, v in pr if int(g['week']) == week]
        ros, eg = defaultdict(float), 0.0
        for k, (g, v) in enumerate(pr):
            p = p_play(avail, cls, k); eg += p
            for c, x in v.items():
                ros[c] += p * x
        q = W.sea.get(gsis, {}).get(last)
        rep = inj.get((last, week, gsis))
        tag = '' if cls.startswith('rq') and rep != 'Questionable' else STATUS_TAG.get(cls.rstrip('-'), '')
        rec = {'id': gsis, 'n': (info.get(gsis) or {}).get('n') or gsis, 'pos': pos, 't': t, 'st': tag,
               'av': round(p_play(avail, cls, 0), 2) if wk else 0, 'r': r2(ros), 'rg': len(tg), 'eg': round(eg, 1),
               'g': q[1] if q else 0, 'ppg': [round(q[2] / q[1], 1), round(q[0] / q[1], 1), round(q[3] / q[1], 1)] if q and q[1] else None}
        if rep == 'Practice':
            rep = 'back on the report from a reserve list, no game status' if cls.startswith('rq') else None
        if rep:
            rec['inj'] = rep
        if stat != 'ACT' and stat != 'INA':
            rec['list'] = stat
        if wk:
            g, v = wk[0]
            home = team(g['home_team']) == t
            rec.update({'opp': team(g['away_team']) if home else team(g['home_team']), 'home': home, 'kick': G.kick(g),
                        'w': r2(v), 'imp': round(imp_of(g, home)[0], 1)})
        if pos in SKILL and pr and bom.get(pos):
            bo = breakout(W, info, bom[pos], gsis, pos, t, last, pr[0][1], vacs[t][0], vmed)
            if bo:
                rec['bo'] = bo
        if (info.get(gsis) or {}).get('img'):
            rec['img'] = info[gsis]['img']
        players.append(rec)
    # defenses: every team
    for t in sorted(sched):
        tg = [g for g in sched[t] if g['home_score'] in ('', 'NA')]
        pr = project(W, info, coef['DST'], 'DST', 'D' + t, t, last, tg, imp_of, pa_sd)
        ros = defaultdict(float)
        for g, v in pr:
            for c, x in v.items():
                ros[c] += x
        q = W.sea.get('D' + t, {}).get(last)
        rec = {'id': 'D' + t, 'n': t + ' D/ST', 'pos': 'DST', 't': t, 'st': '', 'av': 1 if any(int(g['week']) == week for g in tg) else 0,
               'r': r2(ros), 'rg': len(tg), 'eg': float(len(tg)), 'g': q[1] if q else 0,
               'ppg': [round(q[0] / q[1], 1)] * 3 if q and q[1] else None}
        wk = [(g, v) for g, v in pr if int(g['week']) == week]
        if wk:
            g, v = wk[0]
            home = team(g['home_team']) == t
            rec.update({'opp': team(g['away_team']) if home else team(g['home_team']), 'home': home, 'kick': G.kick(g),
                        'w': r2(v), 'imp': round(imp_of(g, home)[1], 1)})
        players.append(rec)
    # keep who matters: anyone projected for a point this week or ten the rest of the way, or with a game played
    def half(rec, key):
        v = rec.get(key) or {}
        return score(rec['pos'], v, 'half') * (rec['av'] if key == 'w' else 1)
    players = [p for p in players if half(p, 'w') >= 1 or half(p, 'r') >= 10 or p['g']]
    players.sort(key=lambda p: -half(p, 'r'))
    asof = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    T = F['test']['2021-25 (held out)']
    meta = {'season': last, 'week': week, 'asof': asof, 'n': len(players),
            'test': {f: {pos: {k: v for k, v in r.items() if k in ('n', 'maeModel', 'maeBase', 'maeLast3', 'rModel', 'rBase', 'gain', 'mean')}
                         for pos, r in T[f].items()} for f in T},
            'ros': F['ros'], 'ablation': F['ablation'], 'paSd': pa_sd, 'params': F['params'],
            'breakout': {k: v for k, v in (F.get('breakout') or {}).items() if k != 'model'}, 'stability': F.get('stability'),
            'avail': {c: avail[c]['p'][0] for c in avail}}
    body = {'season': last, 'week': week, 'asof': asof, 'paSd': pa_sd, 'scoring': SCORING, 'paTiers': PA_TIERS, 'boCut': BO_CUT,
            'players': players}
    try:
        old = json.load(open(PLAYERS))
        if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in body.items() if k != 'asof'})):
            return print('nfl fantasy: no change')
    except (OSError, ValueError):
        pass
    os.makedirs(os.path.dirname(PLAYERS), exist_ok=True)
    with open(PLAYERS, 'w') as f:
        json.dump(body, f, separators=(',', ':'))
    with open(OUT, 'w') as f:
        json.dump(meta, f, indent=1)
    print(f'nfl fantasy: {last} week {week}, {len(players)} players')


STATUS_TAG = {'ok': '', 'q': 'Q', 'd': 'D', 'out': 'O', 'res': 'IR', 'rq': 'Q'}


if __name__ == '__main__':
    fit() if '--fit' in sys.argv else build()
