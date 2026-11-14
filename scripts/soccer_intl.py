#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""National-team soccer for the SOCCER ARKBOARD (data/soccer_intl.json) and the model behind it
(data/soccer_intl_fit.json).

    python3 scripts/soccer_intl.py            # ratings, ARK Ranking, upcoming matches, Nations League odds
    python3 scripts/soccer_intl.py --sq       # squad values by nation from the Transfermarkt dump -> scripts/data/soccer_intl_sq.json.gz
    python3 scripts/soccer_intl.py --odds     # DraftKings open/close 1X2 and totals for ESPN's international matches -> scripts/data/soccer_intl_odds.json.gz
    python3 scripts/soccer_intl.py --fit      # tune on 2000-15, walk forward 2016+, score against the close, test picks

Data (free): every full international since 1872 with its tournament and neutral flag (github.com/martj42/
international_results, results.csv and shootouts.csv), ESPN's scoreboards for the international competitions
(recent results the file hasn't reached yet, fixtures, extra time, and DraftKings' opening and closing prices through
ESPN's core API from mid-2024), Transfermarkt's market value history (dcaribou/transfermarkt-datasets) for squad values.

Ratings: every nation has an attack and a defence (log goals a match). Expected goals for the home side
    log lambda_h = m + H/2 (not at a neutral venue) + a_h - d_a + sq x (q_h - q_a) / 2
with q the log of the nation's top-23 Transfermarkt values on the day. After each match both terms move by
k x w(tournament) x (goals - lambda) (goals capped), new nations learn faster, and ratings drift back toward zero
between matches. 1X2 from a Dixon-Coles score matrix. An Elo rating (World Football Elo's K and goal multiplier) is
kept beside it as the comparison model. Settings are tuned on 2000-15 walk-forward log loss and scored once on 2016+.
"""
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D  # noqa: E402

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'soccer', 'intl')
OUT = os.path.join(ROOT, 'data', 'soccer_intl.json')
FIT = os.path.join(ROOT, 'data', 'soccer_intl_fit.json')
SQF = os.path.join(HERE, 'data', 'soccer_intl_sq.json.gz')
ODDSF = os.path.join(HERE, 'data', 'soccer_intl_odds.json.gz')
MAPF = os.path.join(HERE, 'data', 'soccer_intl_map.json')
MJ = 'https://raw.githubusercontent.com/martj42/international_results/master'
CORE = 'https://sports.core.api.espn.com/v2/sports/soccer/leagues'
TM_DUMP = 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip'

# ESPN's international competitions (slug -> label shown on the page)
INTL = {'fifa.world': 'World Cup', 'uefa.euro': 'Euro', 'uefa.nations': 'Nations League', 'uefa.euroq': 'Euro qual.',
        'fifa.worldq.uefa': 'WC qual. UEFA', 'fifa.worldq.conmebol': 'WC qual. CONMEBOL',
        'fifa.worldq.concacaf': 'WC qual. CONCACAF', 'fifa.worldq.caf': 'WC qual. CAF', 'fifa.worldq.afc': 'WC qual. AFC',
        'fifa.worldq.ofc': 'WC qual. OFC', 'fifa.friendly': 'Friendly', 'conmebol.america': 'Copa América',
        'concacaf.gold': 'Gold Cup', 'concacaf.nations.league': 'CONCACAF NL', 'caf.nations': 'AFCON',
        'afc.asian.cup': 'Asian Cup'}
SHORT = {'fifa.world': 'WORLD CUP', 'uefa.euro': 'EURO', 'uefa.nations': 'NATIONS LEAGUE', 'uefa.euroq': 'EURO QUAL',
         'fifa.worldq.uefa': 'WCQ', 'fifa.worldq.conmebol': 'WCQ', 'fifa.worldq.concacaf': 'WCQ', 'fifa.worldq.caf': 'WCQ',
         'fifa.worldq.afc': 'WCQ', 'fifa.worldq.ofc': 'WCQ', 'fifa.friendly': 'FRIENDLY', 'conmebol.america': 'COPA',
         'concacaf.gold': 'GOLD CUP', 'concacaf.nations.league': 'CONCACAF NL', 'caf.nations': 'AFCON',
         'afc.asian.cup': 'ASIAN CUP'}
ODDS_FROM = '2024-06-01'      # ESPN's core API keeps its partner book's (ESPN BET, then DraftKings) open and close for international matches from about here

# not FIFA members' football (CONIFA, island games and the like): left out of the history
SKIP_T = ('CONIFA', 'Island Games', 'Viva World Cup', 'Inter Games', 'Muratti Vase', 'ELF Cup', 'Coupe de l',
          'Niamh Challenge', 'Corsica Cup', 'Tynwald Hill', 'Wild Cup', 'FIFI Wild Cup', 'Indian Ocean Island Games',
          'Pacific Mini Games', 'Pacific Games', 'South Pacific Games', 'Arctic', 'Atlantic Heritage Cup', 'Benedikt Fontanive',
          'Dragon Cup', 'Island', 'Mauritius Four Nations')


def cat_of(t):
    """tournament -> weight class: wc (World Cup finals), cf (continental finals), q (qualifiers), nl (Nations
    Leagues), f (friendlies), o (other tournaments)"""
    if t == 'FIFA World Cup':
        return 'wc'
    if 'qualification' in t:
        return 'q'
    if 'Nations League' in t:
        return 'nl'
    if t in ('UEFA Euro', 'Copa América', 'African Cup of Nations', 'AFC Asian Cup', 'Gold Cup', 'Confederations Cup',
             'CONCACAF Championship', 'Oceania Nations Cup'):
        return 'cf'
    if t == 'Friendly':
        return 'f'
    return 'o'


# ---------------------------------------------------------------- data
def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': D.UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def mj_rows(fresh=False):
    """martj42 results.csv as rows (date, h, a, hs, as, t, neu), cached 12 hours"""
    os.makedirs(CACHE, exist_ok=True)
    out = {}
    for f in ('results', 'shootouts'):
        p = os.path.join(CACHE, f + '.csv')
        if fresh or not os.path.exists(p) or dt.datetime.now().timestamp() - os.path.getmtime(p) > 12 * 3600:
            try:
                b = _get(f'{MJ}/{f}.csv')
                if len(b) > 1000:
                    open(p, 'wb').write(b)
            except Exception as e:
                print(f'martj42 {f}: {e!r}, using the cache', file=sys.stderr)
        out[f] = list(csv.DictReader(open(p, encoding='utf-8')))
    so = {(r['date'], r['home_team'], r['away_team']): r['winner'] for r in out['shootouts']}
    rows = []
    for r in out['results']:
        if any(s in r['tournament'] for s in SKIP_T):
            continue
        try:
            hs, as_ = int(r['home_score']), int(r['away_score'])
        except (TypeError, ValueError):
            continue
        k = (r['date'], r['home_team'], r['away_team'])
        rows.append({'day': r['date'], 'h': r['home_team'], 'a': r['away_team'], 'hs': hs, 'as': as_,
                     't': r['tournament'], 'neu': int(r['neutral'].upper() == 'TRUE'), 'so': so.get(k),
                     'cat': cat_of(r['tournament'])})
    return rows


def espn_rows(y0, y1):
    """ESPN's international matches, calendar years y0..y1 (finished years cached for good by soccer_data)"""
    jobs = [(lg, y) for y in range(y0, y1 + 1) for lg in INTL]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda j: D.espn_year(*j), jobs))
    out = []
    for rs in res:
        out += rs or []
    return out


