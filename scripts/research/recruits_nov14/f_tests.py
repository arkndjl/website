# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Football tests F1-F5 (pre-registered, /mnt/project-files/recruits/arkstars-nov14/prereg.md) on the corrected history.

    python3 scripts/research/recruits_nov14/f_tests.py [f1 f2 f3 f4 f5]
"""
import datetime as dt
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data as D   # noqa: E402
import rh as H     # noqa: E402
R, T = H.R, H.T
import names as N  # noqa: E402

ON3 = os.path.join(R.ROOT, 'scripts', '.cache', 'cfb', 'on3')
MS = os.path.join(R.ROOT, 'scripts', '.cache', 'recruit', 'milesplit_hist.json')


def attach_on3(data):
    """On3's industry row for each ESPN recruit: name key + home state, else a name key that is unique in the class"""
    by_y = defaultdict(list)
    for r in data: by_y[r['year']].append(r)
    hit = Counter()
    for y, rows in by_y.items():
        f = os.path.join(ON3, f'{y}.json')
        if not os.path.exists(f): continue
        o3 = json.load(open(f)); by = defaultdict(list); cnt = Counter(N.key(o['name']) for o in o3)
        for o in o3: by[(N.key(o['name']), o.get('state'))].append(o); by[N.key(o['name'])].append(o)
        # z of every service's rating within the class (among recruits the service rated)
        for s in ('247', 'espn'):
            v = [o['svc'][s][0] for o in o3 if s in o['svc']]; m, sd = (np.mean(v), np.std(v) or 1) if v else (0, 1)
            for o in o3: o['z' + s] = (o['svc'][s][0] - m) / sd if s in o['svc'] else None
        v = [o['cons'] for o in o3 if o['cons']]; m, sd = np.mean(v), np.std(v)
        for o in o3: o['zc'] = (o['cons'] - m) / sd if o['cons'] else None
        # schools showing interest: the residual on the industry rating within the class
        pts = [(o['zc'], math.log1p(o['interest'])) for o in o3 if o['zc'] is not None and o['interest']]
        b = np.polyfit([p[0] for p in pts], [p[1] for p in pts], 1); rs = np.std([p[1] - np.polyval(b, p[0]) for p in pts]) or 1
        for o in o3: o['intRes'] = (math.log1p(o['interest']) - np.polyval(b, o['zc'])) / rs if o['zc'] is not None and o['interest'] else None
        for r in rows:
            k = N.key(r['name']); c = by.get((k, r['state'])) or (by.get(k) if cnt[k] == 1 else None) or []
            r['o3'] = c[0] if len(c) == 1 else None; hit[(y, r['o3'] is not None)] += 1
    return hit


def on3_blocks():
    def on3(r):
        o = r.get('o3')
        return {'indz': (o['cons'] - 85) / 5 if o and o['cons'] else 0.0, 'noInd': 0.0 if o and o['cons'] else 1.0}
    def svc(r):
        o = r.get('o3') or {}
        return {'g247': (o['z247'] - o['zc']) if o.get('z247') is not None and o.get('zc') is not None else 0.0,
                'gEspn': (o['zespn'] - o['zc']) if o.get('zespn') is not None and o.get('zc') is not None else 0.0}
    def rec(r):
        o = r.get('o3') or {}; y = r['year']; m = 0.0; early = 0.0; no = 1.0
        if o.get('commitDate'):
            d = dt.date.fromisoformat(o['commitDate'][:10]); no = 0.0
            m = max(0.0, min(24.0, (dt.date(y - 1, 12, 20) - d).days / 30.4)); early = 1.0 if d < dt.date(y - 1, 9, 1) else 0.0
        return {'intRes': o['intRes'] if o.get('intRes') is not None else 0.0, 'commitM': m, 'commitEarly': early, 'noCommit': no}
    H.EXTRA.update({'on3': on3, 'svc': svc, 'rec': rec})


