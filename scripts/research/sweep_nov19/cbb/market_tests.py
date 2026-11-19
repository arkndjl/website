#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Leads 4, 7a, 7b (family M): hometown distance and EADA men's basketball expenses in the CBB market models.
Pre-registered in impl/cbb/prereg.md.

    python3 scripts/research/sweep_nov19/cbb/market_tests.py EADA_JSON   # EADA_JSON: {year: [{institution_name, EXP_MEN, ...}]}
"""
import gzip, json, math, os, re, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import names as N
import cbb_market_fit as M

OUT = os.environ.get('OUT', '/mnt/project-files/research-sweep-nov19/impl/cbb/market_results.json')
PLACES = json.load(open(os.path.join(M.HERE, 'geo', 'us_places.json')))
CENT = {st: (sum(v[0] for v in d.values()) / len(d), sum(v[1] for v in d.values()) / len(d)) for st, d in PLACES.items() if isinstance(d, dict) and d and st != '_src'}
EADA_ALIAS = {'university of north carolina at chapel hill': 'North Carolina', 'university of illinois urbana-champaign': 'Illinois',
              'university of minnesota-twin cities': 'Minnesota', 'pennsylvania state university-main campus': 'Penn St.',
              'ohio state university-main campus': 'Ohio St.', 'university of pittsburgh-pittsburgh campus': 'Pittsburgh',
              'rutgers university-new brunswick': 'Rutgers', 'university of missouri-columbia': 'Missouri',
              'university of nebraska-lincoln': 'Nebraska', 'university of tennessee-knoxville': 'Tennessee',
              'louisiana state university and agricultural & mechanical college': 'LSU', 'university of south carolina-columbia': 'South Carolina',
              'university of oklahoma-norman campus': 'Oklahoma', 'oklahoma state university-main campus': 'Oklahoma St.',
              'university of texas at austin': 'Texas', 'the university of texas at austin': 'Texas', 'texas a & m university-college station': 'Texas A&M',
              'university of colorado boulder': 'Colorado', 'university of washington-seattle campus': 'Washington',
              'university of california-los angeles': 'UCLA', 'university of california-berkeley': 'California',
              'university of southern california': 'USC', 'arizona state university campus immersion': 'Arizona St.', 'arizona state university-tempe': 'Arizona St.',
              'university of maryland-college park': 'Maryland', 'purdue university-main campus': 'Purdue', 'indiana university-bloomington': 'Indiana',
              'university of michigan-ann arbor': 'Michigan', 'university of wisconsin-madison': 'Wisconsin', 'university of virginia-main campus': 'Virginia',
              'virginia polytechnic institute and state university': 'Virginia Tech', 'north carolina state university at raleigh': 'N.C. State',
              'georgia institute of technology-main campus': 'Georgia Tech', 'university of cincinnati-main campus': 'Cincinnati',
              'university of connecticut': 'Connecticut', 'university of mississippi': 'Mississippi', 'the university of alabama': 'Alabama',
              'the university of tennessee-knoxville': 'Tennessee', 'university of nevada-las vegas': 'UNLV', 'university of new mexico-main campus': 'New Mexico',
              'university of south florida': 'South Florida', 'university of south florida-main campus': 'South Florida', 'university of central florida': 'UCF',
              'university of houston': 'Houston', 'university of memphis': 'Memphis', 'brigham young university': 'BYU', 'brigham young university-provo': 'BYU',
              'texas christian university': 'TCU', 'southern methodist university': 'SMU', 'university of kansas': 'Kansas', 'university of kentucky': 'Kentucky',
              'university of massachusetts-amherst': 'Massachusetts', 'virginia commonwealth university': 'VCU', "saint john's university-new york": "St. John's",
              "st. john's university-new york": "St. John's", 'university of miami': 'Miami FL', 'miami university-oxford': 'Miami OH',
              'university of akron main campus': 'Akron', 'bowling green state university-main campus': 'Bowling Green', 'kent state university at kent': 'Kent St.',
              'ohio university-main campus': 'Ohio', 'university of toledo': 'Toledo', 'wright state university-main campus': 'Wright St.',
              'new mexico state university-main campus': 'New Mexico St.', 'university of hawaii at manoa': 'Hawaii', 'university of nevada-reno': 'Nevada',
              'california state university-fresno': 'Fresno St.', 'san diego state university': 'San Diego St.', 'colorado state university-fort collins': 'Colorado St.',
              'university of alabama at birmingham': 'UAB', 'university of north carolina at charlotte': 'Charlotte', 'university of texas at el paso': 'UTEP',
              'the university of texas at el paso': 'UTEP', 'the university of texas at san antonio': 'UTSA', 'the university of texas at arlington': 'UT Arlington',
              'university of louisiana at lafayette': 'Louisiana', 'university of louisiana at monroe': 'Louisiana Monroe', 'florida international university': 'FIU',
              'west virginia university': 'West Virginia', 'texas tech university': 'Texas Tech', 'university of arkansas': 'Arkansas'}


EADA_ALIAS.update({k.lower(): v for k, v in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'eada_alias.json'))).items()})


def geocode(home):
    try:
        city, st = [x.strip() for x in home.rsplit(',', 1)]
    except ValueError:
        return None
    d = PLACES.get(st)
    if not isinstance(d, dict): return None
    k = re.sub(r'[^a-z0-9]', '', city.lower())
    for v in (k, k.replace('saint', 'st'), k.replace('mount', 'mt'), k.replace('fort', 'ft')):
        if v in d: return tuple(d[v][:2])
    return CENT.get(st)


def eada_key(n):
    s = n.lower().strip()
    s = re.sub(r'-main campus$| main campus$', '', s)
    s = re.sub(r'^the ', '', s)
    s = re.sub(r'^university of ', '', s)
    s = re.sub(r' university$| college$', '', s)
    s = s.replace(' state university', ' state').replace(' at ', ' ').replace('-', ' ')
    return s


def eada_map(path, names):
    """{(EADA year, Barttorvik team): ln men's basketball expenses z-scored inside the year}"""
    raw = json.load(open(path))
    out, miss = {}, defaultdict(int)
    for y, rows in raw.items():
        vals = {}
        for r in rows:
            nm = r['institution_name']
            t = EADA_ALIAS.get(nm.lower().strip())
            if t not in names:
                t = M.match_team(eada_key(nm), names) or M.match_team(nm, names)
            try: x = float(r.get('EXP_MEN') or 0)
            except (TypeError, ValueError): x = 0.0
            if not t or x <= 0:
                miss[nm] += 1; continue
            vals[t] = math.log(x)
        mu, sd = np.mean(list(vals.values())), np.std(list(vals.values()))
        for t, v in vals.items(): out[(int(y), t)] = (v - mu) / sd
    return out, miss


def ct(d, g):
    s = defaultdict(float)
    for x, k in zip(d, g): s[k] += x
    v = np.array(list(s.values()))
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))) if len(v) > 1 and v.std() > 0 else 0.0


