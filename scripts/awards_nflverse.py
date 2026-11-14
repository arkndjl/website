# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""nflverse weekly player lines for the award races: every player's regular-season line by week (offence and defence),
team records by week and rookie seasons. Past seasons feed the voter fits (scripts/awards_more.py) and the as-of
backtest (scripts/awards_asof.py); the season in progress feeds the live rookie-defender pool (scripts/awards.py).
Files are cached in scripts/.cache/awards/asof/nfl. Stdlib only."""
import collections, csv, os, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'awards', 'asof')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'


def get(url, tries=4):
    for a in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=120).read()
        except Exception as e:
            print(url[:90], e, flush=True); time.sleep(5 * (a + 1))
    return None


NFLV = 'https://github.com/nflverse/nflverse-data/releases/download/'
TEAM_FIX = {'STL': 'LA', 'SD': 'LAC', 'OAK': 'LV'}


def nfl_file(name, url, fresh=False):
    fn = os.path.join(CACHE, 'nfl', name)
    if fresh or not os.path.exists(fn) or os.path.getsize(fn) < 1000:
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        d = get(url)
        if d and len(d) > 1000: open(fn, 'wb').write(d)
    if not os.path.exists(fn): return []
    return list(csv.DictReader(open(fn, encoding='utf-8')))


def nfl_weekly(S, fresh=False):
    """[(player id, name, position, team, week, stat dict)] regular season: offence and defence lines merged"""
    num = lambda r, k: float(r.get(k) or 0)
    out = {}
    def add(r, team, d):
        k = (r['player_id'], int(r['week']))
        x = out.setdefault(k, {'id': r['player_id'], 'n': r['player_display_name'], 'pos': r['position'],
                               'grp': r['position_group'], 'tm': TEAM_FIX.get(team, team), 'wk': int(r['week'])})
        for a, b in d.items(): x[a] = x.get(a, 0.0) + b
    off = lambda r, it: {'pass_y': num(r, 'passing_yards'), 'rush_y': num(r, 'rushing_yards'), 'rec_y': num(r, 'receiving_yards'),
                         'ptd': num(r, 'passing_tds'), 'rtd': num(r, 'rushing_tds'), 'ctd': num(r, 'receiving_tds'),
                         'std': num(r, 'special_teams_tds'), 'int': num(r, it)}
    dfn = lambda r: {'sacks': num(r, 'def_sacks'), 'dint': num(r, 'def_interceptions'), 'tfl': num(r, 'def_tackles_for_loss'),
                     'pd': num(r, 'def_pass_defended'), 'ff': num(r, 'def_fumbles_forced'), 'dtd': num(r, 'def_tds'),
                     'qbh': num(r, 'def_qb_hits'),
                     'tackles': num(r, 'def_tackles_solo') + num(r, 'def_tackle_assists')}
    if S >= 2025:
        for r in nfl_file(f'spw_{S}.csv', NFLV + f'stats_player/stats_player_week_{S}.csv', fresh):
            if r['season_type'] != 'REG': continue
            add(r, r['team'], dict(off(r, 'passing_interceptions'), **dfn(r)))
    else:
        for r in nfl_file(f'ps_{S}.csv', NFLV + f'player_stats/player_stats_{S}.csv'):
            if r['season_type'] == 'REG': add(r, r['recent_team'], off(r, 'interceptions'))
        for r in nfl_file(f'psd_{S}.csv', NFLV + f'player_stats/player_stats_def_{S}.csv'):
            if r['season_type'] == 'REG': add(r, r['team'], dfn(r))
    return list(out.values())


def nfl_games(last=2025):
    out = collections.defaultdict(list)
    for g in nfl_file('games.csv', 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'):
        if g['game_type'] != 'REG' or not g['home_score'] or g['home_score'] == 'NA': continue
        S = int(g['season'])
        if S > last: continue
        out[S].append((int(g['week']), TEAM_FIX.get(g['home_team'], g['home_team']), TEAM_FIX.get(g['away_team'], g['away_team']),
                       int(g['home_score']), int(g['away_score'])))
    return out


NFL_Z = ('pass_y', 'rush_y', 'rec_y', 'ptd', 'rtd', 'ctd', 'std', 'int', 'sacks', 'dint', 'tfl', 'pd', 'ff', 'dtd', 'qbh', 'tackles')
OFF_GRP = {'QB', 'RB', 'WR', 'TE'}
DEF_GRP = {'DL', 'LB', 'DB'}


def nfl_totals(W, wk, rook, S):
    """season-to-week totals a player in the live feature names"""
    out = {}
    for x in W:
        if x['wk'] > wk: continue
        r = out.setdefault(x['id'], {'id': x['id'], 'n': x['n'], 'pos': x['pos'], 'grp': x['grp'], 'tid': x['tm'], 'gp': 0,
                                     **{k: 0.0 for k in NFL_Z}})
        r['gp'] += 1; r['tid'] = x['tm']
        for k in NFL_Z: r[k] += x.get(k, 0.0)
    for r in out.values():
        r['scrim'] = r['rush_y'] + r['rec_y']; r['yds'] = r['pass_y'] + r['scrim']
        r['td'] = r['ptd'] + r['rtd'] + r['ctd'] + r['std']
        r['qb'] = 1.0 if r['pos'] == 'QB' else 0.0
        r['def'] = 1.0 if r['grp'] in DEF_GRP else 0.0
        r['off'] = r['grp'] in OFF_GRP
        r['rookie'] = rook.get(r['id']) == S
    return out


def nfl_records(games, wk):
    T = collections.defaultdict(lambda: [0.0, 0])
    for w, h, a, hs, as_ in games:
        if w > wk: continue
        T[h][0] += 1 if hs > as_ else (.5 if hs == as_ else 0); T[h][1] += 1
        T[a][0] += 1 if as_ > hs else (.5 if hs == as_ else 0); T[a][1] += 1
    return T


def rookies():
    """{gsis id: (rookie season, draft round or None)}"""
    out = {}
    for r in nfl_file('players.csv', NFLV + 'players/players.csv'):
        if (r.get('rookie_season') or '').isdigit():
            out[r['gsis_id']] = (int(r['rookie_season']), int(r['draft_round']) if (r.get('draft_round') or '').isdigit() else None)
    return out
