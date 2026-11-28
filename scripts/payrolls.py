#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Team payrolls for the pro boards (market > payrolls, contracts, free agents): every contract on every team, its cap hit
this season and the next ones, the team's total, space, dead money and the efficiency numbers that passed held out.

    python3 scripts/payrolls.py [nhl nba nfl mls]   # -> data/payrolls/<lg>.json (all four with no argument)
    python3 scripts/payrolls.py --stale 20 nhl      # only when the file is over 20 hours old (the board workflows call it so)
    python3 scripts/payrolls.py --test              # parser checks on cached pages, no network

Sources (one request every 1.2 s, Basketball-Reference 3.5 s; cached under scripts/.cache/payrolls/live, 12 hours)
  NHL  CapWages team pages (capwages.com/teams/<slug>): every contract by season (cap hit, AAV, salary, signing bonus),
       expiry status (UFA, RFA, arbitration), clauses, LTIR, buyouts and buried cap, the team's cap summary.
  NBA  Basketball-Reference contract pages (/contracts/<team>.html): salary by season, player, team and early-termination
       options, remaining guaranteed money. Cap, tax and aprons: the league's 2026-27 figures.
  NFL  OverTheCap through nflverse (historical_contracts.parquet): cap number by season, contract years, value, APY and
       guarantees. The source has no dead money, so NFL shows the active contracts against the cap and no space.
  MLS  American Soccer Analysis (MLSPA releases): base salary and guaranteed compensation. No contract years.
  big five  Salary Sport (salarysport.com; robots.txt allows the club pages): its basic-wage estimates and contract ends,
       pulled at most once a week by scripts/soccer_wages.py. Estimates, labelled so; no cap, no efficiency numbers.

