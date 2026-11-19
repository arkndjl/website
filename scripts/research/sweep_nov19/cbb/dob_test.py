#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Leads 3a / 3b: FIBA roster archive birth dates (match precision) and the class-conditional birth-day estimate for
year-only rows. Pre-registered in impl/cbb/prereg.md.   python3 scripts/research/sweep_nov19/cbb/dob_test.py"""
import datetime as dt, gzip, json, os, sys
from collections import defaultdict, Counter
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import names as N
import cbb_data as D

FIBA = os.environ.get('FIBA_ROSTERS', '/mnt/project-files/research/cbb-new-sources/fiba_rosters.json.gz')
CLS = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4}
exact = lambda d: bool(d) and len(d) == 10 and not d.endswith('-10-15')
day = lambda d: dt.date.fromisoformat(d)


def fiba_index():
    by = defaultdict(set)
    for r in json.load(gzip.open(FIBA)):
        if r.get('dob') and r.get('name'):
            by[N.key(r['name'])].add(r['dob'])
    return by


def pools():
    """[(pool, name key, dob, first season, first class)]"""
    out = []
    d = json.load(gzip.open(os.path.join(D.HERE, 'cbb_prior.json.gz')))
    K = {k: i for i, k in enumerate(d['keep'])}
    for c in d['careers']:
        ss = c['seasons']
        if ss and not isinstance(ss[0], list): ss = [ss]
        if not ss: continue
        out.append(('board', c.get('key') or '', c.get('dob'), ss[0][K['year']], ss[0][K['yr']]))
    for c in json.load(open(os.path.join(D.CACHE, 'careers.json'))):
        s0 = c['seasons'][0]
        out.append(('kit', N.key(c['name']), c.get('dob'), s0['year'], s0.get('yr')))
    return out


def age_nov1(dob, season):
    return D.age_on(dob, season - 1, 11, 1)


def part_a(P, F):
    res = {}
    for use_year in (True, False):
        cnt = Counter((p[0], p[1]) for p in P)
        n = ok = 0; bad = []
        for pool, k, dob, y0, yr in P:
            if not exact(dob) or (pool == 'kit' and y0 < 2012) or cnt[(pool, k)] != 1: continue
            fd = F.get(k)
            if not fd or len(fd) != 1: continue
            f = next(iter(fd))
            a = age_nov1(f, y0)
            if a is None or not (16.5 <= a <= 23.0): continue
            if use_year and abs(int(f[:4]) - int(dob[:4])) > 1: continue
            n += 1
            if abs((day(f) - day(dob)).days) <= 3: ok += 1
            else: bad.append((k, dob, f))
        res['with_year' if use_year else 'no_year'] = {'n': n, 'agree3d': ok, 'share': round(ok / max(1, n), 4), 'misses': bad[:12]}
    # what it would add on the board
    add = Counter()
    cnt = Counter(p[1] for p in P if p[0] == 'board')
    for pool, k, dob, y0, yr in P:
        if pool != 'board' or exact(dob) or cnt[k] != 1: continue
        fd = F.get(k)
        if not fd or len(fd) != 1: continue
        f = next(iter(fd)); a = age_nov1(f, y0)
        if a is None or not (16.5 <= a <= 23.0): continue
        if dob and abs(int(f[:4]) - int(dob[:4])) > 1: continue
        add['year_only' if dob else 'none'] += 1
    res['board_adds'] = dict(add)
    return res


def kof(dob, y0, yr):
    return y0 - int(dob[:4]) - (CLS.get(yr, 1) - 1)


def doy(dob):
    d = day(dob); return (d - dt.date(d.year, 1, 1)).days


def part_b(P):
    tr = defaultdict(list)
    for pool, k, dob, y0, yr in P:
        if pool == 'kit' and exact(dob) and y0 <= 2022: tr[kof(dob, y0, yr)].append(doy(dob))
    m = {k: float(np.mean(v)) for k, v in tr.items() if len(v) >= 30}
    allm = float(np.mean([x for v in tr.values() for x in v]))
    e_new, e_oct, e_jul, ks = [], [], [], Counter()
    for pool, k, dob, y0, yr in P:
        if pool != 'board' or not exact(dob) or y0 < 2023: continue
        kk = kof(dob, y0, yr); ks[kk] += 1
        est = m.get(kk, allm)
        t = doy(dob)
        e_new.append(abs(t - est) / 365.25); e_oct.append(abs(t - 287) / 365.25); e_jul.append(abs(t - 181) / 365.25)
    e_new, e_oct, e_jul = map(np.array, (e_new, e_oct, e_jul))
    t = lambda a, b: float((b - a).mean() / ((b - a).std(ddof=1) / np.sqrt(len(a))))
    return {'m_days': {str(k): round(v, 1) for k, v in sorted(m.items())}, 'train_n': {str(k): len(v) for k, v in sorted(tr.items()) if len(v) >= 30},
            'fallback_days': round(allm, 1), 'held_n': len(e_new), 'held_k': dict(sorted(ks.items())),
            'mae_est': round(float(e_new.mean()), 4), 'mae_oct15': round(float(e_oct.mean()), 4), 'mae_jul1': round(float(e_jul.mean()), 4),
            't_vs_oct15': round(t(e_new, e_oct), 2), 't_vs_jul1': round(t(e_new, e_jul), 2)}


if __name__ == '__main__':
    P = pools(); F = fiba_index()
    out = {'a': part_a(P, F), 'b': part_b(P)}
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.environ.get('OUT', '/mnt/project-files/research-sweep-nov19/impl/cbb/dob_results.json'), 'w'), indent=1)
