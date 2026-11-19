# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 4 (PREREG.md, addendum C): ESPN BPI predictor margin stacked on the committed walk-forward margin.

    python3 bpi_test.py CORE.json      # -> impl/nba/bpi_stack.json

candidate = walk + c x (bpi - walk), c fit on the sampled games of the seasons before; tune 2023-24, held 2025-26;
|margin error| paired, clustered by game day."""
import json, os, sys
import numpy as np
import common as C
import nba_games as N
import nba_games_fit as Fit


def walk_preds():
    fn = os.path.join(C.SCR, 'walk_margin.json')
    if os.path.exists(fn): return json.load(open(fn))
    F = json.load(open(N.FIT))
    G, names = N.load_hist()
    _, data = N.walk(G, names, F['P'], F['params'], inj=Fit.load_inj())
    D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
    X = {f: np.array([x[f] for _, x in D], float) for f in F['feats']}
    y = np.array([g['hs'] - g['as'] for g, _ in D], float); S = np.array([g['S'] for g, _ in D])
    pr = Fit.wf(Fit.mat(X, F['feats']), y, S)
    out = {g['id']: [float(p), float(yy), g['tip'][:10], int(g['S']), g.get('L')] for (g, _), p, yy in zip(D, pr, y) if p == p}
    json.dump(out, open(fn, 'w'))
    return out


def main():
    W = walk_preds()
    core = json.load(open(sys.argv[1]))
    rows = []
    for k, p in core.items():
        h, a = p['home'], p['away']
        b = h.get('teamPredPtDiff') if h.get('teamPredPtDiff') is not None else (-a['teamPredPtDiff'] if a.get('teamPredPtDiff') is not None else None)
        if b is None or k not in W: continue
        w, y, day, S, L = W[k]
        rows.append((S, day, w, b, y, L))
    S = np.array([r[0] for r in rows]); day = np.array([r[1] for r in rows]); w = np.array([r[2] for r in rows]); b = np.array([r[3] for r in rows]); y = np.array([r[4] for r in rows])
    L = np.array([r[5] for r in rows], float)
    pred = np.full(len(y), np.nan); cs = {}
    for s in range(2023, 2027):
        tr, te = S < s, S == s
        g = b[tr] - w[tr]
        c = float((g * (y[tr] - w[tr])).sum() / (g ** 2).sum()); cs[s] = round(c, 3)
        pred[te] = w[te] + c * (b[te] - w[te])
    e1, e0 = np.abs(pred - y), np.abs(w - y)
    res = {'n': len(rows), 'bySeasonN': {int(s): int((S == s).sum()) for s in sorted(set(S))}, 'c': cs,
           'maeBpi': round(float(np.abs(b - y).mean()), 4), 'maeWalk': round(float(e0.mean()), 4), 'maeClose': round(float(np.abs(L - y).mean()), 4)}
    for nm, k in (('tune', np.isin(S, (2023, 2024))), ('held', S >= 2025)):
        p = C.paired((e1 - e0)[k], day[k]); ss = sorted(set(S[k]))
        res[nm] = {'n': int(k.sum()), 'mae0': round(float(e0[k].mean()), 4), 'mae1': round(float(e1[k].mean()), 4), 'd': round(p['d'], 4), 't': round(p['t'], 2),
                   'seasonsLower': int(sum((e1 - e0)[k & (S == s)].mean() < 0 for s in ss)), 'seasons': len(ss)}
    res['pass'] = bool(res['held']['t'] <= -2 and res['tune']['d'] < 0 and res['held']['seasonsLower'] == res['held']['seasons'])
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(C.IMPL, 'bpi_stack.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
