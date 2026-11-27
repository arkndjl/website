"""T2: depth chart / backup grade (backup_watch.nba: 1/.5/.25, k 500 to -1.4) vs pXPM, on next-season box XPM"""
import json, os
import numpy as np
import common as C
import backup_watch as BW
K, REPL, W = BW.NBA_K, BW.NBA_REPL, BW.NBA_W
d, ws, ss, bk, o2, n2 = [], [], [], [], [], []
for y in range(2011, C.LAST):
    for pid, q in C.F[y + 1]['p'].items():
        if q['mp'] < 250 or pid not in C.F[y]['p']: continue
        num = den = 0.0
        for j, w in enumerate(W):
            r = C.F.get(y - j, {}).get('p', {}).get(pid)
            if r: num += w * r['mp'] * r['xpm']; den += w * r['mp']
        old = (num + K * REPL) / (den + K); new = C.pxpm(pid, y)
        o2.append((old - q['xpm']) ** 2); n2.append((new - q['xpm']) ** 2)
        d.append(o2[-1] - n2[-1]); ws.append(q['mp']); ss.append(y + 1); bk.append(C.F[y]['p'][pid]['mp'] < 1000)
d, ws, ss, bk, o2, n2 = map(np.array, (d, ws, ss, bk, o2, n2)); wd = d * ws / ws.mean()
res = {}
for lab, m in (('all', np.ones(len(d), bool)), ('backups (<1000 MP in n)', bk)):
    S = sorted(set(ss[m]))
    res[lab] = {'n': int(m.sum()), 'rmse': [round(float(np.sqrt(np.average(o2[m], weights=ws[m]))), 4), round(float(np.sqrt(np.average(n2[m], weights=ws[m]))), 4)],
                't': round(C.tstat(wd[m]), 2), 'seasons': f"{sum(wd[m & (ss == s)].mean() > 0 for s in S)}/{len(S)}"}
print(json.dumps(res, indent=1)); json.dump(res, open(os.path.join(C.HERE, 't2_depth.json'), 'w'), indent=1)
