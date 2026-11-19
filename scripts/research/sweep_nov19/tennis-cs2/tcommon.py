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


class Resolver:
    """player name -> our id inside one tour, through scripts/names.py (exact key, then names.same among players
    with a match in the window); a name two ids share stays unresolved"""
    def __init__(self, players, rows, since=20100101):
        sys.path.insert(0, SCRIPTS)
        import names
        self.nm = names
        act = set()
        for r in rows:
            if r[0] >= since: act.add(r[7]); act.add(r[8])
        self.by = {'atp': {}, 'wta': {}}; self.last = {'atp': {}, 'wta': {}}
        for pid in act:
            n = (players.get(pid) or {}).get('n')
            if not n: continue
            tour = 'atp' if pid[0] == 'a' else 'wta'
            k = names.key(n)
            self.by[tour].setdefault(k, []).append(pid)
            for tok in set(k.split()): self.last[tour].setdefault(tok, []).append((pid, n))
        self.memo = {}

    def pid(self, name, tour):
        k = (name, tour)
        if k in self.memo: return self.memo[k]
        kk = self.nm.key(name)
        c = self.by[tour].get(kk, [])
        if not c:                                  # names.same among players who share a name token
            cand = {}
            for tok in set(kk.split()):
                for p, n in self.last[tour].get(tok, []): cand[p] = n
            c = [p for p, n in cand.items() if self.nm.same(name, n)]
        self.memo[k] = c[0] if len(c) == 1 else None
        return self.memo[k]


def dord(d):
    import datetime as dt
    return dt.date(d // 10000, d // 100 % 100, d % 100).toordinal()
