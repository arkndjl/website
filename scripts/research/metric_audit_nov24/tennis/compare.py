#!/usr/bin/env python3
"""Paired head-to-heads for the best-metric calls and per-tour splits of the candidates -> compare.json"""
import json, os, pickle, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import score as S
full = pickle.load(open(os.path.join(S.OUT, 'full.pkl'), 'rb')); half = pickle.load(open(os.path.join(S.OUT, 'half.pkl'), 'rb'))
rk = S.year_end_ranks(); S.add_ranks(full['snaps'], rk); S.add_ranks(half['snaps'], rk)
dho, keys = S.build(half['snaps'], half['matches'], 0, 5)
dpr, _ = S.build(full['snaps'], full['matches'], 1, 10)
out = {}
for tgt, d, pairs in (('describe_held', dho, [('elo538', 'ppa'), ('ark', 'ppa'), ('elo', 'ppa'), ('rpa_k', 'ppa'), ('ark_pa', 'ppa')]),
                      ('predict', dpr, [('elo', 'ark_pa'), ('elo538', 'ark_pa'), ('elo', 'ark'), ('elo538', 'elo'), ('ppa', 'ark_pa')])):
    for b, c in pairs:
        out[f'{tgt}: {c} vs {b}'] = S.cand_test(d, keys, b, c, True)
for name, (b, c, tgt) in S.CAND.items():
    d = dho if tgt == 'describe_held' else dpr
    for tour in 'aw':
        sub = {}
        for y, (t, x) in d.items():
            k = np.array([s[0] == tour for s in t])
            if k.any(): sub[y] = (t[k], x[k])
        out[f'{name} {tour}'] = S.cand_test(sub, keys, b, c, True)
for k, v in out.items(): v['p1'] = round(v['p1'], 6); print(k, v['base_r2'], v['cand_r2'], v['d_ll_1e4'], v['t'], v['seasons_better'])
json.dump(out, open(os.path.join(HERE, 'compare.json'), 'w'), indent=1, default=float)
