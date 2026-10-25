#!/usr/bin/env python3
"""Fit Transfer% (data/cfb_transfer_fit.json) on real roster moves, and test the hometown pull.

    python3 scripts/cfb_transfer_fit.py            # pull (cached in scripts/.cache/transfer/), build, fit
    python3 scripts/cfb_transfer_fit.py --offline  # refit from the cached pulls only

Outcome: every player on an FBS or FCS roster in season S (ESPN's season rosters) is followed to season
S+1: on the same team (stay), on another FBS/FCS team (transfer), or on none (exit: out of eligibility,
drafted, left the sport or dropped below FCS). Pairs 2024->25 and 2025->26.

Features, all known at the end of season S (and so computable for this season's players in fetch_cfb.mjs):
  class (ESPN experience years), position group, ESPN recruiting grade (unranked/walk-on flagged),
  PFN production that season (qualified, score percentile at the position, team depth rank), level
  (Power 4 / Group of Five / FCS), team win% that season, head-coach change into S+1 (unknown when scoring,
  so the scorer averages over the fitted chance of one), hometown distance (birthplace, Census places)
  to the school, home-state school, born abroad.

Model: multinomial logit (stay / transfer / exit), L2 ridge, fit on 2024->25 and tested out of time on
2025->26, then refit on both pairs for the live coefficients. Hometown study: the transfer rate by distance
band with and without controls, and where transfers go (distance home->new school vs home->old school).
"""
import concurrent.futures as cf
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'transfer')
OUT = os.path.join(ROOT, 'data', 'cfb_transfer_fit.json')
LOC_OUT = os.path.join(ROOT, 'scripts', 'geo', 'team_loc.json')
OFFLINE = '--offline' in sys.argv
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
PAIRS = [(2024, 2025), (2025, 2026)]
SEASONS = sorted({s for p in PAIRS for s in p})   # plus the season before the first, to tell newcomers
P4_CONF = {'Southeastern Conference', 'Big Ten Conference', 'Big 12 Conference', 'Atlantic Coast Conference'}   # Pac-12 2024-25 was Oregon State and Washington State only
P4_TEAMS = {'87'}   # Notre Dame (FBS independent, paid like Power 4)
os.makedirs(CACHE, exist_ok=True)
S = requests.Session(); S.headers['User-Agent'] = UA


def get(url, ttl=None):
    """GET JSON (or text), cached on disk by URL forever (past seasons don't change) or for ttl seconds."""
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if os.path.exists(f) and (ttl is None or time.time() - os.path.getmtime(f) < ttl or OFFLINE):
        with open(f) as h: return json.load(h)
    if OFFLINE: return None
    for i in range(5):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404: v = None; break
            r.raise_for_status()
            v = r.json() if 'json' in r.headers.get('content-type', '') or url.startswith(CORE) else r.text
            break
        except Exception as e:
            if i == 4: print('fail', url, e); return None
            time.sleep(2 ** i)
    with open(f, 'w') as h: json.dump(v, h)
    return v


def pmap(fn, xs, n=24):
    with cf.ThreadPoolExecutor(n) as ex: return list(ex.map(fn, xs))


def rid(ref):   # id at the end of an ESPN $ref
    return re.search(r'/(\d+)\?', ref['$ref'] + '?').group(1)


def norm(s):
    s = (s or '').lower()
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', s)
    return re.sub(r'[^a-z]', '', s)


# ---- teams: FBS (group 80) and FCS (81) each season, with venue, conference, record, head coach --------
def teams_of(season):
    out = {}
    for g, div in ((80, 'FBS'), (81, 'FCS')):
        d = get(f'{CORE}/seasons/{season}/types/2/groups/{g}/teams?limit=400')
        for it in (d or {}).get('items', []): out[rid(it)] = div
    return out


def team_info(season, tid, div):
    t = get(f'{CORE}/seasons/{season}/teams/{tid}') or {}
    v = t.get('venue') or {}
    addr = v.get('address') or {}
    conf = None
    if t.get('groups'):
        gr = get(t['groups']['$ref'].replace('http://', 'https://')) or {}
        conf = gr.get('name')
        if gr.get('isConference') is False and gr.get('parent'):
            conf = (get(gr['parent']['$ref'].replace('http://', 'https://')) or {}).get('name', conf)
    rec = get(f'{CORE}/seasons/{season}/types/2/teams/{tid}/record') or {}
    w = l = None
    for it in rec.get('items', []):
        if it.get('type') == 'total':
            m = re.match(r'(\d+)-(\d+)', it.get('summary', ''))
            if m: w, l = int(m.group(1)), int(m.group(2))
    co = get(f'{CORE}/seasons/{season}/teams/{tid}/coaches') or {}
    hc = sorted(rid(x) for x in co.get('items', []))
    level = 'FCS' if div == 'FCS' else 'P4' if conf in P4_CONF or tid in P4_TEAMS else 'G5'
    return {'tid': tid, 'season': season, 'name': t.get('location'), 'full': t.get('displayName'), 'div': div, 'conf': conf, 'level': level,
            'city': addr.get('city'), 'state': addr.get('state'), 'w': w, 'l': l, 'hc': hc}


