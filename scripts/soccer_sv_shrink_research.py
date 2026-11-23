#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Shrink for SV's face-value terms (Noah, Nov 23 2026: "make saves count have shrinkage"), season-only: a player's
keeper goals saved vs xG a 90 (gk0) and finishing (goals less npxG a 90, fin) are shrunk toward the league average
(0) by k minutes, w = min / (min + k); no player-specific prior. k from split-half reliability within a season: odd
vs even league matches of each player-season (big five, 2015-26), the odd half's rate shrunk at k predicting the
even half's (and the reverse), minutes-weighted MSE, k on a grid. Writes research/soccer_sv_shrink.json.

    python3 scripts/soccer_sv_shrink_research.py
"""
import json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D, soccer_players as P

OUT = os.path.join(os.path.dirname(HERE), 'research', 'soccer_sv_shrink.json')
GRID = [0, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4000, 6000, 8000, 12000, 20000, 40000, 1e9]


def halves(S0, S1):
    """{(lg, S, player): {'pos', 'h': [[min, gks, fin], [min, gks, fin]]}} odd / even matches of each player-season"""
    acc = {}
    for S in range(S0, S1 + 1):
        for lg in D.BIG5:
            d = D.us_league(lg, S)
            ms = sorted((m for m in (d or {}).get('matches', []) if m['res']), key=lambda m: str(m.get('t')))
            seen = defaultdict(int)
            for mt in ms:
                m = D.us_match(mt['id'])
                if not m: continue
                pen = P.penalties(m)
                for r in P.parse_match(m, lg, S, mt['id']):
                    k = (lg, S, r['p'])
                    a = acc.setdefault(k, {'pos': [], 'h': [[0, 0.0, 0.0], [0, 0.0, 0.0]]})
                    h = a['h'][seen[k] % 2]; seen[k] += 1
                    h[0] += r['min']; h[1] += r['gks']; h[2] += r['g'] - (r['x'] - pen.get(r['p'], 0.0))
                    a['pos'].append(r['pos'])
        print(S, len(acc), flush=True)
    return acc


def best_k(pairs):
    """pairs: (min_a, rate_a, min_b, rate_b), rates relative to the league-season mean. -> (k, mse by k, r)"""
    out = {}
    for k in GRID:
        e = w = 0.0
        for ma, xa, mb, xb in pairs:
            for (m1, x1, m2, x2) in ((ma, xa, mb, xb), (mb, xb, ma, xa)):
                pred = x1 * m1 / (m1 + k)
                e += m2 * (x2 - pred) ** 2; w += m2
        out[k] = e / w
    kb = min(out, key=out.get)
    a = np.array([[p[1], p[3]] for p in pairs]); wt = np.array([min(p[0], p[2]) for p in pairs])
    mu = (a * wt[:, None]).sum(0) / wt.sum()
    r = float(((a[:, 0] - mu[0]) * (a[:, 1] - mu[1]) * wt).sum() / np.sqrt(((a[:, 0] - mu[0]) ** 2 * wt).sum() * ((a[:, 1] - mu[1]) ** 2 * wt).sum()))
    return kb, out, r


def main():
    S1 = D.current_season() - 1
    acc = halves(P.FIRST, S1)
    res = {}
    for key, idx, sel in (('gk0', 1, lambda a: a['pos'].count('GK') > len(a['pos']) / 2), ('fin', 2, lambda a: True)):
        rel = defaultdict(lambda: [0.0, 0.0])          # league-season mean rate a minute (players in the pool)
        for (lg, S, p), a in acc.items():
            if sel(a):
                for h in a['h']: rel[(lg, S)][0] += h[idx]; rel[(lg, S)][1] += h[0]
        pairs = []
        for (lg, S, p), a in acc.items():
            if not sel(a): continue
            (ma, *va), (mb, *vb) = a['h']
            if ma < 90 or mb < 90: continue
            mu = rel[(lg, S)][0] / rel[(lg, S)][1]
            pairs.append((ma, (va[idx - 1] / ma - mu) * 90, mb, (vb[idx - 1] / mb - mu) * 90))
        k, mse, r = best_k(pairs)
        res[key] = {'k': k if k < 1e9 else None, 'splitHalfR': round(r, 3), 'n': len(pairs),
                    'mse': {str(int(kk)) if kk < 1e9 else 'inf': round(v, 6) for kk, v in mse.items()},
                    'mseRaw': round(mse[0], 6), 'mseBest': round(mse[k], 6), 'mseZero': round(mse[1e9], 6)}
        print(key, json.dumps({x: res[key][x] for x in ('k', 'splitHalfR', 'n', 'mseRaw', 'mseBest', 'mseZero')}), flush=True)
    res['seasons'] = [P.FIRST, S1]
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
