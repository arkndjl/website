#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB Next VORX on the position replacement lines (units sweep, Nov 28 2026).

The board's VORX moved to dated position lines in #1386 (scripts/repl_levels.py: season y's lines come from the three
finished seasons before it, so they are point in time). Next (scripts/cbb_next.py) was still fit to VORX on the flat
-1.4 line. Target here: next season's VORX on season y's position line, the number the board shows.

    A   the live form: M2 fit to flat-line VORX, its prediction as it is
    A2  A moved onto the line by last season's minutes share: + (-1.4 - L(pos, y)) x min% / 100 x K
    B   M2 refit on the position-line target, last season's VORX input on season y-1's lines

Walk-forward as scripts/cbb_next_research.py (fit on target seasons before y, test y = 2016..2026; returners and D-I
transfers). Pre-registered: B ships if its RMSE beats A, paired t <= -2 by player and wins most seasons.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SC)
import cbb_roster as R
import cbb_next_research as N
import repl_levels as RL
from cbb_next import K, POSMAP, REPL

OUT = os.path.join(os.path.dirname(SC), 'research', 'cbb_next_line.json')
f = R.f


def wline(x, mp, pos, y):
    return (x - RL.cbb_line(pos, y)) * mp / 100 * K


def main():
    by = R.load_seasons(); ts = R.team_strength(by); pm = N.posmeans(by)
    rows = defaultdict(list)
    for y in sorted(by):
        if y - 1 not in by: continue
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            k = R.kind(r, p, h)
            if k not in ('ret', 'tr'): continue
            x = R.xrow(k, r, h if h else N.withpx(p, pid, y - 1), ts, y)
            pos = POSMAP.get(r['role'], 'F'); pp = POSMAP.get(p['role'], 'F')
            xn, xp = N.xpm(r, pid, y), N.xpm(p, pid, y - 1)
            mp, mq = f(r['min_per'], 0), f(p['min_per'], 0)
            rows[y].append({'x': x, 'e': N.extra(p, pm[y - 1], pid, y - 1), 'pos': pos, 'mq': mq,
                            'flat': (xn - REPL) * mp / 100 * K, 'tgt': wline(xn, mp, pos, y),
                            'curF': (xp - REPL) * mq / 100 * K, 'curL': wline(xp, mq, pp, y - 1), 'y': y})
    E = defaultdict(list)
    per = defaultdict(dict)
    for y in range(N.FIRST, N.LAST + 1):
        tr = [q for yy in rows if yy < y for q in rows[yy]]; te = rows[y]
        cA = N.ols([q['x'] + [q['curF']] + q['e'] for q in tr], [q['flat'] for q in tr])
        cB = N.ols([q['x'] + [q['curL']] + q['e'] for q in tr], [q['tgt'] for q in tr])
        for q in te:
            a = float(np.dot(cA, q['x'] + [q['curF']] + q['e']))
            a2 = a + (REPL - RL.cbb_line(q['pos'], y)) * q['mq'] / 100 * K
            b = float(np.dot(cB, q['x'] + [q['curL']] + q['e']))
            for m, v in (('A', a), ('A2', a2), ('B', b)): E[m].append((y, v, q['tgt'], q['pos']))
    out = {}
    base = np.array([(v - t) ** 2 for _, v, t, _ in E['A']])
    for m, L in E.items():
        e = np.array([(v - t) ** 2 for _, v, t, _ in L]); d = e - base
        t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if m != 'A' else 0.0
        ys = sorted({y for y, *_ in L})
        by_y = {y: (float(np.sqrt(np.mean([(v - tt) ** 2 for yy, v, tt, _ in L if yy == y]))),
                    float(np.sqrt(np.mean([(v - tt) ** 2 for yy, v, tt, _ in E['A'] if yy == y])))) for y in ys}
        sd = np.array([a - b for a, b in by_y.values()])
        bias = {p: round(float(np.mean([v - tt for _, v, tt, pp in L if pp == p])), 4) for p in ('G', 'F', 'C')}
        out[m] = {'n': len(L), 'rmse': round(float(np.sqrt(e.mean())), 4), 't_players': round(t, 2),
                  't_seasons': round(float(sd.mean() / (sd.std(ddof=1) / math.sqrt(len(sd)))), 2) if m != 'A' else 0.0,
                  'won': sum(1 for a, b in by_y.values() if a < b), 'of': len(by_y), 'bias_by_pos': bias,
                  'slope': round(float(np.polyfit([v for _, v, _, _ in L], [tt for _, _, tt, _ in L], 1)[0]), 3)}
        print(m, out[m])
    B = out['B']
    out['verdict'] = 'pass' if B['rmse'] < out['A']['rmse'] and B['t_players'] <= -2 and B['won'] > B['of'] / 2 else 'fail'
    json.dump({'built': 'scripts/research/units_nov28/cbb_next_line.py', 'walk_forward': [N.FIRST, N.LAST], 'models': out}, open(OUT, 'w'), indent=1)
    print(out['verdict'], OUT)


if __name__ == '__main__':
    main()