def roster_ids(season, tid):
    d = get(f'{CORE}/seasons/{season}/teams/{tid}/athletes?limit=400') or {}
    return [rid(x) for x in d.get('items', [])]


def athlete(season, aid):
    a = get(f'{CORE}/seasons/{season}/athletes/{aid}') or {}
    bp = a.get('birthPlace') or {}
    return {'id': aid, 'name': a.get('fullName'), 'pos': (a.get('position') or {}).get('abbreviation'),
            'exp': (a.get('experience') or {}).get('years'), 'ht': a.get('height'), 'wt': a.get('weight'),
            'city': bp.get('city'), 'state': bp.get('state'), 'country': bp.get('country')}


# ---- recruiting: ESPN's recruiting classes (grade 0 = not ranked), keyed by ESPN athlete id --------------
def recruits():
    out = {}
    for y in range(2016, max(SEASONS) + 1):
        d = get(f'{CORE}/recruiting/{y}/athletes?limit=1000&page=1') or {}
        pages = d.get('pageCount', 1)
        items = list(d.get('items', []))
        for p in range(2, pages + 1): items += (get(f'{CORE}/recruiting/{y}/athletes?limit=1000&page={p}') or {}).get('items', [])
        for it in items:
            a = it.get('athlete') or {}
            aid = a.get('alternateId')
            if not aid: continue
            stars = next((x.get('value') for x in it.get('attributes', []) if x.get('name') == 'stars'), None)
            out[aid] = {'year': y, 'grade': float(it.get('grade') or 0), 'stars': stars}
    return out


# ---- PFN impact rankings (every FBS season since 2019): qualified players, score, volume -----------------
PFN_POS = [('quarterback', 'QB'), ('running-back', 'RB'), ('wide-receiver', 'WR'), ('tight-end', 'TE'), ('offensive-line', 'OL'),
           ('edge', 'EDGE'), ('defensive-tackle', 'DL'), ('linebacker', 'LB'), ('cornerback', 'CB'), ('safety', 'S')]


def pfn():
    rows = []
    for slug, g in PFN_POS:
        html = get(f'https://www.profootballnetwork.com/cfb-hq/impact-rankings/{slug}', ttl=86400 * 3)
        chunks = [json.loads(m.group(1)) for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)]
        s = next(c for c in chunks if '"packed":' in c)
        i = s.index('"packed":') + 9
        packed, _ = json.JSONDecoder().raw_decode(s[i:])
        for r in packed['rows']:
            x = dict(zip(packed['cols'], r)); x['g'] = g; rows.append(x)
    return rows


SNAPS_PER_GAME = {'QB': 65, 'RB': 30, 'WR': 40, 'TE': 40, 'CB': 55, 'S': 55, 'OL': 65, 'EDGE': 50, 'DL': 45, 'LB': 55}


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def pfn_volume(r):
    sn = num(r.get('snapsQ')) or num(r.get('snaps'))
    if sn is not None: return sn
    return (num(r.get('gp')) or num(r.get('gamesQ')) or 0) * SNAPS_PER_GAME[r['g']]


# ---- geography ---------------------------------------------------------------------------------------
PLACES = json.load(open(os.path.join(ROOT, 'scripts', 'geo', 'us_places.json')))
STATE_AB = {'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT',
            'Delaware': 'DE', 'District of Columbia': 'DC', 'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL',
            'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
            'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT',
            'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
            'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA',
            'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT',
            'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY',
            'Puerto Rico': 'PR'}
CENTROID = {st: [sum(v[0] for v in d.values()) / len(d), sum(v[1] for v in d.values()) / len(d)] for st, d in PLACES.items() if st != '_src'}


def place_norm(s):
    s = s.lower().replace('saint ', 'st ').replace('st. ', 'st ').replace('mount ', 'mt ').replace('fort ', 'ft ')
    return re.sub(r'[^a-z0-9]', '', s)


def geocode(city, state):
    """[lat, lon, exact] for a US city and state (abbreviation or name); state centroid when the city misses."""
    st = STATE_AB.get(state, state) if state else None
    if not st or st not in PLACES: return None
    hit = PLACES[st].get(place_norm(city or ''))
    return [hit[0], hit[1], 1] if hit else [*CENTROID[st], 0]


