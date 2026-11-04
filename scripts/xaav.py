#!/usr/bin/env python3
"""xAAV: the average annual value a player would sign for as a free agent today, from position, age and the site's
metrics, for the pro leagues (NBA, NHL, NFL). Fit on real free-agent and veteran signings as a share of that year's
salary cap, then priced at this season's cap and clipped to the league's floor and ceiling.

    python3 scripts/xaav.py --fit nhl|nba|nfl    # signings, held-out test against the baselines, data/xaav_fit.json
    python3 scripts/xaav.py nhl|nba|nfl          # this season's xAAV for every player -> static/data/xaav-<sport>.json

Held out one signing year at a time (and forward: each year from a fit on the years before only). Baseline = the
mean by position x age bin (no metrics); a box-score form (points, minutes) is also reported. A sport ships only when
its form beats the baseline on held-out MAE with paired t <= -2 and wins most held-out years (fit['kept']).

Sources
  NHL  CapWages signings by league year (capwages.com/signings/<season>; Std, Std (2-way) and 35+ deals, not
       entry-level or extensions), cap hit / that year's cap; current cap hits from the team pages. Metrics from
       static/data/nhl-war/<season>.json of the last full season before the signing year (WAR, pWAR, 3Y, TOI).
  NBA  Basketball-Reference transactions (signed to a multi-year or plain contract in the offseason, not two-way,
       10-day, Exhibit 10 or extensions) joined to the signing team's salary the next season (team salary tables) /
       that season's cap. Metrics from static/data/nba-xpm/<season>.json (XPM, VORX, minutes) of the season before.
       Ceiling: the max by years in the league (25 / 30 / 35% of the cap); floor: the minimum.
  NFL  OverTheCap via nflverse (historical_contracts.parquet): veteran contracts (3+ years after the draft, or
       undrafted), APY / cap that year. Metrics from the NFL WAR board (scripts/nfl_war.py board) of the season
       before (WAR, WAA, snaps), cached at scripts/.cache/xaav/nfl_boards.json.
"""
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as NM          # noqa: E402
import xaav_lib as L        # noqa: E402

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'xaav')
FIT = os.path.join(ROOT, 'data', 'xaav_fit.json')
UA = {'User-Agent': 'Mozilla/5.0 (arkboard)'}

# ---------------------------------------------------------------- league structure
# NHL upper limit by league year (start year), $M; minimum salary; max contract 20% of the cap
NHL_CAP = {2005: 39.0, 2006: 44.0, 2007: 50.3, 2008: 56.7, 2009: 56.8, 2010: 59.4, 2011: 64.3, 2012: 70.2, 2013: 64.3,
           2014: 69.0, 2015: 71.4, 2016: 73.0, 2017: 75.0, 2018: 79.5, 2019: 81.5, 2020: 81.5, 2021: 81.5, 2022: 82.5,
           2023: 83.5, 2024: 88.0, 2025: 95.5, 2026: 104.0, 2027: 113.5}
NHL_MIN = {2009: 0.5, 2010: 0.5, 2011: 0.525, 2012: 0.525, 2013: 0.55, 2014: 0.55, 2015: 0.575, 2016: 0.575, 2017: 0.65,
           2018: 0.65, 2019: 0.7, 2020: 0.7, 2021: 0.75, 2022: 0.75, 2023: 0.775, 2024: 0.775, 2025: 0.775, 2026: 0.85}
NHL_MAX = 0.20
# NBA salary cap by season (end year), $M
NBA_CAP = {2011: 58.044, 2012: 58.044, 2013: 58.044, 2014: 58.679, 2015: 63.065, 2016: 70.0, 2017: 94.143, 2018: 99.093,
           2019: 101.869, 2020: 109.14, 2021: 109.14, 2022: 112.414, 2023: 123.655, 2024: 136.021, 2025: 140.588,
           2026: 154.647, 2027: 165.0}
# NFL salary cap by league year, $M
NFL_CAP = {2011: 120.375, 2012: 120.6, 2013: 123.0, 2014: 133.0, 2015: 143.28, 2016: 155.27, 2017: 167.0, 2018: 177.2,
           2019: 188.2, 2020: 198.2, 2021: 182.5, 2022: 208.2, 2023: 224.8, 2024: 255.4, 2025: 279.2, 2026: 301.2}


