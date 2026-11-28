# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Big five player wages from Salary Sport (salarysport.com), for the soccer market > wages tabs (scripts/payrolls.py soccer).

Salary Sport's robots.txt allows every path but /docs/club-accounts/ (`User-agent: *` ... `Disallow: /docs/club-accounts/`),
and the site has no terms of use (only a privacy policy). Pages are fetched one at a time, 3 seconds apart, with a
plain user agent; nothing behind a challenge. Figures are the site's basic-wage estimates in GBP (its own EUR toggle is
a fixed 1.2 rate, `RATES` in /enhance.js); wage_week_eur here uses the same 1.2 so the two read alike.

    python3 scripts/soccer_wages.py            # 2026-27 -> scripts/.cache/payrolls/soccer/wages_2027.json
    python3 scripts/soccer_wages.py --season 2024-25   # a past season (wages_2025.json)
"""
import argparse, datetime as dt, html, json, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'scripts', '.cache', 'payrolls', 'soccer')
BASE = 'https://salarysport.com'
LEAGUES = {'eng.1': 'premier-league', 'esp.1': 'la-liga', 'ger.1': 'bundesliga', 'ita.1': 'serie-a', 'fra.1': 'ligue-1'}
NOT_CLUB = {'finances', 'highest-paid', 'highest-paid-at-every-club', 'prize-money', 'shirt-prices', 'stadium-tours',
            'transfers', 'wages-by-age', 'managers', 'central-payments', 'backroom-staff', 'all-time-earners'}
EUR_PER_GBP = 1.2
DELAY = 3.0
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
MON = {m: i for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'], 1)}
_last = [0.0]


def get(path):
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    url = BASE + urllib.parse.quote(path, safe='/%.-_~')
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode('utf-8', 'replace')
    except Exception as e:
        print('  fail', path, e, file=sys.stderr)
        return ''


def clubs(slug):
    s = get(f'/football/{slug}/')
    out = []
    for c in re.findall(rf'href="/football/{slug}/([^/"]+)/"', s):
        c = html.unescape(urllib.parse.unquote(c))
        if c not in NOT_CLUB and c not in out:
            out.append(c)
    return out


def until(txt):
    m = re.match(r'([A-Z]{3})\s+(\d{4})', txt.strip())
    if not m or m.group(1) not in MON:
        return None
    mo, y = MON[m.group(1)], int(m.group(2))
    end = (dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1))
    return end.isoformat()


def parse(s):
    title = re.search(r'<title>(.*?)</title>', s, re.S)
    name = html.unescape(title.group(1)).split(' 20')[0].strip() if title else ''
    rows = []
    for tr in re.findall(r'<tr data-row (.*?)</tr>', s, re.S):
        a = dict(re.findall(r'data-([a-z]+)="([^"]*)"', tr.split('>', 1)[0]))
        tds = [html.unescape(re.sub(r'<[^>]+>', ' ', t)).strip() for t in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        tds = [re.sub(r'\s+', ' ', t) for t in tds]
        if 'weekly' not in a:
            continue
        wk = int(a['weekly'])
        rows.append({'n': html.unescape(a.get('name', '')), 'age': int(a['age']) if a.get('age', '').isdigit() else None,
                     'wage_week_gbp': wk, 'wage_year_gbp': int(a['yearly']) if a.get('yearly', '').isdigit() else wk * 52,
                     'wage_week_eur': round(wk * EUR_PER_GBP), 'pos': tds[5] if len(tds) > 5 else None,
                     'grp': a.get('group'), 'nat': tds[6] if len(tds) > 6 else None,
                     'until': until(tds[7]) if len(tds) > 7 else None, 'src': 'salarysport'})
    return name, rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', default='2026-27', help='YYYY-YY; the current season is the bare club page')
    ap.add_argument('--league', action='append', help='eng.1 ... (default all five)')
    a = ap.parse_args(argv)
    cur = a.season == '2026-27'
    end = int(a.season[:4]) + 1
    os.makedirs(OUT, exist_ok=True)
    fn = os.path.join(OUT, f'wages_{end}.json')
    res = {'_meta': {'src': BASE, 'season': a.season, 'got': dt.date.today().isoformat(), 'eur_per_gbp': EUR_PER_GBP,
                     'note': 'Salary Sport basic-wage estimates (GBP as published); eur = gbp x 1.2, the site\'s own rate'}}
    for lg in a.league or LEAGUES:
        slug = LEAGUES[lg]
        cs = clubs(slug)
        print(lg, len(cs), 'club pages', flush=True)
        got = {}
        for c in cs:
            path = f'/football/{slug}/{c}/' + ('' if cur else f'{a.season}/')
            name, rows = parse(get(path))
            if not rows:
                print('  empty', c, flush=True)
                continue
            got[c] = (name or c, rows)
        # alias slugs (alaves / deportivo-alaves) carry the same squad: keep the fuller page
        keep = {}
        for c, (name, rows) in sorted(got.items(), key=lambda kv: -len(kv[1][1])):
            ns = {r['n'] for r in rows}
            if any(len(ns & {r['n'] for r in k[1]}) >= 0.5 * len(ns) for k in keep.values()):
                print('  alias dropped', c, flush=True)
                continue
            keep[c] = (name, rows)
        res[lg] = {name: rows for name, rows in keep.values()}
        print(lg, len(res[lg]), 'clubs', sum(len(v) for v in res[lg].values()), 'players', flush=True)
    json.dump(res, open(fn, 'w'), ensure_ascii=False, indent=0)
    print('wrote', fn)
    return fn


if __name__ == '__main__':
    main()
