#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Future score for the pro team builder: how good a team will be over the next three seasons, tested point in time
against the wins it went on to get.

    python3 scripts/research/pro_builder_nov28/future.py [nba nhl nfl]   -> research/pro_builder_future.json

Team rows are the payroll panels (scripts/research/payrolls_nov28/panel_<lg>.json.gz): a team at the end of season s, its
players with value v (VORX, WAR) and age. Target = its mean win share over s + 1 .. s + 3 (s + 3 <= the last full season).

  roster    sum over his players of E_k(v, age) x P_k(stay), k = 1 .. 3: the age curve (a_k + b_k v by age group) and the
            share of players in his age group and value third still on the team k seasons on, both fit on seasons whose
            outcome was seen by the end of s (walk-forward); the three seasons averaged
  now       the team's value in season s (sum of v)
  carry     its win share in s
  roster+   roster and carry together
Each read is mapped to the target by a line fit on the earlier team rows. Ships when it beats now and carry on held-out
absolute error, paired t <= -2, and wins most seasons. Picks and cap room have no history on file and are not in it."""
import gzip
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PAN = os.path.join(ROOT, 'scripts', 'research', 'payrolls_nov28')
sys.path.insert(0, PAN)
from test import ols, pred, tstat  # noqa: E402
from aging import ages, bin_of, BINS  # noqa: E402

OUT = os.path.join(ROOT, 'research', 'pro_builder_future.json')
K = (1, 2, 3)
STAY = os.environ.get('STAY', 'v')


def tier(v, cuts):
    return 0 if v < cuts[0] else 1 if v < cuts[1] else 2


def fit_parts(pl_rows, y, last):
    """age curve and stay rates from player-seasons whose k-th season was seen by the end of y"""
    E, P = {}, {}
    vs = sorted(r['pt'] for r in pl_rows if r['s'] <= y)
    cuts = (vs[len(vs) // 3], vs[2 * len(vs) // 3])
    for k in K:
        tr = [r for r in pl_rows if r['s'] + k <= min(y, last)]
        wf = ols([[1, r['v']] for r in tr], [r['y'][k - 1] for r in tr])
        E[k] = {}
        for b in range(len(BINS)):
            tb = [r for r in tr if r['b'] == b]
            E[k][b] = ols([[1, r['v']] for r in tb], [r['y'][k - 1] for r in tb]) if len(tb) > 30 else wf
        cnt = defaultdict(lambda: [0, 0])
        for r in tr:
            c = cnt[(r['b'], tier(r['pt'], cuts))]
            c[0] += r['st'][k - 1]; c[1] += 1
        P[k] = {key: (a + 1) / (n + 2) for key, (a, n) in cnt.items()}
    return E, P, cuts


def score(team_pl, E, P, cuts):
    tot = 0.0
    for k in K:
        for q in team_pl:
            e = pred(E[k][q['b']], [1, q['v']])
            tot += e * P[k].get((q['b'], tier(q['pt'], cuts)), 0.5)
    return tot / len(K)


def run(lg):
    Pn = json.load(gzip.open(os.path.join(PAN, f'panel_{lg}.json.gz')))
    S = {int(s): x for s, x in Pn['seasons'].items()}
    full = sorted(s for s, x in S.items() if not x.get('partial'))
    if lg == 'nfl':
        full = [s for s in full if s <= 2025]
    last = max(full)
    A = ages(lg)
    T = {}
    V = defaultdict(float)
    ON = set()
    for r in Pn['rows']:
        T[(r['s'], r['tm'])] = r
        for q in r['pl']:
            if not q.get('dead'):
                V[(r['s'], q['id'])] += q['v'] or 0
                ON.add((r['s'], r['tm'], q['id']))
    pl_rows, teams = [], []
    for (s, tm), r in T.items():
        if s not in full:
            continue
        gp = r.get('gp') or 0
        if not gp or r.get('w') is None:
            continue
        pl = []
        for q in r['pl']:
            a = A.get((s, str(q['id'])))
            if q.get('dead') or a is None:
                continue
            row = {'s': s, 'b': bin_of(min(max(int(a), 0), 99)), 'v': q['v'] or 0, 'pt': (q['pay'] or 0) / S[s]['cap'] if STAY == 'pay' else (q['v'] or 0), 'y': [V.get((s + k, q['id']), 0.0) for k in K],
                   'st': [1 if (s + k, tm, q['id']) in ON else 0 for k in K]}
            pl.append(row); pl_rows.append(row)
        fut = [T.get((s + k, tm)) for k in K]
        target = None
        if s + 3 <= last and all(f and f.get('gp') for f in fut):
            target = sum(f['w'] / f['gp'] for f in fut) / 3
        teams.append({'s': s, 'tm': tm, 'pl': pl, 'wp': r['w'] / gp, 'now': sum(q['v'] for q in pl), 'y': target})
    ys = sorted({t['s'] for t in teams if t['y'] is not None})
    first = ys[4]
    err = {m: [] for m in ('roster', 'now', 'carry', 'rosterp')}
    by = defaultdict(lambda: defaultdict(list))
    for y in ys:
        if y < first:
            continue
        E, P, cuts = fit_parts(pl_rows, y, last)
        for t in teams:
            t['_fs'] = score(t['pl'], E, P, cuts) if t['s'] <= y else None
        tr = [t for t in teams if t['y'] is not None and t['s'] + 3 <= y]
        te = [t for t in teams if t['s'] == y and t['y'] is not None]
        if len(tr) < 60 or not te:
            continue
        feats = {'roster': lambda t: [1, t['_fs']], 'now': lambda t: [1, t['now']], 'carry': lambda t: [1, t['wp']],
                 'rosterp': lambda t: [1, t['_fs'], t['wp']]}
        for m, f in feats.items():
            w = ols([f(t) for t in tr], [t['y'] for t in tr])
            for t in te:
                e = abs(t['y'] - pred(w, f(t)))
                err[m].append(e); by[y][m].append(e)

    def vs(m, o):
        d = [a - b for a, b in zip(err[m], err[o])]
        won = sum(1 for y in by if sum(by[y][m]) < sum(by[y][o]))
        return {'t': round(tstat(d), 2), 'won': f'{won}/{len(by)}'}

    def beats(g):
        return g['t'] <= -2 and int(g['won'].split('/')[0]) * 2 > int(g['won'].split('/')[1])
    res = {'n': len(err['roster']), 'years': f'{min(by)}-{max(by)}', 'mae': {m: round(sum(e) / len(e), 4) for m, e in err.items()},
           'roster_vs': {o: vs('roster', o) for o in ('now', 'carry')}, 'rosterp_vs': {o: vs('rosterp', o) for o in ('now', 'carry', 'roster')}}
    res['pass'] = {m: beats(res[m + '_vs']['now']) and beats(res[m + '_vs']['carry']) for m in ('roster', 'rosterp')}
    res['read'] = 'rosterp' if res['pass']['rosterp'] and beats(res['rosterp_vs']['roster']) else 'roster' if res['pass']['roster'] \
        else 'rosterp' if res['pass']['rosterp'] else None
    # live parts: every season
    E, P, cuts = fit_parts(pl_rows, last, last)
    for t in teams:
        t['_fs'] = score(t['pl'], E, P, cuts)
    tr = [t for t in teams if t['y'] is not None]
    res['live'] = {'E': {str(k): {str(b): [round(x, 5) for x in E[k][b]] for b in E[k]} for k in K},
                   'P': {str(k): {f'{b},{c}': round(x, 4) for (b, c), x in P[k].items()} for k in K},
                   'cuts': [round(x, 4) for x in cuts],
                   'roster': [round(x, 6) for x in ols([[1, t['_fs']] for t in tr], [t['y'] for t in tr])],
                   'rosterp': [round(x, 6) for x in ols([[1, t['_fs'], t['wp']] for t in tr], [t['y'] for t in tr])],
                   'bins': [f'{lo}-{hi}' for lo, hi in BINS]}
    return res


def main():
    lgs = sys.argv[1:] or ['nba', 'nhl', 'nfl']
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for lg in lgs:
        out[lg] = run(lg)
        print(lg, json.dumps({k: v for k, v in out[lg].items() if k != 'live'}))
    out['note'] = __doc__.strip()
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
