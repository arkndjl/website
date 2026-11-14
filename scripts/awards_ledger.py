#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Weekly forward ledger of the award races: one row per race per week with our chance and the market price.

    python3 scripts/awards_ledger.py           append this week's rows (the awards workflow, after scripts/awards.py)
    python3 scripts/awards_ledger.py --test    self-check

Reads data/awards.json, appends to scripts/data/ledger/awards_2027.jsonl. A race gets one row per ISO week: the first
build of the week, so a week's row is never rewritten (scripts/data_push.py merges .jsonl files by line). Row:
  {"t": build time, "wk": "2026-W46", "sport", "race", "mkt": the race has a market, "rows": [[name, team, p, mkt], ...]}
with every candidate at p >= .005 or with a market price (mkt null when there is no two-sided quote).

PRE-REGISTERED SCORING (once each award is announced; a race with no winner in any of its rows scores the winner at
the floor):
  per row     log loss of the winner under p and, where the race has prices, under mkt renormalised over the listed
              candidates with a price; both floored at .005.
  1 ours      mean log loss by season share (weeks binned at 25 / 50 / 75 / 100% of the season) against the uniform
              price over the row's candidates.
  2 market    rows with a price: our log loss minus the market's, paired by race, clustered by race, by season share.
  3 sharpness slope of logit(mkt) on logit(p) over priced candidates, by season share (1 = as sharp as the market).
Nothing here feeds a model; a temperature or a market blend is fit on past seasons, never on these rows."""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data', 'awards.json')
OUT = os.path.join(ROOT, 'scripts', 'data', 'ledger', 'awards_2027.jsonl')
MIN_P = 0.005


def week(t):
    y, w, _ = dt.datetime.fromisoformat(t.replace('Z', '+00:00')).isocalendar()
    return f'{y}-W{w:02d}'


def rows_of(d):
    out = []
    for sport in sorted(d):
        s = d[sport]
        t = s.get('asof')
        if not t:
            continue
        for r in s.get('races', []):
            cand = [[c.get('n'), c.get('tm'), round(c['p'], 4), (round(c['mkt'], 4) if c.get('mkt') is not None else None)]
                    for c in r.get('rows', []) if c.get('p') is not None and (c['p'] >= MIN_P or c.get('mkt') is not None)]
            if cand:
                out.append({'t': t, 'wk': week(t), 'sport': sport, 'race': r.get('key'), 'mkt': bool(r.get('mkt')), 'rows': cand})
    return out


def have(path):
    seen = set()
    if os.path.exists(path):
        with open(path) as h:
            for line in h:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    seen.add((r['wk'], r['sport'], r['race']))
    return seen


def snap(src=SRC, out=OUT):
    with open(src) as h:
        d = json.load(h)
    seen = have(out)
    new = [r for r in rows_of(d) if (r['wk'], r['sport'], r['race']) not in seen]
    if new:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'a') as h:
            for r in new:
                h.write(json.dumps(r, separators=(',', ':'), ensure_ascii=False) + '\n')
    print(f'awards ledger: {len(new)} new rows ({len(seen)} on file)')
    return len(new)


def test():
    import tempfile
    assert week('2026-11-14T19:10:07Z') == '2026-W46'
    d = {'nba': {'asof': '2026-11-14T19:10:00Z', 'races': [{'key': 'mvp', 'mkt': True, 'rows': [
        {'n': 'A', 'tm': 'X', 'p': .6, 'mkt': .4}, {'n': 'B', 'tm': 'Y', 'p': .001, 'mkt': .02}, {'n': 'C', 'tm': 'Z', 'p': .001}]}]}}
    r = rows_of(d)
    assert len(r) == 1 and [c[0] for c in r[0]['rows']] == ['A', 'B'] and r[0]['rows'][0] == ['A', 'X', .6, .4]
    with tempfile.TemporaryDirectory() as tmp:
        s, o = os.path.join(tmp, 'a.json'), os.path.join(tmp, 'l', 'o.jsonl')
        json.dump(d, open(s, 'w'))
        assert snap(s, o) == 1 and snap(s, o) == 0
        d['nba']['asof'] = '2026-11-16T19:10:00Z'
        json.dump(d, open(s, 'w'))
        assert snap(s, o) == 1 and len(open(o).read().splitlines()) == 2
    print('awards_ledger: ok')


if __name__ == '__main__':
    test() if '--test' in sys.argv else snap()
