# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Does an age curve read a player's value over the years left on his deal better than his last season carried forward?
The question behind a full-deal surplus and a dead-money risk: both need each later season's expected value.

    python3 scripts/research/payrolls_nov28/aging.py [nba nhl nfl]   -> research/payroll_aging.json

Player-season rows from the panels (panel_<lg>.json.gz): value v in season s and his age that season (NBA: the VORX
files, NHL: the WAR files, NFL: OverTheCap birth dates through nflverse). Target: his value k = 1, 2, 3 seasons later,
summed over teams, 0 when he no longer plays (a player who leaves the league is replaced at replacement level).
Rows: players with pay above twice the minimum in season s (the contracts a team carries forward).
  flat  v(s+k) = a_k + b_k v(s)                     the season carried forward, shrunk
  aged  v(s+k) = a_k,age + b_k,age v(s)            the same by age group (<= 24, 25-27, 28-30, 31-33, 34+)
Walk-forward: fit on seasons before s, test on s (first five seasons fit only). Ships when aged beats flat on held-out
MAE with paired t <= -2 for k = 1 and k = 3 and wins most seasons."""
import gzip, io, json, math, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
OUT = os.path.join(ROOT, 'research', 'payroll_aging.json')
sys.path.insert(0, HERE)
from test import ols, pred, tstat  # noqa: E402

BINS = [(0, 24), (25, 27), (28, 30), (31, 33), (34, 99)]


def ages(lg):
    A = {}
    if lg in ('nba', 'nhl'):
        d = os.path.join(ROOT, 'static', 'data', 'nba-xpm' if lg == 'nba' else 'nhl-war')
        for f in os.listdir(d):
            s = int(f[:4])
            for p in json.load(open(os.path.join(d, f)))['players']:
                if p.get('age') is not None:
                    A[(s, str(p['id']))] = p['age']
    else:
        import pyarrow.parquet as pq
        t = pq.read_table(os.path.join(ROOT, 'scripts', '.cache', 'payrolls', 'historical_contracts.parquet'),
                          columns=['gsis_id', 'date_of_birth']).to_pylist()
        dob = {r['gsis_id']: str(r['date_of_birth'])[-4:] for r in t if r['gsis_id'] and r['date_of_birth']}
        for g, y in dob.items():
            if y.isdigit():
                for s in range(2010, 2028):
                    A[(s, g)] = s - int(y) - 1        # age at the season's start (September), roughly
    return A


def bin_of(a):
    return next(i for i, (lo, hi) in enumerate(BINS) if lo <= a <= hi)


def run(lg):
    P = json.load(gzip.open(os.path.join(HERE, f'panel_{lg}.json.gz')))
    S = P['seasons']
    full = {int(s) for s, x in S.items() if not x.get('partial')}
    V, PAY = defaultdict(float), defaultdict(float)
    seen = set()
    for r in P['rows']:
        for q in r['pl']:
            if q.get('dead'):
                continue
            V[(r['s'], q['id'])] += q['v'] or 0
            PAY[(r['s'], q['id'])] += q['pay'] or 0
            seen.add((r['s'], q['id']))
    A = ages(lg)
    last = max(full)
    rows = []
    for (s, pid) in seen:
        a = A.get((s, str(pid)))
        if a is None or PAY[(s, pid)] < 2 * S[str(s)]['min']:
            continue
        for k in (1, 2, 3):
            if s + k > last:
                continue
            rows.append({'s': s, 'k': k, 'b': bin_of(a), 'v': V[(s, pid)], 'y': V.get((s + k, pid), 0.0),
                         'pay': PAY.get((s + k, pid), 0.0), 'mn': S[str(s + k)]['min']})
    res = {}
    for k in (1, 2, 3):
        R = [r for r in rows if r['k'] == k]
        ys = sorted({r['s'] for r in R})[5:]
        ea, ef, by = [], [], {}
        for y in ys:
            tr = [r for r in R if r['s'] + k <= y]
            te = [r for r in R if r['s'] == y]
            if not te:
                continue
            wf = ols([[1, r['v']] for r in tr], [r['y'] for r in tr])
            wa = {}
            for b in range(len(BINS)):
                tb = [r for r in tr if r['b'] == b]
                wa[b] = ols([[1, r['v']] for r in tb], [r['y'] for r in tb]) if len(tb) > 30 else wf
            a1 = [abs(r['y'] - pred(wa[r['b']], [1, r['v']])) for r in te]
            f1 = [abs(r['y'] - pred(wf, [1, r['v']])) for r in te]
            ea += a1; ef += f1; by[y] = (sum(a1) / len(a1), sum(f1) / len(f1))
        d = [x - z for x, z in zip(ea, ef)]
        won = sum(1 for a, f in by.values() if a < f)
        res[f'k{k}'] = {'n': len(d), 'maeAged': round(sum(ea) / len(ea), 4), 'maeFlat': round(sum(ef) / len(ef), 4),
                        't': round(tstat(d), 2), 'won': f'{won}/{len(by)}'}
    # the live curve, fit on every season: b_k and a_k by age group
    curve = {}
    for k in (1, 2, 3):
        R = [r for r in rows if r['k'] == k]
        curve[k] = {b: [round(x, 4) for x in ols([[1, r['v']] for r in R if r['b'] == b], [r['y'] for r in R if r['b'] == b])] for b in range(len(BINS))}
    res['curve'] = {str(k): {f'{lo}-{hi}': v[i] for i, (lo, hi) in enumerate(BINS)} for k, v in curve.items()}
    res['pass'] = all(res[f'k{k}']['t'] <= -2 and int(res[f'k{k}']['won'].split('/')[0]) * 2 > int(res[f'k{k}']['won'].split('/')[1]) for k in (1, 3))
    return res


def main():
    lgs = sys.argv[1:] or ['nba', 'nhl', 'nfl']
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for lg in lgs:
        out[lg] = run(lg)
        print(lg, json.dumps({k: v for k, v in out[lg].items() if k != 'curve'}))
    out['note'] = __doc__.strip()
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
