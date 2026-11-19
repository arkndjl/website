#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Private Polymarket (global) helper for the tennis + CS2 sweep tests: event listings from gamma-api and
pre-start price paths from clob prices-history, cached on disk. Research only; nothing here feeds a page.

    python3 pm.py list <name> <query> <from> <to>    # day windows on start_date, slim rows -> <CACHE>/list_<name>.jsonl
    python3 pm.py hist                               # worker: pulls every token in <CACHE>/queue.jsonl, in file order

Every request is at least 1.05 s after the last one to the same host. Nothing that starts on or after LOCK is kept.
"""
import datetime as dt, json, os, subprocess, sys, time
CACHE = os.environ.get('PM_CACHE', '/home/user/scratch-tennis-cs2/pm')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
GAMMA = 'https://gamma-api.polymarket.com/events'
CLOB = 'https://clob.polymarket.com/prices-history'
LOCK = dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc)
_last = {}


def get(u, tries=4):
    host = u.split('/')[2]
    for k in range(tries):
        w = 1.05 - (time.time() - _last.get(host, 0))
        if w > 0: time.sleep(w)
        _last[host] = time.time()
        try:
            r = subprocess.run(['curl', '-sS', '--compressed', '-m', '40', '-A', UA, u], capture_output=True, text=True, timeout=50)
            return json.loads(r.stdout)
        except (ValueError, subprocess.TimeoutExpired):
            time.sleep(3 * (k + 1))
    return None


def ts(s):
    if not s: return None
    s = s.replace(' ', 'T').replace('+00', '+00:00').replace('+00:00:00', '+00:00').replace('Z', '+00:00')
    try: return dt.datetime.fromisoformat(s)
    except ValueError: return None


def slim(e):
    ms = []
    for m in e.get('markets', []):
        ms.append({'smt': m.get('sportsMarketType'), 'q': m.get('question'), 'o': m.get('outcomes'), 'res': m.get('outcomePrices'),
                   't0': m.get('gameStartTime'), 'vol': m.get('volumeNum'), 'tok': m.get('clobTokenIds'), 'line': m.get('line'),
                   'g': m.get('groupItemTitle'), 'created': m.get('createdAt'), 'closed': m.get('closedTime'), 'cid': m.get('conditionId')})
    return {'id': e['id'], 'title': e.get('title'), 'slug': e.get('slug'), 't0': e.get('startTime'), 'vol': e.get('volume'),
            'score': e.get('score'), 'lg': (e.get('eventMetadata') or {}).get('league'), 'end': e.get('endDate'),
            'start': e.get('startDate'), 'fin': e.get('finishedTimestamp'), 'm': ms}


def before_lock(e):
    t = ts(e.get('startTime')) or ts(e.get('startDate'))
    for m in e.get('markets', []):
        g = ts(m.get('gameStartTime'))
        if g and g >= LOCK: return False
    return t is not None and t < LOCK


def listing(name, q, d0, d1, field='start_date'):
    out = os.path.join(CACHE, f'list_{name}.jsonl')
    done = os.path.join(CACHE, f'list_{name}.days')
    have = set(open(done).read().split()) if os.path.exists(done) else set()
    seen = set()
    if os.path.exists(out):
        for line in open(out): seen.add(json.loads(line)['id'])
    d = d0
    while d < d1:
        if d.isoformat() in have: d += dt.timedelta(days=1); continue
        off, rows, ok = 0, [], True
        while True:
            r = get(f'{GAMMA}?{q}&limit=100&offset={off}&{field}_min={d}T00:00:00Z&{field}_max={d + dt.timedelta(days=1)}T00:00:00Z')
            if r is None or isinstance(r, dict): ok = False; break
            rows += r
            if len(r) < 100: break
            off += 100
        if ok:
            with open(out, 'a') as f:
                for e in rows:
                    if e['id'] in seen or not before_lock(e): continue
                    seen.add(e['id']); f.write(json.dumps(slim(e)) + '\n')
            open(done, 'a').write(d.isoformat() + '\n')
        print(name, d, len(rows), ok, flush=True)
        d += dt.timedelta(days=1)


def load_hist():
    have = {}
    p = os.path.join(CACHE, 'hist.jsonl')
    if os.path.exists(p):
        for line in open(p):
            try: r = json.loads(line)
            except ValueError: continue
            have[(r['tok'], r.get('k', ''))] = r['h']
    return have


def hist_worker():
    """queue rows: {tok, a, b, f, k}: token, window start and end (unix s), fidelity (minutes), kind tag"""
    p = os.path.join(CACHE, 'hist.jsonl')
    have = set(load_hist())
    idle = 0
    while not os.path.exists(os.path.join(CACHE, 'stop')):
        q = [json.loads(x) for x in open(os.path.join(CACHE, 'queue.jsonl'))] if os.path.exists(os.path.join(CACHE, 'queue.jsonl')) else []
        todo = [j for j in q if (j['tok'], j.get('k', '')) not in have]
        if not todo:
            time.sleep(20); idle += 1
            continue
        for i, j in enumerate(todo[:200]):
            if j['b'] >= LOCK.timestamp() and not j.get('k', '').startswith('log'): continue
            d = get(f"{CLOB}?market={j['tok']}&startTs={int(j['a'])}&endTs={int(j['b'])}&fidelity={j.get('f', 10)}")
            if d is None: continue
            h = [[x['t'], x['p']] for x in d.get('history', [])]
            with open(p, 'a') as f: f.write(json.dumps({'tok': j['tok'], 'k': j.get('k', ''), 'h': h}) + '\n')
            have.add((j['tok'], j.get('k', '')))
        print(time.strftime('%H:%M:%S'), 'done', len(have), 'left', len(todo) - 200, flush=True)


if __name__ == '__main__':
    os.makedirs(CACHE, exist_ok=True)
    if sys.argv[1] == 'list':
        listing(sys.argv[2], sys.argv[3], dt.date.fromisoformat(sys.argv[4]), dt.date.fromisoformat(sys.argv[5]))
    elif sys.argv[1] == 'hist':
        hist_worker()
