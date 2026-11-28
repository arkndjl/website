#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pro team builder verdicts against the replacement a team could buy, tested point in time, and the core tag.

    python3 scripts/research/pro_builder_nov28/replace.py [nba nhl nfl]   -> research/pro_builder_replace.json

Rows are the verdict rows of verdicts.py (a player paid at least twice the minimum at the end of season s and paid again in
s + 1; s + 3 <= the last full season). cost = his pay above the minimum as a cap share, summed over s + 1 .. s + 3.

  replacement line   what that money bought on the market at his position: the three seasons' value of new deals
                     (pay in s + 1 moved more than 10% from s) at the position, on their cost, R(c, pos) = a + b c,
                     fit on the deals whose three seasons were seen by the end of season s (walk-forward); a position
                     with fewer than 60 deals uses every position's line
  truth              sum_k v(s+k) >= R(cost, pos) on the line fit on every season (he beat what his money buys)
  agedp              the priced projection of verdicts.py (three seasons' value = c0 + c1 v + c2 cost by age group,
                     walk-forward) >= R(cost, pos)
  carry              3 v(s) >= R(cost, pos)
  pooled             agedp against one line for every position (does the position matter)

Ships when agedp beats carry with paired t >= 2 on the right-call indicator and wins most seasons. Positions: NBA
G / F / C (the XPM files), NHL F / D / G, NFL QB, RB, WR, TE, OL, DL, ED, LB, DB, ST (OverTheCap's position, nflverse).

Core: a player whose projected value over the next three seasons is among his team's top two and in the league's top 15%,
age 31 or under. Test: among rows whose agedp read says trade or let walk, did core players beat their replacement more
often than not (then the read should not move them: a core player is kept)."""
import gzip
import json
import os
import sys
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PAN = os.path.join(ROOT, 'scripts', 'research', 'payrolls_nov28')
sys.path.insert(0, PAN)
from test import ols, pred, tstat  # noqa: E402
from aging import ages, bin_of, BINS  # noqa: E402

OUT = os.path.join(ROOT, 'research', 'pro_builder_replace.json')
EFF = json.load(open(os.path.join(ROOT, 'research', 'payroll_efficiency.json')))
K = (1, 2, 3)
NFL_G = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'LT': 'OL', 'LG': 'OL', 'C': 'OL', 'RG': 'OL', 'RT': 'OL',
         'OL': 'OL', 'IDL': 'DL', 'DT': 'DL', 'DL': 'DL', 'ED': 'ED', 'DE': 'ED', 'EDGE': 'ED', 'LB': 'LB', 'ILB': 'LB', 'OLB': 'ED',
         'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB', 'DB': 'DB', 'K': 'ST', 'P': 'ST', 'LS': 'ST'}
MIN_POS = 60
CORE_TOP, CORE_PCT, CORE_AGE = 2, 0.15, 31


def nba_group(p):
    p = (p or '').upper().split('-')[0].split('/')[0]
    return 'C' if p == 'C' else 'G' if p in ('PG', 'SG', 'G') else 'F' if p in ('SF', 'PF', 'F') else None


def positions(lg):
    """(season, id) -> position group, and id -> the latest group (a fallback for seasons he is not on file)"""
    P, last = {}, {}
    if lg in ('nba', 'nhl'):
        d = os.path.join(ROOT, 'static', 'data', 'nba-xpm' if lg == 'nba' else 'nhl-war')
        for f in sorted(os.listdir(d)):
            s = int(f[:4])
            for p in json.load(open(os.path.join(d, f)))['players']:
                g = nba_group(p.get('pos')) if lg == 'nba' else (p.get('grp') or '').upper()[:1] or None
                if g:
                    P[(s, str(p['id']))] = g; last[str(p['id'])] = g
    else:
        import pyarrow.parquet as pq
        t = pq.read_table(os.path.join(ROOT, 'scripts', '.cache', 'payrolls', 'historical_contracts.parquet'),
                          columns=['gsis_id', 'position', 'year_signed']).to_pylist()
        for r in sorted(t, key=lambda r: r['year_signed'] or 0):
            g = NFL_G.get((r['position'] or '').upper())
            if r['gsis_id'] and g:
                last[r['gsis_id']] = g
    return P, last


def group_of(lg, P, last, s, pid):
    return P.get((s, str(pid))) or last.get(str(pid))


def rows_of(lg):
    Pn = json.load(gzip.open(os.path.join(PAN, f'panel_{lg}.json.gz')))
    S = {int(s): x for s, x in Pn['seasons'].items()}
    full = sorted(s for s, x in S.items() if not x.get('partial'))
    if lg == 'nfl':
        full = [s for s in full if s <= 2025]
    last = max(full)
    rate = {int(y): r for y, r in EFF[lg]['ratePerWin'].items()}
    V, PAY, TM = defaultdict(float), defaultdict(float), {}
    seen = set()
    for r in Pn['rows']:
        for q in r['pl']:
            if q.get('dead'):
                continue
            V[(r['s'], q['id'])] += q['v'] or 0
            PAY[(r['s'], q['id'])] += q['pay'] or 0
            k = (r['s'], q['id'])
            if k not in TM or (q['pay'] or 0) > TM[k][1]:
                TM[k] = (r['tm'], q['pay'] or 0)
            seen.add(k)
    A = ages(lg)
    PS, PL = positions(lg)
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
        rows.append({'s': s, 'id': pid, 'tm': TM[(s, pid)][0], 'age': a, 'b': bin_of(a), 'v': V[(s, pid)], 'c': sum(cost),
                     'sum3': sum(vr), 'pos': group_of(lg, PS, PL, s, pid) or '?',
                     'new': abs(PAY[(s + 1, pid)] - PAY[(s, pid)]) > 0.1 * PAY[(s, pid)]})
    return rows, last


def lines(tr):
    """replacement line by position (new deals only), pooled line for thin positions"""
    deals = [r for r in tr if r['new']]
    pool = ols([[1, r['c']] for r in deals], [r['sum3'] for r in deals])
    by = {}
    for g in {r['pos'] for r in deals}:
        d = [r for r in deals if r['pos'] == g]
        by[g] = ols([[1, r['c']] for r in d], [r['sum3'] for r in d]) if len(d) >= MIN_POS else pool
    return by, pool


def proj(tr):
    """the priced projection, by age group (verdicts.py agedp)"""
    xp = lambda r: [1, r['v'], r['c']]  # noqa: E731
    wf = ols([xp(r) for r in tr], [r['sum3'] for r in tr])
    return {b: (ols([xp(r) for r in tr if r['b'] == b], [r['sum3'] for r in tr if r['b'] == b])
                if sum(1 for r in tr if r['b'] == b) > 40 else wf) for b in range(len(BINS))}, xp


def run(lg):
    rows, last = rows_of(lg)
    years = sorted({r['s'] for r in rows})
    first = years[5]
    LT, PT = lines(rows)                                          # the truth line: every season
    hits = {m: [] for m in ('agedp', 'carry', 'pooled')}
    by = defaultdict(lambda: defaultdict(list))
    core_rows = []
    for y in years:
        if y < first:
            continue
        tr = [r for r in rows if r['s'] + 3 <= y]
        te = [r for r in rows if r['s'] == y]
        if not te or len(tr) < 200:
            continue
        L, Lp = lines(tr)
        W, xp = proj(tr)
        # core inside the test season: projected three seasons' value, ranked on the team and in the league
        e3 = {id(r): pred(W[r['b']], xp(r)) for r in te}
        cut = sorted(e3.values(), reverse=True)[max(int(CORE_PCT * len(te)) - 1, 0)]
        team = defaultdict(list)
        for r in te:
            team[r['tm']].append(e3[id(r)])
        for r in te:
            rep = pred(L.get(r['pos'], Lp), [1, r['c']])
            truth = r['sum3'] >= pred(LT.get(r['pos'], PT), [1, r['c']])
            reads = {'agedp': e3[id(r)] - rep, 'carry': 3 * r['v'] - rep, 'pooled': e3[id(r)] - pred(Lp, [1, r['c']])}
            for m, x in reads.items():
                h = 1.0 if (x >= 0) == truth else 0.0
                hits[m].append(h); by[y][m].append(h)
            top = sorted(team[r['tm']], reverse=True)[:CORE_TOP]
            core = e3[id(r)] >= cut and e3[id(r)] >= min(top) and r['age'] <= CORE_AGE
            if core:
                core_rows.append({'neg': reads['agedp'] < 0, 'truth': truth})

    def vs(m, o):
        d = [a - b for a, b in zip(hits[m], hits[o])]
        won = sum(1 for y in by if sum(by[y][m]) > sum(by[y][o]))
        return {'t': round(tstat(d), 2), 'won': f'{won}/{len(by)}', 'gain': round(sum(d) / len(d), 4)}

    def beats(g):
        return g['t'] >= 2 and int(g['won'].split('/')[0]) * 2 > int(g['won'].split('/')[1])
    res = {'n': len(hits['agedp']), 'years': f'{min(by)}-{max(by)}',
           'acc': {m: round(sum(h) / len(h), 4) for m, h in hits.items()},
           'agedp_vs': {o: vs('agedp', o) for o in ('carry', 'pooled')},
           'deals': Counter(r['pos'] for r in rows if r['new'])}
    res['pass'] = beats(res['agedp_vs']['carry'])
    res['posPass'] = beats(res['agedp_vs']['pooled'])
    # core rows whose read was below the line: how often they beat it anyway (override is right when over half did)
    cn = [c for c in core_rows if c['neg']]
    res['core'] = {'n': len(core_rows), 'nNeg': len(cn), 'negBeat': round(sum(1 for c in cn if c['truth']) / len(cn), 4) if cn else None,
                   'acc': round(sum(1 for c in core_rows if (not c['neg']) == c['truth']) / len(core_rows), 4) if core_rows else None,
                   'rule': f'top {CORE_TOP} on his team and top {int(CORE_PCT * 100)}% in the league in projected three seasons\' value, age {CORE_AGE} or under'}
    res['core']['override'] = bool(cn) and res['core']['negBeat'] > 0.5
    # live coefficients: replacement lines on every season
    res['live'] = {'pos': {g: [round(x, 5) for x in w] for g, w in LT.items()}, 'pool': [round(x, 5) for x in PT],
                   'form': 'three seasons\' value a new deal at the position returned = a + b cost (cap share above the minimum, three seasons)'}
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
