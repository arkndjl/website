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
  conflict(...)        two dates more than `tol` days apart are logged to data/dob_conflicts_<sport>.json.

RealGM, Proballers, EliteProspects and On3 answer bots with a Cloudflare challenge or disallow AI crawlers in
robots.txt: they are not fetched; a date read off one of them by hand goes in the overrides file with its URL.
No personal data goes out in a request: names and sport keywords only, under a generic UA.
"""
import datetime as dt, json, os, re, subprocess, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OVERRIDES = os.path.join(ROOT, 'data', 'dob_overrides.json')
CONFLICTS = os.path.join(ROOT, 'data', 'dob_conflicts_{sport}.json')
UA = 'arkboard-research/1.0 (+https://arkndjl.net)'
# a college Sports Reference player id: the item is a US college player of that sport even when it lists no team
SR = {'basketball': 'P3696', 'football': 'P3697'}
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
    """name -> [{'qid', 'dob', 'label', 'teams' (lowercase labels joined by |), 'nat', 'sr' (college Sports Reference
    id, or ''), 'espn' (ESPN college football id, or '')}], day-precision dates only.
    Each name goes through Wikidata's own entity search (run inside the SPARQL call: labels, aliases, accents
    folded, so "Roko Prkacin" finds "Roko Prkačin"); a hit counts only when its English label has the same name key
    (scripts/names.py) as ours."""
    import names as N
    out = {}
    for i in range(0, len(names), batch):
        vals = ' '.join(json.dumps(n) for n in names[i:i + batch])
        q = f'''SELECT ?name ?p ?lab ?dob (GROUP_CONCAT(DISTINCT ?tl; separator="|") AS ?teams)
          (GROUP_CONCAT(DISTINCT ?cl; separator="|") AS ?nat) (SAMPLE(?sr0) AS ?sr) (SAMPLE(?es0) AS ?espn) WHERE {{
          VALUES ?name {{ {vals} }}
          SERVICE wikibase:mwapi {{ bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "EntitySearch";
            mwapi:search ?name; mwapi:language "en". ?p wikibase:apiOutputItem mwapi:item. }}
          ?p wdt:P106 wd:{OCC[occ]}; rdfs:label ?lab FILTER(lang(?lab)="en")
          ?p p:P569/psv:P569 [ wikibase:timeValue ?dob; wikibase:timePrecision 11 ].
          OPTIONAL {{ ?p wdt:P54|wdt:P69 ?t. ?t rdfs:label ?tl FILTER(lang(?tl)="en") }}
          OPTIONAL {{ ?p wdt:P27 ?c. ?c rdfs:label ?cl FILTER(lang(?cl)="en") }}
          OPTIONAL {{ ?p wdt:{SR.get(occ, 'P3696')} ?sr0 }} OPTIONAL {{ ?p wdt:P7262 ?es0 }} }} GROUP BY ?name ?p ?lab ?dob'''
        for wait in (0, 30, 90):   # a 429 asks for a pause: back off, then give the batch up for this run
            time.sleep(wait)
            code, body = _get('https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(q), 90)
            if code != 429: break
        try:
            for b in json.loads(body)['results']['bindings']:
                n, lab = b['name']['value'], b['lab']['value']
                if N.key(lab) != N.key(n): continue
                c = {'qid': b['p']['value'].rsplit('/', 1)[-1], 'dob': b['dob']['value'][:10], 'label': lab,
                     'teams': b.get('teams', {}).get('value', '').lower(), 'nat': b.get('nat', {}).get('value', ''),
                     'sr': b.get('sr', {}).get('value', ''), 'espn': b.get('espn', {}).get('value', '')}
                if all(x['qid'] != c['qid'] for x in out.get(n, [])): out.setdefault(n, []).append(c)
        except (ValueError, KeyError):
            print('wikidata batch failed', i, code)
        time.sleep(1)
    return out


def sr_players(occ='basketball', since=1998):
    """name key -> [{'qid', 'dob', 'label', 'teams', 'sr'}]: every Wikidata item with a college Sports Reference id for
    the sport and a day-precision birth date (one query; ~8,600 basketball, ~1,300 football). Many of these items
    list no team, which the per-name search above can't tie to a school; callers match them by name, class and
    birth year instead."""
    import names as N
    q = f'''SELECT ?p ?lab ?dob ?sr (GROUP_CONCAT(DISTINCT ?tl; separator="|") AS ?teams) WHERE {{
      ?p wdt:{SR[occ]} ?sr; rdfs:label ?lab FILTER(lang(?lab)="en")
      ?p p:P569/psv:P569 [ wikibase:timeValue ?dob; wikibase:timePrecision 11 ]. FILTER(YEAR(?dob) >= {since})
      OPTIONAL {{ ?p wdt:P54|wdt:P69 ?t. ?t rdfs:label ?tl FILTER(lang(?tl)="en") }} }} GROUP BY ?p ?lab ?dob ?sr'''
    for wait in (0, 30, 90):
        time.sleep(wait)
        code, body = _get('https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(q), 120)
        if code != 429: break
    out = {}
    try:
        for b in json.loads(body)['results']['bindings']:
            c = {'qid': b['p']['value'].rsplit('/', 1)[-1], 'dob': b['dob']['value'][:10], 'label': b['lab']['value'],
                 'teams': b.get('teams', {}).get('value', '').lower(), 'sr': b['sr']['value']}
            k = N.key(c['label'])
            if all(x['qid'] != c['qid'] for x in out.get(k, [])): out.setdefault(k, []).append(c)
    except (ValueError, KeyError):
        print('wikidata sports reference list failed', code)
    return out


CLASS_N = {'Fr': 0, 'So': 1, 'Jr': 2, 'Sr': 3, 'Gr': 4}


def fits_class(dob, cls, season, years=None):
    """a birth date that fits his class: age on Nov 1 of the season's first year from 17.3 (a true freshman) to 20.8,
    one more a class (a redshirt adds 1.5), and within a year of his Barttorvik birth year when there is one (`years`:
    set of years; Barttorvik's year-only stand-in is off by one now and then: Ethan Brown 2008, bio Nov 14, 2007)"""
    c = (cls or '').replace('RS-', '')
    if c not in CLASS_N: return False
    a = (dt.date(season, 11, 1) - dt.date.fromisoformat(dob)).days / 365.25
    lo, hi = 17.3 + CLASS_N[c], 20.8 + CLASS_N[c] + (1.5 if (cls or '').startswith('RS-') else 0)
    return lo <= a <= hi and (not years or any(abs(int(dob[:4]) - y) <= 1 for y in years))


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

# ---- English Wikipedia college player articles ------------------------------------------------------------------
# Many current players' articles carry no {{birth date}} template: the date is plain text ("Oct 28 2005"), month and
# year only ("January 2006"), or month and day in a hidden comment citing a team's birthday post ("<!-- October 9
# https://x.com/... -->"). wiki_birth() reads all of them, with the precision.
INFOBOX = {'football': 'Infobox college football player', 'basketball': 'Infobox basketball biography'}
MON = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
_M = r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?'
_TPL_TXT = re.compile(r'\{\{\s*birth[ _-]?date(?: and age)?\s*\|(?:\s*\w+\s*=[^|}]*\|)*\s*([^|}]+)', re.I)
_ISO = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_MDY = re.compile(_M + r'\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})', re.I)
_DMY = re.compile(r'(\d{1,2})\s+' + _M + r',?\s+(\d{4})', re.I)
_MY = re.compile(_M + r',?\s+(\d{4})', re.I)
_MD = re.compile(_M + r'\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!,?\s*\d{4})', re.I)
_BORN = re.compile("'''[^'\\n]+'''[^(\\n]{0,40}\\(born ([^)\\n]{3,40})\\)")


def parse_date(s):
    """free text -> (iso, precision) with precision 'day', 'month' (iso day set to the 15th) or 'md' (month and day,
    no year: iso year 0000), else None"""
    s = s or ''
    for rx, f in ((_ISO, lambda m: (m[1], m[2], m[3])), (_MDY, lambda m: (m[3], MON[m[1][:3].lower()], m[2])),
                  (_DMY, lambda m: (m[3], MON[m[2][:3].lower()], m[1]))):
        m = rx.search(s)
        if m:
            y, mo, d = (int(x) for x in f(m))
            if 1 <= mo <= 12 and 1 <= d <= 31: return f'{y:04d}-{mo:02d}-{d:02d}', 'day'
    m = _MY.search(s)
    if m: return f'{int(m[2]):04d}-{MON[m[1][:3].lower()]:02d}-15', 'month'
    m = _MD.search(s)
    if m and 1 <= int(m[2]) <= 31: return f'0000-{MON[m[1][:3].lower()]:02d}-{int(m[2]):02d}', 'md'
    return None


def wiki_birth(wt):
    """an article's birth date: the {{birth date}} template, else the infobox birth_date field as text (comments
    included), else '(born ...)' in the lead -> (iso, precision) or None"""
    m = BIRTH.search(wt)
    if m: return f'{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}', 'day'
    f = re.search(r'\|\s*birth_date\s*=(.*)', wt)
    if f:
        m = _TPL_TXT.search(f[1])
        r = parse_date(m[1] if m else f[1])
        if r: return r
    m = _BORN.search(wt)
    return parse_date(m[1]) if m else None


def first_college_year(wt):
    """the first year of his college career from the infobox college years ('(2024–present)'), or None"""
    f = re.search(r'\|\s*college\s*=(.*?)(?=\n\s*\||\n\}\})', wt, re.S)   # the value can run over several '*' lines
    ys = [int(y) for y in re.findall(r'\((\d{4})\s*[–-]', f[1] if f else '')]
    return min(ys) if ys else None


def enwiki_titles(occ='football'):
    """titles of every English Wikipedia article using the sport's college infobox (one SPARQL call through
    Wikidata's MWAPI generator, since the Wikimedia action API rate-limits cloud runners)"""
    q = f'''SELECT ?title WHERE {{ SERVICE wikibase:mwapi {{ bd:serviceParam wikibase:endpoint "en.wikipedia.org";
      wikibase:api "Generator"; mwapi:generator "embeddedin"; mwapi:geititle "Template:{INFOBOX[occ]}";
      mwapi:geinamespace "0"; mwapi:geilimit "max". ?title wikibase:apiOutput mwapi:title. }} }}'''
    for wait in (0, 30, 90):
        time.sleep(wait)
        code, body = _get('https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(q), 120)
        if code != 429: break
    try: return [b['title']['value'] for b in json.loads(body)['results']['bindings']]
    except (ValueError, KeyError):
        print('wikipedia title list failed', code); return []


def wiki_raw(title):
    """an article's wikitext (index.php?action=raw): '' when there is none, None when refused"""
    code, body = _get('https://en.wikipedia.org/w/index.php?action=raw&title=' + urllib.parse.quote(title.replace(' ', '_')), 30)
    return body if code == 200 else '' if code == 404 else None


def gap(a, b): return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


def log_conflicts(sport, rows):
    """rows: [{'key', 'why', 'dates', 'used', ...}] -> data/dob_conflicts_<sport>.json (one file a sport, so two board
    workflows never write the same file)"""
    p = CONFLICTS.format(sport=sport)
    json.dump(sorted(rows, key=lambda r: r['key']), open(p, 'w'), indent=1, ensure_ascii=False); open(p, 'a').write('\n')


def disagree(dates, tol=3):
    """dates: {src: dob}; True when any two are more than tol days apart (Tankathon is +-2)"""
    v = [d for d in dates.values() if d]
    return any(gap(a, b) > tol for a in v for b in v)
