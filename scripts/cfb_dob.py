#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Birth dates for College Football ARKBOARD players: data/cfb_dob.json, the store scripts/fetch_cfb.mjs reads (it also
fills from Wikidata and Wikipedia by exact name, school must match).

    python3 scripts/cfb_dob.py                    # best-graded undated players first, within the per-run budgets
    python3 scripts/cfb_dob.py --wd 1500 --bios 300 --check

Sources, first that has him (scripts/dob_sources.py):
  0. data/dob_overrides.json "cfb" (key '<name>|<team>'): checked by hand against a cited page
  1. Wikidata entity search (accents, aliases), day precision, a football player whose teams or schools include his
     school
  2. his school's athletics roster bio (scripts/school_bios.py), when the school prints a birth date
Each date is kept with its source; a miss is retried after 30 days. --check also compares every dated player's
Wikidata date with the one used and logs disagreements to data/dob_conflicts_cfb.json. Tankathon's robots.txt
disallows Claude and AI crawlers, so its draft-age dates are not read, and the ones kept before are dropped.
"""
import datetime as dt, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cfb_all as CA
import dob_sources as DS
import school_bios as SB

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cfb_dob.json')
SEASON = 2026


def plausible(d): return bool(d) and SEASON - 27 <= int(d[:4]) <= SEASON - 16


def school_in(school, labels):
    pat = re.compile(r'\b' + re.escape(school) + r'\b')
    return bool(school) and any(pat.search(l) for l in labels.split('|'))


def arg(name, default):
    return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main():
    today = dt.date.today()
    store = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for k, v in list(store.items()):
        if v.get('src') == 'tankathon': store[k] = {'dob': None, 'checked': '2000-01-01'}
    for k, v in DS.pinned('cfb').items():
        if v.get('dob'): store[k] = {'dob': v['dob'], 'src': 'override', 'cite': v['src']}
    A = CA.read_cfb_all()
    ci = {c: j for j, c in enumerate(A['cols'])}
    rows = [r for r in A['rows'] if r[ci['team']] and r[ci['name']]]
    key = lambda r: f"{r[ci['name']]}|{r[ci['team']]}"
    stale = lambda s: not s or (not s.get('dob') and (today - dt.date.fromisoformat(s.get('checked', '2000-01-01'))).days >= 30)
    todo = [r for r in rows if r[ci['age']] is None and stale(store.get(key(r)))]
    todo.sort(key=lambda r: -(r[ci['fvx']] or 0))
    found = {'wikidata': 0, 'school': 0}
    # 1. Wikidata entity search, school must match
    wd_rows = todo[:arg('--wd', 1500)]
    in_wd = {id(r) for r in wd_rows}
    check = '--check' in sys.argv
    pool = wd_rows + ([r for r in rows if (store.get(key(r)) or {}).get('dob')] if check else [])
    wd = DS.wikidata(sorted({r[ci['name']] for r in pool}), 'football')
    conflicts = []
    for r in pool:
        school = (r[ci['team']] or '').lower()
        hits = {x['dob'] for x in wd.get(r[ci['name']], []) if plausible(x['dob']) and school_in(school, x['teams'])}
        have = store.get(key(r)) or {}
        if len(hits) > 1:
            conflicts.append({'key': key(r), 'why': 'several Wikidata players', 'dates': sorted(hits), 'used': have.get('dob')})
        elif hits and not have.get('dob'):
            store[key(r)] = {'dob': hits.pop(), 'src': 'wikidata'}; found['wikidata'] += 1
        elif hits and have.get('dob') and DS.gap(have['dob'], next(iter(hits))) > 3:
            conflicts.append({'key': key(r), 'why': 'sources disagree', 'dates': {have.get('src', 'store'): have['dob'], 'wikidata': next(iter(hits))}, 'used': have['dob']})
    # 2. school bios for the rest, best-graded first
    rest = [r for r in todo if not (store.get(key(r)) or {}).get('dob')]
    tid = lambda r: (re.search(r'/(\d+)\.png', r[ci['logo']] or '') or [None, None])[1]
    bios = SB.lookup('cfb', [(r[ci['name']], r[ci['team']], tid(r)) for r in rest], arg('--bios', 300))
    import names as N
    for r in rest:
        b = bios.get(f"{N.key(r[ci['name']])}|{r[ci['team']]}")
        if b and plausible(b['dob']):
            store[key(r)] = {'dob': b['dob'], 'src': 'school', 'url': b['url']}; found['school'] += 1
        elif id(r) in in_wd:
            store[key(r)] = {'dob': None, 'checked': today.isoformat()}
    if check or conflicts: DS.log_conflicts('cfb', conflicts)
    json.dump(dict(sorted(store.items())), open(OUT, 'w'), indent=1)
    open(OUT, 'a').write('\n')
    print(f'{len(todo)} undated board players to look up; {found}; {len(conflicts)} conflicts; '
          f'store holds {sum(1 for v in store.values() if v.get("dob"))} dates')


if __name__ == '__main__':
    main()
