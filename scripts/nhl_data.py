# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL pulls for the NHL ARKBOARD (scripts/nhl_games.py, scripts/nhl_players.py): the NHL's stats API (every game's
score and last period, goalie and skater game logs), MoneyPuck's team game logs (expected goals by situation), and
ESPN (every listed book's moneyline, puck line and total from 2019-20 on; injuries and rosters). Trimmed copies go to
scripts/.cache/nhl/ so a finished season is fetched once. Stdlib only.

    python3 scripts/nhl_data.py 2011 2026      # seasons from..to (end year), for the backtest history

Team codes are the NHL's tri-codes; Arizona (ARI, PHX) carries on as Utah (UTA) and Atlanta (ATL) as Winnipeg (WPG),
so ratings follow the roster.
"""
import csv, datetime as dt, gzip, io, json, os, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nhl')
STATS = 'https://api.nhle.com/stats/rest/en'
WEB = 'https://api-web.nhle.com/v1'
MP = 'https://moneypuck.com/moneypuck/playerData'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl'
CORE = 'https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
TEAMS = {'ANA', 'BOS', 'BUF', 'CAR', 'CBJ', 'CGY', 'CHI', 'COL', 'DAL', 'DET', 'EDM', 'FLA', 'LAK', 'MIN', 'MTL', 'NJD',
         'NSH', 'NYI', 'NYR', 'OTT', 'PHI', 'PIT', 'SEA', 'SJS', 'STL', 'TBL', 'TOR', 'UTA', 'VAN', 'VGK', 'WPG', 'WSH'}
ALIAS = {'ARI': 'UTA', 'PHX': 'UTA', 'ATL': 'WPG', 'T.B': 'TBL', 'TB': 'TBL', 'N.J': 'NJD', 'NJ': 'NJD', 'S.J': 'SJS',
         'SJ': 'SJS', 'L.A': 'LAK', 'LA': 'LAK', 'UTAH': 'UTA', 'WAS': 'WSH', 'MON': 'MTL', 'CLS': 'CBJ', 'NAS': 'NSH',
         'VEG': 'VGK', 'WIN': 'WPG', 'CAL': 'CGY'}
TEAM_ID = {1: 'NJD', 2: 'NYI', 3: 'NYR', 4: 'PHI', 5: 'PIT', 6: 'BOS', 7: 'BUF', 8: 'MTL', 9: 'OTT', 10: 'TOR', 11: 'WPG',
           12: 'CAR', 13: 'FLA', 14: 'TBL', 15: 'WSH', 16: 'CHI', 17: 'DET', 18: 'NSH', 19: 'STL', 20: 'CGY', 21: 'COL',
           22: 'EDM', 23: 'VAN', 24: 'ANA', 25: 'DAL', 26: 'LAK', 27: 'UTA', 28: 'SJS', 29: 'CBJ', 30: 'MIN', 52: 'WPG',
           53: 'UTA', 54: 'VGK', 55: 'SEA', 59: 'UTA', 68: 'UTA'}


def team(a):
    a = (a or '').upper()
    return ALIAS.get(a, a)


def get(url, tries=4, raw=False):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            r = urllib.request.urlopen(req, timeout=90)
            return r.read() if raw else json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    op = gzip.open if path.endswith('.gz') else open
    with op(tmp, 'wt') as f:
        json.dump(obj, f, separators=(',', ':'))
    os.replace(tmp, path)


def load(path):
    op = gzip.open if path.endswith('.gz') else open
    with op(path, 'rt') as f:
        return json.load(f)


def current_season(today=None):
    d = today or dt.date.today()
    return d.year + 1 if d.month >= 8 else d.year


def sid(S):
    return f'{S - 1}{S}'


def _done(S):
    return S < current_season()


_NAMES = {}


def player_names(S, max_age_h=24):
    """{player id: full name} for season S from the stats API (skaters and goalies, 100 rows a page). MoneyPuck's files
    drop every non-ASCII letter (Tim Sttzle, Juraj Slafkovsk, Alexis Lafrenire); repair_name puts the league's spelling
    back. Cached; the current season is read again after max_age_h. A failed pull returns what the cache has ({} with
    no cache), so the callers keep MoneyPuck's names and never fail on it."""
    if S in _NAMES:
        return _NAMES[S]              # one pull a run
    fn = os.path.join(CACHE, 'names', f'{S}.json')
    old = load(fn) if os.path.exists(fn) else {}
    _NAMES[S] = old
    if old and (_done(S) or time.time() - os.path.getmtime(fn) < max_age_h * 3600):
        return old
    out = {}
    for kind in ('skater', 'goalie'):
        for start in range(0, 3000, 100):
            j = get(f'{STATS}/{kind}/summary?isAggregate=true&isGame=false&start={start}&limit=100'
                    f'&cayenneExp=seasonId={sid(S)}%20and%20gameTypeId=2', tries=2)
            data = (j or {}).get('data')
            if data is None:
                return old            # a failed page: the last full pull, not half a list
            for r in data:
                if r.get(f'{kind}FullName'):
                    out[str(r['playerId'])] = r[f'{kind}FullName']
            if len(data) < 100:
                break
    if out:
        save(fn, out)
        _NAMES[S] = out
    return out or old


def repair_name(n, full):
    """full (the league's name) when n is that name with letters missing, word by word: the word without its non-ASCII
    letters (Slafkovsk / Slafkovský), or the word with letters gone from the inside where the league writes it in ASCII
    (Rty / Raty, Mtt / Maatta: vowels only). A short form (Will / William, Joe / Joseph) or any other difference keeps n."""
    if not n or not full or n == full:
        return n
    a, b = n.split(), full.split()
    if len(a) != len(b):
        return n
    for x, y in zip(a, b):
        if x == y or x == ''.join(c for c in y if c.isascii()):
            continue
        gone, k = [], 0                      # y's letters that x lacks, x read in order
        for c in y:
            if k < len(x) and c == x[k]: k += 1
            else: gone.append(c)
        if k == len(x) and gone and not y.startswith(x) and all(c in 'aeiouy' for c in gone):
            continue                         # only vowels gone (the accented letters; Joe / Joseph loses consonants)
        return n
    return full


def games(S, fresh=False):
    """every regular-season and playoff game of season S: id, date, start, teams, score, last period (4 OT, 5 SO)"""
    fn = os.path.join(CACHE, 'games', f'{S}.json')
    if not fresh and os.path.exists(fn):
        return load(fn)
    j = get(f'{STATS}/game?cayenneExp=season={sid(S)}%20and%20gameType%3E=2%20and%20gameType%3C=3')
    out = []
    for g in (j or {}).get('data', []):
        h, a = TEAM_ID.get(g['homeTeamId']), TEAM_ID.get(g['visitingTeamId'])
        if not h or not a:
            continue
        out.append({'id': g['id'], 'day': g['gameDate'], 'et': g.get('easternStartTime'), 'type': g['gameType'],
                    'h': h, 'a': a, 'hs': g.get('homeScore'), 'as': g.get('visitingScore'), 'per': g.get('period'),
                    'final': g.get('gameStateId') == 7})
    out.sort(key=lambda g: (g['et'] or g['day'], g['id']))
    if out and _done(S):
        save(fn, out)              # unplayed 'if necessary' playoff games stay in, not final
    return out


def schedule(day):
    """api-web schedule for the week from `day` (start times in UTC, game state, neutral sites)"""
    j = get(f'{WEB}/schedule/{day}')
    out = []
    for w in (j or {}).get('gameWeek', []):
        for g in w.get('games', []):
            if g.get('gameType') not in (2, 3):
                continue
            out.append({'id': g['id'], 'day': w['date'], 'start': g.get('startTimeUTC'), 'type': g['gameType'],
                        'h': team(g['homeTeam']['abbrev']), 'a': team(g['awayTeam']['abbrev']),
                        'hs': g['homeTeam'].get('score'), 'as': g['awayTeam'].get('score'),
                        'state': g.get('gameState'), 'neutral': bool(g.get('neutralSite')),
                        'venue': (g.get('venue') or {}).get('default')})
    return out


PAGE = 100          # the stats API returns at most 100 rows a call (limit=-1 included, since Nov 2026)


def _pages(url):
    """every row of one stats-API query, paged by start in a fixed order (game, then player); raises when the rows
    that came back are not the query's total, so a short answer never passes for a full log"""
    srt = '%5B%7B%22property%22:%22gameId%22,%22direction%22:%22ASC%22%7D,%7B%22property%22:%22playerId%22,%22direction%22:%22ASC%22%7D%5D'

    def page(start):
        j = get(f'{url}&sort={srt}&start={start}&limit={PAGE}')
        if j is None or 'data' not in j:
            raise RuntimeError(f'stats API: no answer for {url} start={start}')
        return j

    for attempt in range(3):            # rows added while the pages were read (a game going final) shift them: read again
        first = page(0)
        rows, total = list(first['data']), first.get('total') or 0
        step = len(rows)                # the page size the API really gave
        if total > step > 0:
            with ThreadPoolExecutor(6) as ex:
                for j in ex.map(page, range(step, total, step)):
                    rows += j['data']
        if len(rows) == total and len({(r['gameId'], r['playerId']) for r in rows}) == total:
            return rows
        time.sleep(3)
    raise RuntimeError(f'stats API: {len(rows)} of {total} rows for {url}')


def _logs(kind, S, gtype, fresh):
    """stats-API game logs (goalie or skater summary, one row a player-game), every page of each query (_pages);
    skaters come two weeks at a time"""
    fn = os.path.join(CACHE, kind, f'{S}-{gtype}.json.gz')
    if not fresh and os.path.exists(fn):
        return load(fn)
    rows = []
    if kind == 'goalie':
        spans = [(None, None)]
    else:
        lo, hi = dt.date(S - 1, 9, 1), dt.date(S, 10, 15) if S == 2020 else dt.date(S, 7, 31)
        hi = min(hi, dt.date.today())               # the current season: no queries for weeks still to come
        spans, d = [], lo
        while d <= hi:
            e = min(d + dt.timedelta(days=13), hi)
            spans.append((d, e)); d = e + dt.timedelta(days=1)
    for lo, hi in spans:
        q = f'seasonId={sid(S)}%20and%20gameTypeId={gtype}'
        if lo:
            q += f'%20and%20gameDate%3E=%22{lo}%22%20and%20gameDate%3C=%22{hi}%22'
        rows += _pages(f'{STATS}/{kind}/summary?isAggregate=false&isGame=true&cayenneExp={q}')
    if kind == 'goalie':
        keep = [(r['gameId'], r['playerId'], r['goalieFullName'], team(r['teamAbbrev']), r['gamesStarted'],
                 r['timeOnIce'], r['shotsAgainst'], r['goalsAgainst']) for r in rows]
    else:
        keep = [(r['gameId'], r['playerId'], r['skaterFullName'], team(r['teamAbbrev']), r['positionCode'],
                 r.get('timeOnIcePerGame') or 0, r['goals'], r['assists'], r.get('shots') or 0,
                 r.get('ppPoints') or 0, r.get('plusMinus') or 0) for r in rows]
    if keep and _done(S):
        save(fn, keep)
    return keep


def goalie_logs(S, fresh=False):
    """(gameId, playerId, name, team, started, toi s, shots against, goals against) for every goalie-game"""
    return _logs('goalie', S, 2, fresh) + _logs('goalie', S, 3, fresh)


def skater_logs(S, fresh=False):
    """(gameId, playerId, name, team, pos, toi s, g, a, shots, pp pts, +/-) for every skater-game"""
    return _logs('skater', S, 2, fresh) + _logs('skater', S, 3, fresh)


XG_COLS = ('xGoalsFor', 'xGoalsAgainst', 'scoreVenueAdjustedxGoalsFor', 'scoreVenueAdjustedxGoalsAgainst',
           'goalsFor', 'goalsAgainst', 'shotAttemptsFor', 'shotAttemptsAgainst', 'iceTime',
           'penalityMinutesFor', 'penalityMinutesAgainst', 'highDangerxGoalsFor', 'highDangerxGoalsAgainst')


def moneypuck_teams(fresh=False, max_age_h=10):
    """MoneyPuck team game logs: {gameId: {team: {situation: {col: value}}}}, situations all, 5on5, 5on4, 4on5"""
    raw = os.path.join(CACHE, 'all_teams.csv')
    if fresh or not os.path.exists(raw) or time.time() - os.path.getmtime(raw) > max_age_h * 3600:
        b = get(f'{MP}/careers/gameByGame/all_teams.csv', raw=True)
        if b:
            with open(raw + '.tmp', 'wb') as f:
                f.write(b)
            os.replace(raw + '.tmp', raw)
    out = {}
    with open(raw) as f:
        for r in csv.DictReader(f):
            if r['situation'] == 'other':
                continue
            g = out.setdefault(int(r['gameId']), {})
            g.setdefault(team(r['playerTeam']), {})[r['situation']] = {k: float(r[k] or 0) for k in XG_COLS}
    return out


def moneypuck_goalie_games(pids, recent=(), workers=8, max_age_h=10):
    """MoneyPuck's game logs for each goalie in pids, all situations: {gameId: {playerId: [xG faced, goals allowed]}}.
    The xG a goalie faced is only shots with him in net (empty-net shots are not his), unlike his team's xG against.
    Regular season and playoffs; a career file is cached once, re-fetched after max_age_h for goalies in recent"""
    recent = set(recent)

    def one(a):
        pid, kind = a
        fn = os.path.join(CACHE, 'mpg', kind, f'{pid}.json')
        if os.path.exists(fn) and (pid not in recent or time.time() - os.path.getmtime(fn) < max_age_h * 3600):
            return load(fn)
        b = get(f'{MP}/careers/gameByGame/{kind}/goalies/{pid}.csv', raw=True)
        if b is None:
            return load(fn) if os.path.exists(fn) else {}
        out = {}
        for r in csv.DictReader(io.StringIO(b.decode('utf-8', 'replace'))):
            if r.get('situation') == 'all':
                out[r['gameId']] = [round(float(r['xGoals'] or 0), 3), float(r['goals'] or 0)]
        save(fn, out)
        return out
    todo = [(p, k) for p in sorted(set(pids)) for k in ('regular', 'playoffs')]
    out = {}
    with ThreadPoolExecutor(workers) as ex:
        for (pid, _), g in zip(todo, ex.map(one, todo)):
            for gid, v in g.items():
                out.setdefault(int(gid), {})[pid] = v
    return out


def _num(s):
    try:
        return float(str(s).replace('EVEN', '100').replace('PK', '0'))
    except (TypeError, ValueError):
        return None


def espn_day(d, fresh=False):
    """ESPN's games on a date (ids, teams, start, current odds): ESPN ids differ from the NHL's, joined by date + teams"""
    fn = os.path.join(CACHE, 'espn', 'sb', d.strftime('%Y%m%d') + '.json')
    if not fresh and os.path.exists(fn):
        return load(fn)
    j = get(f'{ESPN}/scoreboard?dates={d.strftime("%Y%m%d")}')
    if j is None:
        return []
    out = []
    for e in j.get('events', []):
        c = e['competitions'][0]
        side = {x['homeAway']: x for x in c['competitors']}
        if 'home' not in side or 'away' not in side:
            continue
        h, a = team(side['home']['team'].get('abbreviation')), team(side['away']['team'].get('abbreviation'))
        if h not in TEAMS or a not in TEAMS:
            continue
        st = c['status']['type']
        o = (c.get('odds') or [{}])[0]
        out.append({'id': e['id'], 'start': e['date'], 'season': e['season']['year'], 'type': e['season']['type'],
                    'h': h, 'a': a, 'final': bool(st.get('completed')), 'state': st.get('state'),
                    'odds': {'book': (o.get('provider') or {}).get('name'), 'total': o.get('overUnder'),
                             'spread': o.get('spread'), 'details': o.get('details'),
                             'mlH': (o.get('homeTeamOdds') or {}).get('moneyLine'),
                             'mlA': (o.get('awayTeamOdds') or {}).get('moneyLine')} if o else None})
    if out and all(g['final'] for g in out) and d < dt.date.today() - dt.timedelta(days=1):
        save(fn, out)
    return out


def espn_odds(gid, fresh=False):
    """every book ESPN lists for a game: moneylines, puck line (home handicap) and total, with open/close where given"""
    fn = os.path.join(CACHE, 'espn', 'odds', f'{gid}.json')
    if not fresh and os.path.exists(fn):
        return load(fn)
    j = get(f'{CORE}/events/{gid}/competitions/{gid}/odds?limit=50')
    if j is None:
        return None
    out = []
    for it in j.get('items', []):
        h, a = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}

        def ml(x, k):
            v = ((x.get(k) or {}).get('moneyLine') or {}).get('american')
            return _num(v) if v not in (None, '') else None

        def tot(k):
            v = ((it.get(k) or {}).get('total') or {}).get('american') if isinstance(it.get(k), dict) else None
            return _num(str(v).lstrip('ou')) if v else None
        out.append({'book': (it.get('provider') or {}).get('name'), 'spread': it.get('spread'), 'total': it.get('overUnder'),
                    'mlH': h.get('moneyLine'), 'mlA': a.get('moneyLine'), 'oH': h.get('spreadOdds'), 'oA': a.get('spreadOdds'),
                    'oO': it.get('overOdds'), 'oU': it.get('underOdds'),
                    'open': {'mlH': ml(h, 'open'), 'mlA': ml(a, 'open'), 'total': tot('open')},
                    'close': {'mlH': ml(h, 'close'), 'mlA': ml(a, 'close'), 'total': tot('close')}})
    if out:
        save(fn, out)
    return out


