#!/usr/bin/env python3
"""The age tests in one file for Process and scripts/recruit_age.py: data/recruit_age_research.json. python3 pack.py
(after cbb_age.py, cbb_path_age.py, cfb_age.py; On3 coverage from scripts/.cache when the live classes are pulled)."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OUT = os.path.join(ROOT, 'data', 'recruit_age_research.json')
ld = lambda f: json.load(open(os.path.join(HERE, f)))
prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
cb, cp, cf = ld('cbb_age.json'), ld('cbb_path_age.json'), ld('cfb_age.json')
T = lambda d: {'gain': d['train']['gain'], 't': d['train']['t'], 'classes': d['train']['classes'], 'of': 8, 'n': d['train']['n'], 'fwd_t': d['fwd']['t']}
out = {
    'cbb': {'median': cb['median'], 'n': cb['n_exact'], 'bins': cb['bins'],
            'old': T(cb['A0 old vs rank only']), 'age_alone': T(cb['A0e agec vs rank, exact only']), 'swap': T(cb['A1 swap old -> agec']),
            'add': T(cb['A2 add agec']), 'young': T(cb['A3 add young']), 'hinge': T(cb['A4 hinges for old']), 'value': T(cb['B1 value + agec']),
            'path': cp},
    'cfb': {'median': cf['median'], 'n': cf['n'], 'rows': cf['rows'], 'bins': cf['bins'],
            'drafted': cf['given NFL entry: drafted + agec'], 'pick': cf['given NFL entry: log pick + agec'], 'top64': cf['given NFL entry: top-64 + agec'],
            'old_known': cf['age known (On3 or NFL): drafted + old']},
    'coverage': prev.get('coverage', {}),
}
for sp, d in (('cfb', 'cfb'), ('cbb', 'cbb')):
    for y in (2027, 2028, 2029):
        f = os.path.join(ROOT, 'scripts', '.cache', d, 'on3', f'{y}.json')
        if not os.path.exists(f): continue
        L = json.load(open(f)); rk = lambda r: r.get('consRank') or r.get('rk') or 9999
        top = [r for r in L if rk(r) <= 300]
        if top: out['coverage'].setdefault(sp, {})[str(y)] = {'n': len(top), 'age': sum(r.get('age') is not None for r in top)}
json.dump(out, open(OUT, 'w'), separators=(',', ':'))
print(json.dumps(out['coverage']))
