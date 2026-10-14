#!/usr/bin/env python3
"""MaxPreps' high school football ratings, every state and season: scripts/.cache/maxpreps/<season>.json.

    python3 scripts/cfb_hs_teams.py 22-23 23-24     # pull those seasons (default: 19-20 through this one)

Each team: MaxPreps school id, name, city and state (from the team link), record, rating (MaxPreps' computer
rating, a national points scale) and strength (its schedule strength on the same scale). The recruit fit links a
recruit's high school (ESPN gives its name, city and state) to these to test the level of competition he faced.

Tested 2026-10-14 on the 2023-26 classes (87% of high schools link): team rating and schedule strength add
nothing on top of the kept recruit model (P(on) t -0.02 and 0.08, FV(on) t 1.06 and 0.87), so they are not in
the fit. A multi-sport test on the same links (MaxPreps basketball and baseball rosters, junior and senior
seasons: 2,718 two-sport recruits) failed too (P(on) t 0.5, FV(on) t -2.1). MaxPreps lists track rosters for
few schools, so it is no source for sprint times.
"""
import concurrent.futures as cf
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'maxpreps')
STATES = ('al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok or pa '
          'ri sc sd tn tx ut vt va wa wv wi wy').split()
S = requests.Session(); S.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'


def page(st, season, n):
    url = f'https://www.maxpreps.com/{st}/football/{season}/rankings/{n}/'
    for i in range(5):
        try:
            r = S.get(url, timeout=40)
            if r.status_code == 404: return None, 0
            r.raise_for_status()
            d = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S).group(1))
            L = d['props']['pageProps'].get('rankingsListData') or {}
            return L.get('rankings') or [], L.get('totalCount') or 0
        except Exception as e:
            if i == 4: print('fail', url, e, flush=True); return None, 0
            time.sleep(2 ** i)


def team(x):
    m = re.search(r'maxpreps\.com/([a-z]{2})/([^/]+)/([^/]+)/football', x.get('teamLink') or '')
    return {'id': x['schoolId'], 'name': x['schoolName'], 'st': x.get('stateCode'), 'city': m.group(2) if m else None,
            'slug': m.group(3) if m else None, 'rank': x.get('rank'), 'rec': x.get('overall'), 'rating': x.get('rating'), 'strength': x.get('strength')}


def state(st, season):
    first, tot = page(st, season, 1)
    if not first: return []
    out = [team(x) for x in first]
    for n in range(2, (tot + 49) // 50 + 1):
        r, _ = page(st, season, n)
        if not r: break
        out += [team(x) for x in r]
    return out


def season_pull(season):
    f = os.path.join(CACHE, f'{season}.json')
    if os.path.exists(f): return json.load(open(f))
    with cf.ThreadPoolExecutor(8) as ex: rows = [t for ts in ex.map(lambda s: state(s, season), STATES) for t in ts]
    os.makedirs(CACHE, exist_ok=True)
    json.dump(rows, open(f, 'w'), separators=(',', ':'))
    return rows


if __name__ == '__main__':
    for s in sys.argv[1:] or [f'{y % 100:02d}-{(y + 1) % 100:02d}' for y in range(2019, 2027)]:
        t = time.time(); rows = season_pull(s)
        print(s, len(rows), 'teams', sum(r['rating'] is not None for r in rows), 'rated', round(time.time() - t), 's', flush=True)


# ---- link ESPN's high schools to MaxPreps ------------------------------------------------------------------
STOP = {'high', 'school', 'senior', 'hs', 'the', 'of', 'and', 'sr', 'jr', 'h', 's'}
ALIAS = {'st': 'saint', 'mt': 'mount', 'ft': 'fort', 'preparatory': 'prep', 'acad': 'academy', 'chr': 'christian', 'cath': 'catholic'}


def toks(s):
    w = re.sub(r"[^a-z0-9 ]", ' ', (s or '').lower().replace('&', ' and ').replace("'", '')).split()
    return {ALIAS.get(x, x) for x in w if x not in STOP and len(x) > 1 or x.isdigit()}


def cslug(s): return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def seasons():
    """{season: {school id: team}} for every cached season, and {state: [school]} across them."""
    out, sch = {}, {}
    for f in sorted(os.listdir(CACHE)):
        if not re.match(r'\d\d-\d\d\.json$', f): continue
        rows = json.load(open(os.path.join(CACHE, f))); out[f[:5]] = {t['id']: t for t in rows}
        for t in rows: sch[t['id']] = t
    by = {}
    for t in sch.values(): by.setdefault(t['st'], []).append(t)
    return out, by


def linker(by_state):
    """ESPN high school {name, address: {city, stateAbbreviation}} -> MaxPreps school id, or None. A candidate in
    the same state scores on shared name tokens (MaxPreps drops 'High School' and often prefixes or suffixes the
    city); the city breaks ties. Only a clear best is taken."""
    memo = {}

    def go(h):
        a = h.get('address') or {}; st = a.get('stateAbbreviation'); city = cslug(a.get('city'))
        key = (h.get('name'), st, city)
        if key in memo: return memo[key]
        e = toks(h.get('name')); best = []
        for t in by_state.get(st, []):
            m = toks(t['name']) - toks(t['city'].replace('-', ' ') if t['city'] else '') if city and cslug(t['city']) == city else toks(t['name'])
            if not m: m = toks(t['name'])
            sh = len(e & m)
            if not sh: continue
            sc = sh / len(m | e) + (0.5 if city and cslug(t['city']) == city else 0) + (0.3 if m <= e else 0)
            best.append((sc, t['id']))
        best.sort(reverse=True)
        r = best[0][1] if best and best[0][0] >= 0.75 and (len(best) == 1 or best[0][0] - best[1][0] >= 0.2) else None
        memo[key] = r
        return r
    return go
