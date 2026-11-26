#!/usr/bin/env python3
"""NBA mock conviction (scripts/cbb_mock.py fit_conv / lodo_rmse: leave one draft out, RMSE on career peak XPM over ln(slot),
drafts 2009-23; guard: redraft slot error not worse). Swaps in the kept columns:
  draft-season BPM -> rXPM, D-BPM -> D-rXPM (descriptive);  3-season BPM -> pXPM board | core (point in time)  -> mock.json"""
import json, math, os, sys
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import cbb_data as D, cbb_mock as M, cbb_conv_backtest as CB
CS = {c['name'] + '|' + str((c['nba'] or {}).get('draft')): c for c in json.load(open(os.path.join(D.CACHE, 'careers.json')))}
rows = CB.rows_with_targets(); tg = CB.impute(rows, ['age'])
for r in rows:
    r['y'] = tg(r); c = CS.get(r['name'] + '|' + str(r['year']))
    ss = [s for s in c['seasons'] if s['year'] <= r['year']] if c else []
    y, pid = (int(ss[-1]['year']), c['pid']) if ss else (None, None)
    for k, src in (('xpm', 'xpm'), ('dxpm', 'dxpm'), ('px', 'px'), ('px2', 'px2')):
        r['f'][k] = C.get(pid, y, src) if ss else None
        if r['f'][k] is None: r['f'][k] = r['f'].get({'xpm': 'bpm', 'dxpm': 'dbpm', 'px': 'bpm3', 'px2': 'bpm3'}[k])
    r['f']['x3'] = M.bpm3_of([dict(s, bpm=C.get(pid, s['year'], 'xpm', s.get('bpm'))) for s in ss]) if ss else r['f'].get('bpm3')
k0 = json.load(open(os.path.join(C.ROOT, 'scripts', 'data', 'cbb_mock_fit.json')))
k0 = (k0.get('conv') or k0).get('kept'); print('kept', k0)
r0, p0, e0 = M.lodo_rmse(rows, k0); out = {'kept': k0, 'rmse': round(r0, 4), 'slotErr': round(M.lodo_slot(rows, e0), 4)}
sw = lambda m: [m.get(k, k) for k in k0]
for nm, alt in (('rXPM for draft-season BPM / D-BPM', sw({'bpm': 'xpm', 'dbpm': 'dxpm'})), ('pXPM board for 3-season BPM', sw({'bpm3': 'px2'})),
                ('pXPM core for 3-season BPM', sw({'bpm3': 'px'})), ('pXPM board added', k0 + ['px2']), ('3-season rXPM for 3-season BPM', sw({'bpm3': 'x3'})), ('all three', sw({'bpm': 'xpm', 'dbpm': 'dxpm', 'bpm3': 'px2'}))):
    if alt == k0: out[nm] = 'no such column kept'; print(nm, out[nm]); continue
    r1, p1, e1 = M.lodo_rmse(rows, alt); d = e0 ** 2 - e1 ** 2
    out[nm] = {'cols': alt, 'rmse': round(r1, 4), 't': round(C.tstat(d), 2), 'drafts': f'{int(sum(p1[y] < p0[y] for y in p0))}/{len(p0)}', 'slotErr': round(M.lodo_slot(rows, e1), 4)}
    print(nm, out[nm], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'mock.json'), 'w'), indent=1)
