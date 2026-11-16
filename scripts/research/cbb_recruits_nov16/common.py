# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Shared rows for the CBB recruit tests: the committed history, the shipped drivers, class-held-out scores."""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
if '--offline' not in sys.argv: sys.argv.append('--offline')
import cbb_recruit_fit as C   # noqa: E402

CP, CV = ['lrk', 'old'], ['lrk']          # the shipped kept drivers
T = list(range(30, 85, 5))                # the ladder's thresholds
OUT = '/mnt/project-files/recruits/cbb-nov16'


def load(classes):
    H = C.history()
    for r in H['recruits']:
        if (r.get('x') or {}).get('hs'): C.HS_BY[r['cls']][r['x']['hs']] += 1
    smap = C.slug_map(H)
    tr_rows = [r for r in H['recruits'] if r['cls'] in C.TRAIN]
    _, ref = C.frame(tr_rows, smap, H['teams'])
    rows = [r for r in H['recruits'] if r['cls'] in classes]
    F, _ = C.frame(rows, smap, H['teams'], ref)
    cls = np.array([r['cls'] for r in rows]); ts = np.array([float(r['rfv'] - 20) for r in rows])
    return H, rows, F, cls, ts


def tstat(d):
    d = np.asarray(d, float); s = d.std(ddof=1)
    return float(d.mean() / (s / math.sqrt(len(d)))) if s > 0 else 0.0


def place(score, cls, rk):
    """a recruit's place in his class by score (ties by consensus rank)"""
    r = np.zeros(len(score), int)
    for c in set(cls):
        i = np.where(cls == c)[0]; o = sorted(i, key=lambda j: (-score[j], rk[j]))
        for n, j in enumerate(o): r[j] = n + 1
    return r