NAME_FIX = {  # ESPN -> martj42 where the vote can't see a match yet (new or rare sides)
    'USA': 'United States', 'Republic of Ireland': 'Republic of Ireland', 'Türkiye': 'Turkey', 'Czechia': 'Czech Republic',
    "Côte d'Ivoire": 'Ivory Coast', 'Korea Republic': 'South Korea', 'IR Iran': 'Iran', 'China PR': 'China PR',
    'Congo DR': 'DR Congo', 'Cabo Verde': 'Cape Verde', 'Bosnia-Herzegovina': 'Bosnia and Herzegovina',
    'Bosnia & Herzegovina': 'Bosnia and Herzegovina', 'Curacao': 'Curaçao', 'North Korea': 'North Korea',
    'Korea DPR': 'North Korea', 'Chinese Taipei': 'Taiwan', 'Kyrgyz Republic': 'Kyrgyzstan', 'St. Kitts and Nevis': 'Saint Kitts and Nevis',
    'St. Lucia': 'Saint Lucia', 'St. Vincent and the Grenadines': 'Saint Vincent and the Grenadines', 'The Gambia': 'Gambia',
    'Gambia': 'Gambia', 'Brunei Darussalam': 'Brunei', 'Timor-Leste': 'East Timor', 'Eswatini': 'Eswatini',
    'São Tomé and Príncipe': 'São Tomé and Príncipe', 'Sao Tome and Principe': 'São Tomé and Príncipe', 'Macau': 'Macau',
    'Hong Kong, China': 'Hong Kong', 'United States Virgin Islands': 'United States Virgin Islands', 'US Virgin Islands': 'United States Virgin Islands',
}


def name_map(mj, es):
    """ESPN display name -> martj42 name by votes over shared finished matches (same day +-1, same score)"""
    names = {r['h'] for r in mj} | {r['a'] for r in mj}
    votes = defaultdict(Counter)
    idx = defaultdict(list)
    for r in mj:
        if r['day'] >= '2004-01-01':
            idx[r['day']].append(r)
    for e in es:
        if e.get('hs') is None:
            continue
        d0 = dt.date.fromisoformat(e['day'])
        cands = []
        for k in (-1, 0, 1):
            for r in idx.get((d0 + dt.timedelta(days=k)).isoformat(), []):
                if (r['hs'], r['as']) == (e['hs'], e['as']):
                    cands.append((r['h'], r['a']))
                elif (r['as'], r['hs']) == (e['hs'], e['as']):
                    cands.append((r['a'], r['h']))
        hit = [c for c in cands if c[0] == NAME_FIX.get(e['hn'], e['hn']) or c[1] == NAME_FIX.get(e['an'], e['an'])]
        if len(hit) == 1:
            votes[e['hn']][hit[0][0]] += 1
            votes[e['an']][hit[0][1]] += 1
    out = {}
    for n in {e['hn'] for e in es} | {e['an'] for e in es}:
        v = votes.get(n)
        if v and v.most_common(1)[0][1] >= 2:
            out[n] = v.most_common(1)[0][0]
        elif NAME_FIX.get(n, n) in names:
            out[n] = NAME_FIX.get(n, n)
    return out


def load(fresh=False, y0=2018):
    """history (martj42, with ESPN's results after the file's last day and ESPN's extra-time flags), ESPN's
    upcoming matches, and the ESPN -> martj42 name map"""
    mj = mj_rows(fresh)
    today = dt.date.today()
    es = espn_rows(y0, today.year + (1 if today.month >= 11 else 0))
    mp = name_map(mj, es)
    json.dump(mp, open(MAPF, 'w'), indent=0, sort_keys=True, ensure_ascii=False)
    last = max(r['day'] for r in mj)
    have = {(r['day'], r['h'], r['a']) for r in mj}
    aet = {}
    fx = []
    for e in es:
        h, a = mp.get(e['hn']), mp.get(e['an'])
        if not h or not a:
            continue
        e = dict(e, H=h, A=a)
        if e.get('hs') is not None:
            aet[(e['day'], h, a)] = e
            if e['day'] > last and (e['day'], h, a) not in have:
                t = INTL[e['lg']]
                rows_t = {'fifa.world': 'FIFA World Cup', 'uefa.euro': 'UEFA Euro', 'uefa.nations': 'UEFA Nations League',
                          'fifa.friendly': 'Friendly', 'conmebol.america': 'Copa América', 'concacaf.gold': 'Gold Cup',
                          'concacaf.nations.league': 'CONCACAF Nations League', 'caf.nations': 'African Cup of Nations',
                          'afc.asian.cup': 'AFC Asian Cup'}.get(e['lg'], 'FIFA World Cup qualification' if 'worldq' in e['lg'] else
                                                                 'UEFA Euro qualification' if e['lg'] == 'uefa.euroq' else t)
                so = None
                if e.get('st') == 'PEN':
                    so = h if (e.get('hp') or 0) > (e.get('ap') or 0) else a
                mj.append({'day': e['day'], 'h': h, 'a': a, 'hs': e['hs'], 'as': e['as'], 't': rows_t, 'neu': e.get('neu', 0),
                           'so': so, 'cat': cat_of(rows_t), 'espn': e['id'], 'lg': e['lg']})
                have.add((e['day'], h, a))
        elif e.get('st') == 'SCHED' and e['day'] >= today.isoformat():
            fx.append(e)
    for r in mj:
        e = aet.get((r['day'], r['h'], r['a']))
        if e:
            r['espn'], r['lg'] = e['id'], e['lg']
            if e.get('st') in ('AET', 'PEN'):
                r['et'] = 1
        elif r.get('so'):
            r['et'] = 1
    mj.sort(key=lambda r: (r['day'], r['h']))
    seen, fx2 = set(), []
    for e in sorted(fx, key=lambda e: e['t']):
        k = (e['day'], e['H'], e['A'])
        if k not in seen:
            seen.add(k)
            fx2.append(e)
    return mj, fx2, mp


def res90(r):
    """90-minute score: a match that went to extra time was level after 90; the lower score stands in for it"""
    if r.get('et'):
        m = min(r['hs'], r['as'])
        return m, m
    return r['hs'], r['as']


# ---------------------------------------------------------------- DraftKings prices through ESPN's core API
def _am(x):
    try:
        v = float(str(x).replace('+', ''))
    except (TypeError, ValueError):
        return None
    return None if v == 0 else v


def _ml(o, side, when):
    s = (o.get(side) or {})
    if when == 'close' and not s.get('close'):
        return _am(s.get('moneyLine'))
    v = ((s.get(when) or {}).get('moneyLine') or {})
    return _am(v.get('american') or v.get('alternateDisplayValue'))


BOOKS = ('DraftKings', 'ESPN BET')      # ESPN's partner book: ESPN BET until late 2025, DraftKings since


def odds_one(lg, gid):
    try:
        d = json.loads(_get(f'{CORE}/{lg}/events/{gid}/competitions/{gid}/odds', timeout=20))
    except Exception:
        return None
    o = next((x for x in d.get('items') or [] if (x.get('provider') or {}).get('name') in BOOKS), None)
    if not o:
        return {}

    def tot(when):
        t = o.get(when) or {}
        try:
            line = float(((t.get('total') or {}).get('american')) or o.get('overUnder'))
        except (TypeError, ValueError):
            line = None
        ov = _am(((t.get('over') or {}).get('american')))
        un = _am(((t.get('under') or {}).get('american')))
        dr = _am(((t.get('draw') or {}).get('american')))
        return line, ov, un, dr
    out = {}
    for when in ('open', 'close'):
        line, ov, un, dr = tot(when)
        if when == 'close' and dr is None:
            dr = _am((o.get('drawOdds') or {}).get('moneyLine'))
        out[when] = {'h': _ml(o, 'homeTeamOdds', when), 'd': dr, 'a': _ml(o, 'awayTeamOdds', when), 'ou': line, 'o': ov, 'u': un}
    out['bk'] = o['provider']['name']
    return out


def fetch_odds():
    """DraftKings open/close for every finished ESPN international match since ODDS_FROM, kept in the repo
    (finished matches never change); matches ESPN shows no DraftKings line for are kept as {} and retried for a week"""
    have = {}
    if os.path.exists(ODDSF):
        have = json.load(gzip.open(ODDSF, 'rt'))
    es = espn_rows(int(ODDS_FROM[:4]), dt.date.today().year)
    today = dt.date.today()
    todo = [e for e in es if e.get('hs') is not None and e['day'] >= ODDS_FROM
            and (e['id'] not in have or (not have[e['id']] and (today - dt.date.fromisoformat(e['day'])).days < 8))]
    print(len(todo), 'matches to fetch')
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda e: (e['id'], odds_one(e['lg'], e['id'])), todo))
    n = 0
    for gid, o in res:
        if o is not None:
            have[gid] = o
            n += bool(o)
    with gzip.open(ODDSF, 'wt') as f:
        json.dump(have, f, separators=(',', ':'), sort_keys=True)
    print('odds: +', n, 'with prices;', sum(1 for v in have.values() if v), 'in all')
    return have


