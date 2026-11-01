#!/usr/bin/env python3
"""History for the college basketball game model (scripts/cbb_games.py): every D-I game from 2013-14 on, with the
market's lines, written to scripts/data/cbb_games_hist.json.gz (committed, so the daily job never re-pulls history).

    python3 scripts/cbb_games_hist.py              # pull what the cache lacks, rebuild the file
    python3 scripts/cbb_games_hist.py 2025 2026    # only these seasons (season = the year it ends)

Sources (free, cached in scripts/.cache/cbb/games/):
  ESPN scoreboard, one call a date (groups=50 is all of D-I): ids, teams, site, neutral flag, conference game, score
  ESPN core odds, one call a game: every book's spread, total and moneylines (open and close where the book has them)
  Barttorvik super_sked: possessions a game (joined by date and both scores), for tempo and points a possession
"""
import csv, gzip, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache', 'cbb', 'games')
OUT = os.path.join(HERE, 'data', 'cbb_games_hist.json.gz')
SB = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={d}&groups=50&limit=1000'
ODDS = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/events/{i}/competitions/{i}/odds?limit=50'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
FIRST = 2014
# books in the order a game's line is taken from: the sharpest available first, then the biggest US books;
# 'consensus' and 'Opening' entries, projection sites and pick services are never a line
SKIP = ('accuscore', 'teamrankings', 'numberfire', 'consensus', 'opening', 'live')
BOOKS = ['pinnacle', 'circa', 'bookmaker', '5dimes', 'betonline', 'caesars', 'william hill', 'draftkings', 'espn bet',
         'fanduel', 'betmgm', 'westgate', 'cg technology', 'bovada', 'betfair', 'betrivers', 'unibet', 'pointsbet']


def curl(url, path, tries=3):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for i in range(tries):
        subprocess.run(['curl', '-s', '-m', '40', '-A', UA, url, '-o', path + '.tmp'], check=False)
        try:
            j = json.load(open(path + '.tmp'))
            os.replace(path + '.tmp', path)
            return j
        except Exception:
            time.sleep(1 + 2 * i)
    return None


