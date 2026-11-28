# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Units check (Nov 28 2026): Surplus prices last season's value at last season's $ a win and takes this season's pay
above the minimum from it, so the two halves are in dollars a year apart (the cap grew 6.7% NBA, 8.9% NHL into 2026-27).
The pro team builder already carries the rate to this season's cap (pro_builder.rate_now); payrolls.py does not.

    python3 scripts/research/payrolls_nov28/cap_carry.py [nba nhl nfl mls]   -> research/payroll_cap_carry.json

Pre-registered: the carried form (rate_{s-1} x cap_s / cap_{s-1}) replaces the shipped one in payrolls.py only if, in
test.py's walk-forward on held-out next-season win% (MLS points a match), it beats the shipped Surplus with paired
t <= -2 and wins most held-out seasons."""
import gzip, json, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test as T  # noqa: E402

OUT = os.path.join(T.ROOT, 'research', 'payroll_cap_carry.json')


def run(lg):
    P = json.load(gzip.open(os.path.join(HERE, f'panel_{lg}.json.gz')))
    TS, rate = T.team_seasons(P)
    V = defaultdict(float)
    for t in TS.values():
        for q in t['pl']:
            V[(t['s'], q['id'])] += q['v'] or 0
    rows = []
    for (s, tm), n in TS.items():
        p = TS.get((s - 1, tm))
        if not p or rate.get(s - 1) is None:
            continue
        mn = n['mn']
        rv = sum(V.get((s - 1, q['id']), 0.0) for q in n['pl'])
        ra = sum(max((q['pay'] if q['pay'] is not None else mn) - mn, 0) for q in n['pl'])
        rows.append({'s': s, 'y': n['wp'], 'wp0': p['wp'], 'pay1': n['pay'] / n['cap'],
                     'old': (rate[s - 1] * rv - ra) / n['cap'], 'new': (rate[s - 1] * n['cap'] / p['cap'] * rv - ra) / n['cap']})
    ys = sorted({r['s'] for r in rows})[4:]
    err, by = defaultdict(list), defaultdict(dict)
    for y in ys:
        tr = [r for r in rows if r['s'] < y]; te = [r for r in rows if r['s'] == y]
        for k in ('old', 'new'):
            f = lambda r: [1, r['wp0'], r['pay1'], r[k]]
            w = T.ols([f(r) for r in tr], [r['y'] for r in tr])
            e = [abs(r['y'] - T.pred(w, f(r))) for r in te]
            err[k] += e; by[k][y] = sum(e) / len(e)
    d = [a - b for a, b in zip(err['new'], err['old'])]
    won = sum(1 for y in ys if by['new'][y] < by['old'][y])
    t = round(T.tstat(d), 2)
    return {'n': len(d), 'years': f'{ys[0]}-{ys[-1]}', 'maeShipped': round(sum(err['old']) / len(d), 4),
            'maeCarried': round(sum(err['new']) / len(d), 4), 't': t, 'won': f'{won}/{len(ys)}', 'pass': t <= -2 and won * 2 > len(ys)}


if __name__ == '__main__':
    out = {lg: run(lg) for lg in (sys.argv[1:] or ['nba', 'nhl', 'nfl', 'mls'])}
    for lg, r in out.items():
        print(lg, r)
    json.dump(out, open(OUT, 'w'), indent=1)
