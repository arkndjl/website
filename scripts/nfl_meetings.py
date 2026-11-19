#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-draft meetings between NFL teams and prospects, logged with the date they were read.

    python3 scripts/nfl_meetings.py [draft year]     # default: the coming draft
    python3 scripts/nfl_meetings.py --test

WalterFootball lists each team's reported meetings (ProspectMeetingsByTeam<year>.php): top-30 visits (T30), private
workouts (PRI), combine (COM), pro day (PRO), Senior Bowl (SR), virtual (VIR), local day (LOC), workout (WOR). The
page is overwritten in place and does not exist until the winter before the draft, so each run that finds it writes
scripts/data/nfl_meetings/<year>.json: {updated (the page's own stamp), pulled, teams: {abbr: [[name, pos, college,
[tags]]]}} and appends the stamp to its "seen" list, which is the dated history a later test needs. A missing page
(404) changes nothing. One request a run.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'scripts', 'data', 'nfl_meetings')
URL = 'https://walterfootball.com/ProspectMeetingsByTeam{}.php'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
NFL = {'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL', 'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR',
       'Chicago Bears': 'CHI', 'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL', 'Denver Broncos': 'DEN',
       'Detroit Lions': 'DET', 'Green Bay Packers': 'GB', 'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX',
       'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC', 'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA',
       'Minnesota Vikings': 'MIN', 'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG', 'New York Jets': 'NYJ',
       'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA',
       'Tampa Bay Buccaneers': 'TB', 'Tennessee Titans': 'TEN', 'Washington Commanders': 'WSH'}
ROW = re.compile(r'^([^,]+?)[\^%#]*,\s*([^,]+),\s*(.+?)\s*\(([A-Z0-9, ]+)\)\s*$')


def parse(page):
    t = html.unescape(re.sub(r'<[^>]+>', '\n', re.sub(r'<script.*?</script>|<style.*?</style>', '', page, flags=re.S)))
    lines = [x.strip() for x in t.split('\n') if x.strip()]
    up = next((re.sub(r'^Updated:\s*', '', x) for x in lines if x.startswith('Updated:')), None)
    marks = [i for i, x in enumerate(lines) if x == 'By College']
    teams, team = {}, None
    for x in lines[(marks[-1] if marks else 0):]:
        if x in NFL:
            team = NFL[x]
            continue
        m = ROW.match(x)
        if team and m:
            teams.setdefault(team, []).append([m.group(1).strip(), m.group(2).strip(), m.group(3).strip(), sorted({a.strip() for a in m.group(4).split(',') if a.strip()})])
    return up, teams


def self_test():
    page = ('<p>Updated: April 24, 2024</p><a>By Team</a><a>By Prospect</a><a>By College</a><b>Arizona Cardinals</b><br>'
            'Marvin Harrison Jr.^, Wide Receiver, Ohio State (COM, T30)<br>Terrion Arnold, Cornerback, Alabama (T30)<br><b>Atlanta Falcons</b><br>'
            'Jer&#39;Zhan Newton, Defensive Tackle, Illinois (T30, LOC)')
    up, teams = parse(page)
    assert up == 'April 24, 2024', up
    assert teams['ARI'][0] == ['Marvin Harrison Jr.', 'Wide Receiver', 'Ohio State', ['COM', 'T30']], teams
    assert teams['ATL'][0][0] == "Jer'Zhan Newton" and len(teams['ARI']) == 2
    print('nfl_meetings: self-test ok')


def main():
    if '--test' in sys.argv:
        return self_test()
    args = [a for a in sys.argv[1:] if a.isdigit()]
    today = dt.date.today()
    year = int(args[0]) if args else (today.year + 1 if today.month >= 5 else today.year)
    try:
        page = urllib.request.urlopen(urllib.request.Request(URL.format(year), headers={'User-Agent': UA}), timeout=30).read().decode('latin1')
    except Exception as e:
        print(f'nfl meetings: no {year} page yet ({e})')
        return 0
    up, teams = parse(page)
    n = sum(len(v) for v in teams.values())
    if len(teams) < 20 or n < 50:
        print(f'nfl meetings: {year} page has {n} rows for {len(teams)} teams, nothing written')
        return 0
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, f'{year}.json')
    try:
        seen = json.load(open(f)).get('seen', [])
    except Exception:
        seen = []
    if not seen or seen[-1][1] != up:
        seen.append([today.isoformat(), up, n])
    with open(f, 'w') as o:
        json.dump({'draft': year, 'updated': up, 'pulled': today.isoformat(), 'seen': seen, 'teams': teams}, o, separators=(',', ':'), ensure_ascii=False)
    print(f'nfl meetings: {year} {n} meetings, {len(teams)} teams (page of {up})')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
