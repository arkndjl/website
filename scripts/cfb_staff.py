#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Head coach, offensive and defensive coordinators of every FBS and FCS team, seasons 2021-26, from each
'<season> <team> football team' Wikipedia infobox (one raw page per request; the batch API answers 429 from cloud hosts).

    python3 scripts/cfb_staff.py            # -> scripts/data/cfb_staff_hist.json (once a season; pages are cached)
Needs scripts/cfb_transfer_fit.py's team cache (scripts/.cache/transfer) for the team names.

load() joins it with the FBS head coaches and coordinators of 2013-25 (scripts/data/coach_alltime_src.json.gz) and picks
each season's starting head coach by continuity. changed(season) is the schools whose head coach is not the one who
started the season (the recruit model's `late` term; scripts/research/coach_loyalty_nov27)."""
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
from collections import defaultdict

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as N  # noqa: E402
OUT = os.path.join(ROOT, 'scripts', 'data', 'cfb_staff_hist.json')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'cfbstaff')
UA = 'arkndjl.net ARKBOARD (https://arkndjl.net; site maintenance)'
SEASONS = range(2021, 2027)
os.makedirs(CACHE, exist_ok=True)


def raw(title):
    f = os.path.join(CACHE, re.sub(r'[^A-Za-z0-9]+', '_', title) + '.txt')
    if os.path.exists(f):
        return open(f).read()
    url = 'https://en.wikipedia.org/w/index.php?action=raw&section=0&title=' + urllib.parse.quote(title.replace(' ', '_'))
    txt = ''
    for k in range(5):
        r = requests.get(url, headers={'User-Agent': UA}, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get('retry-after') or 20 * 2 ** k)); continue
        txt = r.text if r.status_code == 200 else ''
        break
    else:
        return None
    m = re.match(r'\s*#REDIRECT\s*\[\[([^\]|#]+)', txt, re.I)
    if m and m.group(1) != title:
        txt = raw(m.group(1)) or ''
    open(f, 'w').write(txt)
    time.sleep(0.35)
    return txt


def people(txt, field):
    out = []
    for m in re.finditer(r'\|\s*' + field + r'\d?\s*=([^\n]*)', txt or ''):
        v = m.group(1)
        names = re.findall(r'\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]', v)
        if not names:
            names = [x.strip() for x in re.split(r'<br\s*/?>|,|/|\(|&', re.sub(r'<ref.*', '', v)) if x.strip() and not re.match(r'^[\d\W]|.*\)$|interim|season|games?\b', x.strip(), re.I)][:2]
        out += [re.sub(r'\s*\(.*?\)', '', n).strip() for n in names]
    return [n for n in dict.fromkeys(out) if n and len(n.split()) >= 2 and not re.search(r'coach|coordinator|football|\d', n, re.I)]


def main():
    import cfb_transfer_fit as T
    T.OFFLINE = True
    full = {}
    for s in (2026, 2025, 2024):
        for tid, div in T.teams_of(s).items():
            if tid not in full:
                t = T.get(f'{T.CORE}/seasons/{s}/teams/{tid}') or {}
                if t.get('displayName'): full[tid] = t['displayName']
    print('teams', len(full), flush=True)
    out = {}
    for s in SEASONS:
        out[str(s)] = {}
        for tid, nm in sorted(full.items()):
            txt = raw(f'{s} {nm} football team')
            if txt is None: print('gave up (429)', s, nm); continue
            v = {'hc': people(txt, 'head_coach'), 'oc': people(txt, 'off_coach'), 'dc': people(txt, 'def_coach')}
            if v['hc']: out[str(s)][tid] = v
        print(s, len(out[str(s)]), 'of', len(full), 'oc', sum(bool(v['oc']) for v in out[str(s)].values()), flush=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), sort_keys=True)


POSW = {'running back', 'defensive end', 'quarterback', 'cornerback', 'linebacker', 'offensive line', 'offensive tackle', 'wide receiver', 'safety', 'tight end',
        'defensive tackle', 'defensive back', 'int', 'interim', 'center', 'guard', 'fullback', 'halfback', 'defensive line', 'tbd', 'vacant'}


