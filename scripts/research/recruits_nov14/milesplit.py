# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""High school track marks for football recruits, from MileSplit's public athlete search and stats feeds (the ones its
own athlete pages read; the rankings and performance lists need a login and are not used).

    python3 scripts/research/recruits_nov14/milesplit.py            # the history sample (ESPN grade >= 75, 2011-19)
    python3 scripts/research/recruits_nov14/milesplit.py --test "Henry Ruggs" AL 2017

A recruit is the MileSplit athlete with the same name key (scripts/names.py), the same home state and a graduation year
equal to his class; two or more such athletes: the one with the most marks. Cached in scripts/.cache/recruit/milesplit/.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import sys
import time
import urllib.parse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
from scripts_path import ROOT   # noqa: E402
import names as N               # noqa: E402

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'recruit', 'milesplit')
os.makedirs(CACHE, exist_ok=True)
API = 'https://www.milesplit.com/api/v1'
S = requests.Session(); S.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
EVENTS = {'100m', '200m', '400m', '55m', '60m', 'LJ', 'TJ', 'HJ', 'SP', 'D', 'DT', '110H', '300H'}


def get(url):
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if os.path.exists(f):
        try: return json.load(open(f))
        except ValueError: pass
    for i in range(4):
        try:
            r = S.get(url, timeout=30)
            if r.status_code in (401, 403, 404): v = {'data': [], 'status': r.status_code}; break
            r.raise_for_status(); v = r.json(); break
        except Exception:
            if i == 3: return None
            time.sleep(2 ** i)
    json.dump(v, open(f, 'w'))
    time.sleep(0.25)
    return v


def lookup(name, state, cls):
    """{'id', 'marks': {event: [mark, units]}} or None (no athlete), False (the search failed)"""
    q = ' '.join(w for w in name.replace('.', '').split() if w.lower() not in ('jr', 'sr', 'ii', 'iii', 'iv', 'v'))
    d = get(f'{API}/athletes/search?q={urllib.parse.quote(q)}')
    if d is None: return False
    k = N.key(name); best = None
    for a in d.get('data') or []:
        if N.key(f"{a.get('firstName', '')} {a.get('lastName', '')}") != k or (a.get('state') or '').upper() != (state or '').upper(): continue
        s = get(f"{API}/athletes/{a['id']}/stats")
        if not s: continue
        at = (s.get('_embedded') or {}).get('athlete') or {}
        if str(at.get('gradYear')) != str(cls) or at.get('gender') not in ('M', None, ''): continue
        marks = {}
        for x in s.get('data') or []:
            e = x.get('eventCode')
            try: u = float(x.get('units'))
            except (TypeError, ValueError): continue
            if e and u > 0 and (e not in marks or (u < marks[e][1]) == (e[0].isdigit())): marks[e] = [x.get('mark'), u]
        if best is None or len(marks) > len(best['marks']): best = {'id': a['id'], 'marks': marks}
    return best


def main():
    if '--test' in sys.argv:
        i = sys.argv.index('--test'); print(lookup(sys.argv[i + 1], sys.argv[i + 2], int(sys.argv[i + 3]))); return
    import data as D
    rows = [r for r in D.load() if r['grade'] >= 75 and r['state']]
    out_f = os.path.join(ROOT, 'scripts', '.cache', 'recruit', 'milesplit_hist.json')
    out = {}
    t0 = time.time()
    with cf.ThreadPoolExecutor(4) as ex:
        for n, (r, v) in enumerate(zip(rows, ex.map(lambda r: lookup(r['name'], r['state'], r['year']), rows))):
            if v: out[r['rid']] = v
            if n % 500 == 0: print(n, len(rows), len(out), round(time.time() - t0), flush=True)
    json.dump(out, open(out_f, 'w'))
    print('matched', len(out), 'of', len(rows))


if __name__ == '__main__':
    main()
