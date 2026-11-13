#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""K (prereg.md): does the model predict Novig's own line moves? Every tennis match with an archived Novig price,
Oct 27 - Nov 10 2026 (lockbox after), model chances from the committed data/tennis.json of the time."""
import json, subprocess, glob, math, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names
def lg(p): p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p / (1 - p))
# Novig archive: per market id, the price series before the listed start
mk = {}
for f in sorted(glob.glob(os.path.join(ROOT, 'scripts/data/odds_novig/tennis-*.jsonl'))):
    for line in open(f):
        x = json.loads(line)
        m = mk.setdefault(x['nid'], {'s': []})
        for k in ('a', 'b', 'lg', 'k'):
            if x.get(k): m[k] = x[k]
        if x.get('p') is not None and x['t'] < x['k'] and x['t'] <= '2026-11-10T23:59:59Z':
            m['s'].append((x['t'], x['p'], x.get('h'), x.get('vol') or 0))
mk = {k: v for k, v in mk.items() if v.get('a') and len(v['s']) >= 2 and v['k'] <= '2026-11-10T23:59:59Z'}
print('markets with 2+ pre-match prices and names:', len(mk))
# model chances over time from git history
cm = subprocess.run(['git', 'log', 'origin/main', '--since=2026-10-26', '--until=2026-11-11', '--format=%H %cI', '--', 'data/tennis.json'],
                    cwd=ROOT, capture_output=True, text=True).stdout.split('\n')
mod = {}        # (key a, key b, day) -> [(commit time, p of a)]
for line in cm:
    if not line.strip(): continue
    h, t = line.split()
    try:
        d = json.loads(subprocess.run(['git', 'show', f'{h}:data/tennis.json'], cwd=ROOT, capture_output=True, text=True).stdout)
    except ValueError:
        continue
    for g in d.get('matches', []):
        if g.get('state') != 'pre': continue
        mod.setdefault((names.key(g['a']['n']), names.key(g['b']['n']), g['tip'][:10]), []).append((d['asof'], g['p']))
print('model match-days:', len(mod))
rows = []
for nid, m in mk.items():
    ka, kb, day = names.key(m['a']), names.key(m['b']), m['k'][:10]
    pm = None
    for (a, b, d_), v in mod.items():
        if abs((np.datetime64(d_) - np.datetime64(day)).astype(int)) > 1: continue
        # the archive's p is the chance of the side after '@' (b)
        if a == kb and b == ka: pm = sorted(v)
        elif a == ka and b == kb: pm = [(t, 1 - p) for t, p in sorted(v)]
        if pm: break
    if not pm: continue
    s = sorted(m['s'])
    # first archived price at which a model chance was already on file
    first = next(((t, p) for t, p, h, vol in s if any(tm <= t for tm, _ in pm)), None)
    if not first: continue
    t0, p0 = first
    pmod = [p for tm, p in pm if tm <= t0][-1]
    p1 = s[-1][1]
    if s[-1][0] <= t0: continue
    rows.append((lg(pmod) - lg(p0), lg(p1) - lg(p0), abs(pmod - p0), m['lg'], day, t0, s[-1][0]))
R = np.array([r[:3] for r in rows], float)
print('matches with a model chance and a later price:', len(R))
def slope(mask, label):
    x, y = R[mask, 0], R[mask, 1]
    if len(x) < 20: print(label, 'n', len(x)); return
    k = (x @ y) / (x @ x)
    days = np.array([r[4] for r in rows])[mask]
    # day-clustered se through the origin
    num = sum((x[days == d] @ (y[days == d] - k * x[days == d])) ** 2 for d in set(days))
    se = num ** .5 / (x @ x)
    print(f'{label}: n {len(x)}  k {k:+.3f}  se {se:.3f}  t {k/se:+.2f}  mean |gap| {R[mask,2].mean():.3f}  sd move {y.std():.3f}')
slope(np.ones(len(R), bool), 'all')
slope(R[:, 2] >= .04, 'gap 4+ pts (the pick rule)')
slope(R[:, 2] < .04, 'gap under 4')
hrs = np.array([(np.datetime64(r[6][:19]) - np.datetime64(r[5][:19])).astype('timedelta64[m]').astype(int) / 60 for r in rows])
print('hours first price to last: median', np.median(hrs))
slope(hrs >= 12, '12+ hours of line history')
slope(hrs < 12, 'under 12 hours')
lgs = np.array([r[3] for r in rows])
for l in sorted(set(lgs)): slope(lgs == l, l)

# ---- tradeable version: buy the model's side at the ask (no-vig chance + half spread h) at the first snapshot where
# the gap is X+; value at the last pre-match no-vig chance
print('\ntradeable (ask = mid + h):')
def trade(X, hmax, vmin=0):
    out = []
    for nid, m in mk.items():
        ka, kb, day = names.key(m['a']), names.key(m['b']), m['k'][:10]
        pm = None
        for (a, b, d_), v in mod.items():
            if abs((np.datetime64(d_) - np.datetime64(day)).astype(int)) > 1: continue
            if a == kb and b == ka: pm = sorted(v)
            elif a == ka and b == kb: pm = [(t, 1 - p) for t, p in sorted(v)]
            if pm: break
        if not pm: continue
        s = sorted(m['s'])
        p1 = s[-1][1]
        for t, p, h, vol in s[:-1]:
            if h is None or h > hmax or vol < vmin: continue
            pmv = [q for tm, q in pm if tm <= t]
            if not pmv: continue
            q = pmv[-1]
            side = 1 if q > p else -1
            ps, qs, cs = (p, q, p1) if side == 1 else (1 - p, 1 - q, 1 - p1)
            if qs - ps < X or qs - ps > .35 or not (.25 <= ps <= .75): continue
            out.append((cs / (ps + h) - 1, cs / ps - 1, lg(cs) - lg(ps), lg(qs) - lg(ps), day, h))
            break
    if len(out) < 10: print(f'  X {X} h<={hmax} vol>={vmin}: n {len(out)}'); return
    A = np.array([o[:4] for o in out], float); days = np.array([o[4] for o in out])
    def ct(v):
        g = np.array([v[days == d].sum() for d in set(days)])
        return v.mean(), g.sum() / (g.std(ddof=1) * len(g) ** .5)
    r, t = ct(A[:, 0]); r0, t0 = ct(A[:, 1])
    k = (A[:, 3] @ A[:, 2]) / (A[:, 3] @ A[:, 3])
    print(f'  X {X} h<={hmax} vol>={vmin}: n {len(A)}  CLV ret at ask {r*100:+.2f}% (t {t:+.2f})  at mid {r0*100:+.2f}% (t {t0:+.2f})  k {k:+.3f}  mean h {np.mean([o[5] for o in out]):.3f}')
for X in (.04, .08, .12):
    for hmax in (1, .03, .015, .01):
        trade(X, hmax)
trade(.04, .015, 500); trade(.04, 1, 500); trade(.04, .015, 2000)
