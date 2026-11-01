#!/usr/bin/env python3
"""Player badges for the NHL ARKBOARD's WAR leaderboard (the College Football board's medals, scripts/cfb_badges.mjs).

A badge is one trait (Playmaker, Shooter...) measured by one stat on MoneyPuck's season line. The stat is regressed
toward the position mean by its volume, v' = m + (v - m) * n / (n + k), k = n (1 - r) / r from the year-to-year r at
the pairs' mean volume n (MoneyPuck 2008-09 to 2025-26, players in the pool both seasons; scripts/nhl_badge_backtest.py
measures them). The tier is the percentile of v' among the position's pool that season (forwards, defencemen, goalies;
skaters with 200+ minutes, goalies 600+, both scaled to the season's games so far):
    Bronze 75th, Silver 90th, Gold 97th, Platinum 99th.
CANDS lists every candidate the backtest measures; SHIP the ones that predicted next season's WAR beyond this season's
WAR, pWAR and HPM (clustered t >= 2, a leave-one-season-out gain, positive sign, alone and next to the other passers;
data/nhl_badge_backtest.json). Only SHIP badges reach the board, as display: pWAR is fit to team goal differential
(scripts/nhl_players.py) and the badges are not added to it.
"""
import bisect
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MPD = os.path.join(HERE, '.cache', 'nhl', 'mp')
TIERS = [('p', .99), ('g', .97), ('s', .90), ('b', .75)]
MIN_TOI = {'F': 200, 'D': 200, 'G': 600}          # minutes for the pool, per 82 team games


def _f(r, k):
    try:
        return float((r or {}).get(k) or 0)
    except ValueError:
        return 0.0


def _per60(x, sec):
    return x / (sec / 3600) if sec > 0 else None


def _rel5(e5, on, off):
    """5-on-5 on-ice rate a 60 minus the team's rate with him on the bench"""
    i5, b5 = _f(e5, 'icetime'), _f(e5, 'timeOnBench')
    if i5 <= 0 or b5 <= 0:
        return None
    return _f(e5, on) / (i5 / 3600) - _f(e5, off) / (b5 / 3600)


def _neg(v):
    return None if v is None else -v