def novig3(h, d, a):
    """American 3-way prices -> no-vig chances (proportional)"""
    if None in (h, d, a):
        return None
    q = [100 / (x + 100) if x > 0 else -x / (-x + 100) for x in (h, d, a)]
    s = sum(q)
    if not (1.0 < s < 1.25):
        return None
    return [x / s for x in q]


def novig2(o, u):
    if None in (o, u):
        return None
    q = [100 / (x + 100) if x > 0 else -x / (-x + 100) for x in (o, u)]
    s = sum(q)
    return None if not (1.0 < s < 1.2) else q[0] / s


# ---------------------------------------------------------------- squad values (Transfermarkt)
def build_sq():
    """nation -> [(month, sum of the top-23 Transfermarkt values on the 1st of that month, EUR m)] from the
    dcaribou dump's value history. A player counts for the national team he plays for (Transfermarkt's
    current_national_team_id) or, without one, his first citizenship."""
    import zipfile
    import pandas as pd
    os.makedirs(CACHE, exist_ok=True)
    zp = os.path.join(CACHE, 'tm.zip')
    if not os.path.exists(zp) or dt.datetime.now().timestamp() - os.path.getmtime(zp) > 5 * 86400:
        open(zp, 'wb').write(_get(TM_DUMP, timeout=600))
    z = zipfile.ZipFile(zp)
    rd = lambda n, **k: pd.read_csv(io.BytesIO(z.read(n + '.csv.gz')), compression='gzip', **k)  # noqa: E731
    pl = rd('players', usecols=['player_id', 'country_of_citizenship', 'current_national_team_id', 'date_of_birth'])
    nt = rd('national_teams', usecols=['national_team_id', 'country_name'])
    ntn = dict(zip(nt.national_team_id, nt.country_name))
    pl['nat'] = [ntn.get(x) if x == x and x in ntn else c for x, c in zip(pl.current_national_team_id, pl.country_of_citizenship)]
    nat = dict(zip(pl.player_id, pl.nat))
    v = rd('player_valuations', usecols=['player_id', 'date', 'market_value_in_eur'])
    v['date'] = pd.to_datetime(v.date)
    v = v.sort_values('date')
    months = pd.date_range('2004-07-01', dt.date.today().replace(day=1).isoformat(), freq='MS')
    out = defaultdict(list)
    # value on each month start = the latest valuation before it, if within 18 months (retired players drop out)
    v['nat'] = v.player_id.map(nat)
    v = v.dropna(subset=['nat'])
    last = {}
    it = iter(v.itertuples(index=False))
    row = next(it, None)
    for m in months:
        while row is not None and row.date < m:
            last[row.player_id] = (row.date, row.market_value_in_eur, row.nat)
            row = next(it, None)
        agg = defaultdict(list)
        for pid, (d0, mv, n) in last.items():
            if (m - d0).days <= 548:
                agg[n].append(mv)
        for n, xs in agg.items():
            xs.sort(reverse=True)
            out[n].append([m.strftime('%Y-%m'), round(sum(xs[:23]) / 1e6, 2), len(xs), round(sum(xs[:11]) / 1e6, 2)])
    out = {tm_to_mj(k): v for k, v in out.items()}
    with gzip.open(SQF, 'wt') as f:
        json.dump(out, f, separators=(',', ':'), sort_keys=True)
    print('squad values for', len(out), 'nations')


TM_FIX = {'Türkiye': 'Turkey', 'Korea, South': 'South Korea', 'Korea, North': 'North Korea', "Cote d'Ivoire": 'Ivory Coast',
          'Bosnia-Herzegovina': 'Bosnia and Herzegovina', 'Czech Republic': 'Czech Republic', 'Ireland': 'Republic of Ireland',
          'United States': 'United States', 'Cape Verde': 'Cape Verde', 'The Gambia': 'Gambia', 'Chinese Taipei': 'Taiwan',
          'Hongkong': 'Hong Kong', 'Saint-Martin': 'Saint Martin', 'Curacao': 'Curaçao', 'Brunei Darussalam': 'Brunei',
          'Palestine, State of': 'Palestine', 'Macao': 'Macau', 'Sao Tome and Principe': 'São Tomé and Príncipe',
          'St. Kitts & Nevis': 'Saint Kitts and Nevis', 'St. Lucia': 'Saint Lucia', 'St. Vincent & Grenadinen': 'Saint Vincent and the Grenadines',
          'Kyrgyzstan': 'Kyrgyzstan', 'DR Congo': 'DR Congo', 'Congo': 'Congo', 'Southern Sudan': 'South Sudan',
          'Antigua and Barbuda': 'Antigua and Barbuda', 'Trinidad and Tobago': 'Trinidad and Tobago', 'Neukaledonien': 'New Caledonia'}


def tm_to_mj(n):
    return TM_FIX.get(n, n)


_SQ = None
SQ_COL = 1          # 1: top-23 value, 3: top-11 value


def sq_of(team, day):
    """log(1 + top-23 value, EUR m) on the month of day, None before the history or for a nation not in it"""
    global _SQ
    if _SQ is None:
        _SQ = {}
        if os.path.exists(SQF):
            for k, v in json.load(gzip.open(SQF, 'rt')).items():
                _SQ[k] = {e[0]: e[SQ_COL] for e in v if len(e) > SQ_COL}
    s = _SQ.get(team)
    if not s:
        return None
    m = day[:7]
    x = s.get(m)
    if x is None:
        if m < min(s):
            return None
        x = s[max(s)] if m > max(s) else None
        if x is None:
            return None
    return math.log1p(x)


# ---------------------------------------------------------------- the model
GMAX = 11
FAC = [math.factorial(i) for i in range(GMAX)]


def pmf(l):
    e = math.exp(-l)
    return [e * l ** i / FAC[i] for i in range(GMAX)]


def wdl(lh, la, rho):
    """home win, draw, away win, P(over 2.5), P(both score) and the most likely score: Dixon-Coles"""
    ph, pa = pmf(lh), pmf(la)
    w = d = l = 0.0
    u25 = 0.0
    best, bp = (0, 0), -1.0
    for i in range(GMAX):
        for j in range(GMAX):
            p = ph[i] * pa[j]
            if i < 2 and j < 2:
                p *= (1 - lh * la * rho) if i == 0 and j == 0 else (1 + la * rho) if i == 0 and j == 1 else \
                    (1 + lh * rho) if i == 1 and j == 0 else (1 - rho)
            if i > j:
                w += p
            elif i == j:
                d += p
            else:
                l += p
            if i + j <= 2:
                u25 += p
            if p > bp:
                best, bp = (i, j), p
    s = w + d + l
    btts = 1 - ph[0] - pa[0] + ph[0] * pa[0] * (1 - lh * la * rho)
    return w / s, d / s, l / s, 1 - u25 / s, btts, best, bp / s


# tuned on 2000-15 walk-forward log loss (fit() rewrites data/soccer_intl_fit.json; these are its start and the fallback)
P0 = {'k': 0.06, 'kh': 0.002, 'H0': 0.30, 'km': 0.001, 'm0': 0.25, 'rev': 0.10, 'boost': 1.5, 'nb': 10.0, 'cap': 5,
      'wwc': 1.2, 'wcf': 1.0, 'wq': 1.0, 'wnl': 1.0, 'wf': 0.6, 'wo': 0.8, 'rho': -0.05, 'sq': 0.0, 'kd': 1.0,
      'a0': 0.0, 'd0': 0.0}
TUNE, HOLD = ('2000-01-01', '2015-12-31'), '2016-01-01'
ELO_K = {'wc': 60, 'cf': 50, 'q': 40, 'nl': 40, 'o': 30, 'f': 20}


