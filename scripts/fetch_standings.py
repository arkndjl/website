#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Standings page data: what has happened, no model numbers.

    python3 scripts/fetch_standings.py        # writes data/standings.json (only when something changed)

Every sport on ARKBOARD from ESPN's public site API: standings tables (NFL/NHL divisions, NBA conferences, CFB FBS and
CBB D-I conferences, 18 soccer leagues + MLS + the UEFA league phases), the playoff picture as it stands (seeds and
first-round pairs by each league's format), official stat leaders, AP/Coaches/CFP polls, ATP/WTA rankings, and
recent scores + upcoming games. CS2's Valve ranking is read from data/cs2.json by the template.
Run by the odds-snap workflow (about every 30 minutes). A source that fails keeps its last good copy.
"""
import datetime
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'standings.json')
ET = ZoneInfo('America/New_York')
SITE = 'https://site.api.espn.com/apis/site/v2/sports/'
STAND = 'https://site.api.espn.com/apis/v2/sports/'
LEAD = 'https://site.api.espn.com/apis/site/v3/sports/'

SOCCER = [('eng.1', 'Premier League'), ('esp.1', 'La Liga'), ('ger.1', 'Bundesliga'), ('ita.1', 'Serie A'),
          ('fra.1', 'Ligue 1'), ('ned.1', 'Eredivisie'), ('por.1', 'Primeira Liga'), ('bel.1', 'Belgian Pro League'),
          ('tur.1', 'Süper Lig'), ('cze.1', 'Czech First League'), ('gre.1', 'Greek Super League'),
          ('pol.1', 'Ekstraklasa'), ('den.1', 'Danish Superliga'), ('sui.1', 'Swiss Super League'),
          ('nor.1', 'Eliteserien'), ('aut.1', 'Austrian Bundesliga'), ('sco.1', 'Scottish Premiership'),
          ('swe.1', 'Allsvenskan'), ('usa.1', 'MLS'), ('uefa.champions', 'Champions League'),
          ('uefa.europa', 'Europa League'), ('uefa.europa.conf', 'Conference League')]

# leaders: (key, ESPN path, query, [(category, label)])
LEADERS = [
    ('nfl', 'football/nfl', '', [('passingYards', 'Passing yards'), ('passingTouchdowns', 'Passing TD'),
     ('quarterbackRating', 'Passer rating'), ('rushingYards', 'Rushing yards'), ('rushingTouchdowns', 'Rushing TD'),
     ('receivingYards', 'Receiving yards'), ('receptions', 'Receptions'), ('receivingTouchdowns', 'Receiving TD'),
     ('sacks', 'Sacks'), ('totalTackles', 'Tackles'), ('interceptions', 'Interceptions'),
     ('passesDefended', 'Passes defended')]),
    ('cfb', 'football/college-football', 'group=80', [('passingYards', 'Passing yards'),
     ('passingTouchdowns', 'Passing TD'), ('rushingYards', 'Rushing yards'), ('rushingTouchdowns', 'Rushing TD'),
     ('receivingYards', 'Receiving yards'), ('receptions', 'Receptions'), ('receivingTouchdowns', 'Receiving TD'),
     ('sacks', 'Sacks'), ('totalTackles', 'Tackles'), ('interceptions', 'Interceptions')]),
    ('nba', 'basketball/nba', '', [('pointsPerGame', 'Points'), ('reboundsPerGame', 'Rebounds'),
     ('assistsPerGame', 'Assists'), ('stealsPerGame', 'Steals'), ('blocksPerGame', 'Blocks'),
     ('3PointsMadePerGame', '3PM'), ('fieldGoalPercentage', 'FG%'), ('3PointPct', '3P%'),
     ('FreeThrowPct', 'FT%'), ('minutesPerGame', 'Minutes'), ('doubleDouble', 'Double-doubles')]),
    ('cbb', 'basketball/mens-college-basketball', '', [('pointsPerGame', 'Points'), ('reboundsPerGame', 'Rebounds'),
     ('assistsPerGame', 'Assists'), ('stealsPerGame', 'Steals'), ('blocksPerGame', 'Blocks'),
     ('3PointsMadePerGame', '3PM'), ('fieldGoalPercentage', 'FG%'), ('3PointPct', '3P%')]),
    ('nhl', 'hockey/nhl', '', [('points', 'Points'), ('goals', 'Goals'), ('assists', 'Assists'),
     ('plusMinus', '+/-'), ('penaltyMinutes', 'PIM'), ('wins', 'Goalie wins'), ('savePct', 'Save %'),
     ('avgGoalsAgainst', 'GAA'), ('shutouts', 'Shutouts')]),
]
N_LEAD = 10

# scores: (key, ESPN path, query, days back, days ahead); NFL and CFB by week instead
SCORES = [('nba', 'basketball/nba', '', 2, 2), ('nhl', 'hockey/nhl', '', 2, 2),
          ('cbb', 'basketball/mens-college-basketball', 'groups=50&limit=400', 1, 1)]


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net standings'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def logo(team, size=40):
    """ESPN's full-colour logo, small (the combiner resizes server side)."""
    href = team.get('logo') or next((l['href'] for l in team.get('logos') or [] if 'default' in (l.get('rel') or [])),
                                    None) or next((l['href'] for l in team.get('logos') or []), None)
    if not href or 'espncdn.com/' not in href:
        return href
    path = href.split('espncdn.com', 1)[1]
    return f'https://a.espncdn.com/combiner/i?img={path}&w={size}&h={size}'


def stats(entry):
    """type -> displayValue for the entry's top-level stats (types with _ are splits)."""
    out = {}
    for s in entry.get('stats', []):
        k = (s.get('type') or s.get('name') or '').lower()
        if k and k not in out:
            out[k] = s.get('displayValue')
            out[k + '#'] = s.get('value')
    return out


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def groups_of(node, depth):
    """Leaf groups with standings entries."""
    if node.get('standings', {}).get('entries'):
        return [node]
    out = []
    for c in node.get('children', []):
        out += groups_of(c, depth + 1)
    return out


def team_row(e, cols, z=None, zn=None):
    t = e['team']
    return {'n': t.get('shortDisplayName') or t.get('displayName'), 'full': t.get('displayName'),
            'ab': t.get('abbreviation'), 'logo': logo(t), 'v': cols, **({'z': z} if z else {}), **({'zn': zn} if zn else {})}


# ---------------------------------------------------------------- standings tables
def us_tables():
    out, seeds = {}, {}
    # NFL: divisions
    d = get(STAND + 'football/nfl/standings?level=3')
    groups = []
    for g in groups_of(d, 0):
        rows = []
        for e in sorted(g['standings']['entries'], key=lambda e: (-num(stats(e).get('winpercent#')), num(stats(e).get('playoffseed#'), 99))):
            s = stats(e)
            rows.append(team_row(e, [s.get('wins'), s.get('losses'), s.get('ties'), s.get('winpercent'), s.get('vsdiv'),
                                     s.get('vsconf'), s.get('home'), s.get('road'), s.get('pointsfor'),
                                     s.get('pointsagainst'), s.get('differential'), s.get('streak')]))
        groups.append({'name': g['name'], 'rows': rows})
    out['nfl'] = {'title': 'NFL standings', 'cols': ['W', 'L', 'T', 'PCT', 'Div', 'Conf', 'Home', 'Road', 'PF', 'PA', 'Diff', 'Strk'],
                  'groups': groups}
    d = get(STAND + 'football/nfl/standings')
    seeds['nfl'] = [{'name': g['name'], 'rows': [dict(team_row(e, [stats(e).get('total')]), s=int(num(stats(e).get('playoffseed#'))))
                    for e in g['standings']['entries']]} for g in groups_of(d, 0)]

    # NBA: conferences
    d = get(STAND + 'basketball/nba/standings')
    groups, nba_seeds = [], []
    for g in groups_of(d, 0):
        ents = sorted(g['standings']['entries'], key=lambda e: num(stats(e).get('playoffseed#'), 99))
        rows = []
        for e in ents:
            s = stats(e)
            sd = int(num(s.get('playoffseed#')))
            rows.append(team_row(e, [s.get('wins'), s.get('losses'), s.get('winpercent'), s.get('gamesbehind'), s.get('home'),
                                     s.get('road'), s.get('vsconf'), s.get('lasttengames'), s.get('avgpointsfor'),
                                     s.get('avgpointsagainst'), s.get('differential'), s.get('streak')],
                                 z=1 if sd <= 6 else 2 if sd <= 10 else None))
        groups.append({'name': g['name'], 'rows': rows})
        nba_seeds.append({'name': g['name'], 'rows': [dict(team_row(e, [stats(e).get('total')]), s=int(num(stats(e).get('playoffseed#')))) for e in ents]})
    out['nba'] = {'title': 'NBA standings', 'cols': ['W', 'L', 'PCT', 'GB', 'Home', 'Road', 'Conf', 'L10', 'PPG', 'Opp', 'Diff', 'Strk'],
                  'groups': groups, 'zones': [{'z': 1, 'd': 'playoffs (1-6)'}, {'z': 2, 'd': 'play-in (7-10)'}]}
    seeds['nba'] = nba_seeds

    # NHL: divisions, ordered by ESPN's conference seed (points, then the tiebreaks)
    d = get(STAND + 'hockey/nhl/standings?level=3')
    groups, conf = [], {}
    for confnode in d.get('children', []):
        for g in groups_of(confnode, 0):
            ents = sorted(g['standings']['entries'], key=lambda e: num(stats(e).get('playoffseed#'), 99))
            rows = []
            for e in ents:
                s = stats(e)
                rows.append(team_row(e, [s.get('gamesplayed'), s.get('wins'), s.get('losses'), s.get('otlosses'), s.get('points'),
                                         s.get('regwins'), s.get('pointsfor'), s.get('pointsagainst'), s.get('pointdifferential'),
                                         s.get('home'), s.get('road'), (s.get('lasttengames') or '').split(',')[0], s.get('streak')]))
            groups.append({'name': g['name'], 'rows': rows})
            conf.setdefault(confnode['name'], []).append((g['name'], ents))
    out['nhl'] = {'title': 'NHL standings', 'cols': ['GP', 'W', 'L', 'OTL', 'PTS', 'RW', 'GF', 'GA', 'Diff', 'Home', 'Road', 'L10', 'Strk'],
                  'groups': groups}
    seeds['nhl'] = conf
    return out, seeds


def college_tables(path, q, key, title):
    d = get(STAND + path + '/standings' + (('?' + q) if q else ''))
    groups = []
    for g in groups_of(d, 0):
        ents = sorted(g['standings']['entries'], key=lambda e: num(stats(e).get('playoffseed#'), 99) or 99)
        rows = []
        for e in ents:
            s = stats(e)
            rows.append(team_row(e, [s.get('vsconf'), s.get('total'), s.get('home') or s.get('homerecord'),
                                     s.get('road') or s.get('awayrecord'), s.get('vsaprankedteams'),
                                     s.get('pointsfor'), s.get('pointsagainst'), s.get('streak')]))
        groups.append({'name': g.get('name'), 'rows': rows})
    return {'title': title, 'cols': ['Conf', 'Overall', 'Home', 'Away', 'vs AP', 'PF', 'PA', 'Strk'], 'groups': groups}


def soccer_table(lg, name):
    try:
        d = get(STAND + f'soccer/{lg}/standings')
    except Exception:
        d = {}
    if not groups_of(d, 0):
        return soccer_table_results(lg, name)
    groups, zones = [], {}
    for g in groups_of(d, 0):
        rows = []
        for e in sorted(g['standings']['entries'], key=lambda e: num(stats(e).get('rank#'), 99)):
            s = stats(e)
            z = None
            note = e.get('note') or {}
            if note.get('description'):
                z = zones.setdefault(note['description'], len(zones) + 1)
            rows.append(team_row(e, [s.get('rank'), s.get('gamesplayed'), s.get('wins'), s.get('ties'), s.get('losses'),
                                     s.get('pointsfor'), s.get('pointsagainst'), s.get('pointdifferential'), s.get('points')],
                                 z=min(z, 6) if z else None))
        gname = g.get('name') or ''
        groups.append({'name': '' if gname.startswith('20') or len(groups_of(d, 0)) == 1 else gname, 'rows': rows})
    return {'title': name, 'cols': ['#', 'GP', 'W', 'D', 'L', 'GF', 'GA', 'GD', 'Pts'], 'groups': groups,
            'zones': [{'z': min(z, 6), 'd': k} for k, z in zones.items()], 'rankcol': True}


def soccer_table_results(lg, name):
    """ESPN has no current table for a few leagues (Czechia, Poland, Switzerland, Nov 2026): the table from the results
    the soccer build already pulls (data/soccer_games.json leagues[lg].teams: played, record, goals, points only)."""
    with open(os.path.join(ROOT, 'data', 'soccer_games.json')) as f:
        L = json.load(f)['leagues'][lg]
    ts = sorted(L['teams'], key=lambda t: (-t['pts'], -t['gd'], -t.get('gf', 0), t['n']))
    rows = []
    for i, t in enumerate(ts):
        w, dr, l = (t['rec'].split('-') + ['', '', ''])[:3]
        gf = t.get('gf')
        rows.append({'n': t['n'], 'full': t['n'], 'ab': t.get('ab'), 'logo': f"/img/soccer/{t['id']}.png",
                     'v': [str(i + 1), str(t['gp']), w, dr, l, str(gf) if gf is not None else None,
                           str(gf - t['gd']) if gf is not None else None, f"{t['gd']:+d}" if t['gd'] else '0', str(t['pts'])]})
    return {'title': name, 'cols': ['#', 'GP', 'W', 'D', 'L', 'GF', 'GA', 'GD', 'Pts'], 'groups': [{'name': '', 'rows': rows}],
            'zones': [], 'rankcol': True, 'src': 'results'}


# ---------------------------------------------------------------- playoff picture
def picture(seeds):
    out = {}
    # NFL: 7 a conference, 1 has the bye; 2-7, 3-6, 4-5
    confs = []
    for c in seeds['nfl']:
        rows = sorted([r for r in c['rows'] if 1 <= r['s']], key=lambda r: r['s'])
        top = rows[:7]
        by = {r['s']: r for r in top}
        confs.append({'name': c['name'], 'seeds': top, 'out': rows[7:10], 'bye': [by[1]] if 1 in by else [],
                      'pairs': [[by[a], by[b]] for a, b in ((2, 7), (3, 6), (4, 5)) if a in by and b in by]})
    out['nfl'] = {'title': 'NFL playoff picture', 'note': 'seeds 1-4 division leaders, 5-7 wild cards; the 1 seed has the bye; first 3 out below', 'confs': confs}
    # NBA: 1-6 in, 7-10 play-in; 1 v 8, 2 v 7, 3 v 6, 4 v 5 after the play-in
    confs = []
    for c in seeds['nba']:
        rows = sorted([r for r in c['rows'] if r['s'] >= 1], key=lambda r: r['s'])
        by = {r['s']: r for r in rows}
        confs.append({'name': c['name'], 'seeds': rows[:6], 'playin': rows[6:10],
                      'pairs': [[by[a], by[b]] for a, b in ((3, 6), (4, 5)) if a in by and b in by],
                      'pin': [[by[a], by[b]] for a, b in ((7, 8), (9, 10)) if a in by and b in by],
                      'note': '1 and 2 meet the play-in winners'})
    out['nba'] = {'title': 'NBA playoff picture', 'note': '1-6 in, 7-10 play-in (7 v 8 for the 7 seed; its loser v the 9/10 winner for the 8)', 'confs': confs}
    # NHL: top 3 in each division + 2 wild cards a conference; division winner with more points v WC2
    confs = []
    for cname, divs in seeds['nhl'].items():
        tops, rest = [], []
        for dname, ents in divs:
            for i, e in enumerate(ents):
                s = stats(e)
                r = dict(team_row(e, [s.get('total', '').split(',')[0], s.get('points')]), s=int(num(s.get('playoffseed#'))),
                         div=dname.replace(' Division', ''), dpos=i + 1)
                (tops if i < 3 else rest).append(r)
        rest.sort(key=lambda r: r['s'])
        wc = rest[:2]
        for i, r in enumerate(wc):
            r['wc'] = i + 1
        d1 = [r for r in tops if r['dpos'] == 1]
        d1.sort(key=lambda r: r['s'])
        pairs = []
        if len(d1) == 2 and len(wc) == 2:
            pairs.append([d1[0], wc[1]])
            pairs.append([next(r for r in tops if r['div'] == d1[0]['div'] and r['dpos'] == 2),
                          next(r for r in tops if r['div'] == d1[0]['div'] and r['dpos'] == 3)])
            pairs.append([d1[1], wc[0]])
            pairs.append([next(r for r in tops if r['div'] == d1[1]['div'] and r['dpos'] == 2),
                          next(r for r in tops if r['div'] == d1[1]['div'] and r['dpos'] == 3)])
        confs.append({'name': cname, 'pairs': pairs, 'out': rest[2:5]})
    out['nhl'] = {'title': 'NHL playoff picture', 'note': 'top 3 in each division + 2 wild cards; the division winner with more points meets WC2', 'confs': confs}
    return out


# ---------------------------------------------------------------- leaders
def leaders(key, path, q, cats):
    d = get(LEAD + path + '/leaders' + ('?' + q if q else '?limit=15'))   # CFB's group=80 500s with a limit
    by = {c['name']: c for c in d['leaders']['categories']}
    out = []
    for name, label in cats:
        c = by.get(name)
        if not c:
            continue
        rows = []
        for l in c.get('leaders', [])[:N_LEAD]:
            a, t = l.get('athlete', {}), l.get('team') or {}
            rows.append({'n': a.get('displayName'), 'pos': (a.get('position') or {}).get('abbreviation'),
                         't': t.get('abbreviation'), 'tl': logo(t, 24) if t else None, 'v': l.get('displayValue')})
        if rows:
            out.append({'name': label, 'rows': rows})
    yr = d.get('requestedSeason') or {}
    return {'cats': out, 'season': yr.get('displayName') if isinstance(yr, dict) else None}


def soccer_leaders(lg):
    d = get(SITE + f'soccer/{lg}/statistics')
    out = []
    for c in d.get('stats', []):
        label = {'goalsLeaders': 'Goals', 'assistsLeaders': 'Assists'}.get(c.get('name'))
        if not label:
            continue
        rows = []
        for l in c.get('leaders', [])[:N_LEAD]:
            a = l.get('athlete', {})
            t = a.get('team') or {}
            dv = l.get('shortDisplayValue') or l.get('displayValue') or ''
            gp = dv.split(',')[0].replace('M:', '').strip() if 'M:' in dv else None
            rows.append({'n': a.get('displayName'), 't': t.get('abbreviation') or t.get('shortDisplayName') or t.get('name'),
                         'tl': logo(t, 24) if t else None, 'v': str(int(num(l.get('value')))), 'gp': gp})
        out.append({'name': label, 'rows': rows})
    return {'cats': out}


# ---------------------------------------------------------------- polls and rankings
def polls(path):
    d = get(SITE + path + '/rankings')
    out = []
    for r in d.get('rankings', []):
        name = r.get('name') or ''
        if not any(k in name for k in ('AP Top 25', 'Coaches', 'Playoff')) or any(k in name for k in ('FCS', 'Division', 'Div ')):
            continue
        rows = []
        for x in r.get('ranks', []):
            t = x.get('team') or {}
            rec = (x.get('recordSummary') or '')
            rows.append({'rk': x.get('current'), 'prev': x.get('previous'), 'n': t.get('location') or t.get('nickname'),
                         'logo': logo(t), 'rec': rec, 'pts': int(num(x.get('points'))) or None,
                         'fpv': x.get('firstPlaceVotes') or None})
        lbl = 'CFP ranking' if 'Playoff' in name else 'AP' if 'AP' in name else 'Coaches'
        out.append({'name': lbl, 'date': (r.get('headline') or r.get('shortHeadline') or ''), 'rows': rows})
    order = {'CFP ranking': 0, 'AP': 1, 'Coaches': 2}
    return sorted(out, key=lambda p: order.get(p['name'], 9))


def tennis(tour):
    d = get(SITE + f'tennis/{tour}/rankings')
    r = d['rankings'][0]
    rows = []
    for x in r.get('ranks', [])[:100]:
        a = x.get('athlete') or {}
        rows.append({'rk': x.get('current'), 'prev': x.get('previous'), 'n': a.get('displayName'),
                     'c': a.get('citizenshipCountry') or a.get('flagAltText'), 'pts': int(num(x.get('points')))})
    return {'title': f'{tour.upper()} ranking', 'date': (r.get('update') or '')[:10], 'rows': rows}


# ---------------------------------------------------------------- scores and schedule
def game(e):
    c = e['competitions'][0]
    st = e.get('status', {}).get('type', {})
    side = {}
    for t in c.get('competitors', []):
        tm = t.get('team', {})
        rk = (t.get('curatedRank') or {}).get('current')
        side[t.get('homeAway')] = {'n': tm.get('shortDisplayName') or tm.get('displayName'), 'ab': tm.get('abbreviation'),
                                   'logo': logo(tm, 24), 's': t.get('score') if st.get('state') == 'post' else None,
                                   'w': bool(t.get('winner')), 'rk': rk if rk and rk <= 25 else None}
    dt = datetime.datetime.fromisoformat(e['date'].replace('Z', '+00:00')).astimezone(ET)
    when = f"{dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}" if not st.get('state') == 'post' else None
    return {'day': f"{dt:%a} {dt.month}/{dt.day}", 'key': dt.strftime('%Y%m%d%H%M'),
            # a game in progress shows as such, no live score: the file refreshes every 30 minutes and each change rebuilds the site
            'st': st.get('state'), 'det': 'in progress' if st.get('state') == 'in' else st.get('shortDetail'), 'time': when,
            'a': side.get('away'), 'h': side.get('home'), 'note': ((c.get('notes') or [{}])[0].get('headline'))}


def days(games):
    out = {}
    for g in sorted(games, key=lambda g: g['key']):
        out.setdefault(g['day'], []).append(g)
    return [{'d': k, 'games': v} for k, v in out.items()]


def scores_daily(path, q, back, ahead):
    today = datetime.datetime.now(ET).date()
    urls = [SITE + f'{path}/scoreboard?dates={(today + datetime.timedelta(days=i)).strftime("%Y%m%d")}' + ('&' + q if q else '')
            for i in range(-back, ahead + 1)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda u: get(u).get('events', []), urls))
    seen, games = set(), []
    for evs in res:
        for e in evs:
            if e['id'] not in seen:
                seen.add(e['id']); games.append(game(e))
    return days(games)


