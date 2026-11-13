#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Shared harness (tennis audit): one walk-forward pass of the live match model, cached; lockbox cut at Nov 10 2026."""
import os, sys, pickle, json, math, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import tennis_model as M
import tennis_data as T
LOCK = 20261110            # lockbox: nothing after this date is read
CACHE = os.path.join(os.path.dirname(os.path.dirname(HERE)), '.cache', 'tennis', 'nov13')
os.makedirs(CACHE, exist_ok=True)

def load_rows():
    rows, players, tn = T.load()
    return [r for r in rows if r[0] <= LOCK], players, tn

def live_P():
    return dict(M.DEFAULT, **json.load(open(M.FIT))['params'])

def base_rec(rows, P=None, name='base'):
    p = os.path.join(CACHE, name + '.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    P = P or live_P()
    t = time.time()
    _, rec = M.run(rows, P, score=lambda r: M.scored(r, 2012 - M.WIN, 2100), cm_lag=M.CM_LAG)
    print('pass', round(time.time() - t), 's', len(rec))
    pickle.dump(rec, open(p, 'wb'))
    return rec
if __name__ == '__main__':
    rows, players, tn = load_rows()
    rec = base_rec(rows)
    P = live_P()
    pw = M.wf_probs(rec, P)
    for y0, y1 in ((2012, 2022), (2023, 2026), (2025, 2026)):
        s = [p for x, p in zip(rec, pw) if y0 <= x[0][0] // 10000 <= y1]
        print(y0, y1, len(s), round(M.ll(s), 5))
