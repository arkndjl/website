#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Birth dates from Tankathon's NFL draft pages for College Football ARKBOARD players: added to data/cfb_dob.json
(the store scripts/fetch_cfb.mjs reads; it fills the rest from Wikidata and Wikipedia, which win when both have him).

    python3 scripts/cfb_dob.py              # best-graded players without a date first, at most 1,500 new pages a run
    python3 scripts/cfb_dob.py --max 300

Tankathon prints each prospect's age on draft day to two decimals; the birth date backed out of it (tankathon_bio.dob_of)
is good to about +-2 days. The school must match (scripts/names.py), so a namesake at another school is never taken.
"""
import datetime as dt, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tankathon_bio as T

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cfb_dob.json')
BOARD = os.path.join(ROOT, 'static', 'data', 'cfb-all.json')


def plausible(d, season=2026): return bool(d) and season - 27 <= int(d[:4]) <= season - 16


def main():
    max_new = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 1500
    store = json.load(open(OUT)) if os.path.exists(OUT) else {}
    B = json.load(open(BOARD))
    ci = {c: j for j, c in enumerate(B['cols'])}
    rows = [r for r in B['rows'] if r[ci['age']] is None and r[ci['team']]]
    rows = [r for r in rows if not (store.get(f"{r[ci['name']]}|{r[ci['team']]}") or {}).get('dob')]
    rows.sort(key=lambda r: r[ci['ovr']] if r[ci['ovr']] is not None else 1e9)
    hits = T.lookup('nfl', [{'name': r[ci['name']], 'team': r[ci['team']]} for r in rows], max_new=max_new)
    n = 0
    for i, b in hits.items():
        d = T.dob_of('nfl', b)
        if not plausible(d): continue
        r = rows[i]
        store[f"{r[ci['name']]}|{r[ci['team']]}"] = {'dob': d, 'src': 'tankathon', 'slug': b['slug'], 'dage': [b['dy'], b['dage']]}
        n += 1
    json.dump(dict(sorted(store.items())), open(OUT, 'w'), indent=1)
    open(OUT, 'a').write('\n')
    print(f'{len(rows)} board players without a birth date; Tankathon {n}; store holds {sum(1 for v in store.values() if v.get("dob"))} dates')


if __name__ == '__main__':
    main()
