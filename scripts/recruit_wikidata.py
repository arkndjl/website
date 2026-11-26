#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Birth dates of young basketball and football players from Wikidata (one SPARQL query a sport; Jan 1 dates are
year-only entries and are dropped), for the
recruits' age for the class (scripts/recruit_age.py reads the file as a third exact source, after the pins and FIBA).
-> scripts/data/recruit_wikidata_dob.json = {sport: {name key (scripts/names.py): [birth dates]}}, kept to the names on
the sport's recruit tabs. recruit_age takes a date only when one person of that name fits the class (17-20 on Sep 1)
and On3's listed-age bound, so a namesake cannot land on a recruit. A failed query leaves the sport's rows as they were.

    python3 scripts/recruit_wikidata.py [cbb] [cfb]"""
import datetime as dt
import json, os, subprocess, sys, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N  # noqa: E402

OUT = os.path.join(ROOT, 'scripts', 'data', 'recruit_wikidata_dob.json')
OCC = {'cbb': 'Q3665646', 'cfb': 'Q19204627'}       # basketball player, American football player
UA = 'site-data-bot/1.0'


def query(occ, since):
    q = ('SELECT ?pLabel ?dob WHERE { ?p wdt:P106 wd:%s ; wdt:P569 ?dob . FILTER(?dob >= "%s-01-01T00:00:00Z"^^xsd:dateTime) '
         'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }') % (occ, since)
    u = 'https://query.wikidata.org/sparql?' + urllib.parse.urlencode({'format': 'json', 'query': q})
    r = subprocess.run(['curl', '-sS', '-m', '150', '-A', UA, u], capture_output=True, text=True)
    return json.loads(r.stdout)['results']['bindings']


def wanted(sp):
    d = json.load(open(os.path.join(ROOT, 'data', f'{sp}_recruits.json')))
    cl = d.get('classes') or ([{'list': d.get('class') or []}] + (d.get('future') or []))
    return {N.key(r['name']) for c in cl for r in c.get('list') or [] if r.get('name')}


def main():
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    year = dt.date.today().year
    for sp in [a for a in sys.argv[1:] if a in OCC] or list(OCC):
        try:
            rows, keep = query(OCC[sp], year - 22), wanted(sp)
        except (ValueError, KeyError, OSError) as e:
            print(sp, 'wikidata query failed:', e, file=sys.stderr); continue
        by = {}
        for b in rows:
            k, d = N.key(b['pLabel']['value']), b['dob']['value'][:10]
            if k in keep and d[:4].isdigit() and d[5:] != '01-01' and year - 22 <= int(d[:4]) <= year - 12: by.setdefault(k, set()).add(d)
        if not by and out.get(sp): print(sp, 'no rows: kept the last pull', file=sys.stderr); continue
        out[sp] = {k: sorted(v) for k, v in sorted(by.items())}
        print(sp, len(rows), 'wikidata players,', len(by), 'names on the recruit tabs')
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), sort_keys=True)


if __name__ == '__main__':
    main()