Value and efficiency (research/payroll_efficiency.json, scripts/research/payrolls_nov28/test.py): each player's value over
replacement in the last full season (NHL WAR, NBA VORX, NFL WAR, MLS g+ above replacement) is priced at that season's
league rate ($ above the minimum the league paid a win), less what he costs above a minimum player now. Summed over the
roster that is Surplus; Eff+ puts it on the plus scale (100 = average, 25 = one SD). Both show only for a league whose
roster surplus beat last season's record and payroll on next season's wins, held out (`eff.ship`).
"""
import unicodedata
import datetime as dt
import gzip
import io
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as NM  # noqa: E402

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'payrolls', 'live')
OUT = os.path.join(ROOT, 'data', 'payrolls')
RES = os.path.join(ROOT, 'research', 'payroll_efficiency.json')
AGE = os.path.join(ROOT, 'research', 'payroll_aging.json')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
YEARS = 5          # seasons shown from this one on

# league structure, this season (2026-27 for the NHL and NBA, 2026 for the NFL and MLS)
NHL = {'season': 2027, 'label': '2026-27', 'cap': 104.0, 'floor': 76.9, 'min': 0.85}
NBA = {'season': 2027, 'label': '2026-27', 'cap': 164.961, 'floor': 148.465, 'tax': 200.428, 'apron1': 209.015,
       'apron2': 221.686, 'min': 1.272}
NFL = {'season': 2026, 'label': '2026', 'cap': 301.2, 'min': 0.885}
MLS = {'season': 2026, 'label': '2026', 'cap': 6.425, 'min': 0.1134}


def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def get(url, fn, age_h=12, wait=1.2, binary=False):
    p = os.path.join(CACHE, fn)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < age_h * 3600:
        b = open(p, 'rb').read()
        return b if binary else b.decode('utf-8', 'replace')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    err = None
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=90) as r:
                b = r.read()
            open(p, 'wb').write(b)
            time.sleep(wait)
            return b if binary else b.decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(10 * (k + 1))
    if os.path.exists(p):                         # a failed pull keeps the last copy
        b = open(p, 'rb').read()
        return b if binary else b.decode('utf-8', 'replace')
    raise RuntimeError(f'{url}: {err!r}')


def money(s):
    try:
        return float(str(s).replace('$', '').replace(',', '')) / 1e6
    except ValueError:
        return None


def r2(x, d=3):
    return None if x is None else round(x, d)


def ystr(y):        # 2027 -> '2026-27'
    return f'{y - 1}-{str(y)[2:]}'


def efficiency():
    try:
        return json.load(open(RES))
    except (OSError, ValueError):
        return {}


def plus(vals):
    v = [x for x in vals if x is not None]
    if len(v) < 3:
        return [None] * len(vals)
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) or 1.0
    return [None if x is None else round(100 + 25 * (x - m) / sd) for x in vals]


def team_value(lg, teams, players, mn, cap):
    """Surplus ($M) and Eff+ per team: last full season's value of today's roster at the league's rate a win, less pay above
    the minimum; ships only when the held-out test passed for the league (research/payroll_efficiency.json)"""
    R = efficiency().get(lg) or {}
    rates = R.get('ratePerWin') or {}
    rate = rates[max(rates, key=int)] if rates else None
    ship = bool((R.get('surplus') or {}).get('pass'))
    by = defaultdict(list)
    for p in players:
        if not p.get('dead') and not p.get('nr') and p['tm']:
            by[p['tm']].append(p)
    for t in teams:
        pl = by.get(t['tm'], [])
        above = sum(max((p['h'][0] or 0) - mn, 0) for p in pl if p['h'] and p['h'][0] is not None) + (t.get('dead') or 0)
        val = sum(p.get('v') or 0 for p in pl)
        t['val'] = r2(val, 1)
        if ship and rate:
            t['surp'] = r2(rate * val - above, 1)
            t['dpw'] = r2(above / val, 2) if val > 1 else None
        for p in pl:
            if ship and rate and p['h'] and p['h'][0] is not None:
                p['sv'] = r2(rate * (p.get('v') or 0) - max(p['h'][0] - mn, 0), 1)
    if ship and rate:
        for t, e in zip(teams, plus([t.get('surp') for t in teams])):
            t['eff'] = e
    return {'ship': ship, 'rate': r2(rate, 3), 'test': {k: R.get(k) for k in ('n', 'years', 'maeBase', 'surplus', 'value', 'eff', 'effYoY', 'surplusVsValue')} if R else None}


AGE_BINS = [(0, 24), (25, 27), (28, 30), (31, 33), (34, 99)]


def deal_risk(lg, players, mn, rate):
    """Deal ($M): his expected value over the seasons left in view (the age curve of research/payroll_aging.json, which beat
    last season carried forward held out) at the league's rate a win, less his cap hits above the minimum. Risk ($M): the
    cap dollars after this season that the curve expects to buy no value. Only for a league whose age curve and Surplus
    both passed."""
    try:
        A = json.load(open(AGE)).get(lg) or {}
    except (OSError, ValueError):
        return False
    if not A.get('pass') or not rate or not ((efficiency().get(lg) or {}).get('surplus') or {}).get('pass'):
        return False                                   # the league's value-for-pay reading must have passed too (NFL, MLS failed)
    C = {int(k): v for k, v in A['curve'].items()}

    def coef(k, age):
        b = next((f'{lo}-{hi}' for lo, hi in AGE_BINS if lo <= age <= hi), '34-99')
        return C[k][b]
    for p in players:
        if p.get('dead') or p.get('nr') or not p.get('h') or p.get('age') is None:
            continue
        v0, a0 = p.get('v') or 0.0, p['age'] - 1          # last full season, his age then
        E = []
        for i in range(YEARS):
            k = i + 1
            if k <= 3:
                a, b = coef(k, a0); E.append(a + b * v0)
            else:                                          # past three seasons: one more year on the age curve
                a, b = coef(1, a0 + k - 1); E.append(a + b * E[-1])
        deal = risk = 0.0
        for i, h in enumerate(p['h']):
            if h is None:
                continue
            cost = max(h - mn, 0)
            deal += rate * E[i] - cost
            if i >= 1:
                risk += max(0.0, cost - rate * max(E[i], 0.0))
        p['deal'] = r2(deal, 1)
        p['risk'] = r2(risk, 1)
    return True


def finish(lg, L, teams, players, src, extra=None):
    for t in teams:
        t['c'] = [r2(sum((p['h'][i] or 0) for p in players if p['tm'] == t['tm'] and not p.get('nr') and p['h'] and i < len(p['h'])), 2) for i in range(YEARS)]
        t['exp'] = r2(sum((p['h'][0] or 0) for p in players if p['tm'] == t['tm'] and p.get('fa') and not p.get('nr') and p['h']), 2)
        t['nfa'] = sum(1 for p in players if p['tm'] == t['tm'] and p.get('fa') and not p.get('nr') and not p.get('dead'))
    eff = team_value(lg, teams, players, L['min'], L['cap'])
    eff['deal'] = deal_risk(lg, players, L['min'], (efficiency().get(lg) or {}).get('ratePerWin', {}).get(str(max(map(int, (efficiency().get(lg) or {}).get('ratePerWin', {'0': 0}))))))
    if eff['deal']:
        A = json.load(open(AGE))[lg]
        eff['aging'] = {k: A[k] for k in ('k1', 'k2', 'k3')}
        for t in teams:
            t['risk'] = r2(sum(p.get('risk') or 0 for p in players if p['tm'] == t['tm']), 1)
            t['deal'] = r2(sum(p.get('deal') or 0 for p in players if p['tm'] == t['tm']), 1)
    teams.sort(key=lambda t: (-(t.get('eff') or -999), -(t['pay'] or 0)))
    for t in teams:      # the team's financial card (gfx.js buildPayroll): its biggest contracts and the ones coming off
        pl = sorted([p for p in players if p['tm'] == t['tm'] and not p.get('nr') and not p.get('dead') and p['h'] and p['h'][0]],
                    key=lambda p: -p['h'][0])
        def row(p):
            st = p.get('st') or ('FA' if p.get('fa') else '')
            return [p['n'], p.get('pos') or '', p['h'][0], p.get('thru') or '', st if p.get('fa') else '', p.get('deal') if p.get('deal') is not None else p.get('sv')]
        t['top'] = [row(p) for p in pl[:14 if lg == 'mls' else 8]]
        t['off'] = [row(p) for p in pl if p.get('fa')][:6]
    out = {'lg': lg, 'season': L['season'], 'label': L['label'], 'asof': now(), 'cap': L['cap'], 'min': L['min'],
           'years': [ystr(L['season'] + i) if lg in ('nhl', 'nba') else str(L['season'] + i) for i in range(YEARS)],
           'src': src, 'eff': eff, 'teams': teams, 'players': players}
    for k in ('floor', 'tax', 'apron1', 'apron2'):
        if k in L:
            out[k] = L[k]
    out.update(extra or {})
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f'{lg}.json'), 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)
    print(f'payrolls {lg}: {len(teams)} teams, {len(players)} contracts, efficiency shipped {eff["ship"]}')


# ---------------------------------------------------------------- NHL (CapWages)
def next_data(h):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    return json.loads(m.group(1))['props']['pageProps']


def nhl_grp(pos):
    p = (pos or '').split(',')[0].strip()
    return 'G' if p == 'G' else 'D' if p in ('D', 'LD', 'RD') else 'F'


def nhl_age(born, y):
    try:
        b = dt.datetime.strptime(born.replace('.', ''), '%b %d, %Y').date()
    except (ValueError, AttributeError):
        return None
    d = dt.date.today()
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def nhl_values():
    """last full season's WAR by (name key, group) and id, for the value column and the surplus"""
    y = NHL['season'] - 1
    try:
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{y}.json')))
    except OSError:
        return {}
    out = defaultdict(list)
    for p in d['players']:
        out[(NM.key(p['n']), p['grp'])].append(p)
    return out


