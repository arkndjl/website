# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL non-QB season value (layouts/shortcodes/nflseason.html: leaders > skill, defense) -> data/nfl_season_value.json.
Descriptive, this season only; nothing here feeds a model.

Skill (RB, WR, TE): every designed run (rusher) and target (receiver, sacks out) from nflverse play-by-play, regular season
+ playoffs, two-point tries, spikes and kneels out.
  aEPA   EPA a play less the defense's EPA allowed a play of that kind (run / pass) over the league's, from its other
         games, shrunk with K_DEF = 300 plays (RB and WR; TE left raw). RBs also less the play's weather (WX, fit 2016-25 on
         every run and dropback: wind over 10 mph, cold under 40 F, rain / snow, outdoor games)
  SV  sum(aEPA - replacement) / games with an offensive snap; replacement = the mean aEPA a run / a target of the
         players past the starters by volume (RB 48, WR 96, TE 48 a season), 2016-25 (REPL)
Defense (DL, LB, DB): credited EPA. On each play with a negative EPA the defenders credited with a sack (half sacks .5), INT,
pass defensed, forced fumble, TFL, QB hit, or (failed run / completion) a tackle split -(EPA - offense adjustment); the
offense adjustment = the offense's EPA a play over the league's, other games, shrunk 300 plays (DL and DB; LB left raw).
  SV  sum(credit - replacement a snap x defensive snaps) / games with a defensive snap; replacement = the credit a
         snap of the players past the starters by snaps (DL 128, LB 80, DB 160), 2016-25
Adjustments kept only where the split-half reliability (alternate games, 2016-26 player-seasons: skill 100+ plays,
defense 300+ snaps; 1,000 boots) went up with P >= .9:
  opponent  RB r .199 -> .217 (P .99), WR .172 -> .190 (1.0), TE .326 -> .310 (.17), DL .308 -> .315 (1.0),
            LB .198 -> .200 (.82), DB .147 -> .149 (.91)
  weather   on top: RB .217 -> .220 (P 1.0); WR .37, TE .77 (n 73), DL .64, LB .33, DB .43
