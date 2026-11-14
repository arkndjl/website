#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Birth dates for College Basketball ARKBOARD players that Barttorvik doesn't have yet (freshmen until their games
count, a few transfers): data/cbb_dob.json, read by scripts/cbb_live.py and scripts/fetch_cbb.py.

    python3 scripts/cbb_dob.py              # look up every board player without a birth date
    python3 scripts/cbb_dob.py --max 300    # read at most 300 new Tankathon pages this run (default 600)

Sources, first that has him:
  1. Barttorvik's season file (the live board reads it directly; this script records the date too, so the preseason
     builder has it)
  2. Tankathon (scripts/tankathon_bio.py): draft age to two decimals -> birth date, about +-2 days. School must match.
  3. Wikidata P569 for a basketball player (Q3665646) whose teams or schools include his school
Each date is kept with its source; a miss is retried after 14 days. Matching goes through scripts/names.py.
"""
import datetime as dt, json, os, re, subprocess, sys, time, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as N
import tankathon_bio as T

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


def wikidata(names):
    """name -> [(dob, 'team|school labels')] for basketball players with that English label"""
    out = {}
    for i in range(0, len(names), 60):
        vals = ' '.join(json.dumps(n) + '@en' for n in names[i:i + 60])
        q = f'''SELECT ?name ?dob (GROUP_CONCAT(DISTINCT ?tl; separator="|") AS ?teams) WHERE {{
          VALUES ?name {{ {vals} }} ?p rdfs:label ?name; wdt:P106 wd:Q3665646; wdt:P569 ?dob.
          OPTIONAL {{ ?p wdt:P54|wdt:P69 ?t. ?t rdfs:label ?tl FILTER(lang(?tl)="en") }} }} GROUP BY ?name ?p ?dob'''
        url = 'https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(q)
        r = subprocess.run(['curl', '-s', '-m', '60', '-A', UA, url], capture_output=True, text=True)
        try:
            for b in json.loads(r.stdout)['results']['bindings']:
                out.setdefault(b['name']['value'], []).append((b['dob']['value'][:10], b.get('teams', {}).get('value', '').lower()))
        except (ValueError, KeyError):
            print('wikidata batch failed', i)
        time.sleep(1)
    return out


def main():
    max_new = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 600
    today = dt.date.today()
    store = load()
    B = json.load(open(BOARD))
    ci = {c: j for j, c in enumerate(B['cols'])}
    rows = [r for r in B['rows'] if r[ci['age']] is None and r[ci['cls']] != 'Intl']
    todo = []
    for r in rows:
        s = store.get(key(r[ci['name']], r[ci['team']]))
        if s and (s.get('dob') or (today - dt.date.fromisoformat(s['checked'])).days < 14): continue
        todo.append(r)
    # Tankathon: the school prospect lists are in its cache; guess slugs best-graded first
    todo.sort(key=lambda r: r[ci['ovr']])
    hits = T.lookup('nba', [{'name': r[ci['name']], 'team': r[ci['team']]} for r in todo], max_new=max_new, today=today)
    found = {'tankathon': 0, 'wikidata': 0}
    for i, b in hits.items():
        d = T.dob_of('nba', b)
        if plausible(d):
            r = todo[i]
            store[key(r[ci['name']], r[ci['team']])] = {'name': r[ci['name']], 'dob': d, 'src': 'tankathon', 'slug': b['slug'], 'dage': [b['dy'], b['dage']]}
            found['tankathon'] += 1
    rest = [r for r in todo if not (store.get(key(r[ci['name']], r[ci['team']])) or {}).get('dob')]
    wd = wikidata(sorted({r[ci['name']] for r in rest}))
    for r in rest:
        k = key(r[ci['name']], r[ci['team']])
        school = re.sub(r'\bst$', 'state', (r[ci['team']] or '').lower())
        hit = next((d for d, t in wd.get(r[ci['name']], []) if plausible(d) and school_in(school, t)), None)
        if hit:
            store[k] = {'name': r[ci['name']], 'dob': hit, 'src': 'wikidata'}; found['wikidata'] += 1
        else:
            store[k] = {'name': r[ci['name']], 'dob': None, 'checked': today.isoformat()}
    json.dump(dict(sorted(store.items())), open(OUT, 'w'), indent=0, separators=(',', ':'))
    have = sum(1 for v in store.values() if v.get('dob'))
    print(f'{len(rows)} board players without a Barttorvik birth date; looked up {len(todo)}: '
          f'Tankathon {found["tankathon"]}, Wikidata {found["wikidata"]}; store holds {have} dates')


if __name__ == '__main__':
    main()
