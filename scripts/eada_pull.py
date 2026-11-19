#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Men's basketball program finances from the US Department of Education's Equity in Athletics survey (public domain):
scripts/data/eada_mbb.json.gz, read by scripts/cbb_market_fit.py (coach pay model).

    python3 scripts/eada_pull.py              # the newest academic year not on file (a new one each April)
    python3 scripts/eada_pull.py 2014 2025    # academic years by their spring (2014 = 2013-14)

Source: ope.ed.gov/athletics, one zip an academic year (api/dataFiles/file?fileName=EADA_2024-2025.zip; 'EADA 2013-2014.zip'
with a space before 2016-17). Schools.xlsx has one row a school and sport; kept: NCAA Division I men's basketball total
expenses and revenue. School names map to the board's team names through scripts/data/eada_alias.json and the market
fit's team matcher; an unmatched school is printed.
"""
import gzip, io, json, os, re, sys, time, urllib.parse, urllib.request, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'data', 'eada_mbb.json.gz')
ALIAS = os.path.join(HERE, 'data', 'eada_alias.json')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
URL = 'https://ope.ed.gov/athletics/api/dataFiles/file?fileName='


def key(n):
    s = n.lower().strip()
    s = re.sub(r'-main campus$| main campus$', '', s)
    s = re.sub(r'^the ', '', s)
    s = re.sub(r'^university of ', '', s)
    s = re.sub(r' university$| college$', '', s)
    return s.replace(' state university', ' state').replace(' at ', ' ').replace('-', ' ')


def fetch(year):
    for name in (f'EADA_{year - 1}-{year}.zip', f'EADA {year - 1}-{year}.zip'):
        try:
            req = urllib.request.Request(URL + urllib.parse.quote(name), headers={'User-Agent': UA})
            b = urllib.request.urlopen(req, timeout=300).read()
        except Exception:  # noqa: BLE001
            b = b''
        time.sleep(2)
        if b[:2] == b'PK':
            return b
    return None


def rows_of(blob):
    import openpyxl
    zf = zipfile.ZipFile(io.BytesIO(blob))
    nm = [n for n in zf.namelist() if n.lower().endswith('schools.xlsx')][0]
    ws = openpyxl.load_workbook(io.BytesIO(zf.read(nm)), read_only=True).active
    it = ws.iter_rows(values_only=True)
    h = [str(c) for c in next(it)]
    ix = {k: h.index(k) for k in ('institution_name', 'classification_name', 'Sports', 'EXP_MEN', 'REV_MEN')}
    for r in it:
        cl = str(r[ix['classification_name']])
        if r[ix['Sports']] != 'Basketball' or 'NCAA Division I' not in cl or 'Division II' in cl:
            continue
        try:
            e = float(r[ix['EXP_MEN']] or 0)
        except (TypeError, ValueError):
            continue
        if e > 0:
            try: rev = float(r[ix['REV_MEN']] or 0)
            except (TypeError, ValueError): rev = 0.0
            yield r[ix['institution_name']], e, rev


def team_of(name, names, alias):
    import cbb_market_fit as M
    t = alias.get(name.lower().strip())
    if t in names:
        return t
    return M.match_team(key(name), names) or M.match_team(name, names)


def main():
    import cbb_market_fit as M
    try: out = json.load(gzip.open(OUT, 'rt'))
    except (OSError, ValueError): out = {}
    a = [int(x) for x in sys.argv[1:3]]
    years = range(a[0], (a[1] if len(a) > 1 else a[0]) + 1) if a else [max([int(y) for y in out] or [2013]) + 1]
    TS, _ = M.team_seasons()
    names = {t for (_, t) in TS}
    alias = json.load(open(ALIAS))
    for y in years:
        b = fetch(y)
        if not b:
            print(f'EADA {y - 1}-{str(y)[2:]}: no file'); continue
        d, miss = {}, []
        for nm, e, rev in rows_of(b):
            t = team_of(nm, names, alias)
            if t: d[t] = [round(e), round(rev)]
            else: miss.append(nm)
        out[str(y)] = d
        print(f'EADA {y - 1}-{str(y)[2:]}: {len(d)} teams' + (f'; unmatched: {miss}' if miss else ''), flush=True)
    with gzip.open(OUT, 'wt') as f:
        json.dump(dict(sorted(out.items())), f, separators=(',', ':'))


if __name__ == '__main__':
    main()
