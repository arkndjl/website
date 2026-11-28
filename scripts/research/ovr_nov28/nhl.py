# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL OVR research rows (per group F / D / G): P = pWAR a 60 (PR #1395: calibrated to next season's WAR a 60),
D = WAR a 60 this season, Y = next season's WAR a 60. Rookie FV = the draft-year hockey
board FV (static/data/rookies/nhl.json pfv)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as NM


def season_file(s):
    fn = os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{s}.json')
    return json.load(open(fn)) if os.path.exists(fn) else None


def rookie_fv():
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'rookies', 'nhl.json'))); out = {}
    for s in d['seasons']:
        for r in s['rows']:
            if r.get('pfv') is not None: out[(s['s'], NM.key(r['n']))] = r['pfv']
    return out


def rate(p, k='war'): return p[k] / p['toi'] * 60 if p.get('toi') and p.get(k) is not None else None


def rows(grp, last=2026):
    fv = rookie_fv(); F = {}; REP = {}
    for s in range(2009, last + 2):
        d = season_file(s)
        if d:
            REP[s] = d.get('repl') or {}
            F[s] = {p['id']: p for p in d['players'] if p.get('grp') == grp and p.get('toi') and p.get('hpm') is not None}
    car = {}; out = []
    for s in sorted(F):
        nxt = F.get(s + 1)
        for pid, p in F[s].items():
            q = nxt.get(pid) if nxt else None
            r = {'s': s, 'id': pid, 'n_': p['n'], 'pos': p.get('pos') if grp == 'F' else grp, 'age': p.get('age'),
                 'P': rate(p, 'pwar'), 'P0': p['hpm'] - REP[s].get(grp, 0), 'D': rate(p), 'n': p['toi'], 'car': car.get(pid, 0),
                 'fv': fv.get((s, NM.key(p['n']))), 'tm': p.get('tm'),
                 'Po': p.get('o'), 'Pd': p.get('d')}
            if q and rate(q) is not None:
                r.update(Y=rate(q), Yn=q['toi'], tmN=q.get('tm'))
            out.append(r)
        for pid, p in F[s].items(): car[pid] = car.get(pid, 0) + p['toi']
    first = {}
    for r in out:
        if r['fv'] is not None: first.setdefault(r['id'], (r['s'], r['fv']))
    for r in out:
        f = first.get(r['id'])
        if f and 0 <= r['s'] - f[0] <= 2: r['fv2'] = f[1]
    return out
