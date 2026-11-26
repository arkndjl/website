#!/usr/bin/env python3
"""pXPM vs the board's xBPM (cbb_fit.xbpm_fit: projected BPM this season, ridge on XB_RET, returners) on the audit
harness, both walk-forward (xBPM refit on target seasons <= n for pair n; the shipped one is fit 2010-26 in sample).
Also xBPM with pXPM as one more input (cross-sport rule).  -> xbpm.json"""
import gzip, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb')); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import audit as A
import cbb_data as D
import cbb_fit as F
PX = {int(y): v for y, v in json.load(gzip.open(os.path.join(HERE, 'pxpm_loso.json.gz'), 'rt')).items()}
careers = json.load(open(os.path.join(D.CACHE, 'careers.json'))); F.set_context(careers)
rows = []
for c in careers:
    for i, s in enumerate(c['seasons']):
        if s['year'] < 2010 or i == 0: continue
        f = F.features(c, i)
        if f['newcomer']: continue
        q = PX.get(int(c['seasons'][i - 1]['year']), {}).get(str(c['pid'])); f['pxpm'] = q[0] + q[1] if q else None
        rows.append({'pid': str(c['pid']), 'year': s['year'], 'prev': c['seasons'][i - 1]['year'], 'f': f, 'bpm_now': s['bpm'], 'mpt_now': (s['mp'] or 0) * (s['gp'] or 0)})
print(len(rows), 'returner rows', flush=True)


def wf(cands):
    out = {}
    for n in A.PAIRS:
        m = F.xbpm_fit([r for r in rows if r['year'] <= n], cands)
        te = [r for r in rows if r['year'] == n + 1 and r['prev'] == n]
        Z = F.Std.__new__(F.Std); Z.m = np.array(m['mean']); Z.s = np.array(m['sd']); Z.clip = 4
        X = Z(F.matrix(te, cands)); p = np.hstack([np.ones((len(X), 1)), X]) @ np.array(m['w'])
        out[n] = {r['pid']: float(v) for r, v in zip(te, p)}
    return out


res = {}
_, _, base = A.predict(lambda n: A.vals(n, 'bpm'))
px = {n: {pid: v[0] + v[1] for pid, v in PX[n].items()} for n in A.PAIRS}
for nm, vn in (('xBPM (walk-forward)', wf(F.XB_RET)), ('xBPM + pXPM input', wf(F.XB_RET + ['pxpm'])), ('pXPM (LOSO file)', px)):
    _, _, sc = A.predict(lambda n: vn[n]); res[nm] = sc; res[nm + ' vn'] = vn
    print(nm, sc['teamR2'], sc['playerR_vsBPM'], flush=True)
out = {}
for a, b in (('pXPM (LOSO file)', 'xBPM (walk-forward)'), ('xBPM + pXPM input', 'xBPM (walk-forward)')):
    d = [res[a]['byPair'][n] - res[b]['byPair'][n] for n in A.PAIRS]; t, p = A.paired_t(d)
    out[f'{a} vs {b}'] = {'teamR2': [res[b]['teamR2'], res[a]['teamR2']], 'playerR_vsBPM': [res[b]['playerR_vsBPM'], res[a]['playerR_vsBPM']],
                          'pairsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': round(p, 5)}
# player RMSE on common players (300+ next minutes)
def rm(vn):
    se = w = 0.0
    for n in A.PAIRS:
        P1 = A.S[n + 1]['pl']
        for pid, x in vn[n].items():
            q = P1.get(pid)
            if q and q['e'] >= A.MINN and all(pid in res[k + ' vn'][n] for k in ('xBPM (walk-forward)', 'pXPM (LOSO file)')): se += q['e'] * (x - q['bpm']) ** 2; w += q['e']
    return round((se / w) ** .5, 4)
out['playerRMSE_common'] = {k: rm(res[k + ' vn']) for k in ('xBPM (walk-forward)', 'xBPM + pXPM input', 'pXPM (LOSO file)')}
print(json.dumps(out, indent=1)); json.dump(out, open(os.path.join(HERE, 'xbpm.json'), 'w'), indent=1)
