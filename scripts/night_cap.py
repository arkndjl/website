#!/usr/bin/env python3
"""Nightly exposure cap (Noah, Nov 1 2026: "40% a night"). The picks starting on one ET date, every sport together,
stake at most CAP % of the bankroll in all; a night past it has every stake scaled by CAP / total (quarter units,
rounded down, 0.25 floor). Research: scripts/exposure_cap_research.py (data/exposure_cap_research.json): at the
measured within-night correlation a 40% cap keeps 85% of the expected growth if the backtest's edges hold, is the best
cap tested if they run at half, and cuts the chance of a 50% drawdown from .27 to .12.

Each open pick keeps its own stake as unitsRaw (the Kelly stake its writer computed) and units is the capped one; the
same for its `now` quote. A writer that restakes a pick writes a fresh units, which this reads as the new raw stake.

  python3 scripts/night_cap.py            # every games_picks_<sport>.json
  python3 scripts/night_cap.py cbb        # only cbb's file is rewritten (every sport still counts toward the night)

scripts/games_picks.py, tennis_picks.py and nfl_props_paper.py call apply([their sport]) after writing; picks_refresh.py
calls apply() over every file. The bets alert (scripts/bets_today.py --sent) counts bets already sent first.
"""
import json
import math
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPORTS = ('nba', 'cbb', 'nfl', 'cfb', 'tennis', 'nflprops')
CAP = 40.0
ET = ZoneInfo('America/New_York')
EPS = 1e-9


def fn(sport):
    return os.path.join(ROOT, 'data', f'games_picks_{sport}.json')


def ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None


def night(kick):
    return ts(kick).astimezone(ET).date().isoformat()


def raw(o):
    """the uncapped stake of a pick or quote: unitsRaw if units is still the capped value this wrote, else units"""
    if o is None or o.get('units') is None:
        return 0.0
    if 'unitsRaw' in o and abs(o['units'] - o.get('unitsCap', -1)) < EPS:
        return float(o['unitsRaw'])
    return float(o['units'])


def capped(r, k):
    if r <= 0 or k >= 1:
        return r
    return max(0.25, math.floor(r * k * 4 + EPS) / 4)


def set_units(o, r, k):
    if o is None or o.get('units') is None:
        return
    u = capped(r, k)
    if k >= 1 or abs(u - r) < EPS:
        o['units'] = r
        for f in ('unitsRaw', 'unitsCap'):
            o.pop(f, None)
    else:
        o['units'], o['unitsRaw'], o['unitsCap'] = u, r, u


def live(p, now):
    k = ts(p.get('kick'))
    return k is not None and k > now and p.get('res') is None


def exposure(D, now):
    """ET date -> total uncapped stake of the open picks that would be bet (the current quote's, else the pick's)"""
    out = {}
    for d in D.values():
        for p in d.get('picks', []):
            if not live(p, now) or p.get('pass'):
                continue
            r = raw(p['now']) if p.get('now') else raw(p)
            out[night(p['kick'])] = out.get(night(p['kick']), 0.0) + r
    return out


def apply(only=None, now=None):
    now = now or datetime.now(timezone.utc)
    D = {}
    for s in SPORTS:
        try:
            with open(fn(s)) as f:
                D[s] = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    ex = exposure(D, now)
    K = {n: min(1.0, CAP / t) if t > 0 else 1.0 for n, t in ex.items()}
    for s in (only or list(D)):
        d = D.get(s)
        if not d:
            continue
        before = json.dumps(d, sort_keys=True)
        for key in ('picks', 'log'):
            rows = d.get(key, [])
            if isinstance(rows, dict):
                rows = list(rows.values())
            for p in rows:
                if not isinstance(p, dict) or not live(p, now):
                    continue
                k = K.get(night(p['kick']), 1.0)
                set_units(p, raw(p), k)
                if isinstance(p.get('now'), dict):
                    set_units(p['now'], raw(p['now']), k)
        d['nightCap'] = {'cap': CAP, 'nights': {n: {'raw': round(ex[n], 2), 'scale': round(K[n], 4)} for n in sorted(ex)}}
        if json.dumps(d, sort_keys=True) != before:
            with open(fn(s), 'w') as f:
                if s in ('tennis', 'nflprops'):
                    json.dump(d, f, separators=(',', ':'), allow_nan=False)
                else:
                    json.dump(d, f, indent=1, allow_nan=False)
    for n in sorted(ex):
        if K[n] < 1:
            print(f'night cap {n}: {ex[n]:.2f}% uncapped -> x{K[n]:.3f}')
    return K


def test():
    now = datetime(2026, 11, 1, 23, tzinfo=timezone.utc)
    p = {'kick': '2026-11-03T00:00:00Z', 'units': 5.0}
    set_units(p, raw(p), 0.4)
    assert p['units'] == 2.0 and p['unitsRaw'] == 5.0
    assert raw(p) == 5.0                     # still capped: raw comes back
    p['units'] = 3.0                         # a writer restaked it
    assert raw(p) == 3.0
    set_units(p, raw(p), 1.0)
    assert p['units'] == 3.0 and 'unitsRaw' not in p
    q = {'units': 0.25}
    set_units(q, raw(q), 0.1)
    assert q['units'] == 0.25
    assert night('2026-11-03T03:00:00Z') == '2026-11-02'
    D = {'cbb': {'picks': [{'kick': '2026-11-03T00:00:00Z', 'units': 30.0, 'now': {'units': 50.0}},
                           {'kick': '2026-11-03T00:00:00Z', 'units': 30.0, 'pass': True}]},
         'nba': {'picks': [{'kick': '2026-11-03T01:00:00Z', 'units': 30.0}]}}
    assert exposure(D, now) == {'2026-11-02': 80.0}
    print('night_cap tests pass')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--test':
        test()
    else:
        apply([s for s in a if s in SPORTS] or None)