def get(url, fn, age_h=None):
    """cached fetch (scripts/.cache/xaav/<fn>); refetched when older than age_h hours"""
    p = os.path.join(CACHE, fn)
    if os.path.exists(p) and (age_h is None or time.time() - os.path.getmtime(p) < age_h * 3600):
        return open(p, 'rb').read()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    for k in range(4):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
            open(p, 'wb').write(raw)
            return raw
        except Exception as e:  # noqa: BLE001
            print(f'xaav: {url} {e!r}', flush=True)
            time.sleep(5 * (k + 1))
    if os.path.exists(p):
        return open(p, 'rb').read()
    raise RuntimeError(f'xaav: cannot fetch {url}')


def next_data(h):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    return json.loads(m.group(1))['props']['pageProps']


def money(s):
    try:
        return float(str(s).replace('$', '').replace(',', '')) / 1e6
    except ValueError:
        return None


def season_file(sport, y):
    fn = os.path.join(ROOT, 'static', 'data', {'nhl': 'nhl-war', 'nba': 'nba-xpm'}[sport], f'{y}.json')
    try:
        return json.load(open(fn))
    except OSError:
        return None


def by_key(players):
    d = defaultdict(list)
    for p in players:
        d[NM.key(p['n'])].append(p)
    return d


# ---------------------------------------------------------------- NHL
NHL_GRPS = ['F', 'D', 'G']


def nhl_grp(pos):
    p = str(pos).split(',')[0].strip()
    return 'G' if p == 'G' else 'D' if p in ('LD', 'RD', 'D') else 'F'


def nhl_feats(p, p2, age):
    """inputs from the last full season's row p (and the one before, p2) of static/data/nhl-war"""
    gp = p.get('gp') or 0
    return {'grp': p['grp'], 'age': age, 'war1': p.get('war') or 0.0, 'pwar': p.get('pwar') or 0.0,
            'p3': p.get('p3'), 'war2': (p2 or {}).get('war') or 0.0, 'has2': 1.0 if p2 else 0.0,
            'toi': p.get('toi') or 0.0, 'gp': gp, 'ppg': (p.get('pts') or 0) / gp if gp else 0.0,
            'toig': (p.get('toi') or 0) / gp if gp else 0.0}


def nhl_rows():
    """signings (league year Y >= 2010) joined to the season before: {'y', 'grp', 'age', 't', inputs}"""
    sg = json.load(open(os.path.join(CACHE, 'nhl_signings.json')))
    files = {}
    for y in range(2009, 2028):
        d = season_file('nhl', y)
        if d:
            files[y] = (d, by_key(d['players']), {p['id']: p for p in d['players']})
    rows, miss = [], Counter()
    for s in sg:
        if s['contractType'] not in ('Std', '35+ Contract', 'Std (2-way)'):
            continue
        y = int(s['season'][:4])
        cap = NHL_CAP.get(y); ah = money(s['capHit'])
        if y < 2010 or y > 2026 or not cap or not ah or (y not in files):
            continue
        n = s['player'].split(', ', 1); n = f'{n[1]} {n[0]}' if len(n) == 2 else s['player']
        g = nhl_grp(s['position'])
        c = [p for p in files[y][1].get(NM.key(n), []) if p['grp'] == g and (p.get('age') is None or abs(p['age'] + 1 - (s['age'] - (2026 - y))) <= 2)]
        if len(c) != 1:
            miss['nomatch' if not c else 'dup'] += 1
            continue
        p = c[0]
        if (p.get('gp') or 0) < 10:
            miss['gp<10'] += 1
            continue
        p2 = files.get(y - 1, (None, None, {}))[2].get(p['id'])
        age = (p['ax'] + 1) if p.get('ax') else (p['age'] + 1) if p.get('age') else s['age'] - (2026 - y)
        r = nhl_feats(p, p2, age); r.update(y=y, t=ah / cap, n=n, id=p['id'], len=int(s['length'] or 1), type=s['contractType'])
        rows.append(r)
    print('nhl signings matched', len(rows), dict(miss))
    return rows


