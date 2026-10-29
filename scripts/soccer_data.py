"""Soccer pulls for the SOCCER ARKBOARD (scripts/soccer_games.py, scripts/soccer_players.py): ESPN (every match's
score in the big five leagues, their second tiers, the other UEFA leagues that feed the European cups, the cups
themselves and the domestic cups, one calendar year a request; today's lines from DraftKings; rosters and
injuries), football-data.co.uk (results, shots and the closing 1X2 and over/under prices, for the backtest), and
Understat (expected goals for every big-five match since 2014-15, and each match's rosters and shots for player
values), FotMob (team expected goals in twelve other leagues since 2020-21). Trimmed copies go to scripts/.cache/soccer/ so a finished year is fetched once. Stdlib only.

    python3 scripts/soccer_data.py espn 2010 2027      # calendar years, every league in LEAGUES
    python3 scripts/soccer_data.py fd 2010 2027        # football-data seasons (end years)
    python3 scripts/soccer_data.py fm 2012 2027        # FotMob seasons (Swiss, Polish, Czech leagues; UEFA cups)
    python3 scripts/soccer_data.py fmx 2021 2027       # FotMob team xG, FMX_LG leagues (~3,000 match pages a season)
    python3 scripts/soccer_data.py us 2015 2027        # Understat league seasons (end years)
    python3 scripts/soccer_data.py usm 2015 2027       # Understat match rosters and shots (slow: ~1,800 a season)

Seasons are named by the year they end in (2027 = 2026-27). Teams are ESPN ids, which hold across competitions.
"""
import csv, datetime as dt, gzip, io, json, os, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'soccer')
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
FD = 'https://www.football-data.co.uk/mmz4281'
US = 'https://understat.com'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'

# the five leagues the section covers, then everything that links them: second tiers (promoted sides), the other
# leagues with clubs in the European cups, the cups, the domestic cups (cross-tier games)
BIG5 = ['eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1']
LEAGUES = BIG5 + ['eng.2', 'esp.2', 'ger.2', 'ita.2', 'fra.2',
                  'por.1', 'ned.1', 'bel.1', 'sco.1', 'tur.1', 'aut.1', 'sui.1', 'gre.1', 'den.1', 'nor.1', 'swe.1',
                  'rus.1', 'usa.1', 'pol.1', 'cze.1',
                  'uefa.champions', 'uefa.europa', 'uefa.europa.conf', 'uefa.champions_qual', 'uefa.europa_qual',
                  'uefa.europa.conf_qual', 'uefa.super_cup',
                  'eng.fa', 'eng.league_cup', 'esp.copa_del_rey', 'ger.dfb_pokal', 'ita.coppa_italia',
                  'fra.coupe_de_france']
EURO = {'uefa.champions', 'uefa.europa', 'uefa.europa.conf', 'uefa.champions_qual', 'uefa.europa_qual',
        'uefa.europa.conf_qual', 'uefa.super_cup'}
CUPS = {'eng.fa', 'eng.league_cup', 'esp.copa_del_rey', 'ger.dfb_pokal', 'ita.coppa_italia', 'fra.coupe_de_france'}
NAME = {'eng.1': 'Premier League', 'esp.1': 'La Liga', 'ger.1': 'Bundesliga', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1',
        'eng.2': 'Championship', 'esp.2': 'La Liga 2', 'ger.2': '2. Bundesliga', 'ita.2': 'Serie B', 'fra.2': 'Ligue 2',
        'por.1': 'Primeira Liga', 'ned.1': 'Eredivisie', 'bel.1': 'Belgian Pro League', 'sco.1': 'Scottish Premiership',
        'tur.1': 'Super Lig', 'aut.1': 'Austrian Bundesliga', 'sui.1': 'Swiss Super League', 'gre.1': 'Greek Super League',
        'den.1': 'Danish Superliga', 'nor.1': 'Eliteserien', 'swe.1': 'Allsvenskan', 'rus.1': 'Russian Premier League',
        'usa.1': 'MLS', 'pol.1': 'Ekstraklasa', 'cze.1': 'Czech First League', 'uefa.champions': 'Champions League', 'uefa.europa': 'Europa League',
        'uefa.europa.conf': 'Conference League', 'uefa.champions_qual': 'UCL qualifying',
        'uefa.europa_qual': 'UEL qualifying', 'uefa.europa.conf_qual': 'UECL qualifying', 'uefa.super_cup': 'Super Cup',
        'eng.fa': 'FA Cup', 'eng.league_cup': 'League Cup', 'esp.copa_del_rey': 'Copa del Rey',
        'ger.dfb_pokal': 'DFB-Pokal', 'ita.coppa_italia': 'Coppa Italia', 'fra.coupe_de_france': 'Coupe de France'}
