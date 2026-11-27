#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ARK stars for every recruit a source names, past classes included, and each college player's high school grade.

    node scripts/on3_commits.mjs football 2008 2027 --fcs   # On3 team commit lists (scripts/.cache/on3commits)
    python3 scripts/arkstars_hist.py --pull                  # merge the sources, grade, write the pack and the join
    python3 scripts/arkstars_hist.py --update                # the weekly job: this season's classes on from fresh pulls, the
                                                             # older classes from the pack plus the new lists' transfers
    python3 scripts/arkstars_hist.py                         # the join only, from the pack (every board run)
    python3 scripts/arkstars_hist.py --test                  # the held-out calibration (data/arkstars_hist_research.json)

The recruit tabs grade the classes still being recruited. This grades the rest with the same index (the NFL hurdle of
scripts/cfb_recruit_retarget.py, the cuts in data/cfb_recruit_retarget.json `stars`), so a transfer or a fifth-year
senior carries the grade he had as a recruit. One row a recruit, merged from

    ESPN's class lists 2006 on (every recruit it names, 3,000 to 18,000 a class, most with no school and no grade)
    On3's team commit lists (every signee of an FBS or FCS class, rated or not, with each service's own grade, and
      the transfers a program took with their high school class and grades)
    the 247 composite as CFBD holds it (scripts/data/cfb_recruits_cfbd.json.gz, 2009-25)
    On3's industry table (scripts/data/cfb_on3_hist.json.gz, cfb_on3_live.json)

joined by name through scripts/names.py with the home state or the signing school. A recruit ESPN did not grade and the
industry table does not hold, but one service graded, reads that grade on the industry scale (`pseudo`, a line fit
on the recruits with both); a recruit nobody graded is scored on his program, position and size alone.

