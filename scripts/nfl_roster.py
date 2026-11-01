#!/usr/bin/env python3
"""The NFL game model's offseason roster prior (scripts/nfl_offseason_research.py, data/nfl_roster_fit.json; Oct 21 2026).

Each player's WAR for the new season is projected from his last two seasons (AV WAR, as nfl_war.war_ledger, kept by
team), his age (one curve: years past 29 and under 25) and, two seasons in or less, his draft slot; rookies from draft
slot alone. Then each team's offseason moves are the projected WAR of its week-1 roster (nflverse weekly rosters,
active and game-day inactive; QBs left out, the QB term has them) minus the projected WAR of last season's players at
their share of last season's games with the team: free agency, trades, cuts and the draft class, in WAR.

The game model adds ROSTER['c'] x (moves home x fade - moves away x fade) x 36/17 points to the margin, fade =
0.5 ** (games the team has played this season / ROSTER['hl']), at a fixed share picked on 2015-20 (a refit weight
on the thin 2014-on history did worse). Stdlib only, for the board job.
"""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N   # noqa: E402
import nfl_war as W     # noqa: E402

FIT = os.path.join(N.ROOT, 'data', 'nfl_roster_fit.json')
ROSTER = {'c': 0.25, 'hl': 8.0, 'aging': 'pooled'}
FIRST = 2013           # snap counts (and so WAR) start here
TEAM = {'LAR': 'LA', 'STL': 'LA', 'OAK': 'LV', 'SD': 'LAC', 'SL': 'LA', 'ARZ': 'ARI', 'BLT': 'BAL', 'CLV': 'CLE', 'HST': 'HOU'}
tm = lambda t: N.team(TEAM.get(t, t))


def team_ledger(y):
    """{(gsis, team): [WAR, games]} for season y: war_ledger's formula, kept by team."""
    b = json.load(open(W.FIT))['coef']
    by_pfr, by_name = W.gsis_map(y)
    sd = W.season_data(y)
    out = {}
    for (pfr, t), s in sd['snaps'].items():
        gsis = by_pfr.get(pfr) or by_name.get((W.NM.key(s['name']), t))
        g, _ = W.group_of(s['pos'], '')
        if not gsis or not g:
            continue
        x = W.features(sd, pfr, gsis, t, g)
        if x is None:
            continue
        P = sd['plays'][t]
        share = ((s['off'] / P[0]) if g in W.OFFENSE else (s['def'] / P[1])) * sd['team'][t]['g'] / 17 if P[0] and P[1] else 0.0
        a = out.setdefault((gsis, tm(t)), [0.0, 0, g])
        a[0] += (W.predict(b, g, x) - W.NFL_REPL[g] * share) * W.NWAR_PER_AV
        a[1] += s['g']
    return out


def rosters(y):
    """Week-1 active roster per team ({team: {gsis: row}}) and every player's bio row."""
    wk = defaultdict(dict)
    first = {}
    for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv')):
        if r['game_type'] != 'REG' or not r['gsis_id'] or r['status'] not in ('ACT', 'INA'):
            continue
        w = int(r['week']); t = tm(r['team'])
        f = first.setdefault(t, w)
        if w < f:
            first[t] = w; wk[t] = {}
        if w == first[t]:
            wk[t][r['gsis_id']] = r
    return wk


def age(r, y):
    try:
        by, bm = int(r['birth_date'][:4]), int(r['birth_date'][5:7])
        return y - by - (bm - 9) / 12
    except (ValueError, TypeError, KeyError):
        return 26.0


def pick(r):
    try:
        return int(float(r['draft_number']))
    except (ValueError, TypeError, KeyError):
        return None


GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB']
RPOS = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'OT': 'OL',
        'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LB': 'LB', 'ILB': 'LB', 'OLB': 'LB', 'MLB': 'LB', 'CB': 'DB', 'S': 'DB',
        'SS': 'DB', 'FS': 'DB', 'DB': 'DB'}