def espn_map(gs, fresh_after=None):
    """NHL game id -> ESPN event id, by date (ET date and the day after, for late starts) and teams"""
    days = sorted({g['day'] for g in gs})
    idx = {}
    def one(ds):
        d = dt.date.fromisoformat(ds)
        return espn_day(d, fresh=bool(fresh_after and d >= fresh_after))
    with ThreadPoolExecutor(8) as ex:
        for ds, evs in zip(days, ex.map(one, days)):
            for e in evs:
                idx[(ds, e['h'], e['a'])] = e['id']
    return {g['id']: idx.get((g['day'], g['h'], g['a'])) for g in gs}


def odds_for(gs, fresh=False, workers=8):
    """ESPN odds for each game with an ESPN id (2019-20 on): {nhl id: [book rows]}"""
    emap = espn_map(gs)
    todo = [(g['id'], emap.get(g['id'])) for g in gs if emap.get(g['id']) and g['day'] >= '2019-10-01']
    with ThreadPoolExecutor(workers) as ex:
        res = ex.map(lambda t: (t[0], espn_odds(t[1], fresh)), todo)
        return {k: v for k, v in res if v}


if __name__ == '__main__':
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    mp = moneypuck_teams()
    for S in range(lo, hi + 1):
        t0 = time.time()
        gs = games(S)
        gl = goalie_logs(S)
        od = odds_for(gs) if S >= 2020 else {}
        nx = sum(1 for g in gs if g['id'] in mp)
        print(S, len(gs), 'games', nx, 'with xG', len(gl), 'goalie-games', len(od), 'with odds', f'{time.time() - t0:.0f}s', flush=True)
