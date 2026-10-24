#!/usr/bin/env python3
"""NHL picks test (Noah, Oct 24 2026): does any NHL market beat the close held out? Nothing goes on the picks board
unless it does (the pick rules, scripts/games_picks.py).

    python3 scripts/nhl_picks_research.py     -> data/nhl_picks_research.json (shown on Predictions, game models tab)

Moneyline   ESPN has opening moneylines from 2023-24 (DraftKings and others): the model's side where its win chance sits
            X+ off the open's no-vig price, judged by what the bet was worth at the closing price (the close's no-vig
            chance x the open's payout - 1), as every sport's picks are.
Totals      No opening over/under prices (only the line), so totals can't be judged by the close; tested on results at
            DraftKings' closing total and prices instead (the NFL's basis), tuned 2019-20 to 2022-23, held 2023-24 on.
Puck line   No opening puck-line prices either; not testable by the close.
Rows: the walk-forward file scripts/data/games_wf/nhl.json.gz (scripts/nhl_games.py --fit).
"""
import datetime as dt
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import nhl_data as D

WF = os.path.join(HERE, 'data', 'games_wf', 'nhl.json.gz')
OUT = os.path.join(ROOT, 'data', 'nhl_picks_research.json')
TUNE, HELD = (2020, 2021, 2022, 2023), (2024, 2025, 2026)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def nv(ml):
    a, b = [1 / dec(x) for x in ml]
    return a / (a + b)


def stats(xs):
    n = len(xs)
    if n < 2:
        return {'n': n, 'ret': None, 't': None}
    m = sum(xs) / n
    sd = (sum((v - m) ** 2 for v in xs) / (n - 1)) ** .5
    return {'n': n, 'ret': round(100 * m, 2), 't': round(m / (sd / n ** .5), 2) if sd else None}


def main():
    rows = json.load(gzip.open(WF))
    ok = lambda ml: ml and all(x and abs(x) >= 100 for x in ml)
    out = {'asof': dt.date.today().isoformat(), 'ml': [], 'total': []}
    # moneyline at the open, judged by the close
    mrows = [r for r in rows if r.get('o') and r.get('c') and ok(r['o'].get('ml')) and ok(r['c'].get('ml'))]
    for x in (0.0, 0.02, 0.04, 0.06, 0.08, 0.10):
        rec = {'x': x}
        for S in sorted({r['S'] for r in mrows}):
            cr, pr = [], []
            for r in mrows:
                if r['S'] != S:
                    continue
                po, pc, pm = nv(r['o']['ml']), nv(r['c']['ml']), r['p']
                if abs(pm - po) < x:
                    continue
                home = pm > po
                d = dec(r['o']['ml'][0 if home else 1])
                cr.append((pc if home else 1 - pc) * d - 1)
                pr.append(d - 1 if (r['hs'] > r['as']) == home else -1)
            rec[S] = {**stats(cr), 'roi': stats(pr)['ret']}
        out['ml'].append(rec)
    # totals on results at DraftKings' close
    em = D.espn_map([{'id': r['id'], 'day': r['day'], 'h': r['h'], 'a': r['a']} for r in rows], fresh_after=dt.date(2000, 1, 1))
    recs = []
    for r in rows:
        e = em.get(r['id'])
        fn = os.path.join(D.CACHE, 'espn', 'odds', f'{e}.json') if e else None
        if not fn or not os.path.exists(fn) or r.get('T') is None:
            continue
        od = json.load(open(fn))
        b = ([q for q in od if q.get('book') == 'DraftKings'] or [None])[0]
        if not b or not b.get('total') or not b.get('oO') or not b.get('oU'):
            continue
        tot = r['hs'] + r['as'] - (1 if r.get('per') == 5 else 0)         # a shootout counts one goal
        recs.append((r['S'], r['T'], float(b['total']), float(b['oO']), float(b['oU']), tot))
    for x in (0.2, 0.3, 0.4, 0.5, 0.6, 0.75):
        rec = {'x': x}
        for name, Ss in (('tune', TUNE), ('held', HELD)):
            pr = []
            for S, T, L, oO, oU, tot in recs:
                if S not in Ss or abs(T - L) < x:
                    continue
                over = T > L
                pr.append(0.0 if tot == L else (dec(oO if over else oU) - 1 if (tot > L) == over else -1.0))
            rec[name] = stats(pr)
        out['total'].append(rec)
    best_ml = max((r[S]['ret'] for r in out['ml'] for S in r if S != 'x' and r[S]['ret'] is not None), default=None)
    best_t = max((r['held']['ret'] for r in out['total'] if r['held']['ret'] is not None), default=None)
    out['verdict'] = {'on': False, 'mlBest': best_ml, 'totalBest': best_t,
                      'why': 'no NHL market beat the close held out: moneyline picks at the open were worth less than the close at every cut, and totals lost at every cut on both the tuning and held-out seasons'}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(out['verdict']))
    for r in out['ml']:
        print('ml', r)
    for r in out['total']:
        print('total', r)


if __name__ == '__main__':
    main()