SHORT = {'eng.1': 'EPL', 'esp.1': 'LIGA', 'ger.1': 'BUN', 'ita.1': 'SA', 'fra.1': 'L1', 'uefa.champions': 'UCL',
         'uefa.europa': 'UEL', 'uefa.europa.conf': 'UECL', 'usa.1': 'MLS'}
# the other top flights with tables, sims and matches on the page: every European league at or near the Danish
# Superliga's level (UEFA coefficient or our cross-league rating), strongest first
SHOWN = ['ned.1', 'por.1', 'bel.1', 'tur.1', 'cze.1', 'gre.1', 'pol.1', 'den.1', 'sui.1', 'nor.1', 'aut.1', 'sco.1',
         'swe.1']
# football-data.co.uk division codes and Understat league names
FD_DIV = {'eng.1': 'E0', 'eng.2': 'E1', 'esp.1': 'SP1', 'esp.2': 'SP2', 'ger.1': 'D1', 'ger.2': 'D2', 'ita.1': 'I1',
          'ita.2': 'I2', 'fra.1': 'F1', 'fra.2': 'F2', 'ned.1': 'N1', 'bel.1': 'B1', 'por.1': 'P1', 'tur.1': 'T1',
          'gre.1': 'G1', 'sco.1': 'SC0'}
# football-data.co.uk's "new" files (one CSV a country, every season; result and the closing 1X2 only)
FD_NEW = {'den.1': 'DNK', 'aut.1': 'AUT', 'sui.1': 'SWZ', 'pol.1': 'POL', 'nor.1': 'NOR', 'swe.1': 'SWE', 'usa.1': 'USA'}
# FotMob (www.fotmob.com/api/data/leagues): the leagues ESPN doesn't carry (Switzerland after Sep 2025, Poland and
# Czechia), from season FM_FROM on, and the UEFA cups (only to tie FotMob's club ids to ESPN's)
FM_LG = {'sui.1': 69, 'pol.1': 196, 'cze.1': 122}
FM_FROM = {'sui.1': 2026, 'pol.1': 2011, 'cze.1': 2011}
FM_EURO = {'uefa.champions': 42, 'uefa.europa': 73, 'uefa.europa.conf': 10216, 'uefa.champions_qual': 10611,
           'uefa.europa_qual': 10613, 'uefa.europa.conf_qual': 10615}
FM = 'https://www.fotmob.com/api/data/leagues'
NO_ESPN = {'pol.1', 'cze.1'}
# FotMob team xG (matchDetails) outside the big five: these leagues from FMX_FROM (season end year; calendar leagues
# the year). The other second tiers, Greece, Poland and Czechia have it only from 2026-27.
FMX_LG = {'eng.2': 48, 'ger.2': 146, 'por.1': 61, 'ned.1': 57, 'bel.1': 40, 'sco.1': 64, 'tur.1': 71, 'aut.1': 38,
          'sui.1': 69, 'den.1': 46, 'nor.1': 59, 'swe.1': 67}
FMX_FROM = {'tur.1': 2023, 'ger.2': 2022, 'nor.1': 2020, 'swe.1': 2020}
US_LG = {'eng.1': 'EPL', 'esp.1': 'La_liga', 'ger.1': 'Bundesliga', 'ita.1': 'Serie_A', 'fra.1': 'Ligue_1'}
# calendar-year leagues (spring to autumn): their season is the calendar year
CAL = {'nor.1', 'swe.1', 'usa.1'}


def get(url, tries=4, raw=False, headers=None):
    for i in range(tries):
        try:
            h = {'User-Agent': UA, 'Accept-Encoding': 'gzip'}
            h.update(headers or {})
            r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=90)
            b = r.read()
            if b[:2] == b'\x1f\x8b':
                b = gzip.decompress(b)
            return b if raw else json.loads(b)
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


