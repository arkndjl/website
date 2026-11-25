#!/usr/bin/env python3
"""(e1) NFL neutral EPA in the predictive chain. Loads the round-1 audit (../../nfl/audit.py) with a hook that moves XV's
EPA inputs to neutral-play EPA (nfl_neutral_prep.py deltas) in the full-season captures and the XV fit rows, then scores
predict for pXR/60 (pwar), pXP/60 and XV.  NEUTRAL=0|1 python3 nfl_neutral.py -> nfl_neutral_<0|1>.json"""
import json, os, sys, types
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
AUD = os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'nfl', 'audit.py')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
NEU = os.environ.get('NEUTRAL', '0') == '1'
STAT = {'rows': 0, 'moved': 0}


def adj(c, d):
    c['pepa'] = c.get('pepa', 0.0) + d[0] * (c.get('att', 0.0) + c.get('sk', 0.0))
    c['repa'] = c.get('repa', 0.0) + d[1] * c.get('car', 0.0)
    c['recepa'] = c.get('recepa', 0.0) + d[2] * c.get('tgt', 0.0)


def HOOK(C, S):
    if not NEU: return
    for y in range(2018, 2026):
        D = json.load(open(os.path.join(CACHE, f'port_neutral_{y}.json')))
        g = C[(y, 'full')]['gsis']
        for p in C[(y, 'full')]['xrows']:
            STAT['rows'] += 1; d = D.get(g.get(p['pfr'], ''))
            if d: adj(p['c'], d); STAT['moved'] += 1
        for p in S[y]['players']:
            d = D.get(p.get('gsis', ''))
            if d: adj(p['c'], d)


src = open(AUD).read()
key = "S = X.load(); X.zscore(S)\n"
assert key in src
src = src.replace(key, "S = X.load(); HOOK(C, S); X.zscore(S)\n").replace("HERE = os.path.dirname(os.path.abspath(__file__))", f"HERE = {os.path.dirname(AUD)!r}")
A = types.ModuleType('audit_port'); A.__dict__['HOOK'] = HOOK; A.__dict__['__file__'] = AUD
exec(compile(src, AUD, 'exec'), A.__dict__)
print('hook', STAT, flush=True)
P = {}
for n in A.PAIRS:
    Un, U1 = A.units(n, 'full', (n, n + 1)), A.units(n + 1, 'full', (n, n + 1))
    px, Dy = A.pxp_of(n, 'full', (n, n + 1), n); A.add_pxp(Un, px, Dy)
    P[n] = ((lambda m, U=Un, n=n: A.season_D(U, A.C[(n, 'full')]['teams'], m)), (lambda m, U=U1, n=n: A.season_D(U, A.C[(n + 1, 'full')]['teams'], m)))
    print('pair', n, flush=True)
out = {'neutral': NEU, 'hook': STAT, 'metrics': {}}
for mt in ('pwar', 'pxp', 'xv'):
    p, err, _ = A.predict(mt, P)
    # player r vs next board WAR rate (raw board, the common target)
    out['metrics'][mt] = {'predict': p, 'err': {str(k): v for k, v in err.items()}}
    print(mt, {k: p[k] for k in ('teamR2', 'teamHeldR2', 'playerR')}, flush=True)
px_, py_, pw_ = {}, {}, {}
for mt in ('pwar', 'pxp'):
    xs, ys, ws = [], [], []
    for n in A.PAIRS:
        Dn, D1 = P[n][0](mt), P[n][1]('board')
        from collections import defaultdict
        e = defaultdict(float); e1 = defaultdict(float)
        for pid, t, x in Dn['parts']: e[pid] += x
        for pid, t, x in D1['parts']: e1[pid] += x
        for pid, x in e1.items():
            if x >= .4 and pid in Dn['val'] and pid in D1['val']:
                xs.append(Dn['val'][pid] * e[pid] / (e[pid] + .2)); ys.append(D1['val'][pid]); ws.append(x)
    out['metrics'][mt]['playerVsBoard'] = round(A.core.wcorr(xs, ys, ws), 4)
    print(mt, 'player r vs next board', out['metrics'][mt]['playerVsBoard'], flush=True)
json.dump(out, open(os.path.join(HERE, f'nfl_neutral_{int(NEU)}.json'), 'w'))
