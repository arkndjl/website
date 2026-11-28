#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pro team builder verdicts, tested point in time: does the sign of a player's projected surplus over the next three
seasons (value on the age curve at the league's $ a win, less his pay above the minimum) call the sign of the surplus he
actually returned better than the readings a team has without a projection?

    python3 scripts/research/pro_builder_nov28/verdicts.py [nba nhl nfl]   -> research/pro_builder_verdicts.json

Rows: the payroll panels (scripts/research/payrolls_nov28/panel_<lg>.json.gz). A row is a player at the end of season s with
pay above twice the minimum and pay again in s + 1 (a contract a team carries or a new one it signs), s + 3 <= the last
full season. Pay in s + 1 .. s + 3 is what he was paid (the deal on the table at the decision; 0 after he leaves the
league, when the cost and the value both stop). Value and pay are read as cap shares (value x that season's $ a win /
cap), so seasons on different caps add.

  realized   sum_k  v(s+k) rate(s) / cap(s) - max(pay(s+k) - min, 0) / cap(s+k)
  aged       v(s+k) read as a_k,age + b_k,age v(s), the curve fit on seasons before s only (walk-forward)
  flat       a_k + b_k v(s), one curve for every age (walk-forward)
  carry      v(s) carried forward unchanged (no projection)
  last       one season: v(s) rate - (pay(s) - min), the Surplus a payroll table shows, its sign carried to the deal

Verdict = the sign of the read (keep or extend when >= 0; trade or let walk below). Score = share of rows whose verdict
matches the realized sign. Ships when aged beats carry and last on that share with paired t >= 2 (on the right-call
indicator) and wins most seasons. Flat is reported beside it. Subsets: new deal (pay in s + 1 moved more than 10% from s:
the extend / let walk calls) and same deal (the keep / trade calls)."""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PAN = os.path.join(ROOT, 'scripts', 'research', 'payrolls_nov28')
sys.path.insert(0, PAN)
from test import ols, pred, tstat  # noqa: E402
from aging import ages, bin_of, BINS  # noqa: E402

OUT = os.path.join(ROOT, 'research', 'pro_builder_verdicts.json')
EFF = json.load(open(os.path.join(ROOT, 'research', 'payroll_efficiency.json')))
K = (1, 2, 3)


def run(lg):
    P = json.load(gzip.open(os.path.join(PAN, f'panel_{lg}.json.gz')))
    S = {int(s): x for s, x in P['seasons'].items()}
    full = sorted(s for s, x in S.items() if not x.get('partial'))
    if lg == 'nfl':
        full = [s for s in full if s <= 2025]          # 2026 is the season to date
    last = max(full)
    rate = {int(y): r for y, r in EFF[lg]['ratePerWin'].items()}
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
    PW = {}
    if lg == 'nhl':          # the board's pWAR in each season file (inputs from that season; coefficients from today's fit)
        d = os.path.join(ROOT, 'static', 'data', 'nhl-war')
        for f in os.listdir(d):
            for q in json.load(open(os.path.join(d, f)))['players']:
                if q.get('pwar') is not None:
                    PW[(int(f[:4]), str(q['id']))] = q['pwar']
    # curve training rows (as payroll_aging.py): every contract season with a later season inside the panel
    tr_rows = []
    for (s, pid) in seen:
        a = A.get((s, str(pid)))
        if a is None or s not in S or PAY[(s, pid)] < 2 * S[s]['min']:
            continue
        for k in K:
            if s + k <= last:
                tr_rows.append({'s': s, 'k': k, 'b': bin_of(a), 'v': V[(s, pid)], 'y': V.get((s + k, pid), 0.0)})
    # decision rows
    rows = []
    for (s, pid) in seen:
        a = A.get((s, str(pid)))
        if a is None or s not in S or s + 3 > last or s not in rate:
            continue
        mn = S[s]['min']
        if PAY[(s, pid)] < 2 * mn or PAY.get((s + 1, pid), 0) <= 0:
            continue
        cost = [max(PAY.get((s + k, pid), 0.0) - S[s + k]['min'], 0.0) / S[s + k]['cap'] if PAY.get((s + k, pid), 0) > 0 else 0.0 for k in K]
        vr = [V.get((s + k, pid), 0.0) for k in K]
        u = rate[s] / S[s]['cap']
        rows.append({'s': s, 'b': bin_of(a), 'v': V[(s, pid)], 'u': u, 'cost': cost, 'sum3': sum(vr), 'pw': PW.get((s, str(pid))),
                     'real': sum(x * u for x in vr) - sum(cost),
                     'last': V[(s, pid)] * u - max(PAY[(s, pid)] - mn, 0.0) / S[s]['cap'],
                     'new': abs(PAY[(s + 1, pid)] - PAY[(s, pid)]) > 0.1 * PAY[(s, pid)]})
    years = sorted({r['s'] for r in rows})
    first = sorted({r['s'] for r in tr_rows})[5] if len({r['s'] for r in tr_rows}) > 5 else years[0]
    out = {m: [] for m in ('aged', 'flat', 'aged3', 'flat3', 'agedp', 'agedpw', 'carry', 'last')}
    keep, by = [], defaultdict(lambda: defaultdict(list))
    outR, byR = {m: [] for m in ('agedp', 'aged3', 'carry', 'last')}, defaultdict(lambda: defaultdict(list))
    for y in years:
        if y < first:
            continue
        te = [r for r in rows if r['s'] == y]
        W = {}
        for k in K:
            tr = [r for r in tr_rows if r['k'] == k and r['s'] + k <= y]       # outcomes seen by the end of season y
            wf = ols([[1, r['v']] for r in tr], [r['y'] for r in tr])
            wa = {}
            for b in range(len(BINS)):
                tb = [r for r in tr if r['b'] == b]
                wa[b] = ols([[1, r['v']] for r in tb], [r['y'] for r in tb]) if len(tb) > 30 else wf
            W[k] = (wf, wa)
        # the same population as the decision (paid again next season), target = the three seasons' value summed
        tr3 = [r for r in rows if r['s'] + 3 <= y]
        w3f = ols([[1, r['v']] for r in tr3], [r['sum3'] for r in tr3])
        w3a = {}
        for b in range(len(BINS)):
            tb = [r for r in tr3 if r['b'] == b]
            w3a[b] = ols([[1, r['v']] for r in tb], [r['sum3'] for r in tb]) if len(tb) > 30 else w3f
        # the deal as a read of him too: the price on the table (cap share, three seasons) beside last season's value
        def xp(r):
            return [1, r['v'], sum(r['cost'])]
        wpf = ols([xp(r) for r in tr3], [r['sum3'] for r in tr3])
        def xw(r):
            return [1, r['v'], r['pw'] if r['pw'] is not None else r['v'], sum(r['cost'])]
        wwf = ols([xw(r) for r in tr3], [r['sum3'] for r in tr3])
        wwa = {}
        for b in range(len(BINS)):
            tb = [r for r in tr3 if r['b'] == b]
            wwa[b] = ols([xw(r) for r in tb], [r['sum3'] for r in tb]) if len(tb) > 40 else wwf
        wpa = {}
        for b in range(len(BINS)):
            tb = [r for r in tr3 if r['b'] == b]
            wpa[b] = ols([xp(r) for r in tb], [r['sum3'] for r in tb]) if len(tb) > 40 else wpf
        # the market line: the realized surplus of a deal at that price (cap share over the three seasons), fit on outcomes seen
        wm = ols([[1, sum(r['cost'])] for r in tr3], [r['real'] for r in tr3])
        for r in te:
            mh = pred(wm, [1, sum(r['cost'])])
            rel = {'agedp': pred(wpa[r['b']], xp(r)) * r['u'] - sum(r['cost']) - mh,
                   'aged3': pred(w3a[r['b']], [1, r['v']]) * r['u'] - sum(r['cost']) - mh,
                   'carry': 3 * r['v'] * r['u'] - sum(r['cost']) - mh,
                   'last': 3 * r['last'] - mh}
            tr_ = r['real'] - mh >= 0
            for m, x in rel.items():
                hit = 1.0 if (x >= 0) == tr_ else 0.0
                outR[m].append(hit); byR[y][m].append(hit)
            reads = {
                'aged': sum(pred(W[k][1][r['b']], [1, r['v']]) * r['u'] for k in K) - sum(r['cost']),
                'flat': sum(pred(W[k][0], [1, r['v']]) * r['u'] for k in K) - sum(r['cost']),
                'aged3': pred(w3a[r['b']], [1, r['v']]) * r['u'] - sum(r['cost']),
                'agedp': pred(wpa[r['b']], xp(r)) * r['u'] - sum(r['cost']),
                'agedpw': pred(wwa[r['b']], xw(r)) * r['u'] - sum(r['cost']),
                'flat3': pred(w3f, [1, r['v']]) * r['u'] - sum(r['cost']),
                'carry': 3 * r['v'] * r['u'] - sum(r['cost']),
                'last': r['last'],
            }
            truth = r['real'] >= 0
            for m, x in reads.items():
                hit = 1.0 if (x >= 0) == truth else 0.0
                out[m].append(hit)
                by[y][m].append(hit)
            keep.append((r, reads))
    n = len(keep)

    def acc(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    def vs(m, other, sub=None):
        idx = [i for i, (r, _) in enumerate(keep) if sub is None or r['new'] == sub]
        d = [out[m][i] - out[other][i] for i in idx]
        won = sum(1 for y in by if by[y][m] and sum(by[y][m]) > sum(by[y][other]))
        return {'t': round(tstat(d), 2) if len(d) > 2 else None, 'won': f'{won}/{len(by)}', 'gain': round(sum(d) / len(d), 4) if d else None}
    res = {'n': n, 'years': f'{min(by)}-{max(by)}', 'acc': {m: acc(out[m]) for m in out},
           'aged_vs': {o: vs('aged', o) for o in ('carry', 'last', 'flat')},
           'aged3_vs': {o: vs('aged3', o) for o in ('carry', 'last', 'flat3', 'aged')},
           'agedp_vs': {o: vs('agedp', o) for o in ('carry', 'last', 'aged3')},
           'last_vs': {o: vs('last', o) for o in ('carry', 'agedp')},
           'agedpw_vs': {o: vs('agedpw', o) for o in ('agedp', 'carry', 'last')}}
    for name, sub in (('newDeal', True), ('sameDeal', False)):
        idx = [i for i, (r, _) in enumerate(keep) if r['new'] == sub]
        res[name] = {'n': len(idx), 'acc': {m: acc([out[m][i] for i in idx]) for m in out},
                     'aged_vs': {o: vs('aged', o, sub) for o in ('carry', 'last')},
                     'aged3_vs': {o: vs('aged3', o, sub) for o in ('carry', 'last')},
                     'agedp_vs': {o: vs('agedp', o, sub) for o in ('carry', 'last')}}
    # what the calls were worth: realized surplus (cap share) of the rows the aged read keeps vs lets go
    pos = [r['real'] for r, x in keep if x['aged'] >= 0]
    neg = [r['real'] for r, x in keep if x['aged'] < 0]
    res['realized'] = {'keep': round(sum(pos) / len(pos), 4) if pos else None, 'nKeep': len(pos),
                       'go': round(sum(neg) / len(neg), 4) if neg else None, 'nGo': len(neg)}
    def vsR(m, o):
        d = [a - b for a, b in zip(outR[m], outR[o])]
        won = sum(1 for y in byR if sum(byR[y][m]) > sum(byR[y][o]))
        return {'t': round(tstat(d), 2), 'won': f'{won}/{len(byR)}', 'gain': round(sum(d) / len(d), 4)}
    res['market'] = {'acc': {m: acc(outR[m]) for m in outR}, 'agedp_vs': {o: vsR('agedp', o) for o in ('carry', 'last', 'aged3')},
                     'last_vs': {o: vsR('last', o) for o in ('carry', 'agedp')},
                     'note': 'reads and truth less the market line (the realized surplus of a deal at that price)'}

    def beats(g, o):
        return g[o]['t'] is not None and g[o]['t'] >= 2 and int(g[o]['won'].split('/')[0]) * 2 > int(g[o]['won'].split('/')[1])
    res['pass'] = {m: beats(res[m + '_vs'], 'carry') and beats(res[m + '_vs'], 'last') for m in ('aged', 'aged3', 'agedp')}
    # the read the live builder uses: the priced projection when it beat both baselines, else the one-season Surplus when
    # it beat carrying the season forward, else none (no verdicts for the league)
    res['read'] = 'agedp' if res['pass']['agedp'] else 'last' if beats(res['last_vs'], 'carry') else None
    M = res['market']
    res['market']['pass'] = {'agedp': beats(M['agedp_vs'], 'carry') and beats(M['agedp_vs'], 'last'), 'last': beats(M['last_vs'], 'carry')}
    res['marketRead'] = 'agedp' if M['pass']['agedp'] else 'last' if M['pass']['last'] else None
    tr3 = [r for r in rows if r['s'] + 3 <= last]
    res['marketLine'] = [round(x, 5) for x in ols([[1, sum(r['cost'])] for r in tr3], [r['real'] for r in tr3])]
    # live coefficients for the priced projection: every row whose three seasons are in (no hold-out)
    allr = [r for r in rows if r['s'] + 3 <= last]
    xp = lambda r: [1, r['v'], sum(r['cost'])]  # noqa: E731
    wf = ols([xp(r) for r in allr], [r['sum3'] for r in allr])
    res['live'] = {'bins': [f'{lo}-{hi}' for lo, hi in BINS], 'all': [round(x, 4) for x in wf],
                   'b': [[round(x, 4) for x in (ols([xp(r) for r in allr if r['b'] == b], [r['sum3'] for r in allr if r['b'] == b])
                          if sum(1 for r in allr if r['b'] == b) > 40 else wf)] for b in range(len(BINS))],
                   'form': 'sum_k v(s+k) = c0 + c1 v(s) + c2 sum_k max(pay(s+k) - min, 0) / cap(s+k), by age group; value in league units, pay as cap share'}
    return res


def main():
    lgs = sys.argv[1:] or ['nba', 'nhl', 'nfl']
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for lg in lgs:
        out[lg] = run(lg)
        print(lg, json.dumps(out[lg]))
    out['note'] = __doc__.strip()
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
