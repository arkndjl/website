"""T3b: XPM (proj) in season on the live prior vs the pXPM prior, against the rest-of-season XPM implied by the
harness's simulated partial seasons (the draws of nba_proj3y_research.inputs, shared by both arms).  -> t3b_proj.json"""
import json, math, os
import numpy as np
import common as C
import nba_proj3y_research as R

T3 = json.load(open(os.path.join(C.HERE, 't3_prior.json')))['cover']
rows = R.load()
for r in rows:
    v = C.pxpm(r['id'], r['S'] - 1); r['prior2'] = r['prior'] if v is None else v; r['k2'] = T3['new ' + r['g']]['k']
res = {}
for f in (0.1, 0.2, 0.35, 0.5, 0.75):
    rng = np.random.default_rng(20261127)
    ea, eb, ws, ss, ids = [], [], [], [], []
    for r in rows:
        for _ in range(R.DRAWS):
            cg = max(1, round(r['gp'] * f))
            mp = max(1.0, r['mp'] * cg / r['gp'] * math.exp(rng.normal(0, 0.25 * math.sqrt((1 - f) / f))))
            x = r['xpm'] + rng.normal() * math.sqrt(r['s2'] * max(1 / mp - 1 / r['mp'], 0))
            left = r['mp'] - mp
            if left < 100: continue
            rest = (r['xpm'] * r['mp'] - x * mp) / left
            pa = r['prior'] + (x - r['prior']) * mp / (r['k'] + mp); pb = r['prior2'] + (x - r['prior2']) * mp / (r['k2'] + mp)
            ea.append((pa - rest) ** 2); eb.append((pb - rest) ** 2); ws.append(left); ss.append(r['S']); ids.append(r['id'] + str(r['S']))
    ea, eb, ws, ss = map(np.array, (ea, eb, ws, ss)); S = sorted(set(ss))
    won = sum(np.average(eb[ss == c], weights=ws[ss == c]) < np.average(ea[ss == c], weights=ws[ss == c]) for c in S)
    res[str(f)] = {'n': len(set(ids)), 'rmse': [round(float(np.sqrt(np.average(ea, weights=ws))), 4), round(float(np.sqrt(np.average(eb, weights=ws))), 4)],
                   't': round(R.tstat(ws * (ea - eb), ids), 2), 'seasons': f'{won}/{len(S)}'}
    print(f, json.dumps(res[str(f)]), flush=True)
json.dump(res, open(os.path.join(C.HERE, 't3b_proj.json'), 'w'), indent=1)