def nhl_forms():
    G = NHL_GRPS
    def base(r):
        return [1.0] + L.onehot(f"{r['grp']}{L.agebin(r['age'])}", [f'{g}{k}' for g in G for k in range(5)])[1:]
    def box(r):
        x = [1.0] + L.onehot(r['grp'], G)[1:]
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * v for v in L.hinge(r['age'], 27)] + [d * r['ppg'], d * r['toig'] / 20, d * r['gp'] / 82]
        return x
    def m1(r):
        x = [1.0] + L.onehot(r['grp'], G)[1:]
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * v for v in L.hinge(r['age'], 27)]
        return x + [r['pwar'], r['war1'], r['war2'], r['has2'], math.log1p(r['toi'])]
    def m2(r):
        x = [1.0] + L.onehot(r['grp'], G)[1:]
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * v for v in L.hinge(r['age'], 27)] + [d * r['pwar'], d * r['war1'], d * r['war2'], d * r['has2'], d * math.log1p(r['toi'])]
        return x
    def m3(r):
        p3 = r['p3']
        x = m2(r)
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * (p3 if p3 is not None else 0.0), d * (0.0 if p3 is not None else 1.0)]
        return x
    def m4(r):   # m3 + metrics x age past 30 (the market discounts older players' production)
        x = m3(r)
        o = max(0.0, r['age'] - 30)
        return x + [o * r['pwar'], o * (r['p3'] or 0.0)]
    def m5(r):   # box + the metrics: what the market pays for (points, ice time) and what the site's metrics add
        x = box(r)
        p3 = r['p3']
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * r['pwar'], d * r['war1'], d * r['war2'], d * r['has2'], d * (p3 if p3 is not None else 0.0), d * (0.0 if p3 is not None else 1.0)]
        return x
    def m6(r):   # m5 + production x age past 30
        o = max(0.0, r['age'] - 30)
        return m5(r) + [o * r['ppg'], o * r['pwar'], o * (r['p3'] or 0.0)]
    return {'base': base, 'box': box, 'M1': m1, 'M2': m2, 'M3': m3, 'M4': m4, 'M5': m5, 'M6': m6}




# ---------------------------------------------------------------- NFL
NFL_POS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P']
OTC_POS = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'LT': 'OL', 'RT': 'OL', 'LG': 'OL', 'RG': 'OL', 'C': 'OL',
           'OL': 'OL', 'ED': 'EDGE', 'IDL': 'DL', 'LB': 'LB', 'CB': 'CB', 'S': 'S', 'K': 'K', 'P': 'P'}
NFL_MAX = 0.245        # the record APY share of the cap (Burrow 2023): no cap on contracts, but none has gone past it
OTC = 'https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.parquet'


def nfl_board_pos(p):
    return p['pos'] if p['pos'] in NFL_POS else {'DT': 'DL', 'NT': 'DL', 'DE': 'EDGE', 'OLB': 'LB', 'ILB': 'LB', 'FS': 'S', 'SS': 'S', 'FB': 'RB'}.get(p['pos'], p['_g'])


def otc(age_h=24):
    """OverTheCap contracts (nflverse parquet, read with pyarrow) as dicts"""
    import io
    import pyarrow.parquet as pq
    raw = get(OTC, 'otc.parquet', age_h)
    return pq.read_table(io.BytesIO(raw), columns=['player', 'position', 'team', 'is_active', 'year_signed', 'years', 'apy',
                                                     'apy_cap_pct', 'gsis_id', 'draft_year', 'date_of_birth']).to_pylist()


def nfl_boards():
    return json.load(open(os.path.join(CACHE, 'nfl_boards.json')))


def nfl_feats(p, p2):
    return {'grp': nfl_board_pos(p), 'age': (p.get('ax') or p.get('age') or 27) + 0.5, 'war1': p.get('war') or 0.0,
            'waa1': p.get('waa') or 0.0, 'war2': (p2 or {}).get('war') or 0.0, 'has2': 1.0 if p2 else 0.0,
            'sn': p.get('sn') or 0, 'g': p.get('g') or 0, 'exp': float(p.get('exp') or 0) if str(p.get('exp') or '').isdigit() else 0.0}


def nfl_rows(first=2014):
    H = {int(k): v for k, v in nfl_boards().items()}
    idx = {y: (by_key(v), {p['id']: p for p in v}) for y, v in H.items()}
    rows, miss = [], Counter()
    for c in otc():
        try:
            y, t = int(c['year_signed']), float(c['apy_cap_pct'])
        except (TypeError, ValueError):
            continue
        if y < first or y - 1 not in idx or not t > 0 or (t != t):
            continue
        dy = c.get('draft_year')
        if dy == dy and dy is not None and y - int(dy) < 3:
            continue
        g = OTC_POS.get(c['position'])
        if not g:
            continue
        cand = [p for p in idx[y - 1][0].get(NM.key(c['player']), []) if NM.pos_fits(c['position'], p['pos']) or nfl_board_pos(p) == g]
        if len(cand) > 1 and c.get('date_of_birth') and c['date_of_birth'] == c['date_of_birth']:
            try:
                b = dt.datetime.strptime(c['date_of_birth'], '%B %d, %Y')
                cand = [p for p in cand if p.get('ax') is None or abs((y - 1 + 0.67 - (b.year + b.timetuple().tm_yday / 365)) - p['ax']) < 1.2]
            except ValueError:
                pass
        if len(cand) != 1:
            miss['nomatch' if not cand else 'dup'] += 1
            continue
        p = cand[0]
        if (p.get('sn') or 0) < 50:
            miss['snaps<50'] += 1
            continue
        p2 = idx.get(y - 2, ({}, {}))[1].get(p['id'])
        r = nfl_feats(p, p2); r.update(y=y, t=t, n=p['n'], id=p['id'], otcpos=g)
        rows.append(r)
    print('nfl contracts matched', len(rows), dict(miss))
    return rows


