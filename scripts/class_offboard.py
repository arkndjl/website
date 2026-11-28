#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Every commit of the live classes, the ones the recruit boards do not list included, for the class rankings.

The CFB board lists the recruits ESPN grades; the CBB board the recruits a service ranks. On3's team commit lists
(scripts/on3_commits.mjs, packed by scripts/arkstars_hist.py: scripts/data/arkstars_hist_cfb.json.gz, _cbb.json.gz) name
the rest: walk-ons, FCS and low-major signees, the late adds. Each is graded with the HS ARK stars (the same index and
cuts; 1 star when nobody rates him) and counts in his class's commits and star buckets at the board's floor, FV 20, so
he adds nothing to the class score: his points failed held out (scripts/research/class_unranked_nov28, Nov 28 2026:
CFB 2011-20 draft picks, t -2.05 at his index points, t -2.01 with a separate 0.5-star value for the unrated).

Writes data/class_offboard.json:
  {asof, cfb: {<class>: [[name, pos, ESPN team id, ARK stars, hometown, height in, weight], ...]},
         cbb: {<class>: [[name, pos, ESPN team id, ARK stars, hometown, height in, weight], ...]}}
and drops every recruit a board lists (any school, committed or not: the board's row wins), joined by scripts/names.py.
Read by scripts/cfb_recruit.mjs (class rankings), scripts/cbb_recruit_fit.py (class_ranks) and scripts/class_cards.py.
Rerun after the packs or a board's recruit lists change (arkstars-hist.yml, cfb-recruits.yml, cbb-recruits.yml).

Also writes data/school_slugs.json (On3 school slug -> board team, every FBS, FCS and D-I program, from ESPN's team
lists by team id; the class cards' visits and offers) when it is missing or with --slugs, and with --offers packs
On3's program offer lists (scripts/on3_commits.mjs --offers) into scripts/data/class_offers.json.gz:
  {asof, cfb|cbb: {<class>: {<board team>: [[name, pos, state, On3 status, school he is committed to (On3 slug)], ...]}}}
    python3 scripts/class_offboard.py [--test] [--slugs] [--offers]
"""
import gzip
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as N  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'class_offboard.json')
SLUGS = os.path.join(ROOT, 'data', 'school_slugs.json')
OFFERS = os.path.join(ROOT, 'scripts', 'data', 'class_offers.json.gz')
ESPN = {'cfb': [('football/college-football', 80), ('football/college-football', 81)], 'cbb': [('basketball/mens-college-basketball', 50)]}
# On3 spells these programs another way than ESPN's display name (scripts/on3_commits.mjs ALIAS, scripts/arkstars_hist.py on3_tids)
SLUG_FIX = {'mcneese-cowboys': 'mcneese-state-cowboys', 'nicholls-colonels': 'nicholls-state-colonels', 'ualbany-great-danes': 'albany-great-danes',
            'long-island-university-sharks': 'liu-sharks', 'central-connecticut-blue-devils': 'central-connecticut-state-blue-devils',
            'se-louisiana-lions': 'southeastern-louisiana-lions', 'ut-martin-skyhawks': 'tennessee-martin-skyhawks', 'east-texas-am-lions': 'texas-am-commerce-lions',
            'st-thomas-minnesota-tommies': 'st-thomas-tommies', 'uconn-huskies': 'connecticut-huskies', 'app-state-mountaineers': 'appalachian-state-mountaineers',
            'ul-monroe-warhawks': 'louisiana-monroe-warhawks', 'florida-international-panthers': 'fiu-panthers', 'south-florida-bulls': 'usf-bulls',
            'middle-tennessee-blue-raiders': 'middle-tennessee-state-blue-raiders', 'sam-houston-bearkats': 'sam-houston-state-bearkats',
            'pittsburgh-panthers': 'pitt-panthers', 'delaware-blue-hens': 'delaware-fightin-blue-hens', 'miami-oh-redhawks': 'miami-ohio-redhawks'}


def slugify(s):
    s = N.fold(s).replace('&', 'and')
    s = re.sub(r"['.()]", '', s); s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s.replace('aandm', 'am').replace('aandt', 'at').replace('-and-', '-')


def school_slugs(pull=False):
    """{sport: {On3 slug: board team}}: ESPN's display names slugged as On3 slugs them, joined to the board by team id"""
    if os.path.exists(SLUGS) and not pull: return json.load(open(SLUGS))
    import requests
    out = {}
    for sp, groups in ESPN.items():
        tids = board_tids(sp); m = {}
        for lg, grp in groups:
            for pg in range(1, 6):   # ESPN pages its team lists
                j = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/{lg}/teams?groups={grp}&limit=500&page={pg}', timeout=40).json()
                ts = j['sports'][0]['leagues'][0]['teams']
                for x in ts:
                    t = x['team']; team = tids.get(str(t['id']))
                    if not team: continue
                    s = slugify(t['displayName']); m[s] = team
                    if s in SLUG_FIX: m[SLUG_FIX[s]] = team
                if len(ts) < 50: break
        out[sp] = dict(sorted(m.items()))
    with open(SLUGS, 'w') as f: json.dump(out, f, indent=0, ensure_ascii=False)
    print('school slugs', {k: len(v) for k, v in out.items()})
    return out


def pack_offers():
    """On3's program offer lists (scripts/.cache/on3offers/<sport>/<slug>-<class>.json) by class and board team"""
    import glob
    sl = school_slugs(); old = load('scripts', 'data', 'class_offers.json.gz') if os.path.exists(OFFERS) else {}
    out = {'asof': __import__('datetime').date.today().isoformat()}; miss = Counter()
    for sp, dirn in (('cfb', 'football'), ('cbb', 'basketball')):
        got = {}
        for p in glob.glob(os.path.join(ROOT, 'scripts', '.cache', 'on3offers', dirn, '*-*.json')):
            m = re.match(r'(.+)-(\d{4})\.json$', os.path.basename(p))
            if not m: continue
            team = sl.get(sp, {}).get(m.group(1))
            if not team: miss[sp + ' ' + m.group(1)] += 1; continue
            rows = [[r.get('name'), r.get('pos'), r.get('state'), r.get('status'), r.get('org')] for r in json.load(open(p)) if r.get('name')]
            if rows: got.setdefault(m.group(2), {})[team] = rows
        out[sp] = got or old.get(sp) or {}   # a pull that reached nothing keeps the last one
    with gzip.open(OFFERS, 'wt') as f: json.dump(out, f, separators=(',', ':'), ensure_ascii=False)
    print('offers', {sp: {y: [len(v), sum(len(x) for x in v.values())] for y, v in out[sp].items()} for sp in ('cfb', 'cbb')}, 'unmatched', len(miss), sorted(miss)[:20])


def load(*p):
    f = os.path.join(ROOT, *p)
    return json.load(gzip.open(f, 'rt') if f.endswith('.gz') else open(f, encoding='utf-8'))


def board_tids(sport):
    """ESPN team id -> board team name (the logos carry the id)"""
    b = load('static', 'data', sport + '-all.json'); c = {k: i for i, k in enumerate(b['cols'])}; out = {}
    for r in b['rows']:
        m = re.search(r'/(\d+)\.png', r[c['logo']] or '')
        if m: out.setdefault(m.group(1), r[c['team']])
    return out


def home(r):
    if r.get('home'): return r['home']
    return ', '.join(x for x in (r.get('city'), r.get('state')) if x) or None


def keep(rows, board, tids, sport):
    """the pack's commits a board does not list, one row a recruit"""
    M = N.Matcher(board, name='name', team=None, pos=None)
    out, why, seen = [], Counter(), set()
    for r in rows:
        t = str(r.get('tid') or '')
        if not t or t not in tids: why['no board school'] += 1; continue
        m, _ = M.find(r['name'])
        if m is not None and (not r.get('state') or not m.get('home') or m['home'].endswith(r['state']) or m.get('team') == tids[t]):
            why['on the board'] += 1; continue
        k = (N.key(r['name']), t)
        if k in seen: why['twice'] += 1; continue
        seen.add(k); why['kept'] += 1
        out.append([r['name'], r.get('pos') or None, t, float(r['ark']), home(r), r.get('ht') or None, r.get('wt') or None])
    out.sort(key=lambda x: (x[2], -x[3], x[0]))
    return out, dict(why)


def cfb():
    import arkstars_hist as A
    pack, _ = A.read_pack(); d = A.fitfile(); tids = board_tids('cfb')
    b = load('static', 'data', 'cfb-recruits.json')
    lists = {int(b['next']): b['class'], **{int(f['year']): f['list'] for f in b.get('future') or []}}
    out, how = {}, {}
    for y, lst in lists.items():
        rows = [r for r in pack.get(y, []) if not r.get('dup')]
        A.score(rows, d)
        rows = [r for r in rows if 'ark' in r and r.get('tid') and r.get('tsrc') != 'b']
        out[str(y)], how[str(y)] = keep(rows, lst, tids, 'cfb')
    return out, how


def cbb():
    import arkstars_hist as A
    d = load('scripts', 'data', 'arkstars_hist_cbb.json.gz'); tids = board_tids('cbb'); star = A.cbb_curve()
    b = load('data', 'cbb_recruits.json')
    out, how = {}, {}
    for c in b['classes']:
        y = int(c['year'])
        rows = [dict(zip(d['cols'], a)) for a in d['rows']]
        rows = [{**r, 'ark': float(star(r['rk'])) if r.get('rk') else 1.0} for r in rows if r['y'] == y]
        out[str(y)], how[str(y)] = keep(rows, c['list'], tids, 'cbb')
    return out, how


def main():
    school_slugs(pull='--slugs' in sys.argv)
    if '--offers' in sys.argv: pack_offers()
    res = {'asof': None}
    for sp, fn in (('cfb', cfb), ('cbb', cbb)):
        res[sp], how = fn()
        print(sp, json.dumps(how), {y: Counter(r[3] for r in v).most_common(4) for y, v in res[sp].items()})
    res['asof'] = load('static', 'data', 'cfb-recruits.json')['asof']
    if '--test' in sys.argv:
        bad = [f'{sp} {y}: {r[0]} has no grade' for sp in ('cfb', 'cbb') for y, v in res[sp].items() for r in v if not r[3] or r[3] < 1]
        for x in bad: print('BAD', x)
        sys.exit(1 if bad else 0)
    with open(OUT, 'w') as f: json.dump(res, f, separators=(',', ':'), ensure_ascii=False)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