def event_ll(X, ev, ch, b):
    p = M.clogit_p(X, ev, b)
    starts = np.r_[0, np.flatnonzero(np.diff(ev)) + 1]
    ll, rk = [], []
    for i, s0 in enumerate(starts):
        s1 = starts[i + 1] if i + 1 < len(starts) else len(ev)
        c = np.flatnonzero(ch[s0:s1])
        if not len(c): ll.append(np.nan); rk.append(np.nan); continue
        ll.append(math.log(p[s0:s1][c[0]] + 1e-12)); rk.append(int((p[s0:s1] > p[s0:s1][c[0]]).sum()) + 1)
    return np.array(ll), np.array(rk)


def land_data(by, TS, raw, loc, years):
    X, ev, ch, info = M.land_events(by, TS, raw, loc, years)
    cand = []
    for (y, pid, o, dest) in info:
        cand += [t for t in sorted({r['team'] for r in by[y + 1]}) if t != o]
    assert len(cand) == len(ev)
    return X, ev, ch, info, cand


def land_test(by, TS, raw, loc, extra, covered, label):
    """extra(info row, candidate team) -> [features]; covered(info row) -> bool (held rows scored)"""
    D = {y: land_data(by, TS, raw, loc, [y]) for y in range(M.NIL0, 2026)}

    def aug(y):
        X, ev, ch, info, cand = D[y]
        E = np.array([extra(info[e], t) for e, t in zip(ev, cand)], float)
        return X, np.hstack([X, E]), ev, ch, info

    def stack(ys):
        Xs, Es, evs, chs, off = [], [], [], [], 0
        for y in ys:
            X, XE, ev, ch, info = aug(y)
            Xs.append(X); Es.append(XE); evs.append(ev + off); chs.append(ch); off += ev.max() + 1
        return np.vstack(Xs), np.vstack(Es), np.concatenate(evs), np.concatenate(chs)

    def score(fit_years, y):
        X, XE, ev, ch = stack(fit_years)
        b0, b1 = M.clogit(X, ev, ch, lam=1.0), M.clogit(XE, ev, ch, lam=1.0)
        Xt, XEt, evt, cht, info = aug(y)
        l0, r0 = event_ll(Xt, evt, cht, b0); l1, r1 = event_ll(XEt, evt, cht, b1)
        k = np.array([covered(i) for i in info]) & ~np.isnan(l0)
        return l0[k], l1[k], r0[k], r1[k], [i[2] for i, kk in zip(info, k) if kk], b1
    l0, l1, r0, r1, org, b1 = score([2022, 2023, 2024], 2025)
    d = l1 - l0
    res = {'label': label, 'held_n': int(len(d)), 'held_ll_base': round(float(l0.mean()), 4), 'held_ll_cand': round(float(l1.mean()), 4), 'held_t': round(ct(d, org), 2),
           'top10_base': round(float((r0 <= 10).mean()), 3), 'top10_cand': round(float((r1 <= 10).mean()), 3), 'coef_extra': [round(float(x), 4) for x in b1[len(M.LAND_F):]]}
    lo = []
    for y in (2022, 2023, 2024):
        a0, a1, *_ = score([z for z in (2022, 2023, 2024) if z != y], y)
        lo.append(round(float((a1 - a0).mean()), 4))
    res['tune_loyo_d'] = lo
    res['covered_share_held'] = round(float(np.mean([covered(i) for i in D[2025][3]])), 3)
    res['pass'] = bool(res['held_t'] >= 2 and sum(lo) > 0)
    return res


