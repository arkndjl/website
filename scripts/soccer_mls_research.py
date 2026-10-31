#!/usr/bin/env python3
"""MLS in the soccer game model (Oct 31 2026): FotMob team xG as an input, and picks against the close.

    python3 scripts/soccer_mls_research.py --pull   # FotMob MLS match pages (soccer_data.fm_xg, id 130) -> scripts/.cache/soccer/fmx/
    python3 scripts/soccer_mls_research.py          # -> data/soccer_mls_research.json

MLS rows have football-data.co.uk's closing 1X2 ('nc': Pinnacle's close to early 2025, then Betfair Exchange's or the
average) and no opening price, so picks are judged at the close: the model's side where its chance beats the Shin
no-vig close by X or more, settled at the close's decimal price. X is picked on 2013-22 (n >= 40, t >= 1), then
2023-26 is the held-out test (mean return > 0, t >= 1.65, n >= 30). The second test is a tilt of the Shin close by
the model's home-minus-away log odds (k fit on 2013-22): it is the edge in a form that doesn't depend on a cut.
FotMob xG: tested as the model's xG side rating ('x', same rate and weight as Understat and the other FotMob leagues),
tune 2020-22, held out 2023-26."""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soccer_data as D
import soccer_games as G

OUT = os.path.join(G.ROOT, 'data', 'soccer_mls_research.json')
LG = 'usa.1'
TUNE, HOLD = (2013, 2022), (2023, 2100)
XTUNE = (2020, 2022)


def pull():
    D.FMX_LG.setdefault(LG, 130)
    for S in range(2018, D.current_season(dt_today()) + 1):
        print(S, len(D.fm_xg(LG, S)), flush=True)


def dt_today():
    import datetime as dt
    return dt.date.today()


def run(rows, P):
    out = {}

    def score(r, S, lh, la, R):
        p = G.wdl(lh, la, P['rho'])
        out[r['id']] = (S, r['day'], G.ll_of(p, G.res(r)), p)
    saved = G.SCORED
    G.SCORED = {LG}
    try:
        G.run(rows, P, score)
    finally:
        G.SCORED = saved
    return out


def ret(o, k):
    return o[k] - 1


def picks(rows, wf):
    """model side vs the Shin close, settled at the close price; X tuned 2013-22, judged 2023+"""
    rid = {r['id']: r for r in rows}
    bets = []
    for i, (S, day, _, p) in wf.items():
        r = rid[i]
        c = G.novig(r.get('nc'))
        if not c:
            continue
        e = [p[k] - c[k] for k in range(3)]
        k = max(range(3), key=lambda j: e[j])
        y = G.res(r)
        bets.append((S, day, e[k], (r['nc'][k] - 1) if y == k else -1.0, k))

    def summ(sub):
        if not sub:
            return {'n': 0}
        m = sum(b[3] for b in sub) / len(sub)
        return {'n': len(sub), 'ret': round(100 * m, 2), 't': G.cl_t([b[3] for b in sub], [b[1] for b in sub]),
                'won': sum(b[3] > 0 for b in sub)}
    grid = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15]
    by = []
    for x in grid:
        tu = [b for b in bets if TUNE[0] <= b[0] <= TUNE[1] and b[2] >= x]
        ho = [b for b in bets if b[0] >= HOLD[0] and b[2] >= x]
        by.append({'x': x, 'tune': summ(tu), 'hold': summ(ho)})
    ok = [g for g in by if g['tune']['n'] >= 40 and g['tune']['ret'] > 0 and (g['tune']['t'] or 0) >= 1]
    pick = max(ok, key=lambda g: g['tune']['ret']) if ok else None
    on = bool(pick and pick['hold']['n'] >= 30 and pick['hold']['ret'] > 0 and (pick['hold']['t'] or 0) >= 1.65)
    side = {}
    for nm, kk in (('home', 0), ('draw', 1), ('away', 2)):
        side[nm] = {'tune': summ([b for b in bets if TUNE[0] <= b[0] <= TUNE[1] and b[4] == kk and b[2] >= 0.03]),
                    'hold': summ([b for b in bets if b[0] >= HOLD[0] and b[4] == kk and b[2] >= 0.03])}
    bySeason = {S: summ([b for b in bets if b[0] == S and b[2] >= 0.03]) for S in sorted({b[0] for b in bets})}
    return {'grid': by, 'chosen': pick and pick['x'], 'on': on, 'bySide3': side, 'bySeason3': bySeason}


