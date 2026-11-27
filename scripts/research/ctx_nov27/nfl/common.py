"""Shared loaders for the Nov 27 NFL context tests: replayed board rows and point-in-time pXP/60."""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
ROOT = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import nfl_rate as R      # noqa: E402
import nfl_market as MK   # noqa: E402

CACHE = os.path.join(SCR, '.cache', 'nfl')
YEARS = list(range(2016, 2026))
FIT = json.load(open(R.FIT))
M = FIT['model']


def load(y, tag=''):
    with open(os.path.join(CACHE, f'ctx27_rows_{y}{tag}.json')) as f:
        return {p['id']: p for p in json.load(f)}


FULL = {y: load(y) for y in YEARS}
W9 = {y: load(y, '_w9') for y in YEARS}
RATE = {y: {i: r for i, r in ((i, R.row_of(p)) for i, p in FULL[y].items()) if r} for y in YEARS}
RATE9 = {y: {i: r for i, r in ((i, R.row_of(p)) for i, p in W9[y].items()) if r} for y in YEARS}
MK.load()


def pxp(y, pid, r):
    """the live pXP/60 form for rate row r of season y (whole season or to a point), seasons y-1 and y-2 from the replay"""
    g = r['grp']
    prior = M['m'].get(r['sub'], 0.0)
    s = MK.signal(pid, y)
    k = f'{g}:{s[0]}' if s else None
    mq = M.get('mq') or {}
    if k in mq.get('b', {}):
        prior += mq['b'][k] * (s[1] - mq['xb'][k])
    P, S = r['pts'] * R.PER, r['sn']
    for i, w in enumerate(M['marcel'][1:], 1):
        h = RATE.get(y - i, {}).get(pid)
        if h and h['grp'] == g:
            P += w * h['pts'] * R.PER
            S += w * h['sn']
    K = M['K'][g]
    return (P + K * prior) / (S + K)


def wmean(x, w):
    s = sum(w)
    return sum(a * b for a, b in zip(x, w)) / s if s else 0.0


def paired_t(d, w=None):
    """t of the mean of d (weights w: weighted mean, effective-n standard error)"""
    n = len(d)
    w = w or [1.0] * n
    sw = sum(w)
    m = sum(a * b for a, b in zip(d, w)) / sw
    v = sum(b * (a - m) ** 2 for a, b in zip(d, w)) / sw
    neff = sw ** 2 / sum(b * b for b in w)
    se = math.sqrt(v / max(neff - 1, 1))
    return m / se if se else 0.0
