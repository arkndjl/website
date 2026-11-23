#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Port pass Nov 23 2026, model-to-model cells M1-M2 (prereg_addendum.md): shipped win-model terms into the NHL totals
model. Lockbox 2026-27 never read. -> results_m2m.json here"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCR)
import harness as H     # noqa: E402
import nhl_games as G   # noqa: E402

_orig = G.Model.feats


def feats(self, g, *a, **k):
    f = _orig(self, g, *a, **k)
    h, aw = g['h'], g['a']
    f['b2bT'] = float(self.rest(h, g['day']) == 0) + float(self.rest(aw, g['day']) == 0)
    f['rvT'] = self.lineup(h) + self.lineup(aw) if h in self.lv and aw in self.lv else 0.0
    return f


G.Model.feats = feats


def cut(r):
    return {'d': round(float(r['d']), 6), 't': round(float(r['t']), 2), 'p': round(float(r['p']), 4), 'n': int(r['n'])}


def main():
    hist = [g for g in G.load_hist() if g['S'] < 2027]
    P = json.load(open(G.FIT))['params']
    _, rows, _ = G.walk(hist, P, moves=G.hist_moves(hist))
    S, y, mg, tot, pc, tc, day = G.arrays(rows)
    lt = ~np.isnan(tc)
    X = G.design(rows, G.TFEATS)
    Tb = H.walk_ols(X, tot, S, 2021, train=lt)
    res = {}
    for name, key in (('M1 b2b -> totals', 'b2bT'), ('M2 rv -> totals', 'rvT')):
        x = G.design(rows, [key])
        T1 = H.walk_ols(np.column_stack([X, x]), tot, S, 2021, train=lt)
        out = {}
        for lab, m in (('tune', (S >= 2021) & (S <= 2023)), ('held', S >= 2024)):
            k = m & lt & ~np.isnan(T1) & ~np.isnan(Tb)
            out[lab] = cut(H.paired((T1[k] - tot[k]) ** 2, (Tb[k] - tot[k]) ** 2, day[k]))
            out['mae_' + lab] = [round(float(np.abs(Tb[k] - tot[k]).mean()), 4), round(float(np.abs(T1[k] - tot[k]).mean()), 4)]
        out['coef_all'] = round(float(np.linalg.lstsq(np.column_stack([X, x])[lt], tot[lt], rcond=None)[0][-1]), 4)
        res[name] = out
    adj = H.holm([res[k]['held']['p'] for k in res])
    for k, p in zip(res, adj):
        res[k]['holmP'] = round(float(p), 4)
        res[k]['pass'] = bool(res[k]['tune']['t'] <= -1.5 and p < 0.05)
    json.dump(res, open(os.path.join(HERE, 'results_m2m.json'), 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
