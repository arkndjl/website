#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Point-in-time WAR ledgers by week (nfl_war.war_ledger, as nfl_games.injury_history reads them), cached for
the tests in PREREG.md: scripts/.cache/nfl/nov13_led_<y>.json = {'prev': ledger of y-1, 'led': {week: ledger before it}}."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import nfl_games as N   # noqa: E402
import nfl_war as W     # noqa: E402


def path(y):
    return os.path.join(N.CACHE, f'nov13_led_{y}.json')


def build(y):
    maps = W.gsis_map(y)
    prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
    led = {w: W.war_ledger(y, thru=w, maps=maps) for w in range(1, 20)}
    json.dump({'prev': prev, 'led': led}, open(path(y), 'w'))
    print(y, len(prev), len(led[19]), flush=True)


def load(y):
    d = json.load(open(path(y)))
    return d['prev'], {int(w): v for w, v in d['led'].items()}


if __name__ == '__main__':
    for y in (int(a) for a in sys.argv[1:]):
        if not os.path.exists(path(y)):
            build(y)
