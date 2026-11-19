#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Knicks finals and box scores for the season in progress, kept in the repo (data/knicks_games.json) so tools that
read only the repo get final scores. Data only; no page reads it. ESPN's scoreboard (scripts/nba_espn.py day(), cached)
gives the schedule; each final game's ESPN summary gives the line score and both teams' player lines. Final games never
change, so a game already in the file is not fetched again: the first run backfills the season, later runs add the
new finals. Stdlib only.

    python3 scripts/knicks_games.py            # this season (scripts/nba_xpm.py current_season())
    python3 scripts/knicks_games.py 2026       # season ending in 2026
    python3 scripts/knicks_games.py --test     # parser self-check on a stub summary

Schema: {"asof", "season", "team": "NY", "games": [ ... in tip order ]}, each game
    {"id", "date" (ET, YYYY-MM-DD), "tip" (UTC), "type" (2 regular, 3 playoffs, 5 play-in/cup final), "ha" ("home"/"away"),
     "opp", "ny", "op" (final points), "res" ("W"/"L"), "ot" (overtime periods), "q": {"NY": [...], opp: [...]} (points per period),
     "box": {"NY": [row...], opp: [row...]}}
    row = {"id" (ESPN athlete), "name", "st" (1 starter), "min", "pts", "reb", "ast", "stl", "blk", "tov", "pf",
           "oreb", "dreb", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "pm"}; a player who did not play has "dnp" (reason)
           and no stat keys.
