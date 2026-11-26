#!/usr/bin/env python3
"""Next, in-season grid (scripts/cbb_next_research.py partial: leave one season out at each season share f, seasons 2015-25).
Target = next-season value on rXPM, (rXPM + 1.4) x min%. History input: last season's 3-year BPM (shipped) | last season's
pXPM board form (point in time).  -> next_inseason.json"""
import gzip, json, os, sys
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import cbb_roster as R, cbb_next_research as NR
from cbb_next import pxrow, NX
f = R.f; by = R.load_seasons(); pm = NR.posmeans(by); LOG = os.path.join(C.ROOT, 'scripts', '.cache', 'cbb', 'advgames')
val = lambda rate, mp: (rate + 1.4) * mp / 100 * 31 * .68 * .01872
data = {v: {fr: {} for fr in NR.GRID} for v in ('b3', 'px2')}
for s in range(2015, 2026):
    games = [g for g in json.load(gzip.open(os.path.join(LOG, f'{s}.json.gz'))) if g[-1] == s]
    for fr in NR.GRID:
        td = NR.todate(games, fr) if fr > 0 else None; L = {'b3': [], 'px2': []}
        for pid, r in by[s].items():
            q = by[s + 1].get(pid)
            if q is None or not f(r['min_per']): continue
            t = td.get(pid) if td is not None else None
            if fr > 0 and t is None: continue
            y = val(C.get(pid, s + 1, 'xpm', f(q['bpm'], -2.0)), f(q['min_per'], 0)); prev = by[s - 1].get(pid) if s - 1 in by else None
            L['b3'].append((pxrow(r, t, prev, pm[s - 1]), y, pid))
            p2 = dict(prev, bpm3=C.get(pid, s - 1, 'px2', prev.get('bpm3'))) if prev is not None else None
            L['px2'].append((pxrow(r, t, p2, pm[s - 1]), y, pid))
        for v in L: data[v][fr][s] = L[v]
    print(s, flush=True)
seasons = sorted(data['b3'][1.0]); out = {}
for fr in NR.GRID:
    E = {}
    for v in data:
        e = {}
        for s in seasons:
            tr = [q for ss in seasons if ss != s for q in data[v][fr][ss]]; c = NR.ols([q[0] for q in tr], [q[1] for q in tr])
            for x, y, pid in data[v][fr][s]: e[(s, pid)] = (float(np.dot(c, x)) - y) ** 2
        E[v] = e
    ks = sorted(E['b3']); a = np.array([E['b3'][k] for k in ks]); b = np.array([E['px2'][k] for k in ks])
    won = sum(1 for s in seasons if np.mean([E['px2'][k] for k in ks if k[0] == s]) < np.mean([E['b3'][k] for k in ks if k[0] == s]))
    out[str(fr)] = {'n': len(ks), 'rmse': [round(float(np.sqrt(a.mean())), 4), round(float(np.sqrt(b.mean())), 4)], 't': round(C.tstat(a - b), 2), 'seasons': f'{won}/{len(seasons)}'}
    print(fr, out[str(fr)], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'next_inseason.json'), 'w'), indent=1)
