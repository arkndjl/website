#!/usr/bin/env python3
"""Homepage ticker: the next games of Noah's teams and of 1NT (Noah, Nov 1 2026).

    python3 scripts/fetch_ticker.py          # writes data/ticker.json (only when the games changed)

Teams: Knicks, Mets, Rangers, FC Barcelona (every competition), Ravens, from ESPN's public team schedules.
The Mets' offseason has no regular-season games on the current schedule, so they show next season's Opening Day.
1NT comes from data/esea.json (scripts/fetch_esea.mjs). Win chances are the site's own game models
(data/<sport>_games.json, joined on the ESPN event id; 1NT from the match preview). No betting lines.
Run by the odds-snap and picks-refresh workflows. Times are written in ET for the page.
"""
import datetime
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'ticker.json')
ET = ZoneInfo('America/New_York')
API = 'https://site.api.espn.com/apis/site/v2/sports/'
KEEP = 3   # games per team, so the page can move past one that has finished before the next refresh

# key, label, ESPN path, team id, model file, game length (hours, for the page to roll on)
TEAMS = [
    ('knicks', 'Knicks', 'basketball/nba', '18', 'nba', 3),
    ('mets', 'Mets', 'baseball/mlb', '21', None, 3.5),
    ('rangers', 'Rangers', 'hockey/nhl', '13', 'nhl', 3),
    ('barcelona', 'Barcelona', 'soccer/all', '83', 'soccer', 2.25),
    ('ravens', 'Ravens', 'football/nfl', '33', 'nfl', 3.5),
]
COMP = {'esp.1': 'LaLiga', 'uefa.champions': 'UCL', 'esp.copa_del_rey': 'Copa', 'esp.super_cup': 'Supercopa',
        'club.friendly': 'Friendly', 'fifa.cwc': 'CWC'}


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net ticker'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load(name):
    try:
        with open(os.path.join(ROOT, 'data', name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def et_text(dt, time_ok=True):
    t = dt.astimezone(ET)
    day = f"{t:%a} {t.month}/{t.day}"
    if not time_ok:
        return day, None
    return day, f"{t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'}"


def model_p(sport, eid, home):
    """The team's win chance (0-100) from the site's game model and the pregame numbers the page's in-game model
    starts from (home side's view: NFL/NBA win chance + margin sd, NHL win chance + total, soccer expected goals)."""
    if not sport:
        return None, None
    d = load(f'{sport}_games.json')
    for g in d.get('games') or []:
        gid = str(g.get('espn') or g.get('id')) if sport in ('nhl', 'nfl') else str(g.get('id'))
        if gid != eid:
            continue
        if sport == 'soccer':
            p, l = g.get('p') or [], g.get('l') or []
            live = {'l': l} if len(l) == 2 else None
            return (round(100 * (p[0] if home else p[2])) if len(p) == 3 else None), live
        ph = g.get('pHome')
        if ph is None:
            return None, None
        live = {'ph': round(ph, 4)}
        if sport in ('nfl', 'nba') and d.get('sd'):
            live['sd'] = d['sd']
        if sport == 'nhl':
            live['t'] = g.get('total')
        return round(100 * (ph if home else 1 - ph)), live
    return None, None


def logo(team):
    if team.get('logo'):
        return team['logo']
    for l in team.get('logos') or []:
        if l.get('href'):
            return l['href']
    return None


def events(path, tid, sport):
    if sport == 'soccer':
        return get(f'{API}{path}/teams/{tid}/schedule?fixture=true').get('events') or []
    ev = get(f'{API}{path}/teams/{tid}/schedule').get('events') or []
    up = [e for e in ev if e['competitions'][0]['status']['type'].get('state') == 'pre']
    if up or path != 'baseball/mlb':
        return ev
    # MLB offseason: next season's regular schedule (spring training games are left out)
    year = datetime.date.today().year + 1
    return get(f'{API}{path}/teams/{tid}/schedule?season={year}&seasontype=2').get('events') or []


def team_rows(key, label, path, tid, sport, hours):
    now = datetime.datetime.now(datetime.timezone.utc)
    rows, me_logo = [], None
    for e in events(path, tid, sport):
        c = e['competitions'][0]
        st = c['status']['type']
        if st.get('state') == 'post' or st.get('name') in ('STATUS_POSTPONED', 'STATUS_CANCELED'):
            continue
        at = datetime.datetime.fromisoformat(e['date'].replace('Z', '+00:00'))
        if at + datetime.timedelta(hours=hours) < now:
            continue
        comp = c.get('competitors') or []
        me = next((x for x in comp if str(x['team'].get('id')) == tid), None)
        op = next((x for x in comp if x is not me), None)
        if not me or not op:
            continue
        me_logo = me_logo or logo(me['team'])
        home = me.get('homeAway') == 'home'
        time_ok = c.get('timeValid', True) is not False
        day, clock = et_text(at, time_ok)
        lg = (e.get('league') or {}).get('slug') if isinstance(e.get('league'), dict) else None
        note = None
        if path == 'baseball/mlb':
            note = 'opening day' if not rows and at.year > now.year and at.month <= 4 else None
            note = note or ((e.get('seasonType') or {}).get('name') or '').lower().replace('regular season', '') or None
        elif lg and lg != 'esp.1':
            note = COMP.get(lg, (e.get('league') or {}).get('abbreviation') or lg)
        o = op['team']
        p, live = model_p(sport, str(e['id']), home)
        rows.append({
            'id': str(e['id']), 'at': at.strftime('%Y-%m-%dT%H:%M:%SZ'), 'day': day, 'time': clock,
            'home': home, 'neutral': bool(c.get('neutralSite')),
            'opp': o.get('shortDisplayName') or o.get('displayName') or o.get('name'),
            'oppAbbr': o.get('abbreviation'), 'oppLogo': logo(o), 'note': note,
            'p': p, 'live': live, 'lg': lg if sport == 'soccer' else None,
        })
        if len(rows) >= KEEP:
            break
    return {'key': key, 'label': label, 'logo': me_logo, 'hours': hours, 'path': path, 'sport': sport or path.split('/')[1], 'games': rows,
            'off': not rows}


def nt_rows():
    d = load('esea.json')
    pv = d.get('preview') or {}
    now_ms = datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
    rows = []
    for m in d.get('matches') or []:
        if m.get('result') or m.get('status') in ('CANCELLED', 'FINISHED') or not m.get('at'):
            continue
        if m['at'] + 3 * 3600e3 < now_ms:
            continue
        at = datetime.datetime.fromtimestamp(m['at'] / 1000, datetime.timezone.utc)
        day, clock = et_text(at)
        win = (pv.get('p') or {}).get('win') if pv.get('id') == m.get('id') else None
        opp = m.get('opp') or {}
        rows.append({
            'id': m['id'], 'at': at.strftime('%Y-%m-%dT%H:%M:%SZ'), 'day': day, 'time': clock,
            'opp': opp.get('name') or 'TBD', 'oppLogo': opp.get('avatar'),
            'oppRank': opp.get('rank'), 'bo': m.get('best_of') or 1, 'stage': m.get('stage'),
            'url': m.get('url') or None, 'p': win,
        })
    rows.sort(key=lambda r: r['at'])
    return {'season': d.get('season'), 'hours': 1.5, 'games': rows[:KEEP]}


def main():
    old = load('ticker.json')
    teams = []
    for t in TEAMS:
        try:
            teams.append(team_rows(*t))
        except Exception as e:   # one team's feed failing keeps its last rows
            print(f'{t[0]}: {e}', file=sys.stderr)
            prev = next((x for x in old.get('teams') or [] if x.get('key') == t[0]), None)
            if prev:
                teams.append(prev)
    teams.sort(key=lambda t: t['games'][0]['at'] if t.get('games') else '9999')   # soonest game first
    out = {'teams': teams, 'nt': nt_rows()}
    if {k: old.get(k) for k in out} == out:
        print('ticker: no change')
        return
    out['asof'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1, ensure_ascii=False, allow_nan=False)
        f.write('\n')
    print(f"ticker: {sum(len(t['games']) for t in teams)} team games, {len(out['nt']['games'])} 1NT")


if __name__ == '__main__':
    main()