def nfl_forms():
    G = NFL_POS
    def base(r):
        return [1.0] + L.onehot(f"{r['grp']}{min(L.agebin(r['age'], (25, 28, 31)), 3)}", [f'{g}{k}' for g in G for k in range(4)])[1:]
    def ages(r):
        x = [1.0] + L.onehot(r['grp'], G)[1:]
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * v for v in L.hinge(r['age'], 28)]
        return x
    def box(r):
        x = ages(r)
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * r['sn'] / 1000, d * r['g'] / 17]
        return x
    def m1(r):
        return ages(r) + [r['war1'], r['war2'], r['has2'], r['sn'] / 1000]
    def m2(r):
        x = ages(r)
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * r['war1'], d * r['war2'], d * r['has2'], d * r['sn'] / 1000]
        return x
    def m3(r):   # box + WAR by position
        x = box(r)
        for g in G:
            d = 1.0 if r['grp'] == g else 0.0
            x += [d * r['war1'], d * r['war2'], d * r['has2']]
        return x
    def m4(r):   # m3 + WAR x age past 30
        return m3(r) + [max(0.0, r['age'] - 30) * r['war1']]
    return {'base': base, 'box': box, 'M1': m1, 'M2': m2, 'M3': m3, 'M4': m4}


# ---------------------------------------------------------------- NBA
NBA_GRPS = ['G', 'F', 'C']
BB = 'https://www.basketball-reference.com'


def nba_grp(pos):
    p = str(pos or '').split('-')[0]
    return 'C' if p == 'C' else 'F' if p in ('SF', 'PF', 'F') else 'G'


def bbref(path, fn, age_h=None):
    return get(BB + path, os.path.join('bbref', fn), age_h).decode('utf-8', 'replace')


def nba_per_game(y, age_h=None):
    """{bbref id: (games, minutes a game, points a game)} from the league per-game page (a traded player's first row is
    his season total)"""
    s = bbref(f'/leagues/NBA_{y}_per_game.html', f'pg_{y}.html', age_h)
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        m = re.search(r'data-append-csv="([\w.]+)"', tr)
        if not m or m.group(1) in out:
            continue
        def st(k):
            v = re.search(rf'data-stat="{k}"[^>]*>(?:<strong>)?([\d.]+)', tr)
            return float(v.group(1)) if v else 0.0
        out[m.group(1)] = (st('games'), st('mp_per_g'), st('pts_per_g'))
    return out


def nba_salaries(t, y):
    try:
        s = bbref(f'/teams/{t}/{y}.html', f'{t}_{y}.html')
    except RuntimeError:
        return {}
    i = s.find('id="salaries2"')
    if i < 0:
        return {}
    tab = s[i:s.find('</table>', i)]
    return {a: int(b) / 1e6 for a, b in re.findall(r'data-append-csv="([\w.]+)".*?data-stat="salary" csk="(\d+)"', tab)}


SIGNED = re.compile(r'<a[^>]*data-attr-to="(\w+)"[^>]*>[^<]*</a> signed <a href="/players/\w/([\w.]+)\.html">[^<]*</a>'
                    r'(?: as a free agent| to a multi-year contract)?\.</p>')
MONTHS = {m: i + 1 for i, m in enumerate('January February March April May June July August September October November December'.split())}
OPEN = {2012: (2011, 12, 25), 2021: (2020, 12, 22)}       # late starts (lockout, bubble)


def nba_signings(y):
    """offseason signings before season y (free agent, multi-year or plain contracts): [(team, bbref id)]"""
    s = bbref(f'/leagues/NBA_{y}_transactions.html', f'tx_{y}.html')
    lo, hi = dt.date(y - 1, 6, 25), dt.date(*OPEN.get(y, (y - 1, 10, 31)))
    out = []
    for d, body in re.findall(r'<li><span>(\w+ \d+, \d{4})</span>(.*?)</li>', s, re.S):
        mo, dd, yy = d.replace(',', '').split()
        if not lo <= dt.date(int(yy), MONTHS[mo], int(dd)) <= hi:
            continue
        for p in re.findall(r'<p>.*?</p>', body, re.S):
            m = SIGNED.search(p)
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def nba_service(files, pid, y):
    """seasons in the league before y: seasons on the XPM files, or for a player already on the first (2010) file,
    his age then less 20"""
    ys = [k for k in files if k < y and pid in files[k][1]]
    if not ys:
        return 0
    first = min(ys)
    if first == min(files):
        a = files[first][1][pid].get('age') or 25
        return (y - first) + max(0, a - 20)
    return len(ys)


