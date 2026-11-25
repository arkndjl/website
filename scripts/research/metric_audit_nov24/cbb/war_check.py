#!/usr/bin/env python3
"""Confirmation of D1 on the board's own WAR form (scripts/cbb_tabs.py fit_wpp): team wins = a x games + b x sum((X - R) x
minutes / 40 x .68), X = BPM (shipped) or GBPM, R = the 9th man's minutes-weighted X that season set (pooled), fit leave one
season out on 2013-2026 team-seasons (20+ games), scored on the held-out season's wins. -> war_check.json"""
import json, math, os, sys
import numpy as np
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit as A
YS = list(range(2013, 2027))


def ninth(y, k):
    """minutes-weighted k of each team's 9th man in minutes, pooled"""
    by = defaultdict(list)
    for pid, t, e in A.S[y]['parts']: by[t].append((e, A.S[y]['pl'][pid][k]))
    L = [sorted(v, reverse=True)[8] for v in by.values() if len(v) >= 9]
    return sum(e * x for e, x in L) / sum(e for e, _ in L)


def rows(k, R):
    out = {}
    for y in YS:
        X = defaultdict(float)
        for pid, t, e in A.S[y]['parts']: X[t] += (A.S[y]['pl'][pid][k] - R) * e / 40 * .68
        out[y] = [(g, X[t], w) for t, (w, g) in A.S[y]['wp'].items() if g >= 20 and t in X]
    return out


res = {}
for k in ('bpm', 'gbpm'):
    R = float(np.mean([ninth(y, k) for y in YS])); Rw = rows(k, R); sse = {}
    for y in YS:
        tr = [r for s in YS if s != y for r in Rw[s]]
        c = np.linalg.lstsq(np.array([[g, x] for g, x, _ in tr]), np.array([w for *_, w in tr]), rcond=None)[0]
        sse[y] = float(sum((w - c[0] * g - c[1] * x) ** 2 for g, x, w in Rw[y]))
    c = np.linalg.lstsq(np.array([[g, x] for y in YS for g, x, _ in Rw[y]]), np.array([w for y in YS for *_, w in Rw[y]]), rcond=None)[0]
    res[k] = {'repl': round(R, 3), 'a': round(float(c[0]), 4), 'wpp': round(float(c[1]), 5), 'heldRMSE': round(math.sqrt(sum(sse.values()) / sum(len(Rw[y]) for y in YS)), 4), 'sse': sse}
d = np.array([res['bpm']['sse'][y] - res['gbpm']['sse'][y] for y in YS])
res['t'] = round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2); res['seasonsBetter'] = int((d > 0).sum()); res['of'] = len(YS)
for k in ('bpm', 'gbpm'): res[k].pop('sse')
print(res); json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'war_check.json'), 'w'), indent=1)
