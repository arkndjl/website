#!/usr/bin/env python3
"""One-off (Nov 28 2026): first-round picks of the 2022-26 NFL and NBA drafts whose college NIL agency is named by a source
dated before the draft process (declaring; Dec 1 for football, Mar 15 for basketball) or by a later source saying the agency
already had him in college. Pro agents signed at or after declaring are not counted. Sweep output (one row a pick, agency
null when no source names one) -> data/agency_pros.json rows with backfill = 1.

  python3 scripts/research/agencies_nov28/backfill_pros.py sweep1.json sweep2.json ...
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import agencies as A  # noqa: E402

rows, seen = [], set()
for f in sys.argv[1:]:
    for r in json.load(open(f)):
        if not r.get('agency') or (r['player'], r['year']) in seen: continue
        seen.add((r['player'], r['year']))
        sp = 'cfb' if r['league'] == 'nfl' else 'cbb'
        rows.append(dict(player=r['player'], school=r.get('college'), pos=None, agency=A.canon(r['agency']), conf=r.get('confidence') or 'medium',
                         round=1, pick=r['pick'], src=r.get('source'), source_date=r.get('source_date'), note=r.get('note'),
                         sport=sp, league=r['league'], year=r['year'], backfill=1))
p = os.path.join(ROOT, 'data', 'agency_pros.json')
pros = json.load(open(p))
pros['rows'] = [r for r in pros['rows'] if not r.get('backfill')] + sorted(rows, key=lambda r: (r['league'], r['year'], r['pick']))
json.dump(pros, open(p, 'w'), indent=1)
print(len(rows), 'backfilled picks;', sum(1 for r in rows if r['conf'] != 'low'), 'count (low confidence is shown, not counted)')