def tilt(p, k, z):
    a, c = p[0] * math.exp(k * z / 2), p[2] * math.exp(-k * z / 2)
    s = a + p[1] + c
    return [a / s, p[1] / s, c / s]


def lo_(p):
    return math.log(max(p[0], 1e-6) / max(p[2], 1e-6))


def vs_close(rows, wf):
    rid = {r['id']: r for r in rows}
    xs = []
    for i, (S, day, ll, p) in wf.items():
        c = G.novig(rid[i].get('nc'))
        if c:
            xs.append((S, day, c, lo_(p) - lo_(c), G.res(rid[i]), ll))
    tu = [x for x in xs if TUNE[0] <= x[0] <= TUNE[1]]; ho = [x for x in xs if x[0] >= HOLD[0]]

    def gap(sub):
        d = [x[5] - G.ll_of(x[2], x[4]) for x in sub]
        return {'n': len(d), 'model': round(sum(x[5] for x in sub) / len(sub), 5),
                'close': round(sum(G.ll_of(x[2], x[4]) for x in sub) / len(sub), 5),
                'gap': round(sum(d) / len(d) * 1e4, 1), 't': G.cl_t(d, [x[1] for x in sub])}

    def tl(sub, k):
        return [G.ll_of(tilt(x[2], k, x[3]), x[4]) - G.ll_of(x[2], x[4]) for x in sub]
    k = min([i / 20 for i in range(-10, 21)], key=lambda k: sum(tl(tu, k)))
    a, b = tl(tu, k), tl(ho, k)
    return {'gap': {'tune': gap(tu), 'hold': gap(ho)},
            'tilt': {'k': k, 'tune': {'dLL': round(sum(a) / len(a) * 1e4, 2), 't': G.cl_t(a, [x[1] for x in tu])},
                     'hold': {'dLL': round(sum(b) / len(b) * 1e4, 2), 't': G.cl_t(b, [x[1] for x in ho])}}}


def compare(base, new, lo, hi):
    d, k = [], []
    for i, b in base.items():
        if lo <= b[0] <= hi and i in new:
            d.append(new[i][2] - b[2]); k.append(b[1])
    return {'n': len(d), 'dLL': round(sum(d) / max(1, len(d)) * 1e4, 2), 't': G.cl_t(d, k)}


def main():
    if '--pull' in sys.argv:
        pull()
        return
    rows = G.add_inj(G.add_mv(G.add_market(D.load(G.HIST))))
    for r in rows:                      # the history carries MLS FotMob xG since this test shipped: start without it
        if r['lg'] == LG:
            r.pop('hx', None); r.pop('ax', None)
    P = G.params()
    res = {'note': __doc__.split('\n\n')[2]}
    base = run(rows, P)
    res['base'] = {'vsClose': vs_close(rows, base), 'picks': picks(rows, base)}
    print(json.dumps(res['base']), flush=True)
    # FotMob xG on MLS rows as hx/ax
    D.FMX_LG.setdefault(LG, 130)
    by = defaultdict(list)
    for r in rows:
        if r['lg'] == LG and r.get('hs') is not None:
            by[D.season_of(r['day'], LG)].append(r)
    names = D.load(G.NAMES)
    n = {}
    for S, es in sorted(by.items()):
        if S < 2019:
            continue
        for r in es:
            r['hn'], r['an'] = (names.get(r['h']) or ['?'])[0], (names.get(r['a']) or ['?'])[0]
        n[S] = (G.fm_xg_join(es, LG, S), len(es))
    res['xgJoined'] = n
    print(n, flush=True)
    xg = run(rows, P)
    res['xg'] = {'tune': compare(base, xg, *XTUNE), 'hold': compare(base, xg, *HOLD),
                 'bySeason': {S: compare(base, xg, S, S) for S in range(2020, 2027)},
                 'vsClose': vs_close(rows, xg), 'picks': picks(rows, xg)}
    print(json.dumps(res['xg']), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
