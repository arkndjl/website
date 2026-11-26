#!/usr/bin/env python3
"""Downstream test 1 (prereg): pXPM inside the roster prior's returner/transfer projection (scripts/cbb_roster.py xrow),
scored on the audit harness (next-season team adjEM R2, returners + transfers + back, same fill) against the shipped
roster prior. Variants: swap = pXPM in place of last-season BPM (b, and b in b x min%, tr x b); add = pXPM as one more
input; swap3 = pXPM in place of b and bpm3.   python3 roster.py -> roster.json"""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb')); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import audit as A
import cbb_roster as R
PX = {int(y): v for y, v in json.load(gzip.open(os.path.join(HERE, 'pxpm_loso.json.gz'), 'rt')).items()}


def px(p):
    q = PX.get(int(p['year']), {}).get(str(p['pid']))
    return q[0] + q[1] if q else None


def make(variant):
    base = R.xrow
    def xrow(k, r, p, ts, y):
        x = base(k, r, p, ts, y)
        if k not in ('ret', 'tr'): return x
        v = px(p); b = R.f(p['bpm'], R.REPL)
        if v is None: v = b
        m = R.f(p['min_per'], 0) / 100
        if variant == 'add': return x + [v]
        x = list(x); x[1] = v; x[4] = v * m; x[10] = x[7] * v
        if variant == 'swap3': x[2] = v
        return x
    return xrow


def run(variant):
    if variant: R.xrow = make(variant)
    RP = A.roster_prior()
    R.xrow = ORIG
    vn = {n: {pid: v for pid, (v, k) in RP[n].items() if k in ('ret', 'tr', 'back')} for n in A.PAIRS}
    return A.predict(lambda n: vn[n])


ORIG = R.xrow
by = R.load_seasons(); y0 = sorted(by)[-1]; p0 = next(iter(by[y0 - 1].values()))
hit = sum(1 for p in by[y0 - 1].values() if px(p) is not None); print('pxpm join', hit, '/', len(by[y0 - 1]), flush=True)
_, _, base = run(None); out = {'base': base}
for v in ('swap', 'add', 'swap3'):
    _, _, sc = run(v)
    d = [sc['byPair'][n] - base['byPair'][n] for n in A.PAIRS]; t, p = A.paired_t(d)
    out[v] = {'teamR2': [base['teamR2'], sc['teamR2']], 'playerR_vsBPM': [base['playerR_vsBPM'], sc['playerR_vsBPM']],
              'pairsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': round(p, 5)}
    print(v, out[v], flush=True)
json.dump(out, open(os.path.join(HERE, 'roster.json'), 'w'), indent=1)