class Ratings:
    def __init__(self, P):
        self.P = P
        self.a = defaultdict(lambda: P['a0'])
        self.d = defaultdict(lambda: P['d0'])
        self.n = Counter()
        self.last = {}
        self.m = P['m0']
        self.H = P['H0']
        self.elo = defaultdict(lambda: 1500.0)

    def _decay(self, t, day):
        lt = self.last.get(t)
        if lt is not None:
            g = (dt.date.fromisoformat(day) - dt.date.fromisoformat(lt)).days / 365.25
            f = math.exp(-self.P['rev'] * g)
            self.a[t] *= f
            self.d[t] *= f
        self.last[t] = day

    def rates(self, h, a, neu, qh=None, qa=None):
        P = self.P
        hh = 0 if neu else self.H / 2
        x = 0.0
        if P['sq'] and qh is not None and qa is not None:
            x = P['sq'] * (qh - qa) / 2
        lh = math.exp(self.m + hh + self.a[h] - self.d[a] + x)
        la = math.exp(self.m - hh + self.a[a] - self.d[h] - x)
        return lh, la

    def strength(self, t, q=None, q0=None):
        """expected goal margin a match against an average side at a neutral ground"""
        P = self.P
        x = P['sq'] * (q - q0) / 2 if (P['sq'] and q is not None and q0 is not None) else 0.0
        e = math.exp(self.m)
        return e * (math.exp(self.a[t] + x) - math.exp(-self.d[t] - x))

    def update(self, r, lh, la):
        P = self.P
        h, a = r['h'], r['a']
        gh, ga = res90(r)
        gh, ga = min(gh, P['cap']), min(ga, P['cap'])
        w = P['w' + r['cat']]
        kh_ = P['k'] * w * (1 + P['boost'] * math.exp(-self.n[h] / P['nb']))
        ka_ = P['k'] * w * (1 + P['boost'] * math.exp(-self.n[a] / P['nb']))
        eh, ea = gh - lh, ga - la
        self.a[h] += kh_ * eh
        self.d[a] -= ka_ * eh * P['kd']
        self.a[a] += ka_ * ea
        self.d[h] -= kh_ * ea * P['kd']
        self.m += P['km'] * (eh + ea) / 2
        if not r['neu']:
            self.H += P['kh'] * (eh - ea) / 2
        self.n[h] += 1
        self.n[a] += 1
        # Elo, World Football Elo's K and goal multiplier (the comparison model)
        rh, ra = self.elo[h], self.elo[a]
        dr = rh - ra + (0 if r['neu'] else 100)
        we = 1 / (10 ** (-dr / 400) + 1)
        gd = abs(gh - ga)
        G = 1 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        W = 1 if gh > ga else .5 if gh == ga else 0
        ch = ELO_K[r['cat']] * G * (W - we)
        self.elo[h] = rh + ch
        self.elo[a] = ra - ch


def outcome(r):
    gh, ga = res90(r)
    return 0 if gh > ga else 1 if gh == ga else 2


def run(rows, P, lo=TUNE[0], hi=TUNE[1], keep=False, minn=5):
    """walk forward over every match; returns (ratings, scored rows [(row, pH, pD, pA, elo diff, lh, la)])"""
    R = Ratings(P)
    sc = []
    rho = P['rho']
    for r in rows:
        h, a = r['h'], r['a']
        R._decay(h, r['day'])
        R._decay(a, r['day'])
        qh, qa = r.get('qh'), r.get('qa')
        lh, la = R.rates(h, a, r['neu'], qh, qa)
        if lo <= r['day'] <= hi and R.n[h] >= minn and R.n[a] >= minn:
            if keep:
                w, d_, l_, o25, _, _, _ = wdl(lh, la, rho)
                dr = R.elo[h] - R.elo[a] + (0 if r['neu'] else 100)
                sc.append((r, w, d_, l_, dr, lh, la, o25))
            else:
                sc.append((r, lh, la))
        R.update(r, lh, la)
    return R, sc


def ll_rows(sc, rho):
    s, n = 0.0, 0
    for r, lh, la in sc:
        p = wdl(lh, la, rho)[outcome(r)]
        s -= math.log(max(p, 1e-9))
        n += 1
    return s / max(n, 1), n


def attach_sq(rows):
    for r in rows:
        if r['day'] >= '2005-01-01':
            qh, qa = sq_of(r['h'], r['day']), sq_of(r['a'], r['day'])
            r['qh'], r['qa'] = qh or 0.0, qa or 0.0


