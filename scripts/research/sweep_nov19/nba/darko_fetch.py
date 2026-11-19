# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""DARKO Time Machine snapshots (darko.app public MCP endpoint, read-only) for the sweep tests.

    python3 darko_fetch.py OUTDIR            # the pre-registered sample dates -> OUTDIR/<metric>_<date>.json

One snapshot = get_rankings paged by age band (50 rows a call; a band over 50 is split). {nba id: [name, team, value,
snapshot date]}. 1.2 s between calls. The history is retrospective (model_vintage null): research upper bound only."""
import json, os, sys, time, urllib.request

URL = 'https://www.darko.app/mcp'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
CALLS = [0]


def call(args):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'get_rankings', 'arguments': args}}).encode()
    for k in range(4):
        try:
            req = urllib.request.Request(URL, data=body, headers={'User-Agent': UA, 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
            t = urllib.request.urlopen(req, timeout=60).read().decode()
            CALLS[0] += 1; time.sleep(1.2)
            if 'data:' in t[:80]:
                t = next(l[5:] for l in t.splitlines() if l.startswith('data:'))
            r = json.loads(t)['result']
            return r.get('structuredContent') or json.loads(r['content'][0]['text'])
        except Exception as e:
            print(args, e, flush=True); time.sleep(10 * (k + 1))
    return None


def snapshot(metric, date, minutes_min=None):
    out = {}
    def band(lo, hi):
        a = {'metric': metric, 'asof': date, 'limit': 50, 'age_min': lo, 'age_max': hi}
        if minutes_min: a['minutes_min'] = minutes_min
        r = call(a)
        if not r: return
        if r.get('matching_players', 0) > 50 and hi - lo > 0.05:
            mid = round((lo + hi) / 2, 3)
            band(lo, mid); band(mid, hi)
            return
        for p in r.get('players', []):
            out[str(p['nba_id'])] = [p['player_name'], p.get('team_name'), p['value'], p.get('snapshot_date')]
    for lo, hi in ((17, 21), (21, 22.5), (22.5, 23.5), (23.5, 24.5), (24.5, 25.5), (25.5, 26.5), (26.5, 27.5), (27.5, 28.5), (28.5, 30), (30, 32), (32, 35), (35, 50)):
        band(lo, hi)
    return out


def dates(S):
    """sample dates of season S (end year): the first week (each player at his first pregame value), then three in-season"""
    if S == 2021: return ['2020-12-27', '2021-01-20', '2021-02-20', '2021-04-01']
    return [f'{S - 1}-11-01', f'{S - 1}-12-01', f'{S}-01-15', f'{S}-03-01']


def main():
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    jobs = []
    for S in range(2016, 2027):
        for i, d in enumerate(dates(S)):
            jobs.append(('dpm', d, None if i == 0 else 8))
    for S in (2024, 2025, 2026):
        for d in dates(S)[1:]:
            for m in ('x_minutes', 'x_pts_100', 'x_ast_100', 'x_drb_100', 'x_orb_100'):
                jobs.append((m, d, 8))
    for m, d, mm in jobs:
        fn = os.path.join(out, f'{m}_{d}.json')
        if os.path.exists(fn): continue
        s = snapshot(m, d, mm)
        json.dump(s, open(fn, 'w'))
        print(m, d, len(s), 'calls', CALLS[0], flush=True)


if __name__ == '__main__':
    main()
