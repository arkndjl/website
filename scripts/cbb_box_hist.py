#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Dated ESPN player box scores for past college basketball seasons, and a point-in-time player value built from them:
the board's second value path (the live path stays Barttorvik's lines; this one needs no Barttorvik file).

    python3 scripts/cbb_box_hist.py 2024            # build scripts/.cache/cbb/games_pit/2024.json.gz
    python3 scripts/cbb_box_hist.py 2014 2026       # a range of seasons
    python3 scripts/cbb_box_hist.py --test          # self-test of the walk-forward ratings (no network)

Source: the sportsdataverse (hoopR) release files of ESPN's box scores and play-by-play, one parquet a season
(player_box_YYYY.parquet 2003 on, play_by_play_YYYY.parquet for rim and dunk attempts), cached in
scripts/.cache/cbb/hoopr/.

Loaders (for any by-date research, awards included):
  frame(season)   the season's player-game rows as a pandas frame (date, game_id, athlete_id, team_id, box counts)
  boxes(season)   [{id, date 'YYYYMMDD', neutral, teams: {ESPN team id: {opp, loc, players: [box dict]}}}] in date
                  order; a player's box dict is the one cbb_espn_logs.box_from_espn builds (rim / dunk from the pbp)
  to_date(season, date)   {athlete_id: summed box line} from games before `date`

