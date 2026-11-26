# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Round 2 extras: CFB position mix (prereg form 6) and the returning-production / transfer sensitivity.
python3 sens.py -> sens.json"""
import json, os, sys
import numpy as np
import tests as T
sys.path.insert(0, os.path.join(T.ROOT, 'scripts'))
import names as N  # noqa: E402

ESPN = '/mnt/project-files/recruits/commit-distance/espn_classes'
out = {}

# ---- CFB position mix ---------------------------------------------------------------------------------------------
P, S, C = T.load('cfb')
QB = {'QB-DT', 'QB-PP', 'QB'}; LINE = {'OG', 'OT', 'OC', 'DE', 'DT'}
pos, hit, tot = {}, 0, 0
for c in T.CFG['cfb']['classes']:
    f = os.path.join(ESPN, f'cfb-{c}.json')
    if not os.path.exists(f): continue
    by = {}
    for x in json.load(open(f)):
        if x.get('status') in ('Signed', 'Verbal'): by.setdefault(N.key(x['name']), x['pos'])
    for t, ps in C.get(c, {}).items():
        q = l = 0.0
        for nm, rating, pts in ps:
            g = by.get(N.key(nm)); tot += 1; hit += g is not None
            if g in QB: q += pts
            elif g in LINE: l += pts
        pos[(t, c)] = [q, l]
out['pos_match'] = round(hit / tot, 3)
rows = T.rows_of('cfb', S, C, r2=True)
for r in rows: r['pos'] = pos.get((r['t'], r['c']), [0.0, 0.0])
res = T.compare(rows, {'position mix': ([T.f_pos], ['-'])})
b = T.ols(T.X_of(rows, T.f_pos), np.array([r['y'] for r in rows]))
out['cfb_position'] = {**res['forms']['position mix'], 'n': res['n'], 'base_rmse': res['base_rmse'], 'w_plain_qb_line': [round(float(v), 5) for v in b[-3:]]}
print('position', out['pos_match'], out['cfb_position'])

# ---- returning production and transfers, first season after signing ------------------------------------------------
# Outcome = season C+1 only, controls from that season: its returners were on the roster before the class arrived
# (CBB) or carry one freshman season of it (CFB). Later seasons' returning value includes the class itself (a mediator,
# not a control), so the three-season outcome is not used here.
F = json.load(open(os.path.join(T.ROOT, 'scripts', 'data', 'cfb_roster_feats.json')))['feats']
def cfb_x(t, c):
    v = [F.get(str(c + k), {}).get(t) for k in (1,)]
    if any(x is None for x in v): return None
    return [float(np.mean([x[k] for x in v])) for k in ('offRet', 'qbRet', 'offIn')]
PB, SB, CB = T.load('cbb')
def cbb_x(t, c):
    v = [PB['prior'].get(str(c + k), {}).get(t) for k in (1,)]
    if any(x is None or x.get('ret') is None or x.get('tr') is None for x in v): return None
    return [float(np.mean([x[k] for x in v])) for k in ('ret', 'tr')]
for sp, (S_, C_, fx) in {'cfb': (S, C, cfb_x), 'cbb': (SB, CB, cbb_x)}.items():
    cfg = T.CFG[sp]
    for nm, cls in (('all', range(min(cfg['classes']), cfg['last'])), ('NIL era', range(2021, cfg['last']))):
        rr = T.rows_of(sp, S_, C_, classes=cls, out=(1,), extra=fx, r2=True)
        if len(rr) < 100: continue
        w = T.weights(rr, cfg['live_k']); e = {'n': len(rr), 'classes': sorted(set(r['c'] for r in rr)), 'weights': w}
        if len(e['classes']) >= 4:
            cmp_ = T.compare(rr, T.family(sp, r2=True)); e['forms'] = {k: {'t': v['t'], 'd': v['d'], 'classes_up': v['classes_up']} for k, v in cmp_['forms'].items()}; e['base_rmse'] = cmp_['base_rmse']
        out[f'{sp} {nm}'] = e
        print(sp, nm, e['n'], e['classes'], 'top', w['top'], 'depth', w['depth'], 't_diff', w['t_diff'], e.get('forms'))
json.dump(out, open(os.path.join(T.HERE, 'sens.json'), 'w'), indent=1)
