#!/usr/bin/env python3
"""Each school's recruiting class, commit by commit, for the class rankings dropdown and the class GFX card
(assets/js/gfx.js buildClassCard, layouts/partials/classdrop.html).

Reads static/data/cfb-recruits.json (every graded recruit, scripts/cfb_recruit.mjs) and data/cbb_recruits.json
(scripts/cbb_recruit_fit.py) and writes static/data/classes/cfb.json and cbb.json:

  {asof, y: {<class year>: {of: schools ranked, t: {<school>: {rk, s, n, a6, ah, am, al, avg, te, dp, x, conf,
     g: [[position group, commits, FV points, mean FV], ...],
     r: [{n name, p position, g group, h height, w weight, o hometown, hs high school, f FV, y Y1 FV, x xNIL,
          a ARK stars, s industry stars, sp industry 5-star+, i On3 photo path,
          fl [school, logo, date] he flipped from (static/data/moves/<sport>.json)}, ...] best first,
     ld: uncommitted recruits the school leads for, best first: {n, p, a, f, i, e: [experts on it, experts with a pick]
         (On3/Rivals, data/recruit_expert_picks.json), r: On3 RPM % (data/recruit_rpm.json), l: ARK lean %
         (data/recruit_commit_leans.json)},
     v: visits to the school, upcoming first (date >= today), then the last VISIT_DAYS days' officials:
        {d date, k o official | u unofficial, n, p, a, f, i, c school he is committed to, cl its logo when it is another school}}}}}}

a6 = 5-star+, ah = 4.5-5, am = 3-4, al = unranked to 2.5 ARK stars (copied from the class rankings rows).
Visits come from On3's live pull of uncommitted recruits and the weekly pull of committed ones
(scripts/data/recruit_on3_live.json.gz, recruit_on3_committed.json.gz), joined by scripts/names.py.

The class numbers (rank, score, star counts, top end, depth) are copied from the class rankings rows, never
recomputed. Rerun after either recruit file changes (cfb-recruits.yml, cbb-recruits.yml). --test checks the
files against the class rankings.
"""
import datetime as dt
import gzip
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names  # noqa: E402
from player_moves import school_slugs  # noqa: E402
VISIT_DAYS = 30
LEADS, VISITS = 8, 10
OUT = os.path.join(ROOT, 'static', 'data', 'classes')
CFB_G = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ATH', 'K', 'P', 'LS']
CBB_G = ['PG', 'CG', 'SG', 'SF', 'PF', 'C']
BUCKETS = ('a6', 'ah', 'am', 'al')


def load(*p, default=None):
    f = os.path.join(ROOT, *p)
    try:
        return json.load(gzip.open(f, 'rt') if f.endswith('.gz') else open(f, encoding='utf-8'))
    except (OSError, ValueError):
        if default is None: raise
        return default


def who(r, sp):
    return {'n': r['name'], 'p': r['pos'].split('-')[0] if sp == 'cfb' else r['pos'], 'a': r.get('ark'),
            'f': round(r['xfv'] if sp == 'cfb' else r['fv']), 'i': img(r.get('img'))}


def leads(sp, yr, lst):
    """{school: [lead rows]}: the uncommitted recruits the experts, On3's RPM or the ARK lean put at the school"""
    src = [(k, (load('data', f, default={}).get(sp) or {}).get(str(yr)) or {}) for k, f in
           (('e', 'recruit_expert_picks.json'), ('r', 'recruit_rpm.json'), ('l', 'recruit_commit_leans.json'))]
    out = {}
    for r in lst:
        if r.get('team'): continue
        row = {}
        for k, m in src:
            v = m.get(r['name'])
            if not v: continue
            sch = v[0]
            row.setdefault(sch, who(r, sp))[k] = [v[1], v[2]] if k == 'e' else round(v[1])
        for sch, x in row.items(): out.setdefault(sch, []).append(x)
    for sch in out:
        out[sch].sort(key=lambda x: (-sum(k in x for k in 'erl'), -(x['a'] or 0), -x['f']))
        out[sch] = out[sch][:LEADS]
    return out