# [key, name, groups, value (higher is better), volume, what the stat is]; volume in minutes unless noted. k comes
# from data/nhl_badge_backtest.json (the measured year-to-year r), K below is the fallback.
CANDS = [
    ['scorer', 'Scorer', 'FD', lambda a, s: _per60(_f(a, 'I_F_goals'), _f(a, 'icetime')), lambda a, s: _f(a, 'icetime') / 60, 'goals a 60'],
    ['sniper', 'Sniper', 'FD', lambda a, s: ((_f(a, 'I_F_goals') - _f(a, 'I_F_xGoals')) / _f(a, 'I_F_unblockedShotAttempts')) if _f(a, 'I_F_unblockedShotAttempts') > 0 else None,
     lambda a, s: _f(a, 'I_F_unblockedShotAttempts'), 'goals over xG a shot'],
    ['shooter', 'Shooter', 'FD', lambda a, s: _per60(_f(a, 'I_F_shotAttempts'), _f(a, 'icetime')), lambda a, s: _f(a, 'icetime') / 60, 'shot attempts a 60'],
    ['chances', 'Chance Getter', 'FD', lambda a, s: _per60(_f(a, 'I_F_xGoals'), _f(a, 'icetime')), lambda a, s: _f(a, 'icetime') / 60, 'individual xG a 60'],
    ['playmaker', 'Playmaker', 'FD', lambda a, s: _per60(_f(a, 'I_F_primaryAssists'), _f(a, 'icetime')), lambda a, s: _f(a, 'icetime') / 60, 'primary assists a 60'],
    ['driver', 'Play Driver', 'FD', lambda a, s: _rel5(s.get('5on5'), 'OnIce_F_xGoals', 'OffIce_F_xGoals'), lambda a, s: _f(s.get('5on5'), 'icetime') / 60,
     '5-on-5 on-ice xG for, relative to team'],
    ['suppress', 'Shot Suppressor', 'FD', lambda a, s: _neg(_rel5(s.get('5on5'), 'OnIce_A_shotAttempts', 'OffIce_A_shotAttempts')),
     lambda a, s: _f(s.get('5on5'), 'icetime') / 60, '5-on-5 on-ice shot attempts against, relative to team'],
    ['pp', 'Power Play', 'FD', lambda a, s: _per60(_f(s.get('5on4'), 'I_F_points'), _f(s.get('5on4'), 'icetime')) if _f(s.get('5on4'), 'icetime') >= 600 else None,
     lambda a, s: _f(s.get('5on4'), 'icetime') / 60, '5-on-4 points a 60'],
    ['physical', 'Physical', 'FD', lambda a, s: _per60(_f(a, 'I_F_hits'), _f(a, 'icetime')), lambda a, s: _f(a, 'icetime') / 60, 'hits a 60'],
    ['takeaway', 'Takeaways', 'FD', lambda a, s: _per60(_f(a, 'I_F_takeaways'), _f(a, 'icetime')), lambda a, s: _f(a, 'icetime') / 60, 'takeaways a 60'],
    ['blocker', 'Shot Blocker', 'FD', lambda a, s: _per60(_f(a, 'shotsBlockedByPlayer'), _f(a, 'icetime')), lambda a, s: _f(a, 'icetime') / 60, 'shots blocked a 60'],
    ['faceoff', 'Faceoffs', 'F', lambda a, s: (_f(a, 'faceoffsWon') / (_f(a, 'faceoffsWon') + _f(a, 'faceoffsLost'))) if _f(a, 'faceoffsWon') + _f(a, 'faceoffsLost') >= 200 else None,
     lambda a, s: _f(a, 'faceoffsWon') + _f(a, 'faceoffsLost'), 'faceoff win %'],
    # goalies
    ['stopper', 'Shot Stopper', 'G', lambda a, s: ((_f(a, 'xGoals') - _f(a, 'goals')) / _f(a, 'unblocked_shot_attempts')) if _f(a, 'unblocked_shot_attempts') > 0 else None,
     lambda a, s: _f(a, 'unblocked_shot_attempts'), 'goals saved above expected a shot'],
    ['hd', 'High Danger', 'G', lambda a, s: ((_f(a, 'highDangerxGoals') - _f(a, 'highDangerGoals')) / _f(a, 'highDangerShots')) if _f(a, 'highDangerShots') > 0 else None,
     lambda a, s: _f(a, 'highDangerShots'), 'high-danger goals saved above expected a shot'],
    ['rebound', 'Rebound Control', 'G', lambda a, s: ((_f(a, 'xRebounds') - _f(a, 'rebounds')) / _f(a, 'unblocked_shot_attempts')) if _f(a, 'unblocked_shot_attempts') > 0 else None,
     lambda a, s: _f(a, 'unblocked_shot_attempts'), 'rebounds under expected a shot'],
    ['freeze', 'Puck Control', 'G', lambda a, s: ((_f(a, 'freeze') - _f(a, 'xFreeze')) / _f(a, 'unblocked_shot_attempts')) if _f(a, 'unblocked_shot_attempts') > 0 else None,
     lambda a, s: _f(a, 'unblocked_shot_attempts'), 'freezes over expected a shot'],
]
BY = {c[0]: c for c in CANDS}
# shipped: passed the backtest alone AND next to the other passers (group -> key -> k, the volume at which the stat is
# half signal). Nov 1 2026, next-season WAR per 82 games on WAR + pWAR + HPM, t clustered by player, 17 seasons held out
# one at a time (oos = R^2 gain x100; joint = with the group's other shipped badges in):
#   F  Scorer       r .57  t  9.7  oos 1.07  joint t 4.3    Shooter          r .76  t 12.5  oos 1.73  joint t 6.9
#      Playmaker    r .57  t  6.1  oos  .41  joint t 3.7    Play Driver      r .55  t  7.1  oos  .44  joint t 3.8
#      Takeaways    r .55  t  9.4  oos  .87  joint t 9.1
#   D  Chance Getter r .70 t  7.6  oos 1.34  joint t 6.2    Shot Suppressor  r .40  t  6.7  oos  .86  joint t 6.5
#      Takeaways    r .56  t  6.3  oos 1.31  joint t 4.5
# Failed (data/nhl_badge_backtest.json): F Sniper (t .1), Shot Suppressor (.5), Chance Getter and Power Play (pass alone,
# t 1.6 / 1.8 next to the rest), Physical, Shot Blocker, Faceoffs (negative: t -7.6, -5.4, -2.1); D Scorer, Shooter,
# Playmaker (pass alone, not next to Chance Getter), Play Driver (-1.5), Power Play (1.4), Physical (-4.9), Shot Blocker
# (-2.9); G Shot Stopper (year-to-year r .12, noise), High Danger (t 1.0), Rebound Control (.6), Puck Control (.9).
SHIP = {'F': {'shooter': 320, 'takeaway': 829, 'scorer': 778, 'driver': 663, 'playmaker': 750},
        'D': {'suppress': 1488, 'chances': 516, 'takeaway': 960}}


