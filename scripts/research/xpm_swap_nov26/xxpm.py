#!/usr/bin/env python3
"""xXPM: the board's xBPM (cbb_fit.xbpm_fit ridge) rebuilt on XPM. Walk-forward (fit on target seasons <= n, score pair n -> n + 1,
pairs 2012-25) on the metric-audit team harness (next-season team adjEM R2 from minutes actually played) + player r / RMSE.
  target: next-season BPM (xBPM) | next-season rXPM
  inputs: XB_RET | + pXPM board form (point in time) | + pXPM core
Newcomers (no pXPM): XB_NEW on BPM | on rXPM, scored on first-season players.   -> xxpm.json"""
import json, os, sys
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb')); sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import audit as A, cbb_data as D, cbb_fit as F
careers = json.load(open(os.path.join(D.CACHE, 'careers.json'))); F.set_context(careers)
rows, new = [], []
for c in careers:
    for i, s in enumerate(c['seasons']):
        if s['year'] < 2010: continue
        f = F.features(c, i); pid = str(c['pid']); e = (s['mp'] or 0) * (s['gp'] or 0)
        r = {'pid': pid, 'year': s['year'], 'f': f, 'bpm_now': s['bpm'], 'xpm_now': C.get(pid, s['year'], 'xpm', s['bpm']), 'mpt_now': e}
        if f['newcomer']: new.append(r); continue
        if i == 0: continue
        py = c['seasons'][i - 1]['year']; r['prev'] = py
        f['px2'] = C.get(pid, py, 'px2'); f['pxc'] = C.get(pid, py, 'px')
        if f['px2'] is None: f['px2'] = f['pxc'] = f.get('bpm3') if f.get('bpm3') is not None else f.get('bpm')
        rows.append(r)
print(len(rows), 'returner rows', len(new), 'newcomer rows', flush=True)


def wf(R, cands, tgt, ret=True):
    out = {}
    for n in A.PAIRS:
        tr = [dict(r, bpm_now=r[tgt]) for r in R if r['year'] <= n]
        m = F.xbpm_fit(tr, cands)
        te = [r for r in R if r['year'] == n + 1 and (not ret or r['prev'] == n)]
        Z = F.Std.__new__(F.Std); Z.m = np.array(m['mean']); Z.s = np.array(m['sd']); Z.clip = 4
        p = np.hstack([np.ones((len(te), 1)), Z(F.matrix(te, cands))]) @ np.array(m['w'])
        out[n] = {r['pid']: float(v) for r, v in zip(te, p)}
    return out


def prm(vn, R, key):
    se = w = 0.0; idx = {(r['pid'], r['year']): r for r in R}
    for n in A.PAIRS:
        for pid, x in vn[n].items():
            r = idx.get((pid, n + 1))
            if r and r['mpt_now'] >= A.MINN and r[key] is not None: se += r['mpt_now'] * (x - r[key]) ** 2; w += r['mpt_now']
    return round((se / w) ** .5, 4)


V = {'xBPM': (F.XB_RET, 'bpm_now'), 'xBPM + pXPM board': (F.XB_RET + ['px2'], 'bpm_now'), 'xBPM + pXPM core': (F.XB_RET + ['pxc'], 'bpm_now'),
     'rXPM target': (F.XB_RET, 'xpm_now'), 'rXPM target + pXPM board': (F.XB_RET + ['px2'], 'xpm_now')}
res, out = {}, {}
for nm, (cands, tgt) in V.items():
    vn = wf(rows, cands, tgt); _, _, sc = A.predict(lambda n: vn[n]); res[nm] = sc
    out[nm] = {'teamR2': sc['teamR2'], 'playerR_vsBPM': sc['playerR_vsBPM'], 'rmse_vs_BPM': prm(vn, rows, 'bpm_now'), 'rmse_vs_rXPM': prm(vn, rows, 'xpm_now')}
    if nm != 'xBPM':
        d = [sc['byPair'][n] - res['xBPM']['byPair'][n] for n in A.PAIRS]; t, p = A.paired_t(d)
        out[nm].update(pairsBetter=f'{int(sum(x > 0 for x in d))}/{len(d)}', t=t)
    print(nm, out[nm], flush=True)
# newcomers: per-player squared error on his first season, both targets, both models
out['newcomers'] = {}
vb, vx = wf(new, F.XB_NEW, 'bpm_now', False), wf(new, F.XB_NEW, 'xpm_now', False)
idx = {(r['pid'], r['year']): r for r in new}
for key in ('bpm_now', 'xpm_now'):
    d, ws = [], []
    for n in A.PAIRS:
        for pid in vb[n]:
            r = idx[(pid, n + 1)]
            if r['mpt_now'] >= A.MINN and r[key] is not None: d.append((vb[n][pid] - r[key]) ** 2 - (vx[n][pid] - r[key]) ** 2); ws.append(r['mpt_now'])
    out['newcomers']['scored on ' + key] = {'rmse': [prm(vb, new, key), prm(vx, new, key)], 't_rXPM_target_better': round(C.tstat(d), 2), 'n': len(d)}
print(out['newcomers'])
json.dump(out, open(os.path.join(C.HERE, 'xxpm.json'), 'w'), indent=1)

# whole roster (returners + newcomers on one harness): today's xBPM against xXPM (rXPM target, pXPM board in the returner inputs)
def both(rc, tgt):
    a, b = wf(rows, rc, tgt), wf(new, F.XB_NEW, tgt, False)
    return {n: {**b[n], **a[n]} for n in A.PAIRS}
W = {'xBPM (both groups)': both(F.XB_RET, 'bpm_now'), 'BPM target + pXPM board': both(F.XB_RET + ['px2'], 'bpm_now'), 'xXPM (rXPM target + pXPM board)': both(F.XB_RET + ['px2'], 'xpm_now')}
sc = {k: A.predict(lambda n: v[n])[2] for k, v in W.items()}; out['whole roster'] = {}
for k in W:
    out['whole roster'][k] = {'teamR2': sc[k]['teamR2'], 'playerR_vsBPM': sc[k]['playerR_vsBPM']}
    for ref in W:
        if ref == k or list(W).index(ref) > list(W).index(k): continue
        d = [sc[k]['byPair'][n] - sc[ref]['byPair'][n] for n in A.PAIRS]; t, p = A.paired_t(d)
        out['whole roster'][k]['vs ' + ref] = {'pairsBetter': f'{int(sum(x > 0 for x in d))}/{len(d)}', 't': t}
    print(k, out['whole roster'][k], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'xxpm.json'), 'w'), indent=1)
