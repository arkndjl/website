#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Free preseason win-total history for the futures backtest (scripts/futures_backtest.py).

    python3 scripts/futures_hist.py        # writes scripts/data/futures/win_totals.json

  NFL  nflverse nfldata win_totals.csv: 2003-20, line with over and under prices (one book, preseason close)
  NBA  Basketball-Reference preseason odds pages (courtesy sportsoddshistory): 2015-16 to 2025-26, the W-L O/U line
       only, no prices (graded at -110 both sides in the backtest); 2019-20 kept but the backtest drops it (the season
       stopped at 63-67 games and books settled the totals differently)
  NHL  Hockey-Reference preseason odds pages: 2011-12 on, the points O/U line and Stanley Cup odds, no prices on the
       total (graded at -110); `futures_hist.py nhl` refreshes these alone
  CFB, CBB  no free history found: sportsoddshistory.com (now behind covers.com) and Pro-Football-Reference answer
       bots with 503/403. ESPN's free DraftKings futures (scripts/futures_board.py) carry title, conference and
       division prices but no win totals.
Keys: season = the year the season ends for the NBA (2026 = 2025-26), the year it starts for the NFL.
"""
import csv
import io
import json
import os
import re
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'scripts', 'data', 'futures', 'win_totals.json')
UA = {'User-Agent': 'Mozilla/5.0 (arkndjl.net futures backtest)'}
NFL_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/win_totals.csv'
NBA_URL = 'https://www.basketball-reference.com/leagues/NBA_{}_preseason_odds.html'

# Basketball-Reference team names -> the NBA game model's codes (scripts/nba_games.py)
NBA = {'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN', 'Charlotte Hornets': 'CHA',
       'Charlotte Bobcats': 'CHA', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE', 'Dallas Mavericks': 'DAL',
       'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET', 'Golden State Warriors': 'GS', 'Houston Rockets': 'HOU',
       'Indiana Pacers': 'IND', 'Los Angeles Clippers': 'LAC', 'LA Clippers': 'LAC', 'Los Angeles Lakers': 'LAL',
       'Memphis Grizzlies': 'MEM', 'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN',
       'New Orleans Pelicans': 'NO', 'New York Knicks': 'NY', 'Oklahoma City Thunder': 'OKC', 'Orlando Magic': 'ORL',
       'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX', 'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC',
       'San Antonio Spurs': 'SA', 'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTAH', 'Washington Wizards': 'WSH'}
# nflverse codes -> nfl_games.py's (it already uses nflverse's, bar the moved franchises)
NFL = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA'}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode('utf-8', 'replace')


def nfl():
    rows = []
    for r in csv.DictReader(io.StringIO(get(NFL_URL))):
        o, u = int(float(r['over_odds'] or 0)), int(float(r['under_odds'] or 0))
        if abs(o) < 100 or abs(u) < 100:            # a missing price (2020 GB under): the line without a bet
            o = u = None
        rows.append({'S': int(r['season']), 't': NFL.get(r['team'], r['team']), 'line': float(r['line']), 'over': o, 'under': u})
    return rows


def nba(first=2016, last=2026):
    rows = []
    for S in range(first, last + 1):
        h = get(NBA_URL.format(S))
        tb = h[h.find('id="NBA_preseason_odds"'):]
        tb = tb[:tb.find('</table>')]
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb, re.S):
            cells = [re.sub(r'<[^>]+>|&nbsp;', ' ', c).strip() for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', tr, re.S)]
            cells = [c for c in cells if c]
            if len(cells) < 3 or cells[0] not in NBA:
                continue
            line = next((float(c) for c in cells[2:] if re.fullmatch(r'\d+(\.\d)?', c)), None)
            if line is None:
                continue
            odds = next((c for c in cells[1:] if re.fullmatch(r'[+-]\d+', c)), None)
            rows.append({'S': S, 't': NBA[cells[0]], 'line': line, 'title': int(odds) if odds else None})
        time.sleep(4)                       # Sports Reference asks for <20 requests a minute
    return rows


NHL_URL = 'https://www.hockey-reference.com/leagues/NHL_{}_preseason_odds.html'
# Hockey-Reference team names end in these -> the NHL game model's codes (scripts/nhl_games.py)
NHL = {'Mighty Ducks': 'ANA', 'Ducks': 'ANA', 'Bruins': 'BOS', 'Sabres': 'BUF', 'Flames': 'CGY', 'Hurricanes': 'CAR',
       'Blackhawks': 'CHI', 'Avalanche': 'COL', 'Blue Jackets': 'CBJ', 'Stars': 'DAL', 'Red Wings': 'DET', 'Oilers': 'EDM',
       'Panthers': 'FLA', 'Kings': 'LAK', 'Wild': 'MIN', 'Canadiens': 'MTL', 'Predators': 'NSH', 'Devils': 'NJD',
       'Islanders': 'NYI', 'Rangers': 'NYR', 'Senators': 'OTT', 'Flyers': 'PHI', 'Penguins': 'PIT', 'Sharks': 'SJS',
       'Kraken': 'SEA', 'Blues': 'STL', 'Lightning': 'TBL', 'Maple Leafs': 'TOR', 'Canucks': 'VAN', 'Golden Knights': 'VGK',
       'Capitals': 'WSH', 'Jets': 'WPG', 'Thrashers': 'WPG', 'Coyotes': 'UTA', 'Hockey Club': 'UTA', 'Mammoth': 'UTA'}


def nhl(first=2012, last=2027):
    """points O/U and Cup odds by season (the year it ends); the page's Final Pts. column is not read"""
    rows = []
    for S in range(first, last + 1):
        h = get(NHL_URL.format(S))
        tb = h[h.find('<table class="sortable stats_table" id="preseason_odds"'):]
        tb = tb[:tb.find('</table>')]
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb, re.S):
            cells = [re.sub(r'<[^>]+>|&nbsp;', ' ', c).strip() for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', tr, re.S)]
            code = next((v for k, v in NHL.items() if cells and cells[0].endswith(k)), None)
            if not code or len(cells) < 3 or not re.fullmatch(r'\d+(\.\d)?', cells[2]):
                continue
            rows.append({'S': S, 't': code, 'line': float(cells[2]), 'title': int(cells[1]) if re.fullmatch(r'[+-]\d+', cells[1]) else None})
        time.sleep(4)                       # Sports Reference asks for <20 requests a minute (robots: crawl-delay 3)
    return rows


def main():
    import sys
    if 'nhl' in sys.argv[1:]:               # the NHL lines alone, the other sports as stored
        out = json.load(open(OUT))
        out['nhl'] = nhl()
        with open(OUT, 'w') as f:
            json.dump(out, f, separators=(',', ':'))
        print('nhl', len(out['nhl']))
        return
    out = {'asof': time.strftime('%Y-%m-%d'), 'nfl': nfl(), 'nba': nba(), 'nhl': nhl()}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    for k in ('nfl', 'nba', 'nhl'):
        by = {}
        for r in out[k]:
            by[r['S']] = by.get(r['S'], 0) + 1
        print(k, len(out[k]), by)


if __name__ == '__main__':
    main()