In the game model's injury term (each injured / reserve non-QB at this season's value instead of WAR a game) it failed
held out 2021-25 (MAE 10.010 -> 10.070, t 2.6, 0/5 seasons; as an extra term 10.006, t -.3, 2/5 with a negative
coefficient), so the game model keeps WAR (/mnt/project-files/qb-season-metric/nonqb/).
Names, teams, positions, headshots and counting stats: nflverse stats_player_week; snaps: nflverse snap_counts (pfr id ->
gsis through the season roster); WAR from static/data/nfl-war.json (scripts/names.py matcher, team checked)."""
import csv
import gzip
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names  # noqa: E402
from nfl_qb import get, f, FR, REL  # noqa: E402

K_DEF = 300
GROUP = {'RB': 'RB', 'FB': 'RB', 'HB': 'RB', 'WR': 'WR', 'TE': 'TE', 'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'OLB': 'LB',
         'ILB': 'LB', 'MLB': 'LB', 'LB': 'LB', 'CB': 'DB', 'S': 'DB', 'SS': 'DB', 'FS': 'DB', 'DB': 'DB', 'SAF': 'DB'}
OPP = {'RB', 'WR', 'DL', 'DB'}
WEA = {'RB'}
# replacement: aEPA a run (0) / a target (1) for skill players, credit a snap for defenders (2016-25, research above)
REPL = {('RB', 0): -0.0942, ('RB', 1): -0.0005, ('WR', 0): 0.0827, ('WR', 1): 0.0811, ('TE', 0): 0.2589, ('TE', 1): 0.1247,
        'DL': 0.0250, 'LB': 0.0325, 'DB': 0.0211}
# weather on EPA a play (run 0 / dropback 1): wind mph over 10, degrees under 40 F, rain / snow; outdoor and open roofs
WX = {0: (0.0004, 0.0013, -0.0005), 1: (-0.0033, -0.0016, -0.0609)}
TK = ['solo_tackle_1_player_id', 'solo_tackle_2_player_id', 'assist_tackle_1_player_id', 'assist_tackle_2_player_id',
      'assist_tackle_3_player_id', 'assist_tackle_4_player_id', 'tackle_with_assist_1_player_id', 'tackle_with_assist_2_player_id']
SPL = ['interception_player_id', 'pass_defense_1_player_id', 'pass_defense_2_player_id', 'forced_fumble_player_1_player_id',
       'forced_fumble_player_2_player_id', 'tackle_for_loss_1_player_id', 'tackle_for_loss_2_player_id', 'qb_hit_1_player_id',
       'qb_hit_2_player_id']
MIN_SKILL, MIN_SNAPS = 30, 150
tm = lambda x: FR.get(x, x)  # noqa: E731


def wadj(kind, wind, temp, wet, out):
    if not out:
        return 0.0
    b = WX[kind]
    return b[0] * max((wind or 0) - 10, 0) + b[1] * max(40 - (temp if temp is not None else 60), 0) + b[2] * wet


def plays(y, fresh):
    allp, off, dfc = [], [], []
    with gzip.open(get(f'play_by_play_{y}.csv.gz', f'{REL}/pbp/play_by_play_{y}.csv.gz', fresh), 'rt', encoding='utf-8') as fh:
        rd = csv.reader(fh)
        h = next(rd); I = {k: i for i, k in enumerate(h)}
        for r in rd:
            g = lambda k: r[I[k]]  # noqa: E731
            if g('two_point_attempt') == '1' or g('season_type') not in ('REG', 'POST'):
                continue
            pt, db = g('play_type'), g('qb_dropback') == '1'
            if pt not in ('run', 'pass') or g('qb_spike') == '1' or g('qb_kneel') == '1':
                continue
            epa = f(g('epa'))
            if epa is None:
                continue
            wthr = g('weather').lower()
            wx = (f(g('wind')), f(g('temp')), 1 if any(w in wthr for w in ('rain', 'snow', 'shower', 'sleet', 'drizzle')) else 0,
                  g('roof') in ('outdoors', 'open'))
            gid, ot, dt = g('game_id'), tm(g('posteam')), tm(g('defteam'))
            kind = 1 if db else 0
            allp.append((gid, ot, dt, kind, epa))
            if pt == 'run' and not db and g('rusher_player_id') not in ('', 'NA'):
                off.append((gid, g('rusher_player_id'), 0, dt, epa, wx))
            elif pt == 'pass' and g('receiver_player_id') not in ('', 'NA') and g('sack') != '1':
                off.append((gid, g('receiver_player_id'), 1, dt, epa, wx))
            W = defaultdict(float)
            if g('sack') == '1':
                if g('sack_player_id') not in ('', 'NA'):
                    W[g('sack_player_id')] += 1
                for c in ('half_sack_1_player_id', 'half_sack_2_player_id'):
                    if g(c) not in ('', 'NA'):
                        W[g(c)] += .5
            for c in SPL:
                if g(c) not in ('', 'NA'):
                    W[g(c)] += 1
            if epa <= 0 and (pt == 'run' or g('complete_pass') == '1'):
                for c in TK:
                    if g(c) not in ('', 'NA'):
                        W[g(c)] += 1
            if W and epa < 0:
                dfc.append((gid, dict(W), ot, epa))
    return allp, off, dfc


def main():
    G = json.load(open(os.path.join(ROOT, 'data', 'nfl_games.json')))
    WAR = json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))['players']
    y = int(G['season'])
    fresh = '--cache' not in sys.argv
    allp, off, dfc = plays(y, fresh)
    # team EPA by kind: defense allowed / offense gained, season and by game, league
    A = defaultdict(lambda: [0.0, 0])
    for gid, ot, dt, kind, epa in allp:
        for key in (('d', dt, kind), ('dg', gid, dt, kind), ('o', ot, kind), ('og', gid, ot, kind), ('l', kind)):
            A[key][0] += epa; A[key][1] += 1

    def rel(side, t, gid, kind):
        s, n = A[(side, t, kind)]; sg, ng = A[(side + 'g', gid, t, kind)]
        m = A[('l', kind)][0] / A[('l', kind)][1] if A[('l', kind)][1] else 0.0
        return ((s - sg) - m * (n - ng)) / (n - ng + K_DEF)
    # who: names, teams, positions, headshots, counting stats
    P, ST = {}, defaultdict(lambda: defaultdict(float))
    with open(get(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv', fresh), newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            P[r['player_id']] = (r['player_display_name'], tm(r['team']), r['position'], r['headshot_url'])
            S = ST[r['player_id']]
            for k in ('carries', 'rushing_yards', 'rushing_tds', 'targets', 'receptions', 'receiving_yards', 'receiving_tds',
                      'def_sacks', 'def_interceptions', 'def_pass_defended', 'def_tackles_for_loss', 'def_fumbles_forced',
                      'def_qb_hits', 'def_tackles_solo', 'def_tackle_assists', 'def_tackles_with_assist'):
                S[k] += f(r.get(k)) or 0.0
    by_pfr = {}
    for r in csv.DictReader(open(get(f'roster_{y}.csv', f'{REL}/rosters/roster_{y}.csv', fresh), newline='', encoding='utf-8')):
        if r['gsis_id'] and r['pfr_id']:
            by_pfr[r['pfr_id']] = r['gsis_id']
            P.setdefault(r['gsis_id'], (r['full_name'], tm(r['team']), r['position'], r.get('headshot_url') or ''))
    osn, dsn = defaultdict(set), defaultdict(lambda: [set(), 0])
    for r in csv.DictReader(open(get(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv', fresh), newline='', encoding='utf-8')):
        gs = by_pfr.get(r['pfr_player_id'])
        if not gs:
            continue
        if (f(r['offense_snaps']) or 0) > 0:
            osn[gs].add(r['game_id'])
        if (f(r['defense_snaps']) or 0) > 0:
            dsn[gs][0].add(r['game_id']); dsn[gs][1] += int(f(r['defense_snaps']))
    grp = lambda pid: GROUP.get((P.get(pid) or ('', '', ''))[2], '')  # noqa: E731
    V = defaultdict(lambda: defaultdict(float))
    for gid, pid, kind, dt, epa, wx in off:
        g = grp(pid)
        if g not in ('RB', 'WR', 'TE'):
            continue
        a = epa - (rel('d', dt, gid, kind) if g in OPP else 0.0) - (wadj(kind, *wx) if g in WEA else 0.0)
        X = V[pid]; X['par'] += a - REPL[(g, kind)]; X['a'] += a; X['n'] += 1; X[f'a{kind}'] += a; X[f'n{kind}'] += 1
    for gid, W, ot, epa in dfc:
        tw = sum(W.values())
        for pid, w in W.items():
            g = grp(pid)
            if g not in ('DL', 'LB', 'DB'):
                continue
            adj = (rel('o', ot, gid, 0) + rel('o', ot, gid, 1)) / 2 if g in OPP else 0.0
            V[pid]['cr'] += -(epa - adj) * w / tw
    war = defaultdict(list)                # last name token -> WAR rows, then the matcher
    for p in WAR:
        war[(names.tokens(p['n']) or [''])[-1]].append(p)

    def war_of(n, t):
        L = [p for p in war.get((names.tokens(n) or [''])[-1], []) if names.same(p['n'], n)]
        L = [p for p in L if t in (p.get('tm') or p.get('t') or '').split('/')] or L
        return L[0] if L else {}
    r1 = lambda x, k=1: None if x is None else round(x, k)  # noqa: E731
    skill, dfn = [], []
    for pid in set(V) | {k for k in dsn if grp(k) in ('DL', 'LB', 'DB')}:
        g = grp(pid)
        n, t, _, ph = P.get(pid, ('', '', '', ''))
        S, X = ST.get(pid, {}), V.get(pid, {})
        w = war_of(n, t)
        if g in ('RB', 'WR', 'TE'):
            if X.get('n', 0) < MIN_SKILL:
                continue
            gp = len(osn.get(pid, ())) or 1
            skill.append({'n': n, 't': t, 'pos': g, 'ph': ph or None, 'pts': r1(X['par'] / gp), 'tot': r1(X['par']),
                          'aepa': r1(X['a'] / X['n'], 3), 'g': gp, 'opp': int(X['n']),
                          'ra': r1(X['a0'] / X['n0'], 3) if X.get('n0') else None,
                          'ta': r1(X['a1'] / X['n1'], 3) if X.get('n1') else None,
                          'car': int(S.get('carries', 0)), 'ry': int(S.get('rushing_yards', 0)), 'rtd': int(S.get('rushing_tds', 0)),
                          'tgt': int(S.get('targets', 0)), 'rec': int(S.get('receptions', 0)), 'recy': int(S.get('receiving_yards', 0)),
                          'rectd': int(S.get('receiving_tds', 0)), 'war': w.get('war')})
        elif g in ('DL', 'LB', 'DB'):
            gs, sn = dsn.get(pid, (set(), 0))
            if sn < MIN_SNAPS:
                continue
            par = X.get('cr', 0.0) - REPL[g] * sn
            dfn.append({'n': n, 't': t, 'pos': g, 'ph': ph or None, 'pts': r1(par / max(len(gs), 1)), 'tot': r1(par),
                        'p100': r1(100 * par / sn, 2), 'cr': r1(X.get('cr', 0.0)), 'g': len(gs), 'sn': sn,
                        'sk': r1(S.get('def_sacks', 0.0)), 'int': int(S.get('def_interceptions', 0)), 'pd': int(S.get('def_pass_defended', 0)),
                        'tfl': r1(S.get('def_tackles_for_loss', 0.0)), 'ff': int(S.get('def_fumbles_forced', 0)),
                        'qbh': int(S.get('def_qb_hits', 0)),
                        'tk': int(S.get('def_tackles_solo', 0) + S.get('def_tackle_assists', 0) + S.get('def_tackles_with_assist', 0)),
                        'war': w.get('war')})
    for L in (skill, dfn):
        L.sort(key=lambda r: -r['pts'])
    out = {'season': y, 'week': G.get('week'), 'asof': G.get('asof'), 'skill': skill, 'defense': dfn}
    with open(os.path.join(ROOT, 'data', 'nfl_season_value.json'), 'w') as fh:
        json.dump(out, fh, separators=(',', ':'), allow_nan=False)
    print(f'nfl_season_value: {len(skill)} skill players ({MIN_SKILL}+ plays), {len(dfn)} defenders ({MIN_SNAPS}+ snaps), '
          f'{sum(r["war"] is not None for r in skill + dfn)} with WAR')


if __name__ == '__main__':
    main()
