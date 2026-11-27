"""PFN impact pages (ten positions, every season on the page) -> scripts/.cache/ctx27_cfb/pfn_<pos>.json. 2026 rows dropped (lockbox)."""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cfb_breakout as B  # noqa: E402

OUT = os.path.join(ROOT, 'scripts', '.cache', 'ctx27_cfb')
PAGES = dict(B.PAGES, OL='offensive-line', CB='cornerback', S='safety')
os.makedirs(OUT, exist_ok=True)
for g, slug in PAGES.items():
    f = os.path.join(OUT, f'pfn_{g}.json')
    if os.path.exists(f):
        continue
    req = urllib.request.Request(f'https://www.profootballnetwork.com/cfb-hq/impact-rankings/{slug}', headers={'User-Agent': B.UA})
    rows = [r for r in B.parse_pfn(urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')) if r.get('season', 0) <= 2025]
    json.dump(rows, open(f, 'w'))
    print(g, len(rows), sorted({r['season'] for r in rows}), flush=True)
    time.sleep(1)
