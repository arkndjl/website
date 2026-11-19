#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Forward logs for two Counter-Strike scoring targets (research ledgers; nothing here feeds a page).

    python3 scripts/cs2_market_log.py           append to both ledgers (the cs2-market-log workflow)
    python3 scripts/cs2_market_log.py --test    self-check, no network

1. Major stage markets: every Polymarket event whose title names the current Major (cs2_events.MAJOR) and that
   lists 8+ outcomes (winner, qualify to a stage, reach the final) -> scripts/data/ledger/cs2/stage_markets.jsonl,
   one row a run and event: {t, ev, title, sha (sha256 of data/cs2_events.json at that moment), m: [[team, bid, ask,
   last trade]]}. Scored once after the Major ends against scripts/cs2_ledger.py's pre-stage copies.
2. bo3.gg crowd share: `bet_updates.team_N.aggrement_score` of upcoming series and of the same series once finished
   -> scripts/data/ledger/cs2/bo3_share.jsonl {t, id, st (upcoming / finished), start, t1, t2, s1, s2}. A row is
   written when a series first appears, when its share moves .005, and once after it ends. No result is stored.
"""
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
STORE = os.path.join(HERE, 'data', 'ledger', 'cs2')
STAGE = os.path.join(STORE, 'stage_markets.jsonl')
SHARE = os.path.join(STORE, 'bo3_share.jsonl')
EVENTS = os.path.join(ROOT, 'data', 'cs2_events.json')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
SEARCH = 'https://gamma-api.polymarket.com/public-search?limit_per_type=50&q='


def curl(u):
    r = subprocess.run(['curl', '-sS', '--compressed', '-m', '40', '-A', UA, u], capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout)


def stage_rows(events, name, stamp, sha):
    """ledger rows for the multi-outcome events of the Major called name"""
    out = []
    words = [w for w in name.lower().split() if not w.isdigit()]
    for e in events:
        t = (e.get('title') or '').lower()
        ms = e.get('markets') or []
        if len(ms) < 8 or not all(w in t for w in words) or ' vs ' in t:
            continue
        m = []
        for x in ms:
            f = lambda k: (float(x[k]) if x.get(k) not in (None, '') else None)  # noqa: E731
            m.append([x.get('groupItemTitle') or x.get('question'), f('bestBid'), f('bestAsk'), f('lastTradePrice')])
        out.append({'t': stamp, 'ev': str(e['id']), 'title': e.get('title'), 'sha': sha, 'm': m})
    return out


def share_rows(matches, status, stamp, last):
    """rows for series whose share is new, moved .005 or (finished) not yet logged as finished"""
    out = []
    for m in matches:
        bu = m.get('bet_updates') or {}
        a, b = bu.get('team_1') or {}, bu.get('team_2') or {}
        s1, s2 = a.get('aggrement_score'), b.get('aggrement_score')
        if s1 is None or s2 is None:
            continue
        if a.get('team_id') != m.get('team1_id'):
            s1, s2 = s2, s1
        prev = last.get(m['id'])
        if status == 'finished':
            if prev is None or prev['st'] == 'finished':
                continue
        elif prev is not None and prev['st'] == 'upcoming' and abs(prev['s1'] - s1) < .005:
            continue
        out.append({'t': stamp, 'id': m['id'], 'st': status, 'start': m.get('start_date'), 't1': m.get('team1_id'),
                    't2': m.get('team2_id'), 's1': s1, 's2': s2})
    return out


def read(p):
    return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def main():
    import cs2_bo3
    import cs2_events
    os.makedirs(STORE, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    name = cs2_events.MAJOR['name']
    sha = hashlib.sha256(open(EVENTS, 'rb').read()).hexdigest() if os.path.exists(EVENTS) else None
    try:
        ev = curl(SEARCH + urllib.parse.quote(name)).get('events') or []
        rows = stage_rows(ev, name, stamp, sha)
        with open(STAGE, 'a') as f:
            for r in rows:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
        print('stage markets:', len(rows), 'events logged')
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        print('stage markets: failed', e)
    last = {}
    for r in read(SHARE):
        last[r['id']] = r
    new = []
    try:
        for status, sort in (('upcoming', 'start_date'), ('finished', '-start_date')):
            for off in range(0, 300, 100):
                res = cs2_bo3.get(f'matches?page[offset]={off}&page[limit]=100&sort={sort}&filter[matches.status][in]={status}')
                got = share_rows(res['results'], status, stamp, last)
                new += got
                for r in got:
                    last[r['id']] = r
                if len(res['results']) < 100:
                    break
        with open(SHARE, 'a') as f:
            for r in new:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
        print('bo3 share:', len(new), 'rows')
    except Exception as e:  # noqa: BLE001
        print('bo3 share: failed', e)


def test():
    ev = [{'id': 1, 'title': 'PGL Major Singapore 2026: Qualify to Stage 2', 'markets': [{'groupItemTitle': f'T{i}', 'bestBid': '0.4', 'bestAsk': 0.5} for i in range(9)]},
          {'id': 2, 'title': 'Counter-Strike: A vs B - PGL Major Singapore', 'markets': [{}] * 9},
          {'id': 3, 'title': 'Other Major 2026: Winner', 'markets': [{}] * 9}]
    r = stage_rows(ev, 'PGL Major Singapore 2026', 't', 'x')
    assert len(r) == 1 and r[0]['m'][0] == ['T0', 0.4, 0.5, None], r
    m = {'id': 5, 'team1_id': 2, 'team2_id': 1, 'start_date': 's',
         'bet_updates': {'team_1': {'team_id': 1, 'aggrement_score': .3}, 'team_2': {'team_id': 2, 'aggrement_score': .7}}}
    a = share_rows([m], 'upcoming', 't', {})
    assert a[0]['s1'] == .7 and a[0]['s2'] == .3
    last = {5: a[0]}
    assert share_rows([m], 'upcoming', 't', last) == []
    assert len(share_rows([m], 'finished', 't', last)) == 1
    assert share_rows([m], 'finished', 't', {5: dict(a[0], st='finished')}) == []
    assert share_rows([m], 'finished', 't', {}) == []
    print('ok')


if __name__ == '__main__':
    test() if '--test' in sys.argv else main()
