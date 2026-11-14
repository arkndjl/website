#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Derivative markets (first-half spread / total, team totals) against the full-game line. Research only: no picks.

    python3 scripts/derivs_research.py --describe [sport ...]   # counts and dispersion, no drift
    python3 scripts/derivs_research.py --count                  # games toward the registered trigger
    python3 scripts/derivs_research.py --b2                     # the registered test: runs once, at the trigger
    python3 scripts/derivs_research.py --test

The spec is scripts/data/ledger/derivs_b2.json (frozen; its sha256 is stored with the result). A quote's fair line is
its line moved by its prices (line + sd x zinv(no-vig chance)), so a main rung that hops between neighbours does not
read as a move. The implied value comes from the archive's own cross-section (the repo has no half scores): first-half
lines as a ratio of the full-game fair line, team totals as (total +/- margin) / 2 plus a constant.
"""
import datetime
import glob
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rule_monitor as RM  # noqa: E402
from novig import zinv  # noqa: E402

PROPS = os.path.join(HERE, 'data', 'props')
MAIN = os.path.join(HERE, 'data', 'odds_novig')
SPEC = os.path.join(HERE, 'data', 'ledger', 'derivs_b2.json')
RESULT = os.path.join(HERE, 'data', 'ledger', 'derivs_b2_result.json')
SPORTS = ('nfl', 'nba', 'cbb', 'cfb', 'nhl')
AHEAD = 2 * 3600
LOOKBACK = 7 * 86400
CUT = 1.5
CUT_SD = 2.0
FIT_SHARE = 0.4
MIN_FIT = 20


def ts(s):
    s = s.replace('Z', '+00:00')
    if len(s) == 22:
        s = s[:16] + ':00' + s[16:]
    return datetime.datetime.fromisoformat(s).timestamp()


def chance(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def spec():
    raw = open(SPEC, 'rb').read()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def sd_of(S, sport, mk):
    sm, st = S['sd'][sport]
    if mk == '1hs':
        return sm * S['halfSd']
    if mk == '1ht':
        return st * S['halfSd']
    return math.sqrt(sm * sm + st * st) / 2


def quote_fair(S, sport, mk, r):
    """the quote's fair line, or None without two prices"""
    if r.get('L') is None or r.get('oO') is None or r.get('oU') is None:
        return None
    p = (chance(r['oO']) + 1 - chance(r['oU'])) / 2
    if not .2 < p < .8:
        return None
    return r['L'] + sd_of(S, sport, mk) * zinv(p)


def jl(pat):
    for fn in sorted(glob.glob(pat)):
        with open(fn) as f:
            for ln in f:
                if ln.strip():
                    try:
                        yield json.loads(ln)
                    except ValueError:
                        continue


def load(sport):
    """{game id: {'k': start, 'q': {market: [(t, row)]}, 'M': [(t, fair margin)], 'T': [(t, fair total)]}}"""
    G = {}
    pat = 'nfl-*.jsonl' if sport == 'nfl' else f'derivs-{sport}-*.jsonl'
    for r in jl(os.path.join(PROPS, pat)):
        if r.get('a') != 'game' or r.get('src') != 'novig':
            continue
        g = G.setdefault(str(r['id']), {'k': ts(r['k']), 'kick': r['k'], 'q': {}, 'M': [], 'T': []})
        g['k'], g['kick'] = ts(r['k']), r['k']
        if r['s'] in ('ms', 'mt'):
            if r.get('m') is not None:
                g['M' if r['s'] == 'ms' else 'T'].append((ts(r['t']), r['m']))
        else:
            g['q'].setdefault(r['s'], []).append((ts(r['t']), r))
    if sport == 'nfl':
        for r in jl(os.path.join(MAIN, 'nfl-*.jsonl')):
            g = G.get(str(r.get('id')))
            if g:
                for k, f in (('M', 'L'), ('T', 'T')):
                    if r.get(f) is not None:
                        g[k].append((ts(r['t']), r[f]))
    for g in G.values():
        for v in [g['M'], g['T'], *g['q'].values()]:
            v.sort(key=lambda x: x[0])
    return G


def standing(series, t, lo):
    v = [x for x in series if lo <= x[0] <= t]
    return v[-1][1] if v else None


def table(S, sport):
    """one row per game-market with both sides standing 2 h before the start"""
    out = []
    for gid, g in load(sport).items():
        t0 = g['k'] - AHEAD
        M, T = standing(g['M'], t0, t0 - LOOKBACK), standing(g['T'], t0, t0 - LOOKBACK)
        if M is None or T is None:
            continue
        for mk in S['markets']:
            a, z = standing(g['q'].get(mk, []), t0, t0 - LOOKBACK), standing(g['q'].get(mk, []), g['k'] - 1, t0 - LOOKBACK)
            fa = quote_fair(S, sport, mk, a) if a else None
            fz = quote_fair(S, sport, mk, z) if z else None
            if fa is None or fz is None:
                continue
            x = M if mk == '1hs' else T if mk == '1ht' else (T + M) / 2 if mk == 'ttH' else (T - M) / 2
            out.append({'sport': sport, 'id': gid, 'k': g['k'], 'day': RM.day(g['kick'] if len(g['kick']) > 17 else g['kick'][:16] + ':00Z'),
                        'mk': mk, 'x': x, 'fa': fa, 'fz': fz})
    return out