The join (static/data/arkstars-cfb.json) keys each board player to his row: ESPN athlete id, else his name with a
school he signed with or transferred to, else his name with his hometown.
"""
import csv
import glob
import gzip
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_recruit_fit as R        # noqa: E402
import cfb_recruit_retarget as T   # noqa: E402
import names as N                  # noqa: E402

ROOT = R.ROOT
C3 = os.path.join(ROOT, 'scripts', '.cache', 'on3commits', 'football')
AC = os.path.join(ROOT, 'scripts', '.cache', 'arkstars')
PACK = os.path.join(ROOT, 'scripts', 'data', 'arkstars_hist_cfb.json.gz')
JOIN = os.path.join(ROOT, 'static', 'data', 'arkstars-cfb.json')
RES = os.path.join(ROOT, 'data', 'arkstars_hist_research.json')
FIRST, LAST = 2008, 2029
KEEP_LOOSE = 2019        # ESPN rows with no school are kept from this class on (a player still in college can be one)
SVC_ORDER = ('247', 'on3', 'rivals', 'espn', 'c247')


def slugify(s):
    s = N.fold(s).replace('&', 'and')
    s = re.sub(r"['.()]", '', s); s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    s = s.replace('aandm', 'am').replace('aandt', 'at').replace('-and-', '-')
    return s


def espn_teams():
    """ESPN's college football programs: id -> names, and On3's slug for each (display name, slugged)"""
    f = os.path.join(AC, 'espn_teams.json')
    if not os.path.exists(f):
        os.makedirs(AC, exist_ok=True); out = {}
        for pg in range(1, 5):
            j = R.S.get(f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=500&page={pg}', timeout=40).json()
            ts = j['sports'][0]['leagues'][0]['teams']
            for t in ts: t = t['team']; out[t['id']] = {'name': t.get('location') or t['displayName'], 'full': t['displayName'], 'nick': t.get('nickname')}
            if len(ts) < 500: break
        json.dump(out, open(f, 'w'))
    return json.load(open(f))


def on3_tids(et):
    """On3 team slug -> ESPN team id"""
    f = os.path.join(C3, '_teams.json'); meta = json.load(open(f)) if os.path.exists(f) else {}
    by = {slugify(v['full']): k for k, v in et.items()}
    fix = {'mcneese-state-cowboys': 'mcneese-cowboys', 'nicholls-state-colonels': 'nicholls-colonels', 'albany-great-danes': 'ualbany-great-danes',
           'liu-sharks': 'long-island-university-sharks', 'central-connecticut-state-blue-devils': 'central-connecticut-blue-devils',
           'southeastern-louisiana-lions': 'se-louisiana-lions', 'tennessee-martin-skyhawks': 'ut-martin-skyhawks', 'texas-am-commerce-lions': 'east-texas-am-lions',
           'connecticut-huskies': 'uconn-huskies', 'appalachian-state-mountaineers': 'app-state-mountaineers', 'louisiana-monroe-warhawks': 'ul-monroe-warhawks',
           'miami-hurricanes': 'miami-hurricanes', 'miami-oh-redhawks': 'miami-oh-redhawks', 'hawaii-rainbow-warriors': 'hawaii-rainbow-warriors',
           'fiu-panthers': 'florida-international-panthers', 'fiu-golden-panthers': 'florida-international-panthers', 'usf-bulls': 'south-florida-bulls', 'san-jose-state-spartans': 'san-jose-state-spartans',
           'massachusetts-minutemen': 'massachusetts-minutemen', 'southern-miss-golden-eagles': 'southern-miss-golden-eagles', 'ole-miss-rebels': 'ole-miss-rebels',
           'middle-tennessee-state-blue-raiders': 'middle-tennessee-blue-raiders', 'sam-houston-state-bearkats': 'sam-houston-bearkats', 'umass-minutemen': 'massachusetts-minutemen',
           'ucf-knights': 'ucf-knights', 'louisiana-ragin-cajuns': 'louisiana-ragin-cajuns', 'pitt-panthers': 'pittsburgh-panthers', 'nc-state-wolfpack': 'nc-state-wolfpack',
           'kennesaw-state-owls': 'kennesaw-state-owls', 'jacksonville-state-gamecocks': 'jacksonville-state-gamecocks', 'utsa-roadrunners': 'utsa-roadrunners',
           'delaware-fightin-blue-hens': 'delaware-blue-hens', 'missouri-state-bears': 'missouri-state-bears', 'ul-lafayette-ragin-cajuns': 'louisiana-ragin-cajuns'}
    out = {}
    slugs = set(meta) | {re.sub(r'-\d{4}\.json$', '', os.path.basename(p)) for p in glob.glob(os.path.join(C3, '*-*.json'))}
    for s in slugs:
        if (meta.get(s) or {}).get('espn'): out[s] = str(meta[s]['espn']); continue
        t = by.get(s) or by.get(fix.get(s, ''))
        if not t:   # the school's name alone, when one ESPN program has it
            c = [k for k, v in et.items() if slugify(v['name']) and s.startswith(slugify(v['name']) + '-') and N.same_team(v['name'], s.replace('-', ' ')[:len(v['name'])])]
            t = c[0] if len(c) == 1 else None
        if t: out[s] = t
    return out


_PROG = {}
XFER = {}    # class -> ESPN's transfer rows (athlete id, name, new school): a later school of an earlier class's recruit


def programs(y):
    """the programs as class y saw them (retarget's programs_hist: season y - 1), else the latest season on file"""
    for yy in range(y, 2007, -1):
        if yy in _PROG: return _PROG[yy]
        try:
            p = T.programs_hist(yy)
            if p: _PROG[yy] = p; return p
        except (Exception, SystemExit): continue
    return {}


def inches(h):
    if isinstance(h, (int, float)): return float(h) if h else None
    m = re.match(r"(\d)[-'](\d{1,2}(?:\.\d+)?)", h or '')
    return int(m.group(1)) * 12 + float(m.group(2)) if m else None


# ---- the sources, one class at a time ---------------------------------------------------------------------
def on3_lists():
    """On3's team lists by high school class: {class: {on3 key: row}} with the signing school and later schools"""
    et = espn_teams(); tid = on3_tids(et); out = defaultdict(dict); miss = Counter()
    for f in glob.glob(os.path.join(C3, '*-*.json')):
        slug, yr = re.match(r'(.+)-(\d{4})\.json$', os.path.basename(f)).groups(); yr = int(yr)
        t = tid.get(slug)
        if not t: miss[slug] += 1
        for r in json.load(open(f)):
            y = r.get('cls') or 0
            if not (FIRST <= y <= LAST) or not r.get('name'): continue
            o = out[y].setdefault(r['key'], {'on3': r['key'], 'slug': r.get('slug'), 'name': r['name'], 'pos': r.get('pos'), 'ht': inches(r.get('ht')), 'wt': r.get('wt') or None,
                                             'state': r.get('state'), 'home': r.get('home'), 'hsName': r.get('hsName'), 'dob': (r.get('dob') or '')[:10] or None,
                                             'svc': {}, 'sign': None, 'later': []})
            for k, v in (r.get('svc') or {}).items(): o['svc'].setdefault(k, v)
            if r.get('xfer') or yr != y:
                if t: o['later'].append((t, yr))
            elif t:
                rank = {'Enrolled': 3, 'Signed': 2, 'Committed': 1, 'Verbal': 1}.get(r.get('status'), 0)
                if o['sign'] is None or rank > o['sign'][2]: o['sign'] = (t, (r.get('date') or '')[:10] or None, rank)
    if miss: print('On3 teams with no ESPN id:', ', '.join(sorted(miss)), flush=True)
    return out


def espn_class(y):
    """ESPN's class y as scripts/cfb_recruit_fit.py recruit_class reads it, with the hometown, and the transfers ESPN
    lists in a class since 2021 (ungraded, a college in the high school field) marked: they are no recruits of it."""
    ttl = None if y < 2026 else 86400 * 3
    d = R.get(f'{R.CORE}/recruiting/{y}/athletes?limit=1000&page=1', ttl) or {}
    items = list(d.get('items', []))
    for p in range(2, d.get('pageCount', 1) + 1): items += (R.get(f'{R.CORE}/recruiting/{y}/athletes?limit=1000&page={p}', ttl) or {}).get('items', [])
    out = []
    for it in items:
        a = it.get('athlete') or {}; at = {x.get('name'): x.get('value') for x in it.get('attributes', [])}
        sch = [(s['status']['description'], R.rid(s['team']['$ref'])) for s in it.get('schools', []) if s.get('status', {}).get('id') and s.get('team')]
        hs = a.get('highSchool') or {}; ht = a.get('hometown') or {}; gr = float(it.get('grade') or 0)
        out.append({'rid': a.get('id'), 'id': a.get('alternateId'), 'name': a.get('fullName'), 'pos': (a.get('position') or {}).get('abbreviation'),
                    'ht': a.get('height') or None, 'wt': a.get('weight') or None, 'grade': gr, 'rank': at.get('rank'), 'posRank': at.get('positionRank'),
                    'state': ht.get('stateAbbreviation') or ((hs.get('address') or {}).get('stateAbbreviation')), 'city': ht.get('city'),
                    'tid': next((t for st, t in sch if st in ('Signed', 'Enrolled', 'Verbal', 'Committed')), None),
                    'xfer': gr < 60 and R.not_hs(hs.get('name'))})
    return out


def anchor_eq(a, b):
    """(state, {school ids}) of two rows: the same home state, or a school in common"""
    return bool((a[0] and a[0] == b[0]) or (a[1] and b[1] and set(a[1]) & set(b[1])))


def merge_class(y, lists, et):
    """One row a recruit of class y."""
    prog = programs(y); pname = {t: v['team'] for t, v in prog.items()}
    rows, xf = [], []
    for r in espn_class(y):
        if not r.get('name'): continue
        if r['xfer']: xf.append(r); continue
        rows.append({'y': y, 'name': r['name'], 'pos': r['pos'], 'ht': r['ht'], 'wt': r['wt'], 'state': r['state'], 'city': r['city'], 'rid': r['rid'], 'id': r['id'],
                     'grade': r['grade'], 'rank': r['rank'], 'posRank': r['posRank'], 'tid': r['tid'], 'src': 'e', 'svc': {}, 'later': [], 'on3': None, 'commit': None})
    how = Counter()
    M = N.Matcher(rows, name='name', team=lambda r: (r['state'], [r['tid']] if r['tid'] else []), pos=None, team_eq=anchor_eq)
    for o in lists.get(y, {}).values():
        sign = o['sign'][0] if o['sign'] else None
        anc = (o['state'], [sign] if sign else [])
        m, h = M.find(o['name'], team=anc, cross_team='none') if (anc[0] or anc[1]) else (None, None)
        if m is not None and m.get('on3') not in (None, o['on3']): m = None
        if m is None:
            m = {'y': y, 'name': o['name'], 'pos': o['pos'], 'ht': o['ht'], 'wt': o['wt'], 'state': o['state'], 'rid': None, 'id': None, 'grade': 0.0, 'rank': None,
                 'posRank': None, 'tid': None, 'src': '', 'svc': {}, 'later': []}
            rows.append(m); how['on3 new'] += 1
        else: how['on3 ' + h] += 1
        m['src'] += 'o'; m['on3'] = o['on3']; m['slug'] = o['slug']; m['svc'] = o['svc']; m['later'] = o['later']; m['home'] = o['home']; m['hsName'] = o['hsName']; m['dob'] = o['dob']
        if not m['tid'] and sign: m['tid'] = sign; m['tsrc'] = 'o'
        if o['sign'] and o['sign'][1]: m['commit'] = o['sign'][1]
        for k in ('pos', 'ht', 'wt', 'state'):
            if not m.get(k): m[k] = o[k]
    # the 247 composite as CFBD holds it: name + signing school
    tk = {N.team_key(v['name']): t for t, v in et.items() if t in prog}
    M2 = N.Matcher(rows, name='name', team=lambda r: pname.get(r['tid']) or (et.get(r['tid']) or {}).get('name'), pos=None)
    byk = defaultdict(list)
    for r in rows: byk[N.key(r['name'])].append(r)
    cf = R.CFBD_REC.get(str(y), []); nk = Counter(N.key(c[0]) for c in cf)
    for c in cf:
        nm, comp, _, crk, sch, ht, wt = (list(c) + [None] * 7)[:7]
        if not comp or not nm: continue
        m, h = M2.find(nm, team=sch, cross_team='none') if sch else (None, None)
        if m is None:   # no school on one side: his name alone when it is one recruit's in both lists
            c2 = byk.get(N.key(nm), [])
            if len(c2) == 1 and nk[N.key(nm)] == 1: m, h = c2[0], 'name'
        if m is None and sch:   # a first name the two sources do not share (Tyshun / Deebo Samuel): the surname at the same school, one recruit on each side, the same build
            ln = N.parts(nm)[1]
            c2 = [r for r in rows if 'c' not in r['src'] and r['tid'] and N.parts(r['name'])[1] == ln and N.same_team(sch, pname.get(r['tid']) or '')]
            if len(c2) == 1 and sum(1 for x in cf if x[4] == sch and N.parts(x[0])[1] == ln) == 1 and ht and wt and c2[0]['ht'] and c2[0]['wt'] \
                    and abs(c2[0]['ht'] - ht) <= 2 and abs(c2[0]['wt'] - wt) <= 25: m, h = c2[0], 'surname+team'
        if m is None:
            t = tk.get(N.team_key(sch)) if sch else None
            m = {'y': y, 'name': nm, 'pos': None, 'ht': ht or None, 'wt': wt or None, 'state': None, 'rid': None, 'id': None, 'grade': 0.0, 'rank': None, 'posRank': None,
                 'tid': t, 'src': '', 'svc': {}, 'later': [], 'on3': None}
            rows.append(m); byk[N.key(nm)].append(m); how['cfbd new'] += 1
        else: how['cfbd ' + h] += 1
        if 'c' in m['src']: continue
        m['src'] += 'c'; m['c247'] = comp; m['cRank'] = crk
        if not m['tid'] and sch and tk.get(N.team_key(sch)): m['tid'] = tk[N.team_key(sch)]; m['tsrc'] = 'c'
    # On3's industry table (name + home state, else a name one recruit has), then the team lists' copy of it
    for r in rows: r.setdefault('commit', None); r['year'] = y
    XFER[y] = [(r['id'], r['name'], r['tid']) for r in xf if r['tid']]
    keep = {id(r): r.get('commit') for r in rows}
    R.attach_on3(rows)
    for r in rows:
        if not r.get('commit'): r['commit'] = keep[id(r)]
        sv = r['svc']
        if not r.get('ind') and sv.get('industry'): r['ind'] = round(sv['industry'][0], 2); r['indRank'] = sv['industry'][2]; r['isrc'] = 'list'
        if r['grade'] < 60 and sv.get('espn') and sv['espn'][0] >= 60: r['grade'] = float(sv['espn'][0]); r['gsrc'] = 'list'
    # the service gaps of a row whose industry rating came from a team list: each service's z less the industry's, on
    # the class's listed recruits (scripts/cfb_on3_pack.py's form)
    st = {}
    for s in ('industry', '247', 'espn'):
        v = [r['svc'][s][0] for r in rows if s in r['svc'] and 'industry' in r['svc']]
        st[s] = (float(np.mean(v)), float(np.std(v)) or 1.0) if len(v) >= 20 else None
    for r in rows:
        if r.get('isrc') == 'list' and st['industry']:
            zc = (r['ind'] - st['industry'][0]) / st['industry'][1]
            for s, k in (('247', 'g247'), ('espn', 'gEspn')):
                if s in r['svc'] and st[s]: r[k] = round((r['svc'][s][0] - st[s][0]) / st[s][1] - zc, 3)
    for r in rows:
        place(r, prog, et)
        r['g'] = R.group(r['pos'], r['ht'], r['wt']) if r['pos'] else 'ATH'
        r['year'] = y; r['k'] = 3
    return rows, how


def place(r, prog, et):
    """The program he signed with as his class saw it. A recruit no source gives a signing school, whom a program
    later lists as a transfer, is read at the lowest level the index knows (his first school was one no list covers:
    a lower-division or junior college start, or a walk-on year), marked lv '?'."""
    p = prog.get(r['tid']) if r['tid'] else None
    r['level'] = p['level'] if p else None; r['eloZ'] = round(p['eloZ'], 3) if p else 0.0
    r['team'] = (p or {}).get('team') or (et.get(r['tid']) or {}).get('name')
    r.pop('lv', None)
    if not r['level'] and not r['tid'] and r.get('later'): r['level'] = 'FCS'; r['lv'] = '?'


def cross_class(allrows, et):
    """A recruit the sources put in different classes (a prep year, a reclass, a junior college listing): the row
    ESPN does not have, matched to an ESPN row one or two classes away by name with the home state or a school,
    is folded into it."""
    n = 0
    for y in sorted(allrows):
        loose = [r for r in allrows[y] if 'e' not in r['src']]
        if not loose: continue
        for dy in (-1, 1, -2, 2):
            tgt = [r for r in allrows.get(y + dy, []) if 'e' in r['src'] and not r.get('gone')]
            if not tgt: continue
            M = N.Matcher(tgt, name='name', team=lambda r: (r['state'], [r['tid']] + [t for t, _ in r['later']] if r['tid'] else [t for t, _ in r['later']]), pos=None, team_eq=anchor_eq)
            for r in loose:
                if r.get('gone'): continue
                anc = (r['state'], ([r['tid']] if r['tid'] else []) + [t for t, _ in r['later']])
                if not (anc[0] or anc[1]): continue
                m, h = M.find(r['name'], team=anc, cross_team='none')
                if m is None or h not in ('name+team',): continue
                if r.get('on3') and m.get('on3') and r['on3'] != m['on3']: continue
                if 'o' in r['src'] and 'o' not in m['src']:
                    m['src'] += 'o'; m['on3'] = r['on3']; m['slug'] = r.get('slug'); m['svc'] = r['svc']; m['later'] = r['later']; m['home'] = r.get('home'); m['hsName'] = r.get('hsName'); m['dob'] = r.get('dob')
                    if not m.get('ind') and r.get('ind'): m['ind'], m['indRank'], m['isrc'] = r['ind'], r.get('indRank'), r.get('isrc')
                if 'c' in r['src'] and 'c' not in m['src']: m['src'] += 'c'; m['c247'] = r.get('c247'); m['cRank'] = r.get('cRank')
                if not m['tid'] and r['tid']: m['tid'] = r['tid']; m['tsrc'] = r.get('tsrc') or 'x'; place(m, programs(m['y']), et)
                r['gone'] = True; n += 1
    for y in allrows: allrows[y] = [r for r in allrows[y] if not r.get('gone')]
    return n


# ---- a lone service's grade on the industry scale ---------------------------------------------------------
def svc_val(r, s):
    if s == 'c247': return r['c247'] * 100 if r.get('c247') else None
    if s == 'espn': return r['grade'] if r['grade'] >= 60 else None
    return r['svc'][s][0] if s in r['svc'] else None


def pseudo_fit(rows):
    """industry rating = a + b x the service's grade, on recruits with both (signed classes)"""
    out = {}
    for s in SVC_ORDER:
        p = [(svc_val(r, s), r['ind']) for r in rows if r.get('ind') and r.get('isrc') != 'pseudo' and svc_val(r, s)]
        if len(p) < 200: continue
        x = np.array([a for a, _ in p]); yv = np.array([b for _, b in p]); b = np.cov(x, yv)[0, 1] / x.var(ddof=1)
        out[s] = [round(float(yv.mean() - b * x.mean()), 4), round(float(b), 5), len(p), round(float(np.corrcoef(x, yv)[0, 1]), 3)]
    return out


def pseudo_apply(rows, pm):
    """A recruit with no industry rating reads the mean of his services' grades on its scale."""
    for r in rows:
        if r.get('ind'): continue
        v = [pm[s][0] + pm[s][1] * svc_val(r, s) for s in SVC_ORDER if s in pm and svc_val(r, s)]
        if v: r['ind'] = round(min(99.0, max(60.0, float(np.mean(v)))), 2); r['isrc'] = 'pseudo'; r['indRank'] = None


# ---- the grade --------------------------------------------------------------------------------------------
def fitfile():
    d = json.load(open(T.OUT)); R.TM_MEAN = d['index']['tm']
    d['thin'] = (json.load(open(RES)).get('thin') or {}).get('coef') if os.path.exists(RES) else None
    return d


def listed(r):
    """in ESPN's signee list (the recruits the index was fit on): an ESPN row with ESPN's own school"""
    return 'e' in r['src'] and bool(r['tid']) and not r.get('tsrc')


def thin(r):
    """The recruits the index never saw: not in ESPN's signee list and with no ESPN grade. 'fbs' / 'fcs' by the
    program a source says he signed with; None for the rest (a first school nobody lists reads as the index has it)."""
    if listed(r) or r['grade'] >= 60 or r.get('lv') == '?': return None
    return 'fcs' if r['level'] == 'FCS' else 'fbs'


def score(rows, d):
    """index score, P(drafted) and ARK stars (1-5 in halves, 6 = 5-star+) for the rows with a program and a group"""
    ok = [r for r in rows if r['level'] and r['g']]
    if not ok: return
    ix, sz, S = d['index'], d['sizeNorms'], d['stars']
    for r in ok: r.pop('_bc', None)
    s = T.index_score(ix, ok, sz)
    X, _ = R.design(ok, ix['on']['blocks'], sz); p = R.sig(ix['on']['b0'] + X @ np.array(ix['on']['coef']))
    e = S.get('elite')
    th = d.get('thin') or {}
    for i, r in enumerate(ok):   # the thin-coverage offset on P(drafted); the value if drafted stays the index's
        a = th.get(thin(r) or '')
        if a:
            q = float(R.sig(math.log(p[i] / (1 - p[i])) + a)); s[i] = R.FLOOR + (s[i] - R.FLOOR) * q / p[i]; p[i] = q
    for r, x, pp in zip(ok, s, p):
        t = 1 + sum(c <= x for c in S['cuts']); h = S['half'][t - 1] if t <= 4 else None
        st = t + 0.5 if h is not None and x >= h else t
        if t == 5 and e:
            ir = r.get('indRank') or 0; lir = math.log(400) - math.log(ir) if 0 < ir <= 400 else 0.0
            if R.sig(e['b0'] + e['coef'][0] * x + e['coef'][1] * lir + e['coef'][2] * max(0.0, ((r.get('ind') or 0) - 95) / 5)) >= e['line']: st = 6
        r['x'] = round(float(x), 3); r['p'] = round(float(pp), 4); r['ark'] = st
        r.pop('_bc', None)


def fold_lists(y, rows, lists, prog, et):
    """A packed class and the team lists pulled since: a transfer a program now lists adds a later school to his row
    (On3 key, else his name with the home state or a school), and one no row holds becomes a row."""
    bykey = {r['on3']: r for r in rows if r.get('on3')}; n = Counter()
    M = N.Matcher(rows, name='name', team=lambda r: (r['state'], [t for t in [r['tid']] + [t for t, _ in r['later']] if t]), pos=None, team_eq=anchor_eq)
    for o in lists.get(y, {}).values():
        sch = ([o['sign'][0]] if o['sign'] else []) + [t for t, _ in o['later']]
        m = bykey.get(o['on3'])
        if m is None and (o['state'] or sch):
            m, _ = M.find(o['name'], team=(o['state'], sch), cross_team='none')
            if m is not None and m.get('on3'): m = None
        if m is None:
            m = {'y': y, 'year': y, 'k': 3, 'name': o['name'], 'pos': o['pos'], 'ht': o['ht'], 'wt': o['wt'], 'state': o['state'], 'city': None, 'rid': None, 'id': None, 'grade': 0.0,
                 'rank': None, 'posRank': None, 'tid': o['sign'][0] if o['sign'] else None, 'tsrc': 'o' if o['sign'] else None, 'src': 'o', 'svc': o['svc'], 'later': [], 'commit': None}
            sv = o['svc']
            if sv.get('industry'): m['ind'] = round(sv['industry'][0], 2); m['indRank'] = sv['industry'][2]; m['isrc'] = 'list'
            if sv.get('espn') and sv['espn'][0] >= 60: m['grade'] = float(sv['espn'][0])
            m['g'] = R.group(m['pos'], m['ht'], m['wt']) if m['pos'] else 'ATH'
            rows.append(m); n['new'] += 1
        if 'o' not in m['src']: m['src'] += 'o'
        m['on3'] = o['on3']; m['home'] = m.get('home') or o['home']; m['dob'] = m.get('dob') or o['dob']
        for x in o['later']:
            if tuple(x) not in [tuple(z) for z in m['later']]: m['later'].append(tuple(x)); n['later'] += 1
        place(m, prog, et)
    return n


def build(years=range(FIRST, LAST + 1), pseudo=True, verbose=True, base=None, prog=None):
    """years: the classes merged from the sources. base: classes read from the pack (read_pack), kept as they are but
    for the team lists in the cache, which are folded in (--update: the cache then holds the new lists only)."""
    et = espn_teams(); lists = on3_lists(); d = fitfile(); allrows = {}
    for y, rows in (base or {}).items():
        if y in years: continue
        n = fold_lists(y, rows, lists, {t: {'level': v[0], 'eloZ': v[1], 'team': v[2]} for t, v in (prog or {}).get(str(y), {}).items()}, et); allrows[y] = rows
        if verbose and n: print(y, 'packed', len(rows), dict(n), flush=True)
    for y in years:
        rows, how = merge_class(y, lists, et); allrows[y] = rows
        if verbose: print(y, len(rows), dict(how), flush=True)
    # ESPN's transfer rows: the new school is a later school of the recruit with that athlete id
    byid = {str(r['id']): r for rows in allrows.values() for r in rows if r['id']}
    for y in allrows:
        for aid, _, t in XFER.get(y, []):
            r = byid.get(str(aid)) if aid else None
            if r is not None and t != r['tid'] and (t, y) not in [tuple(x) for x in r['later']]: r['later'].append((t, y))
    # ESPN's transfer listings that kept a high school (not marked above): an ESPN-only row at a school an earlier
    # class's recruit of that name and state later went to is that recruit's transfer, not a second recruit
    lat = defaultdict(list)
    for y in allrows:
        for r in allrows[y]:
            for t, _ in r['later']: lat[(N.key(r['name']), t)].append(r)
    nt = 0
    for y in allrows:
        for r in allrows[y]:
            if r['src'] == 'e' and r['tid'] and any(o is not r and 0 < y - o['y'] <= 7 and (not o['state'] or not r['state'] or o['state'] == r['state']) for o in lat.get((N.key(r['name']), r['tid']), [])):
                r['gone'] = True; nt += 1
        allrows[y] = [r for r in allrows[y] if not r.get('gone')]
    if verbose: print('ESPN transfer listings dropped', nt, flush=True)
    nx = cross_class(allrows, et)
    if verbose: print('folded across classes', nx, flush=True)
    pm = pseudo_fit([r for y, rows in allrows.items() if y <= 2026 for r in rows])
    if verbose: print('pseudo industry', pm, flush=True)
    for y, rows in allrows.items():
        if pseudo: pseudo_apply(rows, pm)
        score(rows, d)
    # a recruit listed in two classes (a prep year, a reclass) keeps his earliest graded listing. Two classes apart at
    # most: ESPN gives namesakes years apart the same athlete id.
    seen = {}
    for y in sorted(allrows):
        for r in allrows[y]:
            for k in (('e', r['id']) if r['id'] else None, ('o', r['on3']) if r.get('on3') else None):
                if k is None: continue
                if k in seen and seen[k] is not r and y - seen[k]['y'] <= 2: r['dup'] = True
                elif r.get('ark') and (k not in seen or y - seen[k]['y'] > 2): seen[k] = r
    return allrows, pm


# ---- held out: do the grades of the added and the low-rated recruits calibrate? -------------------------------
def picks():
    """NFL draft picks 2014 on with ESPN ids (nflverse)"""
    pe = {x['gsis_id']: x['espn_id'] for x in csv.DictReader(open(os.path.join(T.SP, 'players.csv'))) if x['gsis_id']}
    return [{'name': r['pfr_player_name'], 'team': r['college'], 'season': int(r['season']), 'espn': pe.get(r['gsis_id']) or None, 'pick': int(r['pick'])}
            for r in csv.DictReader(open(os.path.join(T.SP, 'draft_picks.csv'))) if int(r['season']) >= 2014 and int(r['pick'] or 0) > 0]


def label(allrows, et):
    """drafted (and the pick) for every graded row: ESPN id, else the name with the signing school or a later one, in
    the drafts three to six years after the class"""
    pk = picks(); last = max(p['season'] for p in pk)
    M = N.Matcher(pk, name='name', team='team', pos=None, cls='season', id='espn')
    ids = {str(r['id']) for rows in allrows.values() for r in rows if r['id']}
    M2 = N.Matcher([{**p, 'espn': None} for p in pk if str(p['espn']) not in ids], name='name', team='team', pos=None, cls='season', id='espn')
    for y, rows in allrows.items():
        win = lambda s, y=y: y + 3 <= s <= y + 6
        for r in rows:
            if 'ark' not in r: continue
            m = None
            for t in [r['team']] + [(et.get(t) or {}).get('name') for t, _ in r.get('later') or []]:
                if not t: continue
                m, h = M.find(r['name'], team=t, id=r['id'], cls=win, cross_team='none')
                if m is None: m, h = M2.find(r['name'], team=t, cls=win, cross_team='none')
                if m is not None and not win(m['season']): m = None
                if m is not None: break
            r['drafted'] = m is not None; r['pick'] = m['pick'] if m else None
    return last


def table(rows, by=lambda r: r['ark']):
    out = []
    for k in sorted({by(r) for r in rows}, key=lambda x: (str(type(x)), x)):
        g = [r for r in rows if by(r) == k]; n = len(g); d = sum(r['drafted'] for r in g); p = float(np.mean([r['p'] for r in g]))
        se = math.sqrt(max(p * (1 - p), 1e-9) / n)
        out.append({'k': k if isinstance(k, str) else float(k), 'n': n, 'drafted': round(d / n, 4), 'expected': round(p, 4), 'z': round((d / n - p) / se, 2)})
    return out


def offsets(tr, groups):
    """logit offsets on the index's P(drafted), one a group (ridge 1): the added recruits of the index's own classes"""
    y = np.array([r['drafted'] for r in tr], float); off = np.log(np.array([r['p0'] for r in tr]) / (1 - np.array([r['p0'] for r in tr])))
    X = np.array([[float(thin(r) == g) for g in groups] for r in tr]); b = np.zeros(len(groups))
    for _ in range(80):
        p = R.sig(off + X @ b); st = np.linalg.solve(X.T @ (X * (p * (1 - p))[:, None]) + np.eye(len(groups)), X.T @ (y - p) - b); b += st
        if np.abs(st).max() < 1e-9: break
    return {g: round(float(v), 4) for g, v in zip(groups, b)}


def paired(g, rows):
    """mean gain in log loss a recruit, t over recruits and clustered by signing school"""
    u = defaultdict(float)
    for v, r in zip(g - g.mean(), rows): u[r['tid'] or r['name']] += v
    return {'gain': round(float(g.mean()), 5), 't': round(float(g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))), 2),
            'tSchool': round(float(g.mean() / (math.sqrt(sum(v * v for v in u.values())) / len(g) * math.sqrt(len(u) / (len(u) - 1)))), 2)}