def lines(S):
    """MoneyPuck's season S lines (file year S - 1): {player id: (group, {situation: row})}"""
    out = {}
    for kind in ('skaters', 'goalies'):
        fn = os.path.join(MPD, f'{kind}_{S - 1}.csv')
        if not os.path.exists(fn):
            continue
        for r in csv.DictReader(open(fn)):
            g = 'G' if kind == 'goalies' else ('D' if r['position'] == 'D' else 'F')
            out.setdefault(r['playerId'], (g, {}))[1][r['situation']] = r
    return out


def raw(S, keys=None):
    """{key: {player id: (group, value, volume, minutes)}} for the season's pool players"""
    L = lines(S)
    out = {}
    for key, _, grps, val, vol, _ in CANDS:
        if keys is not None and key not in keys:
            continue
        d = {}
        for pid, (g, s) in L.items():
            a = s.get('all')
            if g not in grps or not a:
                continue
            v = val(a, s)
            if v is None:
                continue
            d[pid] = (g, v, max(0.0, vol(a, s)), _f(a, 'icetime') / 60)
        out[key] = d
    return out


def regressed(d, k, games=82):
    """{player id: (group, regressed value, z in the group pool, percentile in the pool)} for pool players"""
    out = {}
    for g in 'FDG':
        xs = [(pid, v, n) for pid, (gg, v, n, m) in d.items() if gg == g and m >= max(40 if g != 'G' else 120, MIN_TOI[g] * games / 82)]
        if len(xs) < 20:
            continue
        nw = sum(n for _, _, n in xs)
        m = sum(v * n for _, v, n in xs) / nw if nw else sum(v for _, v, _ in xs) / len(xs)
        reg = [(pid, m + (v - m) * n / (n + k)) for pid, v, n in xs]
        mu = sum(v for _, v in reg) / len(reg)
        sd = (sum((v - mu) ** 2 for _, v in reg) / len(reg)) ** .5 or 1
        srt = sorted(v for _, v in reg)
        for pid, v in reg:
            out[pid] = (g, v, (v - mu) / sd, bisect.bisect_left(srt, v) / len(srt))
    return out


def assign(S, rows, games=82):
    """sets r['bdg'] = [[name, tier letter, percentile, stat], ...] best first (SHIP badges, bronze or better) on the
    season's board rows (dicts with 'id'); games: the season's team games so far (scales the pool's minutes)"""
    R = raw(S, {k for d in SHIP.values() for k in d})
    got = {}
    for g, ks in SHIP.items():
        for key, k in ks.items():
            _, name, _, _, _, stat = BY[key]
            for pid, (gg, v, z, pc) in regressed(R.get(key, {}), k, games).items():
                t = next((t for t, cut in TIERS if pc >= cut), None)
                if gg == g and t:
                    got.setdefault(pid, []).append([name, t, min(99, int(100 * pc)), stat])
    rank = {'p': 4, 'g': 3, 's': 2, 'b': 1}
    for r in rows:
        b = got.get(str(r['id']))
        if b:
            r['bdg'] = sorted(b, key=lambda x: (-rank[x[1]], -x[2]))
    return rows
