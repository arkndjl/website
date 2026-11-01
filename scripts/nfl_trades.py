#!/usr/bin/env python3
"""In-season moves in the NFL game model: trades, waiver claims and signings off other clubs (Nov 1 2026;
scripts/nfl_trades_research.py, data/nfl_trades_research.json).

The team ratings learn a roster only from games played. After a trade the old club's ratings still carry the player
and the new club's don't have him, until games wash it in. For each team before each game:
    departures  players who took snaps for the club earlier this season and are on another club's roster now, at
                WAR a game (nfl_games.player_value, the injury term's value) x the share of the club's games he
                played for it (what its ratings carry)
    arrivals    players on the club's roster now who took snaps for another club earlier this season, at WAR a game
                x the share of his old club's games he played
    points      arrivals - departures x 36, each faded 0.5 ** (the club's games since the move / hl)
QBs are left out (the QB term reads the starter). History: nflverse weekly rosters (the club a player is on for
that week's game) and PFR snap counts; live, this week's club comes from ESPN's team rosters (nflverse's roster
file lags trades by days), joined by ESPN id and then the shared name matcher on position. Stdlib only.
"""
import json
import os
import sys
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N   # noqa: E402

ON = ('ACT', 'INA', 'RES')          # on a club's roster that week (reserve lists included: still that club's player)
# Backtest (Nov 1 2026, data/nfl_trades_research.json, 2015-20 tune / 2021-25 held, MAE vs results): no version passes.
# Refit as an input the weight is negative for departures in every variant (-0.2 to -2.9) and the walk-forward is
# worse; at fixed shares on top of the walk-forward (c .25-1.36, hl 1-8 or flat, all moves / direct moves / regulars,
# floored or not) the best cell is arrivals only, direct, hl 4, c .25: -.0008 (t -1.1) / .0000 (t 0.0); the injury
# weight on both sides (c 1, hl 2, direct) -.0010 (t -0.3) / +.0021 (t +0.5). Result minus the close on the term is
# noise (t -1.4 to +0.5, signs flip by period): the close prices these moves at about their value. A typical move is
# 0.3-0.9 points (McCaffrey 2022 1.0, Simmons 2026 0.9), so 11 seasons can't tell it from zero.
# Noah chose (Nov 1 2026) to put it in the line anyway: direct moves, both sides, at the injury term's fitted weight
# (nfl_games_fit.json coef inj), fading with a half-life of 2 club games, outside the fit (as the roster prior).
TRADES = {'on': True, 'hl': 2.0, 'direct': True}


def _snaps(y, tw=None):
    """{gsis: {team: set(weeks with snaps)}} for season y's regular season. Ids: pfr id, else name on the club,
    from the season roster file and every week's roster (the season file has a traded player on his new club only)"""
    import nfl_war as W
    by_pfr, by_name = W.gsis_map(y)
    by_pfr, by_name = dict(by_pfr), dict(by_name)
    for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv')):
        if r['gsis_id']:
            if r.get('pfr_id'):
                by_pfr.setdefault(r['pfr_id'], r['gsis_id'])
            by_name.setdefault((r['full_name'].lower(), r['team']), r['gsis_id'])
    out = defaultdict(lambda: defaultdict(set))
    for r in N.rows(N.get(f'snap_counts_{y}.csv', f'{N.REL}/snap_counts/snap_counts_{y}.csv')):
        if r['game_type'] != 'REG':
            continue
        if N.num(r['offense_snaps']) + N.num(r['defense_snaps']) <= 0:
            continue
        t = N.team(r['team'])
        g = by_pfr.get(r['pfr_player_id']) or by_name.get((r['player'].lower(), r['team']))
        if g:
            out[g][t].add(int(r['week']))
    if tw is not None:            # a week the weekly roster puts him on another club is a crossed id: dropped
        for g, by in out.items():
            for t, ks in by.items():
                ks -= {k for k in ks if (g, k) in tw and tw[(g, k)][0] != t}
    return out


def _weekly(y, fresh=False):
    """{(gsis, week): (team, status)} and gsis -> position from the weekly rosters"""
    tw, pos = {}, {}
    p = N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv', fresh)
    for r in N.rows(p):
        if r['game_type'] != 'REG' or not r['gsis_id']:
            continue
        k = (r['gsis_id'], int(r['week']))
        st = r['status']
        if k in tw and tw[k][1] in ON and st not in ON:
            continue
        tw[k] = (N.team(r['team']), st)
        pos[r['gsis_id']] = r['position']
    return tw, pos


