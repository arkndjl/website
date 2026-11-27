#!/usr/bin/env python3
"""Each school's recruiting class, commit by commit, for the class rankings dropdown and the class GFX card
(assets/js/gfx.js buildClassCard, layouts/partials/classdrop.html).

Reads static/data/cfb-recruits.json (every graded recruit, scripts/cfb_recruit.mjs) and data/cbb_recruits.json
(scripts/cbb_recruit_fit.py) and writes static/data/classes/cfb.json and cbb.json:

  {asof, y: {<class year>: {of: schools ranked, t: {<school>: {rk, s, n, a6, a5, a4, avg, te, dp, x, conf,
     g: [[position group, commits, FV points, mean FV], ...],
     r: [{n name, p position, g group, h height, w weight, o hometown, hs high school, f FV, y Y1 FV, x xNIL,
          a ARK stars, s industry stars, sp industry 5-star+, i On3 photo path}, ...] best first}}}}}

The class numbers (rank, score, star counts, top end, depth) are copied from the class rankings rows, never
recomputed. Rerun after either recruit file changes (cfb-recruits.yml, cbb-recruits.yml). --test checks the
files against the class rankings.
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'static', 'data', 'classes')
CFB_G = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ATH', 'K', 'P', 'LS']
CBB_G = ['PG', 'CG', 'SG', 'SF', 'PF', 'C']


def load(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return json.load(f)


def feet(inches):
    return '%d-%d' % (inches // 12, inches % 12) if inches else None


def img(u):
    return re.sub(r'^https://on3static\.com/', '', u) if u else None


def groups(rows, order, floor):
    by = {}
    for r in rows:
        by.setdefault(r['g'], []).append(r['fx'])
    keys = [k for k in order if k in by] + sorted(k for k in by if k not in order)
    return [[k, len(by[k]), round(sum(v - floor for v in by[k]), 1), round(sum(by[k]) / len(by[k]), 1)] for k in keys]


def pack(rows, order, floor):
    # best first: ARK stars, then FV (the order of the class rankings' top commits)
    rows = sorted(rows, key=lambda r: (-(r['a'] or 0), -r['fx'], r['n']))
    g = groups(rows, order, floor)
    for r in rows:
        del r['fx']
        for k in [k for k, v in r.items() if v is None or v == '']:
            del r[k]
    return g, rows


def cfb():
    d = load('static', 'data', 'cfb-recruits.json')
    floor = d.get('floor', 20)
    sets = [(d['next'], d['class'], d['teams'])] + [(f['year'], f['list'], f.get('teams') or []) for f in d.get('future', [])]
    out = {'asof': d['asof'], 'y': {}}
    for yr, lst, teams in sets:
        if not teams:
            continue
        by = {}
        for r in lst:
            if not r.get('team') or r.get('status') == 'uncommitted':
                continue
            by.setdefault(r['team'], []).append({
                'n': r['name'], 'p': r['pos'].split('-')[0], 'g': r.get('g') or r['pos'], 'h': feet(r.get('ht')), 'w': r.get('wt'),
                'o': r.get('home'), 'f': round(r['xfv']), 'y': round(r['fvOn']), 'x': r.get('xnil'), 'a': r.get('ark'),
                's': r.get('stars'), 'i': img(r.get('img')), 'fx': r['xfv']})
        T = {}
        for t in teams:
            g, rows = pack(by.get(t['team'], []), CFB_G, floor)
            T[t['team']] = {'rk': t['classRk'], 's': t['classXfv'], 'n': t['classN'], 'a6': t.get('a6', 0), 'a5': t.get('a5', 0), 'a4': t.get('a4', 0),
                            'avg': t.get('avgXfv'), 'te': t.get('topRk'), 'dp': t.get('depthRk'), 'x': t.get('classXnil'), 'conf': t.get('conf'), 'g': g, 'r': rows}
        out['y'][str(yr)] = {'of': len(teams), 't': T}
    return out


def cbb():
    d = load('data', 'cbb_recruits.json')
    floor = 20
    by_yr = d.get('teamsBy') or {str(d['classes'][0]['year']): d['teams']}
    out = {'asof': d['asof'], 'y': {}}
    for c in d['classes']:
        teams = by_yr.get(str(c['year'])) or []
        if not teams:
            continue
        by = {}
        for r in c['list']:
            if not r.get('team'):
                continue
            by.setdefault(r['team'], []).append({
                'n': r['name'], 'p': r['pos'], 'g': r['pos'], 'h': r.get('ht'), 'w': r.get('wt'), 'o': r.get('home'), 'hs': r.get('hs'),
                'f': round(r['fv']), 'y': round(r['y1fv']), 'x': r.get('xnil'), 'a': r.get('ark'), 's': r.get('stars'),
                'sp': 1 if r.get('fsp') else None, 'i': img(r.get('img')), 'fx': r['fv']})
        T = {}
        for t in teams:
            g, rows = pack(by.get(t['team'], []), CBB_G, floor)
            T[t['team']] = {'rk': t['rk'], 's': round(t['ets'], 1), 'n': t['n'], 'a6': t.get('a6', 0), 'a5': t.get('a5', t.get('ark5', 0)), 'a4': t.get('a4', t.get('ark4', 0)),
                            'avg': t.get('avgFv'), 'te': t.get('topRk'), 'dp': t.get('depthRk'), 'x': t.get('xnil'), 'conf': t.get('conf'), 'g': g, 'r': rows}
        out['y'][str(c['year'])] = {'of': len(teams), 't': T}
    return out


def check(name, out):
    bad = []
    for yr, Y in out['y'].items():
        for team, t in Y['t'].items():
            if len(t['r']) != t['n']:
                bad.append('%s %s %s: %d commits listed, class rankings say %d' % (name, yr, team, len(t['r']), t['n']))
            if sum(g[1] for g in t['g']) != len(t['r']):
                bad.append('%s %s %s: position groups do not add up' % (name, yr, team))
            for r in t['r']:
                if not all(k in r for k in ('n', 'p', 'f', 'y', 'a')):
                    bad.append('%s %s %s: %s is missing a core field' % (name, yr, team, r.get('n')))
    return bad


def main():
    test = '--test' in sys.argv
    os.makedirs(OUT, exist_ok=True)
    bad = []
    for name, fn in (('cfb', cfb), ('cbb', cbb)):
        out = fn()
        bad += check(name, out)
        if not test:
            with open(os.path.join(OUT, name + '.json'), 'w') as f:
                json.dump(out, f, separators=(',', ':'), ensure_ascii=False)
        print('%s: %s' % (name, ', '.join('%s %d schools, %d commits' % (yr, len(Y['t']), sum(len(t['r']) for t in Y['t'].values())) for yr, Y in out['y'].items())))
    for b in bad:
        print('MISMATCH', b)
    if test:
        sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
