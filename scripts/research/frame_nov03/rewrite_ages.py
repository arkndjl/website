#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""One-off (Nov 3 2026): rewrite only the age fields of the committed board JSON to two decimals from real birth dates,
so the pages show exact ages before the next scheduled builds (which now write them). Each board's age is recomputed
at the date its builder uses and checked against the stored rounded age; a row whose birth date cannot be found or
does not agree keeps its age (shown ~ where the builder now marks estimates).

    python3 scripts/research/frame_nov03/rewrite_ages.py hockey|cs2|soccer|tennis|nhl|nfl [--dry]
"""
import csv
import datetime as dt
import glob
import gzip
import io
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(SCR)
sys.path.insert(0, SCR)
UA = 'arkboard-research/1.0 (+https://arkndjl.net)'
DRY = '--dry' in sys.argv
STATS = {}


def fetch(url, raw=False):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json' if not raw else '*/*'})
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    return b if raw else json.loads(b)


def yrs(a, b):
    return (a - b).days / 365.25


def save(fn, d, indent=None):
    if DRY:
        return
    old = open(fn).read()
    sep = (', ', ': ') if not indent and '", "' in old[:2000] else (',', ':') if not indent else None
    txt = json.dumps(d, indent=indent, separators=sep)
    open(fn, 'w').write(txt + ('\n' if old.endswith('\n') else ''))


def fmt_of(fn):
    """keep the file's own layout: indented or compact"""
    s = open(fn).read(200)
    return 1 if '\n ' in s else None


def tally(board, n, ok, est=0, bad=0):
    STATS[board] = {'rows': n, 'exact': ok, 'estimated': est, 'disagree': bad, 'share': round(ok / max(n, 1), 3)}
    print(board, STATS[board], flush=True)


def check(old, new, tol):
    return old is None or abs(old - new) <= tol


# ---------------------------------------------------------------- hockey (data/hockey.json)
def hockey():
    import nhl_data as D
    D.UA = UA
    import hockey_prospects as H
    import hockey_provisional as HP
    fn = os.path.join(ROOT, 'data', 'hockey.json')
    d = json.load(open(fn))
    rows = json.load(gzip.open(H.ROWS, 'rt'))
    birth = {r['id']: r.get('birth') for r in rows if r.get('id')}
    cur = d['season']
    n = ok = bad = 0
    for p in d['pipe']:
        n += 1
        b = birth.get(p.get('id'))
        if b:
            a = round(H.age_at(b, cur - 1), 2)
            if check(p.get('age'), a, .051):
                p['age'] = a; ok += 1
            else:
                bad += 1
    tally('hockey pipeline', n, ok, 0, bad)
    year, tk = H.tankathon()
    HP.live(year, [], [])                      # fills HP._BIRTHS from the CHL/AHL/USHL/Liiga feeds
    tkb = {t['name']: t['birth'] for t in tk}
    n = ok = est = bad = 0
    for p in d['board']:
        n += 1
        if p.get('prov'):
            c = {b for nm, b in HP._BIRTHS if __import__('names').same(nm, p['name'])
                 and abs(H.age_at(b, d['year']) - (p.get('age') or 0)) <= .051}
            if len(c) == 1:
                p['age'] = round(H.age_at(c.pop(), d['year']), 2); ok += 1
            elif p.get('age') is not None:
                p['ageEst'] = 1; est += 1
            continue
        b0 = tkb.get(p['name'])
        eb = HP.exact_birth(p['name'], b0) if b0 else None
        if eb and check(p.get('age'), H.age_at(eb, d['year']), .1):
            p['age'] = round(H.age_at(eb, d['year']), 2); p.pop('ageEst', None); ok += 1
        elif p.get('age') is not None:
            p['ageEst'] = 1; est += 1
    tally('hockey board', n, ok, est, bad)
    save(fn, d, fmt_of(fn))
    mf = os.path.join(ROOT, 'data', 'hockey_mock.json')
    if os.path.exists(mf):
        m = json.load(open(mf))
        by = {p['name']: p for p in d['board']}
        k = 0

        def walk(o):
            nonlocal k
            if isinstance(o, dict):
                if 'name' in o and 'age' in o and o['name'] in by:
                    q = by[o['name']]
                    o['age'] = q.get('age')
                    if q.get('ageEst'):
                        o['ageEst'] = 1
                    else:
                        o.pop('ageEst', None)
                    k += 1
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(m)
        print('hockey mock rows', k)
        save(mf, m, fmt_of(mf))


# ---------------------------------------------------------------- CS2 (data/cs2_players.json)
def cs2():
    import cs2_pstats as PS
    pdir = json.load(gzip.open(PS.PDIR, 'rt'))
    fn = os.path.join(ROOT, 'data', 'cs2_players.json')
    d = json.load(open(fn))
    T = dt.date.fromisoformat(d['asof'][:10]) + dt.timedelta(days=1)
    for key in ('board', 'prospects'):
        n = ok = bad = 0
        for p in d[key]:
            n += 1
            b = (pdir.get(str(p['id'])) or [None] * 3)[2]
            if not b:
                continue
            try:
                a = round(yrs(T, dt.date.fromisoformat(b[:10])), 2)
            except ValueError:
                continue
            if check(p.get('age'), a, .051):
                p['age'] = a; ok += 1
            else:
                bad += 1
        tally('cs2 ' + key, n, ok, 0, bad)
    save(fn, d, fmt_of(fn))


