"""ESPN NBA pulls for the game model (scripts/nba_games.py): schedule and scores, box-score minutes and team lines,
and every sportsbook's spread, total and moneyline. Trimmed copies go to scripts/.cache/nba/espn/ so a game is
fetched once; final games never change. Stdlib only.

    python3 scripts/nba_espn.py 2013 2026      # seasons from..to (end year), for the backtest history
"""
import datetime as dt, json, os, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nba', 'espn')
SITE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
TEAMS = {'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GS', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA',
         'MIL', 'MIN', 'NO', 'NY', 'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SA', 'TOR', 'UTAH', 'WSH'}
ALIAS = {'NJ': 'BKN', 'NOH': 'NO', 'NOR': 'NO', 'GSW': 'GS', 'NYK': 'NY', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH',
         'PHO': 'PHX', 'NOP': 'NO', 'BRK': 'BKN', 'CHO': 'CHA'}


def team(a):
    return ALIAS.get(a, a)


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            return json.load(urllib.request.urlopen(req, timeout=30))
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
    with open(tmp, 'w') as f:
        json.dump(obj, f, separators=(',', ':'))
    os.replace(tmp, path)


def day(d, fresh=False):
    """one date's games: id, tip (UTC), season and type, neutral site, teams and scores, state, ESPN's current odds"""
    fn = os.path.join(CACHE, 'sb', d.strftime('%Y%m%d') + '.json')
    if not fresh and os.path.exists(fn):
        return json.load(open(fn))
    j = get(f'{SITE}/scoreboard?dates={d.strftime("%Y%m%d")}')
    if j is None:
        return []
    out = []
    for e in j.get('events', []):
        c = e['competitions'][0]
        side = {x['homeAway']: x for x in c['competitors']}
        if 'home' not in side or 'away' not in side:
            continue
        h, a = team(side['home']['team'].get('abbreviation', '')), team(side['away']['team'].get('abbreviation', ''))
        if h not in TEAMS or a not in TEAMS:
            continue                                   # all-star and exhibition games
        st = c['status']['type']
        o = (c.get('odds') or [{}])[0]
        out.append({'id': e['id'], 'tip': e['date'], 'season': e['season']['year'], 'type': e['season']['type'],
                    'neutral': bool(c.get('neutralSite')), 'h': h, 'a': a,
                    'hs': int(side['home'].get('score') or 0), 'as': int(side['away'].get('score') or 0),
                    'state': st.get('state'), 'final': bool(st.get('completed')),
                    'venue': (c.get('venue') or {}).get('fullName'), 'note': ' '.join(n.get('headline', '') for n in c.get('notes', [])),
                    'odds': {'spread': o.get('spread'), 'total': o.get('overUnder'), 'details': o.get('details'),
                             'mlH': ((o.get('homeTeamOdds') or {}).get('moneyLine')), 'mlA': ((o.get('awayTeamOdds') or {}).get('moneyLine'))} if o else None})
    if all(g['final'] for g in out) and d < dt.date.today() - dt.timedelta(days=1):
        save(fn, out)
    return out


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def box(gid, fresh=False):
    """minutes by player (ESPN athlete id, name, starter, DNP reason) and team counting lines for possessions"""
    fn = os.path.join(CACHE, 'box', gid + '.json')
    if not fresh and os.path.exists(fn):
        return json.load(open(fn))
    j = get(f'{SITE}/summary?event={gid}')
    if j is None or 'boxscore' not in j:
        return None
    out = {'teams': {}, 'players': {}}
    for t in j['boxscore'].get('teams', []):
        ab = team(t['team']['abbreviation'])
        s = {x['name']: x.get('displayValue') for x in t.get('statistics', [])}
        line = {}
        for key, nm in (('fg', 'fieldGoalsMade-fieldGoalsAttempted'), ('ft', 'freeThrowsMade-freeThrowsAttempted'),
                        ('fg3', 'threePointFieldGoalsMade-threePointFieldGoalsAttempted')):
            v = (s.get(nm) or '').split('-')
            if len(v) == 2:
                line[key] = [_num(v[0]), _num(v[1])]
        line['oreb'] = _num(s.get('offensiveRebounds'))
        line['tov'] = _num(s.get('totalTurnovers', s.get('turnovers')))
        out['teams'][ab] = line
    for t in j['boxscore'].get('players', []):
        ab = team(t['team']['abbreviation'])
        rows = []
        for st in t.get('statistics', [])[:1]:
            names = st.get('names') or st.get('labels') or []
            for p in st.get('athletes', []):
                a = p.get('athlete', {})
                d = dict(zip(names, p.get('stats', [])))
                mn = _num(d.get('MIN'))
                rows.append([a.get('id'), a.get('displayName'), mn or 0.0, 1 if p.get('starter') else 0,
                             None if mn else (p.get('reason') or ('DNP' if p.get('didNotPlay') else None))])
        out['players'][ab] = rows
    save(fn, out)
    return out