def ck(n):
    """coach name key: the disambiguator ("(American football)") off, position words and placeholders dropped"""
    k = N.key(re.sub(r'\s*\(.*?\)', '', n or ''))
    return None if (not k or k in POSW or len(k.split()) < 2) else k


def keys(v):
    return [k for k in (ck(n) for n in v or []) if k]


def clean(staff):
    """staff: {season: {tid: {'hc': [names], 'oc': [...], 'dc': [...]}}} -> the season-start head coach by continuity
    (the name also there the season before, else the one there the season after, else the first listed)"""
    out = defaultdict(dict)
    for y in sorted(staff):
        for t, v in staff[y].items():
            hc = keys(v.get('hc'))
            if not hc: continue
            prev = keys((staff.get(y - 1, {}).get(t) or {}).get('hc'))
            nxt = keys((staff.get(y + 1, {}).get(t) or {}).get('hc'))
            pick = next((n for n in hc if n in prev), None) or next((n for n in hc if n in nxt), None) or hc[0]
            out[y][t] = {'hc': pick, 'co': set(keys((v.get('oc') or []) + (v.get('dc') or []))), 'oc': set(keys(v.get('oc'))), 'dc': set(keys(v.get('dc')))}
    return out


_LOAD = []


def load():
    """{season: {ESPN team id: {'hc', 'co', 'oc', 'dc'}}}: FBS 2013-25 from the all-time coach file, then every FBS/FCS
    team 2021-26 from the season infoboxes (OUT)"""
    if _LOAD: return _LOAD[0]
    d = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'coach_alltime_src.json.gz')))['cfb']
    camp = json.load(open(os.path.join(ROOT, 'scripts', 'geo', 'recruit_campus.json')))['cfb']
    alias = {'appalachianstate': 'appstate', 'louisianamonroe': 'ulmonroe', 'miamiohio': 'miamioh', 'middletennesseestate': 'middletennessee',
             'samhoustonstate': 'samhouston', 'southernmississippi': 'southernmiss'}
    by = {}
    for t, v in camp.items():
        if v and v.get('name'): by.setdefault(N.team_key(v['name']), t)
    staff = defaultdict(dict)
    for r in d['rows']:
        if r['y'] < 2013: continue
        k = N.team_key(d['teams'][r['t']]); tid = by.get(k) or by.get(alias.get(k))
        if tid: staff[r['y']][tid] = {'hc': [c[0] for c in r['cs']], 'oc': r.get('oc') or [], 'dc': r.get('dc') or []}
    if os.path.exists(OUT):
        for y, T in json.load(open(OUT)).items():
            for t, v in T.items(): staff[int(y)][t] = v
    _LOAD.append(clean(staff))
    return _LOAD[0]


def changed(season):
    """{tid: 1.0}: schools whose head coach after `season` is not the one who started it. A finished season: the next
    season's starting coach differs. The season being played: today's head coach (data/cfb_coach_market.json, from the
    board run) is not the one in scripts/data/cfb_hc_start.json (fired, left, an interim)."""
    st = load()
    if st.get(season + 1):
        return {t: 1.0 for t, v in st[season + 1].items() if t in st.get(season, {}) and st[season][t]['hc'] != v['hc']}
    try:
        hs = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cfb_hc_start.json')))
        mk = json.load(open(os.path.join(ROOT, 'data', 'cfb_coach_market.json')))
    except (OSError, ValueError):
        return {}
    if int(hs.get('season') or 0) != season: return {}
    out = {}
    for t in mk.get('teams', []):
        a = keys(hs['coaches'].get(t['tid']))
        if a and (t.get('interim') or not any(N.same(t.get('hc') or '', n) for n in hs['coaches'][t['tid']])): out[t['tid']] = 1.0
    return out


if __name__ == '__main__':
    main()
