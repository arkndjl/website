#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Shared pieces for the tennis sweep tests: the audit harness (lockbox cut Nov 10 2026), column picks, clustered t."""
import os, sys, json, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(SCRIPTS, 'research', 'tennis_nov13'))
from base import M, T, LOCK, load_rows, live_P          # noqa: E402,F401
from mtests import newton, arrays, wf_logit, nll        # noqa: E402,F401
import numpy as np                                      # noqa: E402
from scipy import stats                                 # noqa: E402
CACHE = os.path.join(SCRIPTS, '.cache', 'tennis', 'sweep19')
os.makedirs(CACHE, exist_ok=True)
RES = '/mnt/project-files/research-sweep-nov19/impl/tennis-cs2/'
NB = len(M.NAMES)                    # live blend inputs recorded per row
LIVE = list(M.ALL)                   # the columns the live blend uses


def tclust(d, g):
    """mean x 1e4, t clustered by g, one-sided p (lower is better), n"""
    s = {}
    for v, k in zip(d, g): s[k] = s.get(k, 0.0) + v
    a = np.array(list(s.values()))
    if len(a) < 3 or a.std(ddof=1) == 0: return None
    t = a.sum() / (a.std(ddof=1) * len(a) ** .5)
    return {'n': int(len(d)), 'd1e4': round(float(np.mean(d) * 1e4), 2), 't': round(float(t), 2),
            'p1': float(stats.t.cdf(t, len(a) - 1)), 'clusters': int(len(a))}


def save(name, obj):
    json.dump(obj, open(os.path.join(HERE, name + '.json'), 'w'), indent=1, default=str)
    try: json.dump(obj, open(os.path.join(RES, name + '.json'), 'w'), indent=1, default=str)
    except OSError: pass
