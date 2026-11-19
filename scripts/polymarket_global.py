#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Polymarket (global) tennis moneylines for the tennis picks (scripts/tennis_picks.py; Noah, Nov 19 2026).

    python3 scripts/polymarket_global.py            # print the open tennis moneylines
    python3 scripts/polymarket_global.py --test

Public reads only, no account and no orders: open events from the gamma API (series ATP 10365, WTA 10366) and, for a
pick's closing price, the clob's price history. polymarket.com's robots.txt allows every agent; the two API hosts
publish none. One request a series a run, one a graded pick.

h2h() rows: {id, slug, lg 'ATP' | 'WTA', ev (the listing's event), a, b, start (ISO Z), bid, ask (of a, shares 0-1),
vol ($ traded), tok [a, b] (clob token ids)}. A row needs a two-sided quote on a.
"""
import datetime
import json
import subprocess
import sys

UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
GAMMA = 'https://gamma-api.polymarket.com/events'
CLOB = 'https://clob.polymarket.com/prices-history'
SERIES = {'ATP': 10365, 'WTA': 10366}
FEE = 0.03                # the sports taker fee: FEE x p x (1 - p) a share


def get(u):
    r = subprocess.run(['curl', '-sS', '--compressed', '-m', '40', '-A', UA, u], capture_output=True, text=True, timeout=50)
    return json.loads(r.stdout)


def iso(s):
    """'2026-11-20 13:00:00+00' -> '2026-11-20T13:00:00Z'"""
    if not s:
        return None
    s = s.strip().replace(' ', 'T')
    for suf in ('+00:00', '+00', 'Z'):
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    return s[:19] + 'Z'


def parse(events, lg):
    out = []
    for e in events or []:
        for m in e.get('markets', []):
            if m.get('sportsMarketType') != 'moneyline' or m.get('closed') or not m.get('active') or not m.get('acceptingOrders'):
                continue
            try:
                names = json.loads(m.get('outcomes') or '[]')
                tok = json.loads(m.get('clobTokenIds') or '[]')
                bid, ask = float(m['bestBid']), float(m['bestAsk'])
            except (ValueError, TypeError, KeyError):
                continue
            start = iso(m.get('gameStartTime'))
            if len(names) != 2 or len(tok) != 2 or not start or not 0 < bid < ask < 1:
                continue
            out.append({'id': str(e.get('id')), 'slug': e.get('slug'), 'lg': lg, 'ev': (e.get('eventMetadata') or {}).get('league'),
                        'a': names[0], 'b': names[1], 'start': start, 'bid': bid, 'ask': ask,
                        'vol': round(float(m.get('volumeNum') or 0)), 'tok': tok})
    return out


def h2h():
    out = []
    for lg, sid in SERIES.items():
        try:
            out += parse(get(f'{GAMMA}?series_id={sid}&closed=false&limit=200'), lg)
        except Exception as ex:  # noqa: BLE001
            print(f'polymarket global {lg}: failed ({ex})')
    return out


def cost(p):
    """what a share bought at p costs after the fee"""
    return p + FEE * p * (1 - p)


def close(tok, start, lead=3600):
    """the token's last price at or before `lead` seconds ahead of the start (ISO Z), or None"""
    t1 = int(datetime.datetime.strptime(start, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).timestamp()) - lead
    try:
        h = get(f'{CLOB}?market={tok}&startTs={t1 - 86400}&endTs={t1}&fidelity=10').get('history') or []
    except Exception as ex:  # noqa: BLE001
        print(f'polymarket global close: failed ({ex})')
        return None
    h = [x for x in h if x.get('t', 0) <= t1]
    return float(h[-1]['p']) if h else None


def self_test():
    ev = [{'id': 7, 'slug': 's', 'eventMetadata': {'league': 'Metz'}, 'markets': [
        {'sportsMarketType': 'moneyline', 'active': True, 'acceptingOrders': True, 'outcomes': '["A One", "B Two"]', 'clobTokenIds': '["1", "2"]',
         'bestBid': 0.45, 'bestAsk': 0.47, 'gameStartTime': '2026-11-20 14:00:00+00', 'volumeNum': 12.4},
        {'sportsMarketType': 'moneyline', 'active': True, 'acceptingOrders': False, 'outcomes': '["C", "D"]', 'clobTokenIds': '["3", "4"]',
         'bestBid': 0.4, 'bestAsk': 0.5, 'gameStartTime': '2026-11-20 14:00:00+00'},
        {'sportsMarketType': 'totals', 'active': True, 'acceptingOrders': True}]}]
    r = parse(ev, 'ATP')
    assert len(r) == 1 and r[0]['a'] == 'A One' and r[0]['start'] == '2026-11-20T14:00:00Z' and r[0]['tok'] == ['1', '2'], r
    assert abs(cost(0.5) - 0.5075) < 1e-9 and iso('2026-11-20T13:00:00Z') == '2026-11-20T13:00:00Z'
    print('polymarket_global: self-test ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        self_test()
    else:
        for g in h2h():
            print(g['lg'], g['start'], g['a'], 'v', g['b'], g['bid'], g['ask'], g['vol'], g['ev'])
