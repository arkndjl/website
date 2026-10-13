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
Weekly and rest-of-season points are the stat lines times P(he plays), from an availability table fit on
2016-25 by status (healthy, questionable, doubtful, out, reserve or not on a roster), whether he played his
team's last game, and how many weeks ahead the game is. Rest of season sums every remaining game on his team's
schedule (byes drop out), each with its own game-model environment.

The backtest refits each season on the seasons before it (2013 on, the snap-count era) and scores that season
(2016-25) against the season-to-date points a game (last season's in week 1), on each week's fantasy-relevant
pool (the top 32 QBs, 64 RBs, 96 WRs, 32 TEs, 32 Ks and DSTs by that baseline) in the games they played.
Ratings memory is tuned on 2016-20 RMSE (a projection is a mean, and squared error is what a mean minimizes);
2021-25 is held out for the report. Each input group is scored by leaving it out and refitting.
Rest of season is tested from weeks 4, 8 and 12 of 2021-25 against points a game so far times the games a
healthy starter plays.
"""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as G  # noqa: E402

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
                if r.get('gsis_id') and r.get('game_type', 'REG') == 'REG' and r['report_status']:
                    inj[(y, int(r['week']), r['gsis_id'])] = r['report_status']
    return games, box, dst, status, inj, info


# ---------------------------------------------------------------- the walk
class Walk:
    """Walks REG games in order, keeping every player's and team's weighted rates: read them before a game,
    update() after it."""
    def __init__(self, hl=5.0, carry=0.5, k0=2.0, thl=8.0, info=None):
        self.a, self.carry, self.k0 = 0.5 ** (1 / hl), carry, k0
        self.ta = 0.5 ** (1 / thl)
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

    def new_season(self, s):
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
        return st

    def rates(self, st):
        """Weighted per-game rates, shrunk toward zero by k0 games, and the share of weight that's his own."""
        W = st['W'] if st else 0.0
        den = W + self.k0
        S = st['S'] if st else {}
        return {k: S.get(k, 0.0) / den for k in COMPS + USAGE + KKEYS}, W / den

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
            for gsis, (pos, v) in box.get((g['game_id'], t), {}).items():
                st = self.state(gsis, s)
                if st is None:
                    st = self.p[gsis] = {'S': defaultdict(float), 'W': 0.0, 's': s, 'pos': pos, 't': t}
                for k in st['S']:
                    st['S'][k] *= self.a
                st['W'] = st['W'] * self.a + 1
                if pos == 'K':
                    for k in KKEYS:
                        st['S'][k] += v.get(k, 0.0)
                    kp = kpts(v)
                    self.credit(gsis, s, kp, kp, kp)
                else:
                    fp = pts(v, 'half')
                    for k in COMPS + USAGE:
                        st['S'][k] += fp if k == 'fp' else v.get(k, 0.0)
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


def skill_x(e, wf, d, pos, c, r, o):
    return [1.0, wf, d * (1 - wf)] + [e[k] for k in USE[pos]] + [(r - 1) * e[c], r - 1, (o - 1) * e[c]]


def skill_names(pos):
    return ['one', 'wf', '_draft'] + USE[pos] + ['_env', '_env0', '_opp']


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


def project(W, info, coef, pos, gsis, t, s, games, imp_of, pa_sd):
    """The stat line in each of `games` (if he plays), from rates as of now: [(game, {stat: value})]."""
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
    for g in games:
        home = team(g['home_team']) == t
        o = team(g['away_team']) if home else team(g['home_team'])
        ti, oi = imp_of(g, home)
        r = env(W, t, ti)
        if pos == 'K':
            x = k_x(e, wf, r, ti, 1.0 if g['roof'] in ('dome', 'closed') else 0.0)
            v = {c: max(0.0, dot(x, coef[c])) for c in KCOMP}
        else:
            o_f = W.opp_factor(o, pos)
            v = {c: max(0.0, dot(skill_x(e, wf, d, pos, c, r, o_f), coef[c])) for c in PROJ[pos]}
        out.append((g, v))
    return out


# ---------------------------------------------------------------- availability
AV_K = 18
AV_CLASSES = ('ok', 'q', 'd', 'out', 'res')


def roster_status(status, s, w, gsis):
    """The latest roster entry before week w (up to three weeks back; week 1's own in week 1)."""
    for ww in ((1,) if w <= 1 else range(w - 1, max(0, w - 4), -1)):
        st = status.get((s, ww, gsis))
        if st:
            return st
    return None


def av_class(status, inj, s, w, gsis, played_last):
    """What a manager knows before week w: the injury report for week w, the roster status the week before, and
    whether he played his team's last game ('-' when he didn't)."""
    rep = inj.get((s, w, gsis), '')
    st = roster_status(status, s, w, gsis)
    if rep == 'Out':
        c = 'out'
    elif rep == 'Doubtful':
        c = 'd'
    elif st is None or st[0] not in ('ACT', 'INA'):
        c = 'res'
    elif rep == 'Questionable':
        c = 'q'
    else:
        c = 'ok'
    return c + ('' if played_last else '-')


def p_play(avail, cls, k):
    return avail[cls]['p'][min(k, AV_K - 1)]


# ---------------------------------------------------------------- fit
def collect(games, box, dst, info, model, params):
    """Walk every game; one row per player-game played (2013 on): features before kickoff, the stat line after.
    Returns per position: season, week, id, X[stat], Y[stat], baselines (season-to-date points a game, three formats),
    last-3 average, and (defenses) the opponent's implied points."""
    W = Walk(info=info, **params)
    R = defaultdict(lambda: {'s': [], 'w': [], 'id': [], 'X': defaultdict(list), 'Y': defaultdict(list), 'b': [], 'l3': [], 'oi': []})

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
                for gsis, (pos, v) in box.get((g['game_id'], t), {}).items():
                    e, wf = W.rates(W.state(gsis, s))
                    if pos == 'K':
                        add('K', s, w, gsis, {c: k_x(e, wf, r, imp, dome) for c in KCOMP}, {c: v.get(c, 0.0) for c in KCOMP})
                        continue
                    o_f = W.opp_factor(o, pos); d = dv(info, gsis)
                    add(pos, s, w, gsis, {c: skill_x(e, wf, d, pos, c, r, o_f) for c in PROJ[pos]}, {c: v.get(c, 0.0) for c in COMPS})
                add('DST', s, w, 'D' + t, {k: d_x(W, t, o, k, oimp) for k in DCOMP}, dst_line(dst.get((g['game_id'], t), {}), sc[o]), oimp)
        W.update(g, box, dst)
    return R, W


def arrays(R):
    import numpy as np
    A = {}
    for pos, r in R.items():
        A[pos] = {'s': np.array(r['s']), 'w': np.array(r['w']), 'id': r['id'], 'oi': np.array(r['oi']),
                  'X': {c: np.array(x) for c, x in r['X'].items()}, 'Y': {c: np.array(y) for c, y in r['Y'].items()},
                  'b': np.array(r['b']), 'l3': np.array(r['l3'])}
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
    # tune the rating memory on 2016-20 out-of-sample RMSE (half PPR, skill positions); 2021-25 stays held out
    grid = []
    tune = list(range(TEST0, HOLD0))
    for hl in (3, 5, 8):
        for carry in (0.35, 0.6):
            for k0 in (1.0, 2.5):
                p = {'hl': hl, 'carry': carry, 'k0': k0}
                R, _ = collect(games, box, dst, info, model, p)
                A = arrays({k: v for k, v in R.items() if k in SKILL})
                err = pooled(evaluate(A, walk_forward(A, tune), tune))
                grid.append((err, p)); print('grid', p, round(err, 4), flush=True)
    grid.sort(key=lambda z: z[0])
    best = grid[0][1]
    R, W = collect(games, box, dst, info, model, best)
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
              'opponent vs position': ['_opp'], 'draft slot': ['_draft'],
              'production history': ['py', 'ptd', 'pint', 'ry', 'rtd', 'rc', 'wy', 'wtd', 'fl', 'tp', 'std', 'fp']}
    SA = {k: A[k] for k in SKILL}
    abl = {}
    for period, ss in (('2016-20', tune), ('2021-25', hold)):
        base_err = pooled(evaluate(SA, P, ss))
        for gname, keys in groups.items():
            cols = {pos: [i for i, nme in enumerate(skill_names(pos)) if nme not in keys] for pos in SKILL}
            err = pooled(evaluate(SA, walk_forward(SA, ss, cols), ss))
            abl.setdefault(gname, {})[period] = round(err - base_err, 4)
            print('without', gname, period, abl[gname][period], flush=True)
    avail = fit_avail(games, box, status, inj, A)
    ros = ros_backtest(games, box, dst, info, model, snapv, best, A, avail, pa_sd, status, inj, cps)
    # published coefficients: every season 2013-25
    coef = {}
    for pos, a in A.items():
        m = a['s'] >= SNAP0
        coef[pos] = {c: [round(float(v), 6) for v in ridge(a['X'][c][m], a['Y'][c][m])] for c in comps_of(pos)}
    out = {'params': best, 'paSd': round(pa_sd, 2), 'test': test, 'ablation': abl, 'ros': ros, 'pool': POOL,
           'avail': avail, 'coef': coef, 'grid': [[round(e, 4), p] for e, p in grid],
           'features': {pos: skill_names(pos) for pos in SKILL}}
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k in ('params', 'paSd', 'ablation', 'ros')}, indent=1))
    print(json.dumps(test['2021-25 (held out)']['half'], indent=1))


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