def season_of(day, lg=''):
    """season end year of a match day ('2026-10-24' -> 2027); calendar leagues -> that year"""
    y, m = int(day[:4]), int(day[5:7])
    if lg in CAL:
        return y
    return y + 1 if m >= 7 else y


def current_season(today=None):
    d = today or dt.date.today()
    return d.year + 1 if d.month >= 7 else d.year


# ---------------------------------------------------------------- ESPN
STATUS = {'STATUS_FULL_TIME': 'FT', 'STATUS_FINAL': 'FT', 'STATUS_FINAL_AET': 'AET', 'STATUS_FINAL_PEN': 'PEN',
          'STATUS_END_OF_EXTRATIME': 'AET', 'STATUS_FINAL_ET': 'AET'}


def _trim(e, lg):
    c = (e.get('competitions') or [{}])[0]
    cs = c.get('competitors') or []
    h = next((x for x in cs if x.get('homeAway') == 'home'), None)
    a = next((x for x in cs if x.get('homeAway') == 'away'), None)
    if not h or not a:
        return None
    st = ((c.get('status') or e.get('status') or {}).get('type') or {})
    name = st.get('name', '')

    def num(x, k):
        try:
            return int(float(x.get(k)))
        except (TypeError, ValueError):
            return None
    r = {'id': e['id'], 'lg': lg, 't': e.get('date'), 'day': (e.get('date') or '')[:10],
         'h': h['team']['id'], 'a': a['team']['id'], 'hn': h['team'].get('displayName'),
         'an': a['team'].get('displayName'), 'hab': h['team'].get('abbreviation'), 'aab': a['team'].get('abbreviation'),
         'st': STATUS.get(name, 'SCHED' if st.get('state') == 'pre' else name.replace('STATUS_', '').lower()),
         'slug': (e.get('season') or {}).get('slug'), 'neu': int(bool(c.get('neutralSite')))}
    if st.get('completed') and r['st'] in ('FT', 'AET', 'PEN'):
        r['hs'], r['as'] = num(h, 'score'), num(a, 'score')
        if r['st'] == 'PEN':
            r['hp'], r['ap'] = num(h, 'shootoutScore'), num(a, 'shootoutScore')
        r['hw'] = int(bool(h.get('winner')))
    if c.get('leg'):
        r['leg'] = (c['leg'] or {}).get('value')
    ser = c.get('series') or {}
    if ser.get('title'):
        r['ser'] = ser.get('title')
    return r


def espn_year(lg, y, fresh=False):
    """every match ESPN lists for league lg in calendar year y (finished years are cached for good)"""
    p = os.path.join(CACHE, 'espn', f'{lg}_{y}.json.gz')
    done = y < dt.date.today().year
    if os.path.exists(p) and not fresh and (done or time.time() - os.path.getmtime(p) < 3 * 3600):
        return load(p)
    d = get(f'{ESPN}/{lg}/scoreboard?dates={y}&limit=1000')
    if d is None:
        return load(p) if os.path.exists(p) else []
    rows, seen = [], set()
    for e in d.get('events') or []:
        r = _trim(e, lg)
        if not r:
            continue
        k = (r['day'], r['h'], r['a'])          # ESPN lists some old matches twice under two ids
        if k in seen:
            continue
        seen.add(k)
        rows.append(r)
    save(p, rows)
    return rows


def espn_day(lg, day):
    """one day's scoreboard, uncached, with DraftKings' line where ESPN has one (today's and tomorrow's matches)"""
    d = get(f"{ESPN}/{lg}/scoreboard?dates={day.replace('-', '')}")
    out = []
    for e in (d or {}).get('events') or []:
        r = _trim(e, lg)
        if not r:
            continue
        c = (e.get('competitions') or [{}])[0]
        o = next((x for x in (c.get('odds') or []) if x), None)
        if o:
            def ml(k):
                try:
                    return float(((o.get(k) or {}).get('moneyLine')))
                except (TypeError, ValueError):
                    return None
            r['dk'] = {'h': ml('homeTeamOdds'), 'd': ml('drawOdds'), 'a': ml('awayTeamOdds'), 'ou': o.get('overUnder')}
        r['venue'] = ((c.get('venue') or {}).get('fullName'))
        out.append(r)
    return out