def grade_pos():
    def gp(r):
        g = (r['grade'] - 75) / 5 if r['grade'] >= 60 else 0.0
        return {f'g_{p}': g if r['g'] == p else 0.0 for p in R.GROUPS if p != 'WR'}
    H.EXTRA['grade_pos'] = gp


SPRINT = {'100m': 1.0, '200m': 1.0, '55m': 1.0, '60m': 1.0}
THROW = ('S', 'D')
JUMP = ('LJ', 'HJ', 'TJ')


def attach_track(data):
    ms = json.load(open(MS)) if os.path.exists(MS) else {}
    for r in data: r['ms'] = (ms.get(r['rid']) or {}).get('marks') if r['rid'] in ms else None; r['msLooked'] = r['rid'] in ms
    # z of each event against the matched recruits of his position group (times: faster is positive)
    ref = defaultdict(list)
    for r in data:
        for e, (_, u) in (r['ms'] or {}).items(): ref[(r['g'], e)].append(u)
    st = {k: (float(np.mean(v)), float(np.std(v)) or 1.0) for k, v in ref.items() if len(v) >= 20}
    def best(r, evs, sign):
        z = [sign * (u - st[(r['g'], e)][0]) / st[(r['g'], e)][1] for e, (_, u) in (r['ms'] or {}).items() if e in evs and (r['g'], e) in st]
        return max(-3.0, min(3.0, max(z))) if z else None
    def track(r):
        sp, th, ju = best(r, SPRINT, -1), best(r, THROW, 1), best(r, JUMP, 1)
        return {'hasTrack': 1.0 if r['ms'] else 0.0, 'sprint': sp or 0.0, 'hasSprint': 1.0 if sp is not None else 0.0,
                'throw': th or 0.0, 'jump': ju or 0.0}
    H.EXTRA['track'] = track
    return len(ms)


def main():
    which = set(sys.argv[1:]) or {'f1', 'f2', 'f3', 'f4', 'f5'}
    data = H.prep(H.dedupe(D.load()))
    sz = R.size_norms(data)
    print('rows', len(data), 'drafted', sum(r['on'] for r in data))
    out = {}
    if which & {'f1', 'f2', 'f3'}:
        hit = attach_on3(data); on3_blocks()
        print('On3 linked by class', {y: f"{hit[(y, True)]}/{hit[(y, True)] + hit[(y, False)]}" for y in sorted({k[0] for k in hit})})
        rated = [r for r in data if r['grade'] >= 60]
        print('rated linked', round(np.mean([r.get('o3') is not None for r in rated]), 3), 'comp present', round(np.mean([bool(r.get('comp')) for r in rated]), 3))
    if 'f1' in which:
        out['F1a on3 added'] = H.test(data, sz, ['on3'])
        out['F1b on3 in place of comp+gap'] = H.test(data, sz, ['on3'], drop=('comp', 'gap'))
    if 'f2' in which:
        out['F2 service gaps added'] = H.test(data, sz, ['svc'])
        out['F2b on3 + service gaps in place of comp+gap'] = H.test(data, sz, ['on3', 'svc'], drop=('comp', 'gap'))
    if 'f3' in which:
        out['F3 recruitment fields'] = H.test(data, sz, ['rec'])
    if 'f5' in which:
        grade_pos(); out['F5 grade by position'] = H.test(data, sz, ['grade_pos'])
    if 'f4' in which:
        n = attach_track(data)
        # the site refused requests from row 4,384 of the sample on (class 2014): the test is on the recruits looked up before that
        sub = [r for r in data if r.get('msLooked')]
        print('track: matched', n, 'sample', len(sub), 'with marks', sum(bool(r['ms']) for r in sub), 'drafted', sum(r['on'] for r in sub))
        out['F4 track (grade >= 75)'] = H.test(sub, sz, ['track'])
    for k, v in out.items(): print(k, json.dumps(v))
    f = os.path.join(HERE, 'f_tests.json'); prev = json.load(open(f)) if os.path.exists(f) else {}
    prev.update(out); json.dump(prev, open(f, 'w'), indent=1)


if __name__ == '__main__':
    main()
