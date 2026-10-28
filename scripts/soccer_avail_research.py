#!/usr/bin/env python3
"""Availability in the soccer game model (Oct 2026): do regulars who sat out (or were sent off in) their club's last
league match predict the next one beyond the ratings? Big five, Understat line-ups 2014-15 on.

    python3 scripts/soccer_avail_research.py      # -> data/soccer_avail_research.json

1. keep rates: share of a regular's usual minutes he plays next, by what happened in the last match (2015-22 only).
2. walk-forward log loss with the avz term at several weights, tune 2013-22 vs held out 2023+, t clustered by day.
Needs the Understat match cache (scripts/.cache/soccer/usm; /mnt/project-files/soccer/understat_cache.tgz)."""
import bisect
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soccer_data as D
import soccer_games as G

OUT = os.path.join(G.ROOT, 'data', 'soccer_avail_research.json')


# availability (big five, Understat line-ups): a regular (60+ minutes a match over the 5 league matches before his
# club's last one) who sat out that last match, or was sent off in it, is likely out again. AV_KEEP[category] =
# share of his usual minutes he played next, measured on 2015-22 league matches (keep_rates);
# 'zero2' = out the last two. Each absence costs his prior-season GAR a 90 (static/data/soccer-war/<S-1>.json;
# AV_V0 when he has none) x the minutes he is expected to lose.
AV_KEEP = {'zero': 0.53, 'zero2': 0.262, 'red': 0.06}
AV_V0, AV_REG, AV_DAYS = 0.05, 60, 30
WARD = os.path.join(G.ROOT, 'static', 'data', 'soccer-war')


def add_av(rows, keep=None, value=True, cats=None, fetch=False):
    """avz on each row: half the away-minus-home goals of value expected to be missing (0 where a side has no
    Understat line-ups in the last AV_DAYS days). fetch=True pulls missing line-ups (the live season)"""
    keep = keep or AV_KEEP
    gv = {}

    def v(S, p):
        if not value:
            return AV_V0
        if S not in gv:
            try:
                gv[S] = {x['p']: x['gar90'] for x in json.load(open(os.path.join(WARD, f'{S}.json')))['players']}
            except (OSError, KeyError, ValueError):
                gv[S] = {}
        return gv[S].get(p, AV_V0)
    seq = defaultdict(list)                                  # club -> [(day, {player: minutes}, {sent off})]
    for r in sorted((r for r in rows if r.get('us') and r.get('hs') is not None), key=lambda r: r['day']):
        p = os.path.join(D.CACHE, 'usm', str(r['us'])[-2:], f"{r['us']}.json.gz")
        m = D.us_match(r['us']) if fetch or os.path.exists(p) else None
        if not m:
            continue
        for s, t in (('h', r['h']), ('a', r['a'])):
            ro = m['ro'][s]
            seq[t].append((r['day'], {str(x['player_id']): int(x['time'] or 0) for x in ro},
                           {str(x['player_id']) for x in ro if int(x.get('red_card') or 0)}))
    days = {t: [x[0] for x in L] for t, L in seq.items()}

    def deficit(t, day):
        L = seq.get(t)
        if not L:
            return 0.0
        i = bisect.bisect_left(days[t], day) - 1           # the club's last league match before this day
        if i < 6 or (dt.date.fromisoformat(day) - dt.date.fromisoformat(L[i][0])).days > AV_DAYS:
            return 0.0
        S = D.season_of(day)
        last, prev, base = L[i], L[i - 1], L[i - 6:i - 1]
        out = 0.0
        for p in set().union(*[x[1] for x in base]):
            b = sum(x[1].get(p, 0) for x in base) / 5
            if b < AV_REG:
                continue
            if p in last[2]:
                c = 'red'
            elif last[1].get(p, 0) == 0:
                c = 'zero2' if prev[1].get(p, 0) == 0 else 'zero'
            else:
                continue
            if cats and c not in cats:
                continue
            out += v(S - 1, p) * b * (1 - keep[c]) / 90
        return out
    for r in rows:
        if r['lg'] in G.SCORED or r.get('us'):
            r['avz'] = round((deficit(r['a'], r['day']) - deficit(r['h'], r['day'])) / 2, 4)
    return rows


