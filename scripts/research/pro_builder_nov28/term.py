#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""xTerm for the NFL and NBA free agent tables: the years a free agent signs for, from his age, position and price.
(The NHL has its own, scripts/xaav.py --fit-term.)

    python3 scripts/research/pro_builder_nov28/term.py [nfl nba]   -> research/pro_term.json

  NFL  OverTheCap veteran contracts (nflverse historical_contracts; 3+ years after the draft or undrafted), 2014 on:
       years on position group, age at signing, APY as a cap share and age x APY share. Held out one signing year at a time.
  NBA  free agent signings in the four offseasons before 2026-27 (Basketball-Reference transactions, the xAAV rule),
       years = seasons left on his deal now (data/payrolls/nba.json, options counted) plus the seasons already played on
       it; deals that ended early are not on file (a short deal waived is missed). Held out one offseason at a time.
Baseline = the mean years by position group x age band. Ships when the fit beats it on MAE with paired t <= -2 and wins
most held-out years."""
import json
import os
import re
import sys
import datetime as dt
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'payrolls_nov28'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from test import ols, pred, tstat  # noqa: E402
sys.path.insert(0, HERE)
from replace import NFL_G, nba_group  # noqa: E402

OUT = os.path.join(ROOT, 'research', 'pro_term.json')
BANDS = [(0, 26), (27, 29), (30, 32), (33, 99)]


def band(a):
    return next(i for i, (lo, hi) in enumerate(BANDS) if lo <= a <= hi)


def nfl_rows():
    import pyarrow.parquet as pq
    t = pq.read_table(os.path.join(ROOT, 'scripts', '.cache', 'payrolls', 'historical_contracts.parquet'),
                      columns=['position', 'year_signed', 'years', 'apy_cap_pct', 'draft_year', 'date_of_birth']).to_pylist()
    rows = []
    for r in t:
        y, n, sh, g = r['year_signed'], r['years'], r['apy_cap_pct'], NFL_G.get((r['position'] or '').upper())
        if not y or y < 2014 or y > 2025 or not n or not sh or sh != sh or not g or g == 'ST' and False:
            continue
        dy = r['draft_year']
        if dy == dy and dy is not None and y - int(dy) < 3:
            continue
        dob = str(r['date_of_birth'] or '')
        if not dob[-4:].isdigit():
            continue
        a = y - int(dob[-4:])
        if not 21 <= a <= 42:
            continue
        rows.append({'y': y, 'g': g, 'a': a, 'sh': float(sh), 'len': min(int(n), 6)})
    return rows


def nba_rows():
    import xaav as X
    T = json.load(open(os.path.join(ROOT, 'data', 'payrolls', 'nba.json')))
    by = {p['id']: p for p in T['players'] if p.get('id') and not p.get('dead')}
    now = int(T['season'])                       # the season's end year (2027 = 2026-27)
    rows = []
    for y in range(now - 3, now + 1):
        for tm, pid in X.nba_signings(y):
            p = by.get(pid)
            if not p or p.get('age') is None or not p.get('aav'):
                continue
            left = sum(1 for v in p['h'] if v is not None)
            g = nba_group(p.get('pos'))
            if not g or not left:
                continue
            rows.append({'y': y, 'g': g, 'a': p['age'] - (now - y), 'sh': p['aav'] / T['cap'], 'len': left + (now - y)})
    return rows


def feats(groups):
    def f(r):
        return [1, r['a'], r['sh'], r['a'] * r['sh']] + [1 if r['g'] == g else 0 for g in groups[1:]]
    return f


def run(lg):
    rows = nfl_rows() if lg == 'nfl' else nba_rows()
    groups = sorted({r['g'] for r in rows})
    f = feats(groups)
    ys = sorted({r['y'] for r in rows})
    ea, eb, by = [], [], {}
    for y in ys:
        tr, te = [r for r in rows if r['y'] != y], [r for r in rows if r['y'] == y]
        if not te:
            continue
        w = ols([f(r) for r in tr], [r['len'] for r in tr])
        m = defaultdict(list)
        for r in tr:
            m[(r['g'], band(r['a']))].append(r['len'])
        a = [abs(r['len'] - min(max(pred(w, f(r)), 1), 6)) for r in te]
        b = [abs(r['len'] - (sum(m[(r['g'], band(r['a']))]) / len(m[(r['g'], band(r['a']))]) if m[(r['g'], band(r['a']))] else 2)) for r in te]
        ea += a; eb += b; by[y] = sum(a) / len(a) < sum(b) / len(b)
    d = [x - z for x, z in zip(ea, eb)]
    t = round(tstat(d), 2)
    won = sum(by.values())
    w = ols([f(r) for r in rows], [r['len'] for r in rows])
    return {'n': len(rows), 'years': f'{ys[0]}-{ys[-1]}', 'maeFit': round(sum(ea) / len(ea), 3), 'maeBase': round(sum(eb) / len(eb), 3),
            't': t, 'won': f'{won}/{len(by)}', 'pass': t <= -2 and won * 2 > len(by), 'groups': groups, 'b': [round(x, 6) for x in w],
            'form': 'years = b0 + b1 age + b2 (AAV / cap) + b3 age (AAV / cap) + position group terms (first group = base), clipped 1-6 (Nov 28: the age x price term beat age squared held out, NBA t -2.95 to -2.50, NFL MAE .293 to .304)'}


def main():
    lgs = sys.argv[1:] or ['nfl', 'nba']
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for lg in lgs:
        out[lg] = run(lg)
        print(lg, json.dumps({k: v for k, v in out[lg].items() if k != 'b'}))
    out['note'] = __doc__.strip()
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
