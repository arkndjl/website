# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L1 attribution (after the gate, not a gate): how much of the ADD form's gain is the pooled box prior alone, the
offence coefficient, the defence coefficient.

    python3 scripts/research/sweep_nov19/soccer/l1_diag.py
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import l1_rapm as L
SP, D = L.SP, L.D


def main():
    F = json.load(open(SP.FIT))
    rows = [r for r in D.load(SP.ROWS) if r['S'] <= L.LAST]
    ts = SP.team_seasons(SP.FIRST, L.LAST)
    pri = dict(priors=SP.PRIORS, LS=SP.league_strength(), TMV=SP.tm_values())
    segs = L.segments()
    feats, lam0 = F['feats'], F['lambda']
    SP.prep(rows, F['shrink'])
    ks, X0, y = SP.design(rows, ts, feats, **pri)
    _, p0 = SP.loso(ks, X0, y, lam0)
    S = np.array([k[1] for k in ks])
    co = {s: L.fit_window(segs, rows, s, 1000.0) for s in range(SP.FIRST, L.LAST + 1)}
    box = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        for s in (r['S'], r['S'] + 1, r['S'] + 2):
            e = box[(str(r['p']), s)]
            e[0] += r['x'] - r['pen'] + r['xA']; e[1] += r['min']
    mu = {}
    for (p, s), e in box.items():
        m = mu.setdefault(s, [0.0, 0.0]); m[0] += e[0]; m[1] += e[1]
    for r in rows:
        o, d_ = co[r['S']].get(str(r['p']), (0.0, 0.0))
        e = box[(str(r['p']), r['S'])]
        m = mu[r['S']]
        r['orp'], r['drp'] = o, d_
        r['box3'] = (e[0] / e[1] * 90 - m[0] / m[1] * 90) * e[1] / (e[1] + 450) if e[1] else 0.0
        r['odev'] = o - r['box3']
    out = {}
    for name, fs in (('both', ['orp', 'drp']), ('box3 only', ['box3']), ('orp only', ['orp']), ('drp only', ['drp']),
                     ('box3 + drp', ['box3', 'drp']), ('box3 + odev + drp', ['box3', 'odev', 'drp'])):
        _, X, _ = SP.design(rows, ts, feats + fs, **pri)
        e, p = SP.loso(ks, X, y, lam0)
        d = (y - p) ** 2 - (y - p0) ** 2
        m, t = L.tstat(list(d), list(S))
        out[name] = {'d': round(float(m), 6), 't': round(float(t), 2), 'seasonsBetter': int(sum(1 for s in np.unique(S) if d[S == s].mean() < 0)),
                     'w': {a: round(float(b), 3) for a, b in zip(fs, SP.ridge(X, y, lam0)[len(feats):len(feats) + len(fs)])}}
        print(name, out[name], flush=True)
    json.dump(out, open(os.path.join(L.OUT, 'l1_diag.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