Point-in-time value: build(season) writes Barttorvik-shaped game rows (cbb_live.GCOLS + the ESPN event id) through
cbb_espn_logs.rows_for, the same proxy the live ESPN fill uses (data/cbb_espn_fit.json). The proxy's team and opponent
ratings are walk-forward: a ridge on the season's games before the game's date, shrunk toward half of last season's
final rating, so no row reads a result from its own day or later. Player ids are 'e<ESPN athlete id>'.
"""
import gzip, json, os, sys, time, urllib.request
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, '.cache', 'cbb', 'hoopr')
PIT = os.path.join(HERE, '.cache', 'cbb', 'games_pit')
HIST = os.path.join(HERE, 'data', 'cbb_games_hist.json.gz')
REL = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/'
BOX_URL = REL + 'espn_mens_college_basketball_player_boxscores/player_box_{}.parquet'
PBP_URL = REL + 'espn_mens_college_basketball_pbp/play_by_play_{}.parquet'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
RIM = {'layupshot', 'tipshot', 'dunkshot'}
RIM_SHARE, RIM_LIFT = 0.49, 1.18      # a game with no play-by-play: rim attempts as a share of twos, rim FG% over 2P%
LAM, CARRY = 2.0, 0.5                 # the ratings ridge and the weight on last season's final rating


def _get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(path + '.tmp', 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)
    os.replace(path + '.tmp', path)
    time.sleep(1)
    return path


_FRAME, _RIM, _BOX = {}, {}, {}


def frame(season):
    """player-game rows that logged minutes: one row a player a game"""
    if season in _FRAME: return _FRAME[season]
    import pandas as pd
    d = pd.read_parquet(_get(BOX_URL.format(season), os.path.join(RAW, f'player_box_{season}.parquet')))
    d = d[(d['minutes'].fillna(0) > 0) & ~d['did_not_play'].fillna(False).astype(bool)].copy()
    d = d[d['athlete_id'].notna() & d['team_id'].notna() & d['opponent_team_id'].notna()].drop_duplicates(['game_id', 'athlete_id'])
    d['date'] = pd.to_datetime(d['game_date']).dt.strftime('%Y%m%d')
    keep = ['date', 'game_id', 'season_type', 'athlete_id', 'athlete_display_name', 'athlete_position_abbreviation', 'team_id', 'team_location',
            'opponent_team_id', 'home_away', 'team_score', 'opponent_team_score', 'starter', 'minutes', 'points', 'field_goals_made',
            'field_goals_attempted', 'three_point_field_goals_made', 'three_point_field_goals_attempted', 'free_throws_made',
            'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'assists', 'turnovers', 'steals', 'blocks', 'fouls']
    _FRAME[season] = d[keep].sort_values(['date', 'game_id']).reset_index(drop=True)
    return _FRAME[season]


def rim_counts(season):
    """{(game_id, athlete_id): [rim made, rim att, dunk made, dunk att]} from the play-by-play; games with any shot row"""
    if season in _RIM: return _RIM[season]
    import pyarrow.parquet as pq
    out, games = defaultdict(lambda: [0, 0, 0, 0]), set()
    try:
        t = pq.read_table(_get(PBP_URL.format(season), os.path.join(RAW, f'pbp_{season}.parquet')),
                          columns=['game_id', 'type_text', 'scoring_play', 'athlete_id_1']).to_pandas()
    except Exception as e:  # noqa: BLE001
        print(f'cbb box hist: no play-by-play for {season} ({e}); rim attempts estimated')
        _RIM[season] = ({}, set())
        return _RIM[season]
    ty = t['type_text'].fillna('').str.lower().str.replace(' ', '')
    games = set(t.loc[ty.str.contains('shot'), 'game_id'].astype(int).unique())
    t = t[ty.isin(RIM) & t['athlete_id_1'].notna()]
    ty = ty[t.index]
    for gid, a, made, k in zip(t['game_id'].astype(int), t['athlete_id_1'].astype(int), t['scoring_play'].fillna(False).astype(bool), ty):
        z = out[(gid, a)]
        z[0] += made; z[1] += 1
        if k == 'dunkshot': z[2] += made; z[3] += 1
    _RIM[season] = (dict(out), games)
    return _RIM[season]


def boxes(season):
    if season in _BOX: return _BOX[season]
    d = frame(season)
    rim, shot_games = rim_counts(season)
    hist = {int(g['id']): g for g in json.load(gzip.open(HIST)) if g['season'] == season}
    n = lambda v: 0.0 if v is None or v != v else float(v)
    out = []
    for gid, rows in d.groupby('game_id', sort=False):
        gid = int(gid)
        h = hist.get(gid)
        teams = {}
        has_pbp = gid in shot_games
        for r in rows.itertuples(index=False):
            tid = str(int(r.team_id))
            t = teams.setdefault(tid, {'opp': str(int(r.opponent_team_id)), 'loc': 'N' if h and h.get('neutral') else ('H' if r.home_away == 'home' else 'A'),
                                       'pts': n(r.team_score), 'players': []})
            fgm, fga, tpm, tpa = n(r.field_goals_made), n(r.field_goals_attempted), n(r.three_point_field_goals_made), n(r.three_point_field_goals_attempted)
            two_m, two_a = fgm - tpm, fga - tpa
            if has_pbp:
                s = rim.get((gid, int(r.athlete_id)), (0, 0, 0, 0))
                rm, ra = min(float(s[0]), two_m), min(float(s[1]), two_a)
                dm, da = min(float(s[2]), rm), min(float(s[3]), ra)
            else:
                ra = RIM_SHARE * two_a
                rm = min(two_m, ra * min(1.0, RIM_LIFT * two_m / two_a)) if two_a else 0.0
                dm = da = 0.0
            t['players'].append({'pid': None, 'espn': str(int(r.athlete_id)), 'name': r.athlete_display_name, 'min': n(r.minutes), 'pts': n(r.points),
                                 'fgm': fgm, 'fga': fga, 'tpm': tpm, 'tpa': tpa, 'ftm': n(r.free_throws_made), 'fta': n(r.free_throws_attempted),
                                 'orb': n(r.offensive_rebounds), 'drb': n(r.defensive_rebounds), 'ast': n(r.assists), 'tov': n(r.turnovers),
                                 'stl': n(r.steals), 'blk': n(r.blocks), 'pf': n(r.fouls), 'rimm': rm, 'rima': ra, 'dunkm': dm, 'dunka': da,
                                 'pos': r.athlete_position_abbreviation, 'start': bool(r.starter)})
        if len(teams) != 2 or any(t['opp'] not in teams for t in teams.values()):
            continue
        out.append({'id': gid, 'date': rows['date'].iloc[0], 'neutral': bool(h and h.get('neutral')), 'pbp': has_pbp, 'teams': teams})
    out.sort(key=lambda g: (g['date'], g['id']))
    _BOX[season] = out
    return out


SUMK = ('min', 'pts', 'fgm', 'fga', 'tpm', 'tpa', 'ftm', 'fta', 'orb', 'drb', 'ast', 'tov', 'stl', 'blk', 'pf', 'rimm', 'rima', 'dunkm', 'dunka')


def to_date(season, date):
    """{ESPN athlete id: {'name', 'team', 'gp', sums}} over the season's games before `date` ('YYYYMMDD')"""
    out = {}
    for g in boxes(season):
        if g['date'] >= date: break
        for tid, t in g['teams'].items():
            for p in t['players']:
                o = out.setdefault(p['espn'], dict({k: 0.0 for k in SUMK}, name=p['name'], team=tid, gp=0))
                o['gp'] += 1; o['team'] = tid
                for k in SUMK: o[k] += p[k]
    return out


# ---------------------------------------------------------------- walk-forward team ratings
def _poss(g):
    ps = []
    for t in g['teams'].values():
        T = {k: sum(p[k] for p in t['players']) for k in ('fga', 'orb', 'tov', 'fta')}
        ps.append(T['fga'] - T['orb'] + T['tov'] + 0.475 * T['fta'])
    return max(40.0, sum(ps) / len(ps))


def margins(games):
    """[(date, team a, team b, site of a (+1 home, -1 away, 0 neutral), a's margin per 100 possessions)]"""
    out = []
    for g in games:
        a, b = list(g['teams'])
        ta, tb = g['teams'][a], g['teams'][b]
        pa = ta.get('pts') or sum(p['pts'] for p in ta['players'])
        pb = tb.get('pts') or sum(p['pts'] for p in tb['players'])
        out.append((g['date'], a, b, {'H': 1, 'A': -1}.get(ta['loc'], 0), (pa - pb) / _poss(g) * 100))
    return out


