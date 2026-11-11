# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""FV-2 (Nov 9 audit): the CFB distribution's `early` spread term is hindsight in the fit (not his last college season)
but a class-year proxy live (scripts/fv_dist.mjs cfbZ). Pre-registered, Nov 11 2026, before any run:
  rows   node scripts/cfb_fv_refit.mjs --dist2 --dist=scripts/.cache/fvdist/cfb_rows_d2.json (last season <= 2023,
         non-final rows only from 2019-20, so they are not selected on leaving college early)
  A      the shipped spread terms, `early` fit on hindsight, scored held out with the LIVE early value (as the board serves it)
  B      the same terms, `early` fit and scored on the live rule
  folds  draft class (last + 1) held out
  pass   B's RPS lower pooled AND in most classes, AND |mean given - mean became| for years 1-2 rows smaller
Writes results.json beside this script."""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import fv_dist_fit as F

src = json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'fvdist', sys.argv[1] if len(sys.argv) > 1 else 'cfb_rows_d2.json')))
YR = {1: 'Fr', 2: 'So', 3: 'Jr', 4: 'Sr', 5: 'Gr'}
def live_early(r):
    y = r['years']; cls = YR.get(r.get('rosY') or 0, '')
    last = y >= 4 or cls in ('Sr', 'Gr')
    return 0.0 if last else (0.5 if r['dt'] and y >= 3 else 1.0)
rows = []
for r in src:
    x = r['fc'] if r['dt'] else r['fm']
    rows.append({**r, 'x': x, 'y': F.fv_of_av(r['av']), 'cls': r['last'], 'eH': 0.0 if r['final'] else 1.0, 'eL': live_early(r)})
folds = np.array([r['last'] for r in rows]); ys = np.array([r['y'] for r in rows]); fl = F.floor_share(ys)
shipped = json.load(open(os.path.join(ROOT, 'data', 'fv_dist.json')))['cfb']['kept']
base, extra = F.cfb_terms(); allt = {t[0]: t for t in base + extra}
terms = lambda ek: [(n, (lambda r, ek=ek: r[ek])) if n == 'early' else allt[n] for n in shipped]
print('rows', len(rows), 'kept', shipped, 'early hindsight vs live disagree', round(np.mean([r['eH'] != r['eL'] for r in rows]), 3))
X = F.loc_x([r['x'] for r in rows]); k = np.array([F.bin_of(y) for y in ys])
def oof(fit_terms, serve_terms):
    Zf, Zs = F.scale_z(rows, fit_terms), F.scale_z(rows, serve_terms); P = np.zeros((len(rows), len(F.EDGES) + 1))
    for f in sorted(set(folds)):
        tr, te = folds != f, folds == f
        m = F.Model(X.shape[1], Zf.shape[1]).fit(X[tr], Zf[tr], k[tr]); P[te] = m.predict(X[te], Zs[te])
    return P
PA, PB = oof(terms('eH'), terms('eL')), oof(terms('eL'), terms('eL'))
mids = np.array(F.bin_stats(ys)[0])      # each bin's realized mean outcome
res = {}
for lab, P in (('A', PA), ('B', PB)):
    s = F.scores(P, ys, fl); pf = {str(c): F.scores(P[folds == c], ys[folds == c], fl, fast=True)['rps'] for c in sorted(set(folds))}
    yr = np.array([r['years'] <= 2.5 for r in rows]); mean = P @ mids
    res[lab] = {**s, 'perClass': pf, 'yrs12': {'n': int(yr.sum()), 'given': round(float(mean[yr].mean()), 2), 'became': round(float(ys[yr].mean()), 2)}}
    print(lab, s['rps'], s['logloss'], pf, res[lab]['yrs12'])
d = {c: res['A']['perClass'][c] - res['B']['perClass'][c] for c in res['A']['perClass']}
gap = lambda L: abs(res[L]['yrs12']['given'] - res[L]['yrs12']['became'])
res['verdict'] = {'rpsBetter': res['B']['rps'] < res['A']['rps'], 'classesBetter': f"{sum(v > 0 for v in d.values())}/{len(d)}", 'yrs12GapA': round(gap('A'), 2), 'yrs12GapB': round(gap('B'), 2)}
res['verdict']['pass'] = bool(res['verdict']['rpsBetter'] and sum(v > 0 for v in d.values()) > len(d) / 2 and gap('B') < gap('A'))
print(res['verdict'])
json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