"""
import datetime as dt, json, os, sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_espn  # noqa: E402

ROOT = nba_espn.ROOT
OUT = os.path.join(ROOT, 'data', 'knicks_games.json')
NY = 'NY'
ET = ZoneInfo('America/New_York')

# ESPN box columns by label (statistics[].labels / names) and by long key (statistics[].keys)
SINGLE = {'MIN': 'min', 'PTS': 'pts', 'REB': 'reb', 'AST': 'ast', 'STL': 'stl', 'BLK': 'blk', 'TO': 'tov', 'PF': 'pf',
          'OREB': 'oreb', 'DREB': 'dreb', '+/-': 'pm',
          'minutes': 'min', 'points': 'pts', 'rebounds': 'reb', 'assists': 'ast', 'steals': 'stl', 'blocks': 'blk',
          'turnovers': 'tov', 'fouls': 'pf', 'offensiveRebounds': 'oreb', 'defensiveRebounds': 'dreb', 'plusMinus': 'pm'}
PAIR = {'FG': ('fgm', 'fga'), '3PT': ('fg3m', 'fg3a'), 'FT': ('ftm', 'fta'),
        'fieldGoalsMade-fieldGoalsAttempted': ('fgm', 'fga'),
        'threePointFieldGoalsMade-threePointFieldGoalsAttempted': ('fg3m', 'fg3a'),
        'freeThrowsMade-freeThrowsAttempted': ('ftm', 'fta')}
ORDER = ['min', 'pts', 'reb', 'ast', 'stl', 'blk', 'tov', 'pf', 'oreb', 'dreb', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'pm']


def _int(s):
    try:
        return int(float(str(s).replace('+', '')))
    except (TypeError, ValueError):
        return None


def parse(j):
    """an ESPN summary -> {"q", "box", "ot", "pts"} or None when the game is not final"""
    if not j or 'boxscore' not in j:
        return None
    comp = ((j.get('header') or {}).get('competitions') or [{}])[0]
    if not ((comp.get('status') or {}).get('type') or {}).get('completed'):
        return None
    q, pts = {}, {}
    for c in comp.get('competitors', []):
        ab = nba_espn.team((c.get('team') or {}).get('abbreviation', ''))
        q[ab] = [_int(x.get('displayValue', x.get('value'))) for x in c.get('linescores', [])]
        pts[ab] = _int(c.get('score'))
    box = {}
    for t in j['boxscore'].get('players', []):
        ab = nba_espn.team(t['team']['abbreviation'])
        rows = []
        for st in t.get('statistics', [])[:1]:
            cols = st.get('labels') or st.get('names') or st.get('keys') or []
            for p in st.get('athletes', []):
                a = p.get('athlete', {})
                r = {'id': a.get('id'), 'name': a.get('displayName'), 'st': 1 if p.get('starter') else 0}
                vals = p.get('stats') or []
                if p.get('didNotPlay') or not vals:
                    r['dnp'] = p.get('reason') or 'DNP'
                    rows.append(r)
                    continue
                s = {}
                for c, v in zip(cols, vals):
                    if c in SINGLE:
                        s[SINGLE[c]] = _int(v)
                    elif c in PAIR:
                        mk = str(v).split('-')
                        if len(mk) == 2:
                            s[PAIR[c][0]], s[PAIR[c][1]] = _int(mk[0]), _int(mk[1])
                r.update({k: s[k] for k in ORDER if k in s})
                rows.append(r)
        box[ab] = rows
    n = max((len(v) for v in q.values()), default=4)
    return {'q': q, 'box': box, 'ot': max(0, n - 4), 'pts': pts}


def game_row(g, b):
    home = g['h'] == NY
    opp = g['a'] if home else g['h']
    ny, op = (g['hs'], g['as']) if home else (g['as'], g['hs'])
    ny, op = b['pts'].get(NY) or ny, b['pts'].get(opp) or op
    tip = dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00'))
    return {'id': g['id'], 'date': tip.astimezone(ET).date().isoformat(), 'tip': g['tip'], 'type': g['type'],
            'ha': 'home' if home else 'away', 'opp': opp, 'ny': ny, 'op': op, 'res': 'W' if ny > op else 'L',
            'ot': b['ot'], 'q': {NY: b['q'].get(NY, []), opp: b['q'].get(opp, [])},
            'box': {NY: b['box'].get(NY, []), opp: b['box'].get(opp, [])}}


def build(S):
    old = {}
    try:
        prev = json.load(open(OUT))
        if prev.get('season') == S:
            old = {g['id']: g for g in prev.get('games', [])}
    except (OSError, ValueError):
        pass
    today = dt.date.today()
    sched = [g for g in nba_espn.games(S, fresh_after=today - dt.timedelta(days=2))
             if NY in (g['h'], g['a']) and g['final']]
    out, miss = [], 0
    for g in sched:
        if g['id'] in old:
            out.append(old[g['id']]); continue
        b = parse(nba_espn.get(f"{nba_espn.SITE}/summary?event={g['id']}"))
        if b is None:
            miss += 1; continue
        out.append(game_row(g, b))
    out.sort(key=lambda g: (g['tip'], g['id']))
    if [g['id'] for g in out] == sorted(old, key=lambda i: (old[i]['tip'], i)) and old:
        print(f'knicks games: {len(out)} finals, nothing new')
        return
    doc = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'season': S, 'team': NY, 'games': out}
    nba_espn.save(OUT, doc)
    w = sum(g['res'] == 'W' for g in out)
    print(f'knicks games: {len(out)} finals ({w}-{len(out) - w}), {len(out) - len(old)} new, {miss} summaries missing')


def _test():
    stub = {'header': {'competitions': [{'status': {'type': {'completed': True}}, 'competitors': [
        {'team': {'abbreviation': 'NY'}, 'score': '112', 'linescores': [{'displayValue': '30'}, {'displayValue': '25'},
                                                                         {'displayValue': '27'}, {'displayValue': '22'}, {'displayValue': '8'}]},
        {'team': {'abbreviation': 'BOS'}, 'score': '108', 'linescores': [{'displayValue': '28'}] * 4 + [{'displayValue': '-4'}]}]}]},
        'boxscore': {'players': [{'team': {'abbreviation': 'NY'}, 'statistics': [{
            'labels': ['MIN', 'PTS', 'FG', '3PT', 'FT', 'REB', 'AST', 'TO', 'STL', 'BLK', 'OREB', 'DREB', 'PF', '+/-'],
            'athletes': [{'athlete': {'id': '1', 'displayName': 'A B'}, 'starter': True,
                          'stats': ['38', '31', '11-20', '3-7', '6-6', '4', '9', '2', '1', '0', '1', '3', '2', '+7']},
                         {'athlete': {'id': '2', 'displayName': 'C D'}, 'didNotPlay': True, 'reason': 'COACH\'S DECISION', 'stats': []}]}]}]}}
    b = parse(stub)
    r = b['box']['NY'][0]
    assert r['pts'] == 31 and r['fgm'] == 11 and r['fga'] == 20 and r['fg3a'] == 7 and r['pm'] == 7 and r['st'] == 1, r
    assert b['box']['NY'][1] == {'id': '2', 'name': 'C D', 'st': 0, 'dnp': "COACH'S DECISION"}
    assert b['ot'] == 1 and b['q']['NY'][-1] == 8
    g = game_row({'id': '9', 'tip': '2026-11-19T00:30Z', 'type': 2, 'h': 'BOS', 'a': 'NY', 'hs': 0, 'as': 0}, b)
    assert g['date'] == '2026-11-18' and g['ha'] == 'away' and g['opp'] == 'BOS' and g['ny'] == 112 and g['res'] == 'W', g
    assert parse({'header': {'competitions': [{'status': {'type': {'completed': False}}}]}, 'boxscore': {}}) is None
    print('knicks_games: ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        _test()
    else:
        import nba_xpm
        build(int(sys.argv[1]) if len(sys.argv) > 1 else nba_xpm.current_season())
