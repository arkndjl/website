#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Birth dates for College Basketball ARKBOARD players that Barttorvik doesn't have yet (freshmen until their games
count, a few transfers): data/cbb_dob.json, read by scripts/cbb_live.py and scripts/fetch_cbb.py.

    python3 scripts/cbb_dob.py              # look up every board player without a birth date

Sources, first that has him (scripts/dob_sources.py):
  0. data/dob_overrides.json: a date checked by hand against a cited page (RealGM, Wikipedia, a club page)
  1. Barttorvik's season file (the live board reads it directly; this script records the date too, so the preseason
     builder has it)
  2. Wikidata P569 (day precision) for a basketball player whose teams or schools include his school
  3. Wikidata, school not listed: the only basketball player with that name born 2000 on, and his teams are clubs
     (or none, for a player from outside the US), not another college, and no other board player has the name: internationals and pro-to-college transfers, whose items list Trento, Milano,
     Mega, not the school. Names go through Wikidata's entity search, so accents and aliases match.
  3b. Wikidata, no team listed but a Sports Reference college basketball id: the one such item with his name, his
     name unique on the board, born to fit his class and within a year of his Barttorvik birth year
  4. Wikipedia search ("<name>" basketball), lead section {{birth date}}, school named in the lead
  5. his school's athletics roster bio (scripts/school_bios.py), when it prints a birth date (also for players whose
     only date is Barttorvik's birth-year stand-in)
Each date is kept with its source; a miss is retried after 14 days. Matching goes through scripts/names.py.
Two sources more than 3 days apart, or two same-name Wikidata players, go to data/dob_conflicts_cbb.json.
    python3 scripts/cbb_dob.py --all        # retry recent misses too (after a source is added)
    python3 scripts/cbb_dob.py --check      # also check every dated board player against Wikidata
