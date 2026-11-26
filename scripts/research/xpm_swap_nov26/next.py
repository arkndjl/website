#!/usr/bin/env python3
"""Next (scripts/cbb_next_research.py M2: next-season value at 31 games, returners + D-I transfers, walk-forward 2016-26).
Targets: T0 = (BPM + 2) x min% (the shipped one), T1 = (rXPM + 1.4) x min% (the value the board shows since Nov 26).
Inputs: last-season rate in the roster row = BPM | pXPM core | pXPM board (point in time, common.py); this-season value and
BPM-over-position / OBPM = BPM based | rXPM based.  -> next.json"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import cbb_roster as R, cbb_next_research as NR
from cbb_next import POSMAP
f = R.f; K = 31 * .68
by = R.load_seasons(); ts = R.team_strength(by)
R.XPM.pxpm_of = lambda pid, year: None
val = lambda rate, mp, rep: (rate - rep) * mp / 100 * K
G = lambda r, pid, y, k: C.get(pid, y, k, f(r['bpm'], -2.0))


def posmeans(key):
    out = {}
    for y, rows in by.items():
        acc = defaultdict(lambda: [0.0, 0.0])
        for pid, r in rows.items():
            m, b = f(r['min_per'], 0), (f(r['bpm']) if key == 'bpm' else C.get(pid, y, 'xpm', f(r['bpm'])))
            if m >= 10 and b is not None: a = acc[POSMAP.get(r['role'], 'F')]; a[0] += m * b; a[1] += m
        out[y] = {p: a[0] / a[1] for p, a in acc.items()}
    return out
PM = {k: posmeans(k) for k in ('bpm', 'xpm')}


def rows_for(rate, desc):
    """rate: None (BPM) | 'px' | 'px2' in the roster row; desc: 'bpm' | 'xpm' for the value / position / offence inputs"""
    rows = defaultdict(list)
    for y in sorted(by):
        if y - 1 not in by: continue
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            k = R.kind(r, p, h)
            if k not in ('ret', 'tr'): continue
            p = dict(p); p['pxpm'] = C.get(pid, y - 1, rate) if rate else None
            x = R.xrow(k, r, p, ts, y); mp = f(r['min_per'], 0)
            b0 = f(p['bpm'], -2.0); bx = G(p, pid, y - 1, 'xpm'); mp0 = f(p['min_per'], 0)
            a = f(p.get('age'), 21.0)
            if desc == 'bpm': cur, d = val(b0, mp0, -2.0), [b0 - PM['bpm'][y - 1].get(POSMAP.get(p['role'], 'F'), 0.0), f(p.get('obpm'), 0.0)]
            else: cur, d = val(bx, mp0, -1.4), [bx - PM['xpm'][y - 1].get(POSMAP.get(p['role'], 'F'), 0.0), C.get(pid, y - 1, 'oxpm', f(p.get('obpm'), 0.0))]
            e = [a - 21, (a - 21) ** 2, min(f(p.get('seasons'), 2), 6) - 2, d[0], d[1], f(p.get('usg'), 18.0) - 18, f(p.get('hti'), 78) - 78]
            rows[y].append({'pid': pid, 'X': x + [cur] + e, 'T0': val(f(r['bpm'], -2.0), mp, -2.0), 'T1': val(G(r, pid, y, 'xpm'), mp, -1.4)})
    return rows


def walk(rows, tgt, fit_tgt=None):
    out = {}
    for y in range(2016, 2027):
        tr = [q for yy in rows if yy < y for q in rows[yy]]
        c = NR.ols([q['X'] for q in tr], [q[fit_tgt or tgt] for q in tr])
        for q in rows[y]: out[(y, q['pid'])] = (float(np.dot(c, q['X'])) - q[tgt]) ** 2
    return out


V = {'base (BPM row, BPM value)': (None, 'bpm'), 'pXPM core row': ('px', 'bpm'), 'pXPM board row': ('px2', 'bpm'), 'rXPM value inputs': (None, 'xpm'),
     'pXPM core row + rXPM value': ('px', 'xpm'), 'pXPM board row + rXPM value': ('px2', 'xpm')}
RW = {n: rows_for(*v) for n, v in V.items()}
out = {}
for tgt in ('T0', 'T1'):
    E = {n: walk(RW[n], tgt) for n in V}; ks = sorted(E['base (BPM row, BPM value)'])
    b = np.array([E['base (BPM row, BPM value)'][k] for k in ks]); out[tgt] = {}
    for n in V:
        e = np.array([E[n][k] for k in ks]); ys = sorted({k[0] for k in ks})
        won = sum(1 for y in ys if np.mean([E[n][k] for k in ks if k[0] == y]) < np.mean([E['base (BPM row, BPM value)'][k] for k in ks if k[0] == y]))
        out[tgt][n] = {'n': len(ks), 'rmse': round(float(np.sqrt(e.mean())), 4), 't': round(C.tstat(b - e), 2), 'seasons': f'{won}/{len(ys)}'}
        print(tgt, n, out[tgt][n], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'next.json'), 'w'), indent=1)
