#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Forward log of DARKO's current player ratings (darko.app public endpoint, read-only): one file a day in
scripts/data/darko_log/<YYYY-MM-DD>.json, {'asof', 'fetched', 'names': {nba id: name}, '<metric>': {nba id: value}}.

    python3 scripts/darko_log.py            # today's snapshot (skipped when today's file exists)
    python3 scripts/darko_log.py --test     # paging self-check on canned pages, no network

DARKO's own history is retrospective (no model vintage), so the only point-in-time record is one kept from now on.
Nothing on the site reads this log; it is scored once at season end (scripts/research/sweep_nov19/nba/PREREG.md).
One metric = the rankings paged by age band, 50 rows a call (a band over 50 is split), 1.2 s apart. Stdlib only."""
import datetime as dt, json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'data', 'darko_log')
URL = 'https://www.darko.app/mcp'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
METRICS = ('dpm', 'o_dpm', 'd_dpm')
BANDS = ((17, 21), (21, 22.5), (22.5, 23.5), (23.5, 24.5), (24.5, 25.5), (25.5, 26.5), (26.5, 27.5), (27.5, 28.5), (28.5, 30), (30, 32), (32, 35), (35, 50))


def call(args):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'get_rankings', 'arguments': args}}).encode()
    for k in range(4):
        try:
            req = urllib.request.Request(URL, data=body, headers={'User-Agent': UA, 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
            t = urllib.request.urlopen(req, timeout=60).read().decode()
            time.sleep(1.2)
            if 'data:' in t[:80]:
                t = next(l[5:] for l in t.splitlines() if l.startswith('data:'))
            r = json.loads(t)['result']
            return r.get('structuredContent') or json.loads(r['content'][0]['text'])
        except Exception as e:
            print('darko', args.get('metric'), e, flush=True); time.sleep(10 * (k + 1))
    return None


def snapshot(metric, get=call):
    """({nba id: value}, {nba id: name}, the dataset's own date) for the current rankings of one metric"""
    vals, names, asof = {}, {}, [None]

    def band(lo, hi):
        r = get({'metric': metric, 'limit': 50, 'age_min': lo, 'age_max': hi})
        if not r:
            return
        asof[0] = r.get('dataset_as_of') or asof[0]
        if r.get('matching_players', 0) > 50 and hi - lo > 0.05:
            mid = round((lo + hi) / 2, 3)
            band(lo, mid); band(mid, hi)
            return
        for p in r.get('players', []):
            vals[str(p['nba_id'])] = p['value']; names[str(p['nba_id'])] = p.get('player_name')
    for lo, hi in BANDS:
        band(lo, hi)
    return vals, names, asof[0]


def main():
    os.makedirs(OUT, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    fn = os.path.join(OUT, today + '.json')
    if os.path.exists(fn):
        return print('darko log: already have', today)
    out = {'fetched': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'names': {}}
    for m in METRICS:
        vals, names, asof = snapshot(m)
        if len(vals) < 200:
            return print('darko log: short snapshot for', m, len(vals), '- nothing written')
        out[m] = vals; out['names'].update(names); out['asof'] = asof
    with open(fn, 'w') as f:
        json.dump(out, f, separators=(',', ':'), sort_keys=True)
    print('darko log:', today, {m: len(out[m]) for m in METRICS}, 'dataset', out.get('asof'))


def _test():
    def fake(a):
        lo, hi = a['age_min'], a['age_max']
        pool = [(i, 17 + i * 0.05) for i in range(400)]
        hit = [(i, g) for i, g in pool if lo <= g <= hi]
        return {'matching_players': len(hit), 'dataset_as_of': '2026-01-01', 'players': [{'nba_id': i, 'player_name': f'P{i}', 'value': float(i)} for i, _ in hit[:50]]}
    v, n, a = snapshot('dpm', fake)
    assert len(v) == 400 and a == '2026-01-01' and v['7'] == 7.0, len(v)
    print('darko_log ok')


if __name__ == '__main__':
    _test() if '--test' in sys.argv else main()
