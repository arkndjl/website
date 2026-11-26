#!/usr/bin/env python3
"""CBB college path years 1-3, age for the class in place of / beside 'old' (prereg.md family C). python3 cbb_path_age.py"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.argv.append('--offline')
import cbb_recruit_fit as R
import names as N
import importlib.util
spec = importlib.util.spec_from_file_location('ca', os.path.join(HERE, 'cbb_age.py'))
src = open(os.path.join(HERE, 'cbb_age.py')).read().rsplit('\nmain()', 1)[0]
ns = {'__file__': os.path.join(HERE, 'cbb_age.py')}; exec(compile(src, 'cbb_age.py', 'exec'), ns)

H = R.history(); smap = R.slug_map(H); teams = H['teams']
rows = [r for r in H['recruits'] if r['cls'] <= R.NOW_CLASS - 1]
kit = ns['dobs']()
shipped = json.load(open(os.path.join(ROOT, 'data', 'cbb_recruits.json')))['model']['path']
F, ref = R.frame(rows, smap, teams)
a = []
for r, f in zip(rows, F):
    k = kit.get((r['cls'], r['rk']))
    if k and not N.same(k[0], r['name']): k = None
    k = k or kit.get((r['cls'], N.key(r['name'])))
    a.append(ns['agec'](k[1], r['cls']) if k and k[1] else None)
m = float(np.mean([x[0] for x in a if x]))
for f, x in zip(F, a):
    f['agec'] = x[0] if x else m; f['_ex'] = bool(x and x[1]); f['_kn'] = bool(x)
out = {}
for k in R.PATH_K:
    D = R.path_rows(rows, F, k); folds = sorted(set(d['cls'] for d in D))
    on = np.array([d['on'] for d in D]) > 0
    print('year', k, 'n', len(D), 'plays', on.sum(), 'dob known among players', round(np.mean([d['f']['_kn'] for d, o in zip(D, on) if o]), 3),
          'exact', round(np.mean([d['f']['_ex'] for d, o in zip(D, on) if o]), 3))
    for part in ('min', 'bpm'):
        cols = shipped[str(k)]['parts'][part]['cols']
        base, cl = R.path_cv(D, part, cols); lb = R.path_loss(D, base, part)
        for tag, c2 in (('swap', [c if c != 'old' else 'agec' for c in cols] if 'old' in cols else None), ('add', cols + ['agec'])):
            if c2 is None: continue
            pr, _ = R.path_cv(D, part, c2); l = R.path_loss(D, pr, part)
            d_, t, w = R.paired(l, lb, cl, folds)
            out[f'{k} {part} {tag}'] = {'cols': cols, 'gain': round(-d_, 4), 't': round(-t, 2), 'classes': f'{w}/{len(folds)}'}
            print(' ', k, part, tag, out[f'{k} {part} {tag}'])
json.dump(out, open(os.path.join(HERE, 'cbb_path_age.json'), 'w'), indent=1)