def pay_test(TS, raw, miss, E):
    src = json.load(gzip.open(M.SRC))['pay']
    names = {t for (_, t) in TS}
    kept = json.load(open(M.OUT))['value']['feats']
    rows = []
    for r in src['list']:
        t = M.match_team(r['school'], names)
        if not t: continue
        for y, cid, nm, pay in src['schools'].get(r['sid'], []):
            if not pay or y < 2015 or y > 2026: continue
            co = raw.get(y, {}).get(t)
            ten = co.get('ten') if co else 3
            f = M.val_feats(TS, y, t, ten or 3, M.cres(miss, co['coach'], y) if co else 0.0, M.conf_of(y, t) in M.P6 if M.conf_of(y, t) else True)
            rows.append((y, t, math.log(pay), f, E.get((y - 1, t))))
    have = sum(r[4] is not None for r in rows)
    yrs = sorted({r[0] for r in rows}); schools = sorted({r[1] for r in rows})
    yv = np.array([r[2] for r in rows])

    def design(ex):
        return np.array([[1.0] + [float(r[0] == z) for z in yrs[1:]] + [r[3][M.VAL_F.index(k)] for k in kept] + ([r[4] or 0.0] if ex else []) for r in rows])
    err = {}
    for ex in (False, True):
        X = design(ex); e = np.zeros(len(rows))
        for s in schools:
            m = np.array([r[1] == s for r in rows])
            e[m] = X[m] @ M.ridge(X[~m], yv[~m], 1.0) - yv[m]
        err[ex] = e
    d = err[False] ** 2 - err[True] ** 2
    ss = float(((yv - yv.mean()) ** 2).sum())
    b = M.ridge(design(True), yv, 1.0)
    return {'n': len(rows), 'schools': len(schools), 'rows_with_eada': have, 'rmse_base': round(float(np.sqrt((err[False] ** 2).mean())), 4),
            'rmse_cand': round(float(np.sqrt((err[True] ** 2).mean())), 4), 'r2_base': round(1 - float((err[False] ** 2).sum()) / ss, 3),
            'r2_cand': round(1 - float((err[True] ** 2).sum()) / ss, 3), 't_school': round(ct(d, [r[1] for r in rows]), 2), 'coef': round(float(b[-1]), 4),
            'pass': bool(ct(d, [r[1] for r in rows]) >= 2)}


if __name__ == '__main__':
    by = M.player_rows()
    for y, rs in by.items():
        for r in rs: M.CONF[(y, r['team'])] = r['conf']
    TS, bt = M.team_seasons()
    loc = M.geo(bt)
    raw, miss = M.coaches()
    names = {t for (_, t) in TS}
    out = {}
    # ---- lead 4: hometown
    rec = json.load(gzip.open(os.path.join(M.HERE, 'data', 'cbb_recruit_hist.json.gz')))['recruits']
    idx = {}
    for r in rec:
        c = r.get('college') or {}
        if r.get('home') and c.get('team') and c.get('y1'):
            g = geocode(r['home'])
            if g: idx[(N.key(r['name']), c['team'], int(c['y1']))] = g
    home = {}
    for y, rs in by.items():
        for r in rs:
            g = idx.get((N.key(r['name']), r['team'], y))
            if g: home[r['pid']] = g

    def hx(info, t):
        h = home.get(info[1]); mi = M.miles(h, loc.get(t)) if h else None
        return [math.log1p(mi) - 6.5, float(mi < 150)] if mi is not None else [0.0, 0.0]
    if '--skip4' not in sys.argv: out['lead4'] = land_test(by, TS, raw, loc, hx, lambda i: i[1] in home, 'hometown hlogmi + hnear')
    if 'lead4' in out:
        out['lead4']['players_with_home'] = len(home)
        print(json.dumps(out['lead4']), flush=True)
    # ---- lead 7
    E, em = eada_map(sys.argv[1], names)
    if '--map' in sys.argv:
        print([v for v in EADA_ALIAS.values() if v not in names], len(E), sum(1 for (y, t) in E if y == 2024), len({t for (_, t) in TS if _ == 2025}), sorted(em, key=lambda k: -em[k])[:150]); sys.exit()
    out['eada_match'] = {'team_years': len(E), 'unmatched_names': len(em), 'matched_2024': sum(1 for (y, t) in E if y == 2024)}
    out['lead7b'] = land_test(by, TS, raw, loc, lambda info, t: [E.get((info[0] - 1, t), 0.0)], lambda i: True, 'EADA dest ln MBB expenses')
    print(json.dumps(out['lead7b']), flush=True)
    out['lead7a'] = pay_test(TS, raw, miss, E)
    print(json.dumps(out['lead7a']), flush=True)
    out['eada_unmatched_sample'] = sorted(em, key=lambda k: -em[k])[:40]
    json.dump(out, open(OUT, 'w'), indent=1)
