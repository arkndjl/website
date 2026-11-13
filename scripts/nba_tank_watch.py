#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-registered live test of a late-season term for the NBA game model. Stdlib only.

    python3 scripts/nba_tank_watch.py        # data/model_monitor/nba_tank.json

Registered 2026-11-13, before any 2026-27 team had played 55 games. A team is `bad` once it has played NEED_G regular
season games with a win share of BAD or less; tank = bad(home) - bad(away). On 2015-26 the term's fitted weight is C
points (scripts/nba_audit_research.py: walk-forward tune t -1.74, held t -2.59; it missed Holm over the five terms
tested with it, so it was not shipped). Over this season's logged games with tank != 0,
d = |m + C x tank - res| - |m - res|. With NEED flagged games the verdict is 'add' when mean d < 0 at t <= -T_ADD,
else 'drop'; before that 'wait'. An add verdict means: refit nba_games_fit with the term on, held to the usual gate.
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES = os.path.join(ROOT, 'data', 'nba_games.json')
MON = os.path.join(ROOT, 'scripts', 'data', 'model_monitor', 'nba.json')
OUT = os.path.join(ROOT, 'data', 'model_monitor', 'nba_tank.json')
NEED_G, BAD, C, NEED, T_ADD, REGISTERED = 55, 0.35, -1.70, 120, 1.65, '2026-11-13'


def main():
    log = json.load(open(GAMES)).get('log') or {}
    res = {k: v.get('res') for k, v in (json.load(open(MON)).get('log') or {}).items()}
    rec = {}
    d = []
    for k, v in sorted(log.items(), key=lambda kv: kv[1].get('tip') or ''):
        row = v.get('row') or {}
        r, h, a = res.get(k), row.get('home'), row.get('away')
        if r is None or v.get('m') is None or not h or not a or row.get('po'):
            continue
        bad = lambda t: 1.0 if sum(rec.get(t, (0, 0))) >= NEED_G and rec[t][0] / sum(rec[t]) <= BAD else 0.0
        tank = bad(h) - bad(a)
        if tank:
            d.append(abs(v['m'] + C * tank - r) - abs(v['m'] - r))
        for t, w in ((h, r > 0), (a, r < 0)):
            x = rec.get(t, (0, 0))
            rec[t] = (x[0] + (1 if w else 0), x[1] + (0 if w else 1))
    n = len(d)
    mu = sum(d) / n if n else None
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) if n > 1 else None
    t = mu / (sd / math.sqrt(n)) if sd else None
    verdict = 'wait' if n < NEED else ('add' if t is not None and mu < 0 and t <= -T_ADD else 'drop')
    out = {'registered': REGISTERED, 'n': n, 'need': NEED, 'coef': C, 'tAdd': -T_ADD,
           'dMae': round(mu, 4) if mu is not None else None, 't': round(t, 2) if t is not None else None, 'verdict': verdict}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    print('nba tank watch', out)


if __name__ == '__main__':
    main()
