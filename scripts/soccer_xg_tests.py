#!/usr/bin/env python3
"""Audit item #37 (Oct 25 2026): which Understat xG the soccer game model should learn from.

    python3 scripts/soccer_xg_tests.py        # -> data/soccer_xg_tests.json

The model's xG side ratings (scripts/soccer_games.py, SUBS 'x') learn from each big-five match's total Understat xG,
penalties included. Candidates, each replacing hx/ax on every match with Understat shots (2014-15 on):
  npxg     non-penalty xG
  x11      xG while both sides had 11 players: shots before the first red card, scaled up to 90 minutes by the
           11 v 11 minutes (kept as is when the first red came before minute 30, too little to scale)
  npx11    both
Each is walk-forward with kx and wx (the xG learning rate and its blend weight) retuned on 2013-22, the same as the
current model gets, then scored on the held-out seasons 2023-26 against the current model, match by match.
GATE (registered before results): held-out log-loss gain with a match-day-clustered t >= 2, 3 of the 4 held-out seasons
better, tuning seasons not worse.
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D
import soccer_games as G

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_xg_tests.json')


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def match_xg(mid):
    """{'x': (h, a), 'npxg': ..., 'x11': ..., 'npx11': ...} from Understat's shots and red cards"""
    m = D.us_match(mid)
    if not m:
        return None
    red = 999
    for s in 'ha':
        rs = {r['id']: r for r in m['ro'][s]}
        start = {r['id']: 0 for r in rs.values() if int(f(r.get('positionOrder'))) < 17}
        for _ in range(6):
            for r in rs.values():
                o = str(r.get('roster_out') or '0')
                if r['id'] not in start and o in start and o in rs:
                    start[r['id']] = start[o] + int(f(rs[o]['time']))
        for r in rs.values():
            if int(f(r.get('red_card'))) > 0 and r['id'] in start:
                red = min(red, start[r['id']] + int(f(r['time'])))
    out = {}
    for k in ('x', 'npxg', 'x11', 'npx11'):
        v = []
        for s in 'ha':
            sh = m['sh'].get(s) or []
            np_ = k in ('npxg', 'npx11')
            e11 = k in ('x11', 'npx11') and red < 90
            tot = sum(f(x[1]) for x in sh if not (np_ and x[4] == 'Penalty') and (not e11 or red < 30 or f(x[0]) < red))
            if e11 and red >= 30:
                tot *= 90 / red
            v.append(round(tot, 3))
        out[k] = v
    return out


def main():
    rows = G.add_mv(G.add_market(D.load(G.HIST)))
    P = G.params()
    xs = {}
    for r in rows:
        if r.get('us'):
            x = match_xg(r['us'])
            if x:
                xs[r['id']] = x
    print('matches with Understat shots', len(xs), flush=True)
    orig = {r['id']: (r['hx'], r['ax']) for r in rows if r.get('hx') is not None}

    def setx(k):
        for r in rows:
            if r['id'] in xs:
                r['hx'], r['ax'] = xs[r['id']][k]
            elif r['id'] in orig:
                r['hx'], r['ax'] = orig[r['id']]

    def wf(Q):
        return {o['id']: o for o in G.walk(rows, Q)}

    res = {'n': len(xs)}
    setx('x')
    # the rebuilt total should be the cached total (a check on the shot sums)
    d = [abs(sum(xs[i]['x']) - sum(orig[i])) for i in xs if i in orig]
    res['rebuildMaxDiff'] = round(max(d), 3)
    P0, best0 = G.tune(rows, dict(P), ['kx', 'wx'])
    base = wf(P0)
    res['base'] = {'kx': P0['kx'], 'wx': P0['wx'], 'tune': round(best0, 5)}
    print('base', res['base'], flush=True)
    for k in ('npxg', 'x11', 'npx11'):
        setx(k)
        Q, bq = G.tune(rows, dict(P0), ['kx', 'wx'])
        w = wf(Q)
        diff, day, Sk, big = [], [], [], []
        for i, o in w.items():
            b = base.get(i)
            if not b or o['S'] < G.HOLD_FROM:
                continue
            y = G.res(o)
            diff.append(G.ll_of(b['p'], y) - G.ll_of(o['p'], y))       # positive = the candidate is better
            day.append(o['day']); Sk.append(o['S']); big.append(o['lg'] in D.BIG5)
        byS = defaultdict(list)
        for x, s in zip(diff, Sk):
            byS[s].append(x)
        bigd = [x for x, b in zip(diff, big) if b]
        r = {'kx': round(Q['kx'], 5), 'wx': round(Q['wx'], 5), 'tune': round(bq, 5), 'tuneBase': round(best0, 5),
             'heldGainMll': round(1000 * sum(diff) / len(diff), 3), 't': G.cl_t(diff, day), 'n': len(diff),
             'bigFiveGainMll': round(1000 * sum(bigd) / len(bigd), 3),
             'bySeason': {s: round(1000 * sum(v) / len(v), 3) for s, v in sorted(byS.items())}}
        wins = sum(1 for v in r['bySeason'].values() if v > 0)
        r['wins'] = f'{wins}/{len(byS)}'
        r['pass'] = bool((r['t'] or 0) >= 2 and wins >= 3 and bq <= best0 + 1e-6)
        res[k] = r
        print(k, json.dumps(r), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
