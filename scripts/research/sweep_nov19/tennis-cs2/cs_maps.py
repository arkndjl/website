#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CS2 map rows for the sweep tests: the live team map rating (cs2_bo3.TeamMaps, finished maps only) played forward,
each played map with its pre-match round-share logit z for the match's first team. Lockbox: nothing from Nov 11 2026."""
import os, sys, json, math, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCRIPTS)
import cs2_bo3 as B   # noqa: E402
LOCK = '2026-11-11'
OUT = '/home/user/scratch-tennis-cs2/cs_maps.pkl'


def rows():
    if os.path.exists(OUT): return pickle.load(open(OUT, 'rb'))
    d = B.load()
    d = {'matches': [r for r in d['matches'] if r[1] and r[1] < LOCK], 'games': d['games']}
    bo3 = B.Bo3(d); bo3.valid_only = True
    tm = B.TeamMaps(bo3); p = tm.p
    out = []
    for m in sorted(bo3.mt.values(), key=lambda r: r[1]):
        a, b = m[2], m[3]
        for t in (a, b):
            if t not in tm.R: tm.R[t] = p['new'].get(m[10], 0.0)
        for n, g in enumerate(bo3.maps.get(m[0], [])):
            w, lo, mp = g[5], g[6], g[3]
            if {w, lo} != {a, b}: continue
            tm.recent.append((m[1][:10], mp))
            if not B.real_map(g): continue
            za = tm.R[a] + tm.Mo[(a, mp)] - tm.R[b] - tm.Mo[(b, mp)]
            out.append({'mid': m[0], 'gid': g[0], 't': m[1], 'd': m[1][:10], 'a': m[4], 'b': m[5], 'ta': a, 'tb': b, 'tier': m[10],
                        'bo': m[9], 'n': g[4], 'idx': n, 'map': mp, 'z': za, 'ya': 1 if w == a else 0, 'wr': g[7], 'lr': g[8],
                        'na': tm.n[a], 'nb': tm.n[b]})
            e = B.sig(tm.R[w] + tm.Mo[(w, mp)] - tm.R[lo] - tm.Mo[(lo, mp)])
            s = B.round_share(g[7], g[8], p['span'])
            for t, sg in ((w, 1), (lo, -1)):
                tm.R[t] += sg * p['K'] * (1 + p['Kn'] * math.exp(-tm.n[t] / 30)) * (s - e)
                tm.n[t] += 1
                tm.Mo[(t, mp)] += sg * p['Km'] / (1 + tm.nm[(t, mp)] / p['nm0']) * (s - e)
                tm.nm[(t, mp)] += 1
        if len(tm.recent) > 20000: tm.recent = tm.recent[-12000:]
    pickle.dump(out, open(OUT, 'wb'))
    return out


if __name__ == '__main__':
    r = rows(); print(len(r), r[-1])