def nba_max(svc):
    return 0.25 if svc < 7 else 0.30 if svc < 10 else 0.35


def nba_files():
    files = {}
    for y in range(2010, 2028):
        d = season_file('nba', y)
        if d:
            files[y] = (d, {p['id']: p for p in d['players']})
    return files


def nba_feats(p, p2, pg, svc):
    g, mpg, ppg = pg or (p.get('g') or 0, (p.get('mp') or 0) / max(1, p.get('g') or 1), 0.0)
    return {'grp': nba_grp(p.get('pos')), 'age': (p.get('age') or 26) + 1, 'xpm1': p.get('xpm') or 0.0,
            'sxpm1': p.get('sxpm') if p.get('sxpm') is not None else p.get('xpm') or 0.0, 'vorx1': p.get('vorx') or 0.0,
            'mp1': p.get('mp') or 0, 'xpm2': (p2 or {}).get('xpm') or 0.0, 'mp2': (p2 or {}).get('mp') or 0,
            'has2': 1.0 if p2 else 0.0, 'g': g, 'mpg': mpg, 'ppg': ppg, 'svc': svc, 'hi': nba_max(svc)}


def nba_rows():
    files = nba_files()
    rows, miss = [], Counter()
    for y in range(2011, 2027):
        if y not in files or y - 1 not in files:
            continue
        cap = NBA_CAP[y]
        pg = nba_per_game(y - 1)
        sal = {}
        seen = set()
        for t, pid in nba_signings(y):
            if pid in seen:
                continue
            seen.add(pid)
            if t not in sal:
                sal[t] = nba_salaries(t, y)
            s_ = sal[t].get(pid)
            p = files[y - 1][1].get(pid)
            if not s_:
                miss['nosalary'] += 1; continue
            if not p or (p.get('mp') or 0) < 200:
                miss['mp<200'] += 1; continue
            r = nba_feats(p, files.get(y - 2, (None, {}))[1].get(pid), pg.get(pid), nba_service(files, pid, y))
            r.update(y=y, t=s_ / cap, n=p['n'], id=pid)
            rows.append(r)
    print('nba signings matched', len(rows), dict(miss))
    return rows


def nba_forms():
    G = NBA_GRPS
    def base(r):
        return [1.0] + L.onehot(f"{r['grp']}{L.agebin(r['age'])}", [f'{g}{k}' for g in G for k in range(5)])[1:]
    def ages(r):
        return [1.0] + L.onehot(r['grp'], G)[1:] + list(L.hinge(r['age'], 28))
    def box(r):
        return ages(r) + [r['ppg'], r['mpg'] / 10, r['g'] / 82]
    def m1(r):
        return ages(r) + [r['xpm1'], r['xpm2'], r['has2'], math.log1p(r['mp1']), math.log1p(r['mp2'])]
    def m2(r):
        return m1(r) + [r['vorx1'], r['sxpm1']]
    def m3(r):   # box + the metrics
        return box(r) + [r['xpm1'], r['xpm2'], r['has2'], r['vorx1'], math.log1p(r['mp2'])]
    def m4(r):   # m3 + production x age past 30
        o = max(0.0, r['age'] - 30)
        return m3(r) + [o * r['ppg'], o * r['xpm1']]
    return {'base': base, 'box': box, 'M1': m1, 'M2': m2, 'M3': m3, 'M4': m4}