def espn_all(y0, y1, fresh=False):
    jobs = [(lg, y) for y in range(y0, y1 + 1) for lg in LEAGUES if lg not in NO_ESPN]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda j: (j, espn_year(*j, fresh=fresh)), jobs))
    for (lg, y), rows in res:
        if rows:
            print(lg, y, len(rows), flush=True)


def espn_teams(lg):
    d = get(f'{ESPN}/{lg}/teams')
    out = {}
    for sp in (d or {}).get('sports') or []:
        for L in sp.get('leagues') or []:
            for t in L.get('teams') or []:
                t = t.get('team') or {}
                out[t.get('id')] = {'name': t.get('displayName'), 'ab': t.get('abbreviation'),
                                    'short': t.get('shortDisplayName'), 'logo': ((t.get('logos') or [{}])[0]).get('href')}
    return out


def espn_roster(lg, tid):
    return get(f'{ESPN}/{lg}/teams/{tid}/roster')


# ---------------------------------------------------------------- football-data.co.uk
def _fl(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def fd_new(lg, S, fresh=False):
    """season S from football-data.co.uk's one-file-a-country CSV (Pinnacle, Betfair Exchange and average closing 1X2)"""
    code = FD_NEW.get(lg)
    if not code:
        return []
    p = os.path.join(CACHE, 'fd', f'new_{code}.json.gz')
    if os.path.exists(p) and not fresh and time.time() - os.path.getmtime(p) < 6 * 3600:
        rows = load(p)
    else:
        b = get(f'https://football-data.co.uk/new/{code}.csv', raw=True)
        if not b:
            rows = load(p) if os.path.exists(p) else []
        else:
            rows = []
            for r in csv.DictReader(io.StringIO(b.decode('utf-8-sig', errors='replace'))):
                dd = (r.get('Date') or '').strip().split('/')
                if len(dd) != 3 or not r.get('Home'):
                    continue
                try:
                    day = dt.date(int(dd[2]) + (2000 if len(dd[2]) == 2 else 0), int(dd[1]), int(dd[0])).isoformat()
                    hs, as_ = int(float(r['HG'])), int(float(r['AG']))
                except (ValueError, TypeError, KeyError):
                    continue
                sn = (r.get('Season') or '').strip()
                o = {'S': int(sn[-4:]) if sn[-4:].isdigit() else season_of(day, lg), 'day': day, 'h': r['Home'].strip(),
                     'a': r['Away'].strip(), 'hs': hs, 'as': as_}
                for tag, cols in (('pc', ('PSCH', 'PSCD', 'PSCA')), ('bc', ('BFECH', 'BFECD', 'BFECA')),
                                  ('ac', ('AvgCH', 'AvgCD', 'AvgCA'))):
                    v = [_fl(r.get(c)) for c in cols]
                    if all(v):
                        o[tag] = v
                rows.append(o)
            save(p, rows)
    return [o for o in rows if o['S'] == S]


def fd_season(lg, S, fresh=False):
    """football-data.co.uk's season S for league lg: date, teams, score, shots, and the 1X2 and over/under 2.5 prices
    (Pinnacle and the market average, at the open and the close; before 2019-20 the files carry one Pinnacle price,
    taken shortly before kickoff)"""
    div = FD_DIV.get(lg)
    if not div:
        return fd_new(lg, S, fresh)
    code = f'{(S - 1) % 100:02d}{S % 100:02d}'
    p = os.path.join(CACHE, 'fd', f'{div}_{code}.json.gz')
    if os.path.exists(p) and not fresh and (S < current_season() or time.time() - os.path.getmtime(p) < 6 * 3600):
        return load(p)
    b = get(f'{FD}/{code}/{div}.csv', raw=True)
    if not b:
        return load(p) if os.path.exists(p) else []
    txt = b.decode('utf-8-sig', errors='replace')
    rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        if not r.get('HomeTeam') or not r.get('Date'):
            continue
        dd = r['Date'].strip().split('/')
        if len(dd) != 3:
            continue
        yy = int(dd[2]) + (2000 if len(dd[2]) == 2 else 0)
        try:
            day = dt.date(yy, int(dd[1]), int(dd[0])).isoformat()
        except ValueError:
            continue

        def g(k):
            try:
                return int(float(r.get(k)))
            except (TypeError, ValueError):
                return None
        o = {'day': day, 'h': r['HomeTeam'].strip(), 'a': r['AwayTeam'].strip(), 'hs': g('FTHG'), 'as': g('FTAG'),
             'hsh': g('HS'), 'ash': g('AS'), 'hst': g('HST'), 'ast': g('AST'), 'hr': g('HR'), 'ar': g('AR')}
        # closing: Pinnacle close (to 2025-26), Betfair Exchange close (2024-25 on), else the average close; before
        # 2019-20 the lone Pinnacle columns (PSH) were close-ish
        for tag, cols in (('pc', ('PSCH', 'PSCD', 'PSCA')), ('bc', ('BFECH', 'BFECD', 'BFECA')),
                          ('bfo', ('BFEH', 'BFED', 'BFEA')), ('ac', ('AvgCH', 'AvgCD', 'AvgCA')),
                          ('po', ('PSH', 'PSD', 'PSA')), ('ao', ('AvgH', 'AvgD', 'AvgA')),
                          ('bo', ('BbAvH', 'BbAvD', 'BbAvA')), ('b365', ('B365H', 'B365D', 'B365A'))):
            v = [_fl(r.get(c)) for c in cols]
            if all(v):
                o[tag] = v
        for tag, cols in (('ouc', ('PC>2.5', 'PC<2.5')), ('oubc', ('BFEC>2.5', 'BFEC<2.5')),
                          ('ouac', ('AvgC>2.5', 'AvgC<2.5')), ('ouo', ('P>2.5', 'P<2.5')),
                          ('oua', ('Avg>2.5', 'Avg<2.5')), ('oubb', ('BbAv>2.5', 'BbAv<2.5'))):
            v = [_fl(r.get(c)) for c in cols]
            if all(v):
                o[tag] = v
        try:                                            # match xG, 2026-27 on
            o['hxg'], o['axg'] = float(r['HxG']), float(r['AxG'])
        except (TypeError, ValueError, KeyError):
            pass
        rows.append(o)
    save(p, rows)
    return rows


# ---------------------------------------------------------------- FotMob
def fm_season(lg, S, fresh=False):
    """FotMob's season S (end year) of competition lg as ESPN-shaped rows; team ids are FotMob's ('f' + id: soccer_games
    swaps in ESPN's id where the club has one). Finished seasons are cached for good."""
    fid = FM_LG.get(lg) or FM_EURO.get(lg)
    p = os.path.join(CACHE, 'fm', f'{fid}_{S}.json.gz')
    if os.path.exists(p) and not fresh and (S < current_season() or time.time() - os.path.getmtime(p) < 3 * 3600):
        return load(p)
    d = get(f'{FM}?id={fid}&season={S - 1}%2F{S}')
    if not d or (d.get('details') or {}).get('selectedSeason') != f'{S - 1}/{S}':
        return load(p) if os.path.exists(p) else []
    rows = []
    for m in (d.get('fixtures') or {}).get('allMatches') or []:
        st = m.get('status') or {}
        t = st.get('utcTime') or ''
        if not t:
            continue
        h, a = m['home'], m['away']
        r = {'id': 'fm' + str(m['id']), 'lg': lg, 't': t[:16] + 'Z', 'day': t[:10], 'h': 'f' + str(h['id']),
             'a': 'f' + str(a['id']), 'hn': h.get('name'), 'an': a.get('name'), 'hab': None, 'aab': None,
             'st': 'SCHED', 'slug': None, 'neu': 0, 'src': 'fm'}
        if st.get('cancelled'):
            r['st'] = 'canceled'
        elif st.get('finished'):
            try:
                hs, as_ = [int(x) for x in (st.get('scoreStr') or '').split(' - ')]
            except ValueError:
                continue
            short = ((st.get('reason') or {}).get('short') or 'FT').upper()
            r['st'] = 'PEN' if short.startswith('PEN') else 'AET' if short == 'AET' else 'FT'
            r['hs'], r['as'], r['hw'] = hs, as_, int(hs > as_)
        rows.append(r)
    save(p, rows)
    return rows


FMX_KEYS = {'expected_goals', 'expected_goals_open_play', 'expected_goals_set_play', 'expected_goals_non_penalty',
            'expected_goals_on_target', 'total_shots', 'ShotsOnTarget', 'big_chance', 'BallPossesion', 'red_cards'}


def fm_match_stats(lg, S, m):
    """one finished FotMob match's team stats (the xG family, shots), cached for good"""
    p = os.path.join(CACHE, 'fmx', f'{m["id"]}.json')
    if os.path.exists(p):
        o = json.load(open(p))
        # a page saved before FotMob posted the match's xG is asked again for three days
        if o['st'].get('expected_goals') or (o.get('t') or '9')[:10] < (dt.date.today() - dt.timedelta(days=3)).isoformat():
            return o
    d = get(f'https://www.fotmob.com/api/data/matchDetails?matchId={m["id"]}', tries=2)
    if d is None:
        return None
    o = {'id': m['id'], 'lg': lg, 'S': S, 't': m['status'].get('utcTime'), 'h': m['home']['id'], 'a': m['away']['id'],
         'hn': m['home'].get('name'), 'an': m['away'].get('name'), 'sc': m['status'].get('scoreStr'), 'st': {}}
    try:
        for g in d['content']['stats']['Periods']['All']['stats']:
            for x in g['stats']:
                if x.get('key') in FMX_KEYS and x.get('stats'):
                    o['st'][x['key']] = x['stats']
    except (KeyError, TypeError):
        pass
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, 'w'))
    return o


