#!/usr/bin/env python3
"""Soccer prospects rebuild for the Nov 3 2026 frame test, with a generic research User-Agent.

    python3 scripts/research/frame_nov03/soccer_pull.py dump
    python3 scripts/research/frame_nov03/soccer_pull.py games [comps] --seasons A-B     # soccer_prospect_data.py games
    python3 scripts/research/frame_nov03/soccer_pull.py profiles [threads]                # feeder profiles (age <= 23)
"""
import concurrent.futures as cf
import glob
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
import soccer_prospect_data as SD  # noqa: E402

UA = 'arkboard-research/1.0 (+https://arkndjl.net)'


def get(path, tries=5):
    for k in range(tries):
        try:
            req = urllib.request.Request(SD.API + path, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 405):
                print('blocked', e.code, path, flush=True)
                return None
            time.sleep(2 ** k)
        except Exception:
            time.sleep(2 ** k)
    return None


SD.get = get


def dump():
    d = os.path.join(os.path.dirname(SD.CACHE), 'dump')
    if os.path.exists(os.path.join(d, 'players.csv.gz')):
        return
    os.makedirs(d, exist_ok=True)
    req = urllib.request.Request('https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip',
                                 headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=900) as r:
        zipfile.ZipFile(io.BytesIO(r.read())).extractall(d)


def profiles(nthreads):
    import pandas as pd
    ids = set()
    for fn in glob.glob(os.path.join(SD.CACHE, '*_20*.json.gz')):
        for g in json.load(gzip.open(fn, 'rt')):
            for p in g[9]:
                if p[4] is not None and p[4] <= 23:
                    ids.add(int(p[0]))
    p = pd.read_csv(os.path.join(SD.CACHE, '..', 'dump', 'players.csv.gz'), usecols=['player_id', 'date_of_birth', 'height_in_cm'])
    ok = set(p[p.date_of_birth.notna() & p.height_in_cm.notna()].player_id.astype(int))
    fn = os.path.join(SD.CACHE, 'players.json.gz')
    have = json.load(gzip.open(fn, 'rt')) if os.path.exists(fn) else {}
    todo = [str(i) for i in sorted(ids - ok) if str(i) not in have]
    print('ids', len(ids), 'todo', len(todo), flush=True)
    n = 0
    with cf.ThreadPoolExecutor(nthreads) as ex:
        for i, r in zip(todo, ex.map(lambda i: get(f'/player/{i}'), todo)):
            if r and r.get('data'):
                d = r['data']
                have[i] = {k: d.get(k) for k in ('name', 'lifeDates', 'attributes', 'marketValueDetails', 'clubAssignments')}
            n += 1
            if n % 5000 == 0:
                print(n, flush=True)
    tmp = fn + '.tmp'
    with gzip.open(tmp, 'wt') as f:
        json.dump(have, f)
    os.replace(tmp, fn)
    print('profiles', len(have), flush=True)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'dump':
        dump()
    elif a[0] == 'profiles':
        profiles(int(a[1]) if len(a) > 1 else 16)
    else:
        sys.argv = [sys.argv[0]] + a
        SD.main()
