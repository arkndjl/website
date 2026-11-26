#!/usr/bin/env python3
"""Noah Nov 26: pXPM vs BPM as a CBB FV driver. cbb_fv_drivers.py's protocol (shipped returner drivers and rung penalties
from data/cbb_fit.json, boards 2009-16, outcome = realized FV on peak NBA XPM, out-of-fold rung deviance / null, two
5-fold player splits, player-clustered paired t; bar: gain in both splits, >= 4/5 folds each, t >= 2). pXPM = last college
season's pXPM (pxpm_loso.json.gz: coefficients never fit on that season's own next-season BPM, no NBA data).
  add   : pXPM (and O / D) added to the shipped set
  swap  : pXPM in place of bpm3, of bpm, of both (head to head with BPM)
-> fv.json"""
import gzip, hashlib, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cbb_data as D
import cbb_fit as F
import cbb_fv_drivers as V
PX = {int(y): v for y, v in json.load(gzip.open(os.path.join(HERE, 'pxpm_loso.json.gz'), 'rt')).items()}


def rows_for(years, last_max):
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.set_context(careers)
    rows, hit, n = [], 0, 0
    for c in careers:
        if c['last'] > last_max: continue
        for i, s in enumerate(c['seasons']):
            if s['year'] not in years or i == 0: continue
            f = F.features(c, i); p = c['seasons'][i - 1]
            q = PX.get(int(p['year']), {}).get(str(c['pid'])); n += 1
            if q: hit += 1; f['pxpm'], f['pxpm_o'], f['pxpm_d'] = q[0] + q[1], q[0], q[1]
            rows.append({'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'f': f})
    print('pXPM join', hit, '/', n, flush=True)
    return rows, careers


def swap(rows, kept, alt, lam):
    """per-row OOF deviance of alt set vs kept set, both splits"""
    y = np.array([r['y'] for r in rows], float); pid = [r['pid'] for r in rows]
    cols = list(dict.fromkeys(kept + alt)); X = F.matrix(rows, cols)
    ia, ib = [cols.index(k) for k in kept], [cols.index(k) for k in alt]
    null = []
    for j, t in enumerate(F.LADDER):
        on = y >= (F.LADDER[j - 1] if j else -1); o = (y[on] >= t).astype(float); m = o.mean()
        null.append(-(o * np.log(m) + (1 - o) * np.log(1 - m)).sum())
    splits = {'md5': np.array([F.fold_of(p) for p in pid]),
              'salt': np.array([int(hashlib.md5(('s' + str(p)).encode()).hexdigest(), 16) % F.FOLDS for p in pid])}
    res = {}
    for nm, fo in splits.items():
        d = V.row_dev(V.oof(rows, X, ia, lam, fo, cols), y, null) - V.row_dev(V.oof(rows, X, ib, lam, fo, cols), y, null)
        diff = d.sum(1); cl = defaultdict(float)
        for p, v in zip(pid, diff): cl[p] += v
        v = np.array(list(cl.values()))
        res[nm] = {'gain': round(float(diff.sum() * 100), 3), 'folds': sum(1 for k in range(F.FOLDS) if diff[fo == k].sum() > 0),
                   't': round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2), 'rungs': [round(float(x * 100), 3) for x in d.sum(0)]}
    res['pass'] = all(res[k]['gain'] > 0 and res[k]['folds'] >= 4 and res[k]['t'] >= 2 for k in splits)
    return res


def main():
    fit = json.load(open(os.path.join(ROOT, 'data', 'cbb_fit.json'))); m = fit['models']['returner']
    kept, lam = list(m['kept']), m['lam']
    rows, careers = rows_for(F.TRAIN, 2020)
    tops = [c['nba']['fvx'] for c in careers if c['last'] in F.SCALE_CLASSES and c['nba']['fvx'] >= 60]
    F.TOP_MEAN = round(float(np.mean(tops)), 2)
    rr = [r for r in rows if not r['f']['newcomer']]
    out = {'kept': kept, 'n': len(rr)}
    out['add'] = V.run(rr, kept, ['pxpm', 'pxpm_o', 'pxpm_d'], lam, 'add to the shipped returner set')
    S = {'pXPM for bpm3': [k if k != 'bpm3' else 'pxpm' for k in kept],
         'pXPM for bpm': [k if k != 'bpm' else 'pxpm' for k in kept],
         'pXPM for bpm + bpm3': [k for k in kept if k not in ('bpm', 'bpm3')] + ['pxpm'],
         'bpm3 dropped (reference)': [k for k in kept if k != 'bpm3']}
    out['swap'] = {}
    for nm, alt in S.items():
        out['swap'][nm] = swap(rr, kept, alt, lam); print(nm, out['swap'][nm], flush=True)
    json.dump(out, open(os.path.join(HERE, 'fv.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