def fm_xg(lg, S, fresh=False, budget=None):
    """FotMob team xG for league lg's season S: [{day, hn, an, hs, as, hx, ax}] for its finished matches that have it.
    budget: stop fetching new match pages after this many seconds (the rest come on the next run)"""
    fid = FMX_LG.get(lg)
    if not fid or S < FMX_FROM.get(lg, 2020 if lg in CAL else 2021):
        return []
    p = os.path.join(CACHE, 'fmx', f'season_{fid}_{S}.json.gz')
    if os.path.exists(p) and not fresh and (S < current_season() or time.time() - os.path.getmtime(p) < 3 * 3600):
        ms = load(p)
    else:
        sea = str(S) if lg in CAL else f'{S - 1}%2F{S}'
        d = get(f'{FM}?id={fid}&season={sea}', tries=2)
        if not d:
            ms = load(p) if os.path.exists(p) else []
        else:
            ms = [{'id': m['id'], 'status': {'utcTime': (m.get('status') or {}).get('utcTime'),
                                             'scoreStr': (m.get('status') or {}).get('scoreStr')},
                   'home': {'id': m['home']['id'], 'name': m['home'].get('name')},
                   'away': {'id': m['away']['id'], 'name': m['away'].get('name')}}
                  for m in (d.get('fixtures') or {}).get('allMatches') or []
                  if (m.get('status') or {}).get('finished') and not (m.get('status') or {}).get('cancelled')]
            save(p, ms)
    t0 = time.time()

    def one(m):
        if budget is not None and time.time() - t0 > budget and not os.path.exists(os.path.join(CACHE, 'fmx', f'{m["id"]}.json')):
            return None
        return fm_match_stats(lg, S, m)
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(one, ms))
    out = []
    for o in got:
        xg = (o or {}).get('st', {}).get('expected_goals')
        if not xg or not o.get('t'):
            continue
        try:
            hs, as_ = [int(x) for x in o['sc'].split(' - ')]
            hx, ax = float(xg[0]), float(xg[1])
        except (ValueError, AttributeError, TypeError):
            continue
        out.append({'day': o['t'][:10], 'hn': o['hn'], 'an': o['an'], 'hs': hs, 'as': as_, 'hx': hx, 'ax': ax})
    return out


