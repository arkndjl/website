# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA OVR research rows: P = pXPM (sxpm, season end), D = team-adjusted rXPM (txpm), Y = next season's txpm.
Rookie FV = the draft-year CBB board FV (static/data/rookies/nba.json pfv)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as NM

REPL = -1.4


def pos3(p):
    p = (p or '').split('-')[0].split('/')[0]
    return 'C' if p == 'C' else 'G' if p in ('PG', 'SG', 'G') else 'F'


def season_file(s):
    fn = os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{s}.json')
    return json.load(open(fn)) if os.path.exists(fn) else None


def rookie_fv():
    """(season, name key) -> FV"""
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'rookies', 'nba.json'))); out = {}
    for s in d['seasons']:
        for r in s['rows']:
            if r.get('pfv') is not None: out[(s['s'], NM.key(r['n']))] = r['pfv']
    return out


def d_of(p): return p.get('txpm') if p.get('txpm') is not None else p.get('xpm')


def rows(last=2026):
    fv = rookie_fv(); F = {}
    for s in range(2010, last + 2):
        d = season_file(s)
        if d: F[s] = {p['id']: p for p in d['players'] if p.get('xpm') is not None and not p.get('pr')}
    car = {}; out = []
    for s in sorted(F):
        nxt = F.get(s + 1)
        for pid, p in F[s].items():
            q = nxt.get(pid) if nxt else None
            r = {'s': s, 'id': pid, 'n_': p['n'], 'pos': pos3(p.get('pos')), 'age': p.get('age'), 'P': p.get('sxpm'),
                 'D': d_of(p), 'n': p['mp'], 'car': car.get(pid, 0), 'fv': fv.get((s, NM.key(p['n']))),
                 'Po': p.get('soxpm'), 'Pd': p.get('sdxpm'), 'Do': p.get('toxpm', p.get('oxpm')), 'Dd': p.get('tdxpm', p.get('dxpm')),
                 'tm': p.get('tm'), 'games': None}
            if q:
                r.update(Y=d_of(q), Yn=q['mp'], tmN=q.get('tm'), Yo=q.get('toxpm', q.get('oxpm')), Yd=q.get('tdxpm', q.get('dxpm')))
            out.append(r)
        for pid, p in F[s].items(): car[pid] = car.get(pid, 0) + p['mp']
    # rookie FV also for second-year rows (his draft FV carried one more season)
    first = {}
    for r in out:
        if r['fv'] is not None: first[r['id']] = (r['s'], r['fv'])
    for r in out:
        f = first.get(r['id'])
        if f and r['fv'] is None and r['s'] - f[0] in (1, 2): r['fv2'] = f[1]
        if r['fv'] is not None: r['fv2'] = r['fv']
    return out