# ---------------------------------------------------------------- fitting and scoring
def nelder(f, x0, step=0.2, iters=400):
    """a small Nelder-Mead (no scipy in the workflows)"""
    n = len(x0)
    pts = [list(x0)] + [[x0[j] + (step if j == i else 0) for j in range(n)] for i in range(n)]
    val = [f(p) for p in pts]
    for _ in range(iters):
        o = sorted(range(n + 1), key=lambda i: val[i])
        pts, val = [pts[i] for i in o], [val[i] for i in o]
        c = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        xr = [c[j] + (c[j] - pts[-1][j]) for j in range(n)]
        fr = f(xr)
        if fr < val[0]:
            xe = [c[j] + 2 * (c[j] - pts[-1][j]) for j in range(n)]
            fe = f(xe)
            pts[-1], val[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < val[-2]:
            pts[-1], val[-1] = xr, fr
        else:
            xc = [c[j] + .5 * (pts[-1][j] - c[j]) for j in range(n)]
            fc = f(xc)
            if fc < val[-1]:
                pts[-1], val[-1] = xc, fc
            else:
                pts = [pts[0]] + [[pts[0][j] + .5 * (p[j] - pts[0][j]) for j in range(n)] for p in pts[1:]]
                val = [val[0]] + [f(p) for p in pts[1:]]
        if max(val) - min(val) < 1e-9:
            break
    i = min(range(n + 1), key=lambda i: val[i])
    return pts[i], val[i]


def sig(x):
    return 1 / (1 + math.exp(-x))


def elo_probs(dr, th):
    b, ch, ca = th
    x = dr / 400
    pa = sig(-ca - b * x)
    ph = sig(b * x - ch)
    return ph, max(1 - ph - pa, 1e-6), pa


def elo_fit(sc):
    def f(th):
        s = 0.0
        for r, w, d_, l_, dr, lh, la, o25 in sc:
            s -= math.log(max(elo_probs(dr, th)[outcome(r)], 1e-9))
        return s / len(sc)
    th, v = nelder(f, [2.0, .5, .5])
    return th, v


def tune(rows, P, keys, rounds=3, log=print):
    def f(Q):
        R, sc = run(rows, Q, TUNE[0], TUNE[1])
        return ll_rows(sc, Q['rho'])[0]
    best = f(P)
    steps = {k: (1 if k == 'cap' else .02 if k == 'rho' else .2) for k in keys}
    for rnd in range(rounds):
        for k in keys:
            s = steps[k]
            for direc in (1, -1):
                while True:
                    Q = dict(P)
                    if k == 'cap':
                        Q[k] = P[k] + direc
                    elif k in ('rho', 'a0', 'd0'):
                        Q[k] = P[k] + direc * s
                    else:
                        Q[k] = P[k] * math.exp(direc * s)
                    v = f(Q)
                    if v < best - 1e-6:
                        best, P = v, Q
                    else:
                        break
            steps[k] = s / 2
        log(f'round {rnd}: {best:.5f}')
    return P, best


def cluster_t(diffs, keys):
    """mean of paired differences and its t, clustered by key (international window: the month)"""
    g = defaultdict(float)
    for x, k in zip(diffs, keys):
        g[k] += x
    n = len(diffs)
    if n < 2 or len(g) < 2:
        return 0.0, 0.0
    m = sum(diffs) / n
    v = sum((s - m * sum(1 for kk in keys if kk == k)) ** 2 for k, s in g.items())
    se = math.sqrt(v) / n
    return m, (m / se if se else 0.0)


KEYS = ['k', 'kh', 'H0', 'km', 'rev', 'boost', 'nb', 'cap', 'wwc', 'wcf', 'wnl', 'wf', 'wo', 'rho', 'kd', 'a0', 'd0', 'sq']


def params():
    try:
        return dict(P0, **json.load(open(FIT))['P'])
    except (OSError, ValueError, KeyError):
        return dict(P0)


def ou_p(lh, la, line, rho):
    """P(over line) for a whole or half line, pushes out (None for quarter lines)"""
    if line is None or (line * 2) % 1:
        return None
    ph, pa = pmf(lh), pmf(la)
    tot = [0.0] * (2 * GMAX)
    for i in range(GMAX):
        for j in range(GMAX):
            p = ph[i] * pa[j]
            if i < 2 and j < 2:
                p *= (1 - lh * la * rho) if i == 0 and j == 0 else (1 + la * rho) if i == 0 and j == 1 else \
                    (1 + lh * rho) if i == 1 and j == 0 else (1 - rho)
            tot[i + j] += p
    s = sum(tot)
    over = sum(p for g, p in enumerate(tot) if g > line) / s
    push = sum(p for g, p in enumerate(tot) if g == line) / s
    return over / (1 - push) if push < 1 else None


def dec(am):
    return 1 + (am / 100 if am > 0 else 100 / -am)


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def picks_test(sc, odds, rho, cut=0.05):
    """pre-registered (scripts/research/soccer_intl/prereg.md): model EV >= cut at the open, judged by CLV at the close"""
    out = {}
    for mk in ('1x2', 'ou'):
        clv, ret, keys = [], [], []
        tilt_x, tilt_y = [], []
        for r, w, d_, l_, dr, lh, la, o25 in sc:
            q = odds.get(r.get('espn') or '')
            if not q or not q.get('open') or not q.get('close'):
                continue
            op, cl = q['open'], q['close']
            if mk == '1x2':
                po, pc = novig3(op.get('h'), op.get('d'), op.get('a')), novig3(cl.get('h'), cl.get('d'), cl.get('a'))
                if not po or not pc:
                    continue
                pm = [w, d_, l_]
                prices = [op['h'], op['d'], op['a']]
                y = outcome(r)
                for i in range(3):
                    tilt_x.append(logit(pm[i]) - logit(po[i]))
                    tilt_y.append(logit(pc[i]) - logit(po[i]))
                ev = [pm[i] * dec(prices[i]) - 1 for i in range(3)]
                i = max(range(3), key=lambda i: ev[i])
                if ev[i] < cut:
                    continue
                clv.append(pc[i] * dec(prices[i]) - 1)
                ret.append(dec(prices[i]) - 1 if y == i else -1.0)
            else:
                line = op.get('ou')
                if line is None or line != cl.get('ou'):
                    continue
                pom, pcm = novig2(op.get('o'), op.get('u')), novig2(cl.get('o'), cl.get('u'))
                pmo = ou_p(lh, la, line, rho)
                if pom is None or pcm is None or pmo is None:
                    continue
                tilt_x.append(logit(pmo) - logit(pom))
                tilt_y.append(logit(pcm) - logit(pom))
                g = sum(res90(r))
                if g == line:
                    continue
                cand = [(pmo * dec(op['o']) - 1, 0), ((1 - pmo) * dec(op['u']) - 1, 1)]
                e, i = max(cand)
                if e < cut:
                    continue
                pc = pcm if i == 0 else 1 - pcm
                clv.append(pc * dec(op['o'] if i == 0 else op['u']) - 1)
                won = (g > line) == (i == 0)
                ret.append(dec(op['o'] if i == 0 else op['u']) - 1 if won else -1.0)
            keys.append(r['day'][:7])
        n = len(clv)
        m, t = cluster_t(clv, keys) if n > 1 else (0.0, 0.0)
        rm = sum(ret) / n if n else 0.0
        rse = (math.sqrt(sum((x - rm) ** 2 for x in ret) / (n - 1)) / math.sqrt(n)) if n > 1 else 0.0
        sxx = sum(x * x for x in tilt_x)
        b = sum(x * y for x, y in zip(tilt_x, tilt_y)) / sxx if sxx else 0.0
        res_ = [y - b * x for x, y in zip(tilt_x, tilt_y)]
        bse = math.sqrt(sum(e * e for e in res_) / max(len(res_) - 1, 1) / sxx) if sxx else 0.0
        out[mk] = {'bets': n, 'clv': round(m, 4), 'clv_t': round(t, 2), 'ret': round(rm, 4), 'ret_se': round(rse, 4),
                   'tilt': round(b, 3), 'tilt_se': round(bse, 3), 'pairs': len(tilt_x),
                   'pass': bool(n >= 30 and m > 0 and t >= 2 and rm > -2 * rse)}
    return out


def fit(retune=True):
    rows, _, _ = load()
    attach_sq(rows)
    P = params()
    log = []

    def say(s):
        print(s, flush=True)
        log.append(s)
    if retune:
        P, best = tune(rows, P, KEYS, rounds=3, log=say)
    R, sc = run(rows, P, '2000-01-01', '2099-12-31', keep=True)
    P_nosq = dict(P, sq=0.0)
    _, sc0 = run(rows, P_nosq, '2000-01-01', '2099-12-31', keep=True)
    th, _ = elo_fit([x for x in sc if x[0]['day'] <= TUNE[1]])
    l = lambda p: -math.log(max(p, 1e-9))  # noqa: E731
    base = {id(x[0]): x for x in sc0}
    rep = {}
    for lab, f in (('tune', lambda d: d <= TUNE[1]), ('held', lambda d: d >= HOLD)):
        S = [x for x in sc if f(x[0]['day'])]
        y = [outcome(x[0]) for x in S]
        lm = [l(x[1 + yy]) for x, yy in zip(S, y)]
        l0 = [l(base[id(x[0])][1 + yy]) for x, yy in zip(S, y)]
        le = [l(elo_probs(x[4], th)[yy]) for x, yy in zip(S, y)]
        k = [x[0]['day'][:7] for x in S]
        by = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
        for x, a, b, c in zip(S, lm, l0, le):
            e = by[x[0]['cat']]
            e[0] += 1
            e[1] += a
            e[2] += b
            e[3] += c
        o25 = [(x[7], sum(res90(x[0])) > 2) for x in S]
        rep[lab] = {'n': len(S), 'model': round(sum(lm) / len(S), 5), 'noSquad': round(sum(l0) / len(S), 5),
                    'elo': round(sum(le) / len(S), 5),
                    'squad': [round(v, 5) for v in cluster_t([a - b for a, b in zip(lm, l0)], k)],
                    'vsElo': [round(v, 5) for v in cluster_t([a - b for a, b in zip(lm, le)], k)],
                    'byCat': {c: [e[0], round(e[1] / e[0], 4), round(e[2] / e[0], 4), round(e[3] / e[0], 4)] for c, e in sorted(by.items())},
                    'o25': round(sum(l(p if y_ else 1 - p) for p, y_ in o25) / len(o25), 5),
                    'drawPred': round(sum(x[2] for x in S) / len(S), 4), 'drawReal': round(sum(1 for yy in y if yy == 1) / len(S), 4)}
    odds = json.load(gzip.open(ODDSF, 'rt')) if os.path.exists(ODDSF) else {}
    C = []
    for x in sc:
        q = odds.get(x[0].get('espn') or '') or {}
        c = novig3(*[(q.get('close') or {}).get(k) for k in 'hda'])
        o = novig3(*[(q.get('open') or {}).get(k) for k in 'hda'])
        if c:
            C.append((x, c, o))
    if C:
        y = [outcome(x[0]) for x, _, _ in C]
        lm = [l(x[1 + yy]) for (x, _, _), yy in zip(C, y)]
        lc = [l(c[yy]) for (_, c, _), yy in zip(C, y)]
        k = [x[0]['day'][:7] for x, _, _ in C]
        Co = [(a, b, c, yy, kk) for (a, b, c), yy, kk in zip(C, y, k) if c]
        lo_ = [l(c[yy]) for a, b, c, yy, kk in Co]
        lmo = [l(a[1 + yy]) for a, b, c, yy, kk in Co]
        # totals against the close at 2.5
        T = []
        for x, _, _ in C:
            q = odds[x[0]['espn']]['close']
            if q.get('ou') == 2.5:
                pc = novig2(q.get('o'), q.get('u'))
                if pc:
                    yv = sum(res90(x[0])) > 2
                    T.append((l(x[7] if yv else 1 - x[7]), l(pc if yv else 1 - pc)))
        rep['close'] = {'n': len(C), 'from': min(x[0]['day'] for x, _, _ in C), 'model': round(sum(lm) / len(lm), 5),
                        'close': round(sum(lc) / len(lc), 5), 'gap': [round(v, 5) for v in cluster_t([a - b for a, b in zip(lm, lc)], k)],
                        'nOpen': len(Co), 'open': round(sum(lo_) / len(Co), 5), 'modelOnOpen': round(sum(lmo) / len(Co), 5),
                        'vsOpen': [round(v, 5) for v in cluster_t([a - b for a, b in zip(lmo, lo_)], [c[4] for c in Co])],
                        'o25': {'n': len(T), 'model': round(sum(a for a, b in T) / max(len(T), 1), 5),
                                'close': round(sum(b for a, b in T) / max(len(T), 1), 5)}}
        rep['picks'] = picks_test(sc, odds, P['rho'])
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'P': P, 'elo': [round(v, 4) for v in th],
           'tune': TUNE, 'hold': HOLD, 'H': round(R.H, 4), 'm': round(R.m, 4), 'report': rep, 'log': log}
    json.dump(out, open(FIT, 'w'), indent=1)
    print(json.dumps(rep, indent=1))
    return out



