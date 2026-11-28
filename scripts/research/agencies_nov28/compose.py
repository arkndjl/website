#!/usr/bin/env python3
"""Composite agency score (Noah, Nov 28 2026): Deal+ / Breakout+ with volume, plus players sent to the pros.

Volume enters as a total: a component is clients x the shrunk edge, n x sum(v - mu) / ((n + k) x sd), so the same mean edge
counts for more the more players it covers. (A first run used a t, sum(v - mu) / (sd x sqrt(n)): rho .313, p .008. A single
client with an extreme value scored as high as a 64-client agency, which is not what volume should do, so the total replaced
it; both results are reported. Nov 28, Noah: a big roster should not be charged per player for a low Breakout, so an edge
below the mean now counts once, as the shrunk mean, and only an edge above it is multiplied by the clients. Totals for both
signs had rho .367, p .0025.) Sent = first-round picks the agency had before the draft process (data/agency_pros.json,
low confidence not counted). Each component is z-scored across agencies and the composite is their mean.

Test, forward in time: the composite built from the clients on file now and the 2022-24 sends, against the first-round picks
each agency sent in 2025-26 (not in any input). Spearman over every agency in the ledger or the pick file, both sports
pooled, p from 2,000 shuffles. Compared with each part alone.

  python3 scripts/research/agencies_nov28/compose.py   -> research/agency_composite.json
"""
import json, math, os, random, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import agencies as A  # noqa: E402


def ranks(x):
    o = sorted(range(len(x)), key=lambda i: x[i]); r = [0.0] * len(x); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and x[o[j + 1]] == x[o[i]]: j += 1
        for k in range(i, j + 1): r[o[k]] = (i + j) / 2
        i = j + 1
    return r


def spear(a, b):
    ra, rb = ranks(a), ranks(b); n = len(a); ma = sum(ra) / n; mb = sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)); den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** .5
    return num / den if den else 0.0


def main():
    led = A.load('data/agencies.json')['rows']; pros = [p for p in A.load('data/agency_pros.json')['rows'] if p.get('conf') != 'low']
    rows = []
    for sp, col, rec in (('cfb', A.cfb_rows(), A.cfb_recruits()), ('cbb', A.cbb_rows(), A.cbb_recruits())):
        clients, _ = A.join(led, sp, col, rec)
        comp = A.components(clients, [p for p in pros if p['sport'] == sp and p['year'] <= 2024], sp, col)
        later = defaultdict(int)
        for p in pros:
            if p['sport'] == sp and p['year'] >= 2025: later[A.canon(p['agency'])] += 1
        for a in set(comp) | set(later):
            if a in A.SPECIAL: continue
            c = comp.get(a, {})
            rows.append(dict(sp=sp, a=a, y=later.get(a, 0), **{k: c.get(k, 0.0) for k in ('deal', 'breakout', 'sent', 'vol', 'score')}))
    rnd = random.Random(3); out = {'n': len(rows), 'agencies with a 2025-26 pick': sum(1 for r in rows if r['y'])}
    for k in ('score', 'sent', 'deal', 'breakout', 'vol'):
        x = [r[k] for r in rows]; y = [r['y'] for r in rows]; obs = spear(x, y); yy = y[:]; ge = 0
        for _ in range(2000):
            rnd.shuffle(yy); ge += spear(x, yy) >= obs
        out[k] = dict(rho=round(obs, 3), p=round(ge / 2000, 4))
        print(k, out[k])
    print(out['n'], 'agencies,', out['agencies with a 2025-26 pick'], 'with a 2025-26 pick')
    json.dump(out, open(os.path.join(ROOT, 'research', 'agency_composite.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
