# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Payroll efficiency, held out, point in time: does a team's surplus (value bought beyond what the league pays for it)
tell us more about next season's wins than last season's record and next season's payroll already do?

    python3 scripts/research/payrolls_nov28/test.py [nba nfl nhl mls]   -> research/payroll_efficiency.json

Per team-season s (panel_<lg>.json.gz, PANEL.md):
  above  = sum over players of max(pay - min, 0)                        what he costs beyond a minimum player
  value  = sum of value over replacement (WAR, VORX, g+ above replacement)
  rate_s = league above / league value                                 the league's $ a win that season
  surplus_s = rate_s x value - above                                    sums to 0 over the league
Forms, each predicting win% in s+1 (MLS: points a match), fit on earlier seasons only (walk-forward, first 4 seasons fit only):
  base     win% s, payroll s+1 / cap (the roster's payroll is known before the season)
  eff      base + wins over payroll s (win% s less the season's fit on payroll s / cap: front-office efficiency)
  surplus  base + surplus s / cap of the team's s+1 roster (each s+1 player's value in s, anywhere, against his s+1 pay)
  value    base + the s+1 roster's value in s (the same roster read without pay: what the pay half adds over it)
A form ships when it beats base on held-out MAE with paired t <= -2 and wins most held-out seasons. Also reported: the
year-to-year correlation of wins over payroll (is efficiency a lasting trait of a front office)."""
import gzip, json, math, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
OUT = os.path.join(ROOT, 'research', 'payroll_efficiency.json')


def ols(X, y, ridge=1e-6):
    k = len(X[0])
    A = [[sum(x[i] * x[j] for x in X) + (ridge if i == j and i else 0) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * t for x, t in zip(X, y)) for i in range(k)]
    for i in range(k):            # gauss-jordan
        p = max(range(i, k), key=lambda r: abs(A[r][i])); A[i], A[p] = A[p], A[i]; b[i], b[p] = b[p], b[i]
        piv = A[i][i] or 1e-12
        for j in range(k):
            if j != i:
                f = A[j][i] / piv
                A[j] = [a - f * c for a, c in zip(A[j], A[i])]; b[j] -= f * b[i]
    return [b[i] / (A[i][i] or 1e-12) for i in range(k)]


def pred(w, x):
    return sum(a * c for a, c in zip(w, x))


def tstat(d):
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd else 0.0


def corr(a, b):
    n = len(a); ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a)); sb = math.sqrt(sum((x - mb) ** 2 for x in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else 0.0


def team_seasons(P):
    S = P['seasons']
    T = {}
    for r in P['rows']:
        s = r['s']; mn = S[str(s)]['min']; cap = S[str(s)]['cap'] or 1.0
        pl = [q for q in r['pl'] if not q.get('dead')]
        pay = sum((q['pay'] if q['pay'] is not None else mn) for q in pl) + sum(q['pay'] or 0 for q in r['pl'] if q.get('dead'))
        above = sum(max((q['pay'] if q['pay'] is not None else mn) - mn, 0) for q in pl) + sum(q['pay'] or 0 for q in r['pl'] if q.get('dead'))
        val = sum(q['v'] or 0 for q in pl)
        gp = r['gp'] or S[str(s)].get('gp') or 1
        T[(s, r['tm'])] = {'s': s, 'tm': r['tm'], 'wp': r['w'] / gp, 'pay': pay, 'above': above, 'val': val, 'cap': cap,
                           'mn': mn, 'pl': pl}
    rate = {}
    for s in {k[0] for k in T}:
        a = sum(t['above'] for t in T.values() if t['s'] == s); v = sum(t['val'] for t in T.values() if t['s'] == s)
        rate[s] = a / v if v > 0 else None
    for t in T.values():
        t['rate'] = rate[t['s']]
        t['surp'] = (rate[t['s']] * t['val'] - t['above']) / t['cap'] if rate[t['s']] else 0.0
    return T, rate


def run(lg):
    P = json.load(gzip.open(os.path.join(HERE, f'panel_{lg}.json.gz')))
    T, rate = team_seasons(P)
    seasons = sorted({k[0] for k in T})
    # each player's value by season (summed over teams)
    V = defaultdict(float)
    for t in T.values():
        for q in t['pl']:
            V[(t['s'], q['id'])] += q['v'] or 0
    # wins over payroll: within each season, win% less its fit on payroll / cap
    eff = {}
    for s in seasons:
        ts = [t for t in T.values() if t['s'] == s]
        w = ols([[1, t['pay'] / t['cap']] for t in ts], [t['wp'] for t in ts])
        for t in ts:
            eff[(s, t['tm'])] = t['wp'] - pred(w, [1, t['pay'] / t['cap']])
    rows = []
    for (s, tm), n in T.items():
        p = T.get((s - 1, tm))
        if not p or rate.get(s - 1) is None:
            continue
        mn = n['mn']
        ret_v = sum(V.get((s - 1, q['id']), 0.0) for q in n['pl'])
        ret_a = sum(max((q['pay'] if q['pay'] is not None else mn) - mn, 0) for q in n['pl'])
        rows.append({'s': s, 'tm': tm, 'y': n['wp'], 'wp0': p['wp'], 'pay1': n['pay'] / n['cap'], 'pay0': p['pay'] / p['cap'],
                     'eff0': eff[(s - 1, tm)], 'surp': (rate[s - 1] * ret_v - ret_a) / n['cap'], 'retv': ret_v / n['cap'] * rate[s - 1]})
    forms = {'base': lambda r: [1, r['wp0'], r['pay1']],
             'eff': lambda r: [1, r['wp0'], r['pay1'], r['eff0']],
             'surplus': lambda r: [1, r['wp0'], r['pay1'], r['surp']],
             'value': lambda r: [1, r['wp0'], r['pay1'], r['retv']]}
    ys = sorted({r['s'] for r in rows})
    test_years = ys[4:]
    err = defaultdict(list); by_year = defaultdict(dict)
    for y in test_years:
        tr = [r for r in rows if r['s'] < y]; te = [r for r in rows if r['s'] == y]
        for k, f in forms.items():
            w = ols([f(r) for r in tr], [r['y'] for r in tr])
            e = [abs(r['y'] - pred(w, f(r))) for r in te]
            err[k] += e; by_year[k][y] = sum(e) / len(e)
    res = {'n': len(err['base']), 'years': f'{test_years[0]}-{test_years[-1]}', 'maeBase': round(sum(err['base']) / len(err['base']), 4)}
    for k in ('eff', 'surplus', 'value'):
        d = [a - b for a, b in zip(err[k], err['base'])]
        won = sum(1 for y in test_years if by_year[k][y] < by_year['base'][y])
        res[k] = {'mae': round(sum(err[k]) / len(err[k]), 4), 't': round(tstat(d), 2), 'won': f'{won}/{len(test_years)}',
                  'pass': tstat(d) <= -2 and won * 2 > len(test_years)}
    d = [a - b for a, b in zip(err['surplus'], err['value'])]
    won = sum(1 for y in test_years if by_year['surplus'][y] < by_year['value'][y])
    res['surplusVsValue'] = {'t': round(tstat(d), 2), 'won': f'{won}/{len(test_years)}'}
    # is efficiency a lasting trait? r of wins over payroll year to year
    a = [(eff[(s - 1, tm)], eff[(s, tm)]) for (s, tm) in eff if (s - 1, tm) in eff]
    res['effYoY'] = round(corr([x for x, _ in a], [y for _, y in a]), 3)
    full = ols([forms['surplus'](r) for r in rows], [r['y'] for r in rows])
    res['coefSurplus'] = [round(x, 4) for x in full]
    res['ratePerWin'] = {str(s): round(v, 3) for s, v in sorted(rate.items()) if v}
    res['meanPayCap'] = round(sum(t['pay'] / t['cap'] for t in T.values()) / len(T), 3)
    return res


def main():
    lgs = sys.argv[1:] or ['nba', 'nfl', 'nhl', 'mls']
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for lg in lgs:
        if not os.path.exists(os.path.join(HERE, f'panel_{lg}.json.gz')):
            print(lg, 'no panel'); continue
        out[lg] = run(lg)
        print(lg, json.dumps({k: v for k, v in out[lg].items() if k != 'ratePerWin'}))
    out['note'] = __doc__.strip()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
