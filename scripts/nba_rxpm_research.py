#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Can rXPM be the most descriptive NBA metric? (Nov 24 2026)

Candidate: BPM's team adjustment applied to XPM (scripts/nba_xpm.py team_adj, txpm): each team's players move by one
amount per side so minutes-weighted O-XPM x 5 = ORtg - league and D-XPM x 5 = league - DRtg.
Describe (same-season team net R2) goes to ~1 by construction, as it does for BPM and on-court +/-, so the out-of-sample
checks decide: next-season team net R2 (scripts/nba_xpm_predictive_research.py test, nine pairs) must not fall, and
next-season player XPM r (250+ MP, weighted) must not fall by more than .01. The BPM/DPM blend weight was also scanned
on next-season player BPM and DPM (avg r): .4-.5 BPM best, so the 50/50 blend stays.
-> data/nba_rxpm_research.json"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..'); sys.path.insert(0, HERE)
import nba_pxpm_research as R


def field(n, k):
    return {pid: p[k] for pid, p in R.S[n]['p'].items() if p.get(k) is not None}


def describe(vals, n):
    fill = np.mean([v for pid, v in vals.items() if R.S[n]['p'][pid]['mp'] < 500]); rows = {}
    for r in R.P[R.P.year == n].itertuples():
        rows[r.tm] = rows.get(r.tm, 0) + vals.get(r.pid, fill) * 5 * r.mp / R.TMP[(n, r.tm)]
    return [(rows[t], R.NET[(n, t)]) for t in rows if (n, t) in R.NET]


def wcorr(rows):
    a = np.array(rows); w = a[:, 2]; x, y = a[:, 0], a[:, 1]
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    return float(np.average((x - mx) * (y - my), weights=w) / np.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w)))


def blend(n, c):
    out = {}
    for pid, p in R.S[n]['p'].items():
        b, d = p.get('bpm'), p.get('dpm')
        if b is not None: out[pid] = c * b + (1 - c) * d if d is not None else b
    return out


def main():
    M = {'rXPM (team-adjusted)': 'txpm', 'XPM box blend': 'xpm', 'BPM': 'bpm', 'DPM': 'dpm'}
    res = {'metrics': {}}
    Q = {}
    for m, k in M.items():
        V = {n: field(n, k) for n in range(2011, 2026)}
        Q[m] = {n: R.team_rows(V[n], n) for n in R.TEAMPAIRS}
        pl = sum(([(V[n][pid], q['xpm'], q['mp']) for pid, q in R.S[n + 1]['p'].items() if q['mp'] >= 250 and pid in V[n]] for n in R.PLPAIRS), [])
        res['metrics'][m] = {'describe': round(R.r2(sum((describe(V[n], n) for n in R.TEAMPAIRS), [])), 4),
                             'predict': round(R.r2(sum(Q[m].values(), [])), 4), 'playerR': round(wcorr(pl), 4)}
        print(m, res['metrics'][m], flush=True)
    rng = np.random.default_rng(0); pk = [rng.choice(R.TEAMPAIRS, len(R.TEAMPAIRS)) for _ in range(2000)]
    f = lambda q: np.array([R.r2(sum((q[n] for n in p), [])) for p in pk])
    a = f(Q['rXPM (team-adjusted)'])
    res['vs'] = {m: {'p_better': round(float((a > f(Q[m])).mean()), 3),
                     'pairsBetter': int(sum(R.r2(Q['rXPM (team-adjusted)'][n]) > R.r2(Q[m][n]) for n in R.TEAMPAIRS))}
                 for m in M if m != 'rXPM (team-adjusted)'}
    res['blend'] = {}
    for c in (0, .2, .3, .4, .5, .6, .7, .8, 1.0):
        V = {n: blend(n, c) for n in range(2011, 2026)}
        r = [wcorr(sum(([(V[n][pid], q[k], q['mp']) for pid, q in R.S[n + 1]['p'].items() if q['mp'] >= 250 and pid in V[n] and q.get(k) is not None]
                        for n in R.PLPAIRS), [])) for k in ('bpm', 'dpm')]
        res['blend'][c] = {'rNextBPM': round(r[0], 4), 'rNextDPM': round(r[1], 4), 'avg': round(sum(r) / 2, 4),
                           'team': round(R.r2(sum((R.team_rows(V[n], n) for n in R.TEAMPAIRS), [])), 4)}
    t, b = res['metrics']['rXPM (team-adjusted)'], res['metrics']['XPM box blend']
    res['pass'] = t['predict'] >= b['predict'] and t['playerR'] >= b['playerR'] - .01
    print(json.dumps({k: res[k] for k in ('vs', 'blend', 'pass')}, indent=1))
    json.dump(res, open(os.path.join(ROOT, 'data', 'nba_rxpm_research.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