def fit(rows):
    """{market: (a, b)}: first-half ratio through the origin, team totals a constant over the identity"""
    out = {}
    for mk in {r['mk'] for r in rows}:
        rs = [r for r in rows if r['mk'] == mk]
        if mk in ('1hs', '1ht'):
            den = sum(r['x'] ** 2 for r in rs)
            out[mk] = (0.0, sum(r['x'] * r['fa'] for r in rs) / den if den else 0.5)
        else:
            out[mk] = (sum(r['fa'] - r['x'] for r in rs) / len(rs), 1.0)
    return out


def dev(r, F):
    a, b = F[r['mk']]
    return r['fa'] - (a + b * r['x'])


def describe(sports):
    S, _ = spec()
    for sp in sports:
        rows = table(S, sp)
        if not rows:
            print(sp, 'no rows')
            continue
        F = fit(rows)
        print(f"{sp}: {len({r['id'] for r in rows})} games, {len(rows)} game-markets (fit in sample)")
        for mk in S['markets']:
            d = [dev(r, F) for r in rows if r['mk'] == mk]
            if not d:
                continue
            m = sum(d) / len(d)
            sd = math.sqrt(sum((x - m) ** 2 for x in d) / max(1, len(d) - 1))
            q = sorted(abs(x) for x in d)
            print(f"  {mk}: n {len(d)}  a {F[mk][0]:+.2f} b {F[mk][1]:.3f}  sd {sd:.2f}  median |dev| {q[len(q) // 2]:.2f}  "
                  f"p90 {q[int(.9 * len(q))]:.2f}  1.5+ off {sum(x >= CUT for x in q)} ({sum(x >= CUT for x in q) / len(q):.1%})")


def count():
    S, _ = spec()
    return {sp: len({r['id'] for r in table(S, sp)}) for sp in SPORTS}


def b2():
    S, sha = spec()
    if os.path.exists(RESULT):
        print('B2 already scored:', RESULT)
        return
    c = count()
    if sum(c.values()) < S['trigger']['games']:
        print(f"B2 waits: {sum(c.values())} of {S['trigger']['games']} games {c}")
        return
    flagged, base, by = [], [], {}
    for sp in SPORTS:
        rows = table(S, sp)
        ids = sorted({(r['k'], r['id']) for r in rows})
        nfit = int(len(ids) * FIT_SHARE)
        if nfit < MIN_FIT:
            continue
        fit_ids = {i for _, i in ids[:nfit]}
        F = fit([r for r in rows if r['id'] in fit_ids])
        dv = {}
        for r in rows:
            if r['id'] in fit_ids and r['mk'] in F:
                dv.setdefault(r['mk'], []).append(dev(r, F))
        cut = {mk: CUT_SD * (sum(x * x for x in v) / len(v)) ** .5 for mk, v in dv.items()}
        for r in rows:
            if r['id'] in fit_ids or r['mk'] not in F:
                continue
            d = dev(r, F)
            if d == 0:
                continue
            y = -math.copysign(1, d) * (r['fz'] - r['fa'])
            hit = abs(d) >= cut.get(r['mk'], float('inf'))
            (flagged if hit else base).append((y, r['day'], sp, r['mk']))
            if hit:
                by[f"{sp} {r['mk']}"] = by.get(f"{sp} {r['mk']}", 0) + 1

    def st(v):
        m, se, t, G = RM.clustered([x[0] for x in v], [x[1] for x in v])
        return {'n': len(v), 'days': G, 'mean': None if m is None else round(m, 3), 't': None if t is None else round(t, 2)}
    f = st(flagged)
    out = {'spec': sha, 'scored': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'games': c,
           'flagged': f, 'baseline': st(base), 'toward': round(sum(x[0] > 0 for x in flagged) / len(flagged), 3) if flagged else None,
           'by': by, 'pass': bool(f['t'] is not None and f['mean'] > 0 and f['t'] >= 2)}
    with open(RESULT, 'w') as fh:
        json.dump(out, fh, indent=1)
    print('B2 scored:', json.dumps(out))


def test():
    S, sha = spec()
    assert len(sha) == 64 and S['trigger']['games'] == 1500
    r = {'L': 23.5, 'oO': -110.0, 'oU': -110.0}
    assert abs(quote_fair(S, 'nfl', '1ht', r) - 23.5) < 1e-6
    assert quote_fair(S, 'nfl', '1ht', {'L': 23.5, 'oO': -130.0, 'oU': 110.0}) > 23.5
    assert quote_fair(S, 'nfl', '1ht', {'L': 23.5, 'oO': None, 'oU': 110.0}) is None
    rows = [{'mk': '1hs', 'x': 6.0, 'fa': 3.3}, {'mk': '1hs', 'x': -4.0, 'fa': -2.2}, {'mk': 'ttH', 'x': 24.0, 'fa': 24.5}]
    F = fit(rows)
    assert abs(F['1hs'][1] - .55) < 1e-9 and abs(F['ttH'][0] - .5) < 1e-9 and abs(dev(rows[0], F)) < 1e-9
    assert standing([(1, 'a'), (5, 'b'), (9, 'c')], 6, 0) == 'b' and standing([(1, 'a')], 6, 2) is None
    print('derivs_research: ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--test' in a:
        test()
    elif '--describe' in a:
        describe([x for x in a if x in SPORTS] or ['nfl'])
    elif '--count' in a:
        print(json.dumps(count()))
    elif '--b2' in a:
        b2()
    else:
        print(__doc__)