def nhl_xaav():
    try:
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'xaav-nhl.json')))
    except OSError:
        return {}
    return {(NM.key(p['n']), p['grp']): p for p in d['players']}


def nhl_status(s):
    s = (s or '').strip()
    return {'RFA (Arb)': 'RFA', 'RFA (10.2)': 'RFA', 'UFA (Group 6)': 'UFA'}.get(s, s), s


def nhl_player(p, tri, L, kind):
    seasons = [ystr(L['season'] + i) for i in range(YEARS)]
    det, cur, last = {}, None, None
    for c in p.get('contracts') or []:
        for x in c.get('details') or []:
            if x.get('season') and money(x.get('capHit')) is not None:
                det.setdefault(x['season'], (x, c))
        if any(x.get('season') == seasons[0] for x in c.get('details') or []):
            cur = c
        if c.get('details') and (last is None or max(x['season'] for x in c['details']) > max(x['season'] for x in last['details'])):
            last = c
    cur = cur or last
    if not cur:
        return None
    h = [money(det[s][0].get('capHit')) if s in det else None for s in seasons]
    if all(v is None for v in h):
        return None
    cd = [x for x in cur['details'] if money(x.get('capHit')) is not None]
    tot = sum(money(x.get('totalSalary')) or 0 for x in cd) + sum(money(x.get('performanceBonuses')) or 0 for x in cd) * 0
    thru = max(x['season'] for x in last['details']) if last and last.get('details') else None
    ty = cur.get('type') or ''
    ct = 'ELC' if 'Entry' in ty else '35+' if '35' in ty else '2W' if 'Two-Way' in ty else ''
    st, st_full = nhl_status(last.get('expiryStatus') if last else '')
    n = p['name'].split(', ', 1)
    n = f'{n[1]} {n[0]}' if len(n) == 2 else p['name']
    left = sum(1 for x in (last or cur)['details'] if x.get('season', '') >= seasons[0])
    return {'n': n, 'id': p.get('slug'), 'tm': tri, 'pos': (p.get('officialPosition') or (p.get('pos') or '').split(',')[0]).strip(),
            'grp': nhl_grp(p.get('pos')), 'age': nhl_age(p.get('born'), L['season']), 'h': [r2(v) for v in h],
            'aav': r2(money(cd[0].get('aav')) if cd else None), 'len': len(cd) or None, 'tot': r2(tot or None, 2),
            'gtd': r2(tot or None, 2), 'thru': thru, 'left': left, 'st': st, 'stx': st_full if st_full != st else None,
            'ct': ct, 'cl': (det.get(seasons[0], ({}, {}))[0].get('clause') or None), 'fa': thru == seasons[0],
            'ltir': 1 if kind == 'ltir' else None, 'nr': 1 if kind == 'nr' else None, 'acq': p.get('acquired')}


