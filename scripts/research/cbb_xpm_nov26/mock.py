#!/usr/bin/env python3
"""Cross-sport input test: pXPM in the NBA mock's conviction fit (cbb_mock.fit_conv: LODO RMSE on career peak XPM over
ln(slot), drafts 2009-23, forward selection: keep if RMSE falls, 9+/15 drafts, redraft slot error not worse).
pXPM = draft-season (last college season) pXPM from pxpm_loso.json.gz.  -> mock.json"""
import gzip, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cbb_data as D
import cbb_mock as M
PX = {int(y): v for y, v in json.load(gzip.open(os.path.join(HERE, 'pxpm_loso.json.gz'), 'rt')).items()}
CS = {c['name'] + '|' + str((c['nba'] or {}).get('draft')): c for c in json.load(open(os.path.join(D.CACHE, 'careers.json')))}
_cr = M.conv_rows


def conv_rows(past, drafts=(2009, 2023)):
    rows = _cr(past, drafts)
    for r in rows:
        c = CS.get(r['name'] + '|' + str(r['year']))
        ss = [s for s in c['seasons'] if s['year'] <= r['year']] if c else []
        q = PX.get(int(ss[-1]['year']), {}).get(str(c['pid'])) if ss else None
        r['f']['pxpm'] = q[0] + q[1] if q else None
    return rows


M.conv_rows = conv_rows
past = M.past_boards()
base = M.fit_conv(past)
M.FEATS.append('pxpm'); M.LABEL['pxpm'] = 'pXPM, draft season'
new = M.fit_conv(past)
import cbb_conv_backtest as CB
rows = CB.rows_with_targets(); tg = CB.impute(rows, ['age'])
for r in rows: r['y'] = tg(r)
k0 = base['kept']; out = {'base': {k: base[k] for k in ('kept', 'rmse', 'rmseSlot', 'slotErr', 'years')},
                          'with pXPM offered': {k: new[k] for k in ('kept', 'rmse', 'slotErr', 'years')},
                          'singles': [s for s in new['singles'] if s['key'] in ('bpm', 'bpm3', 'pxpm')]}
r0, p0, e0 = M.lodo_rmse(rows, k0)
for nm, alt in (('pXPM for bpm3', [k if k != 'bpm3' else 'pxpm' for k in k0]), ('pXPM added', k0 + ['pxpm'])):
    if alt == k0: continue
    r1, p1, e1 = M.lodo_rmse(rows, alt); d = e0 ** 2 - e1 ** 2
    out[nm] = {'kept': alt, 'rmse': [round(r0, 4), round(r1, 4)], 'drafts': int(sum(p1[y] < p0[y] for y in p0)),
               't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'slotErr': [round(M.lodo_slot(rows, e0), 4), round(M.lodo_slot(rows, e1), 4)]}
print(json.dumps(out, indent=1)); json.dump(out, open(os.path.join(HERE, 'mock.json'), 'w'), indent=1)
