#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Past portal classes for the MOVES strip: CFBD's player/portal lists already in the cfbhist Actions cache
(scripts/.cache/cfb/hist/portal<year>.json, pulled by scripts/cfb_game_history.mjs) -> scripts/data/cfb_portal_hist.json.gz
= [[name, position, from, to or null, date, season], ...]. A past season in neither the cache nor the file already written is
pulled from CFBD once (one call a season, at most six; needs CFBD_API_KEY). Run by the `cfb portal history` workflow."""
import glob, gzip, json, os, re, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist')
OUT = os.path.join(ROOT, 'scripts', 'data', 'cfb_portal_hist.json.gz')


def season_rows(d, y):
    d = d.get('data', d) if isinstance(d, dict) else d
    out = []
    for r in d or []:
        n = ' '.join(x for x in (r.get('firstName'), r.get('lastName')) if x).strip()
        if n and r.get('origin'): out.append([n, r.get('position'), r['origin'], r.get('destination') or None, (r.get('transferDate') or '')[:10] or None, r.get('season') or y])
    return out


def main():
    by = {}
    if os.path.exists(OUT):
        for r in json.load(gzip.open(OUT, 'rt')): by.setdefault(int(r[5]), []).append(r)
    for f in sorted(glob.glob(os.path.join(SRC, 'portal*.json'))):
        y = int(re.search(r'portal(\d{4})', f).group(1))
        try: by[y] = season_rows(json.load(open(f)), y)
        except ValueError: continue
        print(os.path.basename(f), len(by[y]))
    cur = int(json.load(open(os.path.join(ROOT, 'data', 'cfb_portal.json'))).get('season') or 0)
    key = os.environ.get('CFBD_API_KEY')
    for y in [y for y in range(2021, cur) if not by.get(y)][:6]:
        if not key: print(y, 'not in the cache and no CFBD_API_KEY'); continue
        r = subprocess.run(['curl', '-sS', '-m', '60', '-H', 'Authorization: Bearer ' + key, '-H', 'accept: application/json',
                            f'https://api.collegefootballdata.com/player/portal?year={y}'], capture_output=True, text=True)
        try: by[y] = season_rows(json.loads(r.stdout), y)
        except ValueError: print(y, 'CFBD pull failed'); continue
        print(y, 'from CFBD', len(by[y]))
    rows = [r for y in sorted(by) for r in by[y]]
    if not rows: raise SystemExit('no portal files in the cfbhist cache: nothing written')
    rows.sort(key=lambda r: (r[5], r[4] or '', r[0]))
    with open(OUT, 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as fh:
        fh.write(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    print('wrote', OUT, len(rows), 'moves')


if __name__ == '__main__':
    main()