def scores_weekly(path, q):
    cur = get(SITE + f'{path}/scoreboard' + ('?' + q if q else ''))
    wk = (cur.get('week') or {}).get('number')
    st = ((cur.get('season') or {}).get('type'))
    evs = list(cur.get('events', []))
    if wk and wk > 1:
        prev = get(SITE + f'{path}/scoreboard?week={wk - 1}&seasontype={st or 2}' + ('&' + q if q else ''))
        evs = prev.get('events', []) + evs
    seen, games = set(), []
    for e in evs:
        if e['id'] not in seen:
            seen.add(e['id']); games.append(game(e))
    return days(games)


# ---------------------------------------------------------------- main
def main():
    try:
        with open(OUT) as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    new = {'tables': {}, 'picture': {}, 'leaders': {}, 'polls': {}, 'rankings': {}, 'scores': {}}
    fails = []

    def keep(sec, key, fn):
        try:
            new[sec][key] = fn()
        except Exception as ex:  # one source down keeps its last good copy
            fails.append(f'{sec}.{key}: {ex}')
            if key in (old.get(sec) or {}):
                new[sec][key] = old[sec][key]

    try:
        t, s = us_tables()
        new['tables'].update(t)
        new['picture'] = picture(s)
    except Exception as ex:
        fails.append(f'us tables: {ex}')
        for k in ('nfl', 'nba', 'nhl'):
            if k in (old.get('tables') or {}):
                new['tables'][k] = old['tables'][k]
        new['picture'] = old.get('picture', {})
    keep('tables', 'cfb', lambda: college_tables('football/college-football', 'group=80', 'cfb', 'CFB standings (FBS)'))
    keep('tables', 'cbb', lambda: college_tables('basketball/mens-college-basketball', '', 'cbb', 'CBB standings (D-I)'))
    for lg, name in SOCCER:
        keep('tables', lg, lambda lg=lg, name=name: soccer_table(lg, name))
        if not lg.startswith('uefa'):
            keep('leaders', lg, lambda lg=lg: soccer_leaders(lg))
    for key, path, q, cats in LEADERS:
        keep('leaders', key, lambda key=key, path=path, q=q, cats=cats: leaders(key, path, q, cats))
    keep('polls', 'cfb', lambda: polls('football/college-football'))
    keep('polls', 'cbb', lambda: polls('basketball/mens-college-basketball'))
    keep('rankings', 'atp', lambda: tennis('atp'))
    keep('rankings', 'wta', lambda: tennis('wta'))
    for key, path, q, back, ahead in SCORES:
        keep('scores', key, lambda path=path, q=q, back=back, ahead=ahead: scores_daily(path, q, back, ahead))
    keep('scores', 'nfl', lambda: scores_weekly('football/nfl', ''))
    keep('scores', 'cfb', lambda: scores_weekly('football/college-football', 'groups=80&limit=300'))

    for f in fails:
        print('WARN', f, file=sys.stderr)
    body = {k: v for k, v in new.items()}
    if {k: v for k, v in old.items() if k != 'asof'} == body:
        print('standings: no change')
        return
    body = {'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), **body}
    with open(OUT, 'w') as f:
        json.dump(body, f, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    print(f'standings: wrote {os.path.getsize(OUT) // 1024} KB, {len(fails)} sources failed')


if __name__ == '__main__':
    main()