def cached(url, path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return curl(url, path)


def dates(season):
    d, end = date(season - 1, 11, 1), date(season, 4, 12)
    while d <= end:
        yield d.strftime('%Y%m%d')
        d += timedelta(days=1)


def parse_event(e):
    """an ESPN scoreboard event -> the game row (no odds yet)"""
    c = e['competitions'][0]
    side = {x['homeAway']: x for x in c['competitors']}
    if 'home' not in side or 'away' not in side:
        return None
    st = c['status']['type']
    h, a = side['home'], side['away']
    note = ' '.join(n.get('headline', '') for n in c.get('notes') or [])
    return {'id': e['id'], 'date': e['date'], 'season': e['season']['year'], 'stype': e['season'].get('type', 2),
            'home': h['team']['id'], 'away': a['team']['id'],
            'hn': h['team'].get('location') or h['team'].get('displayName'), 'an': a['team'].get('location') or a['team'].get('displayName'),
            'neutral': bool(c.get('neutralSite')), 'conf': bool(c.get('conferenceCompetition')),
            'hs': int(h['score']) if st.get('completed') and h.get('score') not in (None, '') else None,
            'as': int(a['score']) if st.get('completed') and a.get('score') not in (None, '') else None,
            'note': note.strip(), 'state': st.get('state'), 'ot': max(0, (c['status'].get('period') or 2) - 2),
            'att': c.get('attendance') if st.get('completed') else None}


def am(x):
    try:
        v = float(x)
        return v if v and abs(v) >= 100 else None
    except (TypeError, ValueError):
        return None


def pick_line(items):
    """one book's line for the game: spread (home side, negative = home favored), total, moneylines, the open spread"""
    rank = lambda it: next((i for i, b in enumerate(BOOKS) if b in it['provider']['name'].lower()), len(BOOKS))
    books = [it for it in items if not any(s in it['provider']['name'].lower() for s in SKIP)]
    books.sort(key=rank)
    out = {}
    for it in books:
        sp = it.get('spread')
        if 'spread' not in out and sp is not None and abs(sp) < 60:
            # ESPN's spread is the home side's; check against the details text ("MARQ -6.5") when the favorite is named
            out['spread'] = float(sp); out['book'] = it['provider']['name']
            ho, ao = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
            if ho.get('favorite') and sp > 0 or ao.get('favorite') and sp < 0:
                out['spread'] = -float(sp)
            op = (ho.get('open') or {}).get('pointSpread') or {}
            try:
                out['open'] = float(op.get('american', 'x').replace('PK', '0'))
            except ValueError:
                pass
        if 'total' not in out and it.get('overUnder') and 90 < it['overUnder'] < 220:
            out['total'] = float(it['overUnder'])
        ho, ao = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
        if 'mlh' not in out and am(ho.get('moneyLine')) and am(ao.get('moneyLine')):
            out['mlh'], out['mla'] = am(ho['moneyLine']), am(ao['moneyLine'])
    return out


def bart(season):
    """Barttorvik super_sked: (date, sorted scores) -> [(possessions, {points: Barttorvik team name})]"""
    p = os.path.join(CACHE, f'bt_sked{season}.csv')
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        subprocess.run(['curl', '-s', '-m', '120', '-A', UA, f'https://barttorvik.com/{season}_super_sked.csv', '-o', p], check=False)
    out = {}
    for r in csv.reader(open(p, encoding='utf-8', errors='replace')):
        try:
            m, d, y = r[1].split('/')
            dd = f'20{int(y):02d}-{int(m):02d}-{int(d):02d}'
            pts = tuple(sorted((int(float(r[27])), int(float(r[28])))))
            out.setdefault((dd, pts), []).append((float(r[26]), {int(float(r[27])): r[8], int(float(r[28])): r[14]}))
        except (ValueError, IndexError):
            continue
    return out


def season_rows(season):
    evs = {}
    with ThreadPoolExecutor(8) as ex:
        for j in ex.map(lambda d: cached(SB.format(d=d), os.path.join(CACHE, 'sb', str(season), f'{d}.json')), list(dates(season))):
            for e in (j or {}).get('events', []):
                g = parse_event(e)
                if g and g['hs'] is not None:
                    evs[g['id']] = g
    games = sorted(evs.values(), key=lambda g: (g['date'], g['id']))
    with ThreadPoolExecutor(24) as ex:
        odds = list(ex.map(lambda g: cached(ODDS.format(i=g['id']), os.path.join(CACHE, 'odds', str(season), f"{g['id']}.json")), games))
    bt = bart(season)
    from datetime import datetime, timezone, timedelta as td
    for g, o in zip(games, odds):
        g.update(pick_line((o or {}).get('items', [])))
        # ESPN dates are UTC; Barttorvik's are local (US) dates
        local = (datetime.fromisoformat(g['date'].replace('Z', '+00:00')) - td(hours=8)).strftime('%Y-%m-%d')   # cbb_games.et_date
        p = bt.get((local, tuple(sorted((g['hs'], g['as'])))))
        if p and len(p) == 1:
            g['poss'] = round(p[0][0], 1)
            if g['hs'] != g['as']:
                g['hb'], g['ab'] = p[0][1][g['hs']], p[0][1][g['as']]
        for k in ('state', 'stype') if g['stype'] == 2 else ('state',):
            g.pop(k, None)
    return games


def main():
    seasons = [int(a) for a in sys.argv[1:] if a.isdigit()] or list(range(FIRST, 2027))
    old = {}
    if os.path.exists(OUT):
        for g in json.load(gzip.open(OUT)):
            old.setdefault(g['season'], []).append(g)
    for s in seasons:
        t = time.time()
        old[s] = season_rows(s)
        n = len(old[s])
        print(s, n, 'games', sum('spread' in g for g in old[s]), 'spreads', sum('mlh' in g for g in old[s]), 'ML',
              sum('poss' in g for g in old[s]), 'poss', f'{time.time() - t:.0f}s', flush=True)
    rows = [g for s in sorted(old) for g in old[s]]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.GzipFile(OUT, 'wb', mtime=0) as f:
        f.write(json.dumps(rows, separators=(',', ':')).encode())


if __name__ == '__main__':
    main()