def odds(gid, fresh=False):
    """every book ESPN lists: spread (home side, negative = home favored), total, moneylines, and open/close where given"""
    fn = os.path.join(CACHE, 'odds', gid + '.json')
    if not fresh and os.path.exists(fn):
        return json.load(open(fn))
    j = get(f'{CORE}/events/{gid}/competitions/{gid}/odds?limit=50')
    if j is None:
        return None
    out = []
    for it in j.get('items', []):
        h, a = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}

        def ps(x, k):
            v = ((x.get(k) or {}).get('pointSpread') or {}).get('american')
            return _num(str(v).replace('PK', '0')) if v not in (None, '') else None

        def ml(x, k):
            v = ((x.get(k) or {}).get('moneyLine') or {}).get('american')
            return _num(str(v).replace('EVEN', '100')) if v not in (None, '') else None

        def tot(k):
            v = ((it.get(k) or {}).get('total') or {}).get('american') if isinstance(it.get(k), dict) else None
            return _num(str(v).lstrip('ou')) if v else None
        out.append({'book': (it.get('provider') or {}).get('name'), 'spread': it.get('spread'), 'total': it.get('overUnder'),
                    'mlH': h.get('moneyLine'), 'mlA': a.get('moneyLine'), 'oH': h.get('spreadOdds'), 'oA': a.get('spreadOdds'),
                    'hFav': h.get('favorite'),
                    'open': {'spread': ps(h, 'open'), 'mlH': ml(h, 'open'), 'mlA': ml(a, 'open'), 'total': tot('open')},
                    'close': {'spread': ps(h, 'close'), 'mlH': ml(h, 'close'), 'mlA': ml(a, 'close'), 'total': tot('close')}})
    if out:
        save(fn, out)
    return out


def season_days(S):
    """dates that can hold games of the season ending in year S (the 2020 bubble ran to October, 2021 into July)"""
    lo = dt.date(S - 1, 12, 15) if S == 2021 else dt.date(S - 1, 10, 1)
    hi = dt.date(2020, 10, 15) if S == 2020 else dt.date(S, 7, 25) if S == 2021 else dt.date(S, 6, 30)
    d = lo
    while d <= hi:
        yield d
        d += dt.timedelta(days=1)


def games(S, fresh_after=None):
    """every game of season S in tip order (ESPN season year = S, preseason excluded)"""
    out, seen = [], set()
    days = list(season_days(S))
    with ThreadPoolExecutor(8) as ex:
        for gs in ex.map(lambda d: day(d, fresh=bool(fresh_after and d >= fresh_after)), days):
            for g in gs:
                if g['season'] == S and g['type'] in (2, 3, 5) and g['id'] not in seen:
                    seen.add(g['id']); out.append(g)
    out.sort(key=lambda g: (g['tip'], g['id']))
    return out


def details(gs, fresh=False, workers=8, soon=3):
    """box and odds for each final game, and fresh odds for games in the next few days (later ones: none yet)"""
    edge = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=soon)).strftime('%Y-%m-%dT%H:%MZ')

    def one(g):
        if not g['final'] and g['tip'] > edge:
            return g['id'], None, None
        b = box(g['id'], fresh) if g['final'] else None
        o = odds(g['id'], fresh or not g['final'])
        return g['id'], b, o
    with ThreadPoolExecutor(workers) as ex:
        return {gid: (b, o) for gid, b, o in ex.map(one, gs)}


if __name__ == '__main__':
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    for S in range(lo, hi + 1):
        t0 = time.time()
        gs = games(S)
        det = details(gs)
        nb = sum(1 for b, o in det.values() if b); no = sum(1 for b, o in det.values() if o)
        print(S, len(gs), 'games', nb, 'boxes', no, 'with odds', f'{time.time() - t0:.0f}s', flush=True)
