# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer GAR fit with opponent- and home-adjusted inputs against the raw ones (Nov 20 2026): the GAR gate itself
(last season's rates x this season's minutes -> team goal difference a match, leave-one-season-out), per input set.

    python3 scripts/research/oppwx_nov20/soccer_fit_test.py
"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import soccer_data as D
import soccer_players as SP

S1 = D.current_season()
old = {(r['lg'], r['S'], r['tid'], r['p']): r for r in D.load(SP.ROWS)}
rows = SP.build_rows(SP.FIRST, S1 - 1)
for r in rows:
    o = old.get((r['lg'], r['S'], r['tid'], r['p']), {})
    r['orp'] = o.get('orp', 0.0); r['drp'] = o.get('drp', 0.0)
ts = SP.team_seasons(SP.FIRST, S1 - 1)
LS, TMV = SP.league_strength(), SP.tm_values()
pri = dict(priors=SP.PRIORS, LS=LS, TMV=TMV)
F = json.load(open(SP.FIT))
out = {}
E = {}
for nm, adj in (('raw', ()), ('on-pitch', ('xf', 'xa')), ('on-pitch + buildup', ('xf', 'xa', 'bu')), ('all five', ('xf', 'xa', 'bu', 'np', 'xA'))):
    SP.ADJ = adj
    best = None
    for shrink in (100, 200, 300, 500, 800):
        SP.prep(rows, shrink)
        for feats in (SP.FEATS, F['feats']):
            ks, X, y = SP.design(rows, ts, feats, **pri)
            for lam in (0.1, 1.0, 5.0):
                e, pred = SP.loso(ks, X, y, lam)
                if feats is F['feats'] and (best is None or e < best[0]):
                    best = (e, shrink, lam, (np.asarray(pred) - y) ** 2, [k[1] for k in ks])
    # at the live fit's own settings too
    SP.prep(rows, F['shrink'])
    ks, X, y = SP.design(rows, ts, F['feats'], **pri)
    e_live, pred = SP.loso(ks, X, y, F['lambda'])
    var = float(np.mean(y ** 2))
    E[nm] = (best[3], best[4], (np.asarray(pred) - y) ** 2)
    out[nm] = {'best': {'mse': round(best[0], 5), 'r2': round(1 - best[0] / var, 4), 'shrink': best[1], 'lam': best[2]},
               'live': {'mse': round(e_live, 5), 'r2': round(1 - e_live / var, 4)}, 'n': len(y)}
    print(nm, out[nm], flush=True)
for nm in out:
    if nm == 'raw': continue
    for which, ix in (('best', 0), ('live', 2)):
        d = E[nm][ix] - E['raw'][ix]
        seas = np.array(E[nm][1])
        bs = [float(d[seas == s].mean()) for s in sorted(set(seas))]
        out[nm][which]['t'] = round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2)
        out[nm][which]['seasonsBetter'] = f"{sum(1 for b in bs if b < 0)}/{len(bs)}"
    print(nm, out[nm])
json.dump(out, open(os.path.join(HERE, 'soccer_fit_results.json'), 'w'), indent=1)
