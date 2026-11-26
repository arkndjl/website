#!/usr/bin/env python3
"""Ret% stage A (scripts/cbb_declare.py: walk forward over 2023-26, per-row log loss). The kept terms with the season's BPM
replaced by rXPM (same minutes shrink), and pXPM (board form, point in time) offered as an added term and in place of it.
-> declare.json"""
import csv, json, math, os, sys
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import cbb_declare as D
rows = sorted(D.rows_from_kit(), key=lambda r: r['year'])
mins = {}
with open(os.path.join(D.KIT, 'college_seasons_nba.csv'), newline='', encoding='utf-8') as f:
    for r in csv.DictReader(f): mins[(r['pid'], int(r['year']))] = (D.num(r['min_per']), D.num(r['bpm']))
miss = 0
for r in rows:
    m, b = mins[(r['pid'], r['year'])]
    x = C.get(r['pid'], r['year'], 'xpm'); miss += x is None
    r['xpm'] = D.feats(x if x is not None else b, m, None, None, None)['bpm']
    p = C.get(r['pid'], r['year'], 'px2'); r['px2'] = p if p is not None else r['bpm']
kept = json.load(open(D.OUT))['kept']; print('kept', kept, 'rows', len(rows), 'no rXPM', miss)
TE = D.TERMS + ['xpm', 'px2']
mu = {k: float(np.mean([r[k] for r in rows])) for k in TE}; sd = {k: float(np.std([r[k] for r in rows])) for k in TE}
te = [r for r in rows if r['year'] in D.HOLD]; yte = np.array([r['left'] for r in te], float); yrs = np.array([r['year'] for r in te])


def walk(terms):
    P = []
    for y in D.HOLD:
        tr = [r for r in rows if r['year'] < y]; ts = [r for r in rows if r['year'] == y]
        b = D.logit(D.design(tr, terms, mu, sd), np.array([r['left'] for r in tr], float)); P += list(1 / (1 + np.exp(-D.design(ts, terms, mu, sd) @ b)))
    return D.ll(np.array(P), yte)
L0 = walk(kept); out = {'kept': kept, 'n': len(te), 'base': round(float(L0.mean()), 4)}
sw = lambda t, a, b: [k.replace(a, b) for k in t]
for nm, t in (('rXPM for BPM', sw(kept, 'bpm', 'xpm')), ('pXPM for BPM', sw(kept, 'bpm', 'px2')), ('pXPM added', kept + ['px2'])):
    L = walk(t); d = L0 - L
    out[nm] = {'terms': t, 'logLoss': round(float(L.mean()), 4), 't': round(C.tstat(d), 2), 'seasons': f"{int(sum(d[yrs == y].mean() > 0 for y in D.HOLD))}/{len(D.HOLD)}"}
    print(nm, out[nm])
json.dump(out, open(os.path.join(C.HERE, 'declare.json'), 'w'), indent=1)