def test():
    """What the added recruits became, against what their grade says. The index was fit on ESPN's signee lists of
    the 2011-19 classes, so every other row is one it never saw.
    thin   the offset for recruits outside ESPN's signee list with no ESPN grade (mostly walk-ons and one-service
           signees), fit on those rows of 2011-19, scored forward on 2020-21: log loss, t by recruit and by school
    tiers  drafted against expected by star tier: the index's own rows (in sample, for reference), the added rows of
           2011-19, the 2020-21 classes (after the index; drafts through the last on file), 2022 (two drafts so far)
    lone   a lone service's grade read on the industry scale against leaving that recruit unrated"""
    et = espn_teams(); res = {}
    if os.path.exists(RES): os.replace(RES, RES + '.prev')   # score with no offset first
    allrows, pm = build(range(2011, 2023), verbose=False, pseudo=False)
    last = label(allrows, et)
    flat = [r for y in allrows for r in allrows[y] if 'ark' in r and not r.get('dup')]
    for r in flat: r['p0'] = r['p']
    ll = lambda p, d: -(d * np.log(np.clip(p, 1e-6, 1)) + (1 - d) * np.log(np.clip(1 - p, 1e-6, 1)))
    new = lambda r: not listed(r)
    tr = [r for r in flat if r['y'] <= 2019 and new(r)]; te = [r for r in flat if r['y'] in (2020, 2021) and new(r)]
    d = np.array([r['drafted'] for r in te], float); p0 = np.array([r['p0'] for r in te])
    res['draftsThrough'] = last; res['thin'] = {'fitOn': [2011, 2019], 'n': len(tr), 'forward': [2020, 2021], 'nForward': len(te), 'tests': {}}
    for groups in (['fbs'], ['fbs', 'fcs']):
        b = offsets(tr, groups); p1 = R.sig(np.log(p0 / (1 - p0)) + np.array([b.get(thin(r) or '', 0.0) for r in te]))
        res['thin']['tests']['+'.join(groups)] = {'coef': b, 'll': [round(float(ll(p0, d).mean()), 5), round(float(ll(p1, d).mean()), 5)], **paired(ll(p0, d) - ll(p1, d), te),
                                                  'groups': {g: {'n': int(sum(thin(r) == g for r in te)), 'drafted': round(float(np.mean([r['drafted'] for r in te if thin(r) == g])), 4),
                                                                 'before': round(float(np.mean([q for q, r in zip(p0, te) if thin(r) == g])), 4), 'after': round(float(np.mean([q for q, r in zip(p1, te) if thin(r) == g])), 4)} for g in groups}}
    # the offsets that pass forward (t >= 2 both ways, more groups only when they add) are fit once more on every signed
    # class with a draft window and written for the grader
    ok = [k for k, v in res['thin']['tests'].items() if v['t'] >= 2 and v['tSchool'] >= 2]
    pick = max(ok, key=lambda k: res['thin']['tests'][k]['gain']) if ok else None
    res['thin']['pick'] = pick
    res['thin']['coef'] = offsets([r for r in flat if r['y'] <= 2021 and new(r)], pick.split('+')) if pick else {}
    json.dump(res, open(RES, 'w'), indent=1)
    dd = fitfile()
    for y in allrows: score(allrows[y], dd)
    tier = lambda r: min(float(r['ark']), 3.0)   # 3 = three stars and up
    A_fit = [r for r in flat if r['y'] <= 2019 and listed(r)]; A_new = [r for r in flat if r['y'] <= 2019 and new(r)]
    B = [r for r in flat if r['y'] in (2020, 2021)]; B22 = [r for r in flat if r['y'] == 2022]
    res['tiers'] = {'fit': {'n': len(A_fit), 'tiers': table(A_fit, tier)},
                    'added': {'n': len(A_new), 'tiers': table(A_new, tier), 'level': table(A_new, lambda r: r['level'] + (r.get('lv') or ''))},
                    'forward': {'n': len(B), 'tiers': table(B, tier), 'added': table([r for r in B if new(r)], tier), 'level': table(B, lambda r: r['level'] + (r.get('lv') or '')),
                                'low': table([r for r in B if r['ark'] < 3], lambda r: f"{r['level']}{r.get('lv') or ''} {min(float(r['ark']), 2.0):g}")},
                    'c2022': {'n': len(B22), 'tiers': table(B22, tier)}}
    res['counts'] = {str(y): {'graded': sum(1 for r in allrows[y] if 'ark' in r and not r.get('dup')), 'listed': sum(1 for r in allrows[y] if 'ark' in r and listed(r))} for y in allrows}
    # lone: the same rows with the lone service's grade read as an industry rating
    pm = pseudo_fit([r for r in flat])
    ps = [r for r in flat if not r.get('ind') and r['y'] <= 2021 and any(s in pm and svc_val(r, s) for s in SVC_ORDER)]
    d = np.array([r['drafted'] for r in ps], float); p0 = np.array([r['p'] for r in ps]); keep = [(r['x'], r['p'], r['ark']) for r in ps]
    pseudo_apply(ps, pm); score(ps, dd); p1 = np.array([r['p'] for r in ps])
    res['lone'] = {'map': pm, 'n': len(ps), 'drafted': round(float(d.mean()), 4), 'expected': [round(float(p0.mean()), 4), round(float(p1.mean()), 4)],
                   'll': [round(float(ll(p0, d).mean()), 5), round(float(ll(p1, d).mean()), 5)], **paired(ll(p0, d) - ll(p1, d), ps),
                   'auc': [round(float(R.auc(p0, d)), 4), round(float(R.auc(p1, d)), 4)], 'with': table(ps, tier)}
    for r, (x, p, a) in zip(ps, keep): r['x'], r['p'], r['ark'] = x, p, a; r['ind'] = None; r.pop('isrc', None)
    res['lone']['without'] = table(ps, tier)
    json.dump(res, open(RES, 'w'), indent=1)
    if os.path.exists(RES + '.prev'): os.remove(RES + '.prev')
    return res, allrows


