#!/usr/bin/env python3
"""Lead's leakage check for round-1 C2 (pXR/60 = pXP/60 + sub-position value), as port/nhl_soccer_nba/nhl_n6check.py:
(1) one constant k a share for every player (k = the exposure-weighted mean of the position value a share, no position
information); (2) base pXP, pXR and the constant rerun with season n+1 exposure rescaled to fixed lineup shares
(each team side's player shares scaled to 11 x games / 17; special teams rows dropped from n+1 parts, since pXP/pXR carry no
special teams value and those rows only took the fill).  python3 nfl_pxr_leak.py -> nfl_pxr_leak.json"""
import json, math, os, types
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
AUD = os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'nfl', 'audit.py')
src = open(AUD).read().replace("HERE = os.path.dirname(os.path.abspath(__file__))", f"HERE = {os.path.dirname(AUD)!r}")
A = types.ModuleType('audit_leak'); A.__dict__['__file__'] = AUD
exec(compile(src, AUD, 'exec'), A.__dict__)
U = {}
for n in A.PAIRS:
    Un, U1 = A.units(n, 'full', (n, n + 1)), A.units(n + 1, 'full', (n, n + 1))
    px, Dy = A.pxp_of(n, 'full', (n, n + 1), n); A.add_pxp(Un, px, Dy); U[n] = (Un, U1)
    print('pair', n, flush=True)
# k: exposure-weighted mean of the position value a share over the season-n rows that carry pXP
num = sum(A.VALUE.get(sub, 0) * sh for n in A.PAIRS for pid, t, sh, m, g, sub, sn in U[n][0] if 'pxp' in m)
den = sum(sh for n in A.PAIRS for pid, t, sh, m, g, sub, sn in U[n][0] if 'pxp' in m)
k = num / den
for n in A.PAIRS:
    for pid, t, sh, m, g, sub, sn in U[n][0]:
        if 'pxp' in m: m['pconst'] = m['pxp'] + k * sh


def rescale(D):
    tot = defaultdict(float)
    for pid, t, x in D['parts']:
        if not pid.startswith('ST:'): tot[t] += x
    g = {t: v[1] for t, v in D['team'].items()}
    return {**D, 'parts': [(pid, t, x * 11 * g[t] / 17 / tot[t]) for pid, t, x in D['parts'] if not pid.startswith('ST:') and tot[t] > 0 and t in g]}


P = {n: ((lambda m, n=n: A.season_D(U[n][0], A.C[(n, 'full')]['teams'], m)), (lambda m, n=n: A.season_D(U[n][1], A.C[(n + 1, 'full')]['teams'], m))) for n in A.PAIRS}
PR = {n: (P[n][0], (lambda m, n=n: rescale(P[n][1](m)))) for n in A.PAIRS}


def paired(e1, e0):
    d = [a - b for n in e0 for a, b in zip(e1[n], e0[n])]
    t = float(np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d))))
    return dict(t=round(t, 2), p=round(.5 * (1 + math.erf(t / math.sqrt(2))), 4), pairsBetter=f'{sum(sum(e1[n]) < sum(e0[n]) for n in e0)}/{len(e0)}')


def player_r(mt, within=False):
    xs, ys, ws, gs = [], [], [], []
    for n in A.PAIRS:
        Dn, D1 = P[n][0](mt), P[n][1]('board')
        e = defaultdict(float); e1 = defaultdict(float)
        for pid, t, x in Dn['parts']: e[pid] += x
        for pid, t, x in D1['parts']: e1[pid] += x
        for pid, x in e1.items():
            if x >= .4 and pid in Dn['val'] and pid in D1['val']:
                xs.append(Dn['val'][pid] * e[pid] / (e[pid] + .2)); ys.append(D1['val'][pid]); ws.append(x); gs.append(D1['grp'][pid])
    if within:
        xs, ys = np.array(xs), np.array(ys); w = np.array(ws)
        for g in set(gs):
            ix = np.array([q == g for q in gs]); xs[ix] -= np.average(xs[ix], weights=w[ix]); ys[ix] -= np.average(ys[ix], weights=w[ix])
    return round(A.core.wcorr(list(xs), list(ys), ws), 4)


out = {'k_per_share': round(k, 4)}
for lab, PP in (('raw n+1 snaps', P), ('lineup shares', PR)):
    res = {mt: A.predict(mt, PP) for mt in ('pxp', 'pwar', 'pconst')}
    o = {mt: {'teamR2': r[0]['teamR2'], 'teamHeldR2': r[0]['teamHeldR2']} for mt, r in res.items()}
    o['pXR vs base'] = paired(res['pwar'][1], res['pxp'][1]); o['constant vs base'] = paired(res['pconst'][1], res['pxp'][1])
    o['pXR vs constant'] = paired(res['pwar'][1], res['pconst'][1])
    out[lab] = o; print(lab, json.dumps(o), flush=True)
out['playerR_vs_next_board'] = {mt: player_r(mt) for mt in ('pxp', 'pwar', 'pconst')}
out['playerR_within_sub'] = {mt: player_r(mt, True) for mt in ('pxp', 'pwar', 'pconst')}
print(out['playerR_vs_next_board'], out['playerR_within_sub'])
json.dump(out, open(os.path.join(HERE, 'nfl_pxr_leak.json'), 'w'), indent=1)
