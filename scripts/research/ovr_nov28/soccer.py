# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer OVR research rows (big five, Understat seasons 2015-22 in static/data/soccer-war): P = p/90 (pg90, projected
GAR a 90), D = SV (this season's GAR a 90, shrunk), Y = next season's GAR a 90. Rookie FV = the prospect board FV
(static/data/rookies/soccer.json pfv)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as NM


def season_file(s):
    fn = os.path.join(ROOT, 'static', 'data', 'soccer-war', f'{s}.json')
    return json.load(open(fn)) if os.path.exists(fn) else None


def rookie_fv():
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'rookies', 'soccer.json'))); out = {}
    for s in d['seasons']:
        for r in s['rows']:
            if r.get('pfv') is not None: out[(s['s'], NM.key(r['n']))] = r['pfv']
    return out


def rows():
    fv = rookie_fv(); F = {}
    for s in range(2015, 2023):
        d = season_file(s)
        if d: F[s] = {p['p']: p for p in d['players'] if p.get('min') and p.get('pg90') is not None and p.get('gar90') is not None}
    car = {}; out = []
    for s in sorted(F):
        nxt = F.get(s + 1)
        for pid, p in F[s].items():
            q = nxt.get(pid) if nxt else None
            r = {'s': s, 'id': pid, 'n_': p['n'], 'pos': p.get('pos'), 'age': p.get('age'), 'P': p['pg90'],
                 'D': p.get('sv') if p.get('sv') is not None else p['gar90'], 'n': p['min'], 'car': car.get(pid, 0),
                 'fv': fv.get((s, NM.key(p['n']))), 'tm': p.get('team'),
                 'Po': None, 'Pd': None}
            if q: r.update(Y=q['gar90'], Yn=q['min'], tmN=q.get('team'))
            out.append(r)
        for pid, p in F[s].items(): car[pid] = car.get(pid, 0) + p['min']
    first = {}
    for r in out:
        if r['fv'] is not None: first.setdefault(r['id'], (r['s'], r['fv']))
    for r in out:
        f = first.get(r['id'])
        if f and 0 <= r['s'] - f[0] <= 2: r['fv2'] = f[1]
    return out