# ---- the pack: every graded recruit (and, for the classes still in college, the rows with no school) ----------
COLS = ['name', 'pos', 'ht', 'wt', 'state', 'city', 'home', 'id', 'on3', 'grade', 'rank', 'posRank', 'tid', 'tsrc', 'later', 'ind', 'indRank', 'isrc', 'g247', 'gEspn',
        'commit', 'c247', 'src', 'svc3', 'dob']


def write_pack(allrows, prog=None, rebuilt=None):
    out = {'asof': __import__('datetime').date.today().isoformat(), 'cols': COLS, 'prog': {}, 'classes': {}}
    for y, rows in sorted(allrows.items()):
        keep = [r for r in rows if not r.get('dup') and ('ark' in r or (y >= KEEP_LOOSE and r['state']))]
        for r in keep: r['svc3'] = [(r['svc'].get(k) or [None])[0] for k in ('247', 'on3', 'rivals')] if r.get('svc') else r.get('svc3')
        out['classes'][str(y)] = [[r.get(c) for c in COLS] for r in keep]
        out['prog'][str(y)] = prog[str(y)] if prog and str(y) in prog and (rebuilt is None or y not in rebuilt) else {t: [v['level'], round(v['eloZ'], 3), v['team']] for t, v in programs(y).items()}
    with gzip.open(PACK, 'wt') as f: json.dump(out, f, separators=(',', ':'))
    return {y: len(v) for y, v in out['classes'].items()}