# ---------------------------------------------------------------- Understat
XHR = {'X-Requested-With': 'XMLHttpRequest'}


def us_league(lg, S, fresh=False):
    """Understat's league season (S end year): matches with xG, team match histories, player season totals"""
    name = US_LG.get(lg)
    if not name or S < 2015:
        return None
    p = os.path.join(CACHE, 'us', f'{name}_{S}.json.gz')
    if os.path.exists(p) and not fresh and (S < current_season() or time.time() - os.path.getmtime(p) < 6 * 3600):
        return load(p)
    d = get(f'{US}/getLeagueData/{name}/{S - 1}', headers=XHR)
    if not d:
        return load(p) if os.path.exists(p) else None
    out = {'matches': [], 'players': d.get('players') or [], 'teams': {}}
    for m in d.get('dates') or []:
        out['matches'].append({'id': m['id'], 'res': bool(m.get('isResult')), 't': m.get('datetime'),
                               'h': m['h']['title'], 'a': m['a']['title'], 'hid': m['h']['id'], 'aid': m['a']['id'],
                               'hg': m['goals']['h'], 'ag': m['goals']['a'], 'hx': m['xG']['h'], 'ax': m['xG']['a'],
                               'fc': m.get('forecast')})
    for tid, t in (d.get('teams') or {}).items():
        out['teams'][tid] = {'title': t.get('title'), 'history': [
            {k: v for k, v in h.items() if k in ('h_a', 'xG', 'xGA', 'npxG', 'npxGA', 'deep', 'deep_allowed', 'scored',
                                                 'missed', 'date', 'ppda', 'ppda_allowed')} for h in t.get('history') or []]}
    save(p, out)
    return out