def _ledgers(y, weeks):
    import nfl_war as W
    maps = W.gsis_map(y)
    prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
    return prev, {w: W.war_ledger(y, thru=w, maps=maps) for w in weeks}


def _team_weeks(games, y):
    tg = defaultdict(list)
    for g in games:
        if int(g['season']) == y and g['game_type'] == 'REG':
            for s in ('home', 'away'):
                tg[N.team(g[f'{s}_team'])].append(int(g['week']))
    return {t: sorted(v) for t, v in tg.items()}


def moves_for(t, w, now_team, snaps, wk_team, tweeks, pos, val):
    """[(kind, WAR a game x share, club games since the move, direct, share, gsis, the other club)] for club t
    before its week-w game.
    direct: straight from one club's roster to the other's from one week to the next (a trade or a claim, not a cut
    and a later signing); share: the share of the old club's games he played.
    now_team(p): p's club for this game (None if none); wk_team(p, k): his club in week k; val(p): WAR a game."""
    out = []
    games_before = [k for k in tweeks.get(t, []) if k < w]
    n_t = len(games_before)
    for p, by in snaps.items():
        if pos.get(p) == 'QB':
            continue
        here = by.get(t)
        cur = now_team(p)
        mine = {k for k in here if k < w} if here else set()
        if mine and cur and cur != t:
            # departed: moved after his last week on t's roster
            lastk = max(k for k in range(1, w) if wk_team(p, k) == t) if any(wk_team(p, k) == t for k in range(1, w)) else max(mine)
            n = sum(1 for k in games_before if k > lastk)
            nxt = wk_team(p, lastk + 1) if lastk + 1 < w else cur
            sh = len(mine) / max(n_t, 1)
            out.append(('dep', val(p) * sh, n, bool(nxt and nxt != t), sh, p, nxt or cur))
        elif cur == t:
            # arrived: on t now, with snaps for another club before his first week on t's roster since then
            other = {tt: ks for tt, ks in by.items() if tt != t}
            if not other:
                continue
            old = max(other, key=lambda tt: max(other[tt]))
            lo = max(other[old])
            if mine and min(mine) < lo:
                continue                     # played for t before the other club: a return, not a new arrival
            first = min([k for k in range(lo + 1, w) if wk_team(p, k) == t] + [w])
            n = sum(1 for k in games_before if k >= first)
            ng = len([k for k in tweeks.get(old, []) if k <= lo])
            sh = min(1.0, len(other[old]) / max(ng, 1))
            out.append(('arr', val(p) * sh, n, first > 1 and wk_team(p, first - 1) == old, sh, p, old))
    return out


def before(snaps, w):
    """the snap weeks before week w: {gsis: {team: weeks}}, players with any"""
    out = {}
    for p, by in snaps.items():
        b = {t: {k for k in ks if k < w} for t, ks in by.items()}
        b = {t: ks for t, ks in b.items() if ks}
        if b:
            out[p] = b
    return out


def season_terms(y, games):
    """{(game_id, team): [(kind, value, n)]} for every regular-season game of season y, no look-ahead"""
    tw, pos = _weekly(y)
    snaps = _snaps(y, tw)
    tweeks = _team_weeks(games, y)
    weeks = sorted({int(g['week']) for g in games if int(g['season']) == y and g['game_type'] == 'REG'})
    prev, led = _ledgers(y, weeks)
    out, cache = {}, {}
    for g in games:
        if int(g['season']) != y or g['game_type'] != 'REG':
            continue
        w = int(g['week'])
        L = led[w]
        val = lambda p: N.player_value(prev.get(p, (0.0, 0)), L.get(p, (0.0, 0)))
        if w not in cache:
            cache[w] = before(snaps, w)
        sn = cache[w]

        def now_team(p, w=w):
            v = tw.get((p, w))
            return v[0] if v and v[1] in ON else None

        def wk_team(p, k):
            v = tw.get((p, k))
            return v[0] if v and v[1] in ON else None
        for s in ('home', 'away'):
            t = N.team(g[f'{s}_team'])
            out[(g['game_id'], t)] = moves_for(t, w, now_team, sn, wk_team, tweeks, pos, val)
    return out


