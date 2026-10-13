#!/usr/bin/env python3
"""NFL player projections in PPR for the NFL ARKBOARD's projections tab (data/nfl_proj.json).

    python3 scripts/nfl_proj.py          # the coming week (stdlib only; run by the cfb board job after nfl_games.py)
    python3 scripts/nfl_proj.py --fit    # season-swap backtest on 2024 and 2025, writes data/nfl_proj_fit.json

Data: nflverse stats_player_week (QB, RB, WR, TE lines by game), nfldata games.csv (scores, closing spread and
total, the schedule) and nflverse injuries (the week's Out and Doubtful).

A player's projected stat line is three things multiplied together:
    rate    his per-game line in each stat (pass yards and TDs, INTs, rush and receiving yards and TDs, catches,
            fumbles lost, 2-point tries), exponentially weighted by games (half-life h), last season's games
            carried at a fraction c, and shrunk toward his position's average game by k games
    opp     the defense's PPR allowed a game to his position against the league's (same weighting, shrunk by 4
            games), to the power b
    env     his team's implied points (from the market spread and total) over its weighted points a game, to the
            power g
PPR from the line: pass yd .04, pass TD 4, INT -2, rush/rec yd .1, rush/rec TD 6, catch 1, fumble lost -2, 2-pt 2.
h, c, k, b and g are picked on one season and scored on the other (2024 and 2025, each with the season before as
history), against the actual PPR of every QB, RB, WR and TE who played in his team's previous game and this one.
"""
import csv
import datetime
import itertools
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nfl_games import get, rows, num, team, GAMES, REL, kick, ROOT  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'nfl_proj.json')
FIT = os.path.join(ROOT, 'data', 'nfl_proj_fit.json')
POS = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE'}
COMPS = ['pyd', 'ptd', 'int', 'ryd', 'rtd', 'rec', 'yyd', 'ytd', 'fl', 'two']
PTS = {'pyd': .04, 'ptd': 4, 'int': -2, 'ryd': .1, 'rtd': 6, 'rec': 1, 'yyd': .1, 'ytd': 6, 'fl': -2, 'two': 2}
GRID = {'h': [3, 5, 8, 12], 'c': [0.3, 0.6, 1.0], 'k': [0, 1, 2, 4], 'b': [0, 0.25, 0.5, 0.75, 1.0], 'g': [0, 0.5, 1.0], 't': [1.0, 0.7, 0.4, 0.0]}
OPP_K, TEAM_K = 4, 2


def ppr(x):
    return sum(PTS[f] * x[f] for f in COMPS)


def line_of(r):
    n = lambda *k: sum(num(r.get(f)) for f in k)
    return {'pyd': n('passing_yards'), 'ptd': n('passing_tds'), 'int': n('passing_interceptions'), 'ryd': n('rushing_yards'),
            'rtd': n('rushing_tds'), 'rec': n('receptions'), 'yyd': n('receiving_yards'), 'ytd': n('receiving_tds'),
            'fl': n('rushing_fumbles_lost', 'receiving_fumbles_lost', 'sack_fumbles_lost'),
            'two': n('passing_2pt_conversions', 'rushing_2pt_conversions', 'receiving_2pt_conversions')}


