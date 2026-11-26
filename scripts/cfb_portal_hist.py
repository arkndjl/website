#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Past portal classes for the MOVES strip: CFBD's player/portal lists already in the cfbhist Actions cache
(scripts/.cache/cfb/hist/portal<year>.json, pulled by scripts/cfb_game_history.mjs) -> scripts/data/cfb_portal_hist.json.gz
= [[name, position, from, to or null, date, season], ...]. No CFBD call is made. Run by the `cfb portal history` workflow."""
import glob, gzip, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist')
OUT = os.path.join(ROOT, 'scripts', 'data', 'cfb_portal_hist.json.gz')


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(SRC, 'portal*.json'))):
        y = int(re.search(r'portal(\d{4})', f).group(1))
        try: d = json.load(open(f))
        except ValueError: continue
        d = d.get('data', d) if isinstance(d, dict) else d
        for r in d or []:
            n = ' '.join(x for x in (r.get('firstName'), r.get('lastName')) if x).strip()
            if n and r.get('origin'): rows.append([n, r.get('position'), r['origin'], r.get('destination') or None, (r.get('transferDate') or '')[:10] or None, r.get('season') or y])
        print(os.path.basename(f), len(d or []))
    if not rows: raise SystemExit('no portal files in the cfbhist cache: nothing written')
    rows.sort(key=lambda r: (r[5], r[4] or '', r[0]))
    with open(OUT, 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as fh:
        fh.write(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    print('wrote', OUT, len(rows), 'moves')


if __name__ == '__main__':
    main()