# ---------------------------------------------------------------- the test
def research(sport, rows, forms, lo, hi, first_fwd, extra=None):
    out = {'sport': sport, 'rows': len(rows), 'years': f"{min(r['y'] for r in rows)}-{max(r['y'] for r in rows)}", 'forms': {}}
    preds = {}
    for name, f in forms.items():
        for log in (True, False, 'sqrt'):
            k = name + {True: '', False: '/lin', 'sqrt': '/sqrt'}[log]
            preds[k] = L.loyo(rows, f, lo, hi, log=log)
    base = preds['base']
    for k, p in preds.items():
        out['forms'][k] = L.compare(rows, p, base)
    # live form: the lowest held-out MAE among the metric forms whose top end is calibrated (players priced at 7%+ of
    # the cap sign, on average, for 85-115% of the price), else the lowest MAE
    cands = [k for k in preds if k.split('/')[0] not in ('base', 'box')]
    ok = [k for k in cands if out['forms'][k]['topCal'] is not None and 0.85 <= out['forms'][k]['topCal'] <= 1.15]
    best = min(ok or cands, key=lambda k: out['forms'][k]['maeA'])
    out['best'] = best
    bx = min((k for k in preds if k.split('/')[0] == 'box'), key=lambda k: out['forms'][k]['maeA'])
    out['vsBox'] = L.compare(rows, preds[best], preds[bx]); out['vsBox']['box'] = bx
    name = best.split('/')[0]
    log = {'lin': False, 'sqrt': 'sqrt'}.get(best.split('/')[1], True) if '/' in best else True
    fa = L.forward(rows, forms[name], first_fwd, lo, hi, log=log)
    fb = L.forward(rows, forms['base'], first_fwd, lo, hi, log=True)
    idx = sorted(fa)
    out['forward'] = L.compare(rows, fa, fb, idx)
    if out['forward']['t'] is None:
        out['forward']['t'] = 0.0
    # by group, held out
    out['byGroup'] = {}
    for g in sorted({r['grp'] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r['grp'] == g]
        out['byGroup'][g] = L.compare(rows, preds[best], base, idx)
    # top of the market: AAV 5%+ of the cap
    idx = [i for i, r in enumerate(rows) if r['t'] >= 0.05]
    out['top5pct'] = L.compare(rows, preds[best], base, idx)
    f = out['forms'][best]
    out['kept'] = bool(f['t'] is not None and f['t'] <= -2 and int(f['won'].split('/')[0]) * 2 > int(f['won'].split('/')[1]) and out['forward']['t'] <= -2)
    m = L.fit(rows, forms[name], log=log)
    out['live'] = {'form': name, 'log': log, 'b': [round(v, 6) for v in m['b']], 'smear': round(m['smear'], 6)}
    if extra:
        out.update(extra(rows, preds, best))
    return out


def save_fit(sport, res):
    try:
        allf = json.load(open(FIT))
    except (OSError, ValueError):
        allf = {}
    allf[sport] = res
    allf[sport]['fitted'] = dt.date.today().isoformat()
    with open(FIT, 'w') as f:
        json.dump(allf, f, indent=1)
        f.write('\n')

# ---------------------------------------------------------------- live
def live_model(sport):
    try:
        f = json.load(open(FIT))[sport]
    except (OSError, KeyError, ValueError):
        return None
    if not f.get('kept'):
        print(f'xaav {sport}: did not pass, nothing written')
        return None
    return f


def price(f, forms, r, lo, hi):
    lv = f['live']
    z = sum(b * x for b, x in zip(lv['b'], forms[lv['form']](r)))
    v = L.back(z, lv['log'], lv['smear'])
    return min(max(v, lo), hi)


FRESH_H = 20     # the inputs are last full season's and contracts move slowly: rebuild at most about once a day


def fresh(sport):
    try:
        a = json.load(open(os.path.join(ROOT, 'static', 'data', f'xaav-{sport}.json')))['asof']
        t = dt.datetime.strptime(a, '%Y-%m-%dT%H:%MZ').replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() < FRESH_H * 3600
    except (OSError, ValueError, KeyError):
        return False


def nfl_retag():
    """between daily rebuilds, keep each row's club on the WAR board's (today's club, so a trade shows the same day)"""
    fn = os.path.join(ROOT, 'static', 'data', 'xaav-nfl.json')
    try:
        X = json.load(open(fn))
        cur = {p['id']: p['t'] for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))['players']}
    except (OSError, ValueError, KeyError):
        return
    n = 0
    for r in X.get('players', []):
        t = cur.get(r['id'])
        if t and t != r.get('tm'):
            r['tm'] = t
            n += 1
    if n:
        with open(fn, 'w') as f:
            json.dump(X, f, separators=(',', ':'))
        print(f'xaav nfl: {n} players moved to their current club')


def write(sport, payload):
    fn = os.path.join(ROOT, 'static', 'data', f'xaav-{sport}.json')
    with open(fn, 'w') as fh:
        json.dump(payload, fh, separators=(',', ':'), allow_nan=False)
    print(f'xaav {sport}: {len(payload["players"])} players -> {fn}')


