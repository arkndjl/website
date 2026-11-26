#!/usr/bin/env python3
"""CBB recruit Y1 FV: the board grade a recruit carries at the end of his freshman season if he plays D-I (fr_rows.json,
build_rows.py), from his recruit-day drivers. Classes held out; passes when it beats the class mean and the drivers
beyond rank pass the board's gate (t >= 2, 70% of classes). Also scored against the freshman season he then had (BPM).
    python3 scripts/research/cbb_y1fv_nov26/build_rows.py && python3 scripts/research/cbb_y1fv_nov26/fit.py --offline"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_recruit_fit as R
import names as N

H = R.history(); smap = R.slug_map(H); teams = H['teams']
rows = [r for r in H['recruits'] if 2009 <= r['cls'] <= 2025]
F, ref = R.frame(rows, smap, teams)
fr = json.load(open(os.path.join(HERE, 'fr_rows.json')))['rows']
by = {}
for x in fr: by.setdefault((N.key(x['name']), x['year']), []).append(x)
D = []
for r, f in zip(rows, F):
    y = r['cls'] + 1
    s = (r.get('col') or {}).get(str(y))
    if not s or s[0] < 5: continue
    c = by.get((N.key(r['name']), y)) or []
    tm = (r.get('college') or {}).get('team')
    c = [x for x in c if not tm or N.same_team(x['team'], tm)] or (c if len(c) == 1 else [])
    if len(c) != 1: continue
    D.append({'key': r['key'], 'cls': r['cls'], 'f': f, 'on': 1.0, 'v': max(c[0]['fv'] - 20.0, 1e-3), 'fv': c[0]['fv'], 'bpm': s[2], 'min': s[1], 'rk': r.get('rk')})
print(len(D), 'recruits with a graded freshman season', {c: sum(d['cls'] == c for d in D) for c in sorted({d['cls'] for d in D})})
folds = sorted({d['cls'] for d in D}); cl = np.array([d['cls'] for d in D]); y = np.array([d['fv'] for d in D])


def cvp(cols):
    p, _ = R.path_cv(D, 'v', cols); return 20 + p


def se(p): return (y - p) ** 2
null = np.zeros(len(D))
for c in folds: null[cl == c] = y[cl != c].mean()
cols = ['lrk']; pred = cvp(cols); base = se(pred); rank_only = base.copy(); kept = []
d0, t0, w0 = R.paired(rank_only, se(null), cl, folds)
while True:
    best = None
    for c in R.PATH_BASE + ['old']:
        if c in cols: continue
        pr = cvp(cols + [c]); l = se(pr); d_, t, w = R.paired(l, base, cl, folds)
        print(f'   try {c}: t {t:.2f}, {w}/{len(folds)}')
        if t <= -2 and w >= math.ceil(0.7 * len(folds)) and (best is None or t < best[1]): best = (c, t, w, l, pr)
    if not best: break
    cols.append(best[0]); base = best[3]; pred = best[4]; kept.append({'driver': R.LABEL[best[0]], 't': round(-best[1], 2), 'classes': best[2]})
d1, t1, w1 = R.paired(base, se(null), cl, folds)
sp = lambda a, b: float(R.spearman(np.asarray(a, float), np.asarray(b, float)))
bpm = np.array([d['bpm'] for d in D]); val = np.array([R.college_value(d['min'], d['bpm']) for d in D]); lrk = np.array([d['f']['lrk'] for d in D])
top = y >= 30
out = {'n': len(D), 'classes': [folds[0], folds[-1]], 'cols': cols, 'kept': kept,
       'rmse': {'null': round(math.sqrt(se(null).mean()), 3), 'rank': round(math.sqrt(rank_only.mean()), 3), 'model': round(math.sqrt(base.mean()), 3)},
       'vs_null': {'t': round(-t1, 2), 'classes': int(w1), 'of': len(folds)}, 'rank_vs_null': {'t': round(-t0, 2), 'classes': int(w0)},
       'r': round(float(np.corrcoef(pred, y)[0, 1]), 3), 'bias': round(float((pred - y).mean()), 3),
       'cal': [[round(float(pred[m].mean()), 1), round(float(y[m].mean()), 1), int(m.sum())] for m in [(pred >= a) & (pred < b) for a, b in ((20, 21), (21, 23), (23, 26), (26, 30), (30, 36), (36, 99))] if m.sum()],
       'freshman': {'bpm': {'model': round(sp(pred, bpm), 3), 'rank': round(sp(lrk, bpm), 3)}, 'value': {'model': round(sp(pred, val), 3), 'rank': round(sp(lrk, val), 3)}},
       'top30': {'n': int(top.sum()), 'pred': round(float(pred[top].mean()), 1), 'act': round(float(y[top].mean()), 1)}}
json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
# the training rows the production fit reads (scripts/cbb_recruit_fit.py y1fv_fit): [class, On3 key, season-end grade]
import gzip
with open(os.path.join(R.ROOT, 'scripts', 'data', 'cbb_y1fv_rows.json.gz'), 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as fh:
    fh.write(json.dumps({'test': out, 'rows': [[d['cls'], d['key'], round(d['fv'], 2)] for d in D]}, separators=(',', ':')).encode())
print(json.dumps(out, indent=1))
