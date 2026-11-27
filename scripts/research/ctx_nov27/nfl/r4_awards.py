#!/usr/bin/env python3
"""Round 2 R4 (prereg.md): the NFL award draw's games-left rate, this season's box rate a team game against a blend
with last season's.

    python3 scripts/research/ctx_nov27/nfl/r4_awards.py     # -> r4.json
"""
import json
import os
from collections import defaultdict

import common as C
import awards_nflverse as V

STATS = {'pass_y': lambda x: x.get('pass_y', 0), 'scrim': lambda x: x.get('rush_y', 0) + x.get('rec_y', 0),
         'td': lambda x: x.get('ptd', 0) + x.get('rtd', 0) + x.get('ctd', 0), 'sacks': lambda x: x.get('sacks', 0)}
G0 = (2, 4, 6, 8, 12)
CUT = 9


def season(S):
    """{pid: {stat: [to week 9, weeks 10+, season]}}, team games (to 9, after) by the player's last team to week 9"""
    W = V.nfl_weekly(S)
    tw = defaultdict(set)
    for x in W:
        tw[x['tm']].add(x['wk'])
    P = {}
    for x in W:
        p = P.setdefault(x['id'], {'tm': None, 'v': {k: [0.0, 0.0] for k in STATS}})
        if x['wk'] <= CUT:
            p['tm'] = x['tm']
        for k, f in STATS.items():
            p['v'][k][0 if x['wk'] <= CUT else 1] += f(x)
    tg = {t: (sum(1 for w in ws if w <= CUT), sum(1 for w in ws if w > CUT), len(ws)) for t, ws in tw.items()}
    return P, tg


if __name__ == '__main__':
    D = {S: season(S) for S in range(2015, 2026)}
    rows = []
    for S in range(2016, 2026):
        P, tg = D[S]
        P0, tg0 = D[S - 1]
        for k in STATS:
            top = sorted((p for p in P.items() if p[1]['tm'] and tg[p[1]['tm']][0] and tg[p[1]['tm']][1]), key=lambda p: -p[1]['v'][k][0])[:40]
            for pid, p in top:
                g, left, _ = tg[p['tm']]
                now = p['v'][k][0] / g
                q = P0.get(pid)
                prior = None
                if q:
                    tot = q['v'][k][0] + q['v'][k][1]
                    n0 = max(len({1}) and max(t[2] for t in tg0.values()), 1)
                    prior = tot / n0
                rows.append({'S': S, 'k': k, 'g': g, 'now': now, 'prior': prior, 'y': p['v'][k][1] / left})
    sd = {}
    for k in STATS:
        ys = [r['y'] for r in rows if r['k'] == k]
        m = sum(ys) / len(ys)
        sd[k] = (sum((y - m) ** 2 for y in ys) / len(ys)) ** .5
    pred = lambda r, g0: (r['now'] * r['g'] + (.85 * r['now'] if r['prior'] is None else r['prior']) * g0) / (r['g'] + g0)
    err = lambda r, p: ((p - r['y']) / sd[r['k']]) ** 2
    d, dk, by, picks = [], defaultdict(list), {}, {}
    tot = [0.0, 0.0]
    for S in range(2016, 2026):
        tr = [r for r in rows if r['S'] != S]
        g0 = min(G0, key=lambda g_: sum(err(r, pred(r, g_)) for r in tr))
        picks[S] = g0
        e0 = e1 = 0.0
        for r in rows:
            if r['S'] != S:
                continue
            a, b = err(r, r['now']), err(r, pred(r, g0))
            d.append(b - a); dk[r['k']].append(b - a)
            e0 += a; e1 += b
        tot[0] += e0; tot[1] += e1
        by[S] = e1 < e0
    out = {'n': len(d), 'mse_now': round(tot[0] / len(d), 4), 'mse_blend': round(tot[1] / len(d), 4), 't': round(C.paired_t(d), 2),
           'seasons': f'{sum(by.values())}/{len(by)}', 'g0': picks, 'byStat': {k: round(C.paired_t(v), 2) for k, v in dk.items()},
           'g0_all': min(G0, key=lambda g_: sum(err(r, pred(r, g_)) for r in rows))}
    json.dump(out, open(os.path.join(C.HERE, 'r4.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))
