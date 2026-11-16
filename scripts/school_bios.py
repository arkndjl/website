#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Birth dates from schools' own athletics roster bios ("Born August 13, 2005 ...", "Birthdate: 05/12/2004").

    python3 scripts/school_bios.py cbb [--max 600]    # look up board players without a day-precise date
    python3 scripts/school_bios.py cfb [--max 600]

Each school's athletics site comes from Wikidata (official website, P856, of the item found by entity search for
ESPN's team name: "St. Bonaventure Bonnies" -> gobonnies.com). Its roster page (Sidearm /sports/<sport>/roster, the
layout most schools use) lists each player's bio link; a bio is read only for a board player whose name key
(scripts/names.py) matches the link's slug. Bios are plain public pages; every site's robots.txt is read first and
honored, one request per site at a time, a second apart, under a generic UA. Results are cached in
scripts/data/school_bios_<sport>.json (sites 60 days, roster links 7, bios 30 days a miss; a site that shows a bot
wall is left alone until its roster is due again) and returned to the caller as
{'<name key>|<team>': {'dob', 'url'}}. Most D-I bios carry no birth date; the ones that do are exact.
"""
import concurrent.futures as cf, datetime as dt, json, os, re, subprocess, sys, time, urllib.parse, urllib.robotparser
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as N

ROOT = os.path.dirname(HERE)
UA = 'arkboard-research/1.0 (+https://arkndjl.net)'
SPORT = {'cbb': ('basketball/mens-college-basketball', 'mens-basketball', 'static/data/cbb-all.json'),
         'cfb': ('football/college-football', 'football', 'static/data/cfb-all.json')}
MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December'
BORN = re.compile(r'\bBorn\b[^.<>]{0,80}?\b(' + MONTHS + r')\.?\s+(\d{1,2}),?\s+((?:19|20)\d\d)')
BDAY = re.compile(r'Birth\s?date\W{0,20}(\d{1,2})/(\d{1,2})/((?:19|20)\d\d)', re.I)


def get(url, timeout=30, ua=UA):
    r = subprocess.run(['curl', '-sL', '-m', str(timeout)] + (['-A', ua] if ua else []) + ['-w', '\n%{http_code}', url],
                       capture_output=True, text=True)
    body, _, code = r.stdout.rpartition('\n')
    return (int(code) if code.isdigit() else 0), body


def cache_path(sport): return os.path.join(HERE, 'data', f'school_bios_{sport}.json')


def load(sport):
    try: C = json.load(open(cache_path(sport)))
    except (OSError, ValueError): C = {}
    for k in ('sites', 'rosters', 'bios'): C.setdefault(k, {})
    return C


def espn_teams(sport):
    out = {}
    for g in ([50] if sport == 'cbb' else [80, 81]):   # D-I; FBS and FCS
        code, body = get(f'https://site.api.espn.com/apis/site/v2/sports/{SPORT[sport][0]}/teams?limit=1000&groups={g}', ua=None)   # ESPN refuses UAs with a URL
        try: out.update({t['team']['id']: t['team']['displayName'] for t in json.loads(body)['sports'][0]['leagues'][0]['teams']})
        except (ValueError, KeyError, IndexError): pass
    return out


def sites_for(names):
    """ESPN team name -> athletics host, from Wikidata items whose label starts with the name"""
    out = {}
    for i in range(0, len(names), 30):
        vals = ' '.join(json.dumps(n) for n in names[i:i + 30])
        q = f'''SELECT ?name ?lab ?site WHERE {{ VALUES ?name {{ {vals} }}
          SERVICE wikibase:mwapi {{ bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "EntitySearch";
            mwapi:search ?name; mwapi:language "en". ?p wikibase:apiOutputItem mwapi:item. }}
          ?p wdt:P856 ?site; rdfs:label ?lab FILTER(lang(?lab)="en") }}'''
        for wait in (0, 30, 90):
            time.sleep(wait)
            code, body = get('https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(q), 90)
            if code != 429: break
        hosts = {}
        try:
            for b in json.loads(body)['results']['bindings']:
                n, lab = b['name']['value'], b['lab']['value']
                if not lab.lower().startswith(n.lower()): continue
                h = urllib.parse.urlparse(b['site']['value']).netloc.lower().removeprefix('www.')
                if h: hosts.setdefault(n, {}).setdefault(h, 0); hosts[n][h] += 1
        except (ValueError, KeyError):
            print('wikidata sites batch failed', i, code)
        for n, c in hosts.items(): out[n] = max(c.items(), key=lambda kv: kv[1])[0]
        time.sleep(1)
    return out


BLOCK = re.compile(r'Incapsula|_Incapsula_Resource|Just a moment\.\.\.|cf-chl|captcha', re.I)


def slug_key(u):
    m = re.search(r'/roster/([a-z0-9-]+)/\d+', u)
    return N.key(m.group(1).replace('-', ' ')) if m else None


def parse_dob(html):
    text = re.sub(r'<[^>]+>', ' ', html)
    m = BORN.search(text)
    if m:
        mo = MONTHS.split('|').index(m[1]) + 1
        return f'{m[3]}-{mo:02d}-{int(m[2]):02d}'
    m = BDAY.search(text)
    if m and 1 <= int(m[1]) <= 12 and 1 <= int(m[2]) <= 31: return f'{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}'
    return None


def site_job(host, path, want, C, today, budget):
    """one school: its roster links (cached 7 days), then the bios of the wanted players not read in the last 30 days.
    Returns ({key: {'dob', 'url'}}, new bio cache rows, status)"""
    ros = C['rosters'].get(host)
    rp = None
    def allowed(u):
        nonlocal rp
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            code, body = get(f'https://{host}/robots.txt', 20)
            rp.parse(body.splitlines() if code == 200 else [])
        return rp.can_fetch(UA, u)
    status = 'cached'
    if not ros or (today - dt.date.fromisoformat(ros['checked'])).days >= 7:
        roster = f'https://{host}/sports/{path}/roster'
        if not allowed(roster): status = 'robots'; links = {}
        else:
            code, html = get(roster)
            if BLOCK.search(html[:5000]): status, links = 'blocked', {}   # a bot wall: leave the site alone
            elif code != 200: status, links = 'roster', {}
            else:
                status, links = 'ok', {}
                for u in set(re.findall(r'/sports/' + re.escape(path) + r'/roster/[a-z0-9-]+/\d+', html)):
                    k = slug_key(u)
                    if k: links.setdefault(k, []).append(u)
                links = {k: v[0] for k, v in links.items() if len(v) == 1}
        ros = C['rosters'][host] = {'checked': today.isoformat(), 'status': status, 'links': links}
    if ros.get('status') in ('blocked', 'robots'): return {}, {}, ros['status']
    found, rows = {}, {}
    for key, name in want.items():
        u = ros['links'].get(N.key(name))
        if not u: continue
        url = f'https://{host}{u}'
        c = C['bios'].get(url)
        if c and (c.get('dob') or (today - dt.date.fromisoformat(c['checked'])).days < 30):
            if c.get('dob'): found[key] = {'dob': c['dob'], 'url': url}
            continue
        if budget[0] <= 0 or not allowed(url): continue
        time.sleep(1)
        budget[0] -= 1
        code, b = get(url)
        if BLOCK.search(b[:5000]):   # the site put up a bot wall: stop reading it
            ros['status'] = 'blocked'; break
        d = parse_dob(b) if code == 200 else None
        rows[url] = {'dob': d, 'checked': today.isoformat()}
        if d: found[key] = {'dob': d, 'url': url}
    return found, rows, status


def lookup(sport, want_rows, max_bios=600, today=None, threads=8):
    """want_rows: [(name, team, espn team id)] -> {'<name key>|<team>': {'dob', 'url'}}"""
    today = today or dt.date.today()
    C = load(sport)
    path = SPORT[sport][1]
    teams = espn_teams(sport)
    by_team = {}
    for name, team, tid in want_rows:
        if tid in teams: by_team.setdefault((tid, team), {})[f'{N.key(name)}|{team}'] = name
    need = sorted({teams[tid] for tid, _ in by_team if teams[tid] not in C['sites'] or
                   (today - dt.date.fromisoformat(C['sites'][teams[tid]]['checked'])).days >= 60})
    if need:
        got = sites_for(need)
        for n in need: C['sites'][n] = {'host': got.get(n), 'checked': today.isoformat()}
    budget = [max_bios]
    out, status = {}, {}
    jobs = {}
    with cf.ThreadPoolExecutor(threads) as ex:
        for (tid, team), want in by_team.items():
            host = C['sites'].get(teams[tid], {}).get('host')
            if host: jobs[ex.submit(site_job, host, path, want, C, today, budget)] = host
        for f in cf.as_completed(jobs):
            try: found, rows, st = f.result()
            except Exception as e: found, rows, st = {}, {}, f'error {e}'
            out.update(found); C['bios'].update(rows); status[st.split()[0]] = status.get(st.split()[0], 0) + 1
    json.dump(C, open(cache_path(sport), 'w'), indent=0, sort_keys=True); open(cache_path(sport), 'a').write('\n')
    print(f'school bios {sport}: {len(by_team)} teams, sites {status}, {max_bios - budget[0]} bios read, {len(out)} dates')
    return out


if __name__ == '__main__':
    sp = sys.argv[1]
    mx = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 600
    B = json.load(open(os.path.join(ROOT, SPORT[sp][2])))
    ci = {c: j for j, c in enumerate(B['cols'])}
    tid = lambda r: (re.search(r'/(\d+)\.png', r[ci['logo']] or '') or [None, None])[1]
    rows = [(r[ci['name']], r[ci['team']], tid(r)) for r in B['rows'] if r[ci['age']] is None]
    res = lookup(sp, rows, mx)
    print(json.dumps(dict(list(res.items())[:10]), indent=0))
