"""Year-over-year development for the team builder (data/cfb_dev_fit.json).

Every FBS player PFN graded in both 2024 and 2025 (scripts/cfb_transfer_fit.py's build, cached in
scripts/.cache/transfer/rows.json: ESPN ids, years in college, PFN position percentile), NIL era only: the change
in his position percentile from one season to the next, by his years in college, pooled and by position (each
position's mean shrunk to the pooled one by n / (n + SHRINK)). The team builder turns a percentile step into FV
with the board's own slope of FV on the PFN percentile at each position, then scales it so the league's
next-season total matches this season's (the talent pool is level from year to year).

python3 scripts/cfb_dev_fit.py
"""
import json, os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROWS = os.path.join(ROOT, 'scripts', '.cache', 'transfer', 'rows.json')
OUT = os.path.join(ROOT, 'data', 'cfb_dev_fit.json')
SHRINK = 40
POS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']


def main():
    rows = json.load(open(ROWS))
    by = {(r['season'], r['id']): r for r in rows}
    pool, pos = defaultdict(list), defaultdict(list)
    for r in rows:
        nxt = by.get((r['season'] + 1, r['id']))
        if r['pct'] is None or not nxt or nxt['pct'] is None or not r.get('exp'): continue
        e = min(int(r['exp']), 5)
        d = nxt['pct'] - r['pct']
        pool[e].append(d); pos[(r['g'], e)].append(d)
    mean = lambda xs: sum(xs) / len(xs)
    by_exp = {e: round(mean(xs), 4) for e, xs in sorted(pool.items())}
    # the spread around the step (breakouts and slumps), pooled over years in college
    alld = [d for xs in pool.values() for d in xs]
    sd = round((sum((d - by_exp[e]) ** 2 for e, xs in pool.items() for d in xs) / (len(alld) - len(pool))) ** 0.5, 4)
    by_pos = {}
    for g in POS:
        by_pos[g] = {}
        for e in by_exp:
            xs = pos.get((g, e), [])
            w = len(xs) / (len(xs) + SHRINK)
            by_pos[g][e] = round(w * (mean(xs) if xs else 0) + (1 - w) * by_exp[e], 4)
    out = {'pairs': '2024-25', 'n': sum(len(x) for x in pool.values()), 'nByExp': {e: len(x) for e, x in sorted(pool.items())},
           'shrink': SHRINK, 'byExp': by_exp, 'sd': sd, 'byPos': by_pos,
           'note': 'change in PFN position percentile, season to season, by years in college (5 = 5th year+), FBS players graded both seasons'}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: out[k] for k in ('n', 'nByExp', 'byExp', 'sd')}))


if __name__ == '__main__':
    main()