def nhl_capwages(age_h=12):
    """{(name key, grp): (cap hit $M this season, years left, contract type, expiry status)} from the team pages"""
    home = get('https://capwages.com/', 'cw_home.html', age_h).decode()
    out = {}
    lyear = f'{LEAGUE_YEAR}-{str(LEAGUE_YEAR + 1)[2:]}'
    for t in sorted(set(re.findall(r'#cw-logo-(\w+)', home))):
        try:
            d = next_data(get(f'https://capwages.com/teams/{t}', f'cw_{t}.html', age_h).decode())
        except Exception as e:  # noqa: BLE001
            print(f'xaav nhl: {t} {e!r}'); continue
        tri = (d.get('teamMetadata') or {}).get('tricode')
        for part in ('roster', 'non-roster'):
            for grp_rows in (d['data'].get(part) or {}).values():
                if not isinstance(grp_rows, list):
                    continue
                for p in grp_rows:
                    for c in p.get('contracts') or []:
                        det = [x for x in c.get('details') or [] if x.get('season') == lyear]
                        if not det:
                            continue
                        left = sum(1 for x in c['details'] if x.get('season', '') >= lyear)
                        n = p['name'].split(', ', 1); n = f'{n[1]} {n[0]}' if len(n) == 2 else p['name']
                        typ = 'ELC' if 'Entry' in c.get('type', '') else '35+' if '35' in c.get('type', '') else ''
                        out[(NM.key(n), nhl_grp(p.get('pos')))] = (money(det[0].get('capHit')), left, typ, c.get('expiryStatus') or '', tri)
    return out


LEAGUE_YEAR = 2026     # the league year a player signing now would sign in (NHL/NBA season starting this fall)


