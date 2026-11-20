# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL QB leaderboard (layouts/shortcodes/nflqb.html) -> data/nfl_qb.json. Display only, nothing is fit here.

Rows = the game model's QB list (data/nfl_games.json qbs: 60+ plays this season or a listed start), with
  pts, val       game model QB term (Pts/G over a replacement QB, shrunk EPA/play rating), role, status
  war, waa       two-way WAR / WAA from static/data/nfl-war.json (scripts/nfl_war.py)
and this season's play-by-play line (nflverse pbp, regular season + playoffs, two-point tries left out):
  db    dropbacks (passes, sacks, scrambles)
  epa   EPA per dropback (qb_epa: the passer keeps the EPA of a catch-and-fumble)
  sr    success rate on dropbacks (EPA > 0)
  cpoe  completion % over expected (nflverse cp model), attempts with an air-yards spot
  anya  ANY/A = (pass yds + 20 TD - 45 INT - sack yds) / (att + sacks)
  sk    sack % = sacks / (att + sacks)
  adot  air yards per attempt
  int   INT % of attempts
  btt   big throws %: completions 10+ air yards at cp <= .45, per dropback (free proxy for a big-time throw;
        descriptive only: it failed as a forward driver, data/qb_btt_research.json)
  rush  EPA on QB runs (designed + scrambles, kneels out), season total
  aepa  opponent-adjusted EPA a play: each dropback and QB run less the defense's EPA allowed a play over the league's
        (its other games, shrunk with K_DEF = 300 plays). Split-half reliability 2021-26 (QB-seasons 250+ plays, alternate
        games): r .512 raw -> .528 adjusted (P better .91 of 1,000 boots); wind / cold / rain adjustments added nothing
        (.528 -> .529, P .57-.67) and are left out (/mnt/project-files/qb-season-metric/)
  spts  SV (season value): this season's points over a replacement QB (-0.12 EPA a play) a game played (10+ plays): sum(aepa - REPL) / games.
        Descriptive, this season only; pts (proj) is the game model's career-weighted term
