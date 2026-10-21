#!/usr/bin/env python3
"""Free preseason win-total history for the futures backtest (scripts/futures_backtest.py).

    python3 scripts/futures_hist.py        # writes scripts/data/futures/win_totals.json

  NFL  nflverse nfldata win_totals.csv: 2003-20, line with over and under prices (one book, preseason close)
  NBA  Basketball-Reference preseason odds pages (courtesy sportsoddshistory): 2015-16 to 2025-26, the W-L O/U line
       only, no prices (graded at -110 both sides in the backtest); 2019-20 kept but the backtest drops it (the season
       stopped at 63-67 games and books settled the totals differently)
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


def main():
    out = {'asof': time.strftime('%Y-%m-%d'), 'nfl': nfl(), 'nba': nba()}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    for k in ('nfl', 'nba'):
        by = {}
        for r in out[k]:
            by[r['S']] = by.get(r['S'], 0) + 1
        print(k, len(out[k]), by)


if __name__ == '__main__':
    main()
