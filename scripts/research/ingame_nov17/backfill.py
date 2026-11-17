#!/usr/bin/env python3
"""Research backfill (Nov 17 2026): RotoWire's news feed for past seasons, every item kept with its day, its time
(the tweet id's time when it has one, else the page cursor) and the status the live readers give it. Feeds the
in-game news backtest (ingame.py). Writes scripts/research/ingame_nov17/rw_<sport>_<season>.json.gz.

    python3 scripts/research/ingame_nov17/backfill.py football 2025
"""
import gzip
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import rotowire as RW  # noqa: E402
import rotowire_history as H  # noqa: E402

SPAN = {('football', 2024): ('2024-09-04', '2025-01-07'), ('football', 2025): ('2025-09-03', '2026-01-06'),
        ('basketball', 2024): ('2024-10-21', '2025-04-15'), ('basketball', 2025): ('2025-10-20', '2026-04-14')}


def tweet_ts(t):
    try:
        return ((int(t) >> 22) + 1288834974657) / 1000.0
    except (TypeError, ValueError):
        return None


def main(sp, season):
    lo, hi = SPAN[(sp, int(season))]
    out = os.path.join(HERE, f'rw_{sp}_{season}.json.gz')
    have = json.load(gzip.open(out)) if os.path.exists(out) else {'items': {}, 'cursor': hi + ' 12:00:00.000'}
    last, n = have['cursor'], 0
    while last and last > lo:
        try:
            d = H._feed(sp, last)
        except Exception as e:  # noqa: BLE001
            print('feed:', e); time.sleep(5); continue
        items = RW.parse(sp, d.get('updatesHTML') or '')
        cur = d.get('newLastUpdateTime')
        for it in items:
            day = H._day(it['day'])
            if not day:
                continue
            k = f"{it['pid']}|{it['head']}|{day}"
            it2 = {x: it.get(x) for x in ('pid', 'player', 'team', 'abbr', 'pos', 'inj', 'head')}
            it2.update(body=(it.get('body') or '')[:300], d=day.isoformat(), tw=tweet_ts(it.get('tweet')), cur=last)
            have['items'][k] = it2
        last = cur
        have['cursor'] = last
        n += 1
        if n % 50 == 0:
            json.dump(have, gzip.open(out, 'wt'))
            print(sp, season, n, last, len(have['items']), flush=True)
        if d.get('noMoreUpdates') or not items:
            break
        time.sleep(0.4)
    have['cursor'] = lo
    json.dump(have, gzip.open(out, 'wt'))
    print('done', sp, season, n, len(have['items']))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
