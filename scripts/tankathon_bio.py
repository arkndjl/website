#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Draft prospects' bios from Tankathon (basketball and football): draft age to two decimals, height, weight, school,
position. A birth date backed out of the draft age is good to about two days.

    python3 scripts/tankathon_bio.py nba            # every school's current prospects (and the big board)
    python3 scripts/tankathon_bio.py nfl
    python3 scripts/tankathon_bio.py nba --calib    # print the draft dates the ages are measured to

Each player page shows "'28 Draft Age 19.06 yrs": his age on the day of that year's draft. Tankathon doesn't print the
date it measures to, so DRAFT_DAY holds it per sport and year, fit on prospects whose birth date another source has
(--calib: the median of dob + draft age; NBA vs Barttorvik, NFL vs Wikidata). A year with no fit uses the usual day
(NBA: the last Thursday of June; NFL: the last Thursday of April).

Pages are cached in scripts/data/tankathon_<sport>.json (committed: name, school, position, class, height, weight,
draft year, draft age, hometown, the day read). A page is reread after 30 days; a slug with no page after 60.
lookup(sport, rows) also tries the slug a name would have (for board players not on a school's prospect list).
"""
import datetime as dt, html, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as N

UA = 'arkboard-research/1.0 (+https://arkndjl.net)'
BASE = 'https://www.tankathon.com'
PRE = {'nba': '', 'nfl': '/nfl'}
STORE = lambda sport: os.path.join(HERE, 'data', f'tankathon_{sport}.json')
SLEEP = 0.6
# the day each year's draft age is measured to (--calib; refit when a new class appears)
DRAFT_DAY = {'nba': {}, 'nfl': {}}
DAY_FILE = os.path.join(HERE, 'data', 'tankathon_draft_days.json')
if os.path.exists(DAY_FILE): DRAFT_DAY.update(json.load(open(DAY_FILE)))


def get(url):
    r = subprocess.run(['curl', '-s', '-m', '30', '-A', UA, '-w', '\n%{http_code}', url], capture_output=True, text=True)
    body, _, code = r.stdout.rpartition('\n')
    return (body if code == '200' else None), code


def load(sport):
    try: return json.load(open(STORE(sport)))
    except (OSError, ValueError): return {}


def save(sport, store):
    os.makedirs(os.path.dirname(STORE(sport)), exist_ok=True)
    json.dump(dict(sorted(store.items())), open(STORE(sport), 'w'), indent=0, separators=(',', ':'))


def strip(s): return html.unescape(re.sub(r'<[^>]+>', ' ', s or '')).strip()


def parse(h):
    """a player page -> bio dict (None if it isn't one)"""
    m = re.search(r'<h1 class="page-title"[^>]*>(.*?)</h1>', h, re.S)
    if not m: return None
    out = {'name': strip(m.group(1))}
    i = h.find('flex-player-info')
    seg = h[i:i + 6000] if i >= 0 else h
    p = re.search(r'<div class="position"[^>]*>(.*?)</div>', seg, re.S)
    if p: out['pos'] = strip(p.group(1))
    t = re.search(r'class="team-name[^"]*"[^>]*>([^<]*)<', seg, re.S)
    if t: out['school'] = strip(t.group(1))
    c = re.search(r'class="grad-class">(.*?)</span>\s*</div>', seg, re.S)
    if c: out['cls'] = strip(c.group(1)).replace('•', '').strip()
    ft = re.search(r'<span class="feet">(\d)\'</span><span class="inches">([\d.]+)', seg)
    if ft: out['ht'] = int(ft.group(1)) * 12 + float(ft.group(2))
    w = re.search(r'Weight</div><div class="value">([\d.]+)', seg)
    if w: out['wt'] = float(w.group(1))
    a = re.search(r"'(\d\d) Draft Age</div><div class=\"value\">([\d.]+)", seg)
    if a: out['dy'], out['dage'] = 2000 + int(a.group(1)), float(a.group(2))
    ht = re.search(r'class="hometown flex">.*?<div>(.*?)</div>', seg, re.S)
    if ht: out['home'] = strip(ht.group(1))
    return out


def page(sport, slug, store, today, force=False):
    s = store.get(slug)
    if s and not force:
        age = (today - dt.date.fromisoformat(s['read'])).days
        if age < (60 if s.get('miss') else 30): return s if not s.get('miss') else None
    h, code = get(f'{BASE}{PRE[sport]}/players/{slug}')
    time.sleep(SLEEP)
    if h is None:
        if code == '404': store[slug] = {'miss': 1, 'read': today.isoformat()}
        return None
    b = parse(h)
    if not b: return None
    b['read'] = today.isoformat()
    store[slug] = b
    return b


def discover(sport):
    """every school's current prospect list (school pages hold 'Prospects' then 'Draft History'), plus the big board"""
    idx, _ = get(f'{BASE}{PRE[sport]}/colleges')
    schools = sorted(set(re.findall(rf'href="{PRE[sport]}/colleges/([a-z0-9-]+)"', idx or '')))
    slugs = set()
    for s in schools:
        h, _ = get(f'{BASE}{PRE[sport]}/colleges/{s}')
        time.sleep(SLEEP)
        if not h: continue
        a, b = h.find('team-page-section-title'), h.find('Draft History')
        slugs |= set(re.findall(rf'href="{PRE[sport]}/players/([a-z0-9-]+)"', h[a:b] if a >= 0 and b > a else ''))
    for bb in ('big-board', 'big_board'):
        h, _ = get(f'{BASE}{PRE[sport]}/{bb}')
        if h: slugs |= set(re.findall(rf'href="{PRE[sport]}/players/([a-z0-9-]+)"', h)); break
    slugs.discard('compare')
    return sorted(slugs), len(schools)


def slug_of(name):
    s = N.fold(name).lower().replace('&', 'and')
    s = re.sub(r"[.'’]", '', s)
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def draft_day(sport, year):
    days = DRAFT_DAY.get(sport, {})
    d = days.get(str(year))
    if d: return dt.date.fromisoformat(d)
    if days:   # a year not yet fit: the nearest fit year's calendar day
        y0 = min(days, key=lambda y: abs(int(y) - year))
        return dt.date.fromisoformat(days[y0]).replace(year=year)
    m = 6 if sport == 'nba' else 4
    last = dt.date(year, m + 1, 1) - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - 3) % 7)   # last Thursday