def keep_rates(rows, hi=2022):
    seq = defaultdict(list)
    for r in sorted((r for r in rows if r.get('us') and r.get('hs') is not None), key=lambda r: r['day']):
        if D.season_of(r['day']) > hi:
            continue
        m = D.us_match(r['us'])
        for s, t in (('h', r['h']), ('a', r['a'])):
            ro = m['ro'][s]
            seq[t].append(({str(x['player_id']): int(x['time'] or 0) for x in ro},
                           {str(x['player_id']) for x in ro if int(x.get('red_card') or 0)}))
    acc = defaultdict(lambda: [0, 0.0, 0.0])
    for L in seq.values():
        for i in range(6, len(L) - 1):
            last, prev, base, nxt = L[i], L[i - 1], L[i - 6:i - 1], L[i + 1]
            for p in set().union(*[x[0] for x in base]):
                b = sum(x[0].get(p, 0) for x in base) / 5
                if b < AV_REG:
                    continue
                c = 'red' if p in last[1] else ('zero2' if prev[0].get(p, 0) == 0 else 'zero') \
                    if last[0].get(p, 0) == 0 else 'played'
                a = acc[c]
                a[0] += 1; a[1] += b; a[2] += nxt[0].get(p, 0)
    return {c: {'n': a[0], 'keep': round(a[2] / a[1], 3)} for c, a in acc.items()}


def with_av(rows, P, av):
    """the avz term at weight av, carried in the squad-value slot (lambdas adds P['mv'] x mvz to each side)"""
    for r in rows:
        r.setdefault('mvz0', r.get('mvz', 0.0))
        r['mvz'] = r['mvz0'] + av / P['mv'] * r.get('avz', 0.0)


def scores(rows, P, av=0.0):
    with_av(rows, P, av)
    out = {}
    rho = P['rho']

    def score(r, S, lh, la, R):
        pw, pd, pl = G.wdl(lh, la, rho)
        y = pw if r['hs'] > r['as'] else pd if r['hs'] == r['as'] else pl
        out[r['id']] = (S, r['day'], r['lg'], -math.log(max(y, 1e-9)), r.get('avz', 0.0))
    G.run(rows, P, score)
    return out


def compare(base, new, lo, hi, only=None):
    d, k = [], []
    for i, (S, day, lg, l0, z) in base.items():
        if lo <= S <= hi and (only is None or only(lg, z)):
            d.append(new[i][3] - l0); k.append(day)
    return {'n': len(d), 'dLL': round(sum(d) / max(1, len(d)) * 1e4, 2), 't': G.cl_t(d, k)}


def main():
    rows = G.add_mv(G.add_market(D.load(G.HIST)))
    kr = keep_rates(rows)
    print('keep', kr, flush=True)
    keep = {c: kr[c]['keep'] for c in ('zero', 'zero2', 'red')}
    P = G.params()
    add_av(rows, keep=keep)
    base = scores(rows, P)
    res = {'keep': kr, 'tests': []}
    per = lambda lo, hi: (lo, hi)
    for name, kw, avs in (('value (prior-season GAR/90)', {}, (0.15, 0.25, 0.5, 1.0)),
                          ('flat value', {'value': False}, (0.5, 1.0)),
                          ('red cards only', {'cats': {'red'}}, (0.75,)),
                          ('sat out only', {'cats': {'zero', 'zero2'}}, (0.75,)),
                          ('out two in a row', {'cats': {'zero2'}}, (0.15, 0.3)),
                          ('out two in a row + red cards', {'cats': {'zero2', 'red'}}, (0.15, 0.3))):
        add_av(rows, keep=keep, **kw)
        for av in avs:
            s = scores(rows, P, av)
            t = {'name': name, 'av': av,
                 'tune': compare(base, s, *G.TUNE), 'hold': compare(base, s, G.HOLD_FROM, 2100),
                 'holdBig5': compare(base, s, G.HOLD_FROM, 2100, lambda lg, z: lg in D.BIG5),
                 'holdAbsent': compare(base, s, G.HOLD_FROM, 2100, lambda lg, z: abs(z) > 0.02),
                 'bySeason': {S: compare(base, s, S, S)['dLL'] for S in range(2016, 2027)}}
            res['tests'].append(t)
            print(json.dumps(t), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