def read_pack():
    """the pack as rows ready to grade: {class: [row]} and the programs by class"""
    d = json.load(gzip.open(PACK, 'rt')); out = {}
    for y, rows in d['classes'].items():
        y = int(y); prog = d['prog'][str(y)]; out[y] = []
        for a in rows:
            r = dict(zip(d['cols'], a)); r['y'] = r['year'] = y; r['k'] = 3; r['later'] = [tuple(x) for x in r['later'] or []]; r['svc'] = {}
            p = prog.get(r['tid']) if r['tid'] else None
            r['level'] = p[0] if p else None; r['eloZ'] = p[1] if p else 0.0; r['team'] = p[2] if p else None
            if not r['level'] and not r['tid'] and r['later']: r['level'] = 'FCS'; r['lv'] = '?'
            r['g'] = R.group(r['pos'], r['ht'], r['wt']) if r['pos'] else 'ATH'
            out[y].append(r)
    return out, d


# ---- the join: each college player's row --------------------------------------------------------------------
CLS_BACK = {'Fr': (0, 2), 'So': (1, 3), 'Jr': (2, 5), 'Sr': (3, 7), 'Gr': (4, 8)}   # seasons since his class, by the board's class label


def hometowns(tids, pull=False):
    """ESPN rosters' birthplaces by athlete id (scripts/data/cfb_hometowns.json.gz; refreshed by --pull)"""
    f = os.path.join(ROOT, 'scripts', 'data', 'cfb_hometowns.json.gz')
    if pull:
        from concurrent.futures import ThreadPoolExecutor
        def one(t):
            try: j = R.S.get(f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{t}/roster', timeout=40).json()
            except Exception: return []
            return [(a.get('id'), (a.get('birthPlace') or {}).get('city'), (a.get('birthPlace') or {}).get('state')) for g in j.get('athletes', []) for a in g.get('items', [])]
        old = json.load(gzip.open(f, 'rt')) if os.path.exists(f) else {}
        with ThreadPoolExecutor(8) as ex:
            for rows in ex.map(one, tids):
                for i, c, st in rows:
                    if i and (c or st): old[str(i)] = [c, st]
        with gzip.open(f, 'wt') as h: json.dump(old, h, separators=(',', ':'))
    return json.load(gzip.open(f, 'rt')) if os.path.exists(f) else {}


def join(pull=False):
    d = fitfile(); pack, meta = read_pack()
    for y in pack: score(pack[y], d)
    b = json.load(open(R.ALL)); c = {k: i for i, k in enumerate(b['cols'])}; season = int(b['asof'][:4]) - (1 if b['asof'][5:7] < '03' else 0)
    tid_of = lambda r: (re.search(r'/(\d+)\.png', r[c['logo']] or '') or [None, None])[1]
    home = hometowns(sorted({tid_of(r) for r in b['rows']} - {None}), pull)
    lo, hi = season + 1 - 9, season + 1
    pool = [r for y in pack if lo <= y <= hi for r in pack[y]]
    byid = defaultdict(list)
    for r in pool:
        if r['id']: byid[str(r['id'])].append(r)
    stc = lambda r: ((r.get('state') or '').upper(), N.fold((r.get('city') or (r.get('home') or '').split(',')[0]) or '').strip())
    M = N.Matcher(pool, name='name', team=lambda r: (stc(r), [t for t in [r['tid']] + [t for t, _ in r['later']] if t]), pos=None, cls='y',
                  team_eq=lambda a, b: bool(set(a[1]) & set(b[1])) or bool(a[0][0] and a[0][1] and a[0] == b[0]))
    nkey = Counter(N.key(r['name']) for r in pool); bkey = Counter(N.key(r[c['name']]) for r in b['rows'])
    by_key = defaultdict(list)
    for r in pool: by_key[N.key(r['name'])].append(r)
    out, how, used = [], Counter(), {}
    for r in b['rows']:
        nm, t = r[c['name']], tid_of(r); eid = (re.search(r'/id/(\d+)', r[c['espnl']] or '') or [None, None])[1]
        back = CLS_BACK.get((r[c['cls']] or '').replace('RS-', '')[:2]); fit = (lambda y, back=back: season - back[1] <= y <= season + 1 - back[0]) if back else (lambda y: True)
        ci = [x for x in byid.get(eid or '', []) if fit(x['y']) and N.strength(nm, x['name']) >= 1]
        m, h = (min(ci, key=lambda x: x['y']), 'id') if ci else (None, None)
        if m is None:
            hm = home.get(eid or '') or [None, None]
            m, h = M.find(nm, team=((str(hm[1] or '').upper(), N.fold(hm[0] or '').strip()), [t] if t else []), cls=fit, cross_team='none')
            if m is not None:
                h = 'school' if t and t in [m['tid']] + [x for x, _ in m['later']] else 'hometown'
            elif hm[1]:   # his home state and a name no other recruit or player has, in a class that fits and at his position
                k = N.key(nm); c2 = [x for x in by_key.get(k, []) if fit(x['y'])]
                if len(c2) == 1 and nkey[k] == 1 and bkey[k] == 1 and (c2[0].get('state') or '').upper() == str(hm[1]).upper() \
                        and (not c2[0]['pos'] or N.pos_fits(r[c['pos']], c2[0]['pos'])): m, h = c2[0], 'state'
        if m is None:
            # nobody listed him: below every listed recruit, so the floor tier (of the draft picks of 2023-26 about 15 a
            # year have no recruit row, against some 3,000 unlisted players a class). Specialists carry no grade.
            if r[c['pos']] in ('K', 'P', 'LS'): how['specialist ' + r[c['div']]] += 1; continue
            how['unlisted ' + r[c['div']]] += 1; out.append([eid, nm, r[c['team']], 1.0, None, 'unlisted', None, 2]); continue
        if 'ark' not in m and not m['level'] and t:   # a row no source gives a school: read at the program he is at
            p = meta['prog'][str(m['y'])].get(t) or next((meta['prog'][str(yy)][t] for yy in range(m['y'], 2007, -1) if t in meta['prog'].get(str(yy), {})), None)
            if p and m['g']: m['level'], m['eloZ'], m['tid'], m['tsrc'] = p[0], p[1], t, 'b'; score([m], d)
        if 'ark' not in m: how['ungraded ' + r[c['div']]] += 1; continue
        if id(m) in used and used[id(m)] != eid: how['taken'] += 1; continue
        used[id(m)] = eid; how[h + ' ' + r[c['div']]] += 1
        out.append([eid, nm, r[c['team']], float(m['ark']), m['y'], h, round(m['x'], 2), 1 if thin(m) or m.get('lv') else 0])
    n = len(b['rows']); cover = {dv: round(sum(1 for o in out if True and o) / n, 3) for dv in ()}
    by_div = Counter(r[c['div']] for r in b['rows']); got = Counter()
    team_div = {r[c['team']]: r[c['div']] for r in b['rows']}
    for o in out: got[team_div[o[2]]] += 1
    res = {'asof': b['asof'], 'packed': meta['asof'], 'cols': ['espn', 'name', 'team', 'ark', 'class', 'how', 'score', 'thin'],
           'cover': {dv: [got[dv], by_div[dv]] for dv in sorted(by_div)}, 'how': dict(sorted(how.items())), 'rows': out}
    json.dump(res, open(JOIN, 'w'), separators=(',', ':'))
    # the pages' lookup (layouts/partials/hsark.html): "Name|Team" -> stars
    hs = os.path.join(ROOT, 'data', 'arkstars_hs.json'); cur = json.load(open(hs)) if os.path.exists(hs) else {}
    cur['cfb'] = {'asof': b['asof'], 'cover': res['cover'], 'by': {f'{o[1]}|{o[2]}': o[3] for o in out}}
    json.dump(cur, open(hs, 'w'), separators=(',', ':'))
    print('join', res['cover'], res['how'])
    return res


# ---- college basketball --------------------------------------------------------------------------------------
# The basketball recruit grade is the consensus rank alone (scripts/cbb_recruit_fit.py), and the board already carries
# each ranked player's rank (`rec`). So a player's high school stars are the live classes' own rank-to-stars curve
# (data/cbb_recruits.json) read at his rank: from the board, else from On3's team lists (the industry rank, or the
# rating placed among his class's ranked recruits), else the floor: listed with no grade, or listed nowhere.
C3B = os.path.join(ROOT, 'scripts', '.cache', 'on3commits', 'basketball')
PACKB = os.path.join(ROOT, 'scripts', 'data', 'arkstars_hist_cbb.json.gz')
JOINB = os.path.join(ROOT, 'static', 'data', 'arkstars-cbb.json')


def cbb_curve():
    """rank -> ARK stars as the recruit boards grade the classes now being recruited (monotone in rank)"""
    d = json.load(open(os.path.join(ROOT, 'data', 'cbb_recruits.json'))); pts = defaultdict(list)
    for cl in d['classes']:
        for r in cl['list']:
            if r.get('rk') and r.get('ark'): pts[int(r['rk'])].append(float(r['ark']))
    rk = sorted(pts); v = [float(np.median(pts[k])) for k in rk]
    v = list(np.minimum.accumulate(v))   # never better at a worse rank
    return lambda k: (v[min(len(rk) - 1, max(0, int(np.searchsorted(rk, k))))] if k and k <= rk[-1] else 1.0)


def cbb_pack(keep=False):
    """On3's basketball team lists, one row a recruit: [on3 key, name, class, state, home, signing school (ESPN id),
    later schools, industry rank, industry rating, best lone service rating, dob]"""
    f = os.path.join(AC, 'espn_teams_bb.json')
    if not os.path.exists(f):
        j = R.S.get('https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams?groups=50&limit=500', timeout=40).json()
        json.dump({t['team']['id']: {'name': t['team'].get('location'), 'full': t['team']['displayName']} for t in j['sports'][0]['leagues'][0]['teams']}, open(f, 'w'))
    et = json.load(open(f)); by = {slugify(v['full']): k for k, v in et.items()}
    meta = json.load(open(os.path.join(C3B, '_teams.json'))) if os.path.exists(os.path.join(C3B, '_teams.json')) else {}
    fb = on3_tids(espn_teams())   # the football map covers the schools both sports share (ESPN ids are the school's)
    rows = {}; miss = Counter()
    if keep and os.path.exists(PACKB):
        d0 = json.load(gzip.open(PACKB, 'rt')); rows = {a[0]: dict(zip(d0['cols'], a)) for a in d0['rows']}
    for p in glob.glob(os.path.join(C3B, '*-*.json')):
        slug, yr = re.match(r'(.+)-(\d{4})\.json$', os.path.basename(p)).groups(); yr = int(yr)
        t = str((meta.get(slug) or {}).get('espn') or '') or by.get(slug) or fb.get(slug)
        if not t: miss[slug] += 1
        for r in json.load(open(p)):
            if not r.get('name') or not r.get('cls'): continue
            sv = r.get('svc') or {}; ind = sv.get('industry') or sv.get('consensus')
            o = rows.setdefault(r['key'], {'on3': r['key'], 'name': r['name'], 'y': r['cls'], 'state': r.get('state'), 'home': r.get('home'), 'tid': None, 'later': [],
                                           'rk': None, 'ind': None, 'one': None, 'dob': (r.get('dob') or '')[:10] or None})
            if ind: o['rk'] = o['rk'] or ind[2]; o['ind'] = o['ind'] or round(ind[0], 2)
            one = [sv[k][0] for k in ('247', 'on3') if k in sv]
            if one and not o['one']: o['one'] = round(float(np.mean(one)), 1)
            if not t: continue
            if r.get('xfer') or yr != r['cls']:
                if [t, yr] not in o['later']: o['later'].append([t, yr])
            elif not o['tid']: o['tid'] = t
    if miss: print('On3 basketball teams with no ESPN id:', ', '.join(sorted(miss))[:600], flush=True)
    out = {'asof': __import__('datetime').date.today().isoformat(), 'cols': ['on3', 'name', 'y', 'state', 'home', 'tid', 'later', 'rk', 'ind', 'one', 'dob'], 'rows': [list(o.values()) for o in rows.values()]}
    with gzip.open(PACKB, 'wt') as h: json.dump(out, h, separators=(',', ':'))
    return len(out['rows'])


def cbb_join():
    d = json.load(gzip.open(PACKB, 'rt')); pool = [dict(zip(d['cols'], a)) for a in d['rows']]
    # a rating with no rank: its place among the class's ranked recruits
    by_cls = defaultdict(list)
    for r in pool:
        if r['rk'] and r['ind']: by_cls[r['y']].append((r['ind'], r['rk']))
    def rank_of(r):
        if r['rk']: return r['rk']
        if r['ind'] and len(by_cls[r['y']]) > 30:
            pts = sorted(by_cls[r['y']]); x = [a for a, _ in pts]; y = [b for _, b in pts]
            return float(np.interp(r['ind'], x, y)) if r['ind'] >= x[0] else None
        return None
    star = cbb_curve()
    b = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json'))); c = {k: i for i, k in enumerate(b['cols'])}
    b['asof'] = b.get('asof') or b.get('wkFrom') or __import__('datetime').date.today().isoformat(); season = int(b['asof'][:4]) + (1 if b['asof'][5:7] >= '07' else 0)
    tid_of = lambda r: (re.search(r'/(\d+)\.png', r[c['logo']] or '') or [None, None])[1]
    bykey = {r['on3']: r for r in pool}
    M = N.Matcher(pool, name='name', team=lambda r: [t for t in [r['tid']] + [t for t, _ in r['later']] if t], pos=None, cls='y', team_eq=lambda a, b: bool(set(a) & set(b)))
    out, how = [], Counter()
    for r in b['rows']:
        nm, t = r[c['name']], tid_of(r); rec = r[c['rec']] or {}; lk = r[c['links']] or {}
        k = (re.search(r'-(\d+)/?$', lk.get('on3') or '') or [None, None])[1]; eid = (re.search(r'/id/(\d+)', lk.get('espn') or '') or [None, None])[1]
        back = CLS_BACK.get((r[c['cls']] or '')[:2]); fit = (lambda y, back=back: season - 1 - back[1] <= y <= season - back[0]) if back else (lambda y: True)
        m = bykey.get(int(k)) if k else None; h = 'on3' if m else None
        if m is None and t: m, h = M.find(nm, team=[t], cls=fit, cross_team='none'); h = 'school' if m else None
        rk = rec.get('on3rk') or rec.get('rk247') or (rank_of(m) if m else None); y = rec.get('cls') or (m['y'] if m else None)
        if rec.get('on3rk') or rec.get('rk247'): h = 'board'
        if h is None: how['unlisted'] += 1; out.append([eid, nm, r[c['team']], 1.0, None, 'unlisted', None]); continue
        how[h + (' ranked' if rk else ' unranked')] += 1
        out.append([eid, nm, r[c['team']], star(rk) if rk else 1.0, y, h, round(rk) if rk else None])
    # the read on the floor: this season's production by high school stars (the board's own numbers, nothing fit here)
    row = {(r[c['name']], r[c['team']]): r for r in b['rows']}; tiers = []
    grp = lambda o: 'unlisted' if o[5] == 'unlisted' else 'listed, no rank' if o[6] is None else f'{min(o[3], 4.0):g}'
    for g in sorted({grp(o) for o in out}):
        rs = [row[(o[1], o[2])] for o in out if grp(o) == g]
        st = [x[c['now']] or {} for x in rs]; mp = [s.get('mpg') for s in st if s.get('mpg') is not None]; bp = [s.get('bpm') for s in st if s.get('bpm') is not None and (s.get('mpg') or 0) >= 10]
        tiers.append({'k': g, 'n': len(rs), 'mpg': round(float(np.mean(mp)), 1) if mp else None, 'bpm10': round(float(np.mean(bp)), 2) if bp else None, 'nBpm': len(bp),
                      'fv': round(float(np.mean([x[c['fv']] for x in rs])), 1), 'fv30': round(float(np.mean([x[c['fv']] >= 30 for x in rs])), 4)})
    res = {'asof': b['asof'], 'packed': d['asof'], 'cols': ['espn', 'name', 'team', 'ark', 'class', 'how', 'rank'], 'how': dict(sorted(how.items())), 'tiers': tiers, 'rows': out}
    json.dump(res, open(JOINB, 'w'), separators=(',', ':'))
    hs = os.path.join(ROOT, 'data', 'arkstars_hs.json'); cur = json.load(open(hs)) if os.path.exists(hs) else {}
    cur['cbb'] = {'asof': b['asof'], 'how': res['how'], 'by': {f'{o[1]}|{o[2]}': o[3] for o in out}}
    json.dump(cur, open(hs, 'w'), separators=(',', ':'))
    if os.path.exists(RES):
        rr = json.load(open(RES)); rr['cbb'] = {'asof': b['asof'], 'how': res['how'], 'tiers': tiers}; json.dump(rr, open(RES, 'w'), indent=1)
    print('cbb join', res['how']); [print('  ', t) for t in tiers]
    return res


def main():
    if '--test' in sys.argv:
        res, _ = test(); print(json.dumps(res, indent=1)); return
    upd = '--update' in sys.argv
    if '--pull' in sys.argv and '--cbb-only' not in sys.argv:
        allrows, _ = build(pseudo=False)
        print('pack', write_pack(allrows))
    elif upd and '--cbb-only' not in sys.argv:
        # the classes from this season's freshmen on are merged again; the older ones keep their rows and take the new
        # team lists' transfers (the cache holds only what scripts/on3_commits.mjs pulled in this run)
        season = int(json.load(open(R.ALL))['asof'][:4]); base, meta = read_pack(); yrs = range(season, LAST + 1)
        allrows, _ = build(yrs, pseudo=False, base=base, prog=meta['prog'])
        print('pack', write_pack(allrows, meta['prog'], set(yrs)))
    if '--cbb-only' not in sys.argv: join(pull='--pull' in sys.argv or upd)
    if ('--pull' in sys.argv or upd) and os.path.isdir(C3B): print('cbb pack', cbb_pack(keep=upd))
    if os.path.exists(PACKB): cbb_join()


if __name__ == '__main__':
    main()