def nhl_live():
    f = live_model('nhl')
    if not f:
        return
    y = LEAGUE_YEAR
    last, prev, cur = season_file('nhl', y), season_file('nhl', y - 1), season_file('nhl', y + 1)
    pid2 = {p['id']: p for p in prev['players']} if prev else {}
    now = {p['id']: p for p in cur['players']} if cur else {}
    cw = nhl_capwages()
    forms, cap = nhl_forms(), NHL_CAP[y]
    lo, hi = NHL_MIN[y] / cap, NHL_MAX
    rows = []
    for p in last['players']:
        if (p.get('gp') or 0) < 10:
            continue
        r = nhl_feats(p, pid2.get(p['id']), (p['ax'] + 1) if p.get('ax') else (p.get('age') or 27) + 1)
        x = price(f, forms, r, lo, hi) * cap
        c = cw.get((NM.key(p['n']), p['grp']))
        q = now.get(p['id'], {})
        rows.append({'id': p['id'], 'n': p['n'], 'tm': (c[4] if c else None) or q.get('tm') or p['tm'], 'pos': p['pos'], 'grp': p['grp'],
                     'age': q.get('age') or p.get('age'), 'war': p.get('war'), 'pwar': p.get('pwar'), 'p3': p.get('p3'),
                     'pts': p.get('pts'), 'gp': p.get('gp'), 'x': round(x, 2), 'cap': round(c[0], 2) if c and c[0] else None,
                     'yl': c[1] if c else None, 'ct': c[2] if c else None, 'st': c[3] if c else None,
                     'gap': round(x - c[0], 2) if c and c[0] else None, 'ph': p.get('ph')})
    rows.sort(key=lambda r: -r['x'])
    write('nhl', {'season': y + 1, 'label': f'{y}-{str(y + 1)[2:]}', 'basis': last['label'], 'cap': cap,
                  'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'test': f['forms'][f['best']], 'players': rows})


NFL_BASIS = os.path.join(ROOT, 'data', 'xaav_nfl_basis.json')


def nfl_basis_save():
    """the last two full seasons' board rows the live xAAV reads (data/xaav_nfl_basis.json; rolls forward with --fit)"""
    H = nfl_boards()
    y0, y1 = sorted(int(k) for k in H)[-2:]
    keep = ('id', 'n', 't', 'pos', 'g', 'sn', 'war', 'waa', 'age', 'ax', 'exp', '_g')
    last = [p for p in H[str(y1)] if (p.get('sn') or 0) >= 50]
    ids = {p['id'] for p in last}
    with open(NFL_BASIS, 'w') as fh:
        json.dump({str(y0): [{'id': p['id'], 'war': p.get('war')} for p in H[str(y0)] if p['id'] in ids],
                   str(y1): [{k: p.get(k) for k in keep} for p in last]}, fh, separators=(',', ':'))
        fh.write('\n')


def nfl_live():
    f = live_model('nfl')
    if not f:
        return
    B = {int(k): v for k, v in json.load(open(NFL_BASIS)).items()}
    y1 = max(B)
    prev = {p['id']: p for p in B.get(y1 - 1, [])}
    y = y1 + 1                                   # the league year a contract signed now counts in
    con = [c for c in otc(age_h=12) if c.get('is_active') in (True, 'TRUE')]
    caps = [c['apy'] / c['apy_cap_pct'] for c in con if c.get('year_signed') == max(int(x['year_signed'] or 0) for x in con) and (c.get('apy_cap_pct') or 0) > 0.01]
    cap = sorted(caps)[len(caps) // 2] if caps else NFL_CAP[max(NFL_CAP)]
    cur = {}
    try:
        cur = {p['id']: p for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))['players']}
    except (OSError, ValueError, KeyError):
        pass
    act = defaultdict(list)
    for c in con:
        act[NM.key(c['player'])].append(c)
    forms = nfl_forms()
    rows = []
    for p in B[y1]:
        if (p.get('sn') or 0) < 50:
            continue
        r = nfl_feats(p, prev.get(p['id']))
        x = price(f, forms, r, 0.0015, NFL_MAX) * cap
        cs = [c for c in act.get(NM.key(p['n']), []) if NM.pos_fits(c['position'], p['pos']) or OTC_POS.get(c['position']) == r['grp']]
        c = max(cs, key=lambda c: int(c['year_signed'] or 0)) if len(cs) >= 1 else None
        q = cur.get(p['id'], {})
        apy = c['apy'] if c else None
        rows.append({'id': p['id'], 'n': p['n'], 'tm': q.get('t') or p['t'], 'pos': r['grp'], 'age': q.get('age') or p.get('age'),
                     'war': p.get('war'), 'waa': p.get('waa'), 'sn': p.get('sn'), 'p3': q.get('p3'), 'x': round(x, 2),
                     'apy': round(apy, 2) if apy else None, 'ys': int(c['year_signed']) if c else None,
                     'yrs': int(c['years']) if c and c.get('years') else None,
                     'gap': round(x - apy, 2) if apy else None, 'ph': q.get('ph')})
    rows.sort(key=lambda r: -r['x'])
    write('nfl', {'season': y, 'basis': y1, 'cap': round(cap, 1), 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
                  'test': f['forms'][f['best']], 'players': rows})


def nba_live():
    f = live_model('nba')
    if not f:
        return
    y = LEAGUE_YEAR + 1                          # season key (end year) a contract signed now starts in
    files = nba_files()
    last = files[y - 1][1]
    prev = files.get(y - 2, (None, {}))[1]
    pg = nba_per_game(y - 1, age_h=24 * 30)
    forms, cap = nba_forms(), NBA_CAP[y]
    out = {}
    for pid, p in last.items():
        if (p.get('mp') or 0) < 200:
            continue
        svc = nba_service(files, pid, y)
        r = nba_feats(p, prev.get(pid), pg.get(pid), svc)
        out[pid] = round(price(f, forms, r, NBA_MIN_SHARE, r['hi']) * cap, 2)
    write('nba', {'season': y, 'basis': files[y - 1][0]['label'], 'cap': cap,
                  'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'test': f['forms'][f['best']],
                  'players': out})


NBA_MIN_SHARE = 0.008


def main():
    a = sys.argv[1:]
    if '--fit' in a:
        sport = a[a.index('--fit') + 1]
        if sport == 'nhl':
            rows = nhl_rows()
            res = research('nhl', rows, nhl_forms(), lambda r: NHL_MIN[r['y']] / NHL_CAP[r['y']], NHL_MAX, 2016)
        if sport == 'nfl':
            rows = nfl_rows()
            res = research('nfl', rows, nfl_forms(), 0.0015, NFL_MAX, 2018)
        if sport == 'nba':
            rows = nba_rows()
            res = research('nba', rows, nba_forms(), NBA_MIN_SHARE, lambda r: r['hi'], 2016)
        print(json.dumps({k: v for k, v in res.items() if k != 'live'}, indent=1))
        save_fit(sport, res)
        if sport == 'nfl':
            nfl_basis_save()
        return
    for sport in [x for x in a if not x.startswith('--')] or ['nhl', 'nfl', 'nba']:
        if '--force' not in a and fresh(sport):
            print(f'xaav {sport}: built under {FRESH_H}h ago, skipped (--force to rebuild)')
            if sport == 'nfl':
                nfl_retag()
            continue
        {'nhl': nhl_live, 'nfl': nfl_live, 'nba': nba_live}[sport]()


if __name__ == '__main__':
    main()