def pfeat(w1, w2, has2, a, rk, yrs, p, grp, aging):
    """Projection inputs. rk: rookie; yrs: seasons in the league before this one; p: draft pick or None.
    aging: 'none', 'pooled' (one curve: years past 29, years under 25) or 'pos' (a curve and a level per position group,
    hinged at 27 with a slope each side and a quadratic past it, so RBs can fall off sooner than QBs)."""
    lp = math.log(p) if p else math.log(300)
    early = 1.0 if yrs <= 2 else 0.0
    x = [1.0, w1, w2, has2, rk, rk * lp, early * (1 - rk), early * (1 - rk) * lp, 1.0 if p is None else 0.0]
    if aging == 'pooled':
        x += [max(0.0, a - 29), max(0.0, 25 - a)]
    elif aging == 'pos':
        for G in GROUPS:
            d = 1.0 if grp == G else 0.0
            x += [d, d * max(0.0, a - 27), d * max(0.0, a - 27) ** 2, d * max(0.0, 27 - a), d * w1 * max(0.0, a - 27)]
    return x



def player_war(led):
    """{(gsis, team): [WAR, games, group]} -> ({gsis: WAR}, {gsis: group})."""
    pw, pos = defaultdict(float), {}
    for (g, t), v in led.items():
        pw[g] += v[0]; pos[g] = v[2]
    return pw, pos


def player_rows(y, ros, pw1, pw2, has2, pos, aging=ROSTER['aging']):
    """Projection inputs for every player on a week-1 roster in y: [(team, gsis, row, x)]."""
    out = []
    for t, rs in ros.items():
        for g, r in rs.items():
            ry = int(r['rookie_year']) if r.get('rookie_year', '').isdigit() else (int(r['entry_year']) if r.get('entry_year', '').isdigit() else y)
            rk = 1.0 if ry >= y else 0.0
            grp = pos.get(g) or RPOS.get(r['position'], 'DB')
            out.append((t, g, r, pfeat(pw1.get(g, 0.0), pw2.get(g, 0.0), has2, age(r, y), rk, y - ry, pick(r), grp, aging)))
    return out


def team_moves(y, prev, ros, proj, pw1, pos, qbs_in=False):
    """{team: {moves, rook, aging, total, prevWar, proj}} for season y. prev: last season's team ledger; proj: {gsis:
    projected WAR} for this season's week-1 rosters (anyone not on one keeps .4 of last season's WAR)."""
    gp = defaultdict(int)
    for (g, t), v in prev.items():
        gp[g] += v[1]
    keep = lambda g: qbs_in or pos.get(g) != 'QB'
    pt = defaultdict(float); pp = defaultdict(float); rp = defaultdict(float); rk = defaultdict(float)
    for (g, t), v in prev.items():
        if not keep(g):
            continue
        pt[t] += v[0]
        sh = v[1] / gp[g] if gp[g] else 0.0
        pp[t] += sh * proj.get(g, 0.4 * pw1.get(g, 0.0))
    for t, rs in ros.items():
        for g, r in rs.items():
            if r['position'] == 'QB' and not qbs_in:
                continue
            v = proj.get(g, 0.0)
            rp[t] += v
            ry = r.get('rookie_year', '')
            if ry.isdigit() and int(ry) >= y:
                rk[t] += v
    return {t: {'moves': rp[t] - pp[t], 'rook': rk[t], 'aging': pp[t] - pt[t], 'total': rp[t] - pt[t],
                'prevWar': pt[t], 'proj': rp[t]} for t in ros}


def live(y):
    """This season's offseason moves by team ({team: WAR}) on the saved projection fit; {} if anything is missing."""
    try:
        b = json.load(open(FIT))['coef']
        prev, prev2 = team_ledger(y - 1), team_ledger(y - 2)
        ros = rosters(y)
    except (OSError, ValueError, KeyError) as e:
        print('nfl roster prior: skipped', repr(e))
        return {}
    pw1, pos = player_war(prev); pw2, pos2 = player_war(prev2)
    pos = {**pos2, **pos}
    proj = {g: sum(c * v for c, v in zip(b, x)) for _, g, _, x in player_rows(y, ros, pw1, pw2, 1.0, pos)}
    return {t: v['moves'] for t, v in team_moves(y, prev, ros, proj, pw1, pos).items()}


def fade(n):
    return 0.5 ** (n / ROSTER['hl'])


def points(moves, t, n):
    """The prior's points for team t after n games this season."""
    return ROSTER['c'] * fade(n) * moves.get(t, 0.0) * N.PTS_PER_WIN / 17