def ros_backtest(games, box, dst, info, model, snapv, params, A, avail, pa_sd, status, inj, cps):
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
            ros_checkpoint(W, info, coefs, cs, cw, sched, snapv[(cs, cw)], avail, pa_sd, act, res, box, status, inj)
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


def ros_checkpoint(W, info, coefs, s, w, sched, imp_model, avail, pa_sd, act, res, box, status, inj):
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
            pr = project(W, info, coefs[(pos, s)], pos, gsis, t, s, left, imp_of, pa_sd)
            if pos == 'DST':
                m = sum(score('DST', v) for _, v in pr)
            else:
                prev = [g for g in sched[(s, t)] if int(g['week']) < w]
                cls = av_class(status, inj, s, w, gsis, bool(prev) and gsis in box.get((prev[-1]['game_id'], t), {}))
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
    model, snapv = implied(last, fresh=False, snaps_at=[(last, week)])
    imp_model = snapv[(last, week)]
    W = Walk(info=info, **F['params'])
    for g in games:
        if int(g['season']) != W.season:
            W.new_season(int(g['season']))
        W.update(g, box, dst)
    if W.season != last:
        W.new_season(last)
    coef, avail, pa_sd = F['coef'], F['avail'], F['paSd']
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
        pr = project(W, info, coef[pos], pos, gsis, t, last, tg, imp_of, pa_sd)
        wk = [(g, v) for g, v in pr if int(g['week']) == week]
        ros, eg = defaultdict(float), 0.0
        for k, (g, v) in enumerate(pr):
            p = p_play(avail, cls, k); eg += p
            for c, x in v.items():
                ros[c] += p * x
        q = W.sea.get(gsis, {}).get(last)
        rec = {'id': gsis, 'n': (info.get(gsis) or {}).get('n') or gsis, 'pos': pos, 't': t, 'st': STATUS_TAG.get(cls.rstrip('-'), ''),
               'av': round(p_play(avail, cls, 0), 2) if wk else 0, 'r': r2(ros), 'rg': len(tg), 'eg': round(eg, 1),
               'g': q[1] if q else 0, 'ppg': [round(q[2] / q[1], 1), round(q[0] / q[1], 1), round(q[3] / q[1], 1)] if q and q[1] else None}
        rep = inj.get((last, week, gsis))
        if rep:
            rec['inj'] = rep
        if stat != 'ACT' and stat != 'INA':
            rec['list'] = stat
        if wk:
            g, v = wk[0]
            home = team(g['home_team']) == t
            rec.update({'opp': team(g['away_team']) if home else team(g['home_team']), 'home': home, 'kick': G.kick(g),
                        'w': r2(v), 'imp': round(imp_of(g, home)[0], 1)})
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
            'avail': {c: avail[c]['p'][0] for c in avail}}
    body = {'season': last, 'week': week, 'asof': asof, 'paSd': pa_sd, 'scoring': SCORING, 'paTiers': PA_TIERS, 'players': players}
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


STATUS_TAG = {'ok': '', 'q': 'Q', 'd': 'D', 'out': 'O', 'res': 'IR'}


if __name__ == '__main__':
    fit() if '--fit' in sys.argv else build()