def miles(a, b):
    if not a or not b: return None
    p1, p2 = math.radians(a[0]), math.radians(b[0]); dl = math.radians(b[1] - a[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


POS_G = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'OT': 'OL', 'OG': 'OL', 'C': 'OL', 'G': 'OL', 'T': 'OL',
         'IOL': 'OL', 'DE': 'EDGE', 'EDGE': 'EDGE', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB',
         'CB': 'CB', 'DB': 'CB', 'S': 'S', 'SAF': 'S', 'FS': 'S', 'SS': 'S', 'PK': 'K', 'K': 'K', 'P': 'P', 'LS': 'LS', 'ATH': 'ATH'}
STARTERS = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OL': 5, 'EDGE': 2, 'DL': 2, 'LB': 2, 'CB': 3, 'S': 2}   # cfb_teams.mjs


WIKI_UA = 'arkndjl.net ARKBOARD (https://arkndjl.net; site maintenance)'


def wiki_hc(titles):
    """head coach(es) from each '<season> <team> football team' Wikipedia infobox: {title: [linked names]}.
    ESPN's season coach lists only carry the current coach, so they can't date a coaching change."""
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        url = ('https://en.wikipedia.org/w/api.php?action=query&format=json&prop=revisions&rvprop=content&rvslots=main'
               '&rvsection=0&redirects=1&titles=' + requests.utils.quote('|'.join(chunk)))
        f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
        if os.path.exists(f): d = json.load(open(f))
        elif OFFLINE: continue
        else:
            for k in range(3):   # Wikimedia answers 429 to bursts: back off and retry
                r = requests.get(url, headers={'User-Agent': WIKI_UA}, timeout=30)
                if r.status_code != 429: break
                time.sleep(10 * 2 ** k)
            if r.status_code != 200: print('wikipedia', r.status_code); return out
            d = r.json(); json.dump(d, open(f, 'w')); time.sleep(3)
        back = {}
        for n in (d['query'].get('normalized') or []): back[n['to']] = n['from']
        for n in (d['query'].get('redirects') or []): back[n['to']] = back.get(n['from'], n['from'])
        for pg in d['query']['pages'].values():
            rv = pg.get('revisions')
            if not rv: continue
            txt = rv[0]['slots']['main']['*']
            m = re.search(r'\|\s*head_coach\s*=(.*?)(?:\n\s*\||\n\}\})', txt, re.S)
            names = re.findall(r'\[\[([^\]|#]+)', m.group(1)) if m else []
            if not names and m: names = [x.strip() for x in re.split(r'<br\s*/?>|,|\(', m.group(1)) if x.strip() and not x.strip().startswith(')')][:2]
            out[back.get(pg['title'], pg['title'])] = [re.sub(r'\s*\(.*?\)', '', n).strip() for n in names]
    return out


def played(season, aid):
    """games played that regular season (ESPN), 0 when he has no stat line"""
    d = get(f'{CORE}/seasons/{season}/types/2/athletes/{aid}/statistics')
    for c in ((d or {}).get('splits') or {}).get('categories', []):
        for x in c.get('stats', []):
            if x.get('name') == 'gamesPlayed': return int(x.get('value') or 0)
    return 0


def collect():
    tdiv = {s: teams_of(s) for s in [SEASONS[0] - 1] + SEASONS}
    print('teams', {s: Counter(v.values()) for s, v in tdiv.items()})
    info = {}
    for s in SEASONS:
        for t in pmap(lambda kv: team_info(s, *kv), list(tdiv[s].items()), 12): info[(s, t['tid'])] = t
    rosters = {}
    for s in tdiv:
        ids = pmap(lambda t: roster_ids(s, t), list(tdiv[s]), 16)
        rosters[s] = dict(zip(tdiv[s], ids))
        print('rosters', s, sum(map(len, ids)))
    titles = sorted({f"{s} {t['full']} football team" for (s, _), t in info.items() if t.get('full')})
    hc = wiki_hc(titles)
    for (s, _), t in info.items(): t['hc'] = hc.get(f"{s} {t.get('full')} football team") or []
    print('head coaches', sum(1 for t in info.values() if t['hc']), 'of', len(info))
    ath = {}
    for s0, _ in PAIRS:
        want = sorted({a for ids in rosters[s0].values() for a in ids})
        t0 = time.time()
        res = pmap(lambda a: athlete(s0, a), want, 32)
        gps = pmap(lambda a: played(s0, a), want, 32)
        for a, x, gp in zip(want, res, gps): ath[(s0, a)] = {**x, 'gp': gp}
        print('athletes', s0, len(res), f'{time.time() - t0:.0f}s')
    return tdiv, info, rosters, ath


def build(tdiv, info, rosters, ath, rec, pf):
    """One row per player-season in the universe, labelled stay / transfer / exit.

    ESPN's season rosters carry the previous season's players over (2025's Alabama list still has Jalen Milroe,
    drafted in April 2025), so a season list is not who was on the team that season. The universe is the players
    who were: a 2025 stat line, or new to the team that season (not on its list the season before). Someone on two
    teams' lists in one season belongs to the one he's new at. Labels: transfer = new on another FBS/FCS team's
    list the next season (clean in both pairs); stay vs exit is only clean for the latest pair, whose next-season
    lists are the current rosters (see main)."""
    tname = {}
    for (s, tid), t in info.items(): tname[(s, norm(t['name']))] = tid
    pfn_by = {}
    by_pos_season = defaultdict(list)
    for r in pf:
        if r.get('division') != 'FBS': continue
        tid = tname.get((r['season'], norm(r['team'])))
        if not tid: continue
        r['tid'] = tid; r['vol'] = pfn_volume(r)
        pfn_by[(r['season'], tid, norm(r['name']))] = r
        by_pos_season[(r['season'], r['g'])].append(r)
    for rows in by_pos_season.values():
        sc = sorted(x['score'] for x in rows if num(x.get('score')) is not None)
        for x in rows: x['pct'] = float(np.searchsorted(sc, x['score'], side='right') / len(sc)) if num(x.get('score')) is not None else 0.5
    depth = {}
    team_pos = defaultdict(list)
    for (s, tid, n), r in pfn_by.items(): team_pos[(s, tid, r['g'])].append(r)
    for k, rows in team_pos.items():
        for i, r in enumerate(sorted(rows, key=lambda x: -x['vol'])): depth[(k[0], k[1], norm(r['name']), r['g'])] = i + 1
    loc = {}
    for (s, tid), t in sorted(info.items()):
        g = geocode(t['city'], t['state'])
        if g: loc[tid] = [g[0], g[1], STATE_AB.get(t['state'], t['state'])]
    on = {s: defaultdict(set) for s in rosters}
    for s, teams in rosters.items():
        for t, ids in teams.items():
            for a in ids: on[s][a].add(t)
    rows = []
    for s0, s1 in PAIRS:
        for aid, teams in on[s0].items():
            a = ath.get((s0, aid))
            if not a: continue
            new = {t for t in teams if t not in on[s0 - 1].get(aid, set())}
            if len(teams) > 1: teams = new
            if len(teams) != 1: continue
            tid = next(iter(teams))
            if not (a['gp'] > 0 or tid in new): continue
            t = info.get((s0, tid))
            if not t: continue
            g = POS_G.get(a['pos'] or '', 'ATH')
            nxt_all = on[s1].get(aid, set())
            moved = {x for x in nxt_all if x != tid and x not in on[s0].get(aid, set())}
            y = 'transfer' if moved else 'stay' if tid in nxt_all else 'exit'
            nxt = next(iter(moved)) if moved else (tid if tid in nxt_all else None)
            p = pfn_by.get((s0, tid, norm(a['name'])))
            r = rec.get(aid)
            # class: years on campus from the recruiting class when known, else ESPN's class (its profile is the
            # latest one: a player still on a roster next season is a year further on, so one comes off)
            yrs = s0 - r['year'] + 1 if r and s0 - r['year'] + 1 >= 1 else None
            exp = yrs if yrs is not None else ((a['exp'] or 1) - (1 if nxt_all else 0))
            home = geocode(a['city'], a['state']) if (a['country'] in (None, 'USA')) else None
            d = miles(home, loc.get(tid))
            st_ab = STATE_AB.get(a['state'], a['state'])
            t1 = info.get((s1, tid))
            hc_change = None if not t1 or not t['hc'] or not t1['hc'] else int(t1['hc'][0] not in t['hc'])
            games = (t['w'] or 0) + (t['l'] or 0)
            dn = miles(home, loc[nxt]) if y == 'transfer' and home and loc.get(nxt) else None
            rows.append({
                'season': s0, 'id': aid, 'name': a['name'], 'tid': tid, 'team': t['name'], 'level': t['level'], 'div': t['div'], 'g': g,
                'exp': max(1, min(exp, 6)), 'expSrc': 'rec' if yrs is not None else 'espn', 'gp': a['gp'], 'played': int(a['gp'] > 0), 'newcomer': int(tid in new),
                'y': y, 'to': nxt if y == 'transfer' else None, 'toLevel': info.get((s1, nxt), {}).get('level') if y == 'transfer' else None,
                'rec': r['grade'] if r and r['grade'] else None, 'recYear': r['year'] if r else None,
                'q': int(p is not None), 'pct': p['pct'] if p else None, 'vol': p['vol'] if p else 0,
                'depth': depth.get((s0, tid, norm(a['name']), p['g'])) if p else None,
                'starter': int(p is not None and depth.get((s0, tid, norm(a['name']), p['g']), 99) <= STARTERS.get(p['g'], 1)),
                'winp': t['w'] / games if games else None, 'hcChange': hc_change,
                'dist': d, 'homeExact': home[2] if home else None, 'inState': int(st_ab == loc.get(tid, [0, 0, None])[2]) if home else None,
                'abroad': int(a['country'] not in (None, 'USA')), 'distNew': dn, 'homeState': st_ab,
                'home': [home[0], home[1]] if home else None,
            })
    return rows, loc


# ---- design matrix -------------------------------------------------------------------------------------
GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P', 'LS', 'ATH']
LATEST = PAIRS[-1][0]


def features(r, hc=None):
    """The scorer's features. scripts/cfb_transfer.mjs (features()) mirrors this exactly, by name.
    hc: head-coach change into next season (0/1), or the chance of one when scoring."""
    e = min(max(r['exp'] or 1, 1), 6)
    rec = r['rec']
    rz = (rec - 80) / 5 if rec else 0.0
    fbs = 0 if r['level'] == 'FCS' else 1                  # PFN's history is FBS-only
    q = r['q'] * fbs; pct = (r['pct'] or 0) * q; st = r['starter'] * fbs
    lvl = r['level']
    d = r['dist']
    gp = min(r.get('gp') or 0, 13) / 13
    x = {
        'exp2': int(e == 2), 'exp3': int(e == 3), 'exp4': int(e == 4), 'exp5': int(e >= 5),
        'ranked': int(bool(rec)), 'rec': rz, 'played': r['played'], 'rec_dnp': rz * (1 - r['played']),
        'q': q, 'pct': pct, 'starter': st, 'exp5_starter': int(e >= 5) * st,
        'g5': int(lvl == 'G5'), 'fcs': int(lvl == 'FCS'), 'pct_g5': pct * int(lvl == 'G5'), 'st_g5': st * int(lvl == 'G5'),
        'winp': (r['winp'] if r['winp'] is not None else 0.5) - 0.5,
        'hc': hc if hc is not None else (r['hcChange'] or 0),
        # log(1 + miles / 100); 1.6 (~400 mi) when the birthplace doesn't geocode
        'logdist': math.log1p(d / 100) if d is not None else 1.6, 'inState': r['inState'] or 0, 'abroad': r['abroad'],
        'xfer_in': int(bool(r['newcomer']) and e >= 2),
        # playing time (games with a stat line, ESPN; a share of a 13-game season): at a P4 school the spot player
        # (1-7 games, past his first year) moves most and the regular stays; at G5 and FCS schools the regulars
        # move (up). Depth rank, volume share and young players ahead added nothing out of time (PFN players only)
        'gp': gp, 'gp_g5': gp * int(lvl == 'G5'), 'gp_fcs': gp * int(lvl == 'FCS'), 'spot': int(1 <= (r.get('gp') or 0) <= 7 and e >= 2),
        # program talent (z): a starter at a loaded program has the most to lose by moving
        # (starter x talent and ranked x starter added nothing out of time)
        'tal': r.get('tal', 0.0), 'pct_tal': pct * max(r.get('tal', 0.0), 0.0),
        # receivers go with their quarterback: a WR or TE whose starting QB transfers out (scored live as that QB's Transfer%)
        'qb_left': r.get('qbLeft', 0) * int(r['g'] in ('WR', 'TE')),
    }
    for g in GROUPS[1:]: x['pos_' + g] = int(r['g'] == g)
    return x


def design(rows, season_dummy=False, **kw):
    names = list(features(rows[0], **kw).keys())
    X = [[1.0] + [features(r, **kw)[n] for n in names] + ([float(r['season'] == LATEST)] if season_dummy else []) for r in rows]
    return np.array(X), ['const'] + names + ([f's{LATEST}'] if season_dummy else [])


def softmax_fit(X, Y, lam=1.0, iters=60):
    """multinomial logit, class 0 the reference, L2 on every coefficient but the intercepts (Newton)"""
    n, k = X.shape; K = Y.shape[1] - 1
    B = np.zeros((k, K))
    pen = np.ones(k); pen[0] = 0
    for _ in range(iters):
        P = probs(X, B)
        G = X.T @ (Y[:, 1:] - P[:, 1:]) - lam * pen[:, None] * B
        H = np.zeros((k * K, k * K))
        for a in range(K):
            for b in range(K):
                w = P[:, a + 1] * ((a == b) - P[:, b + 1])
                H[a * k:(a + 1) * k, b * k:(b + 1) * k] = -(X * w[:, None]).T @ X
        H -= lam * np.kron(np.eye(K), np.diag(pen))
        step = np.linalg.solve(H, G.T.reshape(-1))
        B -= step.reshape(K, k).T
        if np.abs(step).max() < 1e-7: break
    cov = np.linalg.inv(-H)
    se = np.sqrt(np.diag(cov)).reshape(K, k).T
    return B, se


def probs(X, B):
    z = np.concatenate([np.zeros((X.shape[0], 1)), X @ B], axis=1)
    z -= z.max(1, keepdims=True); e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def auc(p, y):
    o = np.argsort(p); y = np.asarray(y)[o]; n1 = y.sum(); n0 = len(y) - n1
    ranks = np.arange(1, len(y) + 1)
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def logit_fit(X, y, lam=1.0):
    B, se = softmax_fit(X, np.stack([1 - y, y], 1), lam)
    return B[:, 0], se[:, 0]


def sig(z): return 1 / (1 + np.exp(-z))


def scores(p, y):
    """out-of-sample report: AUC, log loss against the base rate, Brier, capture in the top decile, calibration"""
    y = np.asarray(y, float); base = y.mean()
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))); ll0 = float(-(base * math.log(base) + (1 - base) * math.log(1 - base)))
    o = np.argsort(-p); top = o[:len(o) // 10]
    dec = np.array_split(np.argsort(p), 10)
    return {'n': int(len(y)), 'rate': round(base, 4), 'auc': round(auc(p, y), 3), 'logLoss': round(ll, 4), 'logLossBase': round(ll0, 4),
            'skill': round(1 - ll / ll0, 3), 'brier': round(float(np.mean((p - y) ** 2)), 4), 'brierBase': round(float(base * (1 - base)), 4),
            'top10': round(float(y[top].mean()), 3), 'top10Share': round(float(y[top].sum() / y.sum()), 3),
            'calib': [[round(float(p[d].mean()), 3), round(float(y[d].mean()), 3)] for d in dec]}


def bands(rows, key, edges, label):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = [r for r in rows if r[key] is not None and lo <= r[key] < hi]
        if len(g) >= 30: out.append({label: f'{lo}-{hi}' if hi < 1e5 else f'{lo}+', 'n': len(g), 'rate': round(sum(r['y'] == 'transfer' for r in g) / len(g), 4)})
    return out


def main():
    tdiv, info, rosters, ath = collect()
    rec = recruits(); print('recruits linked', len(rec))
    pf = pfn(); print('pfn rows', len(pf))
    rows, loc = build(tdiv, info, rosters, ath, rec, pf)
    json.dump({k: [round(v[0], 3), round(v[1], 3), v[2]] for k, v in sorted(loc.items(), key=lambda kv: int(kv[0]))},
              open(LOC_OUT, 'w'), separators=(',', ':'))
    with open(os.path.join(CACHE, 'rows.json'), 'w') as h: json.dump(rows, h)
    print('rows', len(rows), Counter((r['season'], r['y']) for r in rows))
    fit(rows, info, loc)


LAM = 5.0


def talent(rows):
    """each school's talent that season: its players' mean recruiting grade as a z-score within the season (the
    landing model's measure); schools with fewer than five graded players get their level's 10th percentile"""
    by = defaultdict(list)
    for r in rows:
        if r['rec']: by[(r['season'], r['tid'])].append(r['rec'])
    lvl = {(r['season'], r['tid']): r['level'] for r in rows}
    out = {}
    for s in {k[0] for k in lvl}:
        m = {k: float(np.mean(v)) for k, v in by.items() if k[0] == s and len(v) >= 5}
        v = np.array(list(m.values())); mu, sd = v.mean(), v.std()
        lo = {lv: np.percentile([x for k, x in m.items() if lvl[k] == lv] or [mu], 10) for lv in ('P4', 'G5', 'FCS')}
        for k, lv in lvl.items():
            if k[0] == s: out[k] = round(float((m.get(k, lo[lv]) - mu) / sd), 3)
    for r in rows: r['tal'] = out[(r['season'], r['tid'])]
    # his starting quarterback transferred out that offseason (PFN starter)
    qb = {(r['season'], r['tid']) for r in rows if r['g'] == 'QB' and r['y'] == 'transfer' and (r['starter'] or 0) >= 0.5}
    for r in rows: r['qbLeft'] = int((r['season'], r['tid']) in qb)


def fit(rows, info, loc):
    talent(rows)
    old = [r for r in rows if r['season'] < LATEST]; new = [r for r in rows if r['season'] == LATEST]
    yT = lambda rs: np.array([r['y'] == 'transfer' for r in rs], float)
    # 1. out of time: fit on the earlier cycle(s), score the latest
    Xo, names = design(old); Xn, _ = design(new)
    bo, _ = logit_fit(Xo, yT(old), LAM)
    pn = sig(Xn @ bo)
    test = scores(pn, yT(new))
    test['byLevel'] = {lv: scores(pn[[i for i, r in enumerate(new) if r['level'] == lv]], yT([r for r in new if r['level'] == lv])) for lv in ('P4', 'G5', 'FCS')}
    for v in test['byLevel'].values(): v.pop('calib')
    print('transfer, out of time', {k: v for k, v in test.items() if k not in ('calib', 'byLevel')})
    # each feature group out of the out-of-time fit, scored per player on the latest cycle: paired log loss with the
    # group minus without, clustered by team (scripts/harness.py; t < 0: the group helps). One split only.
    import harness as H
    ll = lambda p, y: -(y * np.log(p) + (1 - y) * np.log(1 - p))
    l0, cl = ll(pn, yT(new)), np.array([r['tid'] for r in new])
    groups = {'class': ['exp2', 'exp3', 'exp4', 'exp5'], 'recruiting': ['ranked', 'rec', 'rec_dnp'], 'played': ['played'],
              'production': ['q', 'pct', 'starter', 'exp5_starter'], 'level': ['g5', 'fcs', 'pct_g5', 'st_g5'], 'team win%': ['winp'],
              'coach change': ['hc'], 'hometown': ['logdist', 'inState', 'abroad'], 'transfer in': ['xfer_in'],
              'playing time': ['gp', 'gp_g5', 'gp_fcs', 'spot'], 'program talent': ['tal', 'pct_tal'], 'QB left': ['qb_left'],
              'position': [n for n in names if n.startswith('pos_')]}
    drop = {}
    for g, cols in groups.items():
        keep = [i for i, n in enumerate(names) if n not in cols]
        b_, _ = logit_fit(Xo[:, keep], yT(old), LAM)
        pr = H.paired(l0, ll(sig(Xn[:, keep] @ b_), yT(new)), cl)
        drop[g] = {'d': round(float(pr['d']), 5), 't': round(float(pr['t']), 2), 'n': int(pr['n']), 'G': int(pr['G'])}
    test['dropOne'] = drop
    print('drop-one, out of time', {g: v['t'] for g, v in drop.items()})
    # 2. live: both cycles, with the latest cycle's level (portal volume) as a dummy
    Xa, namesA = design(rows, season_dummy=True)
    ba, sa = logit_fit(Xa, yT(rows), LAM)
    # 3. exit (out of eligibility, drafted, left the sport): only the latest pair labels it cleanly
    yE = np.array([r['y'] == 'exit' for r in new], float)
    folds = np.array([int(hashlib.md5(r['tid'].encode()).hexdigest(), 16) % 5 for r in new])   # by team
    pe = np.zeros(len(new))
    for f in range(5):
        b, _ = logit_fit(Xn[folds != f], yE[folds != f], LAM); pe[folds == f] = sig(Xn[folds == f] @ b)
    exit_cv = scores(pe, yE); exit_cv.pop('calib')
    be, se_e = logit_fit(Xn, yE, LAM)
    print('exit, 5-fold by team', exit_cv)
    # 4. head-coach change into next season, by team: the chance the scorer averages over
    teams = {}
    for r in rows:
        if r['hcChange'] is not None: teams[(r['season'], r['tid'])] = r
    T = list(teams.values())
    Xh = np.array([[1.0, (t['winp'] if t['winp'] is not None else 0.5) - 0.5, float(t['level'] == 'G5'), float(t['level'] == 'FCS')] for t in T])
    yh = np.array([t['hcChange'] for t in T], float)
    bh = logit_fit(Xh, yh, 1.0)[0] if len(T) > 50 else np.array([-1.6, 0, 0, 0])   # no coaching data: ~17% a year
    print('hc change', len(T), 'team-seasons, rate', yh.mean() if len(T) else None, 'coef', bh)
    # 5. hometown: transfer rate by distance from home, raw and with the model's controls
    us = [r for r in new + old if r['dist'] is not None and not r['abroad']]
    raw = bands(us, 'dist', [0, 50, 150, 300, 600, 1200, 100000], 'miles')
    instate = {'in': round(float(np.mean([r['y'] == 'transfer' for r in us if r['inState']])), 4), 'out': round(float(np.mean([r['y'] == 'transfer' for r in us if not r['inState']])), 4),
               'nIn': sum(1 for r in us if r['inState']), 'nOut': sum(1 for r in us if not r['inState'])}
    ix = {n: i for i, n in enumerate(namesA)}
    Xu, _ = design(us, season_dummy=True)
    def at(miles, ins):
        X = Xu.copy(); X[:, ix['logdist']] = math.log1p(miles / 100); X[:, ix['inState']] = ins
        return float(sig(X @ ba).mean())
    ctrl = [{'miles': m, 'inState': ins, 'p': round(at(m, ins), 4)} for m, ins in ((25, 1), (100, 1), (250, 1), (250, 0), (500, 0), (1000, 0), (2000, 0))]
    # where transfers go: home -> new school against home -> old school, and against a school picked at random
    # from the destination's level (the pull of home)
    mv = [r for r in us if r['y'] == 'transfer' and r['distNew'] is not None]
    by_level = defaultdict(list)
    for (s, tid), t in info.items():
        if s == LATEST + 1 and tid in loc: by_level[t['level']].append(loc[tid])
    edges = [0, 100, 250, 500, 1000, 100000]
    def band_of(m): return next(i for i in range(len(edges) - 1) if m < edges[i + 1])
    obs = Counter(band_of(r['distNew']) for r in mv); exp_ = Counter()
    for r in mv:
        cands = by_level.get(r['toLevel']) or by_level['FCS']
        for c in cands: exp_[band_of(miles(r['home'], c))] += 1 / len(cands)
    pull = [{'miles': f'{edges[i]}-{edges[i + 1]}' if edges[i + 1] < 1e5 else f'{edges[i]}+', 'share': round(obs[i] / len(mv), 4),
             'random': round(exp_[i] / len(mv), 4), 'ratio': round((obs[i] / len(mv)) / max(1e-9, exp_[i] / len(mv)), 2)} for i in range(len(edges) - 1)]
    closer = float(np.mean([r['distNew'] < r['dist'] for r in mv]))
    dd = np.array([r['distNew'] - r['dist'] for r in mv])
    far = [r for r in mv if r['dist'] >= 500]
    home = {
        'raw': raw, 'inState': instate, 'controlled': ctrl,
        'coef': {k: [round(float(ba[ix[k]]), 3), round(float(sa[ix[k]]), 3)] for k in ('logdist', 'inState', 'abroad')},
        'moves': {'n': len(mv), 'closer': round(closer, 3), 'medianChange': round(float(np.median(dd))), 'pull': pull,
                  'farCloser': round(float(np.mean([r['distNew'] < r['dist'] for r in far])), 3) if far else None, 'nFar': len(far),
                  'medianOld': round(float(np.median([r['dist'] for r in mv]))), 'medianNew': round(float(np.median([r['distNew'] for r in mv])))},
    }
    print('home', json.dumps(home)[:1500])
    out = {
        'asof': time.strftime('%Y-%m-%d'), 'pairs': PAIRS, 'n': len(rows),
        'counts': {str(s): dict(Counter(r['y'] for r in rows if r['season'] == s)) for s, _ in PAIRS},
        'lam': LAM, 'latest': LATEST,
        'transfer': {'names': namesA, 'coef': [round(float(x), 4) for x in ba], 'se': [round(float(x), 4) for x in sa], 'test': test, 'mean': [round(float(x), 4) for x in Xa.mean(0)]},
        'exit': {'names': names, 'coef': [round(float(x), 4) for x in be], 'se': [round(float(x), 4) for x in se_e], 'cv': exit_cv},
        'hc': {'names': ['const', 'winp', 'g5', 'fcs'], 'coef': [round(float(x), 4) for x in bh], 'rate': round(float(yh.mean()), 4) if len(T) else None, 'n': len(T)},
        'home': home,
        'labels': 'transfer = on another FBS/FCS team\'s roster the next season (ESPN), new there; 94% of P4 and 84% of G5 transfers are on CFBD\'s portal list',
    }
    if os.path.exists(OUT):   # the landing model (scripts/cfb_landing_fit.py) lives in the same file
        prev = json.load(open(OUT))
        if 'landing' in prev: out['landing'] = prev['landing']
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    if '--refit' in sys.argv:   # refit from the last build (scripts/.cache/transfer/rows.json) and the cached team pulls
        OFFLINE = True
        tdiv = {s: teams_of(s) for s in SEASONS}
        info = {(s, t): team_info(s, t, d) for s in SEASONS for t, d in tdiv[s].items()}
        loc = {k: v for k, v in json.load(open(LOC_OUT)).items()}
        fit(json.load(open(os.path.join(CACHE, 'rows.json'))), info, loc)
    else:
        main()
