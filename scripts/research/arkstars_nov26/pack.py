# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""data/arkstars_research.json for Process (scripts/library_glossary.py): the top-tier tests' numbers, from cfb_top.json
and cbb_top.json as the runs wrote them."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
f = json.load(open(os.path.join(HERE, 'cfb_top.json'))); b = json.load(open(os.path.join(HERE, 'cbb_top.json')))
t = lambda e: {k: e[k] for k in ('gain', 'won', 'forward', 'pass') if k in e} | {'t': e.get('tSchool', e.get('t')), 'p': round(e['p'], 4)}
fl, bl = f['line'], b['line']
out = {'asof': '2026-11-26',
       'cfb': {'classes': [2011, 2021], 'forwardClass': 2022, 'pool': f['n'], 'hits': f['hits'], 'E1': t(f['E1']), 'E3': t(f['E3']),
               'top3': {'index': f['E1']['top3'][0], 'elite': f['E1']['top3'][1], 'industry': f['rates']['industryTop3']},
               'top6': {'index': f['E1']['top6'][0], 'elite': f['E1']['top6'][1], 'industry': f['rates']['industryTop6']},
               'tier': fl['new'], 'before': fl['shipped'], 'plain': fl['plainUnderNew'], 'forward': fl['forward']['byClass']['2022'], 'calibration': fl['calibration']},
       'cbb': {'classes': [2009, 2016], 'forwardClasses': [2017, 2020], 'pool': b['n'], 'hits': b['hits'], 'B3': t(b['B3']),
               'tier': bl['shipped'], 'plain': bl['plainUnderShipped'], 'rule': {'line': bl['lineScore'], **bl['new']}, 'between': b['between'], 'tierR2': b['tierR2'],
               'forward': {'tier': bl['forward']['shipped'], 'rule': bl['forward']['new']}, 'byPlace': b['byPlace']}}
json.dump(out, open(os.path.join(ROOT, 'data', 'arkstars_research.json'), 'w'), indent=1)
print(json.dumps(out)[:600])