"""
import datetime as dt, json, os, re, subprocess, sys, time, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as N
import dob_sources as DS

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cbb_dob.json')
BOARD = os.path.join(ROOT, 'static', 'data', 'cbb-all.json')
UA = 'arkboard-research/1.0 (+https://arkndjl.net)'


def load():
    try: return json.load(open(OUT))
    except (OSError, ValueError): return {}


def key(name, team): return f'{N.key(name)}|{team}'


def plausible(d, lo=1994, hi=2011):
    try: return lo <= int(d[:4]) <= hi
    except (TypeError, ValueError): return False


def school_in(school, labels):
    """the whole school name, as words, in one of his Wikidata team/school labels (a first word alone let 'North'
    match North Carolina and handed a namesake's birth date to a freshman)"""
    pat = re.compile(r'\b' + re.escape(school) + r'\b')
    return bool(school) and any(pat.search(l) for l in labels.split('|'))


COLLEGE = re.compile(r'\b(university|college|high school|academy|prep|state)\b')


def pick_wd(cands, school):
    """(dob, src) from his same-name Wikidata basketball players, or (None, 'ambiguous'/None)"""
    c = [x for x in cands if plausible(x['dob'])]
    hit = [x for x in c if school_in(school, x['teams'])]
    if len({x['dob'] for x in hit}) == 1: return hit[0]['dob'], 'wikidata', hit[0]['qid']
    if hit: return None, 'ambiguous', None
    # not his school: only when he is the one same-name player born 2000 on and lists no other college
    c = [x for x in c if int(x['dob'][:4]) >= 2000]
    clubs = [x for x in c if not any(COLLEGE.search(t) for t in x['teams'].split('|') if t)]
    # an item with no teams at all is taken only for a player from outside the US (the gap this fills); a US name
    # with a bare item is too often a namesake
    clubs = [x for x in clubs if x['teams'] or (x['nat'] and x['nat'] != 'United States')]
    if len(c) == 1 and len(clubs) == 1:
        return clubs[0]['dob'], 'wikidata-club' if clubs[0]['teams'] else 'wikidata-name', clubs[0]['qid']
    return None, ('ambiguous' if len(c) > 1 else None), None


fits_class = DS.fits_class
UNI = re.compile(r'\b(university|college)\b')
HS = re.compile(r'\b(high school|prep|preparatory|academy)\b')


def other_college(labels, school):
    """his Wikidata teams name a college that isn't his school (a namesake, or a transfer the school match missed)"""
    return any(UNI.search(t) and not HS.search(t) and not school_in(school, t) for t in labels.split('|') if t)


def school_of(team): return re.sub(r'\bst$', 'state', (team or '').lower())


def year_only(age, today):
    """an age built on Barttorvik's Oct 15 stand-in date (birth year only), as the board printed it in the last 3 days"""
    import cbb_data as D
    for back in range(3):
        t = today - dt.timedelta(days=back)
        y = t.year - int(age) - 1
        for yy in (y, y + 1):
            a = D.age_on(f'{yy}-10-15', t.year, t.month, t.day)
            if a is not None and abs(a - age) < 0.006: return True
    return False


def cbb_age(d):
    import cbb_data as D
    t = dt.date.today()
    return D.age_on(d, t.year, t.month, t.day)


def main():
    today = dt.date.today()
    store = load()
    B = json.load(open(BOARD))
    ci = {c: j for j, c in enumerate(B['cols'])}
    rows = [r for r in B['rows'] if (r[ci['age']] is None or year_only(r[ci['age']], today)) and r[ci['cls']] != 'Intl']
    every = '--all' in sys.argv   # retry misses checked in the last 14 days too (after a new source is added)
    # Tankathon's robots.txt disallows Claude and AI crawlers: none of its dates are kept; those players are looked up again
    for k, v in list(store.items()):
        if v.get('src') == 'tankathon': store[k] = {'name': v.get('name'), 'dob': None, 'checked': '2000-01-01'}
    todo = []
    for r in rows:
        s = store.get(key(r[ci['name']], r[ci['team']]))
        if s and (s.get('dob') or (not every and (today - dt.date.fromisoformat(s['checked'])).days < 14)): continue
        todo.append(r)
    found = {'wikidata': 0}
    pins = DS.pinned('cbb')
    for k, v in pins.items():
        if v.get('dob'): store[k] = {'name': v['name'], 'dob': v['dob'], 'src': 'override', 'cite': v['src']}
    rest = [r for r in todo if not (store.get(key(r[ci['name']], r[ci['team']])) or {}).get('dob')]
    check = '--check' in sys.argv
    pool = B['rows'] if check else rest
    from collections import Counter
    n_name = Counter(N.key(r[ci['name']]) for r in B['rows'])
    wd = DS.wikidata(sorted({r[ci['name']] for r in pool}), 'basketball')
    found.update({'wikidata-club': 0, 'wikidata-name': 0, 'wikipedia': 0})
    conflicts, miss = [], []
    for r in pool:
        k = key(r[ci['name']], r[ci['team']])
        d, src, qid = pick_wd(wd.get(r[ci['name']], []), school_of(r[ci['team']]))
        if src in ('wikidata-club', 'wikidata-name') and n_name[N.key(r[ci['name']])] > 1:
            d, src, qid = None, None, None   # two board players share the name: a school-less date fits neither
        have = store.get(k) or {}
        if src == 'ambiguous':
            conflicts.append({'key': k, 'name': r[ci['name']], 'team': r[ci['team']], 'why': 'several Wikidata players',
                              'dates': {x['qid']: x['dob'] for x in wd[r[ci['name']]] if plausible(x['dob'])}, 'used': have.get('dob')})
        if r in rest and not have.get('dob'):
            if d:
                store[k] = {'name': r[ci['name']], 'dob': d, 'src': src, 'qid': qid}; found[src] += 1
            else: miss.append(r)
        elif d and src == 'wikidata':
            used = have.get('dob')
            if used and DS.gap(used, d) > 3:
                conflicts.append({'key': k, 'name': r[ci['name']], 'team': r[ci['team']], 'why': 'sources disagree',
                                  'dates': {have.get('src', 'store'): used, 'wikidata ' + qid: d}, 'used': used})
            elif not used and r[ci['age']] is not None:
                a = cbb_age(d)
                if abs(a - r[ci['age']]) > 0.03:
                    conflicts.append({'key': k, 'name': r[ci['name']], 'team': r[ci['team']], 'why': 'sources disagree',
                                      'dates': {'board age': r[ci['age']], 'wikidata ' + qid: d}, 'used': 'board'})
    # Wikidata items with a Sports Reference college basketball id but no team (Toni Bryant, Caleb Holt): the one
    # such player with his name, no other board player with it, born to fit his class and his Barttorvik birth year
    sr = DS.sr_players('basketball')
    bt_years = {}
    try:
        for v in json.load(open(os.path.join(HERE, 'data', 'cbb_bt_dob.json'))).values():
            if v[0]: bt_years.setdefault(v[1], set()).add(int(v[0][:4]))
    except (OSError, ValueError): pass
    found['wikidata-sr'] = 0
    season = today.year if today.month >= 7 else today.year - 1
    still = []
    for r in miss:
        nk = N.key(r[ci['name']])
        c = [x for x in sr.get(nk, []) if plausible(x['dob'])]
        if len(c) == 1 and n_name[nk] == 1 and not other_college(c[0]['teams'], school_of(r[ci['team']])) \
                and fits_class(c[0]['dob'], r[ci['cls']], season, bt_years.get(nk)):
            store[key(r[ci['name']], r[ci['team']])] = {'name': r[ci['name']], 'dob': c[0]['dob'], 'src': 'wikidata-sr',
                                                        'qid': c[0]['qid'], 'sr': c[0]['sr']}
            found['wikidata-sr'] += 1
        else: still.append(r)
    miss = still
    # Wikipedia search for the rest, best-graded first (Wikimedia rate limits: a capped number a run)
    miss.sort(key=lambda r: r[ci['ovr']])
    wp = DS.wikipedia([r[ci['name']] for r in miss], 'basketball', limit=int(os.environ.get('WP_MAX', 120)))
    for r in miss:
        k = key(r[ci['name']], r[ci['team']])
        w = wp.get(r[ci['name']])
        school = school_of(r[ci['team']])
        if w and plausible(w['dob']) and school and re.search(r'\b' + re.escape(school) + r'\b', w['text']):
            store[k] = {'name': r[ci['name']], 'dob': w['dob'], 'src': 'wikipedia', 'title': w['title']}; found['wikipedia'] += 1
        else:
            store[k] = {'name': r[ci['name']], 'dob': None, 'checked': today.isoformat()}
    for k, v in pins.items():   # a pin that disagrees with another source is logged too (the pin is used)
        for x in wd.get(v['name'], []):
            if plausible(x['dob']) and DS.gap(x['dob'], v['dob']) > 3 and school_in(school_of(k.split('|', 1)[1]), x['teams']):
                conflicts.append({'key': k, 'name': v['name'], 'team': k.split('|', 1)[1], 'why': 'override vs Wikidata',
                                  'dates': {'override': v['dob'], 'wikidata ' + x['qid']: x['dob']}, 'used': v['dob']})
    # school athletics bios for whoever still has no day-precise date (scripts/school_bios.py), best-graded first
    import school_bios as SB
    left = sorted([r for r in rows if not (store.get(key(r[ci['name']], r[ci['team']])) or {}).get('dob')], key=lambda r: r[ci['ovr']])
    tid = lambda r: (re.search(r'/(\d+)\.png', r[ci['logo']] or '') or [None, None])[1]
    nm = {key(r[ci['name']], r[ci['team']]): r[ci['name']] for r in left}
    for k, b in SB.lookup('cbb', [(r[ci['name']], r[ci['team']], tid(r)) for r in left], int(os.environ.get('BIO_MAX', 300))).items():
        if plausible(b['dob']):
            store[k] = {'name': nm.get(k, k.split('|')[0]), 'dob': b['dob'], 'src': 'school', 'url': b['url']}
            found['school'] = found.get('school', 0) + 1
    if check or conflicts: DS.log_conflicts('cbb', conflicts)
    json.dump(dict(sorted(store.items())), open(OUT, 'w'), indent=0, separators=(',', ':'))
    have = sum(1 for v in store.values() if v.get('dob'))
    print(f'{len(rows)} board players without a Barttorvik birth date; looked up {len(todo)}: '
          f'{found}; {len(conflicts)} conflicts; store holds {have} dates')


if __name__ == '__main__':
    main()