def dob_of(sport, b):
    """the birth date backed out of the draft age (about +-2 days), or None"""
    if not b or b.get('dage') is None or not b.get('dy'): return None
    d = draft_day(sport, b['dy']) - dt.timedelta(days=round(b['dage'] * 365.2425))
    return d.isoformat()


def lookup(sport, rows, max_new=400, today=None):
    """rows: [{'name', 'team'}] -> {index: bio} for the rows Tankathon has (school must match). Tries the name's slug,
    then '-jr' style variants, reading at most max_new pages that aren't cached."""
    today = today or dt.date.today()
    store = load(sport)
    by_slug = {k: v for k, v in store.items() if not v.get('miss')}
    m = N.Matcher([dict(v, slug=k) for k, v in by_slug.items()], name='name', team='school', pos=None, sport='basketball' if sport == 'nba' else 'football')
    out, fetched = {}, 0
    for i, r in enumerate(rows):
        hit, _ = m.find(r['name'], r.get('team'))
        if hit and r.get('team') and not N.same_team(hit.get('school') or '', r['team']): hit = None
        if not hit:
            sl = slug_of(r['name'])
            if sl not in store and fetched >= max_new: continue
            fetched += sl not in store
            b = page(sport, sl, store, today)
            if b and N.same(b['name'], r['name']) and (not r.get('team') or N.same_team(b.get('school') or '', r['team'])):
                hit = dict(b, slug=sl)
        if hit: out[i] = hit
    save(sport, store)
    return out


def calib(sport, known):
    """known: {slug: dob} -> per-year median of dob + draft age"""
    from statistics import median
    store = load(sport)
    by = {}
    for sl, dob in known.items():
        b = store.get(sl)
        if not b or b.get('miss') or b.get('dage') is None: continue
        d = dt.date.fromisoformat(dob) + dt.timedelta(days=b['dage'] * 365.2425)
        by.setdefault(b['dy'], []).append(d.toordinal())
    return {y: (dt.date.fromordinal(int(median(v))).isoformat(), len(v)) for y, v in sorted(by.items())}


if __name__ == '__main__':
    sport = sys.argv[1] if len(sys.argv) > 1 else 'nba'
    today = dt.date.today()
    store = load(sport)
    slugs, ns = discover(sport)
    print(f'{sport}: {ns} schools, {len(slugs)} prospects listed')
    n = 0
    for sl in slugs:
        if page(sport, sl, store, today): n += 1
    save(sport, store)
    ok = [v for v in store.values() if not v.get('miss')]
    print(f'{n} read; store {len(ok)} bios, {sum(1 for v in ok if v.get("dage") is not None)} with a draft age')
