#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Sources for the College Basketball market tabs (NIL, team builder, staff, coaching jobs, coach pay).

    node scripts/cbb_on3_nil.mjs          # On3 NIL 100 (needs Chromium) -> scripts/.cache/cbbmkt/on3_nil100.json
    python3 scripts/cbb_market_pull.py    # -> scripts/data/cbb_market_src.json.gz (committed; refresh by hand)

  On3 transfer portal, every entrant 2022-27 (On3's public API: name, position, from, to, On3 NIL valuation where
      On3 has one), and the NIL 100.
  USA Today men's basketball head coach pay: this year's list (public schools; private schools don't report), each
      school's pay by year, each listed coach's career page.
Pages are cached in scripts/.cache/cbbmkt (delete to refresh).
"""
import gzip
import hashlib
import html as H
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'cbbmkt')
OUT = os.path.join(ROOT, 'scripts', 'data', 'cbb_market_src.json.gz')
UT = 'https://sportsdata.usatoday.com/ncaa/salaries/mens-basketball'
ON3 = 'https://api.on3.com/public/rdb/v2/transfers/best-available?sportKey=2&year={y}&orderBy=Industry&page={p}'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
os.makedirs(CACHE, exist_ok=True)
S = requests.Session(); S.headers['User-Agent'] = UA
FRESH = set(sys.argv[1:])     # e.g. "portal2027" re-pulls the live portal year


def get(url, kind='json', fresh=False):
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ('.json' if kind == 'json' else '.html'))
    if os.path.exists(f) and not fresh:
        with open(f) as h:
            return json.load(h) if kind == 'json' else h.read()
    v = None
    for i in range(5):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404:
                break
            r.raise_for_status()
            v = r.json() if kind == 'json' else r.text
            break
        except Exception:
            time.sleep(1 + 2 * i)
    if v is not None:
        with open(f, 'w') as h:
            json.dump(v, h) if kind == 'json' else h.write(v)
    return v


def money(s):
    s = re.sub(r'[^0-9]', '', s or '')
    return int(s) if s else None


def table(page):
    out = []
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', page or '', re.S)[1:]:
        cells = [H.unescape(re.sub('<[^>]+>', '', c)).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)]
        out.append((cells, re.findall(r'href="([^"]+)"', r)))
    return out


def ht_in(h):
    m = re.match(r"(\d+)-(\d+)", str(h or ''))
    return int(m[1]) * 12 + int(m[2]) if m else None


def portal(y):
    rows, pages, p = [], 1, 1
    live = y >= 2027
    while p <= pages:
        d = get(ON3.format(y=y, p=p), fresh=live and f'portal{y}' in FRESH)
        if not d:
            break
        pages = (d.get('pagination') or {}).get('pageCount') or 1
        for x in d.get('list') or []:
            pl, st, org = x.get('player') or {}, x.get('status') or {}, x.get('organization') or {}
            to = st.get('committedAsset') or {}
            nv = x.get('nilValue') or {}
            rows.append({'name': pl.get('fullName'), 'pos': (pl.get('position') or {}).get('abbreviation') if isinstance(pl.get('position'), dict) else pl.get('position'),
                         'ht': ht_in(pl.get('height')) if not isinstance(pl.get('height'), (int, float)) else pl.get('height'),
                         'from': org.get('name'), 'fromFull': org.get('fullName'), 'to': to.get('name'), 'toFull': to.get('fullName'),
                         'val': nv.get('totalValue') or nv.get('valuation'), 'entered': (st.get('transferEntered') or '')[:10] or None,
                         'type': st.get('type'), 'draft': bool(st.get('draft')),
                         'rating': (x.get('transferRating') or {}).get('rating') if isinstance(x.get('transferRating'), dict) else None})
        p += 1
        time.sleep(0.2)
    return rows


def usat():
    lst = []
    for cells, hrefs in table(get(f'{UT}/coach', 'html')):
        cid = next((h.rsplit('/', 1)[1] for h in hrefs if re.search(r'/coach/\d+$', h)), None)
        sid = next((h.rsplit('/', 1)[1] for h in hrefs if '/coach/team/' in h), None)
        if not sid or len(cells) < 5:
            continue
        lst.append({'cid': cid, 'sid': sid, 'name': cells[1], 'school': cells[2], 'pay': money(cells[3]), 'conf': cells[4],
                    'buyout': money(cells[9]) if len(cells) > 9 else None, 'estimated': '*' in cells[3]})
    schools, careers = {}, {}
    for r in lst:
        schools[r['sid']] = [[int(c[0]), next((h.rsplit('/', 1)[1] for h in hr if re.search(r'/coach/\d+$', h)), None), c[1], money(c[2])]
                             for c, hr in table(get(f"{UT}/coach/team/{r['sid']}", 'html')) if c and c[0].isdigit()]
    cids = {r['cid'] for r in lst} | {x[1] for v in schools.values() for x in v if x[1]}
    for cid in sorted(cids):
        careers[cid] = [[int(c[0]), c[1], c[2], money(c[3])] for c, _ in table(get(f'{UT}/coach/{cid}', 'html')) if c and c[0].isdigit()]
    names = {}
    for v in schools.values():
        for y, cid, n, _ in v:
            if cid:
                names[cid] = n
    return {'list': lst, 'schools': schools, 'careers': careers, 'names': names}


def main():
    nil100 = []
    f = os.path.join(CACHE, 'on3_nil100.json')
    if os.path.exists(f):
        nil100 = json.load(open(f)).get('nil100', [])
    out = {'asof': time.strftime('%Y-%m-%d'), 'on3': {'nil100': nil100, 'portal': {}}, 'pay': usat()}
    for y in range(2022, 2028):
        out['on3']['portal'][str(y)] = portal(y)
        P = out['on3']['portal'][str(y)]
        print(y, len(P), 'valued', sum(1 for x in P if x['val']), 'landed', sum(1 for x in P if x['to']))
    print('pay', len(out['pay']['list']), 'schools', len(out['pay']['schools']), 'careers', len(out['pay']['careers']), 'nil100', len(nil100))
    with gzip.open(OUT, 'wt') as h:
        json.dump(out, h, separators=(',', ':'))


if __name__ == '__main__':
    main()