def load(first, last, fresh_last=False):
    """Games (schedule order) and player lines for seasons first..last."""
    games = [g for g in rows(get('games.csv', GAMES, fresh_last)) if first <= int(g['season']) <= last]
    games.sort(key=lambda g: (int(g['season']), int(g['week']), g['gameday'], g['gametime'], g['game_id']))
    lines = []
    for y in range(first, last + 1):
        for r in rows(get(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv', fresh_last and y == last)):
            pos = POS.get(r['position'])
            if not pos or r['season_type'] not in ('REG', 'POST'):
                continue
            lines.append({'id': r['player_id'], 'name': r['player_display_name'], 'pos': pos, 'season': int(r['season']), 'week': int(r['week']),
                          'team': team(r['team']), 'opp': team(r['opponent_team']), 'x': line_of(r), 'ppr': num(r['fantasy_points_ppr']),
                          'photo': r.get('headshot_url') or None})
    return games, lines


def implied(g):
    """Implied points (home, away) from the closing spread (home favored when > 0) and total, or None."""
    s, t = g.get('spread_line'), g.get('total_line')
    if s in ('', 'NA', None) or t in ('', 'NA', None):
        return None
    s, t = float(s), float(t)
    return (t + s) / 2, (t - s) / 2


class State:
    """Exponentially weighted per-game sums in schedule order: players' lines, defenses' PPR allowed by position,
    teams' points. Each new season multiplies the history by c."""

    def __init__(self, h, c):
        self.d, self.c, self.season = 0.5 ** (1 / h), c, None
        self.p = defaultdict(lambda: [0.0, {f: 0.0 for f in COMPS}])        # player: [weight, sums]
        self.dfn = defaultdict(lambda: [0.0, defaultdict(float)])           # defense: [weight, PPR allowed by pos]
        self.tm = defaultdict(lambda: [0.0, 0.0])                           # team: [weight, points]
        self.lg = [0.0, defaultdict(float), 0.0]                            # league: games, PPR by pos, points

    def new_season(self, s):
        if self.season is not None and s != self.season:
            for st in self.p.values():
                st[0] *= self.c
                for f in COMPS:
                    st[1][f] *= self.c
            for st in self.dfn.values():
                st[0] *= self.c
                for k in st[1]:
                    st[1][k] *= self.c
            for st in self.tm.values():
                st[0] *= self.c; st[1] *= self.c
        self.season = s

    def rate(self, pid, prior, k):
        w, s = self.p[pid]
        return {f: (s[f] + k * prior[f]) / (w + k) for f in COMPS} if w + k > 0 else None

    def opp(self, d, pos):
        w, s = self.dfn[d]
        L = self.lg[1][pos] / self.lg[0] if self.lg[0] else 0
        return ((s[pos] + OPP_K * L) / (w + OPP_K)) / L if L else 1.0

    def team_pts(self, t):
        w, s = self.tm[t]
        L = self.lg[2] / self.lg[0] if self.lg[0] else 22
        return (s + TEAM_K * L) / (w + TEAM_K)

    def add_game(self, g, glines):
        """One game: its two teams' player lines, the PPR each defense allowed, the points."""
        h, a = team(g['home_team']), team(g['away_team'])
        for t in (h, a):
            st = self.tm[t]; st[0] = st[0] * self.d + 1; st[1] *= self.d
            for k in self.dfn[t][1]:
                self.dfn[t][1][k] *= self.d
            self.dfn[t][0] = self.dfn[t][0] * self.d + 1
        self.tm[h][1] += num(g['home_score']); self.tm[a][1] += num(g['away_score'])
        self.lg[0] += 2; self.lg[2] += num(g['home_score']) + num(g['away_score'])
        for r in glines:
            st = self.p[r['id']]; st[0] = st[0] * self.d + 1
            for f in COMPS:
                st[1][f] = st[1][f] * self.d + r['x'][f]
            if r['opp'] in (h, a):
                self.dfn[r['opp']][1][r['pos']] += r['ppr']
            self.lg[1][r['pos']] += r['ppr']


def priors(lines, season):
    """The average game by position (every QB, RB, WR and TE line that season)."""
    s, n = defaultdict(lambda: {f: 0.0 for f in COMPS}), defaultdict(int)
    for r in lines:
        if r['season'] == season:
            n[r['pos']] += 1
            for f in COMPS:
                s[r['pos']][f] += r['x'][f]
    return {p: {f: s[p][f] / n[p] for f in COMPS} for p in n}


def td_rates(lines, season):
    """TDs a yard by position and kind (pass, rush, receiving) that season."""
    s = defaultdict(lambda: defaultdict(float))
    for r in lines:
        if r['season'] == season:
            for f in COMPS:
                s[r['pos']][f] += r['x'][f]
    return {p: {'ptd': x['ptd'] / x['pyd'] if x['pyd'] else 0, 'rtd': x['rtd'] / x['ryd'] if x['ryd'] else 0,
                'ytd': x['ytd'] / x['yyd'] if x['yyd'] else 0} for p, x in s.items()}


def blend(x, tpy, t):
    """TDs regressed toward the yards: t of his own TD rate, 1 - t of his yards at the position's TDs a yard."""
    y = dict(x)
    for f, yd in (('ptd', 'pyd'), ('rtd', 'ryd'), ('ytd', 'yyd')):
        y[f] = t * x[f] + (1 - t) * x[yd] * tpy[f]
    return y


def project(rate, opp, env, b, g):
    m = (opp ** b) * (env ** g)
    q = {f: rate[f] * m for f in COMPS}
    q['int'] = rate['int'] / (opp ** b) ** 0.5 if opp > 0 else rate['int']   # a good pass defense picks off more
    return q


def by_game(lines):
    out = defaultdict(list)
    for r in lines:
        out[(r['season'], r['week'], r['team'])].append(r)
    return out


def backtest():
    games, lines = load(2023, 2025)
    pri = priors(lines, 2023)
    pri_a = {p: ppr(x) + 2 * x['int'] for p, x in pri.items()}   # PPR of the average game, INTs aside
    tpy = td_rates(lines, 2023)
    bg = by_game(lines)
    played = defaultdict(set)     # (season, week, team) -> player ids
    for (s, w, t), rs in bg.items():
        played[(s, w, t)] = {r['id'] for r in rs}
    # eval rows per (h, c): the inputs before each game, for players who played their team's previous game and this one
    res = {}
    for h in GRID['h']:
        for c in GRID['c']:
            st, ev, prev = State(h, c), [], {}
            for g in games:
                s, w = int(g['season']), int(g['week'])
                if g['home_score'] in ('', 'NA'):
                    continue
                st.new_season(s)
                imp = implied(g)
                gl = []
                for t, o, ip in ((team(g['home_team']), team(g['away_team']), imp and imp[0]), (team(g['away_team']), team(g['home_team']), imp and imp[1])):
                    rs = bg.get((s, w, t), [])
                    gl += rs
                    if s < 2024:
                        continue
                    last = prev.get(t)
                    for r in rs:
                        if not last or r['id'] not in played[last]:
                            continue
                        w0, s0 = st.p[r['id']]
                        if w0 <= 0:
                            continue
                        ev.append((s, r['pos'], w0, {t: ppr(blend(s0, tpy[r['pos']], t)) + 2 * s0['int'] for t in GRID['t']}, s0['int'], st.opp(o, r['pos']), (ip / st.team_pts(t)) if ip else 1.0, r['ppr']))
                for t in (team(g['home_team']), team(g['away_team'])):
                    prev[t] = (s, w, t)
                st.add_game(g, gl)
            res[(h, c)] = ev
    # score every k, b, g, t on each season
    score = {}
    for (h, c), ev in res.items():
        for k, b, gg, tt in itertools.product(GRID['k'], GRID['b'], GRID['g'], GRID['t']):
            err = defaultdict(float); n = defaultdict(int)
            for s, pos, w0, a0, i0, op, en, y in ev:   # project() in closed form: PPR is linear in the line
                ob = op ** b if op > 0 else 1.0
                pred = ob * en ** gg * (a0[tt] + k * pri_a[pos]) / (w0 + k) - 2 * (i0 + k * pri[pos]['int']) / (w0 + k) / ob ** 0.5
                err[s] += abs(pred - y); n[s] += 1
            score[(h, c, k, b, gg, tt)] = {s: err[s] / n[s] for s in n}
    keys = list(score)
    best = {s: min(keys, key=lambda x: score[x][s]) for s in (2024, 2025)}
    swap = {s: score[best[2025 if s == 2024 else 2024]][s] for s in (2024, 2025)}   # picked on the other season
    pooled = min(keys, key=lambda x: score[x][2024] + score[x][2025])
    # naive: his weighted average with nothing else (the best h, c, k with b = g = 0, picked the same way)
    nkeys = [x for x in keys if x[3] == 0 and x[4] == 0 and x[5] == 1.0]
    nbest = {s: min(nkeys, key=lambda x: score[x][s]) for s in (2024, 2025)}
    nswap = {s: score[nbest[2025 if s == 2024 else 2024]][s] for s in (2024, 2025)}
    # each matchup input kept only if it lowers the swapped error in both seasons against the same rate with it at 0
    h, c, k, b, gg, tt = pooled
    def sw(bb, g2):
        return {s: score[(h, c, k, bb, g2, tt)][s] for s in (2024, 2025)}
    keep_b = all(sw(b, 0)[s] < sw(0, 0)[s] for s in (2024, 2025)) if b else False
    keep_g = all(sw(0, gg)[s] < sw(0, 0)[s] for s in (2024, 2025)) if gg else False
    params = {'h': h, 'c': c, 'k': k, 'b': b if keep_b else 0, 'g': gg if keep_g else 0, 't': tt}
    n = defaultdict(int)
    for s, *_ in res[(h, c)]:
        n[s] += 1
    rep = {'params': params, 'picked': {str(s): dict(zip('hckbgt', best[s])) for s in best},
           'mae': {str(s): round(swap[s], 2) for s in swap}, 'naive': {str(s): round(nswap[s], 2) for s in nswap},
           'n': {str(s): n[s] for s in n}, 'kept': {'opp': keep_b, 'env': keep_g},
           'pooled': {str(s): round(score[pooled][s], 2) for s in (2024, 2025)}}
    json.dump(rep, open(FIT, 'w'), indent=1)
    print(json.dumps(rep))


def build():
    F = json.load(open(FIT))
    P = F['params']
    gall = list(rows(get('games.csv', GAMES, True)))
    last = max(int(g['season']) for g in gall if g['home_score'] not in ('', 'NA'))
    games, lines = load(last - 1, last, fresh_last=True)
    pri = priors(lines, last - 1)
    bg = by_game(lines)
    upcoming = [g for g in games if int(g['season']) == last and g['home_score'] in ('', 'NA')]
    if not upcoming:
        return print('nfl proj: no games left this season')
    week = min(int(g['week']) for g in upcoming)
    st, prev = State(P['h'], P['c']), {}
    for g in games:
        if g['home_score'] in ('', 'NA'):
            continue
        s, w = int(g['season']), int(g['week'])
        st.new_season(s)
        st.add_game(g, bg.get((s, w, team(g['home_team'])), []) + bg.get((s, w, team(g['away_team'])), []))
        for t in (team(g['home_team']), team(g['away_team'])):
            prev[t] = (s, w, t)
    st.new_season(last)
    # who plays: on his team's last game sheet this season, not Out or Doubtful on the week's injury report
    inj = {}
    try:
        for r in rows(get(f'injuries_{last}.csv', f'{REL}/injuries/injuries_{last}.csv', True)):
            if int(r['week']) == week and r['report_status'] in ('Out', 'Doubtful'):
                inj[r['gsis_id']] = r['report_status']
    except Exception as e:  # the report is a nice-to-have; the projections stand without it
        print(f'nfl proj: no injury report ({e})')
    season_ppr = defaultdict(lambda: [0.0, 0])
    for r in lines:
        if r['season'] == last:
            season_ppr[r['id']][0] += r['ppr']; season_ppr[r['id']][1] += 1
    latest = {}
    for r in lines:
        if r['season'] == last:
            latest[r['id']] = r
    out = []
    for g in [g for g in upcoming if int(g['week']) == week]:
        imp = implied(g)
        h, a = team(g['home_team']), team(g['away_team'])
        for t, o, home, ip in ((h, a, True, imp and imp[0]), (a, h, False, imp and imp[1])):
            last_g = prev.get(t)
            if not last_g or last_g[0] != last:
                continue
            for r in bg.get(last_g, []):
                if r['id'] in inj or latest[r['id']]['team'] != t:
                    continue
                rate = st.rate(r['id'], pri[r['pos']], P['k'])
                env = ip / st.team_pts(t) if ip else 1.0
                q = project(rate, st.opp(o, r['pos']), env, P['b'], P['g'])
                pts = ppr(q)
                if pts < 3:
                    continue
                sp = season_ppr[r['id']]
                ry = q['ryd'] + q['yyd']; td = q['rtd'] + q['ytd']
                if r['pos'] == 'QB':
                    ln = f"{round(q['pyd'])} pass yds · {q['ptd']:.1f} pass TD" + (f" · {round(ry)} yds · {td:.1f} TD" if ry >= 15 else '')
                else:
                    ln = f"{round(ry)} yds" + (f" · {q['rec']:.1f} rec" if q['rec'] >= 1 else '') + f" · {td:.1f} TD"
                out.append({'name': r['name'], 'pos': r['pos'], 'team': t, 'opp': o, 'home': home, 'kick': kick(g), 'day': g['weekday'][:3],
                            'pts': round(pts, 1), 'line': ln, 'ppg': round(sp[0] / sp[1], 1) if sp[1] else None, 'photo': latest[r['id']]['photo'],
                            'proj': {'passYds': round(q['pyd']), 'passTd': round(q['ptd'], 1), 'int': round(q['int'], 1),
                                     'yds': round(ry), 'rec': round(q['rec'], 1), 'td': round(td, 1)},
                            'imp': round(ip, 1) if ip else None})
    out.sort(key=lambda x: -x['pts'])
    res = {'season': last, 'week': week, 'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'out': len(inj), 'fit': {k: F[k] for k in ('params', 'mae', 'naive', 'n', 'kept')}, 'players': out[:300]}
    json.dump(res, open(OUT, 'w'), separators=(',', ':'))
    print(f"nfl proj: {last} week {week}, {len(out)} players, top {out[0]['name']} {out[0]['pts']}" if out else 'nfl proj: none')


if __name__ == '__main__':
    backtest() if '--fit' in sys.argv else build()
