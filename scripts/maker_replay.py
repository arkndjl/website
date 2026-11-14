#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Maker-side replay of the picks log on the archived Novig quotes. Paper only: reads files, sends nothing. Stdlib only.

    python3 scripts/maker_replay.py --coverage   # quote match counts and snapshot cadence, no close values
    python3 scripts/maker_replay.py --score OUT  # the registered replay -> OUT (json)
    python3 scripts/maker_replay.py --test       # self-check

Every pick in a games_picks_<book>.json log that was a bet (not a pass, not void) took the Novig ask at its flag time.
The replay rests a buy order at the flag instead and asks whether a later archived quote would have filled it.

Quotes (all change-only rows written by the odds-snap run, so a book's state holds until its next row):
  spread / total   scripts/data/odds_novig_ladder: each rung [line, ask home|over, ask away|under] to the cent
  moneyline        scripts/data/odds_dense rows with src novig: mlH, mlA (American asks)
  NFL props        scripts/data/props/nfl-*.jsonl rows with src novig: the main rung L, oO, oU (American asks)
  tennis           scripts/data/odds_novig/tennis-*.jsonl: p (mid chance of the side after '@'), h (hold); rows on a
                   one-point move of p only
A side's bid is 1 - the other side's ask. The quote at the flag is the last row at or before the flag (+2 min); the
pick is kept when that row quotes the pick's line and its ask is within .015 of the logged price.

Orders (price as a chance, floored to a .005 tick): mid; fair = min(pDU, mid); bid. An order fills at its own price
when a later row before the start shows the pick's side ask at the pick's line at or under it. Unfilled: no bet, or
(fallback arms) the ask at the pick's line in the last row at or before 30 minutes to the start.

Close value of a fill at price P is q / P - 1, q = (clvRet + 1) / decimal(price): the close's chance of the pick at
its line, from the log's own close value (pushes ignored). No result field is read.
"""
import datetime
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import rule_monitor as RM  # noqa: E402

BOOKS = ('nba', 'cbb', 'cfb', 'nfl', 'nflprops', 'tennis')
TICK = 0.005
TOL = 0.015                  # archive ask vs logged price, chance
LAG = 120                    # seconds a flag-time quote may trail the flag
FALLBACK = 30 * 60           # seconds before the start
TUNE_END = '2026-11-01'      # flagged before: choices
HELD_END = '2026-11-11'      # flagged before: the gate
ARMS = ('mid', 'fair', 'bid')
RESULT_KEYS = ('res', 'profit', 'score', 'closeML')


def ts(s):
    s = s.replace('Z', '+00:00')
    if len(s) == 22:                       # 2026-11-01T00:05+00:00
        s = s[:16] + ':00' + s[16:]
    return datetime.datetime.fromisoformat(s).timestamp()


def chance(o):
    o = float(o)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def dec(o):
    o = float(o)
    return 1 + (o / 100 if o > 0 else 100 / -o)


def floor_tick(p):
    return math.floor(p / TICK + 1e-6) * TICK


def rows(pat):
    for fn in sorted(glob.glob(os.path.join(HERE, 'data', pat))):
        with open(fn) as f:
            for ln in f:
                if ln.strip():
                    try:
                        yield json.loads(ln)
                    except ValueError:
                        continue


def load_quotes():
    """{book kind: {key: [(t, payload)]}} sorted by time"""
    Q = {'ladder': {}, 'ml': {}, 'prop': {}, 'tennis': {}}
    for sp in ('nba', 'cbb', 'cfb', 'nfl'):
        for r in rows(f'odds_novig_ladder/{sp}-*.jsonl'):
            if r.get('id'):
                Q['ladder'].setdefault((sp, str(r['id'])), []).append((ts(r['t']), r['lad']))
        for r in rows(f'odds_dense/{sp}-*.jsonl'):
            if 'fin' in r:
                continue
            ok = r.get('src') == 'novig' and r.get('mlH') is not None and r.get('mlA') is not None
            Q['ml'].setdefault((sp, str(r['id'])), []).append((ts(r['t']), (chance(r['mlH']), chance(r['mlA'])) if ok else None))
    for r in rows('props/nfl-*.jsonl'):
        if r.get('a') == 'game':
            continue
        ok = r.get('src') == 'novig' and r.get('oO') is not None and r.get('oU') is not None
        Q['prop'].setdefault(f"{r['id']}-{r['a']}-{r['s']}", []).append(
            (ts(r['t']), (r['L'], chance(r['oO']), chance(r['oU'])) if ok else None))
    for r in rows('odds_novig/tennis-*.jsonl'):
        ok = r.get('p') is not None and r.get('h') is not None
        Q['tennis'].setdefault(r['nid'], []).append((ts(r['t']), (r['p'] + r['h'] / 2, 1 - r['p'] + r['h'] / 2) if ok else None))
    for d in Q.values():
        for v in d.values():
            v.sort(key=lambda x: x[0])
    return Q


def series(Q, book, e):
    """[(t, ask mine, ask other) or (t, None)] for the pick's side at the pick's line"""
    mk, side = e['mk'], e['side']
    out = []
    if mk in ('spread', 'total'):
        first = side in ('home', 'over')
        for t, lad in Q['ladder'].get((book, str(e.get('espn') or e['id'])), []):
            hit = next((r for r in lad.get('L' if mk == 'spread' else 'T') or [] if abs(r[0] - e['line']) < 1e-6), None)
            out.append((t, (hit[1], hit[2]) if first else (hit[2], hit[1])) if hit else (t, None))
    elif mk == 'ml' and book != 'tennis':
        for t, v in Q['ml'].get((book, str(e.get('espn') or e['id'])), []):
            out.append((t, v if side == 'home' else (v[1], v[0])) if v else (t, None))
    elif mk == 'prop':
        for t, v in Q['prop'].get(e['id'], []):
            ok = v and abs(v[0] - e['line']) < 1e-6
            out.append((t, (v[1], v[2]) if side == 'over' else (v[2], v[1])) if ok else (t, None))
    elif book == 'tennis':
        # p is the chance of the side after '@' (the log's home unless fl)
        first = (side == 'home') != bool(e.get('fl'))
        for t, v in Q['tennis'].get(e.get('nid'), []):
            out.append((t, v if first else (v[1], v[0])) if v else (t, None))
    return out


def picks(book):
    """the log's bets, result fields dropped before anything else sees them"""
    d = json.load(open(os.path.join(ROOT, 'data', f'games_picks_{book}.json')))
    out = []
    for e in d.get('log') or []:
        void = e.get('void') or e.get('res') == 'void'
        e = {k: v for k, v in e.items() if k not in RESULT_KEYS}
        if void or e.get('pass') or e.get('price') is None or not e.get('kick') or not e.get('flagged') or e.get('bk') == 'poly':
            continue
        out.append(e)
    return out


def replay(e, ser):
    """the pick against its quote series: None when the flag quote can't be matched, else the orders and their fills"""
    t0, tk = ts(e['flagged']), ts(e['kick'])
    at = [x for x in ser if x[0] <= t0 + LAG]
    if not at or at[-1][1] is None or t0 >= tk:
        return None
    ask, other = at[-1][1]
    logged = chance(e['price'])
    if abs(ask - logged) > TOL:
        return None
    bid = 1 - other
    if bid > ask + 1e-9:
        return None
    mid = (ask + bid) / 2
    later = [x for x in ser if t0 + LAG < x[0] < tk]
    fb = None
    if tk - t0 > FALLBACK:
        pre = [x for x in ser if x[0] <= tk - FALLBACK]
        if pre and pre[-1][1] is not None:
            fb = pre[-1][1][0]
    else:
        fb = logged
    px = {'mid': floor_tick(mid), 'fair': floor_tick(min(float(e.get('pDU') or mid), mid)), 'bid': floor_tick(bid)}
    out = {'ask': logged, 'bid': bid, 'half': (ask - bid) / 2, 'fb': fb, 'orders': {}, 'rows': len(later)}
    for arm, p in px.items():
        if p >= ask - 1e-9:                     # nothing inside the spread: the order is the taker's
            out['orders'][arm] = {'p': logged, 'fill': True, 'wait': 0.0}
            continue
        hit = next((x for x in later if x[1] is not None and x[1][0] <= p + 1e-9), None)
        out['orders'][arm] = {'p': round(p, 4), 'fill': bool(hit), 'wait': round((hit[0] - t0) / 3600, 2) if hit else None}
    return out


def split_of(e):
    f = e['flagged'][:10]
    return 'tune' if f < TUNE_END else 'held' if f < HELD_END else 'ext'


def stat(xs, gs):
    m, se, t, G = RM.clustered(xs, gs)
    r = lambda v, k=4: None if v is None else round(v, k)
    return {'n': len(xs), 'days': G, 'mean': r(m), 'se': r(se), 't': r(t, 2)}


def values(e, rp):
    """per-pick close values: taker, and each arm's policy with and without the fallback"""
    q = min(0.999, max(0.001, (e['clvRet'] + 1) / dec(e['price'])))
    taker = e['clvRet']
    v = {'taker': taker, 'q': q}
    for arm, o in rp['orders'].items():
        fill = q / o['p'] - 1 if o['fill'] else None
        v[arm] = {'fill': fill, 'nb': fill if o['fill'] else 0.0,
                  'fb': fill if o['fill'] else (q / rp['fb'] - 1 if rp['fb'] else 0.0)}
    return v


def cadence():
    out = {}
    for name, pat in (('ladder', 'odds_novig_ladder/*.jsonl'), ('dense', 'odds_dense/*.jsonl'), ('props nfl', 'props/nfl-*.jsonl'),
                      ('tennis', 'odds_novig/tennis-*.jsonl')):
        st = sorted({r['t'][:16] for r in rows(pat)})
        g = sorted((ts(b + ':00Z') - ts(a + ':00Z')) / 60 for a, b in zip(st, st[1:]))
        out[name] = {'runs': len(st), 'first': st[0], 'last': st[-1], 'gapMed': g[len(g) // 2], 'gapP75': g[int(.75 * len(g))],
                     'gapP90': g[int(.9 * len(g))], 'gapMax': g[-1]}
    return out


def coverage():
    Q = load_quotes()
    out = {'cadence': cadence(), 'books': {}}
    for b in BOOKS:
        c = {}
        for e in picks(b):
            rp = replay(e, series(Q, b, e))
            k = split_of(e)
            c.setdefault(k, {'bets': 0, 'matched': 0, 'closed': 0, 'rows': 0, 'half': 0.0})
            c[k]['bets'] += 1
            if rp:
                c[k]['matched'] += 1
                c[k]['closed'] += e.get('clvRet') is not None
                c[k]['rows'] += rp['rows']
                c[k]['half'] += rp['half']
        for v in c.values():
            if v['matched']:
                v['rows'] = round(v['rows'] / v['matched'], 1)
                v['half'] = round(v['half'] / v['matched'], 4)
        out['books'][b] = c
    return out


def score():
    Q = load_quotes()
    recs = []
    for b in BOOKS:
        for e in picks(b):
            if e.get('clvRet') is None:
                continue
            rp = replay(e, series(Q, b, e))
            if not rp:
                continue
            recs.append({'book': b, 'split': split_of(e), 'day': RM.day(e['kick']), 'mk': e['mk'], 'rp': rp, 'v': values(e, rp)})
    out = {'arms': {}, 'n': len(recs)}
    for sp in ('tune', 'held', 'ext'):
        for bk in ('all',) + BOOKS:
            rs = [r for r in recs if r['split'] == sp and bk in ('all', r['book'])]
            if not rs:
                continue
            gs = [r['day'] for r in rs]
            blk = {'taker': stat([r['v']['taker'] for r in rs], gs), 'half': round(sum(r['rp']['half'] for r in rs) / len(rs), 4)}
            for arm in ARMS:
                f = [r for r in rs if r['rp']['orders'][arm]['fill']]
                u = [r for r in rs if not r['rp']['orders'][arm]['fill']]
                a = {'fillRate': round(len(f) / len(rs), 3),
                     'filled': stat([r['v'][arm]['fill'] for r in f], [r['day'] for r in f]),
                     'filledTaker': stat([r['v']['taker'] for r in f], [r['day'] for r in f]),
                     'unfilledTaker': stat([r['v']['taker'] for r in u], [r['day'] for r in u]),
                     'unfilledFallback': stat([r['v'][arm]['fb'] for r in u], [r['day'] for r in u])}
                for pol in ('nb', 'fb'):
                    a[pol] = stat([r['v'][arm][pol] for r in rs], gs)
                    a[pol + 'Diff'] = stat([r['v'][arm][pol] - r['v']['taker'] for r in rs], gs)
                blk[arm] = a
            out['arms'].setdefault(sp, {})[bk] = blk
    return out


def test():
    assert abs(chance(-150) - .6) < 1e-9 and abs(chance(150) - .4) < 1e-9 and abs(dec(-200) - 1.5) < 1e-9
    assert abs(floor_tick(.5049) - .5) < 1e-9 and abs(floor_tick(.505) - .505) < 1e-9
    e = {'flagged': '2026-11-01T00:00:00Z', 'kick': '2026-11-01T10:00:00Z', 'price': -108.0, 'pDU': .505, 'clvRet': 0.0,
         'mk': 'total', 'side': 'over', 'line': 220.5}
    t0 = ts(e['flagged'])
    ser = [(t0 - 60, (.52, .50)), (t0 + 3600, (.51, .51)), (t0 + 7200, (.50, .52)), (t0 + 9.8 * 3600, (.53, .49))]
    rp = replay(e, ser)
    assert abs(rp['bid'] - .5) < 1e-9 and rp['orders']['mid'] == {'p': .51, 'fill': True, 'wait': 1.0}
    assert rp['orders']['bid']['fill'] and rp['orders']['bid']['wait'] == 2.0 and rp['orders']['fair']['p'] == .505
    assert abs(rp['fb'] - .50) < 1e-9
    v = values(e, rp)
    assert abs(v['q'] - chance(-108)) < 1e-9 and v['mid']['nb'] > 0
    assert replay(e, [(t0 - 60, (.60, .42))]) is None and replay(e, [(t0 + 600, (.52, .50))]) is None
    rp = replay(e, [(t0 - 60, (.52, .50)), (t0 + 3600, None), (t0 + 9.8 * 3600, (.53, .49))])
    assert not rp['orders']['mid']['fill'] and rp['fb'] is None
    m, se, t, G = RM.clustered([1, 2, 3, 4], ['a', 'a', 'b', 'b'])
    assert G == 2 and abs(m - 2.5) < 1e-9
    print('maker_replay: ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--test' in a:
        test()
    elif '--coverage' in a:
        print(json.dumps(coverage(), indent=1))
    elif '--score' in a:
        out = score()
        with open(a[a.index('--score') + 1], 'w') as f:
            json.dump(out, f, indent=1)
        print('scored', out['n'])
    else:
        print(__doc__)