def us_match(mid, fresh=False):
    """one Understat match: rosters (minutes, position, subs) and shots (minute, xG, player)"""
    p = os.path.join(CACHE, 'usm', str(mid)[-2:], f'{mid}.json.gz')
    if os.path.exists(p) and not fresh:
        return load(p)
    d = get(f'{US}/getMatchData/{mid}', headers=XHR)
    if not d or 'rosters' not in d:
        return None
    ro = {s: [{k: v.get(k) for k in ('id', 'player_id', 'player', 'position', 'positionOrder', 'time', 'roster_in',
                                       'roster_out', 'goals', 'own_goals', 'shots', 'xG', 'assists', 'xA', 'key_passes',
                                       'xGChain', 'xGBuildup', 'yellow_card', 'red_card', 'team_id')}
              for v in (d['rosters'].get(s) or {}).values()] for s in ('h', 'a')}
    sh = {s: [[x.get('minute'), x.get('xG'), x.get('player_id'), x.get('result'), x.get('situation'),
               x.get('player_assisted')] for x in (d['shots'].get(s) or [])] for s in ('h', 'a')}
    out = {'ro': ro, 'sh': sh}
    save(p, out)
    return out


def us_matches(S0, S1):
    ids = []
    for S in range(S0, S1 + 1):
        for lg in BIG5:
            d = us_league(lg, S)
            ids += [m['id'] for m in (d or {}).get('matches', []) if m['res']]
    todo = [i for i in ids if not os.path.exists(os.path.join(CACHE, 'usm', str(i)[-2:], f'{i}.json.gz'))]
    print(len(ids), 'matches,', len(todo), 'to fetch', flush=True)
    n = [0]

    def one(i):
        us_match(i)
        n[0] += 1
        if n[0] % 500 == 0:
            print(n[0], flush=True)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, todo))


if __name__ == '__main__':
    what, a, b = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    if what == 'espn':
        espn_all(a, b)
    elif what == 'fd':
        for S in range(a, b + 1):
            for lg in FD_DIV:
                print(lg, S, len(fd_season(lg, S)), flush=True)
    elif what == 'fm':
        for S in range(a, b + 1):
            for lg in list(FM_LG) + list(FM_EURO):
                if lg in FM_EURO or S >= FM_FROM[lg] or lg == 'sui.1' and S >= 2012:
                    print(lg, S, len(fm_season(lg, S)), flush=True)
    elif what == 'fmx':
        for S in range(a, b + 1):
            for lg in FMX_LG:
                print(lg, S, len(fm_xg(lg, S)), flush=True)
    elif what == 'us':
        for S in range(a, b + 1):
            for lg in BIG5:
                d = us_league(lg, S)
                print(lg, S, d and len(d['matches']), flush=True)
    elif what == 'usm':
        us_matches(a, b)