Join: pbp by gsis id -> name + team (stats_player_week) -> scripts/names.py matcher against the QB list and the WAR board."""
import csv
import gzip
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names  # noqa: E402
from nfl_pbp import download  # noqa: E402

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
FR = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'JAC': 'JAX', 'LAR': 'LA'}


def get(name, url, fresh=True):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if fresh or not os.path.exists(p):
        try:
            download(url, p)
        except Exception as e:  # noqa: BLE001  keep the cached copy
            if not os.path.exists(p):
                raise
            print(f'nfl_qb: {name} not refreshed ({e}), using cache')
    return p


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


REPL, K_DEF = -0.12, 300      # replacement QB EPA a play (the game model's), defense prior in plays


def pbp_lines(y, fresh=True):
    S = defaultdict(lambda: defaultdict(float))
    D, DG, LG = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0]), [0.0, 0]   # EPA allowed by defense, by defense-game
    QP = defaultdict(list)                                                                # player -> [(game, defense, EPA)]
    with gzip.open(get(f'play_by_play_{y}.csv.gz', f'{REL}/pbp/play_by_play_{y}.csv.gz', fresh), 'rt', encoding='utf-8') as fh:
        rd = csv.reader(fh)
        h = next(rd); I = {k: i for i, k in enumerate(h)}
        g = lambda r, k: r[I[k]]  # noqa: E731
        for r in rd:
            if g(r, 'two_point_attempt') == '1' or g(r, 'season_type') not in ('REG', 'POST'):
                continue
            db = g(r, 'qb_dropback') == '1'
            run = g(r, 'play_type') == 'run' and not db and g(r, 'qb_kneel') != '1'
            if not db and not run:
                continue
            pid = g(r, 'id') if db else g(r, 'rusher_player_id')
            epa = f(g(r, 'qb_epa')) if db else f(g(r, 'epa'))
            dt, gid = FR.get(g(r, 'defteam'), g(r, 'defteam')), g(r, 'game_id')
            if epa is not None and g(r, 'qb_spike') != '1':
                for a_ in (D[dt], DG[(gid, dt)], LG): a_[0] += epa; a_[1] += 1
                if pid and pid != 'NA': QP[pid].append((gid, dt, epa))
            if not pid or pid == 'NA':
                continue
            A = S[pid]
            scr = g(r, 'qb_scramble') == '1'
            if run or scr:
                if epa is not None:
                    A['rush'] += epa
            if run:
                continue
            if g(r, 'qb_spike') == '1':
                continue
            A['db'] += 1
            if epa is not None:
                A['epa'] += epa; A['epan'] += 1
                A['succ'] += 1 if epa > 0 else 0
            sack = g(r, 'sack') == '1'
            att = g(r, 'pass_attempt') == '1' and not sack and not scr
            if sack:
                A['sk'] += 1; A['sky'] += -(f(g(r, 'yards_gained')) or 0)
            if att:
                A['att'] += 1
                A['py'] += f(g(r, 'passing_yards')) or 0
                A['td'] += 1 if g(r, 'pass_touchdown') == '1' else 0
                A['int'] += 1 if g(r, 'interception') == '1' else 0
                ay, cp, cpoe = f(g(r, 'air_yards')), f(g(r, 'cp')), f(g(r, 'cpoe'))
                if ay is not None:
                    A['ay'] += ay; A['ayn'] += 1
                if cpoe is not None:
                    A['cpoe'] += cpoe; A['cpn'] += 1
                if g(r, 'complete_pass') == '1' and ay is not None and ay >= 10 and cp is not None and cp <= .45:
                    A['btt'] += 1
    # this season's value: every QB play (dropbacks, his runs) less the defense's EPA allowed a play over the league's,
    # from its other games, shrunk with K_DEF plays; points over a replacement QB (REPL a play) a game played (10+ plays)
    m = LG[0] / LG[1] if LG[1] else 0.0
    for pid, L in QP.items():
        A = S[pid]; gp = defaultdict(int)
        for gid, dt, epa in L:
            sd, nd = D[dt]; sg, ng = DG[(gid, dt)]
            adj = epa - ((sd - sg) - m * (nd - ng)) / (nd - ng + K_DEF)
            A['aepa'] += adj; A['apl'] += 1; A['par'] += adj - REPL; gp[gid] += 1
        A['gp'] = sum(1 for v in gp.values() if v >= 10) or 1
    return S


def who(y, fresh=True):
    """gsis id -> (display name, latest team)."""
    out = {}
    with open(get(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv', fresh), newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            out[r['player_id']] = (r['player_display_name'], FR.get(r['team'], r['team']))
    return out


def line(A):
    att, db, ab = A['att'], A['db'], A['att'] + A['sk']
    r = lambda x, k=3: None if x is None else round(x, k)  # noqa: E731
    return {
        'db': int(db),
        'epa': r(A['epa'] / A['epan'] if A['epan'] else None),
        'sr': r(A['succ'] / A['epan'] if A['epan'] else None),
        'cpoe': r(A['cpoe'] / A['cpn'] if A['cpn'] else None, 1),
        'anya': r((A['py'] + 20 * A['td'] - 45 * A['int'] - A['sky']) / ab if ab else None, 2),
        'sk': r(A['sk'] / ab if ab else None),
        'adot': r(A['ay'] / A['ayn'] if A['ayn'] else None, 1),
        'int': r(A['int'] / att if att else None),
        'btt': r(A['btt'] / db if db else None),
        'rush': r(A['rush'], 1),
        'aepa': r(A['aepa'] / A['apl'] if A['apl'] else None),
        'spts': r(A['par'] / A['gp'] if A['apl'] else None, 1),
        'gp': int(A['gp']),
    }


def main():
    G = json.load(open(os.path.join(ROOT, 'data', 'nfl_games.json')))
    W = json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))
    y = int(G['season'])
    fresh = '--cache' not in sys.argv
    S, P = pbp_lines(y, fresh), who(y, fresh)
    war = [p for p in W['players'] if p.get('pos') == 'QB' or (p.get('two') or {}).get('p2') == 'QB']
    rows, miss = [], []
    for q in G['qbs']:
        t = q.get('t') or ''
        ids = [k for k, (n, tm) in P.items() if k in S and names.same(n, q['n']) and (tm == t or not t)]
        ids = ids or [k for k, (n, tm) in P.items() if k in S and names.same(n, q['n'])]
        ids.sort(key=lambda k: -S[k]['db'])
        wr = [p for p in war if names.same(p['n'], q['n']) and t in p['tm'].split('/')] or [p for p in war if names.same(p['n'], q['n'])]
        row = {'n': q['n'], 't': t, 'photo': q.get('photo'), 'pts': q.get('pts'), 'val': q.get('val'), 'plays': q.get('plays'),
               'role': q.get('role') or ('starter' if q.get('starter') else 'backup'), 'status': q.get('status')}
        if wr:
            row.update(war=wr[0].get('war'), waa=wr[0].get('waa'), age=wr[0].get('age'), pxp=wr[0].get('pxp'))
        if ids:
            row.update(line(S[ids[0]]))
        else:
            miss.append(q['n'])
        rows.append(row)
    rows.sort(key=lambda r: -(r['spts'] if r.get('spts') is not None else -99))
    out = {'season': y, 'week': G.get('week'), 'asof': G.get('asof'), 'rows': rows}
    with open(os.path.join(ROOT, 'data', 'nfl_qb.json'), 'w') as fh:
        json.dump(out, fh, separators=(',', ':'), allow_nan=False)
    print(f'nfl_qb: {len(rows)} QBs, {len(miss)} without a pbp line {miss}, {sum("war" in r for r in rows)} with WAR')


if __name__ == '__main__':
    main()