# ---------------------------------------------------------------- the page
ISO_FIX = {'England': 'gb-eng', 'Scotland': 'gb-sct', 'Wales': 'gb-wls', 'Northern Ireland': 'gb-nir', 'Republic of Ireland': 'ie',
           'United States': 'us', 'South Korea': 'kr', 'North Korea': 'kp', 'Ivory Coast': 'ci', 'Czech Republic': 'cz',
           'Turkey': 'tr', 'Bosnia and Herzegovina': 'ba', 'DR Congo': 'cd', 'Congo': 'cg', 'Cape Verde': 'cv', 'China PR': 'cn',
           'China': 'cn', 'Taiwan': 'tw', 'Kosovo': 'xk', 'Gambia': 'gm', 'Brunei': 'bn', 'Hong Kong': 'hk', 'Macau': 'mo',
           'Palestine': 'ps', 'Curaçao': 'cw', 'Eswatini': 'sz', 'Timor-Leste': 'tl', 'East Timor': 'tl',
           'São Tomé and Príncipe': 'st', 'Saint Kitts and Nevis': 'kn', 'Saint Lucia': 'lc', 'Saint Vincent and the Grenadines': 'vc',
           'Russia': 'ru', 'Iran': 'ir', 'Vietnam': 'vn', 'Syria': 'sy', 'Laos': 'la', 'Moldova': 'md', 'North Macedonia': 'mk',
           'Tahiti': 'pf', 'Kyrgyzstan': 'kg', 'United States Virgin Islands': 'vi', 'British Virgin Islands': 'vg',
           'Faroe Islands': 'fo', 'Bahamas': 'bs', 'Guinea-Bissau': 'gw', 'Equatorial Guinea': 'gq', 'Central African Republic': 'cf',
           'South Sudan': 'ss', 'Sudan': 'sd', 'Cuba': 'cu', 'Guyana': 'gy', 'Liechtenstein': 'li', 'Montserrat': 'ms',
           'Turks and Caicos Islands': 'tc', 'Cayman Islands': 'ky', 'Anguilla': 'ai', 'Bermuda': 'bm', 'Aruba': 'aw',
           'Sint Maarten': 'sx', 'Saint Martin': 'mf', 'Bonaire': 'bq', 'French Guiana': 'gf', 'Guadeloupe': 'gp', 'Martinique': 'mq',
           'American Samoa': 'as', 'Samoa': 'ws', 'Tonga': 'to', 'Cook Islands': 'ck', 'Solomon Islands': 'sb', 'Vanuatu': 'vu',
           'New Caledonia': 'nc', 'Fiji': 'fj', 'Papua New Guinea': 'pg', 'Guam': 'gu', 'Northern Mariana Islands': 'mp',
           'Djibouti': 'dj', 'Comoros': 'km', 'Seychelles': 'sc', 'Mauritius': 'mu', 'Lesotho': 'ls', 'Botswana': 'bw',
           'Namibia': 'na', 'Malawi': 'mw', 'Eritrea': 'er', 'Somalia': 'so', 'Chad': 'td', 'Niger': 'ne', 'Burundi': 'bi',
           'Rwanda': 'rw', 'Bhutan': 'bt', 'Maldives': 'mv', 'Nepal': 'np', 'Sri Lanka': 'lk', 'Bangladesh': 'bd', 'Pakistan': 'pk',
           'Afghanistan': 'af', 'Mongolia': 'mn', 'Myanmar': 'mm', 'Cambodia': 'kh', 'Singapore': 'sg', 'Philippines': 'ph',
           'Kuwait': 'kw', 'Yemen': 'ye', 'Lebanon': 'lb', 'Turkmenistan': 'tm', 'Tajikistan': 'tj', 'Belize': 'bz', 'Dominica': 'dm',
           'Grenada': 'gd', 'Barbados': 'bb', 'Antigua and Barbuda': 'ag', 'Trinidad and Tobago': 'tt', 'Puerto Rico': 'pr',
           'Dominican Republic': 'do', 'Haiti': 'ht', 'Nicaragua': 'ni', 'Suriname': 'sr', 'San Marino': 'sm', 'Andorra': 'ad',
           'Gibraltar': 'gi', 'Malta': 'mt', 'Monaco': 'mc', 'Greenland': 'gl', 'Benin': 'bj'}
CONF_T = {'UEFA Euro qualification': 'UEFA', 'UEFA Nations League': 'UEFA', 'UEFA Euro': 'UEFA',
          'African Cup of Nations qualification': 'CAF', 'African Cup of Nations': 'CAF', 'AFC Asian Cup qualification': 'AFC',
          'AFC Asian Cup': 'AFC', 'CONCACAF Nations League': 'CONCACAF', 'Gold Cup qualification': 'CONCACAF',
          'Oceania Nations Cup': 'OFC', 'Oceania Nations Cup qualification': 'OFC'}
CONF_LG = {'fifa.worldq.uefa': 'UEFA', 'fifa.worldq.conmebol': 'CONMEBOL', 'fifa.worldq.concacaf': 'CONCACAF',
           'fifa.worldq.caf': 'CAF', 'fifa.worldq.afc': 'AFC', 'fifa.worldq.ofc': 'OFC', 'uefa.nations': 'UEFA',
           'concacaf.nations.league': 'CONCACAF', 'caf.nations': 'CAF', 'afc.asian.cup': 'AFC'}
TOPN = 48            # the rating is a margin against an average side of the top 48 (a World Cup field)
SIMS = 10000
DAYS = 10            # matches on the page: the next ten days


def iso_of(n):
    if n in ISO_FIX:
        return ISO_FIX[n]
    try:
        rev = {v: k for k, v in json.load(open(os.path.join(ROOT, 'data', 'soccer_countries.json')))['name'].items()}
    except (OSError, ValueError, KeyError):
        rev = {}
    return rev.get(n)


def flags(isos):
    """fetch any flag the site doesn't host yet (flagcdn, 30x20, the same files soccer_faces.py saves)"""
    d = os.path.join(ROOT, 'static', 'img', 'flags')
    for c in sorted(set(i for i in isos if i)):
        p = os.path.join(d, c + '.png')
        if not os.path.exists(p):
            b = D.get(f'https://flagcdn.com/h20/{c}.png', raw=True)
            if b and len(b) > 50:
                open(p, 'wb').write(b)


def confs(rows):
    v = defaultdict(Counter)
    for r in rows:
        if r['day'] < '2010-01-01':
            continue
        c = CONF_LG.get(r.get('lg')) or CONF_T.get(r['t'])
        if r['t'] == 'FIFA World Cup qualification' and r.get('lg') in CONF_LG:
            c = CONF_LG[r['lg']]
        if c:
            v[r['h']][c] += 1
            v[r['a']][c] += 1
    return {t: c.most_common(1)[0][0] for t, c in v.items()}


