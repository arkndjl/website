"""T3: XPM (proj) prior (nba_xpm.prior_xpm) vs last season's pXPM, on season XPM; guard = held-out 80% cover after refit"""
import json, math, os
import numpy as np
import common as C
import nba_proj as NP
X = C.X
d, ws, ss, o2, n2 = [], [], [], [], []; rows = {'old': {'vet': {}, 'new': {}}, 'new': {'vet': {}, 'new': {}}}
for s in range(2013, C.LAST + 1):
    prior, old = X.prior_xpm(s), NP.past_mp(s)
    for pid, p in C.F[s]['p'].items():
        if p['mp'] < 50: continue
        a = prior(pid)[0]; b = C.pxpm(pid, s - 1); b = a if b is None else b
        g = 'vet' if old.get(pid, 0) >= NP.VET_MP else 'new'
        rows['old'][g].setdefault(s, []).append((p['mp'], p['xpm'] - a)); rows['new'][g].setdefault(s, []).append((p['mp'], p['xpm'] - b))
        o2.append((a - p['xpm']) ** 2); n2.append((b - p['xpm']) ** 2); d.append(o2[-1] - n2[-1]); ws.append(p['mp']); ss.append(s)
d, ws, ss = map(np.array, (d, ws, ss)); wd = d * ws / ws.mean(); S = sorted(set(ss))
res = {'n': len(d), 'rmse': [round(float(np.sqrt(np.average(o2, weights=ws))), 4), round(float(np.sqrt(np.average(n2, weights=ws))), 4)],
       't': round(C.tstat(wd), 2), 'seasons': f"{sum(wd[ss == s].mean() > 0 for s in S)}/{len(S)}", 'cover': {}}
for lab in ('old', 'new'):
    for g, by in rows[lab].items():
        cov = []
        for s, te in by.items():
            a, b = NP.lsq([r for k, v in by.items() if k != s for r in v])
            cov.append(sum(abs(e) < NP.Z80 * math.sqrt(max(a + b / m, 1e-9)) for m, e in te) / len(te))
        t2, s2 = NP.lsq([r for v in by.values() for r in v])
        res['cover'][f'{lab} {g}'] = {'cover80': round(float(np.mean(cov)), 3), 'min': round(min(cov), 3), 'max': round(max(cov), 3), 'tau2': round(t2, 3), 'k': round(s2 / t2)}
print(json.dumps(res, indent=1)); json.dump(res, open(os.path.join(C.HERE, 't3_prior.json'), 'w'), indent=1)