def nhl():
    L = NHL
    home = get('https://capwages.com/', 'cw_home.html')
    slugs = sorted(set(re.findall(r'href="/teams/([a-z_]+)"', home)))
    if len(slugs) < 30:
        raise RuntimeError(f'capwages: {len(slugs)} teams on the home page')
    V, X = nhl_values(), nhl_xaav()
    teams, players = [], []
    for slug in slugs:
        try:
            d = next_data(get(f'https://capwages.com/teams/{slug}', f'cw_{slug}.html'))
        except Exception as e:  # noqa: BLE001
            print('payrolls nhl:', slug, repr(e)); continue
        meta, S = d.get('teamMetadata') or {}, d.get('teamSummary') or {}
        tri = meta.get('tricode')
        if not tri:
            continue
        seen = set()
        for part, kind in (('roster', ''), ('non-roster', 'nr')):
            for grp, rows in (d['data'].get(part) or {}).items():
                for p in rows if isinstance(rows, list) else []:
                    r = nhl_player(p, tri, L, 'ltir' if 'injured' in grp else kind)
                    if r and (r['n'], r['pos']) not in seen:
                        seen.add((r['n'], r['pos']))
                        c = V.get((NM.key(r['n']), r['grp'])) or []
                        r['v'] = r2(c[0]['war'], 2) if len(c) == 1 else None
                        xa = X.get((NM.key(r['n']), r['grp']))
                        r['x'] = xa['x'] if xa else None
                        r['ph'] = (c[0].get('ph') if len(c) == 1 else None) or (xa or {}).get('ph')
                        players.append(r)
        dead = 0.0
        seasons = [ystr(L['season'] + i) for i in range(YEARS)]
        for kind, rows in (d['data'].get('dead cap') or {}).items():
            for p in rows if isinstance(rows, list) else []:
                h = [None] * YEARS
                for c in p.get('contracts') or []:
                    for x in c.get('details') or []:
                        b = x.get('buyout') or {}
                        # buried: only the penalty over the allowance counts (CapWages spells it `burriedPenalty`), not his cap hit
                        bp = x.get('burriedPenalty') or x.get('buriedPenalty')
                        v = money(b.get('capHit')) if b else (money(bp) if 'buried' in kind and bp else None)
                        if x.get('season') in seasons and v:
                            h[seasons.index(x['season'])] = r2((h[seasons.index(x['season'])] or 0) + v)
                if any(h):
                    n = p['name'].split(', ', 1); n = f'{n[1]} {n[0]}' if len(n) == 2 else p['name']
                    players.append({'n': n, 'id': p.get('slug'), 'tm': tri, 'pos': (p.get('pos') or '').split(',')[0], 'h': h,
                                    'dead': 1, 'ct': 'buyout' if 'buyout' in kind else 'buried', 'fa': False})
                    dead += h[0] or 0
        ch = S.get('capHit') or {}
        teams.append({'tm': tri, 'name': meta.get('name'), 'pay': r2(money(ch.get('total')), 2), 'space': r2(money(S.get('capSpace')), 2),
                      'dead': r2(money(ch.get('deadCap')) if ch.get('deadCap') is not None else dead, 2),
                      'ltir': r2(money(S.get('ltir')), 2), 'cap': r2(money(S.get('upperLimit')), 2),
                      'proj': r2(money(S.get('projectedCapSpace')), 2), 'n': S.get('totalContracts'), 'roster': S.get('roster')})
    finish('nhl', L, teams, players, 'CapWages team pages; WAR and xAAV from the NHL board')


