#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Birth-date sources shared by the board DOB scripts (scripts/cbb_dob.py, scripts/cfb_dob.py).

  pinned(sport)        data/dob_overrides.json: dates checked by hand against a cited page (RealGM, a club or
                       federation page, Wikipedia). They win over every other source.
  wikidata(names, occ) Wikidata's entity search (the search fallback: accents and aliases folded), then P569 at
                       day precision, with his team/school labels, citizenship and the item id; 40 names a SPARQL
                       call, 1 s apart (query.wikidata.org asks for a UA with contact and serial calls).
  wikipedia(names, kw) Wikipedia's own search API ("<name> basketball"), then the lead section's
                       {{birth date}} template: the fallback for players whose Wikidata item has no date. One call a
                       second with maxlag; a 429 stops the run's Wikipedia step (the next run picks up).
  conflict(...)        two dates more than `tol` days apart are logged to data/dob_conflicts.json.

RealGM, Proballers, EliteProspects and On3 answer bots with a Cloudflare challenge or disallow AI crawlers in
robots.txt: they are not fetched; a date read off one of them by hand goes in the overrides file with its URL.
No personal data goes out in a request: names and sport keywords only, under a generic UA.
"""
import datetime as dt, json, os, re, subprocess, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OVERRIDES = os.path.join(ROOT, 'data', 'dob_overrides.json')
CONFLICTS = os.path.join(ROOT, 'data', 'dob_conflicts.json')
UA = 'arkboard-research/1.0 (+https://arkndjl.net)'
OCC = {'basketball': 'Q3665646', 'football': 'Q19204627', 'hockey': 'Q11774891', 'soccer': 'Q937857', 'tennis': 'Q10833314'}


def _get(url, timeout=60):
    r = subprocess.run(['curl', '-s', '-m', str(timeout), '-A', UA, '-w', '\n%{http_code}', url], capture_output=True, text=True)
    body, _, code = r.stdout.rpartition('\n')
    return (int(code) if code.isdigit() else 0), body


def pinned(sport):
    """'<name key>|<team>' -> {'dob', 'src': [urls], ...} for one sport"""
    try: return json.load(open(OVERRIDES)).get(sport, {})
    except (OSError, ValueError): return {}


def wikidata(names, occ='basketball', batch=40):
    """name -> [{'qid', 'dob', 'label', 'teams' (lowercase labels joined by |), 'nat'}], day-precision dates only.
    Each name goes through Wikidata's own entity search (run inside the SPARQL call: labels, aliases, accents
    folded, so "Roko Prkacin" finds "Roko Prkačin"); a hit counts only when its English label has the same name key
    (scripts/names.py) as ours."""
    import names as N
    out = {}
    for i in range(0, len(names), batch):
        vals = ' '.join(json.dumps(n) for n in names[i:i + batch])
        q = f'''SELECT ?name ?p ?lab ?dob (GROUP_CONCAT(DISTINCT ?tl; separator="|") AS ?teams)
          (GROUP_CONCAT(DISTINCT ?cl; separator="|") AS ?nat) WHERE {{
          VALUES ?name {{ {vals} }}
          SERVICE wikibase:mwapi {{ bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "EntitySearch";
            mwapi:search ?name; mwapi:language "en". ?p wikibase:apiOutputItem mwapi:item. }}
          ?p wdt:P106 wd:{OCC[occ]}; rdfs:label ?lab FILTER(lang(?lab)="en")
          ?p p:P569/psv:P569 [ wikibase:timeValue ?dob; wikibase:timePrecision 11 ].
          OPTIONAL {{ ?p wdt:P54|wdt:P69 ?t. ?t rdfs:label ?tl FILTER(lang(?tl)="en") }}
          OPTIONAL {{ ?p wdt:P27 ?c. ?c rdfs:label ?cl FILTER(lang(?cl)="en") }} }} GROUP BY ?name ?p ?lab ?dob'''
        for wait in (0, 30, 90):   # a 429 asks for a pause: back off, then give the batch up for this run
            time.sleep(wait)
            code, body = _get('https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(q), 90)
            if code != 429: break
        try:
            for b in json.loads(body)['results']['bindings']:
                n, lab = b['name']['value'], b['lab']['value']
                if N.key(lab) != N.key(n): continue
                c = {'qid': b['p']['value'].rsplit('/', 1)[-1], 'dob': b['dob']['value'][:10], 'label': lab,
                     'teams': b.get('teams', {}).get('value', '').lower(), 'nat': b.get('nat', {}).get('value', '')}
                if all(x['qid'] != c['qid'] for x in out.get(n, [])): out.setdefault(n, []).append(c)
        except (ValueError, KeyError):
            print('wikidata batch failed', i, code)
        time.sleep(1)
    return out


BIRTH = re.compile(r'\{\{\s*birth[ _]date(?: and age)?\s*\|(?:\s*\w+\s*=[^|}]*\|)*\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})', re.I)


def wikipedia(names, kw='basketball', limit=200):
    """name -> {'title', 'dob', 'text' (lead wikitext, lowercase)} via Wikipedia search, at most `limit` searches"""
    out = {}
    api = 'https://en.wikipedia.org/w/api.php?format=json&formatversion=2&maxlag=5&'
    for n in names[:limit]:
        code, body = _get(api + 'action=query&list=search&srlimit=3&srsearch=' + urllib.parse.quote(f'"{n}" {kw}'), 30)
        if code == 429 or 'too many requests' in body.lower():
            print('wikipedia: rate limited, stopping this run'); break
        try: hits = [h['title'] for h in json.loads(body)['query']['search']]
        except (ValueError, KeyError): hits = []
        last = n.split()[-1].lower()
        hits = [t for t in hits if last in t.lower()]
        time.sleep(1)
        if not hits: continue
        code, body = _get(api + 'action=query&prop=revisions&rvprop=content&rvslots=main&rvsection=0&redirects=1&titles='
                          + urllib.parse.quote(hits[0]), 30)
        time.sleep(1)
        try: wt = json.loads(body)['query']['pages'][0]['revisions'][0]['slots']['main']['content']
        except (ValueError, KeyError, IndexError): continue
        m = BIRTH.search(wt)
        if m: out[n] = {'title': hits[0], 'dob': f'{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}', 'text': wt.lower()}
    return out


def gap(a, b): return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


def log_conflicts(sport, rows):
    """rows: [{'key', 'name', 'team', 'dates': {src: dob}, 'used'}]; replaces this sport's list"""
    try: c = json.load(open(CONFLICTS))
    except (OSError, ValueError): c = {}
    c[sport] = sorted(rows, key=lambda r: r['key'])
    json.dump(c, open(CONFLICTS, 'w'), indent=1, ensure_ascii=False); open(CONFLICTS, 'a').write('\n')


def disagree(dates, tol=3):
    """dates: {src: dob}; True when any two are more than tol days apart (Tankathon is +-2)"""
    v = [d for d in dates.values() if d]
    return any(gap(a, b) > tol for a in v for b in v)
