# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""M2 fetch: closed Polymarket (global) game events of one series and each moneyline's price path over the 48 h
before the listed start (ten-minute points).
    python3 m2_fetch_paths.py <series id> <tag> <out dir> [max games]
Writes <out>/<tag>_events.json (slug, title, start, outcomes, winner, token, volume, condition) and
<out>/<tag>_paths.jsonl ({slug, h: [[unix, price of outcome 0], ...]}). Regular-season window Oct 1 2025..Apr 30 2026."""
import json, os, subprocess, sys, time
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
LO, HI = '2025-10-01', '2026-04-30'


def curl(url):
    for a in range(4):
        try:
            r = subprocess.run(['curl', '-s', '--compressed', '--max-time', '60', '-A', UA, url], capture_output=True, timeout=90)
            time.sleep(.3)
            if r.stdout: return json.loads(r.stdout)
        except Exception as e: print(url[:90], e, flush=True)
        time.sleep(3 * (a + 1))
    return None


def ts(s):
    import datetime as dt
    s = s.replace(' ', 'T').replace('+00', '').rstrip('Z')[:19]
    return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp())


def events(series, fn):
    if os.path.exists(fn): return json.load(open(fn))
    import datetime as dt
    out, seen = [], set()
    day = dt.date.fromisoformat(LO)
    while day.isoformat() <= HI:                                 # one week at a time: the offset has a ceiling
        hi = min(day + dt.timedelta(days=6), dt.date.fromisoformat(HI))
        off = 0
        while True:
            d = curl(f'https://gamma-api.polymarket.com/events?series_id={series}&closed=true&limit=100&offset={off}'
                     f'&order=startDate&ascending=true&end_date_min={day}T00:00:00Z&end_date_max={hi}T23:59:59Z')
            if not isinstance(d, list) or not d: break
            for e in d:
                if e['slug'] in seen: continue
                seen.add(e['slug'])
                for m in e.get('markets', []):
                    if m.get('sportsMarketType') != 'moneyline' or not m.get('gameStartTime'): continue
                    try:
                        tok = json.loads(m['clobTokenIds']); px = json.loads(m.get('outcomePrices') or '[]'); oc = json.loads(m['outcomes'])
                    except Exception: continue
                    if len(tok) != 2 or len(px) != 2: continue
                    out.append({'slug': e['slug'], 'title': e.get('title'), 'start': ts(m['gameStartTime']), 'oc': oc,
                                'win': 0 if float(px[0]) > .5 else (1 if float(px[1]) > .5 else None), 'tok': tok[0],
                                'vol': round(float(m.get('volumeNum') or 0)), 'cond': m.get('conditionId'), 'id': int(e['id'])})
            if len(d) < 100: break
            off += 100
        print('events', day, len(out), flush=True)
        day = hi + dt.timedelta(days=1)
    json.dump(out, open(fn, 'w'))
    return out


def main(series, tag, outdir, cap=None):
    os.makedirs(outdir, exist_ok=True)
    ev = events(series, os.path.join(outdir, tag + '_events.json'))
    if cap and len(ev) > cap:                                   # lowest event ids first inside each month, in proportion
        import collections
        by = collections.defaultdict(list)
        for e in ev: by[time.strftime('%Y-%m', time.gmtime(e['start']))].append(e)
        keep = []
        for k, v in by.items():
            v.sort(key=lambda e: e['id']); keep += v[:max(1, round(cap * len(v) / len(ev)))]
        ev = keep
    fn = os.path.join(outdir, tag + '_paths.jsonl')
    done = {json.loads(l)['slug'] for l in open(fn)} if os.path.exists(fn) else set()
    with open(fn, 'a') as f:
        for i, e in enumerate(ev):
            if e['slug'] in done: continue
            d = curl(f"https://clob.polymarket.com/prices-history?market={e['tok']}&startTs={e['start'] - 49 * 3600}&endTs={e['start'] + 600}&fidelity=10") or {}
            h = [[int(x['t']), round(float(x['p']), 4)] for x in d.get('history') or []]
            f.write(json.dumps({'slug': e['slug'], 'h': h}) + '\n'); f.flush()
            if i % 100 == 0: print(tag, i, len(ev), len(h), flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else None)