def american(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def sample_scores(lh, la, rho, n, rng):
    """n score draws from the Dixon-Coles matrix"""
    ph, pa = pmf(lh), pmf(la)
    M = np.outer(ph, pa)
    M[0, 0] *= 1 - lh * la * rho
    M[0, 1] *= 1 + la * rho
    M[1, 0] *= 1 + lh * rho
    M[1, 1] *= 1 - rho
    M = M.ravel() / M.sum()
    k = rng.choice(M.size, size=n, p=M)
    return k // GMAX, k % GMAX


def espn_standings(lg):
    d = D.get(f'https://site.api.espn.com/apis/v2/sports/soccer/{lg}/standings')
    out = []
    for ch in (d or {}).get('children') or []:
        ents = []
        for e in (ch.get('standings') or {}).get('entries') or []:
            st = {s.get('name'): s.get('value') for s in e.get('stats') or []}
            ents.append({'id': str(e['team']['id']), 'n': e['team'].get('displayName'), 'ab': e['team'].get('abbreviation'),
                         'gp': int(st.get('gamesPlayed') or 0), 'w': int(st.get('wins') or 0), 'd': int(st.get('ties') or 0),
                         'l': int(st.get('losses') or 0), 'pts': int(st.get('points') or 0), 'gf': int(st.get('pointsFor') or 0),
                         'ga': int(st.get('pointsAgainst') or 0), 'rank': int(st.get('rank') or 0),
                         'note': (e.get('note') or {}).get('description')})
        if ents:
            out.append({'name': ch.get('name'), 'teams': ents})
    return out


def rank_group(ids, pts, gd, gf, res, rng):
    """UEFA order: points, then head-to-head points, goal difference and goals among the tied, then goal
    difference and goals overall, then a coin"""
    def key_all(t):
        return (pts[t], gd[t], gf[t], rng.random())
    groups = defaultdict(list)
    for t in ids:
        groups[pts[t]].append(t)
    order = []
    for p in sorted(groups, reverse=True):
        tied = groups[p]
        if len(tied) == 1:
            order += tied
            continue
        hp, hg, hf = Counter(), Counter(), Counter()
        ts = set(tied)
        for h, a, x, y in res:
            if h in ts and a in ts:
                hf[h] += x
                hf[a] += y
                hg[h] += x - y
                hg[a] += y - x
                hp[h] += 3 if x > y else 1 if x == y else 0
                hp[a] += 3 if y > x else 1 if x == y else 0
        order += sorted(tied, key=lambda t: (hp[t], hg[t], hf[t], gd[t], gf[t], rng.random()), reverse=True)
    return order


def nations_league(R, P, rows, fx, mp, rng, q_of, rating):
    """UEFA Nations League: the league phase so far (ESPN's standings) plus 10,000 runs of the matches left;
    League A's top two in each group then play the two-legged quarter-finals (winners against runners-up of
    another group, the winner at home in the second leg), and the semi-finals and final at a neutral ground"""
    st = espn_standings('uefa.nations')
    if not st:
        return None
    name = {}
    for g in st:
        for t in g['teams']:
            name[t['id']] = mp.get(t['n'])
    if any(v is None for v in name.values()):
        print('nations league: unmapped', [k for k, v in name.items() if v is None], file=sys.stderr)
    last = max((r['day'] for r in rows if r.get('lg') == 'uefa.nations'), default=dt.date.today().isoformat())
    season0 = last[:4] + '-08-01'          # league phases run September to November
    played = [(r['h'], r['a'], r['hs'], r['as']) for r in rows if r.get('lg') == 'uefa.nations' and r['day'] >= season0
              and 'Nations League' in r['t']]
    left = [e for e in fx if e['lg'] == 'uefa.nations' and (e.get('slug') or '').startswith('league')] or \
        [e for e in fx if e['lg'] == 'uefa.nations']
    rho = P['rho']
    groups_out = []
    sims = {}
    for g in st:
        ids = [name[t['id']] for t in g['teams'] if name.get(t['id'])]
        if len(ids) < 3:
            continue
        ts = set(ids)
        base = {t['id']: t for t in g['teams']}
        ms = [e for e in left if e['H'] in ts and e['A'] in ts]
        draws = []
        for e in ms:
            lh, la = R.rates(e['H'], e['A'], e.get('neu', 0), q_of(e['H']), q_of(e['A']))
            draws.append(sample_scores(lh, la, rho, SIMS, rng))
        res0 = [x for x in played if x[0] in ts and x[1] in ts]
        pos = {t: [0] * len(ids) for t in ids}
        xp = Counter()
        order_s = []
        for s in range(SIMS):
            pts = {name[k]: v['pts'] for k, v in base.items() if name.get(k)}
            gd = {name[k]: v['gf'] - v['ga'] for k, v in base.items() if name.get(k)}
            gf = {name[k]: v['gf'] for k, v in base.items() if name.get(k)}
            res = list(res0)
            for e, (H, A) in zip(ms, draws):
                x, y = int(H[s]), int(A[s])
                h, a = e['H'], e['A']
                res.append((h, a, x, y))
                gd[h] += x - y
                gd[a] += y - x
                gf[h] += x
                gf[a] += y
                pts[h] += 3 if x > y else 1 if x == y else 0
                pts[a] += 3 if y > x else 1 if x == y else 0
            o = rank_group(ids, pts, gd, gf, res, rng)
            for i, t in enumerate(o):
                pos[t][i] += 1
                xp[t] += pts[t]
            order_s.append(o)
        sims[g['name']] = order_s
        teams = []
        for t in g['teams']:
            n = name.get(t['id'])
            if not n:
                continue
            teams.append({'n': n, 'ab': t['ab'], 'iso': iso_of(n), 'gp': t['gp'], 'rec': f"{t['w']}-{t['d']}-{t['l']}", 'pts': t['pts'],
                          'gd': t['gf'] - t['ga'], 'xpts': round(xp[n] / SIMS, 1), 'p': [round(c / SIMS, 4) for c in pos[n]],
                          'rating': rating.get(n)})
        teams.sort(key=lambda x: (-x['xpts'], -x['pts']))
        groups_out.append({'name': g['name'].replace('Group ', ''), 'teams': teams, 'left': len(ms)})
    # League A: quarter-finals, semi-finals and final
    title, sf, fin = Counter(), Counter(), Counter()
    ga = sorted(k for k in sims if k.startswith('Group A'))
    if len(ga) == 4:
        def one(h, a, neu):
            lh, la = R.rates(h, a, neu, q_of(h), q_of(a))
            w, d_, l_ = wdl(lh, la, rho)[:3]
            return w, d_, l_
        cache = {}

        def leg2(x, y):
            """x hosts the second leg; P(x goes through) over both legs, level ties settled 50/50 in extra time and penalties"""
            k = (x, y)
            if k not in cache:
                lh1, la1 = R.rates(y, x, 0, q_of(y), q_of(x))
                lh2, la2 = R.rates(x, y, 0, q_of(x), q_of(y))
                a1, b1 = pmf(lh1), pmf(la1)   # y home goals, x away goals
                a2, b2 = pmf(lh2), pmf(la2)   # x home goals, y away goals
                gx = np.convolve(b1, a2)
                gy = np.convolve(a1, b2)
                M = np.outer(gx, gy)
                win = np.tril(M, -1).sum()
                tie = np.trace(M)
                cache[k] = float(win + tie * .55)
            return cache[k]
        for s in range(SIMS):
            w1 = [sims[g][s][0] for g in ga]
            r2 = [sims[g][s][1] for g in ga]
            # the draw: winners against runners-up of another group
            perm = list(range(4))
            while True:
                rng.shuffle(perm)
                if all(perm[i] != i for i in range(4)):
                    break
            qf = [(w1[i], r2[perm[i]]) for i in range(4)]
            semi = [x if rng.random() < leg2(x, y) else y for x, y in qf]
            for t in semi:
                sf[t] += 1
            f2 = []
            for x, y in ((semi[0], semi[1]), (semi[2], semi[3])):
                w, d_, l_ = one(x, y, 1)
                f2.append(x if rng.random() < w + d_ * (w / (w + l_)) else y)
            for t in f2:
                fin[t] += 1
            x, y = f2
            w, d_, l_ = one(x, y, 1)
            title[x if rng.random() < w + d_ * (w / (w + l_)) else y] += 1
        for g in groups_out:
            if g['name'].startswith('A'):
                for t in g['teams']:
                    t['sf'] = round(sf[t['n']] / SIMS, 4)
                    t['fin'] = round(fin[t['n']] / SIMS, 4)
                    t['title'] = round(title[t['n']] / SIMS, 4)
    return {'groups': groups_out, 'sims': SIMS}


def market(fx):
    """Novig's 1X2 and goals line for the matches it lists (UEFA Nations League so far), else ESPN's book for
    today's and tomorrow's matches"""
    out = {}
    try:
        import novig
        lgs = sorted({e['league'] for e in novig.pages('events', status='OPEN_PREGAME') if e.get('sport') == 'SOCCER'
                      and any(w in (e.get('league') or '') for w in ('Nations League', 'World Cup', 'Euro', 'International',
                                                                       'Friendl', 'Copa', 'Gold Cup', 'AFCON', 'Africa', 'Asian'))})
        if lgs:
            for lg in lgs:
                novig.SOCCER['_' + lg] = lg
            ms = [(e['id'], '_' + lg, e['hn'], e['an'], e['day']) for e in fx for lg in lgs]
            for gid, px in novig.soccer_prices(ms).items():
                out[gid] = dict(px, book='Novig')
    except Exception as ex:
        print(f'novig: {ex!r}', file=sys.stderr)
    today = dt.date.today()
    days = {(today + dt.timedelta(days=i)).isoformat() for i in (0, 1)}
    for lg, day in sorted({(e['lg'], e['day']) for e in fx if e['day'] in days}):
        for r in D.espn_day(lg, day):
            if r['id'] not in out and r.get('dk') and None not in (r['dk'].get('h'), r['dk'].get('d'), r['dk'].get('a')):
                out[r['id']] = dict(r['dk'], book='DraftKings')
    return out


def tip_of(t):
    """ESPN's '2026-11-14T02:00Z' -> '2026-11-14T02:00:00Z' (Hugo's time needs the seconds)"""
    return t[:16] + ':00Z' if t and len(t) == 17 else t


def build():
    P = params()
    rows, fx, mp = load()
    attach_sq(rows)
    today = dt.date.today().isoformat()
    R, _ = run(rows, P, '9999', '9999')
    week = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    R7, _ = run([r for r in rows if r['day'] < week], P, '9999', '9999')
    cf = confs(rows)
    recent = {t for r in rows if r['day'] >= '2022-01-01' for t in (r['h'], r['a'])}
    pool = [t for t in recent if t in cf and R.n[t] >= 20]

    def q_of(t, day=today):
        v = sq_of(t, day)
        return v if v is not None else 0.0
    sqv = {t: math.expm1(q_of(t)) for t in pool}

    def board(Rx, day):
        raw = sorted(pool, key=lambda t: -Rx.strength(t, sq_of(t, day) or 0.0, 0.0))
        top = raw[:TOPN]
        ab = sum(Rx.a[t] for t in top) / len(top)
        db = sum(Rx.d[t] for t in top) / len(top)
        qb = sum((sq_of(t, day) or 0.0) for t in top) / len(top)
        out = {}
        for t in pool:
            q = sq_of(t, day) or 0.0
            x = P['sq'] * (q - qb) / 2
            lf = math.exp(Rx.m + Rx.a[t] - db + x)
            la = math.exp(Rx.m + ab - Rx.d[t] - x)
            out[t] = (lf - la, lf - math.exp(Rx.m + ab - db), math.exp(Rx.m + ab - db) - la, lf, la)
        return out, (ab, db, qb)
    B, base = board(R, today)
    B7, _ = board(R7, week)
    order = sorted(pool, key=lambda t: -B[t][0])
    rk7 = {t: i + 1 for i, t in enumerate(sorted(pool, key=lambda t: -B7[t][0]))}
    yr = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    rec = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        if r['day'] >= yr:
            for t, x, y in ((r['h'], r['hs'], r['as']), (r['a'], r['as'], r['hs'])):
                rec[t][0 if x > y else 1 if x == y else 2] += 1
    nxt = {}
    for e in fx:
        for t, o, home in ((e['H'], e['A'], 1), (e['A'], e['H'], 0)):
            nxt.setdefault(t, {'o': o, 'day': e['day'], 'h': home, 'lg': e['lg']})
    power = []
    for i, t in enumerate(order):
        m, off, de, lf, la = B[t]
        w, d_, l_ = wdl(lf, la, P['rho'])[:3]
        power.append({'n': t, 'iso': iso_of(t), 'conf': cf.get(t), 'rk': i + 1, 'prev': rk7.get(t), 'dR': round(m - B7[t][0], 3),
                      'rating': round(m, 3), 'off': round(off, 3), 'def': round(de, 3), 'pW': round(w, 3), 'pD': round(d_, 3),
                      'elo': round(R.elo[t]), 'sq': round(sqv.get(t, 0.0)), 'rec': '-'.join(map(str, rec[t])) if t in rec else None,
                      'gp': R.n[t], 'next': nxt.get(t)})
    rank = {t: i + 1 for i, t in enumerate(order)}
    # matches
    end = (dt.date.today() + dt.timedelta(days=DAYS)).isoformat()
    show = [e for e in fx if e['day'] <= end]
    mk = market(show)
    games = []
    for e in show:
        h, a = e['H'], e['A']
        lh, la = R.rates(h, a, e.get('neu', 0), q_of(h), q_of(a))
        w, d_, l_, o25, btts, top, pt = wdl(lh, la, P['rho'])
        g = {'id': e['id'], 'lg': e['lg'], 'comp': SHORT.get(e['lg'], e['lg']), 'tip': tip_of(e['t']), 'day': e['day'], 'hn': h, 'an': a,
             'hab': e.get('hab'), 'aab': e.get('aab'), 'hiso': iso_of(h), 'aiso': iso_of(a), 'neu': e.get('neu', 0),
             'p': [round(w, 4), round(d_, 4), round(l_, 4)], 'fair': [american(w), american(d_), american(l_)],
             'l': [round(lh, 2), round(la, 2)], 'top': f'{top[0]}-{top[1]}', 'pTop': round(pt, 3), 'o25': round(o25, 3),
             'btts': round(btts, 3), 'hr': rank.get(h), 'ar': rank.get(a), 'ser': e.get('ser'),
             'hrec': '-'.join(map(str, rec[h])) if h in rec else None, 'arec': '-'.join(map(str, rec[a])) if a in rec else None}
        if e['id'] in mk:
            px = mk[e['id']]
            g['dk'] = {k: px.get(k) for k in ('h', 'd', 'a', 'ou')}
            g['book'] = px.get('book')
            nv = novig3(px.get('h'), px.get('d'), px.get('a'))
            if nv:
                g['pMkt'] = [round(x, 4) for x in nv]
        games.append(g)
    rng = np.random.default_rng(int(dt.date.today().strftime('%Y%m%d')))
    nl = None
    try:
        nl = nations_league(R, P, rows, fx, mp, rng, q_of, {t: round(B[t][0], 3) for t in pool})
    except Exception as ex:
        print(f'nations league sims failed: {ex!r}', file=sys.stderr)
    flags([p['iso'] for p in power] + [g['hiso'] for g in games] + [g['aiso'] for g in games])
    fitj = {}
    try:
        fitj = json.load(open(FIT))
    except (OSError, ValueError):
        pass
    rep = fitj.get('report') or {}
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'topN': TOPN, 'home': round(R.H, 3),
           'base': round(math.exp(R.m + base[0] - base[1]), 3), 'power': power, 'games': games, 'nl': nl,
           'last': max(r['day'] for r in rows), 'held': (rep.get('held') or {}).get('model'), 'n': len(rows)}
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'), ensure_ascii=False)
    print(f'{len(power)} nations, {len(games)} matches, last result {out["last"]}; #1 {order[0]}')


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--sq' in a:
        build_sq()
    elif '--odds' in a:
        fetch_odds()
    elif '--fit' in a:
        fit(retune='--keep' not in a)
    else:
        build()
