# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pull ESPN recruiting classes (hometown, grade, schools in the recruitment, visits, commitment) and each listed
school's campus (ESPN venue city) for scripts/recruit_commit_fit.py. Cache: scripts/.cache/recruit_commit/
  python3 scripts/recruit_commit_pull.py [--force]"""
import glob, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'recruit_commit')
LG = {'cfb': 'football/leagues/college-football', 'cbb': 'basketball/leagues/mens-college-basketball'}
TID = re.compile(r'/teams/(\d+)')


def get(url):
    for i in range(5):
        try:
            r = requests.get(url, timeout=60)
            if r.ok: return r.json()
        except Exception: pass
        time.sleep(2 ** i)
    return None


def pull(sport, y, force=False):
    out = os.path.join(CACHE, f'{sport}-{y}.json')
    if os.path.exists(out) and not force: return out
    acc = []
    for pg in range(1, 30):
        d = get(f'https://sports.core.api.espn.com/v2/sports/{LG[sport]}/recruiting/{y}/athletes?limit=1000&page={pg}')
        if not d: break
        for it in d.get('items', []):
            a = it.get('athlete') or {}; at = {x['name']: x.get('value') for x in it.get('attributes') or []}
            ht = a.get('hometown') or {}; hs = (a.get('highSchool') or {}).get('address') or {}
            sch = []
            for s in it.get('schools') or []:
                m = TID.search((s.get('team') or {}).get('$ref', ''))
                if m: sch.append([m.group(1), (s.get('status') or {}).get('description'), (s.get('visit') or '')[:10] or None])
            acc.append({'rid': a.get('id'), 'name': a.get('fullName'), 'pos': (a.get('position') or {}).get('abbreviation'),
                        'grade': it.get('grade') or 0, 'rank': at.get('rank'), 'city': ht.get('city') or hs.get('city'),
                        'state': ht.get('stateAbbreviation') or hs.get('stateAbbreviation'), 'hsCity': hs.get('city'), 'hsState': hs.get('stateAbbreviation'),
                        'status': (it.get('status') or {}).get('description'), 'schools': sch})
        if pg >= (d.get('pageCount') or 1): break
    os.makedirs(CACHE, exist_ok=True)
    json.dump(acc, open(out, 'w'))
    print(sport, y, len(acc), flush=True)
    return out


def team(sport, tid):
    for y in (2025, 2022, 2018, 2014):
        d = get(f'https://sports.core.api.espn.com/v2/sports/{LG[sport]}/seasons/{y}/teams/{tid}')
        if d and d.get('venue', {}).get('address'):
            a = d['venue']['address']
            g = (d.get('groups') or {}).get('$ref', '')
            return tid, {'name': d.get('location'), 'city': a.get('city'), 'state': a.get('state'), 'group': g.split('/groups/')[-1].split('?')[0] if g else None}
    return tid, None


CAMPUS = os.path.join(ROOT, 'scripts', 'geo', 'recruit_campus.json')


def teams():
    """campus city/state for every school id in the cached lists (kept in git: scripts/geo/recruit_campus.json)"""
    allc = json.load(open(CAMPUS)) if os.path.exists(CAMPUS) else {}
    for sport in ('cfb', 'cbb'):
        ids = set()
        for f in glob.glob(os.path.join(CACHE, f'{sport}-[0-9]*.json')):
            for r in json.load(open(f)):
                for s in r['schools']: ids.add(s[0])
        have = allc.setdefault(sport, {})
        todo = [t for t in ids if t not in have]
        with ThreadPoolExecutor(12) as ex:
            for tid, v in ex.map(lambda t: team(sport, t), todo): have[tid] = v
        print(sport, len(ids), sum(1 for v in have.values() if v and v['city']))
    json.dump(allc, open(CAMPUS, 'w'), indent=0, sort_keys=True)


if __name__ == '__main__':
    jobs = [('cfb', y) for y in range(2012, 2030)] + [('cbb', y) for y in range(2010, 2030)]
    force = '--force' in sys.argv
    with ThreadPoolExecutor(6) as ex: list(ex.map(lambda j: pull(*j, force=force), jobs))
    teams()
