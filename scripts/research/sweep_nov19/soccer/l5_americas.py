# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L5: one strength per league for MLS, Liga MX, Brazil and Argentina, learned only from their cross-league cup
matches, against the same club ratings with every league level. Prereg:
/mnt/project-files/research-sweep-nov19/impl/soccer/prereg.md.

    python3 scripts/research/sweep_nov19/soccer/l5_americas.py pull     # ESPN scoreboards, one call a second
    python3 scripts/research/sweep_nov19/soccer/l5_americas.py tune|held
"""
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
import soccer_data as D
import soccer_games as G

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')
DOM = ('usa.1', 'mex.1', 'bra.1', 'arg.1')
CUPS = ('concacaf.leagues.cup', 'concacaf.champions', 'conmebol.libertadores', 'conmebol.sudamericana', 'fifa.cwc')
Y0, Y1 = 2017, 2025


def pull():
    for lg in DOM + CUPS:
        for y in range(Y0, Y1 + 1):
            p = os.path.join(D.CACHE, 'espn', f'{lg}_{y}.json.gz')
            if os.path.exists(p):
                continue
            rs = D.espn_year(lg, y)
            print(lg, y, len(rs), flush=True)
            time.sleep(1.1)


def rows():
    out = []
    for lg in DOM + CUPS:
        for y in range(Y0, Y1 + 1):
            for r in D.espn_year(lg, y):
                if r.get('hs') is not None and r.get('st') in ('FT', 'AET', 'PEN') and r['day'] <= f'{Y1}-12-31':
                    out.append(r)
    out.sort(key=lambda r: (r['day'], r.get('t') or '', r['id']))
    return out


def run(rs, kl, lo, hi, rho=-0.04, k=0.03):
    att = defaultdict(float); dfn = defaultdict(float); n = Counter()
    home = defaultdict(lambda: 0.25); lgof = {}; s = defaultdict(float); mu = defaultdict(lambda: math.log(1.3))
    recs = []
    for r in rs:
        h, a, lg = r['h'], r['a'], r['lg']
        if lg in DOM:
            lgof[h] = lg; lgof[a] = lg
        Lh, La = lgof.get(h), lgof.get(a)
        if lg in CUPS and (Lh is None or La is None or Lh == La):
            continue                                 # a club from another league, or a same-league cup tie: skipped
        m = (mu[Lh] + mu[La]) / 2
        hh = 0.0 if r.get('neu') else (home[Lh] if lg in DOM else 0.25)
        base_h = m + hh / 2 + att[h] - dfn[a]
        base_a = m - hh / 2 + att[a] - dfn[h]
        ds = s[Lh] - s[La]
        if r['st'] == 'FT':
            gh, ga = r['hs'], r['as']
        else:
            gh = ga = min(r['hs'], r['as'])              # level after 90 minutes
        if lg in CUPS:
            if lo <= r['day'][:4] <= hi and n[h] >= 10 and n[a] >= 10:
                y = 0 if gh > ga else 1 if gh == ga else 2
                p0 = G.wdl(math.exp(base_h), math.exp(base_a), rho)[y]
                p1 = G.wdl(math.exp(base_h + ds / 2), math.exp(base_a - ds / 2), rho)[y]
                recs.append((r['day'], lg, -math.log(max(p1, 1e-9)) + math.log(max(p0, 1e-9)), -math.log(max(p0, 1e-9))))
            lh, la = math.exp(base_h + ds / 2), math.exp(base_a - ds / 2)
            e = (min(gh, 6) - lh) - (min(ga, 6) - la)
            s[Lh] += kl * e; s[La] -= kl * e
            continue
        lh, la = math.exp(base_h), math.exp(base_a)
        eh, ea = min(gh, 6) - lh, min(ga, 6) - la
        att[h] += k * eh; dfn[a] -= k * eh
        att[a] += k * ea; dfn[h] -= k * ea
        mu[lg] += 0.002 * (eh + ea)
        home[lg] += 0.002 * (eh - ea)
        n[h] += 1; n[a] += 1
    return recs, dict(s)


def rep(recs):
    if not recs:
        return {'n': 0}
    d = [x[2] for x in recs]
    by = defaultdict(float)
    for x in recs:
        by[x[0][:4]] += x[2]
    return {'n': len(d), 'base': round(sum(x[3] for x in recs) / len(d), 5), 'd': round(sum(d) / len(d), 6), 't': G.cl_t(d, [x[0] for x in recs]),
            'years': f"{sum(v < 0 for v in by.values())}/{len(by)}"}


def main():
    if sys.argv[1] == 'pull':
        return pull()
    rs = rows()
    fn = os.path.join(OUT, 'l5.json')
    res = json.load(open(fn)) if os.path.exists(fn) else {'rows': dict(Counter(r['lg'] for r in rs)), 'tune': {}}
    if sys.argv[1] == 'tune':
        for kl in (.01, .03):
            recs, s = run(rs, kl, '2018', '2023')
            res['tune'][str(kl)] = dict(rep(recs), strengths={k: round(v, 3) for k, v in s.items()})
            print(kl, res['tune'][str(kl)], flush=True)
    else:
        kl = float(min(res['tune'], key=lambda k: res['tune'][k]['d']))
        recs, s = run(rs, kl, '2024', '2025')
        res['held'] = dict(kl=kl, **rep(recs), strengths={k: round(v, 3) for k, v in s.items()})
        res['heldLeaguesCup'] = rep([x for x in recs if x[1] == 'concacaf.leagues.cup'])
        res['heldByCup'] = dict(Counter(x[1] for x in recs))
        print(json.dumps({k: res[k] for k in ('held', 'heldLeaguesCup', 'heldByCup')}, indent=1))
    json.dump(res, open(fn, 'w'), indent=1)


if __name__ == '__main__':
    main()
