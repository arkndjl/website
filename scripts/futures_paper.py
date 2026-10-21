#!/usr/bin/env python3
"""Paper log of season win-total positions against Kalshi's free win ladders (data/futures_paper_<sport>.json).

    python3 scripts/futures_paper.py nba    # after scripts/nba_games.py (data/nba_games.json)
    python3 scripts/futures_paper.py nfl    # after scripts/nfl_games.py
    python3 scripts/futures_paper.py cfb    # after the CFB model (data/cfb_model.json); no backtest, logged for the record

Paper only: no money. Pre-registered rule (registered 2026-10-21, the commit date; a change restarts the clock):
  Our chance a team reaches k wins: normal, centre = the market's median + w x (our expected wins - the market's
  median), spread = k_sd x our sims' sd now (w and k_sd from the backtest's tuning seasons in data/futures_fit.json;
  CFB, without a backtest, w .25 and k_sd 1). The market's median is where Kalshi's ladder (mid prices of "k+ wins")
  crosses 50%. Only the rung nearest that median is bet (the win-total line's equivalent, as in the backtest), as a
  YES at the ask or a NO at 1 - the bid, with Kalshi's taker fee (.07 x price x (1 - price), rounded up to the cent).
  One position a team a season: the side with the higher expected return per dollar, opened the first run it clears
  the backtest's EV cut, 1u risked, held to settlement. Rungs priced under 5c or over 95c, with nothing at the ask,
  or with a bid-ask gap over 10c are skipped.
Each run marks every open position to the rung's current mid (the move in our favour is the futures' CLV) and settles
finished markets. Snapshots of our expected wins and the market median go to scripts/data/futures/<sport>-snap.jsonl.
"""
import json
import math
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIT = os.path.join(ROOT, 'data', 'futures_fit.json')
API = 'https://api.elections.kalshi.com/trade-api/v2/markets'
SERIES = {'nba': 'KXNBAWINS', 'nfl': 'KXNFLWINS', 'cfb': 'KXNCAAFWINS'}
GAMES = {'nba': 82, 'nfl': 17, 'cfb': 12}
REGISTERED = '2026-10-21'
# Kalshi ticker codes -> the game models' codes
NBA = {'GSW': 'GS', 'NOP': 'NO', 'UTA': 'UTAH', 'NYK': 'NY', 'SAS': 'SA', 'WAS': 'WSH', 'BRK': 'BKN', 'PHO': 'PHX', 'CHO': 'CHA'}
NFL = {'LAR': 'LA', 'JAC': 'JAX', 'WSH': 'WAS', 'OAK': 'LV'}
CFB = {'Miami (FL)': 'Miami', 'Ole Miss': 'Ole Miss', 'UConn': 'UConn', 'UMass': 'UMass', 'NC State': 'NC State',
       'North Carolina St.': 'NC State', 'Pittsburgh': 'Pittsburgh', 'UCF': 'UCF', 'SMU': 'SMU', 'BYU': 'BYU',
       'TCU': 'TCU', 'LSU': 'LSU', 'USC': 'USC', 'UCLA': 'UCLA', 'UNLV': 'UNLV'}


def get(url):
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net paper futures'}), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(3 * (i + 1))
    raise RuntimeError('Kalshi rate limit')


def markets(series, status='open'):
    out, cur = [], ''
    while True:
        d = get(f'{API}?series_ticker={series}&status={status}&limit=1000' + (f'&cursor={cur}' if cur else ''))
        out += d.get('markets', [])
        cur = d.get('cursor')
        if not cur:
            return out
        time.sleep(1)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fee(p):
    return math.ceil(0.07 * p * (1 - p) * 100 - 1e-9) / 100


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def ours(sport):
    """team -> (expected wins, our sd now, games left, record)"""
    if sport == 'cfb':
        d = json.load(open(os.path.join(ROOT, 'data', 'cfb_model.json')))
        out = {}
        for t in d['sim']:
            left = t.get('left') or 0
            out[t['team']] = (float(t['projW']), max(0.3, 0.55 * math.sqrt(left)), left, t['rec'])
        return out, d['asof']
    d = json.load(open(os.path.join(ROOT, 'data', f'{sport}_games.json')))
    F = json.load(open(FIT))[sport]
    pre_sd = F['accuracy']['all']['simSd']                  # a full season's sim sd, before game 1
    out = {}
    for t in d['power']:
        w, l = (int(x) for x in t['rec'].split('-')[:2])
        left = GAMES[sport] - w - l
        out[t['t']] = (float(t['wins']), max(0.3, pre_sd * math.sqrt(left / GAMES[sport])), left, t['rec'])
    return out, d['asof']


def team_of(sport, m, names):
    if sport == 'cfb':
        nm = re.sub(r'^Will (the )?(.*?) (college football team )?(win|have).*$', r'\2', m['title'])
        nm = CFB.get(nm, nm.replace(' St.', ' State'))
        return nm if nm in names else None
    code = m['event_ticker'].split('-')[1][2:]
    return (NBA if sport == 'nba' else NFL).get(code, code)


def ladder(rows):
    """strike -> mid, and the median: where the ladder's P(k+ wins) crosses 50% (k - .5 on a continuous scale)"""
    pts = []
    for m in rows:
        b, a = f(m.get('yes_bid_dollars')), f(m.get('yes_ask_dollars'))
        if b is None or a is None or a <= 0:
            continue
        pts.append((m['floor_strike'], (b + a) / 2))
    pts.sort()
    for (k0, p0), (k1, p1) in zip(pts, pts[1:]):
        if p0 >= 0.5 >= p1 and p0 > p1:
            return k0 - 0.5 + (p0 - 0.5) / (p0 - p1) * (k1 - k0)
    return None