def visits(sp, yr, lst, today):
    """{school: [visit rows]}: upcoming visits, then the last VISIT_DAYS days' officials"""
    slugs, since = school_slugs(), (dt.date.fromisoformat(today) - dt.timedelta(days=VISIT_DAYS)).isoformat()
    m, out, seen = names.Matcher(lst, team=None), {}, set()
    for f in ('recruit_on3_live.json.gz', 'recruit_on3_committed.json.gz'):
        for o in (load('scripts', 'data', f, default={}).get(sp) or {}).get(str(yr)) or []:
            r, _ = m.find(o.get('name'))
            if not r or (o.get('state') and r.get('home') and not r['home'].endswith(o['state'])): continue
            for v in o.get('visits') or []:
                sch, d, k = slugs.get(v[0]), v[2], 'o' if v[1] == 'Official' else 'u'
                if not sch or not d or (d < today and (k == 'u' or d < since)) or (r['name'], sch, d) in seen: continue
                seen.add((r['name'], sch, d))
                out.setdefault(sch, []).append(dict(who(r, sp), d=d, k=k, c=r.get('team') or None, cl=(r.get('logo') or None) if r.get('team') and r.get('team') != sch else None))
    for sch in out:
        up = sorted((x for x in out[sch] if x['d'] >= today), key=lambda x: (x['d'], -x['f']))
        past = sorted((x for x in out[sch] if x['d'] < today), key=lambda x: x['d'], reverse=True)
        out[sch] = [{k: v for k, v in x.items() if v is not None} for x in (up + past)[:VISITS]]
    return out


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


_MV = {}


def flipped(sp, name, yr, team):
    """[school, logo, date]: the school he was committed to before this one (a flip, or a commit to another school
    before this one), from static/data/moves/<sp>.json (scripts/player_moves.py); None when there was none"""
    if sp not in _MV: _MV[sp] = load('static', 'data', 'moves', sp + '.json', default={})
    m = _MV[sp]
    T, L = m.get('t') or [], m.get('l') or []
    nm = lambda i: T[i] if 0 <= i < len(T) else None
    rows = [x for x in (m.get('p') or {}).get(names.key(name)) or [] if x[4] in (0, int(yr))]
    out = None
    for d, k, fr, to, _ in rows:   # oldest first: the latest earlier school wins
        if k == 'flip' and nm(fr) and not names.same_team(nm(fr), team): out = [nm(fr), (L[fr] or None) if fr < len(L) else None, d]
        elif k == 'commit' and nm(to) and not names.same_team(nm(to), team): out = [nm(to), (L[to] or None) if to < len(L) else None, d]
        elif k in ('commit', 'flip') and nm(to) and names.same_team(nm(to), team) and out and k == 'commit' and d and out[2] and d < out[2]: out = None
    return out


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
                's': r.get('stars'), 'i': img(r.get('img')), 'fl': flipped('cfb', r['name'], yr, r['team']), 'fx': r['xfv']})
        T, LD, VS = {}, leads('cfb', yr, lst), visits('cfb', yr, lst, d['asof'])
        for t in teams:
            g, rows = pack(by.get(t['team'], []), CFB_G, floor)
            T[t['team']] = {'rk': t['classRk'], 's': t['classXfv'], 'n': t['classN'], **{k: t.get(k, 0) for k in BUCKETS},
                            'avg': t.get('avgXfv'), 'te': t.get('topRk'), 'dp': t.get('depthRk'), 'x': t.get('classXnil'), 'conf': t.get('conf'), 'g': g, 'r': rows,
                            'ld': LD.get(t['team'], []), 'v': VS.get(t['team'], [])}
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
                'sp': 1 if r.get('fsp') else None, 'i': img(r.get('img')), 'fl': flipped('cbb', r['name'], c['year'], r['team']), 'fx': r['fv']})
        T, LD, VS = {}, leads('cbb', c['year'], c['list']), visits('cbb', c['year'], c['list'], d['asof'])
        for t in teams:
            g, rows = pack(by.get(t['team'], []), CBB_G, floor)
            T[t['team']] = {'rk': t['rk'], 's': round(t['ets'], 1), 'n': t['n'], **{k: t.get(k, 0) for k in BUCKETS},
                            'avg': t.get('avgFv'), 'te': t.get('topRk'), 'dp': t.get('depthRk'), 'x': t.get('xnil'), 'conf': t.get('conf'), 'g': g, 'r': rows,
                            'ld': LD.get(t['team'], []), 'v': VS.get(t['team'], [])}
        out['y'][str(c['year'])] = {'of': len(teams), 't': T}
    return out


def check(name, out):
    bad = []
    for yr, Y in out['y'].items():
        for team, t in Y['t'].items():
            if len(t['r']) != t['n']:
                bad.append('%s %s %s: %d commits listed, class rankings say %d' % (name, yr, team, len(t['r']), t['n']))
            if sum(t[k] for k in BUCKETS) != t['n']:
                bad.append('%s %s %s: star buckets add to %d, not %d' % (name, yr, team, sum(t[k] for k in BUCKETS), t['n']))
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
