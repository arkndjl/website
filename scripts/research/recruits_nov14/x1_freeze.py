# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""X1 (pre-registered): On3's prediction-machine leaders for the uncommitted 2027 football and basketball recruits,
frozen as of the run date in scripts/data/ledger/recruit_rpm_2027.json, beside the site's own lean
(data/recruit_commit_leans.json) where one exists. Scored after the February 2027 signing day: top-1 hit and log loss
of each against where he signed. No history exists to backtest the machine (a committed recruit shows the answer)."""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
out = {'frozen': datetime.date.today().isoformat(), 'class': 2027, 'football': [], 'basketball': []}
for sport, f in (('football', 'cfb'), ('basketball', 'cbb')):
    p = os.path.join(ROOT, 'scripts', '.cache', f, 'on3', '2027.json')
    if not os.path.exists(p): print('missing', p); continue
    for o in json.load(open(p)):
        if o.get('team') or not o.get('rpm'): continue
        out[sport].append([o['key'], o['name'], o.get('state'), o.get('consRank'), o['rpm']])
# the site's own lean for every uncommitted 2027 recruit (scripts/recruit_commit_fit.py, stored models): score set 'list'
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import recruit_commit_fit as F   # noqa: E402
spec = json.load(open(F.OUT)); out['leans'] = {}
for sp in ('cfb', 'cbb'):
    loc, cls = F.load(sp)
    _, lv = F.live(sp, loc, cls, spec[sp], refit=False)
    out['leans'][sp] = [[x['name'], x['st'], x['set'], x['lean']] for x in lv if x['year'] == 2027]
os.makedirs(os.path.join(ROOT, 'scripts', 'data', 'ledger'), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, 'scripts', 'data', 'ledger', 'recruit_rpm_2027.json'), 'w'), separators=(',', ':'))
print({k: len(v) for k, v in out.items() if isinstance(v, list)}, {k: len(v) for k, v in out['leans'].items()})