def main():
    sport = sys.argv[1]
    out_fn = os.path.join(ROOT, 'data', f'futures_paper_{sport}.json')
    snap_fn = os.path.join(ROOT, 'scripts', 'data', 'futures', f'{sport}-snap.jsonl')
    F = json.load(open(FIT)).get(sport) if sport != 'cfb' else None
    w, ksd, cut = (F['w'], F['k'], F['cut']) if F else (0.25, 1.0, 0.05)
    O, asof = ours(sport)
    book = json.load(open(out_fn)) if os.path.exists(out_fn) else {'registered': REGISTERED, 'positions': []}
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    ms = markets(SERIES[sport])
    by = {}
    for m in ms:
        t = team_of(sport, m, O)
        if t:
            by.setdefault(t, []).append(m)
    pos = {p['team']: p for p in book['positions']}
    rows, snaps = [], []
    for t, mk in sorted(by.items()):
        if t not in O:
            continue
        xw, sd, left, rec = O[t]
        med = ladder(mk)
        if med is None:
            continue
        c = med + w * (xw - med)
        best = None
        # the rung nearest the market's median: the win-total line's equivalent (the backtest bet at the line;
        # cheap tail rungs would reward the normal's tail errors, not the projection)
        near = min(abs(m['floor_strike'] - 0.5 - med) for m in mk)
        for m in mk:
            k = m['floor_strike']
            if abs(k - 0.5 - med) > near + 1e-9:
                continue
            p = 1 - phi((k - 0.5 - c) / (ksd * sd))
            b, a = f(m.get('yes_bid_dollars')), f(m.get('yes_ask_dollars'))
            if a is None or b is None or not f(m.get('yes_ask_size_fp')) or a - b > 0.1:
                continue
            for side, q, price in (('yes', p, a), ('no', 1 - p, 1 - b)):
                if not 0.05 <= price <= 0.95:
                    continue
                cost = price + fee(price)
                ev = (q - cost) / cost
                if best is None or ev > best['ev']:
                    best = {'ticker': m['ticker'], 'strike': k, 'side': side, 'price': round(price, 2), 'fee': fee(price),
                            'p': round(q, 3), 'ev': round(ev, 3)}
        snaps.append({'at': now, 't': t, 'xW': round(xw, 2), 'med': round(med, 2), 'c': round(c, 2), 'rec': rec})
        rows.append({'team': t, 'rec': rec, 'xW': round(xw, 1), 'med': round(med, 1), 'c': round(c, 1),
                     'best': best, 'open': bool(best and best['ev'] >= cut)})
        if t not in pos and best and best['ev'] >= cut:
            pos[t] = {'team': t, 'opened': now, 'modelAsof': asof, 'xW': round(xw, 2), 'med': round(med, 2), 'rec': rec,
                      **best, 'stake': 1.0, 'mark': best['price'], 'markAt': now, 'result': None, 'ret': None}
    # mark and settle
    mid = {m['ticker']: m for m in ms}
    for p in pos.values():
        if p['result'] is not None:
            continue
        m = mid.get(p['ticker'])
        if m is None:
            m = get(f"{API}/{p['ticker']}").get('market', {})
        b, a = f(m.get('yes_bid_dollars')), f(m.get('yes_ask_dollars'))
        if b is not None and a is not None and a > 0:
            y = (b + a) / 2
            p['mark'] = round(y if p['side'] == 'yes' else 1 - y, 3); p['markAt'] = now
        if m.get('result') in ('yes', 'no'):
            won = m['result'] == p['side']
            cost = p['price'] + p['fee']
            p['result'] = 'win' if won else 'loss'
            p['ret'] = round((1 - cost) / cost if won else -1.0, 3)
    P = sorted(pos.values(), key=lambda p: p['opened'])
    done = [p for p in P if p['ret'] is not None]
    openp = [p for p in P if p['ret'] is None]
    clv = [(p['mark'] - p['price']) / (p['price'] + p['fee']) for p in openp]
    book.update({'sport': sport, 'asof': now, 'modelAsof': asof, 'rule': {'w': w, 'kSd': ksd, 'cut': cut, 'stake': '1u risked',
                 'backtested': sport != 'cfb'}, 'positions': P, 'board': rows,
                 'summary': {'n': len(P), 'open': len(openp), 'settled': len(done), 'won': sum(p['result'] == 'win' for p in done),
                             'units': round(sum(p['ret'] for p in done), 2),
                             'markRet': round(sum(clv) / len(clv), 4) if clv else None,
                             'markBeat': round(sum(c > 0 for c in clv) / len(clv), 3) if clv else None}})
    with open(out_fn, 'w') as fh:
        json.dump(book, fh, indent=1)
    os.makedirs(os.path.dirname(snap_fn), exist_ok=True)
    with open(snap_fn, 'a') as fh:
        for s in snaps:
            fh.write(json.dumps(s, separators=(',', ':')) + '\n')
    print(sport, 'teams', len(rows), 'positions', len(P), 'new', sum(1 for p in P if p['opened'] == now), book['summary'])


if __name__ == '__main__':
    main()