# ---------------------------------------------------------------- NBA (Basketball-Reference)
NBA_TEAMS = 'ATL BOS BRK CHO CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHO POR SAC SAS TOR UTA WAS'.split()
NBA_LOGO = {'BRK': 'BKN', 'CHO': 'CHA', 'GSW': 'GS', 'NOP': 'NO', 'NYK': 'NY', 'PHO': 'PHX', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH'}
NBA_OPT = {'salary-pl': 'PO', 'salary-tm': 'TO', 'salary-et': 'ETO', 'salary-ex': 'ETO'}


def nba_parse(h):
    m = re.search(r'<table[^>]*id="contracts".*?</table>', h, re.S)
    if not m:
        return []
    out = []
    for row in re.findall(r'<tr[^>]*>.*?</tr>', m.group(0), re.S):
        pid = re.search(r'data-stat="player" csk="(\w+)"', row)
        nm = re.search(r"<a href='/players/\w/\w+\.html'>([^<]+)</a>", row)
        if not pid or not nm:
            continue
        cells = dict((k, (cl, v)) for cl, k, v in re.findall(r'<td class="([^"]*)" data-stat="(y\d|remain_gtd|age_today)"[^>]*>([^<]*)<', row))
        h, o = [], []
        for i in range(1, 7):
            cl, v = cells.get(f'y{i}', ('', ''))
            h.append(money(v) if v.strip() else None)
            o.append(next((NBA_OPT[c] for c in cl.split() if c in NBA_OPT), ''))
        age = cells.get('age_today', ('', ''))[1].strip()
        g = cells.get('remain_gtd', ('', ''))[1].strip()
        # a waived player's guaranteed money left on the books (stretched or not) is a `partial_table` row, his name in <em>
        dead = 'partial_table' in row[:row.find('>')] or '<em><a ' in row
        out.append({'id': pid.group(1), 'n': __import__('html').unescape(nm.group(1)), 'age': int(age) if age.isdigit() else None,
                    'h': h, 'o': o, 'gtd': money(g) if g else None, 'dead': dead})
    return out


def nba():
    L = NBA
    try:
        xp = json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{L["season"] - 1}.json')))['players']
    except OSError:
        xp = []
    V = {p['id']: p for p in xp}
    try:
        cur = {p['id']: p for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{L["season"]}.json')))['players']}
    except OSError:
        cur = {}
    try:
        X = json.load(open(os.path.join(ROOT, 'static', 'data', 'xaav-nba.json')))['players']
    except OSError:
        X = {}
    teams, players = [], []
    for tm in NBA_TEAMS:
        rows = nba_parse(get(f'https://www.basketball-reference.com/contracts/{tm}.html', f'bbref_{tm}.html', wait=3.5))
        if not rows:
            print('payrolls nba: no table', tm); continue
        code = NBA_LOGO.get(tm, tm)
        for r in rows:
            if all(v is None for v in r['h']):
                continue                      # two-way and unsigned rows carry no salary on the page
            h = r['h'][:YEARS]
            last = max(i for i, v in enumerate(r['h']) if v is not None)
            fa = last == 0 or (last >= 1 and r['o'][1] in ('PO', 'TO', 'ETO') and all(v is None for v in r['h'][2:]))
            left = last + 1
            ys = [v for v in r['h'] if v is not None]
            p = V.get(r['id']) or {}
            c = cur.get(r['id']) or {}
            if r['dead']:                     # dead money: on this team's cap, his value and roster spot are elsewhere
                players.append({'n': r['n'], 'id': r['id'], 'tm': code, 'pos': c.get('pos') or p.get('pos'), 'age': r['age'],
                                'h': [r2(v) for v in h], 'gtd': r2(r['gtd'], 2), 'left': left, 'thru': ystr(L['season'] + last),
                                'dead': 1, 'ct': 'waived', 'fa': False})
                continue
            r['o'][0] = ''                    # this season's option is already decided
            opt = next((f'{o} {ystr(L["season"] + i)}' for i, o in enumerate(r['o']) if o), None)
            players.append({'n': r['n'], 'id': r['id'], 'tm': code, 'pos': c.get('pos') or p.get('pos'), 'age': r['age'],
                            'h': [r2(v) for v in h], 'o': [o or None for o in r['o'][:YEARS]], 'opt': opt,
                            'aav': r2(sum(ys) / len(ys)), 'tot': r2(sum(ys), 2), 'gtd': r2(r['gtd'], 2), 'left': left, 'len': None,
                            'thru': ystr(L['season'] + last), 'fa': fa, 'st': 'FA' if last == 0 else (r['o'][1] or None) if fa else None,
                            'v': r2(p.get('vorx'), 2), 'x': r2(X.get(r['id']), 2) if isinstance(X, dict) else None})
        pay = sum(p['h'][0] or 0 for p in players if p['tm'] == code)
        dead = sum(p['h'][0] or 0 for p in players if p['tm'] == code and p.get('dead'))
        teams.append({'tm': code, 'name': NBA_NAMES.get(code, code), 'pay': r2(pay, 2), 'space': r2(L['cap'] - pay, 2), 'tax': r2(L['tax'] - pay, 2),
                      'apron1': r2(L['apron1'] - pay, 2), 'apron2': r2(L['apron2'] - pay, 2), 'cap': L['cap'], 'dead': r2(dead, 2),
                      'n': sum(1 for p in players if p['tm'] == code and not p.get('dead'))})
    finish('nba', L, teams, players, 'Basketball-Reference contract pages; VORX and xAAV from the NBA board')


# ---------------------------------------------------------------- NFL (OverTheCap via nflverse)
OTC = 'https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.parquet'
NICK = {'49ers': 'SF', 'Bears': 'CHI', 'Bengals': 'CIN', 'Bills': 'BUF', 'Broncos': 'DEN', 'Browns': 'CLE', 'Buccaneers': 'TB',
        'Cardinals': 'ARI', 'Chargers': 'LAC', 'Chiefs': 'KC', 'Colts': 'IND', 'Commanders': 'WSH', 'Cowboys': 'DAL',
        'Dolphins': 'MIA', 'Eagles': 'PHI', 'Falcons': 'ATL', 'Giants': 'NYG', 'Jaguars': 'JAX', 'Jets': 'NYJ', 'Lions': 'DET',
        'Packers': 'GB', 'Panthers': 'CAR', 'Patriots': 'NE', 'Raiders': 'LV', 'Rams': 'LAR', 'Ravens': 'BAL', 'Saints': 'NO',
        'Seahawks': 'SEA', 'Steelers': 'PIT', 'Texans': 'HOU', 'Titans': 'TEN', 'Vikings': 'MIN'}
GONE = ('Released', 'Terminated', 'June 1 Terminated', 'Traded', 'Retired', 'Waived')
OTC_POS = {'LT': 'OL', 'RT': 'OL', 'LG': 'OL', 'RG': 'OL', 'C': 'OL', 'ED': 'EDGE', 'IDL': 'DL', 'FB': 'RB'}


def nfl_status(seasons_paid):
    return 'ERFA' if seasons_paid <= 2 else 'RFA' if seasons_paid == 3 else 'UFA'


def nfl():
    L = NFL
    import pyarrow.parquet as pq
    raw = get(OTC, 'otc.parquet', binary=True, age_h=12)
    T = pq.read_table(io.BytesIO(raw), columns=['player', 'position', 'team', 'is_active', 'year_signed', 'years', 'value', 'apy',
                                                 'guaranteed', 'otc_id', 'gsis_id', 'draft_year', 'date_of_birth',
                                                 'season_history', 'contract_history']).to_pylist()
    by = {}
    for r in T:
        k = r['otc_id']
        if k not in by or (r['year_signed'] or 0) > (by[k]['year_signed'] or 0):
            by[k] = r
    try:
        xa = json.load(open(os.path.join(ROOT, 'static', 'data', 'xaav-nfl.json')))['players']
    except OSError:
        xa = []
    X = defaultdict(list)
    for p in xa:
        X[NM.key(p['n'])].append(p)
    y0 = L['season']
    players = []
    for r in by.values():
        sh = [h for h in r['season_history'] or [] if h['year'] != 'Total']
        now_ = [h for h in sh if h['year'] == str(y0) and (h['cap_number'] or 0) > 0]
        if not now_:
            continue
        tm = NICK.get(now_[-1]['team'])
        if not tm:
            continue
        ch = r['contract_history'] or []
        lastc = ch[-1] if ch else {}
        if lastc.get('status') in GONE and NICK.get(lastc.get('team')) == tm:
            continue                          # cut or traded away this season: the charge left is dead money, not a roster spot
        h = []
        for i in range(YEARS):
            v = [x['cap_number'] for x in sh if x['year'] == str(y0 + i) and NICK.get(x['team']) == tm]
            h.append(r2(sum(v)) if v and sum(v) > 0 else None)
        last = max(i for i, v in enumerate(h) if v is not None)
        future = [x for x in sh if x['year'].isdigit() and int(x['year']) > y0 + YEARS - 1 and (x['cap_number'] or 0) > 0]
        thru = max([int(x['year']) for x in sh if x['year'].isdigit() and (x['cap_number'] or 0) > 0 and NICK.get(x['team']) == tm])
        paid = len({x['year'] for x in sh if x['year'].isdigit() and int(x['year']) <= y0 and (x['cap_number'] or 0) > 0})
        fa = thru == y0
        pos = OTC_POS.get(r['position'], r['position'])
        c = [p for p in X.get(NM.key(r['player']), []) if p['tm'] == tm] or [p for p in X.get(NM.key(r['player']), []) if p.get('pos') == pos]
        q = c[0] if len(c) == 1 else {}
        age = None
        if r.get('date_of_birth'):
            try:
                b = dt.datetime.strptime(str(r['date_of_birth']), '%B %d, %Y').date(); t = dt.date.today()
                age = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
            except ValueError:
                pass
        players.append({'n': r['player'], 'id': r.get('gsis_id') or str(r['otc_id']), 'tm': tm, 'pos': pos, 'age': age or q.get('age'),
                        'h': h, 'aav': r2(r['apy']), 'len': r['years'], 'tot': r2(r['value'], 2), 'gtd': r2(r['guaranteed'], 2),
                        'ys': r['year_signed'], 'thru': str(thru), 'left': thru - y0 + 1, 'fa': fa,
                        'st': nfl_status(paid) if fa else None, 'ct': (lastc.get('contract_type') or '') if lastc else '',
                        'v': q.get('war'), 'x': q.get('x'), 'ph': q.get('ph'), 'more': 1 if future else None})
    teams = []
    for tm in sorted(set(NICK.values())):
        pl = [p for p in players if p['tm'] == tm]
        pay = sum(p['h'][0] or 0 for p in pl)
        teams.append({'tm': tm, 'name': NFL_NAMES.get(tm, tm), 'pay': r2(pay, 2), 'cap': L['cap'], 'n': len(pl)})
    finish('nfl', L, teams, players, 'OverTheCap via nflverse (active contracts; no dead money in the source); WAR and xAAV from the NFL board')


# ---------------------------------------------------------------- MLS (American Soccer Analysis)
ASA = 'https://app.americansocceranalysis.com/api/v1/mls'


NBA_NAMES = dict(zip('ATL BKN BOS CHA CHI CLE DAL DEN DET GS HOU IND LAC LAL MEM MIA MIL MIN NO NY OKC ORL PHI PHX POR SA SAC TOR UTAH WSH'.split(),
    ['Atlanta Hawks', 'Brooklyn Nets', 'Boston Celtics', 'Charlotte Hornets', 'Chicago Bulls', 'Cleveland Cavaliers', 'Dallas Mavericks',
     'Denver Nuggets', 'Detroit Pistons', 'Golden State Warriors', 'Houston Rockets', 'Indiana Pacers', 'LA Clippers', 'Los Angeles Lakers',
     'Memphis Grizzlies', 'Miami Heat', 'Milwaukee Bucks', 'Minnesota Timberwolves', 'New Orleans Pelicans', 'New York Knicks',
     'Oklahoma City Thunder', 'Orlando Magic', 'Philadelphia 76ers', 'Phoenix Suns', 'Portland Trail Blazers', 'San Antonio Spurs',
     'Sacramento Kings', 'Toronto Raptors', 'Utah Jazz', 'Washington Wizards']))
NFL_NAMES = dict(zip('ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WSH'.split(),
    ['Arizona Cardinals', 'Atlanta Falcons', 'Baltimore Ravens', 'Buffalo Bills', 'Carolina Panthers', 'Chicago Bears', 'Cincinnati Bengals',
     'Cleveland Browns', 'Dallas Cowboys', 'Denver Broncos', 'Detroit Lions', 'Green Bay Packers', 'Houston Texans', 'Indianapolis Colts',
     'Jacksonville Jaguars', 'Kansas City Chiefs', 'Los Angeles Chargers', 'Los Angeles Rams', 'Las Vegas Raiders', 'Miami Dolphins',
     'Minnesota Vikings', 'New England Patriots', 'New Orleans Saints', 'New York Giants', 'New York Jets', 'Philadelphia Eagles',
     'Pittsburgh Steelers', 'Seattle Seahawks', 'San Francisco 49ers', 'Tampa Bay Buccaneers', 'Tennessee Titans', 'Washington Commanders']))


def _club_key(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower().replace('.', '')
    s = s.replace('internacional', 'inter').replace('football club', '').replace('futbol', '').replace('de foot', '')
    return ' '.join(w for w in re.split(r'\W+', s) if w and w not in {'fc', 'sc', 'cf', 'club', 'de', 'soccer', 'the', 'city'})


CLUB_ALIAS = {'la galaxy': 'los angeles galaxy', 'new york red bulls': 'red bull new york', 'bayern munchen': 'bayern munich',
              'olympique marseille': 'marseille', 'olympique lyonnais': 'lyon', 'bologna 1909': 'bologna',
              'us sassuolo calcio': 'sassuolo', '1 koln': '1fc koln', 'sport freiburg': 'freiburg', '1 fsv mainz 05': 'mainz 05',
              'hamburger sport verein': 'hamburger sv', 'genoa cricket and': 'genoa', 'associazione calcio monza': 'monza',
              'unione sportiva lecce': 'lecce', 'havre ac': 'le havre'}


def club_logo(name, _lk={}):
    """the logo path for a club: data/soccer_logos.json 'tm' (/img/soccer/tm/<id>.png, formal names such as Club de Foot
    Montreal), then 'espn' (/img/soccer/<id>.png); only files that exist"""
    if not _lk:
        try:
            L = json.load(open(os.path.join(ROOT, 'data', 'soccer_logos.json')))
        except OSError:
            L = {}
        for sub, d in (('tm/', L.get('tm', {})), ('', L.get('espn', {}))):
            for k, v in d.items():
                f = f'img/soccer/{sub}{v}.png'
                if os.path.exists(os.path.join(ROOT, 'static', f)):
                    _lk.setdefault(_club_key(k), '/' + f)
        _lk.setdefault('', None)
    k = _club_key(name)
    k = CLUB_ALIAS.get(k, k)
    return _lk.get(k) or _lk.get(re.sub(r'^(fc|afc|ac|as|ssc|ss|us|vfb|vfl|tsg|rc|ogc|ca|rcd|sv|1)\s+', '', k))


def mls():
    L = MLS
    y = L['season']
    sal = json.loads(get(f'{ASA}/players/salaries?season_name={y}', f'asa_sal_{y}.json'))
    pl = {p['player_id']: p for p in json.loads(get(f'{ASA}/players', 'asa_players.json', age_h=72))}
    tm = {t['team_id']: t for t in json.loads(get(f'{ASA}/teams', 'asa_teams.json', age_h=72))}
    V = {}
    try:   # g+ above replacement, the research panel's season (scripts/research/payrolls_nov28/mls_panel.py)
        P = json.load(gzip.open(os.path.join(HERE, 'research', 'payrolls_nov28', 'panel_mls.json.gz')))
        for r in P['rows']:
            if r['s'] == y:
                for q in r['pl']:
                    V[(q['id'], r['tm'])] = q.get('v')
    except OSError:
        pass
    last = {}
    for s in sorted(sal, key=lambda s: s.get('mlspa_release') or ''):
        last[(s['player_id'], s.get('team_id'))] = s
    players = []
    for (pid, tid), s in last.items():
        t = tm.get(tid) or {}
        code = t.get('team_abbreviation')
        if not code or not s.get('guaranteed_compensation'):
            continue
        p = pl.get(pid) or {}
        g = s['guaranteed_compensation'] / 1e6
        players.append({'n': p.get('player_name') or pid, 'id': pid, 'tm': code, 'pos': s.get('position') or p.get('primary_general_position'),
                        'age': None, 'h': [r2(g)] + [None] * (YEARS - 1), 'base': r2((s.get('base_salary') or 0) / 1e6),
                        'gtd': r2(g), 'fa': False, 'v': r2(V.get((pid, code)), 2), 'rel': s.get('mlspa_release')})
    teams = []
    for code in sorted({p['tm'] for p in players}):
        q = [p for p in players if p['tm'] == code]
        name = next((t.get('team_name') or t.get('team_short_name') for t in tm.values() if t.get('team_abbreviation') == code), code)
        teams.append({'tm': code, 'name': name, 'logo': club_logo(name), 'pay': r2(sum(p['h'][0] for p in q), 2), 'base': r2(sum(p['base'] or 0 for p in q), 2), 'n': len(q)})
    finish('mls', L, teams, players, 'American Soccer Analysis (MLSPA salary releases); g+ above replacement from ASA',
           {'release': max((p['rel'] or '') for p in players) if players else None})


# ---------------------------------------------------------------- big five (Salary Sport estimates)
SOCCER = {'season': 2027, 'label': '2026-27', 'cap': None, 'min': 0.0}
SOC_LG = {'eng.1': 'Premier League', 'esp.1': 'La Liga', 'ger.1': 'Bundesliga', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1'}
SOC_TOP = 30          # players a club on the player table (the highest paid); the club totals take every player


def soccer():
    """Salary Sport's basic-wage estimates (GBP, at its own 1.2 EUR rate), pulled at most once a week; SVAR 2025-26 by name"""
    import soccer_wages
    fn = os.path.join(soccer_wages.OUT, 'wages_2027.json')
    if not os.path.exists(fn) or time.time() - os.path.getmtime(fn) > 6 * 86400:
        soccer_wages.main([])
    W = json.load(open(fn))
    try:
        sv = json.load(open(os.path.join(ROOT, 'static', 'data', 'soccer-war', '2026.json')))['players']
    except OSError:
        sv = []
    SV = defaultdict(list)
    for p in sv:
        SV[(p['lg'], NM.key(p['n']))].append(p)
    end = '2027-06-30'
    teams, players = [], []
    for lg, clubs in W.items():
        if lg not in SOC_LG:
            continue
        for club, rows in clubs.items():
            rows = [r for r in rows if r.get('wage_year_gbp')]
            if not rows:
                continue
            code = club
            tot = sum(r['wage_year_gbp'] for r in rows) * W['_meta']['eur_per_gbp'] / 1e6
            exp = [r for r in rows if r.get('until') and r['until'] <= end]
            val = 0.0
            for r in sorted(rows, key=lambda r: -r['wage_year_gbp']):
                c = SV.get((lg, NM.key(r['n'])), [])
                v = c[0].get('svar') if len(c) == 1 else None
                val += v or 0
                if len([q for q in players if q['tm'] == code]) >= SOC_TOP:
                    continue
                eur = r['wage_year_gbp'] * W['_meta']['eur_per_gbp'] / 1e6
                players.append({'n': r['n'], 'tm': code, 'lg': SOC_LG[lg], 'pos': r.get('grp'), 'age': r.get('age'),
                                'w': r2(eur, 2), 'h': [r2(eur, 2)] + [None] * (YEARS - 1), 'wk': round(r['wage_week_gbp'] * W['_meta']['eur_per_gbp'] / 1000),
                                'thru': (r.get('until') or '')[:7] or None, 'fa': bool(r.get('until') and r['until'] <= end),
                                'v': r2(v, 1), 'logo': club_logo(club)})
            teams.append({'tm': code, 'name': club, 'lg': SOC_LG[lg], 'pay': r2(tot, 1), 'n': len(rows),
                          'exp': r2(sum(r['wage_year_gbp'] for r in exp) * W['_meta']['eur_per_gbp'] / 1e6, 1), 'nfa': len(exp),
                          'top': r2(max(r['wage_year_gbp'] for r in rows) * W['_meta']['eur_per_gbp'] / 1e6, 1),
                          'val': r2(val, 1), 'logo': club_logo(club)})
    teams.sort(key=lambda t: -t['pay'])
    out = {'lg': 'soccer', 'season': SOCCER['season'], 'label': SOCCER['label'], 'asof': now(), 'cap': None, 'min': 0.0,
           'years': ['2026-27'], 'src': 'Salary Sport basic-wage estimates (GBP at 1.2 EUR)', 'eff': {'ship': False},
           'got': W['_meta'].get('got'), 'teams': teams, 'players': players}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, 'soccer.json'), 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)
    print(f'payrolls soccer: {len(teams)} clubs, {len(players)} players on the table')


def test():
    h = open(os.path.join(CACHE, 'bbref_BOS.html')).read() if os.path.exists(os.path.join(CACHE, 'bbref_BOS.html')) else None
    if h:
        rows = nba_parse(h)
        assert rows and rows[0]['h'][0] > 1, rows[:1]
        assert any('PO' in r['o'] for r in rows)
        print('nba parse ok', len(rows))
    row = ('<tr class="partial_table" ><th scope="row" class="left " data-stat="player" csk="bealbr01" ><em><a href=\'/players/b/bealbr01.html\'>'
           'Bradley Beal</a></em></th><td class="center " data-stat="age_today" >33</td><td class="right " data-stat="y1" csk="1" >$19,383,010</td></tr>')
    live = row.replace('class="partial_table" ', '').replace('<em>', '').replace('</em>', '')
    rows = nba_parse(f'<table id="contracts">{row}{live}</table>')
    assert [r['dead'] for r in rows] == [True, False] and rows[0]['h'][0] > 19, rows   # waived money is dead, not a roster spot
    assert nhl_status('RFA (Arb)') == ('RFA', 'RFA (Arb)')
    assert nfl_status(3) == 'RFA' and nfl_status(5) == 'UFA'
    assert plus([1, 2, 3])[1] == 100
    print('payrolls tests ok')


def main():
    if '--test' in sys.argv:
        return test()
    args = sys.argv[1:]
    stale = None
    if '--stale' in args:
        i = args.index('--stale'); stale = float(args[i + 1]); del args[i:i + 2]
    lgs = [a for a in args if not a.startswith('-')] or ['nhl', 'nba', 'nfl', 'mls']
    if stale is not None:
        def age(lg):
            try:
                a = json.load(open(os.path.join(OUT, f'{lg}.json')))['asof']
                return (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(a, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)).total_seconds() / 3600
            except (OSError, ValueError, KeyError):
                return 1e9
        lgs = [lg for lg in lgs if age(lg) >= stale]
        if not lgs:
            print('payrolls: fresh, nothing to do'); return
    bad = 0
    for lg in lgs:
        try:
            {'nhl': nhl, 'nba': nba, 'nfl': nfl, 'mls': mls, 'soccer': soccer}[lg]()
        except Exception as e:  # noqa: BLE001  a failed league keeps its last file
            print(f'payrolls {lg}: failed {e!r}')
            bad += 1
    sys.exit(1 if bad == len(lgs) else 0)


if __name__ == '__main__':
    main()
