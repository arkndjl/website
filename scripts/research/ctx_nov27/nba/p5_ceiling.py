"""P5: the next up ceiling (scripts/nba_ceiling_research.py) reads `sxpm`, which became the new pXPM on Nov 24, while
the live build feeds it sx0 (the Nov 4 shrink, what the shipped fit was trained on). (1) does a refit on sx0 reproduce
the shipped coefficients, (2) the final model on pXPM against the same model on sx0: pinball loss at .80, held out by
season.  -> p5_ceiling.json"""
import json, os
import numpy as np
import common as C
import breakout_lib as L, nba_breakout_research as R, nba_ceiling_research as CR

P = R.seasons(R.SRC); X = {k: v for k, v in CR.xpm_seasons().items() if k[1] <= C.LAST}
rows = []
for (pid, y), a in X.items():
    b = X.get((pid, y + 1)); la, lb = P.get((pid, y)), P.get((pid, y + 1))
    if not b or not la or not lb or a['mp'] < 300 or b['mp'] < 1000 or a.get('sxpm') is None or a.get('sx0') is None or b.get('xpm') is None: continue
    rows.append((y + 1, a, b, la, lb))
S = np.array([r[0] for r in rows], float); y = np.array([r[2]['xpm'] for r in rows], float); w = np.array([r[2]['mp'] for r in rows], float)
age = np.array([r[1]['age'] or 25 for r in rows], float); lmp = np.log([r[1]['mp'] for r in rows])
u = np.array([r[3]['usage_pct'] for r in rows], float); du = np.array([r[4]['usage_pct'] - r[3]['usage_pct'] for r in rows], float)
fg2 = np.array([r[3]['fg2_plus'] for r in rows], float); tpar = np.array([r[3]['threepar_plus'] for r in rows], float)


def design(key):
    sx = np.array([r[1][key] for r in rows], float)
    return np.column_stack([sx, age, age ** 2, lmp, du, du ** 2, du * age, du * u, du * fg2, du * tpar, du * sx])


def run(Xm):
    fp = lambda tr, te: L.ceiling_pred(L.ceiling_fit(Xm[tr], y[tr], w[tr], None), Xm[te], None)[0]
    err = lambda c, te: (float(L.pinball(y[te], c, w[te]).sum()), float(w[te].sum()))
    res = L.loso(S, fp, err)
    hit = tot = 0.0
    for s in sorted(set(S.tolist())):
        te, tr = S == s, S != s
        c = L.ceiling_pred(L.ceiling_fit(Xm[tr], y[tr], w[tr], None), Xm[te], None)[0]
        hit += float((w[te] * (y[te] <= c)).sum()); tot += float(w[te].sum())
    return res, round(hit / tot, 3)


a, ca = run(design('sx0')); b, cb = run(design('sxpm'))
live = json.load(open(CR.OUT))['fit']; f0 = L.ceiling_fit(design('sx0'), y, w, None)
res = {'n': len(rows), 'pXPM vs sx0 (final model, pinball .80)': L.compare(a, b), 'coverage': {'sx0': ca, 'pXPM': cb},
       'refit on sx0 vs shipped': {'max |coef diff|': round(float(np.max(np.abs(np.array(f0['b']) - np.array(live['b'])))), 4),
                                    'b0': [round(live['b0'], 3), round(f0['b0'], 3)], 'q': [round(live['q'], 3), round(f0['q'], 3)]}}
print(json.dumps(res, indent=1)); json.dump(res, open(os.path.join(C.HERE, 'p5_ceiling.json'), 'w'), indent=1)