def points(ms, hl, kind='both', floor=False, direct=False, share=0.0):
    """a club's move term in points a game: arrivals - departures, each faded by club games since the move"""
    v = 0.0
    for k, x, n, d, sh, *_ in ms:
        if (kind != 'both' and k != kind) or (direct and not d) or sh < share:
            continue
        x = max(x, 0.0) if floor else x
        f = 0.5 ** (n / hl) if hl else 1.0
        v += (x if k == 'arr' else -x) * f
    return v * N.PTS_PER_WIN


def card(ms, names, top=4, c=1.0):
    """the moves a game card lists: direct moves since the club's last two games, in model points (WAR a game x 36
    x the weight c x the fade)"""
    out = []
    for k, x, n, d, sh, p, other in ms:
        if not d or n >= 2:
            continue
        nm, ps = names.get(p, (p, ''))
        f = 0.5 ** (n / TRADES['hl'])
        out.append({'name': nm, 'pos': ps, 'dir': 'in' if k == 'arr' else 'out', 'team': other,
                    'pts': round(x * N.PTS_PER_WIN * c * f * (1 if k == 'arr' else -1), 1)})
    out.sort(key=lambda r: -abs(r['pts']))
    return [r for r in out if abs(r['pts']) >= 0.1][:top]


# ---------------------------------------------------------------- live
ESPN_TEAM = {'WSH': 'WAS', 'LAR': 'LA'}


def espn_rosters():
    """{espn id: (team, name, position)} from ESPN's 32 team rosters (current to the day)"""
    out = {}
    for t in N.TEAMS:
        code = {'LA': 'lar', 'WAS': 'wsh'}.get(t, t.lower())
        u = f'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{code}/roster'
        req = urllib.request.Request(u, headers={'User-Agent': 'arkndjl.net arkboard'})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
        ab = ESPN_TEAM.get(j.get('team', {}).get('abbreviation', ''), j.get('team', {}).get('abbreviation', t))
        for grp in j.get('athletes', []):
            for a in grp.get('items', []):
                out[a['id']] = (N.team(ab), a.get('fullName', ''), (a.get('position') or {}).get('abbreviation', ''))
    return out


def live(y, week, games):
    """({team: [moves_for rows]}, {gsis: (name, position)}) before this week's games; ({}, {}) if a source is missing. The club each player is on
    now: ESPN's rosters, joined to gsis by ESPN id (nflverse roster file) or name on position; players ESPN doesn't
    list keep their last weekly-roster club."""
    import names as NM
    try:
        tw, pos = _weekly(y, fresh=True)
        snaps = _snaps(y, tw)
        ros = list(N.rows(N.get(f'roster_{y}.csv', f'{N.REL}/rosters/roster_{y}.csv')))
        es = espn_rosters()
    except Exception as e:      # noqa: BLE001
        print('nfl trades: skipped', repr(e))
        return {}, {}
    by_espn = {r['espn_id']: r['gsis_id'] for r in ros if r.get('espn_id') and r['gsis_id']}
    for r in ros:
        pos.setdefault(r['gsis_id'], r['position'])
    M = NM.Matcher([r for r in ros if r['gsis_id']], name='full_name', team=None, pos='position')
    now = {}
    for eid, (t, nm, ps) in es.items():
        g = by_espn.get(eid)
        if not g:
            hit, _ = M.find(nm, pos=ps)
            g = hit['gsis_id'] if hit else None
        if g:
            now[g] = t
    lastwk = {}
    for (p, k), (t, st) in tw.items():
        if st in ON and k >= lastwk.get(p, (0, None))[0]:
            lastwk[p] = (k, t)
    tweeks = _team_weeks(games, y)
    prev, led = _ledgers(y, [week])
    L = led[week]
    val = lambda p: N.player_value(prev.get(p, (0.0, 0)), L.get(p, (0.0, 0)))
    sn = before(snaps, week)

    def now_team(p):
        if p in now:
            return now[p]
        v = lastwk.get(p)
        return v[1] if v and v[0] >= week - 1 else None

    def wk_team(p, k):
        v = tw.get((p, k))
        return v[0] if v and v[1] in ON else None
    out = {}
    for t in tweeks:
        out[t] = moves_for(t, week, now_team, sn, wk_team, tweeks, pos, val)
    names = {r['gsis_id']: (r['full_name'], r['position']) for r in ros if r['gsis_id']}
    n = sum(1 for v in out.values() for z in v if z[3] and z[2] == 0)
    print('nfl trades: direct moves since each club\'s last game', n)
    return out, names