def solve(rows, prior, lam=LAM):
    """ridge net ratings (centred) from margin rows, shrunk toward prior[team]"""
    teams = sorted({r[1] for r in rows} | {r[2] for r in rows})
    if not teams: return {}
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    mu = np.array([prior.get(t, 0.0) for t in teams])
    X, y = np.zeros((len(rows), n + 1)), np.zeros(len(rows))
    for i, (_, a, b, l, m) in enumerate(rows):
        X[i, ix[a]], X[i, ix[b]], X[i, n] = 1, -1, l
        y[i] = m - (mu[ix[a]] - mu[ix[b]])
    w = np.linalg.solve(X.T @ X + np.eye(n + 1) * lam, X.T @ y)
    r = w[:n] + mu
    r -= r.mean()
    return {t: float(r[i]) for t, i in ix.items()}


_FINAL = {}


def final_ratings(season, keep=None):
    """a finished season's ratings from all its games (a prior for the next season only)"""
    if season not in _FINAL:
        try:
            ms = [m for m in margins(boxes(season)) if keep is None or (m[1] in keep and m[2] in keep)]
            _FINAL[season] = solve(ms, {})
        except Exception as e:  # noqa: BLE001
            print(f'cbb box hist: no {season} ratings ({e})')
            _FINAL[season] = {}
    return _FINAL[season]


def pregame_ratings(season, keep=None):
    """{date: {team: rating}} from games before that date, prior = CARRY x last season's final rating"""
    ms = [m for m in margins(boxes(season)) if keep is None or (m[1] in keep and m[2] in keep)]
    prior = {t: CARRY * v for t, v in final_ratings(season - 1, keep).items()}
    out, seen, i = {}, [], 0
    for d in sorted({m[0] for m in ms}):
        while i < len(ms) and ms[i][0] < d:
            seen.append(ms[i]); i += 1
        if seen:
            r = solve(seen, prior)
            out[d] = dict(prior, **r)
        else:
            out[d] = dict(prior)
    return out


# ---------------------------------------------------------------- Barttorvik-shaped point-in-time rows
def team_names():
    """ESPN team id -> Barttorvik name (cbb_games.bt_map), for the row shape the board's readers key on"""
    m = defaultdict(lambda: defaultdict(int))
    for g in json.load(gzip.open(HIST)):
        if 'hb' in g:
            m[g['home']][g['hb']] += 1; m[g['away']][g['ab']] += 1
    return {t: max(c, key=c.get) for t, c in m.items()}


def build(season, out_dir=PIT, names=None):
    import cbb_espn_logs as EL
    fit = json.load(open(EL.FIT))
    names = names or team_names()
    R = pregame_ratings(season, set(names))
    rows, n = [], 0
    for g in boxes(season):
        if any(t not in names for t in g['teams']):
            continue                                   # D-I against D-I only, as Barttorvik's logs
        b = {names[t]: {'opp': names[v['opp']], 'loc': v['loc'], 'players': v['players']} for t, v in g['teams'].items()}
        if len(b) != 2 or any(sum(p['min'] for p in t['players']) < 150 for t in b.values()):
            continue                                   # a partial box
        r = {names[t]: v for t, v in R.get(g['date'], {}).items() if t in names}
        rows += EL.rows_for(b, str(g['id']), g['date'], season, fit, lambda team, p: f"e{p['espn']}", r)
        n += 1
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f'{season}.json.gz')
    with gzip.open(p + '.tmp', 'wt') as fh:
        json.dump(rows, fh, separators=(',', ':'))
    os.replace(p + '.tmp', p)
    print(f'cbb box hist {season}: {n} games, {len(rows)} player rows -> {p}', flush=True)
    return p


def self_test():
    rows = [('20240101', 'a', 'b', 1, 10.0), ('20240102', 'b', 'c', 0, 5.0), ('20240103', 'a', 'c', -1, 12.0)]
    r = solve(rows, {})
    assert r['a'] > r['b'] > r['c'], r
    assert abs(sum(r.values())) < 1e-9
    r2 = solve(rows[:1], {'c': 5.0})
    assert 'c' not in r2 and r2['a'] > r2['b']
    r3 = solve([], {})
    assert r3 == {}
    print('cbb_box_hist self-test ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--test' in a:
        self_test()
    elif a:
        y0 = int(a[0]); y1 = int(a[1]) if len(a) > 1 else y0
        nm = team_names()
        for s in range(y0, y1 + 1):
            build(s, names=nm)
            _FRAME.pop(s - 1, None); _RIM.pop(s - 1, None); _BOX.pop(s - 2, None)
    else:
        print(__doc__)
