#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-registered live test of the NBA game model's lineup term (lin). Stdlib only.

    python3 scripts/nba_lin_watch.py        # data/model_monitor/nba_lin.json

Registered 2026-11-11, before 400 games: over the season's logged games with a result (data/nba_games.json log, results
from scripts/data/model_monitor/nba.json), d = |m - res| - |(m - lin) - res|, the margin error with the lineup term
against without it. Once NBA_N graded games exist the verdict is 'drop' when mean d > 0 at t >= T_DROP (the term makes
live margins worse), else 'keep'. A drop verdict means: refit nba_games_fit with lin off, held to the usual gate.
Before NBA_N games the verdict is 'wait'.
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES = os.path.join(ROOT, 'data', 'nba_games.json')
MON = os.path.join(ROOT, 'scripts', 'data', 'model_monitor', 'nba.json')
OUT = os.path.join(ROOT, 'data', 'model_monitor', 'nba_lin.json')
NBA_N, T_DROP, REGISTERED = 400, 1.65, '2026-11-11'


def main():
    log = json.load(open(GAMES)).get('log') or {}
    res = {k: v.get('res') for k, v in (json.load(open(MON)).get('log') or {}).items()}
    d = []
    for k, v in log.items():
        r = res.get(k)
        lin = ((v.get('row') or {}).get('parts') or {}).get('lin')
        if r is None or v.get('m') is None or lin is None:
            continue
        d.append(abs(v['m'] - r) - abs(v['m'] - lin - r))
    n = len(d)
    mu = sum(d) / n if n else None
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) if n > 1 else None
    t = mu / (sd / math.sqrt(n)) if sd else None
    verdict = 'wait' if n < NBA_N else ('drop' if t is not None and mu > 0 and t >= T_DROP else 'keep')
    out = {'registered': REGISTERED, 'n': n, 'need': NBA_N, 'tDrop': T_DROP,
           'dMae': round(mu, 4) if mu is not None else None, 't': round(t, 2) if t is not None else None, 'verdict': verdict}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    print('nba lin watch', out)


if __name__ == '__main__':
    main()
