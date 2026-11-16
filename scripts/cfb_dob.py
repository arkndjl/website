#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Hand-checked birth dates for College Football ARKBOARD players: data/dob_overrides.json "cfb" (key '<name>|<team>',
each with the page it was read from) into data/cfb_dob.json, the store scripts/fetch_cfb.mjs reads; fetch_cfb.mjs fills
the rest from Wikidata and Wikipedia (school must match).

    python3 scripts/cfb_dob.py

Tankathon's robots.txt disallows Claude and AI crawlers, so its draft-age dates are no longer read, and the ones kept
before are dropped (fetch_cfb.mjs looks those players up again).
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dob_sources as DS

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cfb_dob.json')


def main():
    store = json.load(open(OUT)) if os.path.exists(OUT) else {}
    dropped = 0
    for k, v in list(store.items()):
        if v.get('src') == 'tankathon':
            store[k] = {'dob': None, 'checked': '2000-01-01'}; dropped += 1
    for k, v in DS.pinned('cfb').items():
        if v.get('dob'): store[k] = {'dob': v['dob'], 'src': 'override', 'cite': v['src']}
    json.dump(dict(sorted(store.items())), open(OUT, 'w'), indent=1)
    open(OUT, 'a').write('\n')
    print(f'dropped {dropped} Tankathon dates; store holds {sum(1 for v in store.values() if v.get("dob"))} dates')


if __name__ == '__main__':
    main()
