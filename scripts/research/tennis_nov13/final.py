#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The shipped model (Tennis Abstract rows + Challenger K x0.85) against the old one on the same matches."""
import sys, os, json, gzip
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import *
from mtests import *
def load(f):
    h = json.load(gzip.open(os.path.join(os.path.dirname(CACHE), f)))
    return [r for r in h['rows'] if r[0] <= LOCK]
old, new = load('hist_nota.json.gz'), load('hist.json.gz')
P1 = live_P(); P0 = dict(P1, KLV_C=1.0)
def rec(rows, P, name):
    p = os.path.join(CACHE, name + '.pkl')
    if os.path.exists(p): return pickle.load(open(p, 'rb'))
    _, r = M.run(rows, P, score=lambda r: M.scored(r, 2012 - M.WIN, 2100), cm_lag=M.CM_LAG)
    pickle.dump(r, open(p, 'wb')); return r
out = {}
variants = {'old': (old, P0), 'ta only': (new, P0), 'klv only': (old, P1), 'shipped': (new, P1)}
Z = {}
for k, (rows, P) in variants.items():
    F, m = arrays(rec(rows, P, 'final_' + k.replace(' ', '_'))); Z[k] = (wf_logit(F, m), m)
for k in ('ta only', 'klv only', 'shipped'):
    c = compare(Z['old'][0], Z['old'][1], Z[k][0], Z[k][1], k)
    print(k, 'tune', c['tune'], 'held', c['held'], 'close rows', c['close'], '2026', c['seasons'][2026])
