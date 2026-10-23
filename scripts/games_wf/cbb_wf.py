#!/usr/bin/env python3
"""Walk-forward CBB predictions in the calibration-study schema, from scripts/cbb_games.py with the committed tuning
(data/cbb_games_fit.json params + selected feats, both chosen on 2016-20 only). Writes no repo data files
(only the gitignored scripts/.cache/cbb availability caches when missing)."""
import gzip, json, os, sys
import numpy as np
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))
import cbb_games as C

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'games_wf', 'cbb.json.gz')
F = json.load(open(C.FIT))
P, feats = F['params'], F['feats']
os.makedirs(C.CACHE, exist_ok=True)
games, btname, d1s, tprior, avs = C.load_all()
W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
pred = C.walk_pred(Xm, y, S, d1)
tpred = C.walk_pred(TX, ty, S, d1)
# the availability term's points in each game (home minus away), at that season's walk-forward weight: the 'inj'
# segment family in games_picks.py splits picks by whether the injury part of the margin sides with them
ij = np.zeros(len(y))
if 'inj' in feats:
    j = feats.index('inj')
    for s in range(C.SCORE0, C.LAST + 1):
        tr, te = (S < s) & d1, S == s
        if te.any():
            ij[te] = Xm[te, j] * np.linalg.solve(Xm[tr].T @ Xm[tr], Xm[tr].T @ y[tr])[j]
out = []
for i, (g, _, _) in enumerate(D):
    if not d1[i] or np.isnan(pred[i]) or np.isnan(line[i]):
        continue
    note = (g.get('note') or '').lower()
    po = 1 if (g.get('stype') == 3 or 'tournament' in note or 'championship' in note) else 0
    out.append({'sport': 'cbb', 'S': int(S[i]), 'id': g['id'], 'date': C.et_date(g['date']), 'home': g['hn'], 'away': g['an'],
                'neutral': int(bool(g['neutral'])), 'm': round(float(pred[i]), 2), 'L': float(line[i]),
                'Lo': (-float(g['open']) if g.get('open') is not None else None), 'res': int(y[i]),
                'mlH': g.get('mlh'), 'mlA': g.get('mla'), 'oH': None, 'oA': None,
                'tm': (None if np.isnan(tpred[i]) else round(float(tpred[i]), 2)),
                'T': (float(g['total']) if g.get('total') else None), 'To': None, 'tot': int(ty[i]), 'po': po, 'ij': round(float(ij[i]), 2)})
with gzip.open(OUT, 'wt') as f:
    json.dump(out, f)
# report
from collections import Counter
print('rows', len(out), sorted(Counter(r['S'] for r in out).items()))
A = lambda k: np.array([np.nan if r[k] is None else r[k] for r in out], float)
m, L, res, Ss, tm, T, tot = A('m'), A('L'), A('res'), A('S'), A('tm'), A('T'), A('tot')
for name, k in (('2016-20', (Ss <= 2020)), ('2021-26 held', Ss >= 2021), ('all', Ss > 0)):
    kt = k & ~np.isnan(T) & ~np.isnan(tm)
    print(name, 'n', int(k.sum()), 'MAE m', round(np.mean(np.abs(m[k] - res[k])), 3), 'MAE L', round(np.mean(np.abs(L[k] - res[k])), 3),
          'tot n', int(kt.sum()), 'MAE tm', round(np.mean(np.abs(tm[kt] - tot[kt])), 3), 'MAE T', round(np.mean(np.abs(T[kt] - tot[kt])), 3),
          'sd(res-m)', round(np.std(res[k] - m[k]), 2), 'sd(tot-tm)', round(float(np.std((tot - tm)[kt])), 2))
print('corr(L,res)', round(np.corrcoef(L, res)[0, 1], 3), 'corr(m,L)', round(np.corrcoef(m, L)[0, 1], 3),
      'corr(m,res)', round(np.corrcoef(m, res)[0, 1], 3), 'fit sd', F['sd'], 'tsd', F['tsd'])
print('Lo non-null', int(sum(r['Lo'] is not None for r in out)), 'T non-null', int(sum(r['T'] is not None for r in out)),
      'ml non-null', int(sum(r['mlH'] is not None for r in out)), 'po', int(sum(r['po'] for r in out)), 'neutral', int(sum(r['neutral'] for r in out)))