# ---------------------------------------------------------------- soccer prospects (data/soccer_prospects.json)
def soccer():
    import pandas as pd  # noqa
    api = 'https://tmapi-alpha.transfermarkt.technology/player/'
    fn = os.path.join(ROOT, 'data', 'soccer_prospects.json')
    d = json.load(open(fn))
    ids = sorted({p['id'] for p in d['board']} | {p['id'] for p in d.get('past', [])})

    def dob(i):
        for _ in range(3):
            try:
                j = fetch(api + str(i))
                return ((j.get('data') or {}).get('lifeDates') or {}).get('dateOfBirth')
            except Exception:
                pass
        return None
    with ThreadPoolExecutor(8) as ex:
        DOB = dict(zip(ids, ex.map(dob, ids)))
    t = int(str(d.get('season') or 2026)[:4])
    for key in ('board', 'past'):
        n = ok = est = bad = 0
        for p in d.get(key, []):
            n += 1
            b = DOB.get(p['id'])
            s = t if key == 'board' else p['season']
            try:
                a = round(yrs(dt.date(int(s), 7, 1), dt.date.fromisoformat(b[:10])), 2) if b else None
            except ValueError:
                a = None
            if a is not None and check(p.get('age'), a, .051):
                p['age'] = a; p.pop('ageEst', None); ok += 1
            elif a is not None:
                bad += 1
                if key == 'board':
                    p['ageEst'] = 1; est += 1
            elif key == 'board':
                p['ageEst'] = 1; est += 1
        tally('soccer ' + key, n, ok, est, bad)
    save(fn, d, fmt_of(fn))


# ---------------------------------------------------------------- tennis prospects (data/tennis_prospects.json)
def tennis():
    import tennis_prospects as TP
    Z = json.load(gzip.open(TP.FROZEN, 'rt'))
    pl = json.load(gzip.open(TP.RATINGS, 'rt'))['players']
    fn = os.path.join(ROOT, 'data', 'tennis_prospects.json')
    d = json.load(open(fn))
    D = dt.date.fromisoformat(d['asof']) + dt.timedelta(days=7)          # features(.., today + 7 days, ..)
    for tour in ('atp', 'wta'):
        P = Z[tour]['P']
        n = ok = bad = 0
        for p in d[tour]['board']:
            n += 1
            k = p['id'][1:]
            b = (P.get(k) or [None] * 3)[2] or (pl.get(p['id']) or {}).get('dob')
            if not b:
                continue
            b = str(int(b))
            a = round(yrs(D, dt.date(int(b[:4]), int(b[4:6]), int(b[6:8]))), 2)
            if check(p.get('age'), a, .051):
                p['age'] = a; ok += 1
            else:
                bad += 1
        tally('tennis ' + tour, n, ok, 0, bad)
        n = ok = 0
        for p in d[tour].get('past', []):
            n += 1
    save(fn, d, fmt_of(fn))


# ---------------------------------------------------------------- NHL WAR (static/data/nhl-war/<season>.json)
def nhl():
    b = fetch('https://moneypuck.com/moneypuck/playerData/playerBios/allPlayersLookup.csv', raw=True).decode('utf-8', 'replace')
    bio = {r['playerId']: r.get('birthDate') for r in csv.DictReader(io.StringIO(b))}
    for fn in sorted(glob.glob(os.path.join(ROOT, 'static', 'data', 'nhl-war', '*.json'))):
        S = int(os.path.basename(fn)[:4])
        d = json.load(open(fn))
        n = ok = bad = 0
        for p in d.get('players', []):
            n += 1
            bd = bio.get(str(p['id']))
            if not bd:
                continue
            try:
                bd = dt.date.fromisoformat(bd[:10])
            except ValueError:
                continue
            ref = dt.date(S - 1, 9, 15)
            whole = ref.year - bd.year - ((ref.month, ref.day) < (bd.month, bd.day))
            if p.get('age') in (None, whole):
                p['ax'] = round(yrs(ref, bd), 2); ok += 1
            else:
                bad += 1
        tally(f'nhl war {S}', n, ok, 0, bad)
        save(fn, d, fmt_of(fn))


# ---------------------------------------------------------------- NFL WAR (static/data/nfl-war.json)
def nfl():
    import names as NM
    fn = os.path.join(ROOT, 'static', 'data', 'nfl-war.json')
    d = json.load(open(fn))
    y = d['season']
    txt = fetch(f'https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{y}.csv', raw=True).decode()
    R = list(csv.DictReader(io.StringIO(txt)))
    by = {}
    for r in R:
        for k in (r.get('pfr_id'), r.get('gsis_id')):
            if k:
                by[k] = r.get('birth_date')
        by[(NM.key(r['full_name']), r['team'])] = r.get('birth_date')
    n = ok = bad = 0
    for p in d['players']:
        n += 1
        bd = by.get(p['id']) or by.get((NM.key(p['n']), p.get('t') or (p.get('tm') or '').split('/')[0]))
        try:
            bd = dt.date.fromisoformat(bd[:10])
        except (TypeError, ValueError):
            continue
        whole = y - bd.year - ((9, 1) < (bd.month, bd.day))
        if p.get('age') in (None, whole):
            p['ax'] = round(yrs(dt.date(y, 9, 1), bd), 2); ok += 1
        else:
            bad += 1
    tally('nfl war', n, ok, 0, bad)
    save(fn, d, fmt_of(fn))


if __name__ == '__main__':
    for a in sys.argv[1:]:
        if not a.startswith('--'):
            globals()[a]()
    print(json.dumps(STATS))
