#!/usr/bin/env python3
"""One player's 2026-27 line game by game: Barttorvik's file against the line rebuilt from his games."""
import sys, os, json, gzip
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import cbb_data as D, cbb_live as L

NAME, TEAM = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ('Ethan Brown', 'Illinois')
games = json.load(gzip.open(os.path.join(D.CACHE, 'games', '2027.json.gz')))
off = {r['pid']: r for r in D.load_bt(2027)}
recon = json.load(open(L.LIVE_FIT))['recon']
C = L.C
by = defaultdict(list)
for g in games:
    by[str(g[C['pid']])].append(g)
pid = next(p for p, rs in by.items() if rs[0][C['name']] == NAME and rs[0][C['team']] == TEAM)
rs = sorted(by[pid], key=lambda g: g[C['date']])
o = off.get(pid)
print('official', {k: o.get(k) for k in ('gp', 'mp', 'bpm', 'obpm', 'dbpm', 'gbpm', 'ogbpm', 'dgbpm', 'porpag', 'ortg', 'usg')} if o else None)
for n in range(1, len(rs) + 1):
    a = L.summed(rs[:n], n)
    ln = L.line(a, recon, {})
    g = rs[n - 1]
    print(n, g[C['date']], 'rebuilt bpm %.2f obpm %.2f dbpm %.2f | summed gbpm %.2f ogb %.2f dgb %.2f | game obpm %s dbpm %s gbpm %s min %s'
          % (ln['bpm'], ln['obpm'], ln['dbpm'], a['gbpm'], a['ogb'], a['dgb'], g[C['obpm']], g[C['dbpm']], g[C['gbpm']], g[C['min']]))
